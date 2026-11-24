"""Explicit, read-only raw-trace intake for the predictor snapshots.

The builder never invokes a runner, discovers files with glob, opens sealed
labels, invents a binary error label, or imports historical experiment code.
All physical units, time windows and matching metadata are caller-declared.
"""
from __future__ import annotations

import bisect
import copy
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
from typing import Any

from .data import (
    COHORTS, R06_COHORTS, SIMULATION_REVISIONS, DataError, LeakageError, Snapshot,
    _lineage, validate_r06_partition,
)


class IntakeError(ValueError):
    """An invalid intake or physical extraction contract."""


class LabelIsolationError(IntakeError):
    """A development input would consume a sealed record or file."""


_HASH = re.compile(r"^[0-9a-fA-F]{64}$")
_LEGACY = re.compile(r"(?:^v[1-4](?:$|[-_/])|dram-see-v[1-4](?:$|[-_/]))", re.I)
_HEADS = ("delta_voltage_V", "port_charge_fC", "margin_V", "upset")


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise IntakeError(f"{name}: boolean is not a physical number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise IntakeError(f"{name}: expected a finite number") from exc
    if not math.isfinite(result):
        raise IntakeError(f"{name}: nonfinite value")
    return result


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntakeError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(raw: bytes) -> Any:
    def invalid(value: str) -> None:
        raise IntakeError(f"Nonfinite JSON number: {value}")
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs,
                      parse_constant=invalid)


def _encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       allow_nan=False, indent=2) + "\n").encode("utf-8")


def _numeric_table(names: list[str], values: list[list[Any]]) -> tuple[list[str], list[dict[str, float]]]:
    if not names or any(not name for name in names) or len(set(names)) != len(names):
        raise IntakeError("Empty or duplicate waveform columns")
    if not values:
        raise IntakeError("Empty waveform")
    rows = []
    for i, row in enumerate(values, 1):
        if len(row) != len(names):
            raise IntakeError(f"Waveform row {i} has the wrong number of columns")
        rows.append({name: _finite(value, f"row {i}/{name}") for name, value in zip(names, row)})
    return names, rows


def parse_csv(text: str) -> tuple[list[str], list[dict[str, float]]]:
    """Parse an explicitly numeric CSV waveform; never infer column units."""
    try:
        rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff")), strict=True))
    except csv.Error as exc:
        raise IntakeError(f"Malformed CSV: {exc}") from exc
    if not rows:
        raise IntakeError("Empty waveform")
    return _numeric_table(rows[0], rows[1:])


def parse_dfise(text: str) -> tuple[list[str], list[dict[str, float]]]:
    """Parse DF-ISE datasets/Data blocks, with no legacy experiment semantics."""
    names_blocks = re.findall(r"\bdatasets\s*=\s*\[(.*?)\]", text, re.S)
    data_blocks = re.findall(r"\bData\s*\{([^{}]*)\}", text, re.S)
    if len(names_blocks) != 1 or len(data_blocks) != 1:
        raise IntakeError("Expected one complete DF-ISE datasets and Data block")
    names = re.findall(r'"([^"]+)"', names_blocks[0])
    tokens = data_blocks[0].split()
    if not names or len(tokens) % len(names):
        raise IntakeError("Malformed or truncated DF-ISE values")
    values = [[token.replace("D", "E").replace("d", "e") for token in tokens[i:i + len(names)]]
              for i in range(0, len(tokens), len(names))]
    return _numeric_table(names, values)


