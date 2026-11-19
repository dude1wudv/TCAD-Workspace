#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build/check the fixed r0.5 planning manifest; no runtime, SSH or scheduling."""

import argparse
from collections import Counter, defaultdict
import copy
import datetime as dt
import hashlib
import itertools
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "plans/dram-se-ddr5-lpddr5"
BUDGET_FILE = PLAN / "BUDGET-REDUCTION-20261117.md"
OUTPUT = PLAN / "month-one-cases-r05.json"
# All scientific values below transcribe this exact authorized budget snapshot.
BUDGET_SHA256 = "507a03ea6d098bc2aa37f52ae30f12da2f9ad472a81a49422612802fa146169b"
AXES = ("Lg", "Wfin", "Tox", "NA", "ND")
PROFILE_ROWS = (
    ("D0-nominal", "开发基准", None, None),
    ("D1-short-channel", "开发：短沟道", "Lg", 0.8),
    ("D2-narrow-fin", "开发：窄 fin", "Wfin", 0.8),
    ("D3-low-acceptor", "开发：低受主", "NA", 0.5),
    ("H0-long-channel", "器件留出：长沟道", "Lg", 1.2),
    ("H1-high-donor", "器件留出：高施主", "ND", 2.0),
)
RADIATION_ROWS = (
    ("C0-low-normal", 5, 0, 0),
    ("C1-mid-oblique", 58, 30, 0),
    ("C2-domain-holdout", 20, 45, 90),
    ("C3-high-energy-holdout", 150, 60, 90),
)
RULES = (
    ("core", "development", None, (0, 1, 2, 3), (0, 1)),
    ("core", "domain_holdout", "domain", (0, 1, 2, 3), (2,)),
    ("core", "high_energy_holdout", "high_energy", (0, 1), (3,)),
    ("core", "device_holdout", "device", (4, 5), (0,)),
    ("reserve", "device_holdout", "device", (4, 5), (1,)),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_budget():
    actual = hashlib.sha256(BUDGET_FILE.read_bytes()).hexdigest()
    require(actual == BUDGET_SHA256,
            "Scientific budget SHA changed; reconcile its revision before rebuilding this snapshot")
    return actual


def quantity(value, unit):
    return {"value": value, "unit": unit}


def device_parameters(axis=None, scale=None):
    return {key: dict(value=scale if key == axis else 1.0, unit="1",
                      representation="baseline_multiplier",
                      absolute_value=None, absolute_unit=None) for key in AXES}


def token(identifier):
    return identifier.split("-", 1)[0].lower()


def control_id(profile_id, bit):
    return "m1-r05-%s-zero-b%d" % (token(profile_id), bit)


def case_parameters(profile, radiation=None):
    parameters = copy.deepcopy(profile["parameters"])
    parameters.update(
        particle="proton" if radiation else None,
        energy=quantity(radiation["energy_MeV"] if radiation else None, "MeV"),
        theta=quantity(radiation["theta_deg"] if radiation else None, "deg"),
        phi=quantity(radiation["phi_deg"] if radiation else None, "deg"))
    return parameters


def unbound_fields():
    return dict(
        status="planned", task_id=None, run_ids=[], accepted=False, acceptance_evidence=None,
        parameter_baseline_sha256=None, scientific_label=None, codex_progress_ref=None,
        cv_fold=None, selection_record=None, selection_seed=None, inclusion_probability=None,
        primary_provenance=dict(transport_run_id=None, transport_input_sha256=None,
                                event_id=None, primary_id=None, connected_group_id=None))


def build(updated_at, budget_sha):
    profiles = [
        dict(id=pid, label=label, parameters=device_parameters(axis, scale),
             partition="device_holdout" if pid.startswith("H") else "development",
             parameter_baseline_sha256=None,
             baseline_context=dict(device_outer_length=None, device_outer_width=None,
                                   effective_channel_length=None, junction_geometry=None,
                                   absolute_doping_profiles=None, operating_conditions=None,
                                   source_normalization=None))
        for pid, label, axis, scale in PROFILE_ROWS
    ]
    radiations = [
        dict(id=rid, particle="proton", energy_MeV=energy, theta_deg=theta, phi_deg=phi,
             units=dict(energy_MeV="MeV", theta_deg="deg", phi_deg="deg"))
        for rid, energy, theta, phi in RADIATION_ROWS
    ]
    conditions, cases = [], []
    for cohort, split, holdout, profile_indices, radiation_indices in RULES:
        for pi, ri in itertools.product(profile_indices, radiation_indices):
            profile, radiation = profiles[pi], radiations[ri]
            cid = "m1-r05-%s-%s" % (token(profile["id"]), token(radiation["id"]))
            condition = dict(
                id=cid, profile_id=profile["id"], radiation_id=radiation["id"], cohort=cohort,
                budget_tier=cohort, split=split, holdout=holdout,
                energy_MeV=radiation["energy_MeV"], theta_deg=radiation["theta_deg"],
                phi_deg=radiation["phi_deg"], units=copy.deepcopy(radiation["units"]),
                primary_count=12, random_primary_count=6, enriched_primary_count=6,
                response_count=24)
            conditions.append(condition)
            for primary in range(12):
                pair_id = "%s-p%02d" % (cid, primary)
                mechanism = "random" if primary < 6 else "enriched"
                for bit in (0, 1):
                    cases.append(dict(
                        case_id="%s-b%d" % (pair_id, bit), pair_id=pair_id,
                        condition_id=cid, profile_id=profile["id"], cohort=cohort,
                        kind="response", primary_index=primary, stored_bit=bit,
                        budget_tier=cohort, selection_mechanism=mechanism,
                        split=split, holdout=holdout, training_eligible=split == "development",
                        native_random_statistics_eligible=mechanism == "random",
                        control_case_id=control_id(profile["id"], bit), control_pair_id=None,
                        reusable_for_condition_ids=[], parameters=case_parameters(profile, radiation),
                        **unbound_fields()))
    for profile in profiles:
        held_out = profile["partition"] == "device_holdout"
        for bit in (0, 1):
            cases.append(dict(
                case_id=control_id(profile["id"], bit), pair_id=None, condition_id=None,
                profile_id=profile["id"], cohort="control", kind="control", primary_index=None,
                stored_bit=bit, budget_tier="reusable_zero",
                selection_mechanism="no_particle_control",
                split="device_holdout" if held_out else "development_control",
                holdout="device" if held_out else None, training_eligible=False,
                native_random_statistics_eligible=False, control_case_id=None,
                control_pair_id="m1-r05-%s-zero" % token(profile["id"]),
                reusable_for_condition_ids=[c["id"] for c in conditions
                                           if c["profile_id"] == profile["id"]],
                parameters=case_parameters(profile), **unbound_fields()))
    return dict(
        schema_version=1, revision="r0.5", updated_at=updated_at, status="planned",
        plan_id="dram-se-ddr5-lpddr5",
        artifact_role="planned_cases_not_execution_queue",
        schema_contract="plans/dram-se-ddr5-lpddr5/CASE-MANIFEST-CONTRACT.md",
        scientific_budget_source=dict(
            path=BUDGET_FILE.relative_to(ROOT).as_posix(), revision="0.5", sha256=budget_sha),
        budget=dict(core_conditions=16, reserve_conditions=2, total_conditions=18,
                    core_response_cases=384, reserve_response_cases=48,
                    reusable_zero_cases=12, total_cases=444,
                    core_primary_pairs=192, reserve_primary_pairs=24, total_primary_pairs=216,
                    random_primary_pairs=108, enriched_primary_pairs=108,
                    verified_independent_event_count=None,
                    reserve_activation="core_on_schedule_no_pending_long_task_repairs_and_resource_margin"),
        sampling_contract=dict(
            primary_index_is="planned_selection_slot_not_transport_event_id",
            random_indices=list(range(6)), enriched_indices=list(range(6, 12)),
            states_per_primary=[0, 1], paired_states_are_independent_events=False,
            random_pool_includes_zero_deposition=True, within_condition_primary_replacement=False,
            enrichment_must_exclude_selected_random_events=True, enrichment_rule=None,
            enhanced_samples_are_unweighted_population_statistics=False,
            controls_are_negative_training_samples=False,
            source_reuse_requires_connected_provenance_deduplication=True),
        split_contract=dict(
            response_splits=["development", "domain_holdout", "high_energy_holdout", "device_holdout"],
            training_condition_ids=[c["id"] for c in conditions if c["split"] == "development"],
            final_holdout_condition_ids=[c["id"] for c in conditions if c["holdout"] is not None],
            event_states_repairs_refinements_stay_together=True,
            actual_connected_groups_and_folds_unbound=True,
            holdout_labels_used_for_training_or_hpo=False,
            held_out_profile_controls_sealed=True,
            known_development_profiles_may_share_predeclared_zero_controls=True,
            cross_split_primary_reuse_requires_provenance_conflict_resolution=True),
        integration=dict(
            execution_interface_reference="automation/server-codex/README.md",
            research_progress_reference="plans/dram-se-ddr5-lpddr5/HANDOFF.md#7-状态和报告",
            execution_source_of_truth="existing_runner_manifests_and_verified_archives",
            join_keys=["case_id", "task_id", "run_ids"],
            codex_progress_fields=["progress", "use_scope", "uncertainty", "next_action"],
            codex_progress_ref=None, runtime_state_embedded=False,
            unbound_run_ids_representation="empty_array",
            historical_r04_or_performance_probe_cases_adopted=False),
        profiles=profiles, radiations=radiations, conditions=conditions, cases=cases)


def validate(data, budget_sha):
    require(type(data["schema_version"]) is int and data["schema_version"] == 1
            and data["revision"] == "r0.5" and data["status"] == "planned", "Schema/revision/status")
    require(isinstance(data["updated_at"], str) and data["updated_at"].endswith("Z"), "UTC timestamp")
    parsed = dt.datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
    require(parsed.utcoffset() == dt.timedelta(0), "updated_at must be UTC")
    require(data["scientific_budget_source"]["sha256"] == budget_sha, "Budget provenance")
    profiles = {p["id"]: p for p in data["profiles"]}
    radiations = {r["id"]: r for r in data["radiations"]}
    conditions = {c["id"]: c for c in data["conditions"]}
    by_id = {c["case_id"]: c for c in data["cases"]}
    require(len(profiles) == len(data["profiles"]) == 6, "Six unique profiles")
    require(len(radiations) == len(data["radiations"]) == 4, "Four unique radiation combinations")
    require(len(conditions) == len(data["conditions"]) == 18, "Eighteen unique radiation conditions")
    require(len(by_id) == len(data["cases"]) == 444, "444 unique case IDs")
    require(set(profiles) == {row[0] for row in PROFILE_ROWS}, "Exact profile coverage")
    for pid, label, axis, scale in PROFILE_ROWS:
        p = profiles[pid]
        require(p["label"] == label and "\ufffd" not in p["label"], pid + ": UTF-8 Chinese label")
        require(p["parameters"] == device_parameters(axis, scale), pid + ": relative parameters")
        require(p["parameter_baseline_sha256"] is None
                and all(v is None for v in p["baseline_context"].values()), pid + ": unbound baseline")
    for rid, energy, theta, phi in RADIATION_ROWS:
        r = radiations[rid]
        require((r["energy_MeV"], r["theta_deg"], r["phi_deg"]) == (energy, theta, phi),
                rid + ": radiation values")
        require(r["units"] == dict(energy_MeV="MeV", theta_deg="deg", phi_deg="deg"), rid + ": units")
    expected_matrix = {}
    for cohort, split, holdout, profile_indices, radiation_indices in RULES:
        for pi, ri in itertools.product(profile_indices, radiation_indices):
            expected_matrix[(PROFILE_ROWS[pi][0], RADIATION_ROWS[ri][0])] = (cohort, split, holdout)
    observed_matrix = {}
    for cid, c in conditions.items():
        key = c["profile_id"], c["radiation_id"]
        require(key not in observed_matrix and key in expected_matrix, "Duplicate/unbudgeted condition")
        require(cid == "m1-r05-%s-%s" % (token(key[0]), token(key[1])), "Stable condition ID")
        require((c["cohort"], c["split"], c["holdout"]) == expected_matrix[key], cid + ": split")
        require(c["budget_tier"] == c["cohort"], cid + ": tier")
        require(all(c[k] == radiations[key[1]][k]
                    for k in ("energy_MeV", "theta_deg", "phi_deg", "units")), cid + ": irradiation")
        observed_matrix[key] = c["cohort"], c["split"], c["holdout"]
    require(observed_matrix == expected_matrix, "Exact 16 core / 2 reserve matrix")
    require(Counter(c["cohort"] for c in conditions.values()) == {"core": 16, "reserve": 2},
            "Condition tier counts")
    pairs, per_condition, controls = defaultdict(list), defaultdict(list), []
    for case in data["cases"]:
        rid = case["case_id"]
        require(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", rid) is not None, "ASCII case ID")
        require(type(case["stored_bit"]) is int and case["stored_bit"] in (0, 1), rid + ": bit")
        require(case["profile_id"] in profiles, rid + ": profile foreign key")
        require(case["run_ids"] == [] and case["accepted"] is False
                and case["status"] == "planned", rid + ": unexecuted plan")
        for field in ("task_id", "parameter_baseline_sha256", "acceptance_evidence",
                      "scientific_label", "codex_progress_ref", "cv_fold", "selection_record",
                      "selection_seed", "inclusion_probability"):
            require(case[field] is None, rid + ": unbound " + field)
        require(all(v is None for v in case["primary_provenance"].values()), rid + ": actual provenance")
        profile = profiles[case["profile_id"]]
        if case["kind"] == "response":
            cid = case["condition_id"]
            require(cid in conditions, rid + ": condition foreign key")
            condition = conditions[cid]
            require(case["profile_id"] == condition["profile_id"], rid + ": condition profile")
            require(all(case[k] == condition[k] for k in ("cohort", "budget_tier", "split", "holdout")),
                    rid + ": condition partition")
            primary = case["primary_index"]
            require(type(primary) is int and 0 <= primary <= 11, rid + ": planned primary")
            pair_id = "%s-p%02d" % (cid, primary)
            require(case["pair_id"] == pair_id and rid == "%s-b%d" % (pair_id, case["stored_bit"]),
                    rid + ": stable pair/case ID")
            require(case["selection_mechanism"] == ("random" if primary < 6 else "enriched"),
                    rid + ": 6 random + 6 enriched")
            require(case["parameters"] == case_parameters(profile, radiations[condition["radiation_id"]]),
                    rid + ": parameters/units")
            require(case["training_eligible"] is (case["split"] == "development")
                    and case["native_random_statistics_eligible"] is (primary < 6), rid + ": allowed use")
            control = by_id.get(case["control_case_id"])
            require(control is not None and control["kind"] == "control"
                    and control["profile_id"] == case["profile_id"]
                    and control["stored_bit"] == case["stored_bit"], rid + ": matching reusable zero")
            require(case["control_pair_id"] is None and case["reusable_for_condition_ids"] == [],
                    rid + ": response/control roles")
            pairs[pair_id].append(case)
            per_condition[cid].append(case)
        else:
            require(case["kind"] == "control" and case["cohort"] == "control"
                    and case["budget_tier"] == "reusable_zero", rid + ": control kind")
            require(all(case[k] is None for k in ("pair_id", "primary_index", "condition_id", "control_case_id")),
                    rid + ": controls are not primary events")
            require(rid == control_id(case["profile_id"], case["stored_bit"])
                    and case["control_pair_id"] == "m1-r05-%s-zero" % token(case["profile_id"]),
                    rid + ": stable control identity")
            require(case["selection_mechanism"] == "no_particle_control"
                    and case["training_eligible"] is False
                    and case["native_random_statistics_eligible"] is False, rid + ": zero is not negative sample")
            held_out = profile["partition"] == "device_holdout"
            require(case["split"] == ("device_holdout" if held_out else "development_control")
                    and case["holdout"] == ("device" if held_out else None), rid + ": control sealing")
            require(case["parameters"] == case_parameters(profile), rid + ": zero source parameters")
            require(case["reusable_for_condition_ids"] == [c["id"] for c in conditions.values()
                    if c["profile_id"] == case["profile_id"]], rid + ": control reuse scope")
            controls.append(case)
    require(len(pairs) == 216, "216 response primary pairs")
    for pair_id, members in pairs.items():
        require(len(members) == 2 and {c["stored_bit"] for c in members} == {0, 1}, pair_id + ": b0/b1")
        ignored = {"case_id", "stored_bit", "control_case_id"}
        require({k: v for k, v in members[0].items() if k not in ignored}
                == {k: v for k, v in members[1].items() if k not in ignored},
                pair_id + ": identical primary selection, provenance, parameters and split")
    require(set(per_condition) == set(conditions), "Every condition has response cases")
    for cid, members in per_condition.items():
        require(len(members) == 24 and Counter(c["selection_mechanism"] for c in members)
                == {"random": 12, "enriched": 12}, cid + ": 12 primaries x b0/b1")
        require(len({c["primary_index"] for c in members}) == 12, cid + ": unique planned primaries")
    tiers = Counter(c["budget_tier"] for c in data["cases"])
    require(tiers == {"core": 384, "reserve": 48, "reusable_zero": 12}, "384 / 48 / 12 tiers")
    require(Counter(c["profile_id"] for c in controls) == {pid: 2 for pid in profiles},
            "Two reusable zeros per profile")
    require(Counter(c["split"] for c in data["cases"] if c["kind"] == "response")
            == {"development": 192, "domain_holdout": 96, "high_energy_holdout": 48, "device_holdout": 96},
            "Training and holdout coverage")
    return dict(unique_cases=len(by_id), response_pairs=len(pairs), budget_tiers=dict(tiers),
                conditions=dict(Counter(c["cohort"] for c in conditions.values())),
                random_pairs=sum(m[0]["selection_mechanism"] == "random" for m in pairs.values()),
                enriched_pairs=sum(m[0]["selection_mechanism"] == "enriched" for m in pairs.values()),
                all_planned_unbound=True)


def main():
    # Files are always written directly by Python; never round-trip JSON through
    # a PowerShell native-command text pipeline or the Windows ANSI code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read and validate the fixed output; no writes")
    args = parser.parse_args()
    try:
        budget_sha = check_budget()
        if args.check:
            data = json.loads(OUTPUT.read_text(encoding="utf-8", errors="strict"))
        else:
            now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            data = build(now, budget_sha)
        summary = validate(data, budget_sha)
        require(data == build(data["updated_at"], budget_sha), "Manifest differs from its declared plan contract")
        if not args.check:
            with OUTPUT.open("w", encoding="utf-8", errors="strict", newline="\n") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
        print(json.dumps(dict(mode="check" if args.check else "build",
                              manifest=OUTPUT.relative_to(ROOT).as_posix(),
                              budget_sha256=budget_sha, **summary), ensure_ascii=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, "Case manifest error: %s\n" % exc)


if __name__ == "__main__":
    raise SystemExit(main())
