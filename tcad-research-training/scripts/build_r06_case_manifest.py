#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build/check the local r0.6 planning manifest; never runs TCAD or schedules work."""

import argparse
from collections import Counter
import datetime as dt
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "plans" / "dram-se-ddr5-lpddr5"
BUDGET_FILE = PLAN / "BUDGET-REVISION-r06-20261117.md"
OUTPUT = PLAN / "month-one-cases-r06.json"
REVISION = "r0.6"
TIMING_VERSION = "r06-hold-window-v1"
LHS_SEED = 20261117
LHS_BOUNDS = {
    "Lg": (0.8, 1.1),
    "Wfin": (0.8, 1.2),
    "Tox": (0.8, 1.2),
    "Hjc": (82.0, 92.0),
    "NA": (0.5, 2.0),
    "ND": (0.5, 2.0),
}
LOG_AXES = {"NA", "ND"}
MODEL_BASE_NM = {"Tox": 6.0, "Lsn": 20.0, "Lbl": 20.0, "Lgt": 14.0, "Wfin": 8.0, "Hfin": 35.0}
PROFILE_IDS = (
    "D0-nominal", "D1-short-channel", "D2-narrow-fin", "D3-low-acceptor",
    "LHS01-development", "LHS02-development", "LHS03-development",
    "LHS04-development", "LHS05-development", "LHS06-development",
    "H0-long-channel", "H1-lhs-holdout-a", "H2-lhs-holdout-b",
)
RADIATIONS = (
    ("G0", 1.0, 0.0, 0.0, "development"),
    ("G1", 5.0, 30.0, 0.0, "development"),
    ("G2", 20.0, 60.0, 90.0, "development"),
    ("G3", 58.0, 0.0, 0.0, "development"),
    ("G4", 98.0, 30.0, 90.0, "development"),
    ("G5", 120.0, 60.0, 0.0, "development"),
    ("C0", 5.0, 0.0, 0.0, "development"),
    ("C1", 58.0, 30.0, 0.0, "development"),
    ("C2", 20.0, 45.0, 90.0, "radiation_holdout"),
    ("C3", 150.0, 60.0, 90.0, "radiation_holdout"),
)
DEV_RADIATION_IDS = tuple(r[0] for r in RADIATIONS if r[4] == "development")
HOLDOUT_RADIATION_IDS = tuple(r[0] for r in RADIATIONS if r[4] == "radiation_holdout")
RADIATION_BY_ID = {
    rid: {"id": rid, "particle": "proton", "energy_MeV": e, "theta_deg": theta, "phi_deg": phi, "role": role}
    for rid, e, theta, phi, role in RADIATIONS
}
ANCHORS = {
    "D0-nominal": {},
    "D1-short-channel": {"Lg": 0.8},
    "D2-narrow-fin": {"Wfin": 0.8},
    "D3-low-acceptor": {"NA": 0.5},
}
THRESHOLD_TEMPLATES = (
    ("shape-a", "G0"),
    ("shape-b", "C1"),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def budget_sha():
    return hashlib.sha256(BUDGET_FILE.read_bytes()).hexdigest()


def transformed(value, axis):
    return math.log(value) if axis in LOG_AXES else value


def _normalized_scales(bounds, log_axes):
    return {
        axis: (math.log(hi) if axis in log_axes else hi) - (math.log(lo) if axis in log_axes else lo)
        for axis, (lo, hi) in bounds.items()
    }


def pair_distance(left, right, bounds, log_axes, scales=None):
    if scales is None:
        scales = _normalized_scales(bounds, log_axes)
    distance = 0.0
    for axis in bounds:
        delta = (transformed(left[axis], axis) - transformed(right[axis], axis)) / scales[axis]
        distance += delta * delta
    return math.sqrt(distance)


def min_pairwise_distance(points, bounds, log_axes, anchors=None):
    scales = _normalized_scales(bounds, log_axes)
    best = math.inf
    for left, right in itertools.combinations(points, 2):
        best = min(best, pair_distance(left, right, bounds, log_axes, scales))
    if anchors:
        for point in points:
            for anchor in anchors:
                best = min(best, pair_distance(point, anchor, bounds, log_axes, scales))
    return best


def one_lhs(n, bounds, log_axes, rng):
    points = [dict() for _ in range(n)]
    for axis, (low, high) in bounds.items():
        permutation = list(range(n))
        rng.shuffle(permutation)
        for i, bucket in enumerate(permutation):
            u = (bucket + rng.random()) / n
            if axis in log_axes:
                value = math.exp(math.log(low) + u * (math.log(high) - math.log(low)))
            else:
                value = low + u * (high - low)
            points[i][axis] = value
    return points


def anchor_points():
    result = []
    for pid in ANCHORS:
        row = {axis: 1.0 for axis in ("Lg", "Wfin", "Tox", "NA", "ND")}
        row["Hjc"] = 82.0
        row.update(ANCHORS[pid])
        result.append(row)
    return result


def maximin_lhs(n, bounds=LHS_BOUNDS, log_axes=LOG_AXES, seed=LHS_SEED, candidates=10000, anchors=None):
    """Anchor-aware maximin LHS; when anchors are supplied, maximize min(self, to_anchors)."""
    rng = random.Random(seed)
    best = None
    best_score = -1.0
    for _ in range(candidates):
        points = one_lhs(n, bounds, log_axes, rng)
        score = min_pairwise_distance(points, bounds, log_axes, anchors=anchors)
        if score > best_score:
            best, best_score = points, score
    return best, dict(
        seed=seed,
        candidate_designs=candidates,
        min_pairwise_distance=best_score,
        anchor_aware=bool(anchors),
        axes=list(bounds),
        log_axes=sorted(log_axes),
        point_count=n,
    )


def select_axiswise_sparse_holdouts(dev_points, bounds=LHS_BOUNDS, log_axes=LOG_AXES, seed=LHS_SEED + 1,
                                    candidates=10000, inset=0.08):
    """Sample 2 sparse holdouts inside each development-axis range.

    This construction does not verify membership in the joint convex hull.
    """
    dev_bounds = {
        axis: (min(p[axis] for p in dev_points), max(p[axis] for p in dev_points))
        for axis in bounds
    }
    scales = _normalized_scales(bounds, log_axes)
    rng = random.Random(seed)
    best = None
    best_score = -1.0
    for _ in range(candidates):
        pair = []
        for _idx in range(2):
            point = {}
            for axis, (lo, hi) in dev_bounds.items():
                u = inset + (1.0 - 2.0 * inset) * rng.random()
                if axis in log_axes:
                    point[axis] = math.exp(math.log(lo) + u * (math.log(hi) - math.log(lo)))
                else:
                    point[axis] = lo + u * (hi - lo)
            pair.append(point)
        d_pair = pair_distance(pair[0], pair[1], bounds, log_axes, scales)
        d_dev = min(pair_distance(h, d, bounds, log_axes, scales) for h in pair for d in dev_points)
        score = min(d_pair, d_dev)
        if score > best_score:
            best, best_score = pair, score
    margins = []
    for h in best:
        for axis, (lo, hi) in dev_bounds.items():
            v = transformed(h[axis], axis)
            tlo, thi = transformed(lo, axis), transformed(hi, axis)
            margins.append(min(v - tlo, thi - v) / scales[axis])
    evidence = {
        "seed": seed,
        "candidate_designs": candidates,
        "inset_fraction": inset,
        "min_distance_to_dev_and_pair": best_score,
        "min_normalized_interior_margin": min(margins),
        "support_geometry": "axiswise_development_bounding_box",
        "convex_hull_verified": False,
        "development_bounding_box": {k: [round(v[0], 8), round(v[1], 8)] for k, v in dev_bounds.items()},
    }
    return best, evidence


def random_lhs_scores(count, n, bounds=LHS_BOUNDS, log_axes=LOG_AXES, seed=7, anchors=None):
    rng = random.Random(seed)
    return [min_pairwise_distance(one_lhs(n, bounds, log_axes, rng), bounds, log_axes, anchors=anchors)
            for _ in range(count)]


def geometry_domain_ok(values):
    """Check against experiments/dram-se-r04/model/model.py box constraints."""
    lgt = MODEL_BASE_NM["Lgt"] * values["Lg"]
    wfin = MODEL_BASE_NM["Wfin"] * values["Wfin"]
    tox = MODEL_BASE_NM["Tox"] * values["Tox"]
    hjc = values["Hjc"]
    bl0 = 77.0 - MODEL_BASE_NM["Lbl"] / 2.0
    bl1 = 77.0 + MODEL_BASE_NM["Lbl"] / 2.0
    gate20 = bl0 - tox - lgt
    gate11 = bl1 + tox + lgt
    x0 = gate20 - tox - MODEL_BASE_NM["Lsn"]
    x1 = gate11 + tox + MODEL_BASE_NM["Lsn"]
    y0 = 20.0 - wfin / 2.0
    y1 = 20.0 + wfin / 2.0
    gate_y0 = y0 - tox - 6.0
    gate_y1 = y1 + tox + 6.0
    top, fin_top, fin_bottom = 250.0, 150.0, 150.0 - MODEL_BASE_NM["Hfin"]
    return (0.0 < x0 < x1 < 154.0 and 0.0 < gate_y0 < gate_y1 < 40.0
            and 0.0 < fin_bottom < fin_top < top - hjc < top)


def quantity(value, unit):
    return {"value": value, "unit": unit}


def profile_parameters(values):
    return {
        "Lg": quantity(round(values["Lg"], 8), "baseline_multiplier"),
        "Wfin": quantity(round(values["Wfin"], 8), "baseline_multiplier"),
        "Tox": quantity(round(values["Tox"], 8), "baseline_multiplier"),
        "Hjc": quantity(round(values["Hjc"], 8), "nm"),
        "NA": quantity(round(values["NA"], 8), "baseline_multiplier"),
        "ND": quantity(round(values["ND"], 8), "baseline_multiplier"),
    }


def crn_groups(profiles):
    result = {}
    for profile in profiles:
        pid = profile["id"]
        if pid in {"D0-nominal", "D3-low-acceptor"}:
            result[pid] = "crn-geometry-source-d0-d3"
        else:
            result[pid] = "crn-independent-" + pid.lower().replace("_", "-")
    return result


def build_profiles():
    anchors = anchor_points()
    lhs_dev, lhs_evidence = maximin_lhs(6, anchors=anchors)
    all_dev = anchors + lhs_dev
    holdout_pair, holdout_evidence = select_axiswise_sparse_holdouts(all_dev)
    lhs_evidence["axiswise_sparse_holdout_evidence"] = holdout_evidence

    values = []
    for pid, row in zip(ANCHORS, anchors):
        values.append((pid, "development", row, "anchor"))
    for index in range(6):
        values.append((PROFILE_IDS[4 + index], "development", lhs_dev[index], "anchor_aware_maximin_lhs"))
    holdout = {axis: 1.0 for axis in ("Lg", "Wfin", "Tox", "NA", "ND")}
    holdout["Hjc"] = 82.0
    holdout["Lg"] = 1.2
    values.append(("H0-long-channel", "profile_holdout", holdout, "extrapolation"))
    values.append(("H1-lhs-holdout-a", "profile_holdout", holdout_pair[0], "axiswise_interior_sparse_holdout"))
    values.append(("H2-lhs-holdout-b", "profile_holdout", holdout_pair[1], "axiswise_interior_sparse_holdout"))

    profiles = []
    groups = crn_groups([{"id": row[0]} for row in values])
    for pid, partition, row, origin in values:
        require(geometry_domain_ok(row), f"{pid}: violates model.py box constraints")
        profiles.append({
            "id": pid,
            "partition": partition,
            "origin": origin,
            "parameters": profile_parameters(row),
            "crn_group_id": groups[pid],
            "baseline_context": {
                "absolute_doping_profiles": None,
                "device_outer_length_nm": 154.0,
                "device_outer_width_nm": 40.0,
                "device_height_nm": 250.0,
                "effective_channel_length_nm": None,
                "electrical_feasibility": "pending_p0_z_whr_qualification",
            },
            "parameter_baseline_sha256": None,
        })
    return profiles, lhs_evidence


def radiation_rows():
    return [
        {
            "id": rid,
            "particle": "proton",
            "energy_MeV": e,
            "theta_deg": theta,
            "phi_deg": phi,
            "role": role,
            "units": {"energy_MeV": "MeV", "theta_deg": "deg", "phi_deg": "deg"},
        }
        for rid, e, theta, phi, role in RADIATIONS
    ]


def inclusion(method):
    if method == "simple_random":
        return {"method": "simple_random_without_replacement", "value": None,
                "formula": "n/N_primary", "frame_hash": None,
                "status": "pending_verified_complete_frame",
                "frozen_before_sampling": False, "freeze_before_sampling_required": True}
    if method == "stratified_pi":
        return {
            "method": "coarse_stratified_srswor",
            "value": None,
            "formula": "q_h/N_h",
            "stratum_key": "one_predeclared_coarse_partition_within_condition",
            "quota_contract_version": "r06-coarse-strata-v2",
            "frame_hash": None,
            "status": "pending_verified_complete_frame",
            "frozen_before_sampling": False,
            "freeze_before_sampling_required": True,
        }
    return None


def base_case(
    case_id,
    block,
    profile_id,
    bit,
    mechanism,
    *,
    pair_id=None,
    source_shape_id=None,
    radiation_id=None,
    radiation_pool_id=None,
    scale_factor=1.0,
    split="development",
    holdout=None,
    training_eligible=False,
    source_time=True,
    sample_index=None,
    statistics=None,
    extra=None,
):
    if statistics is None:
        statistics = mechanism in {"simple_random", "stratified_pi"}
    rad = RADIATION_BY_ID.get(radiation_id) if radiation_id else None
    payload = {
        "case_id": case_id,
        "block": block,
        "kind": "zero" if mechanism == "zero" else "response",
        "profile_id": profile_id,
        "stored_bit": bit,
        "pair_id": pair_id,
        "sample_index": sample_index,
        "source_shape_id": source_shape_id,
        "radiation_id": radiation_id,
        "energy_MeV": rad["energy_MeV"] if rad else None,
        "theta_deg": rad["theta_deg"] if rad else None,
        "phi_deg": rad["phi_deg"] if rad else None,
        "radiation_pool_id": radiation_pool_id,
        "scale_factor": scale_factor,
        "selection_mechanism": mechanism,
        "inclusion_probability": inclusion(mechanism),
        "statistics_intent": statistics,
        "statistics_eligible": False,
        "training_eligible": training_eligible,
        "split": split,
        "holdout": holdout,
        "source_time_ns": 22.0 if source_time else None,
        "deck_timing_version": TIMING_VERSION,
        "crn_group_id": None,
        "status": "planned",
        "task_id": None,
        "run_ids": [],
        "accepted": False,
        "acceptance_evidence": None,
        "parameter_baseline_sha256": None,
        "primary_provenance": {
            "transport_run_id": None,
            "event_id": None,
            "seed": None,
            "connected_group_id": None,
            "input_hash": None,
        },
        "selection_record": None,
        "scientific_label": None,
    }
    if statistics and bit == 0:
        payload["inclusion_probability"].update(
            formula="(q_h/N_h)*rho0",
            conditional_b0_probability=None,
            conditional_b0_formula="b0_count_in_cell/b1_count_in_cell",
            parent_b1_probability=None,
            matched_subset_required=True,
        )
    if extra:
        payload.update(extra)
    return payload


def add_case(cases, *args, **kwargs):
    cases.append(base_case(*args, **kwargs))


def dev_s_radiations(profile_index):
    """12 slots: all 8 dev pools once + 4 balanced rotating extras (15 total per pool)."""
    first_eight = list(DEV_RADIATION_IDS)
    extras = [DEV_RADIATION_IDS[(profile_index * 4 + k) % len(DEV_RADIATION_IDS)] for k in range(4)]
    return first_eight + extras


def dev_s_b0_indices(profile_index):
    """Pick 3 distinct radiation slots from the first 8 per profile, balanced across pools."""
    return sorted(((profile_index * 3 + k) % 8) for k in range(3))


def build(updated_at, budget_hash):
    profiles, lhs_evidence = build_profiles()
    profile_map = {p["id"]: p for p in profiles}
    radiations = radiation_rows()
    dev_profiles = [p["id"] for p in profiles if p["partition"] == "development"]
    anchor_profiles = ["D0-nominal", "D1-short-channel", "D2-narrow-fin", "D3-low-acceptor"]
    cases = []
    blocks = []

    # Block Z: 26 matched zero controls, also serving as mandatory P0/P1 WHR qualification
    for profile in profiles:
        is_dev = profile["partition"] == "development"
        pair_id = f"r06-z-{profile['id'].lower()}"
        for bit in (0, 1):
            add_case(
                cases,
                f"{pair_id}-b{bit}",
                "Z",
                profile["id"],
                bit,
                "zero",
                pair_id=pair_id,
                split="development_control" if is_dev else "profile_holdout",
                holdout=None if is_dev else "profile",
                source_time=False,
                extra={"p0_whr_qualification_required": True},
            )
    blocks.append({"id": "Z", "case_count": 26, "description": "profile matched zero controls & WHR qualification"})

    # Block T: 68 threshold calibration cases (adaptive bracketing; fixed b0 x10/x30 bug)
    # Schedule order: middle tier 10.0 first, then probe 3.0 or 30.0 (adaptable around bracket)
    b1_bracket_schedule = ((10.0, 1, "mid"), (3.0, 2, "low_or_bracket"), (30.0, 3, "high_or_bracket"))
    for profile in dev_profiles:
        for shape, ref_rad in THRESHOLD_TEMPLATES:
            for scale, order, role in b1_bracket_schedule:
                add_case(
                    cases,
                    f"r06-t-{profile.lower()}-{shape}-x{int(scale)}-b1",
                    "T",
                    profile,
                    1,
                    "threshold_scaled",
                    source_shape_id=shape,
                    radiation_id=ref_rad,
                    radiation_pool_id=ref_rad,
                    scale_factor=scale,
                    training_eligible=True,
                    extra={
                        "reference_radiation_id": ref_rad,
                        "adaptive_bracketing": True,
                        "bracket_order": order,
                        "bracket_role": role,
                    },
                )
    b0_scales = (("shape-a", "G0", 10.0, 1), ("shape-b", "C1", 30.0, 2))
    for profile in anchor_profiles:
        for shape, ref_rad, scale, order in b0_scales:
            add_case(
                cases,
                f"r06-t-{profile.lower()}-{shape}-x{int(scale)}-b0",
                "T",
                profile,
                0,
                "threshold_scaled",
                source_shape_id=shape,
                radiation_id=ref_rad,
                radiation_pool_id=ref_rad,
                scale_factor=scale,
                training_eligible=True,
                extra={
                    "reference_radiation_id": ref_rad,
                    "adaptive_bracketing": True,
                    "bracket_order": order,
                    "bracket_role": "b0_asymmetry_probe",
                },
            )
    blocks.append({"id": "T", "case_count": 68, "description": "adaptive threshold calibration"})

    # Block S: 150 stratified cases with explicit radiation_id and matched b0/b1 pairs
    for p_idx, profile in enumerate(dev_profiles):
        rads = dev_s_radiations(p_idx)
        b0_slots = set(dev_s_b0_indices(p_idx))
        for index, rad_id in enumerate(rads):
            pair_id = f"r06-s-{profile.lower()}-p{index:02d}" if index in b0_slots else None
            add_case(
                cases,
                f"r06-s-{profile.lower()}-p{index:02d}-b1",
                "S",
                profile,
                1,
                "stratified_pi",
                pair_id=pair_id,
                source_shape_id="pool-event",
                radiation_id=rad_id,
                radiation_pool_id="development-8",
                sample_index=index,
                training_eligible=True,
            )
            if index in b0_slots:
                add_case(
                    cases,
                    f"r06-s-{profile.lower()}-p{index:02d}-b0",
                    "S",
                    profile,
                    0,
                    "stratified_pi",
                    pair_id=pair_id,
                    source_shape_id="pool-event",
                    radiation_id=rad_id,
                    radiation_pool_id="development-8",
                    sample_index=index,
                    training_eligible=True,
                )
    blocks.append({"id": "S", "case_count": 150, "description": "development stratified responses"})

    # Block R: 12 simple_random anchor cases explicitly spanning all 8 development radiations
    for a_idx, profile in enumerate(anchor_profiles):
        for k in range(3):
            rad_id = DEV_RADIATION_IDS[(a_idx * 3 + k) % len(DEV_RADIATION_IDS)]
            add_case(
                cases,
                f"r06-r-{profile.lower()}-p{k:02d}-b1",
                "R",
                profile,
                1,
                "simple_random",
                radiation_id=rad_id,
                radiation_pool_id="development-8",
                sample_index=k,
                training_eligible=True,
            )
    blocks.append({"id": "R", "case_count": 12, "description": "random calibration responses"})

    # Block HR: 28 sealed radiation holdout cases (3 C2 + 3 C3 b1 + 1 paired b0 per anchor)
    for a_idx, profile in enumerate(anchor_profiles):
        b0_slot = 0 if a_idx % 2 == 0 else 3  # alternate C2 (slot 0) and C3 (slot 3) for b0
        for index in range(6):
            rad_id = "C2" if index < 3 else "C3"
            pair_id = f"r06-hr-{profile.lower()}-p{index:02d}" if index == b0_slot else None
            add_case(
                cases,
                f"r06-hr-{profile.lower()}-p{index:02d}-b1",
                "HR",
                profile,
                1,
                "stratified_pi",
                pair_id=pair_id,
                source_shape_id="pool-event",
                radiation_id=rad_id,
                radiation_pool_id="C2-C3-holdout",
                sample_index=index,
                split="radiation_holdout",
                holdout="radiation",
            )
            if index == b0_slot:
                add_case(
                    cases,
                    f"r06-hr-{profile.lower()}-p{index:02d}-b0",
                    "HR",
                    profile,
                    0,
                    "stratified_pi",
                    pair_id=pair_id,
                    source_shape_id="pool-event",
                    radiation_id=rad_id,
                    radiation_pool_id="C2-C3-holdout",
                    sample_index=index,
                    split="radiation_holdout",
                    holdout="radiation",
                )
    blocks.append({"id": "HR", "case_count": 28, "description": "sealed radiation holdout"})

    # Block HP: 30 sealed profile holdout cases (2 threshold + 6 stratified b1 + 2 paired b0 per holdout profile)
    holdout_profiles = ["H0-long-channel", "H1-lhs-holdout-a", "H2-lhs-holdout-b"]
    for h_idx, profile in enumerate(holdout_profiles):
        for index, scale in enumerate((3.0, 10.0)):
            add_case(
                cases,
                f"r06-hp-{profile.lower()}-threshold{index}-b1",
                "HP",
                profile,
                1,
                "threshold_scaled",
                source_shape_id="shape-a",
                radiation_id="G0",
                radiation_pool_id="G0",
                scale_factor=scale,
                split="profile_holdout",
                holdout="profile",
                extra={"reference_radiation_id": "G0"},
            )
        for index in range(6):
            rad_id = DEV_RADIATION_IDS[(h_idx * 2 + index) % len(DEV_RADIATION_IDS)]
            pair_id = f"r06-hp-{profile.lower()}-p{index:02d}" if index < 2 else None
            add_case(
                cases,
                f"r06-hp-{profile.lower()}-p{index:02d}-b1",
                "HP",
                profile,
                1,
                "stratified_pi",
                pair_id=pair_id,
                source_shape_id="pool-event",
                radiation_id=rad_id,
                radiation_pool_id="development-8",
                sample_index=index,
                split="profile_holdout",
                holdout="profile",
            )
            if index < 2:
                add_case(
                    cases,
                    f"r06-hp-{profile.lower()}-p{index:02d}-b0",
                    "HP",
                    profile,
                    0,
                    "stratified_pi",
                    pair_id=pair_id,
                    source_shape_id="pool-event",
                    radiation_id=rad_id,
                    radiation_pool_id="development-8",
                    sample_index=index,
                    split="profile_holdout",
                    holdout="profile",
                )
    blocks.append({"id": "HP", "case_count": 30, "description": "sealed profile holdout"})

    # Block AL: 82 unbound active-learning slots (dynamically assigned after P2 from dev pools)
    for index in range(82):
        batch_index = index // 4
        add_case(
            cases,
            f"r06-al-b{batch_index:02d}-p{index:03d}-b1",
            "AL",
            None,
            1,
            "active_learning",
            radiation_id=None,
            radiation_pool_id="development-8",
            sample_index=index,
            training_eligible=True,
            extra={
                "selection_policy": "dynamic_after_p2",
                "candidate_profile_pool": "development-10",
                "candidate_radiation_pool": "development-8",
                "batch_index": batch_index,
                "batch_size": 4 if index < 80 else 2,
            },
        )
    blocks.append({"id": "AL", "case_count": 82, "description": "active-learning reserve"})

    for case in cases:
        if case["profile_id"] is not None:
            case["crn_group_id"] = profile_map[case["profile_id"]]["crn_group_id"]

    data = {
        "schema_version": 1,
        "revision": REVISION,
        "updated_at": updated_at,
        "status": "planned",
        "plan_id": "dram-se-ddr5-lpddr5",
        "artifact_role": "planned_cases_not_execution_queue",
        "scientific_budget_source": {
            "path": BUDGET_FILE.relative_to(ROOT).as_posix(),
            "revision": REVISION,
            "sha256": budget_hash,
        },
        "budget": {
            "profile_count": 13,
            "development_profile_count": 10,
            "profile_holdout_count": 3,
            "block_case_counts": {b["id"]: b["case_count"] for b in blocks},
            "total_cases": len(cases),
            "zero_cases": 26,
            "threshold_cases": 74,
            "statistics_eligible_cases": sum(c["statistics_eligible"] for c in cases),
            "statistics_intent_cases": sum(c["statistics_intent"] for c in cases),
            "active_learning_cases": 82,
        },
        "timing_contract": {
            "source_time_ns": 22.0,
            "source_time_status": "candidate_pending_p0_evidence",
            "source_window_role": "SN1_hold_after_write_release_before_read",
            "hold_window_ns": [18.2, 30.0],
            "deck_timing_version": TIMING_VERSION,
            "p0_user_review_required": False,
            "execution_authorized": True,
            "p0_evidence_required": True,
            "p0_whr_z_qualification_all_profiles": True,
            "old_r04_source_time_ns": 15.003,
            "old_r04_is_statistics_eligible": False,
        },
        "sampling_contract": {
            "b1_priority": True,
            "b0_fraction_of_stratified_b1": "approximately_25_percent",
            "version": "r06-coarse-strata-v2",
            "selector": "scripts/r06_sampling.py",
            "condition_key": ["block", "profile_id", "radiation_id"],
            "stratum_key": "one_predeclared_coarse_partition_within_condition",
            "max_nonempty_strata": "q_b1",
            "all_nonempty_strata_positive_quota": True,
            "q1_rule": "uniform_srswor_over_complete_primary_frame",
            "inclusion_probability_formula": "q_h/N_h",
            "simple_random_probability_formula": "n/N_primary",
            "b0_selection": "uniform_matched_subset_of_same_cell_selected_b1",
            "b0_probability_formula": "pi1*(b0_count_in_cell/b1_count_in_cell)",
            "b0_unallocated_cell_inference": "forbidden",
            "zero_deposition_events": "retain_in_complete_frame_do_not_impute_y",
            "statistics_eligible_requires": [
                "verified_complete_frame", "frozen_valid_selection_and_weights",
                "all_selected_labels_scientifically_accepted",
            ],
            "probability_materialized_before_submission_required": True,
            "horvitz_thompson_estimator": "A_src/N_primary*sum(y_i/pi_i)",
            "simple_random_estimator": "A_src*k/n",
            "independent_s_r_draws": "allow_overlap_reuse_solves_keep_draws_separate",
            "union_estimator": "forbidden_without_separate_derivation",
            "threshold_and_active_learning_statistics_eligible": False,
            "threshold_adaptive_bracketing": True,
            "active_learning_dynamic_assignment": True,
            "crn_groups": "only identical transport geometry/material/source profiles may share",
        },
        "lhs_evidence": lhs_evidence,
        "blocks": blocks,
        "profiles": profiles,
        "radiations": radiations,
        "cases": cases,
    }
    validate(data, budget_hash)
    return data


def validate(data, budget_hash):
    require(data["schema_version"] == 1 and data["revision"] == REVISION and data["status"] == "planned", "schema")
    require(data["scientific_budget_source"]["sha256"] == budget_hash, "budget provenance")
    require(data["timing_contract"]["p0_user_review_required"] is False
            and data["timing_contract"]["execution_authorized"] is True
            and data["timing_contract"]["p0_evidence_required"] is True
            and data["timing_contract"]["source_time_status"] == "candidate_pending_p0_evidence",
            "authorized evidence-gated timing contract")
    require(len(data["profiles"]) == 13 and len({p["id"] for p in data["profiles"]}) == 13, "profiles")
    require(len(data["radiations"]) == 10 and len({r["id"] for r in data["radiations"]}) == 10, "radiations")
    require(len(data["cases"]) == 396 and len({c["case_id"] for c in data["cases"]}) == 396, "budget/id")
    require(sum(b["case_count"] for b in data["blocks"]) == 396, "block total")
    require(Counter(c["block"] for c in data["cases"]) == {"Z": 26, "T": 68, "S": 150, "R": 12, "HR": 28, "HP": 30, "AL": 82}, "blocks")
    require(sum(c["statistics_eligible"] for c in data["cases"]) == 0, "planned statistics count")
    require(sum(c["statistics_intent"] for c in data["cases"]) == 214, "statistics intent count")

    profile_map = {p["id"]: p for p in data["profiles"]}
    for profile in data["profiles"]:
        require(profile["crn_group_id"], profile["id"] + ": CRN")
        require(set(profile["parameters"]) == set(LHS_BOUNDS), profile["id"] + ": axes")
        vals = {k: v["value"] for k, v in profile["parameters"].items()}
        require(geometry_domain_ok(vals), profile["id"] + ": model.py geometry bounds")
    holdout_evidence = data["lhs_evidence"]["axiswise_sparse_holdout_evidence"]
    require(holdout_evidence["min_normalized_interior_margin"] > 0.0,
            "H1/H2 must be inside every development-axis range")
    require(holdout_evidence["support_geometry"] == "axiswise_development_bounding_box",
            "H1/H2 support geometry")
    require(holdout_evidence["convex_hull_verified"] is False,
            "H1/H2 must not be labeled as convex-hull interpolation")
    # Ensure no CRN group crosses development / profile_holdout
    dev_crns = {p["crn_group_id"] for p in data["profiles"] if p["partition"] == "development"}
    hold_crns = {p["crn_group_id"] for p in data["profiles"] if p["partition"] == "profile_holdout"}
    require(not (dev_crns & hold_crns), "CRN leakage across development and profile_holdout")

    s_b1_by_rad = Counter()
    s_b1_cells = set()
    r_rads = set()
    hr_counts = Counter()
    pairs = {}
    for case in data["cases"]:
        require(case["status"] == "planned" and case["task_id"] is None and case["run_ids"] == []
                and case["accepted"] is False, case["case_id"] + ": unbound")
        require(case["deck_timing_version"] == TIMING_VERSION, case["case_id"] + ": timing")
        if case["kind"] == "response":
            require(case["source_time_ns"] == 22.0, case["case_id"] + ": source time")
        else:
            require(case["source_time_ns"] is None and case["statistics_eligible"] is False, case["case_id"] + ": zero")
        require(case["statistics_eligible"] is False, case["case_id"] + ": planned is not eligible")
        if case["statistics_intent"]:
            require(case["inclusion_probability"] is not None, case["case_id"] + ": missing pi contract")
            require(case["inclusion_probability"]["value"] is None
                    and case["inclusion_probability"]["frame_hash"] is None
                    and case["inclusion_probability"]["frozen_before_sampling"] is False,
                    case["case_id"] + ": planned probability not materialized")
            require(case["radiation_id"] in RADIATION_BY_ID, case["case_id"] + ": missing radiation_id")
            rad = RADIATION_BY_ID[case["radiation_id"]]
            require((case["energy_MeV"], case["theta_deg"], case["phi_deg"])
                    == (rad["energy_MeV"], rad["theta_deg"], rad["phi_deg"]), case["case_id"] + ": radiation metadata")
        if case["selection_mechanism"] in {"threshold_scaled", "active_learning"}:
            require(case["statistics_eligible"] is False, case["case_id"] + ": synthetic/AL statistics")
        if case["selection_mechanism"] == "threshold_scaled":
            require(case["scale_factor"] > 1.0, case["case_id"] + ": threshold scale must exceed 1.0")
            require(case["radiation_id"] in DEV_RADIATION_IDS, case["case_id"] + ": threshold reference radiation")
        if case["block"] == "AL":
            require(case["profile_id"] is None and case["radiation_id"] is None and case["crn_group_id"] is None,
                    case["case_id"] + ": AL must remain dynamically unbound")
        else:
            require(case["profile_id"] in profile_map, case["case_id"] + ": unknown profile_id")
        if case["block"] == "S":
            require(case["radiation_id"] in DEV_RADIATION_IDS, case["case_id"] + ": S must use dev pool")
            if case["stored_bit"] == 1:
                s_b1_by_rad[case["radiation_id"]] += 1
                s_b1_cells.add((case["profile_id"], case["radiation_id"]))
        if case["block"] == "R":
            require(case["radiation_id"] in DEV_RADIATION_IDS, case["case_id"] + ": R must use dev pool")
            r_rads.add(case["radiation_id"])
        if case["block"] == "HR":
            require(case["radiation_id"] in HOLDOUT_RADIATION_IDS, case["case_id"] + ": HR must use C2/C3")
            if case["stored_bit"] == 1:
                hr_counts[(case["profile_id"], case["radiation_id"])] += 1
        if case["block"] == "HP" and case["statistics_intent"]:
            require(case["radiation_id"] in DEV_RADIATION_IDS, case["case_id"] + ": HP stratified uses dev pool")
        if case["pair_id"] is not None:
            pairs.setdefault(case["pair_id"], []).append(case)

    require(len(s_b1_cells) == 80, "every (dev_profile, dev_radiation) cell in S must have >=1 sample")
    require(all(s_b1_by_rad[r] == 15 for r in DEV_RADIATION_IDS), "S must allocate 15 b1 samples per dev pool")
    require(r_rads == set(DEV_RADIATION_IDS), "R must cover all 8 dev radiation pools")
    require(all(v == 3 for v in hr_counts.values()) and len(hr_counts) == 8, "HR must cover 3 C2 + 3 C3 per anchor")
    for pid, members in pairs.items():
        require(len(members) == 2 and {c["stored_bit"] for c in members} == {0, 1}, pid + ": b0/b1 pair")
        require(members[0]["profile_id"] == members[1]["profile_id"]
                and members[0]["radiation_id"] == members[1]["radiation_id"], pid + ": pair alignment")
    require(all(c["inclusion_probability"]["value"] is None
                and c["inclusion_probability"]["formula"] == "n/N_primary"
                for c in data["cases"] if c["selection_mechanism"] == "simple_random"), "random pi")
    return {
        "cases": len(data["cases"]),
        "statistics_eligible": sum(c["statistics_eligible"] for c in data["cases"]),
        "matched_pairs": len(pairs),
        "planned_unbound": True,
    }


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read and validate output without writing")
    args = parser.parse_args()
    try:
        digest = budget_sha()
        if args.check:
            data = json.loads(OUTPUT.read_text(encoding="utf-8", errors="strict"))
        else:
            stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            data = build(stamp, digest)
        summary = validate(data, digest)
        require(data == build(data["updated_at"], digest), "manifest differs from deterministic plan")
        if not args.check:
            with OUTPUT.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
        print(json.dumps({"mode": "check" if args.check else "build", "manifest": OUTPUT.relative_to(ROOT).as_posix(), **summary}, ensure_ascii=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(1, "r06 manifest error: %s\n" % exc)


if __name__ == "__main__":
    raise SystemExit(main())
