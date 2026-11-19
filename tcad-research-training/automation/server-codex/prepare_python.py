#!/usr/bin/env python3
"""Unpack a verified standalone CPython into this controller's own prefix.

The archive and SHA256 must be obtained from the official upstream release.
Offline only: no package manager, system Python change, Codex or solver startup.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import uuid


PREFIX = Path("/opt/tcad-autonomy")
PROBE = (
    "import hashlib,inspect,json,pathlib,sys;"
    "assert sys.version_info >= (3,11);"
    "assert hasattr(hashlib,'file_digest');"
    "assert 'newline' in inspect.signature(pathlib.Path.write_text).parameters;"
    "print(json.dumps({'version':sys.version.split()[0],"
    "'file_digest':True,'write_text_newline':True}))"
)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def check_target(staging, member):
    """Check against already extracted links, immediately before each write."""
    root = staging / "python"
    target = (staging / member.name).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Runtime archive destination escapes Python root")
    if target == root and not member.isdir():
        raise ValueError("Python root must be a directory")
    if member.issym() or member.islnk():
        base = (staging / member.name).parent if member.issym() else staging
        link = PurePosixPath(member.linkname)
        resolved = (base / member.linkname).resolve()
        if link.is_absolute() or (resolved != root and root not in resolved.parents):
            raise ValueError("Runtime archive link escapes Python root")


def prepare(archive_path, expected, version):
    if os.geteuid() != 0:
        raise RuntimeError("Run on the TCAD host as administrator")
    if not re.fullmatch(r"3\.(?:1[1-9]|[2-9][0-9])\.\d+", version):
        raise ValueError("An explicit CPython 3.11+ version is required")
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or sha(archive_path) != expected:
        raise ValueError("Runtime archive SHA256 mismatch")
    for path in (PREFIX, *PREFIX.parents):
        if path.is_symlink():
            raise RuntimeError("Refuse runtime installation through symlink")
    if subprocess.run(["systemctl", "is-active", "--quiet",
                       "tcad-autonomy.service"]).returncode == 0:
        raise RuntimeError("Do not replace runtime while controller is active")
    PREFIX.mkdir(mode=0o755, exist_ok=True)
    destination = PREFIX / ("python-" + version)
    current = PREFIX / "python"
    if destination.exists() or destination.is_symlink() or current.exists() or current.is_symlink():
        raise RuntimeError("A runtime already exists; inspect it instead of replacing it")
    staging = PREFIX / (".python-staging-" + uuid.uuid4().hex)
    staging.mkdir(mode=0o755)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > 20000 or sum(m.size for m in members) > 512 * 1024**2:
            raise ValueError("Unexpectedly large runtime")
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or not path.parts or path.parts[0] != "python"
                    or ".." in path.parts or member.name in names
                    or not (member.isfile() or member.isdir()
                            or member.issym() or member.islnk())):
                raise ValueError("Unsafe runtime archive member")
            names.add(member.name)
            check_target(staging, member)
            member.uid = member.gid = 0
            member.uname = member.gname = ""
            member.mode &= 0o755
        for member in members:
            check_target(staging, member)
            archive.extract(member, staging)
    for path in (staging / "python").rglob("*"):
        if path.is_symlink():
            resolved = path.resolve()
            boundary = staging / "python"
            if resolved != boundary and boundary not in resolved.parents:
                raise ValueError("Runtime link chain escapes Python root")
    executable = staging / "python/bin/python3"
    result = subprocess.run([str(executable), "-I", "-B", "-c", PROBE],
                            check=True, capture_output=True, text=True)
    probe = json.loads(result.stdout)
    if probe["version"] != version:
        raise ValueError("Runtime version differs from pinned archive")
    provenance = {
        "version": version, "archive_sha256": expected,
        "executable_sha256": sha(executable), "capabilities": probe,
        "system_python_replaced": False, "codex_started": False,
    }
    (staging / "python/tcad-runtime.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    os.rename(staging / "python", destination)
    staging.rmdir()
    current.symlink_to(destination, target_is_directory=True)
    subprocess.run(["restorecon", "-RF", str(destination), str(current)], check=True)
    return dict(provenance, executable=str(current / "bin/python3"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.archive, args.sha256, args.version), indent=2))
