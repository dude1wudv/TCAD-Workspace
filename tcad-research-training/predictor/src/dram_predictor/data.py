"""Read-only, provenance-aware development snapshots; sealed labels are never opened."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

COHORTS = {"development", "new_combination", "high_energy", "device_extrapolation"}
R06_COHORTS = {"development", "radiation_holdout", "profile_holdout"}
SIMULATION_REVISIONS = {"0.4", "0.6"}
R06_PROBABILITY_SAMPLING = {"simple_random", "stratified_pi"}
R06_PARTICLE_SAMPLING = R06_PROBABILITY_SAMPLING | {"threshold_scaled", "active_learning"}
DATA_STAGES = {"model_ready", "transport_only"}
DEVICE_FEATURES = (
    "gate_length_nm", "device_length_nm", "device_width_nm", "fin_width_nm",
    "oxide_thickness_nm", "junction_depth_nm", "acceptor_scale", "donor_scale",
    "acceptor_cm3", "donor_cm3", "capacitance_fF", "bias_voltage_V", "temperature_K",
)
F_FEATURES = DEVICE_FEATURES + ("incident_energy_MeV", "direction_x", "direction_y", "direction_z")
SOURCE_FEATURES = (
    "generated_charge_fC", "deposited_energy_MeV", "source_duration_ns",
    "hit_x_nm", "hit_y_nm", "hit_z_nm", "secondary_count",
    "spread_x_nm", "spread_y_nm", "spread_z_nm",
)


class DataError(ValueError):
    pass


class LeakageError(DataError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DataError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_json,
                      parse_constant=lambda x: (_ for _ in ()).throw(DataError(f"Nonfinite JSON: {x}")))


def read_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8-sig") as f:
        for number, line in enumerate(f, 1):
            if line.strip():
                item = json.loads(line, object_pairs_hook=_unique_json,
                                  parse_constant=lambda x: (_ for _ in ()).throw(
                    DataError(f"{path.name}:{number}: nonfinite JSON {x}")))
                if not isinstance(item, dict):
                    raise DataError(f"{path.name}:{number}: expected object")
                records.append(item)
    return records


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def _unique(rows: list[dict], key: str) -> dict[str, dict]:
    result = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or not value:
            raise DataError(f"Missing/nonstring {key}")
        if value in result:
            raise DataError(f"Duplicate {key}: {value}")
        result[value] = row
    return result


def _finite(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DataError(f"{label}: finite numeric value required")
    if positive and value <= 0:
        raise DataError(f"{label}: positive value required")


def _sha256(value, label):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in value)):
        raise DataError(f"{label}: explicit SHA256 required")


def _transport_metadata(value):
    """Keep raw provenance, but never hide supervision in transport metadata."""
    if isinstance(value, dict):
        if set(value) & {"labels", "masks", "delta_voltage_V", "port_charge_fC", "margin_V", "upset"}:
            raise LeakageError("transport_only metadata cannot contain response labels or masks")
        for item in value.values():
            _transport_metadata(item)
    elif isinstance(value, list):
        for item in value:
            _transport_metadata(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise DataError("transport_only metadata must contain finite numbers")


def _lineage(rows: list[dict], *, r06=False) -> tuple[list[dict], list[dict]]:
    """Replacement must be explicit and keep the original physical sample identity."""
    by_id = _unique(rows, "response_id")
    superseded = set()
    identity = ("primary_id", "state", "bit_id")
    design = ("case_id", "scale_factor", "source_shape_id", "source_time_ns", "deck_timing_version",
              "selection_mechanism", "inclusion_probability", "radiation_id")
    for row in rows:
        if r06:
            _finite(row.get("scale_factor"), "scale_factor", positive=True)
        previous = row.get("supersedes")
        if previous:
            if previous not in by_id:
                raise DataError(f"Unknown superseded response: {previous}")
            if previous in superseded:
                raise DataError(f"Conflicting repair branches for {previous}")
            old = by_id[previous]
            if any(old.get(k) != row.get(k) for k in identity + (design if r06 else ())):
                raise LeakageError("Repair changes primary/state/bit identity or frozen sampling design")
            seen = {row["response_id"]}
            while previous:
                if previous in seen:
                    raise DataError("Cyclic repair lineage")
                seen.add(previous)
                previous = by_id[previous].get("supersedes")
            superseded.add(row["supersedes"])
    active = [r for r in rows if r["response_id"] not in superseded]
    keys = [(r.get("primary_id"), r.get("state"), str(r.get("bit_id", "0")),
             r.get("scale_factor") if r06 else None) for r in active]
    if len(keys) != len(set(keys)):
        raise DataError("Multiple active labels for one primary/state/bit/scale; declare supersedes")
    return active, [r for r in rows if r["response_id"] in superseded]


def validate_r06_partition(condition):
    cohort = condition.get("cohort")
    if cohort not in R06_COHORTS:
        raise DataError(f"Unknown r0.6 cohort: {cohort}")
    radiation = condition.get("radiation_id")
    holdout_radiation = radiation in {"C2", "C3"}
    if not holdout_radiation and radiation not in {"G0", "G1", "G2", "G3", "G4", "G5", "C0", "C1"}:
        raise DataError("r0.6 condition requires a radiation_id from the frozen design")
    holdout = {"development": None, "radiation_holdout": "radiation", "profile_holdout": "profile"}[cohort]
    held_profile = condition.get("profile_id") in {"H0-long-channel", "H1-lhs-holdout-a", "H2-lhs-holdout-b"}
    if (condition.get("split", cohort) != cohort or condition.get("holdout", holdout) != holdout
            or holdout_radiation != (cohort == "radiation_holdout")
            or (held_profile and cohort != "profile_holdout")):
        raise LeakageError("r0.6 split/holdout disagrees with the condition cohort or radiation pool")


def _validate_r06_condition(condition):
    validate_r06_partition(condition)
    features = condition["features"]
    max_energy = 200 if condition["cohort"] == "radiation_holdout" else 120
    max_length = 16.8 if condition["cohort"] == "profile_holdout" else 15.4
    if not (1 <= features["incident_energy_MeV"] <= max_energy
            and 11.2 <= features["gate_length_nm"] <= max_length):
        raise LeakageError("r0.6 condition is outside its frozen energy/gate length bounds")


def _validate_r06_evidence(row, manifest, *, control=False):
    if type(row.get("state")) is not int or row["state"] not in (0, 1):
        raise DataError("r0.6 evidence requires state 0 or 1")
    if not isinstance(row.get("run_id"), str) or not row["run_id"].strip():
        raise DataError("r0.6 evidence requires its original run_id")
    _sha256(row.get("source_hash"), "source_hash")
    inputs = row.get("input_sha256")
    if not isinstance(inputs, dict) or not inputs or any(not name for name in inputs):
        raise DataError("r0.6 evidence requires the original input_sha256 file map")
    for value in inputs.values():
        _sha256(value, "input_sha256 value")
    if row.get("deck_timing_version") != manifest["deck_timing_version"]:
        raise DataError("r0.6 evidence deck_timing_version differs from the snapshot")
    if control:
        if (row.get("selection_mechanism") != "no_particle_control"
                or "source_time_ns" not in row or row["source_time_ns"] is not None
                or row.get("statistics_eligible", False) is not False):
            raise DataError("r0.6 Z controls require no_particle_control, null source time and no statistics eligibility")
    else:
        _finite(row.get("source_time_ns"), "response source_time_ns", positive=True)
        if row["source_time_ns"] != manifest["source_time_ns"]:
            raise DataError("r0.6 response source_time_ns differs from the snapshot")


def _validate_r06_response(row, condition, primary):
    if row.get("radiation_id") != condition["radiation_id"]:
        raise DataError("r0.6 response radiation_id differs from the condition")
    if not isinstance(row.get("source_shape_id"), str) or not row["source_shape_id"].strip():
        raise DataError("r0.6 response requires source_shape_id")
    mechanism = row.get("selection_mechanism")
    if mechanism not in R06_PARTICLE_SAMPLING:
        raise DataError("r0.6 particle response requires a supported selection_mechanism")
    scale = row["scale_factor"]
    if (mechanism == "threshold_scaled" and scale <= 1) or (mechanism != "threshold_scaled" and scale != 1):
        raise DataError("r0.6 threshold scale must exceed one; natural and active-learning scale must be one")
    probability = row.get("inclusion_probability")
    if probability is not None:
        _finite(probability, "inclusion_probability", positive=True)
        if probability > 1 or mechanism not in R06_PROBABILITY_SAMPLING:
            raise DataError("inclusion_probability must be in (0,1] for a natural draw")
    labels = row.get("labels")
    masks = row.get("masks")
    if labels is not None and not isinstance(labels, dict):
        raise DataError("r0.6 labels must be an object or null")
    if masks is not None and (not isinstance(masks, dict) or any(type(mask) is not bool for mask in masks.values())):
        raise DataError("r0.6 masks must be booleans")
    for field in ("port_charge_fC", "margin_V", "upset"):
        value = (labels or {}).get(field)
        if value is not None:
            _finite(value, "label." + field)
    if any(has_supervised_head(row, head) for head in
           ("delta_voltage_V", "port_charge_fC", "margin_V", "upset")):
        if not has_mapped_source(primary):
            raise DataError("r0.6 supervised response requires explicit mapped source features")
    eligible = row.get("statistics_eligible")
    if type(eligible) is not bool:
        raise DataError("r0.6 response statistics_eligible must be explicit")
    if eligible and (probability is None or primary["pool_member"] is not True
                     or not head_valid(row, "upset") or (labels or {}).get("upset") not in (0, 1)):
        raise DataError("r0.6 statistics eligibility requires a natural pool draw and valid accepted upset")


def has_mapped_source(primary):
    features = primary.get("source_features") or {}
    return (type(primary.get("source_off")) is bool
            and all(features.get(key) is not None for key in ("generated_charge_fC", "source_duration_ns")))


@dataclass
class Snapshot:
    root: Path
    manifest: dict
    conditions: dict[str, dict]
    primaries: dict[str, dict]
    responses: list[dict]
    controls: list[dict]
    counts: list[dict]
    superseded: list[dict]
    read_files: tuple[str, ...]

    @classmethod
    def load(cls, manifest_path: str | Path) -> "Snapshot":
        path = Path(manifest_path).resolve()
        manifest = read_json(path)
        if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
                or manifest.get("plan_id") != "dram-se-ddr5-lpddr5"
                or manifest.get("simulation_revision") not in SIMULATION_REVISIONS):
            raise DataError("Expected an explicit r0.4 or r0.6 snapshot. Unsupported historical v3/v4 data.")
        r06 = manifest["simulation_revision"] == "0.6"
        if manifest.get("kind") not in {"native_simulation", "synthetic_fixture"}:
            raise DataError("Snapshot kind must be native_simulation or synthetic_fixture")
        if manifest.get("data_stage", "model_ready") not in DATA_STAGES:
            raise DataError("Unknown snapshot data_stage")
        root = path.parent
        opened = [str(path)]
        sealed = manifest.get("sealed", {})
        sealed_paths = {str((root / x).resolve()) for x in sealed.values() if isinstance(x, str)}

        def table(name: str | None, required=True):
            if not name:
                if required:
                    raise DataError("Missing required table path")
                return []
            resolved = (root / name).resolve()
            if not resolved.is_relative_to(root):
                raise DataError(f"Table escapes snapshot directory: {name}")
            if any(resolved == Path(p) or resolved.is_relative_to(Path(p)) for p in sealed_paths):
                raise LeakageError("A development table aliases a sealed label path")
            # Hard links/symlinks cannot silently alias an existing sealed file.
            for candidate in sealed_paths:
                if Path(candidate).exists() and resolved.exists() and resolved.samefile(candidate):
                    raise LeakageError("Development and sealed table are the same file")
            expected = manifest.get("files_sha256", {}).get(name)
            if r06 or manifest.get("data_stage") == "transport_only":
                _sha256(expected, f"files_sha256[{name}]")
            if expected and file_hash(resolved) != expected:
                raise DataError(f"Hash mismatch: {name}")
            opened.append(str(resolved))
            return read_jsonl(resolved)

        conditions = _unique(table(manifest.get("conditions_file")), "condition_id")
        if r06:
            for condition in conditions.values():
                validate_r06_partition(condition)
        primaries = _unique(table(manifest.get("primaries_file")), "primary_id")
        dev = manifest.get("development", {})
        rows = table(dev.get("responses_file"), required=r06)
        controls = table(dev.get("controls_file"), required=r06)
        counts = table(dev.get("counts_file"), required=r06)
        active, old = _lineage(rows, r06=r06)
        result = cls(root, manifest, conditions, primaries, active, controls, counts, old, tuple(opened))
        result.validate()
        return result

    @property
    def times(self):
        return self.manifest.get("sample_times_ns", [])

    @property
    def simulation_revision(self):
        return self.manifest["simulation_revision"]

    @property
    def data_stage(self):
        return self.manifest.get("data_stage", "model_ready")

    def require_model_stage(self):
        if self.data_stage != "model_ready":
            raise DataError("transport_only snapshot cannot enter model training or a training View")

    @property
    def development_conditions(self) -> set[str]:
        return {k for k, c in self.conditions.items() if c["cohort"] == "development"}

    def validate(self):
        if self.data_stage not in DATA_STAGES:
            raise DataError("Unknown snapshot data_stage")
        transport_only = self.data_stage == "transport_only"
        r06 = self.simulation_revision == "0.6"
        if r06 and (not transport_only or {"deck_timing_version", "source_time_ns"} & self.manifest.keys()):
            version = self.manifest.get("deck_timing_version")
            if not isinstance(version, str) or not version.strip():
                raise DataError("r0.6 requires an explicit deck_timing_version")
            _finite(self.manifest.get("source_time_ns"), "source_time_ns", positive=True)
            if not 18.2 <= self.manifest["source_time_ns"] <= 30.:
                raise DataError("r0.6 source_time_ns must fall inside the frozen hold window")
        if r06 and self.responses and (not isinstance(self.times, list) or not self.times):
            raise DataError("r0.6 responses require a frozen sample_times_ns grid")
        if transport_only:
            if self.responses or self.superseded or self.controls or self.counts:
                raise LeakageError("transport_only requires empty response, control and count tables")
            if not self.conditions or not self.primaries:
                raise DataError("transport_only requires a nonempty complete primary pool")
        if transport_only or r06:
            _transport_metadata(list(self.conditions.values()))
            _transport_metadata(list(self.primaries.values()))
        if self.times:
            for t in self.times:
                _finite(t, "sample_times_ns")
            if any(b <= a for a, b in zip(self.times, self.times[1:])):
                raise DataError("sample_times_ns must strictly increase")
        domains = set()
        profile_cohorts: dict[str, set[str]] = {}
        profile_physics: dict[str, str] = {}
        source_cohorts: dict[str, set[str]] = {}
        primary_pools: dict[str, set[str]] = {}
        source_hashes: dict[str, str] = {}
        for condition in self.conditions.values():
            if transport_only and (not isinstance(condition.get("condition_id"), str)
                                   or not condition["condition_id"].strip()):
                raise DataError("Condition condition_id must be a nonempty string")
            for key in ("profile_id", "domain", "cohort"):
                if not condition.get(key):
                    raise DataError(f"Condition lacks {key}")
                if transport_only and (not isinstance(condition[key], str) or not condition[key].strip()):
                    raise DataError(f"Condition requires a nonempty string {key}")
            cohort = condition["cohort"]
            if cohort not in (R06_COHORTS if r06 else COHORTS):
                raise DataError(f"Unknown cohort: {cohort}")
            if "labels" in condition:
                raise LeakageError("Condition metadata must not contain response labels")
            profile_cohorts.setdefault(condition["profile_id"], set()).add(cohort)
            domains.add(condition["domain"])
            features = condition.get("features", {})
            unknown = set(features) - set(F_FEATURES) - {"theta_deg", "phi_deg"}
            if unknown:
                raise LeakageError(f"Unapproved/pre-simulation feature(s): {sorted(unknown)}")
            for key, value in features.items():
                if value is not None:
                    _finite(value, key)
            required_features = ("gate_length_nm", "incident_energy_MeV")
            if not transport_only or features.get("capacitance_fF") is not None:
                required_features += ("capacitance_fF",)
            for key in required_features:
                _finite(features.get(key), key, positive=True)
            if transport_only:
                for key in DEVICE_FEATURES:
                    if features.get(key) is not None and key != "bias_voltage_V" and features[key] < 0:
                        raise DataError(f"{key} must be nonnegative")
            if condition.get("categories", {}).get("particle") != "proton":
                raise DataError("The current frozen predictor designs support proton only")
            if not condition.get("categories", {}).get("structure_family"):
                raise DataError("Explicit structure_family required")
            length, energy = features["gate_length_nm"], features["incident_energy_MeV"]
            if r06:
                _validate_r06_condition(condition)
            else:
                if not 1 <= energy <= 200:
                    raise DataError("Condition outside r0.4 energy design")
                if cohort == "high_energy":
                    if not 120 < energy <= 200 or not 11.2 <= length <= 15.4:
                        raise LeakageError("High-energy cohort does not match frozen bounds")
                elif energy > 120:
                    raise LeakageError("Energy above 120 MeV cannot enter development/device test")
                if cohort == "device_extrapolation":
                    if not 15.4 < length <= 16.8:
                        raise LeakageError("Device-test gate length must exceed 15.4 nm")
                elif not 11.2 <= length <= 15.4:
                    raise LeakageError("Development/known-device gate length outside frozen bounds")
            physics = {k: features.get(k) for k in DEVICE_FEATURES}
            fingerprint = digest({"features": physics, "structure": condition["categories"]["structure_family"],
                                  "domain": condition["domain"]})
            old = profile_physics.setdefault(condition["profile_id"], fingerprint)
            if old != fingerprint:
                raise DataError("A profile_id refers to different device physics")
            n = condition.get("n_bits")
            if not transport_only or n is not None:
                if isinstance(n, bool) or not isinstance(n, int) or n < 1:
                    raise DataError("n_bits must be a positive integer")
            bits = (condition.get("bits") if transport_only else
                    condition.get("bits", [{"bit_id": "0", "x_nm": 0., "y_nm": 0., "z_nm": 0.}]))
            if bits is not None or not transport_only:
                if not isinstance(bits, list) or len(bits) != n or len({str(x["bit_id"]) for x in bits}) != n:
                    raise DataError("Multi-bit models require explicit physical bit positions")
                for bit in bits:
                    for key in ("x_nm", "y_nm", "z_nm"):
                        _finite(bit.get(key), "bit." + key)
            if not transport_only or condition.get("source_area_cm2") is not None:
                _finite(condition.get("source_area_cm2"), "source_area_cm2", positive=True)
            if transport_only:
                count = condition.get("primary_count")
                if type(count) is not int or count < 1:
                    raise DataError("transport_only primary_count must be a positive integer")
                primary_pools[condition["condition_id"]] = set()
        if len(domains) > 1:
            raise DataError("Separate DDR5/LPDDR5 model domains; do not concatenate them")
        for cohorts in profile_cohorts.values():
            if cohorts & {"device_extrapolation", "profile_holdout"} and len(cohorts) > 1:
                raise LeakageError("Unseen-device profile overlaps development/known-device cohort")
        for primary in self.primaries.values():
            if transport_only and (not isinstance(primary.get("primary_id"), str)
                                   or not primary["primary_id"].strip()):
                raise DataError("Primary primary_id must be a nonempty string")
            condition = self.conditions.get(primary.get("condition_id"))
            if condition is None:
                raise DataError("Primary has unknown condition")
            if not primary.get("source_primary_id") or not primary.get("source_hash"):
                raise DataError("Primary requires global source identity and hash, not seed alone")
            if transport_only:
                if (not isinstance(primary["source_primary_id"], str)
                        or not primary["source_primary_id"].strip()):
                    raise DataError("Primary source_primary_id must be a nonempty string")
                _sha256(primary["source_hash"], "Primary source_hash")
                if primary.get("pool_member") is not True:
                    raise DataError("transport_only requires every primary to be an explicit pool_member")
                pool = primary_pools[primary["condition_id"]]
                if primary["source_primary_id"] in pool:
                    raise DataError("Duplicate source_primary_id within a transport primary pool")
                pool.add(primary["source_primary_id"])
                old_hash = source_hashes.setdefault(primary["source_primary_id"], primary["source_hash"])
                if old_hash != primary["source_hash"]:
                    raise DataError("A source_primary_id has conflicting source hashes")
            source_cohorts.setdefault(primary["source_primary_id"], set()).add(condition["cohort"])
            if r06:
                _sha256(primary["source_hash"], "Primary source_hash")
                if type(primary.get("pool_member")) is not bool:
                    raise DataError("r0.6 primary pool membership must be explicit")
                if primary.get("sampling") is not None and primary["sampling"] not in R06_PARTICLE_SAMPLING:
                    raise DataError("Unknown r0.6 primary sampling metadata")
                if "scale_factor" in primary:
                    raise DataError("r0.6 snapshot primaries store unscaled source features; scale belongs to the response")
            elif ((not transport_only or primary.get("sampling") is not None)
                  and primary.get("sampling") not in {"random", "enriched"}):
                raise DataError("Primary selection sampling must be explicit")
            values = primary.get("source_features", {})
            if (transport_only or r06) and values is None:
                values = {}
            if not isinstance(values, dict):
                raise DataError("source_features must be an object")
            if set(values) - set(SOURCE_FEATURES):
                raise DataError("Unknown source features: declare the schema before using them")
            for key, value in values.items():
                if value is not None:
                    _finite(value, key)
            for key in ("generated_charge_fC", "source_duration_ns"):
                if (transport_only or r06) and values.get(key) is None:
                    continue
                _finite(values.get(key), key)
                if values[key] < 0:
                    raise DataError(f"{key} must be nonnegative")
            if transport_only or r06:
                for key in ("deposited_energy_MeV", "secondary_count", "spread_x_nm", "spread_y_nm", "spread_z_nm"):
                    if values.get(key) is not None and values[key] < 0:
                        raise DataError(f"{key} must be nonnegative")
            if ((not (transport_only or r06) or primary.get("source_off") is not None)
                    and not isinstance(primary.get("source_off"), bool)):
                raise DataError("Complete mapped source_off must be explicit")
            if primary.get("source_off") is True and (values.get("generated_charge_fC") != 0
                                                     or (not r06 and values.get("deposited_energy_MeV", 0) != 0)):
                raise DataError("Source-off conflicts with a nonzero mapped source")
        if any(len(c) > 1 for c in source_cohorts.values()):
            raise LeakageError("A primary source crosses development/sealed-test cohorts")
        if transport_only:
            for condition_id, pool in primary_pools.items():
                if len(pool) != self.conditions[condition_id]["primary_count"]:
                    raise DataError(f"Incomplete transport primary pool: {condition_id}")
        dev_conditions = self.development_conditions
        dev_profiles = {self.conditions[k]["profile_id"] for k in dev_conditions}
        _unique(self.controls, "control_id")
        for control in self.controls:
            if control.get("cohort") != "development" or control.get("profile_id") not in dev_profiles:
                raise LeakageError("A sealed/unseen-profile control entered development")
            if control.get("state") not in (0, 1) or not control.get("source_hash"):
                raise DataError("Control needs state and source hash")
            if r06:
                _validate_r06_evidence(control, self.manifest, control=True)
        for row in self.responses + self.superseded:
            p = self.primaries.get(row.get("primary_id"))
            if p is None or p["condition_id"] not in dev_conditions:
                raise LeakageError("A development response references a sealed/unknown primary")
            if row.get("state") not in (0, 1) or not row.get("source_hash") or not row.get("run_id"):
                raise DataError("Response requires state, original run and source hash")
            if row.get("status") not in {"valid", "unresolved", "failed"}:
                raise DataError("Response quality status must be explicit")
            c = self.conditions[p["condition_id"]]
            if str(row.get("bit_id", "0")) not in {str(x["bit_id"]) for x in bits_for(c)}:
                raise DataError("Response references unknown physical bit")
            labels = row.get("labels") or {}
            if r06:
                _validate_r06_evidence(row, self.manifest)
                _validate_r06_response(row, c, p)
            curve = labels.get("delta_voltage_V")
            if curve is not None and (not isinstance(curve, list) or len(curve) != len(self.times)):
                raise DataError("Voltage target length differs from frozen time grid")
            for key, value in labels.items():
                for item in value if isinstance(value, list) else [value]:
                    if item is not None:
                        _finite(item, "label." + key)
            if labels.get("upset") is not None:
                if labels["upset"] not in (0, 1) or not row.get("upset_definition_id"):
                    raise DataError("Binary upset requires an explicit verified definition ID")
        _unique(self.counts, "count_id")
        for count in self.counts:
            if count.get("condition_id") not in dev_conditions:
                raise LeakageError("Sealed native count in development")
            if count.get("state") not in (0, 1) or count.get("count_model") != "poisson":
                raise DataError("This implementation requires justified per-state Poisson native counts")
            k = count.get("bit_errors")
            if not isinstance(k, int) or isinstance(k, bool) or k < 0:
                raise DataError("Native count must be a nonnegative integer")
            _finite(count.get("fluence_cm2"), "fluence_cm2", positive=True)
            condition = self.conditions[count["condition_id"]]
            if count.get("n_bits") != condition["n_bits"]:
                raise DataError("Native count bit denominator differs from condition")
            if not count.get("source_hash") or not count.get("source_primary_ids"):
                raise DataError("Native count requires independently traceable exposure provenance")
            sources = count["source_primary_ids"]
            if (not isinstance(sources, list) or any(not isinstance(s, str) or not s for s in sources)
                    or len(set(sources)) != len(sources)):
                raise DataError("Native count primary provenance must be a unique nonempty list")
            for source in sources:
                if source in source_cohorts and source_cohorts[source] != {"development"}:
                    raise LeakageError("A native-count exposure reuses a sealed primary")
                known = [p for p in self.primaries.values() if p["source_primary_id"] == source]
                if known and not any(p["condition_id"] == count["condition_id"] for p in known):
                    raise LeakageError("Native count source is assigned to a different condition")
        pairs = [(c["condition_id"], c["state"]) for c in self.counts]
        if len(pairs) != len(set(pairs)):
            raise DataError("Merge independent exposures explicitly; no duplicate condition/state counts")

    def view(self, condition_ids: Iterable[str]) -> "View":
        self.require_model_stage()
        ids = frozenset(condition_ids)
        if not ids <= self.development_conditions:
            raise LeakageError("Fit view can contain development conditions only")
        return View(self, ids)

    def summary(self) -> dict:
        return {
            "simulation_revision": self.simulation_revision,
            "kind": self.manifest["kind"], "data_stage": self.data_stage, "conditions": {
                c: sum(x["cohort"] == c for x in self.conditions.values())
                for c in sorted(R06_COHORTS if self.simulation_revision == "0.6" else COHORTS)},
            "primaries": len(self.primaries), "development_responses": len(self.responses),
            "superseded_responses": len(self.superseded), "development_controls": len(self.controls),
            "native_counts": len(self.counts), "label_files_read": list(self.read_files),
            "sealed_labels_opened": False, "training_started": False,
        }


@dataclass(frozen=True)
class View:
    snapshot: Snapshot
    condition_ids: frozenset[str]

    def __post_init__(self):
        self.snapshot.require_model_stage()

    @property
    def conditions(self):
        self.snapshot.require_model_stage()
        return [self.snapshot.conditions[k] for k in sorted(self.condition_ids)]

    @property
    def profiles(self):
        return {c["profile_id"] for c in self.conditions}

    @property
    def primaries(self):
        self.snapshot.require_model_stage()
        return [p for p in self.snapshot.primaries.values() if p["condition_id"] in self.condition_ids]

    @property
    def source_ids(self):
        return {p["source_primary_id"] for p in self.primaries} | {
            s for c in self.counts for s in c["source_primary_ids"]}

    @property
    def responses(self):
        self.snapshot.require_model_stage()
        ids = {p["primary_id"] for p in self.primaries}
        return [r for r in self.snapshot.responses if r["primary_id"] in ids]

    @property
    def controls(self):
        return [c for c in self.snapshot.controls if c["profile_id"] in self.profiles]

    @property
    def counts(self):
        return [c for c in self.snapshot.counts if c["condition_id"] in self.condition_ids]

    def footprint(self):
        return {
            "condition_ids": sorted(self.condition_ids), "profile_ids": sorted(self.profiles),
            "source_primary_ids": sorted(self.source_ids),
            "response_ids": sorted(r["response_id"] for r in self.responses),
            "control_ids": sorted(c["control_id"] for c in self.controls),
            "source_control_ids": sorted({c.get("source_control_id", c["control_id"]) for c in self.controls}),
            "count_ids": sorted(c["count_id"] for c in self.counts),
        }

    def fingerprint(self):
        return digest({"conditions": self.conditions, "primaries": self.primaries,
                       "responses": self.responses, "controls": self.controls, "counts": self.counts,
                       "times": self.snapshot.times, "kind": self.snapshot.manifest["kind"],
                       **({"simulation_revision": "0.6",
                           "deck_timing_version": self.snapshot.manifest["deck_timing_version"],
                           "source_time_ns": self.snapshot.manifest["source_time_ns"]}
                          if self.snapshot.simulation_revision == "0.6" else {})})

    def assert_disjoint(self, other: "View"):
        if self.profiles & other.profiles or self.source_ids & other.source_ids:
            raise LeakageError("Profile/primary provenance crosses fit and validation scopes")
        mine = {c.get("source_control_id", c["control_id"]) for c in self.controls}
        theirs = {c.get("source_control_id", c["control_id"]) for c in other.controls}
        if mine & theirs:
            raise LeakageError("A reused control crosses fit and validation scopes")


def bits_for(condition: dict) -> list[dict]:
    return condition.get("bits", [{"bit_id": "0", "x_nm": 0., "y_nm": 0., "z_nm": 0.}])


def head_valid(row: dict, head: str) -> bool:
    if row["status"] == "failed":
        return False
    if head == "upset" and (row["status"] != "valid" or not row.get("upset_definition_id")):
        return False
    return bool((row.get("masks") or {}).get(head, row["status"] == "valid"))


def has_supervised_head(row: dict, head: str) -> bool:
    value = (row.get("labels") or {}).get(head)
    return head_valid(row, head) and (
        any(item is not None for item in value) if isinstance(value, list) else value is not None
    )
