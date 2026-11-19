"""Artificial fixtures for software tests only; no values are research results."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def rewrite_table(manifest_path: Path, name: str, rows: list[dict]) -> None:
    """Write an intentional fixture mutation and refresh its declared byte hash."""
    path = manifest_path.parent / name
    path.write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                            for row in rows), encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("files_sha256", {})[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _unit_pulse(t: float, duration: float, tau: float) -> float:
    """Closed-form charge-one rectangular-current RC test signal."""
    if t < 0:
        return 0.
    if duration == 0:
        return math.exp(-t / tau)
    if t <= duration:
        return -math.expm1(-t / tau) * tau / duration
    return math.expm1(duration / tau) * math.exp(-t / tau) * tau / duration


def make_snapshot(root: Path, profiles=12, conditions_per_profile=2,
                  primaries_per_condition=6, with_counts=True, with_sealed=True) -> Path:
    """Build a complete, explicitly synthetic snapshot with sealed poison labels.

    ``profiles`` counts development profiles only. Sealed cohorts deliberately
    include two known profiles and one unseen profile. Native-looking counts
    are computed from these artificial labels and are always marked synthetic.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if profiles < 1 or conditions_per_profile < 1 or primaries_per_condition < 1:
        raise ValueError("Fixture dimensions must be positive")
    sample_times = [-.5, 0., .1, .4, 1., 2., 4., 8.]
    conditions, primaries, responses, controls, counts = [], [], [], [], []
    templates = []
    for p in range(profiles):
        position = p / max(profiles - 1, 1)
        profile = f"synthetic-profile-{p:03d}"
        features = {
            "gate_length_nm": 11.4 + 2.6 * position,
            "device_length_nm": 50. + position,
            "device_width_nm": 20.,
            "fin_width_nm": 7. + .4 * position,
            "oxide_thickness_nm": 2.,
            "junction_depth_nm": 85.,
            "acceptor_scale": .8 + .4 * position,
            "donor_scale": 1.1,
            "capacitance_fF": 8. + 2. * position,
            "bias_voltage_V": 1.2,
            "temperature_K": 300.,
        }
        categories = {"particle": "proton", "structure_family": "synthetic-rc-test-only"}
        template = {
            "profile_id": profile, "domain": "synthetic-LPDDR5-test-only",
            "features": features, "categories": categories,
            "source_area_cm2": 1e-8, "n_bits": 1,
            "area_normalization_validated": True, "primary_count": primaries_per_condition,
            "source_distribution": "uniform", "count_model": "poisson",
            "protocol_id": "synthetic-test-protocol",
            "provenance_kind": "synthetic_fixture",
        }
        templates.append(copy.deepcopy(template))
        for state in (0, 1):
            tau = 12. * math.exp(.2 * position + .1 * state)
            control_times = [0., 1., 2., 4., 8., 12.]
            equilibrium, amplitude = .05, .2 + .3 * state
            control = {
                "control_id": f"{profile}:control:{state}", "profile_id": profile,
                "cohort": "development", "state": state,
                "time_ns": control_times,
                "voltage_V": [equilibrium + amplitude * math.exp(-t / tau) for t in control_times],
                "reference_voltage_V": equilibrium, "capacitance_fF": features["capacitance_fF"],
                "mechanism_validated": True, "run_id": f"synthetic-run-control-{p}-{state}",
                "provenance_kind": "synthetic_fixture",
            }
            control["source_hash"] = _hash(control)
            controls.append(control)
        for c in range(conditions_per_profile):
            condition = copy.deepcopy(template)
            condition_id = f"{profile}:condition:{c:02d}"
            condition.update(condition_id=condition_id, cohort="development")
            condition["features"].update(
                incident_energy_MeV=20. + 30. * (c % 4),
                theta_deg=float((c * 15) % 60), phi_deg=float((c * 45) % 360))
            conditions.append(condition)
            count_sources, state_counts = [], {0: 0, 1: 0}
            for j in range(primaries_per_condition):
                primary_id = f"{condition_id}:primary:{j:04d}"
                charge = [0., 2., .4, 1.5, .8, 3.][j % 6]
                duration = .1
                sampling = "random" if j < max(1, primaries_per_condition // 2) else "enriched"
                primary = {
                    "primary_id": primary_id, "condition_id": condition_id,
                    "source_primary_id": f"synthetic-transport-{p:03d}-{c:02d}:event:{j:04d}",
                    "source_features": {
                        "generated_charge_fC": charge,
                        "deposited_energy_MeV": charge * .02,
                        "source_duration_ns": duration,
                        "hit_x_nm": float(j), "hit_y_nm": 0., "hit_z_nm": 1.,
                        "secondary_count": float(j % 3),
                    },
                    "source_off": charge == 0., "pool_member": True, "sampling": sampling,
                    "provenance_kind": "synthetic_fixture",
                }
                if primary["source_off"]:
                    # Complete mapped source off, not just an empty scoring voxel.
                    primary["source_features"] = {k: 0. for k in primary["source_features"]}
                    duration = 0.
                primary["source_hash"] = _hash(primary)
                primaries.append(primary)
                if sampling == "random":
                    count_sources.append(primary["source_primary_id"])
                for state in (0, 1):
                    tau = 12. * math.exp(.2 * position + .1 * state)
                    gain = (.8 + .1 * position) if state == 0 else -(1.1 + .1 * position)
                    delta_v = [gain * charge / features["capacitance_fF"]
                               * _unit_pulse(t, duration, tau) for t in sample_times]
                    # Only a stipulated artificial test label, not a DRAM criterion.
                    upset = int(charge > (1. if state == 0 else 1.2))
                    if sampling == "random":
                        state_counts[state] += upset
                    response = {
                        "response_id": f"{primary_id}:state:{state}", "primary_id": primary_id,
                        "state": state, "bit_id": "0", "status": "valid",
                        "labels": {
                            "delta_voltage_V": delta_v,
                            "port_charge_fC": .75 * gain * charge,
                            "margin_V": .1 - .08 * charge,
                            "upset": upset,
                        },
                        "masks": {k: True for k in ("delta_voltage_V", "port_charge_fC", "margin_V", "upset")},
                        "mechanism_validated": True,
                        "upset_definition_id": "synthetic-test-only",
                        "run_id": f"synthetic-run-{p}-{c}-{j}-{state}",
                        "provenance_kind": "synthetic_fixture",
                    }
                    response["source_hash"] = _hash(response)
                    responses.append(response)
            if with_counts:
                for state in (0, 1):
                    count = {
                        "count_id": f"{condition_id}:native-count:{state}",
                        "condition_id": condition_id, "state": state,
                        "bit_errors": state_counts[state],
                        "fluence_cm2": len(count_sources) / condition["source_area_cm2"],
                        "n_bits": 1, "count_model": "poisson",
                        "source_primary_ids": list(count_sources),
                        "provenance_kind": "synthetic_fixture",
                    }
                    count["source_hash"] = _hash(count)
                    counts.append(count)
    sealed = {}
    if with_sealed:
        held = [
            ("new_combination", templates[0], 75., None),
            ("high_energy", templates[min(1, len(templates)-1)], 160., None),
            ("device_extrapolation", templates[0], 50., 16.2),
        ]
        for cohort, template, energy, length in held:
            condition = copy.deepcopy(template)
            condition_id = f"synthetic-sealed:{cohort}"
            condition.update(condition_id=condition_id, cohort=cohort, primary_count=1)
            condition["features"].update(incident_energy_MeV=energy, theta_deg=35., phi_deg=75.)
            if length is not None:
                condition["profile_id"] = "synthetic-unseen-profile"
                condition["features"]["gate_length_nm"] = length
            conditions.append(condition)
            primary = {
                "primary_id": f"{condition_id}:primary:0", "condition_id": condition_id,
                "source_primary_id": f"synthetic-independent-sealed-{cohort}:0",
                "source_features": {"generated_charge_fC": .6, "deposited_energy_MeV": .012,
                                    "source_duration_ns": .1},
                "source_off": False, "pool_member": True, "sampling": "random",
                "provenance_kind": "synthetic_fixture",
            }
            primary["source_hash"] = _hash(primary)
            primaries.append(primary)
        poison = root / "sealed" / "labels.jsonl"
        poison.parent.mkdir(parents=True, exist_ok=True)
        poison.write_text("THIS FILE MUST NOT BE PARSED OR READ BY TRAINING\n", encoding="utf-8")
        sealed = {"responses_file": "sealed/labels.jsonl",
                  "controls_file": "sealed/not-materialized-controls.jsonl",
                  "counts_file": "sealed/not-materialized-counts.jsonl"}
    manifest = {
        "schema_version": 1, "plan_id": "dram-se-ddr5-lpddr5", "simulation_revision": "0.4",
        "kind": "synthetic_fixture", "sample_times_ns": sample_times,
        "conditions_file": "conditions.jsonl", "primaries_file": "primaries.jsonl",
        "development": {"responses_file": "responses.jsonl", "controls_file": "controls.jsonl",
                        "counts_file": "counts.jsonl"},
        "sealed": sealed, "files_sha256": {},
        "description": "Artificial software test data; never a scientific training snapshot.",
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for name, rows in (("conditions.jsonl", conditions), ("primaries.jsonl", primaries),
                       ("responses.jsonl", responses), ("controls.jsonl", controls),
                       ("counts.jsonl", counts)):
        rewrite_table(path, name, rows)
    return path


def make_fixture(root: Path, profiles=12, conditions_per_profile=2,
                 primaries_per_condition=6, include_counts=True) -> Path:
    """Main-pipeline test entry point; always includes the three sealed cohorts."""
    return make_snapshot(root, profiles, conditions_per_profile, primaries_per_condition,
                         with_counts=include_counts, with_sealed=True)