def _relative(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise IntakeError("Expected an explicit relative source path")
    candidate = Path(value)
    if candidate.is_absolute() or candidate.drive:
        raise IntakeError("Intake source paths must be relative to the intake directory")
    path = (root / candidate).resolve()
    if not path.is_relative_to(root.resolve()):
        raise IntakeError(f"Source path escapes intake directory: {value}")
    return path


def _sealed_paths(root: Path, value: Any) -> set[Path]:
    """Resolve declared references only; do not open even a sealed manifest."""
    paths: set[Path] = set()
    if isinstance(value, str):
        paths.add(_relative(root, value))
    elif isinstance(value, dict):
        for item in value.values():
            paths.update(_sealed_paths(root, item))
    elif isinstance(value, list):
        for item in value:
            paths.update(_sealed_paths(root, item))
    return paths


class _Sources:
    def __init__(self, root: Path, declared_hashes: dict[str, str], sealed: set[Path]):
        self.root = root
        self.declared_hashes = declared_hashes
        self.sealed = sealed
        self.reads: dict[str, dict[str, str]] = {}

    def read(self, relative: str, expected: str | None = None) -> bytes:
        path = _relative(self.root, relative)
        if any(path == blocked or path.is_relative_to(blocked) for blocked in self.sealed):
            raise LabelIsolationError(f"Refusing to read sealed input: {relative}")
        expected_hashes = [value for value in (expected, self.declared_hashes.get(relative))
                           if value is not None]
        for value in expected_hashes:
            if not isinstance(value, str) or not _HASH.fullmatch(value):
                raise IntakeError(f"Invalid SHA256 declaration: {relative}")
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        self.reads[relative] = {"path": relative, "sha256": actual}
        if any(actual != value.lower() for value in expected_hashes):
            raise IntakeError(f"SHA256 mismatch: {relative}")
        return raw

    def rows(self, relative: str) -> list[dict[str, Any]]:
        raw = self.read(relative)
        rows = []
        for line_number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            item = _json(line.encode("utf-8"))
            if not isinstance(item, dict):
                raise IntakeError(f"{relative}:{line_number}: JSONL row must be an object")
            _reject_legacy(item)
            rows.append(item)
        return rows


def _reject_legacy(value: dict[str, Any]) -> None:
    for key in ("generation", "schema", "domain", "model_id"):
        field = value.get(key)
        if isinstance(field, str) and _LEGACY.search(field):
            raise IntakeError(f"Historical {key} cannot be relabeled for predictor intake: {field}")


def _require_label_free(value: Any) -> None:
    """Metadata may contain source physics but never a response supervision head."""
    if isinstance(value, dict):
        if set(value) & {"labels", "masks", *_HEADS}:
            raise LabelIsolationError("Condition/primary metadata contains supervision labels")
        for item in value.values():
            _require_label_free(item)
    elif isinstance(value, list):
        for item in value:
            _require_label_free(item)


def _strict_times(values: Any, name: str, minimum: int = 1) -> list[float]:
    if not isinstance(values, list) or len(values) < minimum:
        raise IntakeError(f"{name}: need at least {minimum} time values")
    result = [_finite(value, name) for value in values]
    if any(b <= a for a, b in zip(result, result[1:])):
        raise IntakeError(f"{name}: time values must be strictly increasing")
    return result


def _read_trace(spec: Any, sources: _Sources) -> dict[str, list[float]]:
    if not isinstance(spec, dict):
        raise IntakeError("Missing explicit trace specification")
    if not isinstance(spec.get("sha256"), str) or not _HASH.fullmatch(spec["sha256"]):
        raise IntakeError("Every raw trace must declare its own SHA256")
    time_scale = {"s": 1e9, "ns": 1.0}
    voltage_scale = {"V": 1.0, "mV": 1e-3}
    current_scale = {"A": 1.0, "uA": 1e-6}
    if spec.get("time_unit") not in time_scale or spec.get("voltage_unit") not in voltage_scale:
        raise IntakeError("Unsupported or missing waveform time/voltage unit")
    current_column = spec.get("current_column")
    if current_column and spec.get("current_unit") not in current_scale:
        raise IntakeError("Unsupported or missing waveform current unit")
    raw = sources.read(spec.get("path"), spec["sha256"])
    parser = {"csv": parse_csv, "dfise": parse_dfise}.get(spec.get("format"))
    if parser is None:
        raise IntakeError("Unsupported waveform format")
    names, rows = parser(raw.decode("utf-8-sig"))
    time_column, voltage_column = spec.get("time_column"), spec.get("voltage_column")
    if time_column not in names or voltage_column not in names or (current_column and current_column not in names):
        raise IntakeError("Declared waveform column is absent")
    times = _strict_times([row[time_column] * time_scale[spec["time_unit"]] for row in rows],
                          "raw waveform time", minimum=2)
    result = {
        "time_ns": times,
        "voltage_V": [row[voltage_column] * voltage_scale[spec["voltage_unit"]] for row in rows],
    }
    if current_column:
        result["current_A"] = [row[current_column] * current_scale[spec["current_unit"]] for row in rows]
    return result


def _sample(times: list[float], values: list[float], target: float) -> float:
    if target < times[0] or target > times[-1]:
        raise IntakeError("Requested window exceeds actual waveform coverage; no extrapolation")
    right = bisect.bisect_left(times, target)
    if right < len(times) and times[right] == target:
        return values[right]
    left = right - 1
    weight = (target - times[left]) / (times[right] - times[left])
    return (1.0 - weight) * values[left] + weight * values[right]


def extract_paired_trace(
    response: dict[str, Any],
    condition: dict[str, Any],
    sample_times_ns: list[float],
    root: str | Path,
    *,
    sources: _Sources | None = None,
    deck_timing_version: str | None = None,
) -> dict[str, Any]:
    """Derive signed voltage perturbation and, when defined, port charge only.

    Signal/control grids may differ. Current difference is integrated on the
    union of their breakpoints and explicit window boundaries, in A * ns * 1e6
    = fC. Relative sample/window times are shifted by injection_time_ns.
    """
    if condition.get("cohort") != "development":
        raise LabelIsolationError("Trace extraction cannot read sealed conditions")
    target_times = _strict_times(sample_times_ns, "sample_times_ns")
    state = response.get("state")
    if isinstance(state, bool) or state not in (0, 1):
        raise IntakeError("Response state must be 0 or 1")
    protocol = response.get("protocol_id", condition.get("protocol_id",
                            condition.get("categories", {}).get("protocol_id", deck_timing_version)))
    matched = response.get("matching_control")
    profile = condition.get("profile_id")
    if (not isinstance(protocol, str) or not protocol or not isinstance(matched, dict)
            or not isinstance(profile, str) or not profile.strip()):
        raise IntakeError("Explicit signal/control profile, state and protocol matching is required")
    expected = {"profile_id": profile, "state": state, "protocol_id": protocol}
    if deck_timing_version is not None:
        expected["deck_timing_version"] = deck_timing_version
    if any(matched.get(key) != value for key, value in expected.items()) or isinstance(matched.get("state"), bool):
        raise IntakeError("Signal/control profile, state, protocol or deck timing differs")
    origin_key = "source_time_ns" if deck_timing_version is not None else "injection_time_ns"
    origin = _finite(response.get(origin_key), origin_key)
    if deck_timing_version is not None and "injection_time_ns" in response:
        if _finite(response["injection_time_ns"], "injection_time_ns") != origin:
            raise IntakeError("injection_time_ns disagrees with the r0.6 source_time_ns")
    source_reader = sources or _Sources(Path(root).resolve(), {}, set())
    signal = _read_trace(response.get("trace"), source_reader)
    control = _read_trace(response.get("control_trace"), source_reader)
    voltage = [
        _finite(_sample(signal["time_ns"], signal["voltage_V"], origin + time)
                - _sample(control["time_ns"], control["voltage_V"], origin + time),
                "delta_voltage_V")
        for time in target_times
    ]
    result: dict[str, Any] = {"delta_voltage_V": voltage, "port_charge_fC": None}
    has_current = "current_A" in signal and "current_A" in control
    if response.get("charge_window_ns") is not None:
        if not has_current:
            raise IntakeError("Charge integration needs both declared current columns")
        window = _strict_times(response["charge_window_ns"], "charge_window_ns", minimum=2)
        if len(window) != 2:
            raise IntakeError("charge_window_ns must have exactly two bounds")
        sign = _finite(response.get("port_current_sign"), "port_current_sign")
        if sign not in (-1.0, 1.0):
            raise IntakeError("port_current_sign must be +1 or -1")
        lo, hi = (origin + value for value in window)
        knots = sorted({lo, hi} | {time for trace in (signal, control) for time in trace["time_ns"] if lo < time < hi})
        currents = [
            _sample(signal["time_ns"], signal["current_A"], time)
            - _sample(control["time_ns"], control["current_A"], time)
            for time in knots
        ]
        result["port_charge_fC"] = _finite(sign * math.fsum(
            (b - a) * (ia * 0.5 + ib * 0.5)
            for a, b, ia, ib in zip(knots, knots[1:], currents, currents[1:])
        ) * 1e6, "port_charge_fC")
    return result


def _index(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise IntakeError(f"Missing or duplicate {key}")
        result[identity] = row
    return result


def _failed(row: dict[str, Any], reason: str) -> dict[str, Any]:
    output = copy.deepcopy(row)
    output["status"] = "failed"
    output["labels"] = {key: None for key in _HEADS}
    output["masks"] = {key: False for key in _HEADS}
    output["extraction_error"] = reason
    return output


def build_snapshot(intake_manifest_path: str | Path, output_dir: str | Path) -> Path:
    """Build an immutable development snapshot from explicitly named inputs.

    Individual extraction failures retain a failed response with masked labels.
    Metadata/partition ambiguity and attempts to open sealed files are fatal.
    Existing snapshots and source files are never overwritten.
    """
    intake_path = Path(intake_manifest_path).resolve()
    root = intake_path.parent
    destination = Path(output_dir).resolve()
    if destination.exists():
        raise IntakeError("Snapshot output must be a new directory")
    raw_manifest = intake_path.read_bytes()
    manifest = _json(raw_manifest)
    if not isinstance(manifest, dict):
        raise IntakeError("Intake manifest must be an object")
    _reject_legacy(manifest)
    if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or manifest.get("plan_id") != "dram-se-ddr5-lpddr5"
            or manifest.get("simulation_revision") not in SIMULATION_REVISIONS
            or manifest.get("kind") not in ("native_simulation", "synthetic_fixture")):
        raise IntakeError("Expected an explicit r0.4 or r0.6 snapshot identity and kind")
    r06 = manifest["simulation_revision"] == "0.6"
    development = manifest.get("development")
    if not isinstance(development, dict):
        raise IntakeError("Missing development tables")
    declared_hashes = manifest.get("files_sha256", {})
    if not isinstance(declared_hashes, dict):
        raise IntakeError("files_sha256 must map relative names to hashes")
    sources = _Sources(root, declared_hashes, _sealed_paths(root, manifest.get("sealed", {})))
    conditions = sources.rows(manifest.get("conditions_file"))
    primaries = sources.rows(manifest.get("primaries_file"))
    _require_label_free(conditions)
    _require_label_free(primaries)
    condition_by_id = _index(conditions, "condition_id")
    primary_by_id = _index(primaries, "primary_id")
    for condition in conditions:
        if (not isinstance(condition.get("profile_id"), str)
                or not condition["profile_id"].strip()
                or condition.get("cohort") not in (R06_COHORTS if r06 else COHORTS)):
            raise IntakeError("Condition requires an explicit profile_id and cohort")
        if r06:
            try:
                validate_r06_partition(condition)
            except LeakageError as exc:
                raise LabelIsolationError(str(exc)) from exc
            except DataError as exc:
                raise IntakeError(str(exc)) from exc
    for primary in primaries:
        if primary.get("condition_id") not in condition_by_id:
            raise IntakeError("Primary references unknown condition")
    responses = sources.rows(development.get("responses_file"))
    controls = sources.rows(development.get("controls_file"))
    counts = sources.rows(development["counts_file"]) if development.get("counts_file") else []
    _index(responses, "response_id")
    _index(controls, "control_id")
    _index(counts, "count_id")
    dev_profiles = {row["profile_id"] for row in conditions if row.get("cohort") == "development"}
    # Validate every cohort before any raw waveform is opened.
    for row in responses:
        primary = primary_by_id.get(row.get("primary_id"))
        if primary is None:
            raise IntakeError("Response references unknown primary")
        condition = condition_by_id[primary["condition_id"]]
        if condition.get("cohort") != "development":
            raise LabelIsolationError("Development response references a sealed condition")
        if r06 and row.get("radiation_id") != condition["radiation_id"]:
            raise LabelIsolationError("r0.6 response radiation_id differs from the condition")
        if r06 and (row.get("deck_timing_version") != manifest.get("deck_timing_version")
                    or row.get("source_time_ns") != manifest.get("source_time_ns")):
            raise IntakeError("r0.6 response timing differs from the snapshot")
    for row in controls:
        if row.get("cohort") != "development" or row.get("profile_id") not in dev_profiles:
            raise LabelIsolationError("Development control references a sealed/unknown profile")
    for row in counts:
        condition = condition_by_id.get(row.get("condition_id"))
        if condition is None or condition.get("cohort") != "development":
            raise LabelIsolationError("Development count references a sealed/unknown condition")
    sample_times = manifest.get("sample_times_ns")
    if sample_times is not None:
        sample_times = _strict_times(sample_times, "sample_times_ns")
    omissions = []
    output_responses = []
    for row in responses:
        result = copy.deepcopy(row)
        if r06 and row.get("status") == "unresolved":
            omissions.append({"response_id": row["response_id"], "reason": "unresolved_upset"})
        elif row.get("status") != "valid":
            result["labels"] = {key: None for key in _HEADS}
            result["masks"] = {key: False for key in _HEADS}
            omissions.append({"response_id": row["response_id"], "reason": "nonvalid_response_status"})
        elif "trace" in row or "control_trace" in row:
            condition = condition_by_id[primary_by_id[row["primary_id"]]["condition_id"]]
            try:
                labels = extract_paired_trace(row, condition, sample_times, root, sources=sources,
                                              deck_timing_version=manifest.get("deck_timing_version") if r06 else None)
                for key in ("labels", "masks"):
                    if result.get(key) is None:
                        result[key] = {}
                    if not isinstance(result[key], dict):
                        raise IntakeError(f"Response {key} must be an object or null")
                for key, value in labels.items():
                    permitted = result["masks"].get(key, True)
                    if not isinstance(permitted, bool):
                        raise IntakeError(f"Response {key} mask must be boolean")
                    result["labels"][key] = value
                    result["masks"][key] = value is not None and permitted
                # Other labels are retained only if explicitly supplied, never derived here.
                result["extraction"] = {
                    "method": "piecewise_linear_matched_delta_and_union_grid_trapezoid",
                    "time_reference": "sample_and_charge_windows_relative_to_injection",
                    "port_charge_definition": "signed_integral_signal_minus_control_current",
                    "source_hash_verified": True,
                    "matching_control": copy.deepcopy(row["matching_control"]),
                }
            except LabelIsolationError:
                raise
            except (IntakeError, OSError, UnicodeError, OverflowError) as exc:
                result = _failed(row, str(exc))
                if r06:
                    result["statistics_eligible"] = False
                omissions.append({"response_id": row["response_id"], "reason": str(exc)})
        output_responses.append(result)
    output_controls = []
    for row in controls:
        result = copy.deepcopy(row)
        if "trace" in row:
            try:
                trace = _read_trace(row["trace"], sources)
                origin = _finite(row.get("time_origin_ns", 0.0), "control time_origin_ns")
                result["time_ns"] = [value - origin for value in trace["time_ns"]]
                result["voltage_V"] = trace["voltage_V"]
                result["source_hash_verified"] = True
            except LabelIsolationError:
                raise
            except (IntakeError, OSError, UnicodeError) as exc:
                result["mechanism_validated"] = False
                result["time_ns"], result["voltage_V"] = [], []
                result["extraction_error"] = str(exc)
                omissions.append({"control_id": row["control_id"], "reason": str(exc)})
        output_controls.append(result)
    tables = {
        "conditions.jsonl": conditions,
        "primaries.jsonl": primaries,
        "development.responses.jsonl": output_responses,
        "development.controls.jsonl": output_controls,
        "development.counts.jsonl": counts,
    }
    payloads = {
        name: b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
                       for row in rows)
        for name, rows in tables.items()
    }
    output_manifest = copy.deepcopy(manifest)
    output_manifest.update({
        "conditions_file": "conditions.jsonl",
        "primaries_file": "primaries.jsonl",
        "development": {
            "responses_file": "development.responses.jsonl",
            "controls_file": "development.controls.jsonl",
            "counts_file": "development.counts.jsonl",
        },
        "sealed": {},
        "sealed_external": {
            "intake_manifest": str(intake_path),
            "references": copy.deepcopy(manifest.get("sealed", {})),
            "accessed": False,
        },
        "files_sha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in payloads.items()},
        "ingestion": {
            "version": 1,
            "intake_manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
            "read_sources": list(sources.reads.values()),
            "omissions": omissions,
            "derived_upset_or_margin": False,
            "training_started": False,
        },
    })
    if sample_times is not None:
        output_manifest["sample_times_ns"] = sample_times
    if r06:
        try:
            active, superseded = _lineage(output_responses, r06=True)
            Snapshot(destination, output_manifest, condition_by_id, primary_by_id,
                     active, output_controls, counts, superseded, ()).validate()
        except DataError as exc:
            raise IntakeError(str(exc)) from exc
    destination.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        with (destination / name).open("xb") as stream:
            stream.write(raw)
    manifest_path = destination / "manifest.json"
    with manifest_path.open("xb") as stream:
        stream.write(_encoded(output_manifest))
    return manifest_path
