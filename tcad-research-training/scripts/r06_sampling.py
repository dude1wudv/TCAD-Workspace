#!/usr/bin/env python3
"""Freeze one condition's complete primary frame and draw SRSWOR samples locally.

No solver, scheduler, or training. Frames require a verified full primary ledger,
including zero-deposition events. This tool validates the declared evidence and
hash bindings; external transport-ledger verification remains the producer's job.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import re
import sys

FRAME_SCHEMA = "r06-primary-frame-v1"
SELECTION_SCHEMA = "r06-frozen-sample-v1"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")).hexdigest()


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def finite_number(value, positive=False):
    return (type(value) in (int, float) and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def validate_frame(frame):
    require(isinstance(frame, dict) and frame.get("schema") == FRAME_SCHEMA, "frame schema")
    for key in ("frame_id", "transport_run_id"):
        require(isinstance(frame.get(key), str) and bool(frame[key]), "missing " + key)
    require(valid_hash(frame.get("transport_input_sha256")), "transport input hash")
    require(valid_hash(frame.get("response_context_sha256")),
            "response context hash must bind electrical/source-mapping/timing/label contracts")
    require(frame.get("complete_primary_ledger_verified") is True
            and valid_hash(frame.get("frame_evidence_sha256")), "unverified complete primary ledger")
    condition = frame.get("condition")
    require(isinstance(condition, dict) and all(
        isinstance(condition.get(k), str) and condition[k]
        for k in ("profile_id", "radiation_id")), "one explicit frame condition required")
    n = frame.get("N_primary")
    require(type(n) is int and n > 0, "N_primary must be positive integer")
    require(finite_number(frame.get("source_area_cm2"), positive=True), "source area cm2")
    events = frame.get("events")
    require(isinstance(events, list) and len(events) == n, "complete frame event count differs from N_primary")
    ids = []
    for event in events:
        require(isinstance(event, dict), "event object required")
        event_id = event.get("event_id")
        require(isinstance(event_id, str) and bool(event_id), "missing event ID; encode IDs as strings")
        ids.append(event_id)
        require(finite_number(event.get("deposition_energy_eV")), "missing/invalid deposition energy")
        require("coarse_stratum" not in event or (
            isinstance(event["coarse_stratum"], str) and bool(event["coarse_stratum"])),
            "coarse_stratum must be one predeclared label")
    require(len(set(ids)) == n, "duplicate event IDs in frame")
    return sorted(events, key=lambda event: event["event_id"])


def _strata(events, q, method):
    if method == "simple_random" or q == 1:
        return [("all", events, sorted({e.get("coarse_stratum", "all") for e in events}))]
    declared = ["coarse_stratum" in event for event in events]
    require(all(declared) or not any(declared), "missing coarse stratum on part of frame")
    groups = defaultdict(list)
    for event in events:
        groups[event.get("coarse_stratum", "all")].append(event)
    labels = sorted(groups)
    count = min(q, len(labels))
    # Deterministic adjacent-label merging; no outcome or TCAD label is consulted.
    bins = [[] for _ in range(count)]
    originals = [[] for _ in range(count)]
    for index, label in enumerate(labels):
        bucket = index * count // len(labels)
        bins[bucket].extend(groups[label])
        originals[bucket].append(label)
    return [("h" + str(i), sorted(rows, key=lambda e: e["event_id"]), originals[i])
            for i, rows in enumerate(bins)]


def select(frame, q, seed, *, expected_frame_sha256, method="stratified", b0_count=0):
    """Freeze design, allocate positive quotas, draw b1 then uniform matched b0."""
    events = validate_frame(frame)
    require(valid_hash(expected_frame_sha256) and digest(frame) == expected_frame_sha256,
            "complete frame hash differs")
    require(type(q) is int and 1 <= q <= len(events), "q outside complete frame")
    require(type(seed) is int and 0 <= seed < 2 ** 64, "seed must be uint64")
    require(method in ("stratified", "simple_random"), "unsupported sampling method")
    require(type(b0_count) is int and 0 <= b0_count <= q, "b0 count outside selected b1")
    strata = _strata(events, q, method)
    quotas = [1] * len(strata)
    for unused in range(q - len(strata)):
        # Allocate remaining quota to the least-sampled population fraction.
        available = [i for i, (_, rows, _) in enumerate(strata) if quotas[i] < len(rows)]
        chosen = max(available, key=lambda i: (len(strata[i][1]) / quotas[i], -i))
        quotas[chosen] += 1
    design = {
        "frame_sha256": expected_frame_sha256, "seed": seed, "q": q,
        "method": method, "b0_count": b0_count,
        "algorithm": "python-random-sample-sorted-ids-v1",
        "python_version": sys.version.split()[0],
        "strata": [{"stratum_id": key, "N_h": len(rows), "q_h": quota,
                    "merged_labels": labels, "event_ids": [e["event_id"] for e in rows]}
                   for (key, rows, labels), quota in zip(strata, quotas)],
    }
    frozen_design_sha256 = digest(design)  # established before any random draws
    rng = random.Random(seed)
    selected = []
    for (key, rows, unused_labels), quota in zip(strata, quotas):
        for event in rng.sample(rows, quota):
            selected.append({
                "event_id": event["event_id"], "stratum_id": key,
                "pi1": quota / len(rows),
                "deposition_energy_eV": event["deposition_energy_eV"],
            })
    selected.sort(key=lambda row: row["event_id"])
    b0_rng = random.Random(str(seed) + "|" + frozen_design_sha256 + "|b0")
    b0_ids = set(b0_rng.sample([row["event_id"] for row in selected], b0_count))
    rho0 = b0_count / q
    draws = []
    for row in selected:
        common = dict(row, conditional_b0_probability=rho0)
        draws.append(dict(common, stored_bit=1, inclusion_probability=row["pi1"]))
        if row["event_id"] in b0_ids:
            draws.append(dict(common, stored_bit=0,
                              inclusion_probability=row["pi1"] * rho0,
                              matched_b1_event_id=row["event_id"]))
    value = {
        "schema": SELECTION_SCHEMA, "status": "selected_not_scientifically_accepted",
        "frame_sha256": expected_frame_sha256, "frame_id": frame["frame_id"],
        "transport_run_id": frame["transport_run_id"],
        "transport_input_sha256": frame["transport_input_sha256"],
        "response_context_sha256": frame["response_context_sha256"],
        "condition": frame["condition"], "N_primary": frame["N_primary"],
        "source_area_cm2": frame["source_area_cm2"], "design": design,
        "frozen_design_sha256": frozen_design_sha256,
        "draws": draws, "statistics_eligible": False,
        "b0_condition_inference_supported": b0_count > 0,
        "scientific_labels": None,
    }
    value["selection_sha256"] = digest(value)
    return value


def validate_selection(frame, selection):
    require(isinstance(selection, dict) and selection.get("schema") == SELECTION_SCHEMA,
            "selection schema")
    design = selection.get("design", {})
    expected = select(
        frame, design.get("q"), design.get("seed"),
        expected_frame_sha256=selection.get("frame_sha256"),
        method=design.get("method"), b0_count=design.get("b0_count"))
    require(selection == expected, "selection replay/hash/weights differ")
    return selection


def estimate(frame, selection, labels, *, stored_bit=1, estimator="ht"):
    """Estimate one draw's one-bit cross section only after complete label acceptance.

    No confidence interval or variance is asserted from one observation per layer.
    Independent S/R estimates must remain separate; this API cannot pool designs.
    """
    validate_selection(frame, selection)
    require(type(stored_bit) is int and stored_bit in (0, 1), "stored bit")
    require(estimator in ("ht", "srs"), "unsupported estimator; union designs forbidden")
    draws = [row for row in selection["draws"] if row["stored_bit"] == stored_bit]
    require(bool(draws), "no allocated b0 sample for this condition" if stored_bit == 0 else "empty draw")
    require(isinstance(labels, list), "label list required")
    indexed = {}
    for label in labels:
        require(isinstance(label, dict), "label object required")
        event_id = label.get("event_id")
        require(isinstance(event_id, str) and event_id not in indexed, "duplicate/missing label event ID")
        require(label.get("selection_sha256") == selection["selection_sha256"]
                and type(label.get("stored_bit")) is int and label["stored_bit"] == stored_bit,
                "label selection/bit binding differs")
        require(label.get("status") == "accepted" and label.get("accepted") is True
                and label.get("scientific_acceptance") == "accepted"
                and valid_hash(label.get("acceptance_evidence_sha256")),
                "all selected labels require scientific acceptance; planned is not accepted")
        require(type(label.get("y")) is int and label["y"] in (0, 1), "binary y required")
        indexed[event_id] = label
    require(set(indexed) == {row["event_id"] for row in draws},
            "missing or extra selected labels; never impute zero-deposition labels")
    area = frame["source_area_cm2"]
    if estimator == "srs":
        require(selection["design"]["method"] == "simple_random"
                or len(selection["design"]["strata"]) == 1, "ordinary SRS invalid for unequal layer weights")
        result = area * sum(label["y"] for label in labels) / len(draws)
        formula = "A_src*k/n"
    else:
        result = area / frame["N_primary"] * sum(
            indexed[row["event_id"]]["y"] / row["inclusion_probability"] for row in draws)
        formula = "A_src/N_primary*sum(y_i/pi_i)"
    return {
        "schema": "r06-cross-section-point-estimate-v1",
        "selection_sha256": selection["selection_sha256"], "stored_bit": stored_bit,
        "cross_section_cm2_per_observed_bit": result, "formula": formula,
        "N_primary": frame["N_primary"], "selected_primary_count": len(draws),
        "statistics_eligible": True, "uncertainty_assessed": False,
        "union_with_other_designs": "forbidden_without_separate_derivation",
    }


def reuse_plan(selections):
    """Deduplicate solver work while retaining every design's original draw.

    Identical original primary, condition and bit may reuse an accepted solution;
    reuse never creates extra independent primary events or a union estimator.
    """
    work = {}
    primaries = set()
    references = 0
    for selection in selections:
        require(isinstance(selection, dict) and valid_hash(selection.get("selection_sha256")),
                "selection hash required")
        payload = {k: v for k, v in selection.items() if k != "selection_sha256"}
        require(digest(payload) == selection["selection_sha256"], "selection hash differs")
        for row in selection["draws"]:
            primary = (selection["transport_run_id"], selection["transport_input_sha256"], row["event_id"])
            key = primary + (selection["response_context_sha256"],
                             digest(selection["condition"]), row["stored_bit"])
            primaries.add(primary)
            references += 1
            item = work.setdefault(key, {
                "transport_run_id": primary[0], "transport_input_sha256": primary[1],
                "event_id": primary[2], "condition": selection["condition"],
                "response_context_sha256": selection["response_context_sha256"],
                "stored_bit": row["stored_bit"], "design_references": [],
            })
            item["design_references"].append(selection["selection_sha256"])
    return {"solver_work": list(work.values()), "draw_references": references,
            "unique_original_primary_count": len(primaries),
            "independence_not_increased_by_reuse": True,
            "union_estimator": "not_implemented_forbidden_without_derivation"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("frame-hash", help="Validate full frame and print canonical SHA256")
    freeze.add_argument("frame", type=Path)
    draw = commands.add_parser("select", help="Select locally, never submit simulation")
    draw.add_argument("frame", type=Path)
    draw.add_argument("--frame-sha256", required=True)
    draw.add_argument("--q", required=True, type=int)
    draw.add_argument("--seed", required=True, type=int)
    draw.add_argument("--method", choices=("stratified", "simple_random"), default="stratified")
    draw.add_argument("--b0-count", type=int, default=0)
    draw.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        frame = json.loads(args.frame.read_text(encoding="utf-8"))
        validate_frame(frame)
        if args.command == "frame-hash":
            print(digest(frame))
        else:
            value = select(frame, args.q, args.seed, expected_frame_sha256=args.frame_sha256,
                           method=args.method, b0_count=args.b0_count)
            # Exclusive create prevents replacement of a frozen selection.
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
            print(json.dumps({"status": value["status"], "selection_sha256": value["selection_sha256"]}))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
