"""Read a small public parameter whitelist from frozen host-side inputs."""
from __future__ import annotations

import hashlib
import json
import math
import re
import tarfile
from functools import lru_cache
from pathlib import Path


def inside(value, root):
    if not isinstance(value, (str, Path)) or not str(value):
        return None
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    return path


def small_bytes(path, limit):
    if not path or not path.is_file() or path.stat().st_size > limit:
        return None
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    return data if len(data) <= limit else None


def numeric(value):
    return type(value) in (float, int) and math.isfinite(value)


@lru_cache(maxsize=32)
def request_parameters(path, expected_sha, mtime_ns, size):
    # Only seek/read a small regular member. Never extract anything to disk.
    with tarfile.open(path, "r:") as archive:
        member = archive.getmember("request.json")
        if not member.isfile() or not 0 <= member.size <= 65536:
            return {}
        data = archive.extractfile(member).read(65537)
    if hashlib.sha256(data).hexdigest() != expected_sha:
        return {}
    request = json.loads(data)
    if not isinstance(request, dict):
        return {}
    fields = {"incident_energy_MeV": "energy_MeV", "theta_deg": "theta_deg", "phi_deg": "phi_deg"}
    return {public: request[key] for key, public in fields.items() if numeric(request.get(key))}


def read_input_parameters(manifest, workspace_root=Path("/home/tcad/course-workspace")):
    result = {}
    try:
        project = inside(manifest.get("project_directory"), Path(workspace_root))
        if project is None:
            return result
        raw = small_bytes(project / "SHA256SUMS.json", 262144)
        sums = json.loads(raw) if raw else {}
        if not isinstance(sums, dict):
            return result

        def verified(name, limit=262144):
            path = inside(project / name, project)
            data = small_bytes(path, limit)
            return data if data is not None and hashlib.sha256(data).hexdigest() == sums.get(name) else None

        deck = verified("device.cmd", 2097152)
        if deck:
            lines = [line.split("//", 1)[0] for line in deck.decode("utf-8").splitlines()
                     if not line.lstrip().startswith(("*", "#"))]
            values = set(float(value) for value in re.findall(
                r"\bTemperature\s*=\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)", "\n".join(lines)))
            if len(values) == 1:
                value = next(iter(values))
                if math.isfinite(value) and value > 0:
                    result["temperature_K"] = value
        raw = verified("provenance.json")
        provenance = json.loads(raw) if raw else {}
        if isinstance(provenance, dict) and provenance.get("stored_pattern") in ("00", "11"):
            result["stored_bit"] = int(provenance["stored_pattern"][0])
        raw = verified("native-event-manifest.json")
        native = json.loads(raw) if raw else {}
        source = native.get("source", {}) if isinstance(native, dict) else {}
        path = inside(source.get("archive"), Path(workspace_root))
        member = source.get("native_members", {}).get("request.json", {})
        expected = member.get("sha256")
        if path and path.is_file() and isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected):
            info = path.stat()
            result.update(request_parameters(str(path), expected, info.st_mtime_ns, info.st_size))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, tarfile.TarError):
        # Optional metadata cannot turn a missing parameter into a guessed value.
        pass
    return result
