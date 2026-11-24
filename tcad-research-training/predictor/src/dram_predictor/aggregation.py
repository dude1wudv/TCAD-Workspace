"""Full-pool proxy aggregation, r0.6 design-based estimation and SI-second rates.

This module never fills an absent event, bit or state with a zero prediction.
Predictions remain model-derived proxies even after probability calibration.
"""
from __future__ import annotations

import copy
import math
from collections import Counter
from collections.abc import Mapping
from numbers import Real

from .data import _sha256, bits_for, digest


_SIGMA_UNITS = {"cm2/bit", "cm^2/bit", "cm²/bit"}
_FLUX_UNITS = {"cm^-2 s^-1", "cm-2 s-1", "1/(cm2 s)", "cm⁻² s⁻¹"}


def _number(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{label} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


def _positive_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _identifier(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _unit_values(value, units, label):
    """Bare arrays use the API's named units; explicit unit payloads are checked."""
    if isinstance(value, Mapping):
        if value.get("unit") not in units:
            raise ValueError(f"{label} has unsupported units; expected {sorted(units)}")
        if "values" not in value:
            raise ValueError(f"{label} unit payload requires values")
        return value["values"]
    return value


def _pair(values, label):
    if isinstance(values, (str, bytes, Mapping)):
        raise ValueError(f"{label} must contain two numeric state values")
    try:
        values = list(values)
    except TypeError as exc:
        raise ValueError(f"{label} must contain two numeric state values") from exc
    if len(values) != 2:
        raise ValueError(f"{label} must contain exactly state 0 and state 1")
    return [_number(value, label) for value in values]


def _state_weights(state_weights):
    weights = _pair(state_weights, "state_weights")
    total = math.fsum(weights)
    # Tolerance only accommodates floating-point representation, not a physical
    # prior or a permission to silently normalize an arbitrary exposure vector.
    if not math.isclose(total, 1.0, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("state_weights must sum to one")
    return weights


def mix_cross_sections(sigma, state_weights) -> float:
    """Return cm2/bit for an explicitly specified mixture of the two states.

    ``sigma`` is a two-value array in cm2/bit, or
    ``{"values": [...], "unit": "cm2/bit"}``. Weights are probabilities,
    not primary counts; paired response states never double the exposure.
    """
    values = _pair(_unit_values(sigma, _SIGMA_UNITS, "sigma"), "sigma")
    weights = _state_weights(state_weights)
    result = math.fsum(s * w for s, w in zip(values, weights))
    if not math.isfinite(result):
        raise ValueError("mixed cross section overflows")
    return result


def rate_from_flux(sigma_by_bin, state_weights, integrated_flux_by_bin) -> float | None:
    """Return errors/(bit*s), or None when an external flux was not supplied.

    Each sigma row contains [state0, state1] in cm2/bit. Each corresponding
    flux is already integrated over that bin's energy/species/solid angle,
    in cm^-2 s^-1 on the same reference plane as sigma. A differential flux
    is not accepted as an explicit unit payload and is never integrated here.
    The caller must establish the reference-plane/bin mapping upstream.
    Arrays may be wrapped in {"values": ..., "unit": ...} to check their units.
    """
    matrix = _unit_values(sigma_by_bin, _SIGMA_UNITS, "sigma_by_bin")
    if isinstance(matrix, (str, bytes, Mapping)):
        raise ValueError("sigma_by_bin must be a nonempty matrix of state pairs")
    try:
        matrix = list(matrix)
    except TypeError as exc:
        raise ValueError("sigma_by_bin must be a nonempty matrix of state pairs") from exc
    if not matrix:
        raise ValueError("sigma_by_bin cannot be empty")
    weights = _state_weights(state_weights)
    mixtures = [mix_cross_sections(row, weights) for row in matrix]
    if integrated_flux_by_bin is None:
        return None
    flux = _unit_values(integrated_flux_by_bin, _FLUX_UNITS, "integrated_flux_by_bin")
    if isinstance(flux, (str, bytes, Mapping)):
        raise ValueError("integrated_flux_by_bin must contain one value per bin")
    try:
        flux = list(flux)
    except TypeError as exc:
        raise ValueError("integrated_flux_by_bin must contain one value per bin") from exc
    if len(flux) != len(mixtures):
        raise ValueError("flux and cross section bins must have equal lengths")
    flux = [_number(value, "integrated_flux_by_bin") for value in flux]
    result = math.fsum(s * f for s, f in zip(mixtures, flux))
    if not math.isfinite(result):
        raise ValueError("rate overflows")
    return result


def aggregate_condition(
    condition,
    primaries,
    probability_rows,
    *,
    provenance=None,
    probability_status="uncalibrated",
    states=(0, 1),
) -> dict:
    """Aggregate a complete uniform transport pool into a per-state proxy.

    ``primary_id`` indexes rows, while ``source_primary_id`` identifies an
    independent emitted primary. Consistent aliases of a source count once.
    TCAD enrichment does not exclude an event that belongs to the full
    transport pool; pool_member=False events never alter the denominator.
    Requested states each need complete predictions. Output arrays retain
    state 0 and state 1 positions, with None for an unrequested state.
    Invalid or incomplete input returns pending without any sigma field.
    """
    base = {
        "status": "pending",
        "condition_id": condition.get("condition_id") if isinstance(condition, Mapping) else None,
        "provenance": copy.deepcopy(provenance) if provenance is not None else {},
        "probability_status": probability_status,
        "label_kind": "model_derived_proxy",
        "native_truth": False,
    }
    audit = {
        "selected_primary_ids": [],
        "source_primary_ids": [],
        "excluded_nonpool_primary_ids": [],
        "ignored_probability_primary_ids": [],
    }
    base["aggregation_audit"] = audit
    try:
        if not isinstance(condition, Mapping):
            raise ValueError("condition must be a mapping")
        condition_id = _identifier(condition.get("condition_id"), "condition_id")
        if probability_status not in {"uncalibrated", "calibrated"}:
            raise ValueError("probability_status must be uncalibrated or calibrated")
        states = tuple(states)
        if (not states or any(type(state) is not int or state not in (0, 1) for state in states)
                or len(set(states)) != len(states)):
            raise ValueError("states must contain distinct integer states 0 or 1")
        if condition.get("source_distribution") != "uniform":
            raise ValueError("unweighted aggregation requires a declared uniform source")
        if condition.get("area_normalization_validated") is not True:
            raise ValueError("source-area/2D-to-3D normalization has not been validated")
        area = _number(condition.get("source_area_cm2"), "source_area_cm2", positive=True)
        n_bits = _positive_integer(condition.get("n_bits"), "n_bits")
        expected_count = _positive_integer(condition.get("primary_count"), "primary_count")
        bits = bits_for(condition)
        if not isinstance(bits, list) or len(bits) != n_bits:
            raise ValueError("physical bit positions do not match n_bits")
        bit_ids = []
        for bit in bits:
            if not isinstance(bit, Mapping) or "bit_id" not in bit:
                raise ValueError("each physical bit requires bit_id and position")
            bit_id = str(bit["bit_id"])
            if not bit_id or bit_id in bit_ids:
                raise ValueError("physical bit IDs must be unique and nonempty")
            for axis in ("x_nm", "y_nm", "z_nm"):
                value = bit.get(axis)
                if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                    raise ValueError(f"physical bit {bit_id} lacks finite {axis}")
            bit_ids.append(bit_id)
        rows = list(primaries.values()) if isinstance(primaries, Mapping) else list(primaries)
        aliases = {}
        sources = {}
        selected_primary_ids = []
        excluded = set()
        for primary in rows:
            if not isinstance(primary, Mapping):
                raise ValueError("primary records must be mappings")
            if primary.get("condition_id") != condition_id:
                continue
            primary_id = _identifier(primary.get("primary_id"), "primary_id")
            if primary.get("pool_member") is not True:
                excluded.add(primary_id)
                continue
            source_id = _identifier(primary.get("source_primary_id"), "source_primary_id")
            source_hash = _identifier(primary.get("source_hash"), "source_hash")
            if primary_id in aliases and aliases[primary_id] != source_id:
                raise ValueError("one primary_id aliases conflicting original sources")
            aliases[primary_id] = source_id
            if not isinstance(primary.get("source_off"), bool):
                raise ValueError("complete mapped source_off must be explicit")
            signature = (source_hash, primary["source_off"], primary.get("source_features", {}))
            if source_id in sources and sources[source_id] != signature:
                raise ValueError("duplicate original primary has conflicting source provenance")
            sources[source_id] = signature
            selected_primary_ids.append(primary_id)
        audit["selected_primary_ids"] = sorted(set(selected_primary_ids))
        audit["source_primary_ids"] = sorted(sources)
        audit["excluded_nonpool_primary_ids"] = sorted(excluded)
        audit["duplicate_source_alias_count"] = len(set(selected_primary_ids)) - len(sources)
        if set(aliases) & excluded:
            raise ValueError("primary_id has conflicting pool membership")
        if len(sources) != expected_count:
            raise ValueError(
                f"incomplete primary pool: expected {expected_count} distinct originals, "
                f"received {len(sources)}"
            )
        probabilities = {}
        ignored = set()
        for row in probability_rows:
            if not isinstance(row, Mapping):
                raise ValueError("probability rows must be mappings")
            primary_id = row.get("primary_id")
            if primary_id not in aliases:
                if isinstance(primary_id, str):
                    ignored.add(primary_id)
                continue
            if row.get("condition_id", condition_id) != condition_id:
                raise ValueError("probability condition disagrees with primary identity")
            state = row.get("state")
            if isinstance(state, bool) or not isinstance(state, int) or state not in (0, 1):
                raise ValueError("each probability requires state 0 or state 1")
            if state not in states:
                continue
            if "bit_id" not in row or str(row["bit_id"]) not in bit_ids:
                raise ValueError("probability refers to an absent or unknown physical bit")
            probability = _number(row.get("probability"), "probability")
            if probability > 1:
                raise ValueError("probability must lie in [0,1]")
            key = (aliases[primary_id], state, str(row["bit_id"]))
            if key in probabilities and probabilities[key] != probability:
                raise ValueError("duplicate original primary has conflicting probabilities")
            probabilities[key] = probability
        audit["ignored_probability_primary_ids"] = sorted(ignored)
        missing = [
            (source_id, state, bit_id)
            for source_id in sorted(sources) for state in states for bit_id in bit_ids
            if (source_id, state, bit_id) not in probabilities
        ]
        if missing:
            audit["missing_probability_count"] = len(missing)
            audit["first_missing_probability"] = list(missing[0])
            raise ValueError("incomplete event/state/bit predictions; missing is not a zero")
        n_primaries = len(sources)
        sigma = [None, None]
        standard_errors = [None, None]
        weights = [None, None]
        weight = 1.0 if probability_status == "calibrated" else 0.25
        for state in states:
            means = [
                math.fsum(probabilities[source_id, state, bit] for bit in bit_ids) / n_bits
                for source_id in sorted(sources)
            ]
            total = math.fsum(means)
            sigma[state] = area * total / n_primaries
            weights[state] = weight
            if n_primaries > 1:
                average = total / n_primaries
                variance = math.fsum((value - average) ** 2 for value in means) / (n_primaries - 1)
                standard_errors[state] = area * math.sqrt(variance / n_primaries)
        return {
            **base,
            "status": "ready",
            "condition_id": condition_id,
            "sigma_cm2_per_bit": sigma,
            "sigma_unit": "cm2/bit",
            "weights": weights,
            "weight_basis": "declared_probability_calibration_status",
            "n_primaries": n_primaries,
            "n_bits": n_bits,
            "source_area_cm2": area,
            "n_source_off_primaries": sum(signature[1] for signature in sources.values()),
            "transport_mc_standard_error_cm2_per_bit": standard_errors,
            "uncertainty_scope": (
                "Transport Monte Carlo standard error across independent uniform primaries, "
                "conditional on fixed probability predictions; excludes model/calibration error "
                "and is not a full prediction interval."
            ),
        }
    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        return {**base, "reason": str(exc)}


def _r06_draws(selection, case_draw_map, n, method):
    design = selection.get("design")
    if not isinstance(design, dict) or design.get("method") != method:
        raise ValueError("sampling method differs from the r0.6 block")
    q = _positive_integer(design.get("q"), "q")
    b0_count = design.get("b0_count")
    if type(b0_count) is not int or not 0 <= b0_count <= q:
        raise ValueError("invalid b0 allocation")
    if method == "simple_random" and b0_count:
        raise ValueError("block R has no b0 allocation")
    strata = design.get("strata")
    if not isinstance(strata, list) or not strata or (method == "simple_random" and len(strata) != 1):
        raise ValueError("incomplete design strata")
    sizes, quotas, membership = {}, {}, {}
    for layer in strata:
        if not isinstance(layer, dict):
            raise ValueError("invalid design stratum")
        h = _identifier(layer.get("stratum_id"), "stratum_id")
        size = _positive_integer(layer.get("N_h"), "N_h")
        quota = _positive_integer(layer.get("q_h"), "q_h")
        ids = layer.get("event_ids")
        if h in sizes or quota > size or not isinstance(ids, list) or len(ids) != size:
            raise ValueError("invalid stratum membership or quota")
        sizes[h], quotas[h] = size, quota
        for event in ids:
            event = _identifier(event, "stratum event_id")
            if event in membership:
                raise ValueError("strata repeat a primary")
            membership[event] = h
    if len(membership) != n or sum(quotas.values()) != q:
        raise ValueError("strata do not cover the complete denominator or draw quota")

    rho0 = b0_count / q
    draws = {}
    draw_rows = selection.get("draws")
    if not isinstance(draw_rows, list):
        raise ValueError("missing frozen draws")
    for row in draw_rows:
        if not isinstance(row, dict):
            raise ValueError("invalid frozen draw")
        event = _identifier(row.get("event_id"), "draw event_id")
        bit = row.get("stored_bit")
        h = membership.get(event)
        if (type(bit) is not int or bit not in (0, 1) or (event, bit) in draws
                or h is None or row.get("stratum_id") != h):
            raise ValueError("duplicate, outside-frame or mis-stratified draw")
        pi1 = quotas[h] / sizes[h]
        pi = pi1 if bit == 1 else pi1 * rho0
        if (_number(row.get("pi1"), "pi1", positive=True) != pi1
                or _number(row.get("conditional_b0_probability"), "conditional_b0_probability") != rho0
                or _number(row.get("inclusion_probability"), "inclusion_probability", positive=True) != pi):
            raise ValueError("frozen draw inclusion probability differs from the design")
        if bit == 0 and row.get("matched_b1_event_id") != event:
            raise ValueError("b0 draw lacks a matched b1 event")
        draws[event, bit] = (h, pi)
    b1 = {event for event, bit in draws if bit == 1}
    b0 = {event for event, bit in draws if bit == 0}
    if Counter(membership[event] for event in b1) != quotas or len(b0) != b0_count or not b0 <= b1:
        raise ValueError("incomplete stratum draws or b0 matched subset")

    case_ids = {}
    bindings = case_draw_map.get("case_draws")
    if not isinstance(bindings, list):
        raise ValueError("missing case/draw bindings")
    for row in bindings:
        if not isinstance(row, dict):
            raise ValueError("invalid case/draw binding")
        event = _identifier(row.get("event_id"), "bound event_id")
        bit = row.get("stored_bit")
        key = (event, bit)
        if type(bit) is not int or key not in draws or key in case_ids:
            raise ValueError("duplicate or unexpected case/draw binding")
        case_ids[key] = _identifier(row.get("case_id"), "case_id")
    if case_ids.keys() != draws.keys() or len(set(case_ids.values())) != len(draws):
        raise ValueError("incomplete or duplicate case/draw bindings")
    return sizes, draws, case_ids, rho0


def _r06_variance(sizes, outcomes_by_stratum, *, n, area, subsampled_b0):
    if subsampled_b0 and len(sizes) > 1:
        return None, "multi-stratum b0 subsampling requires a joint inclusion probability estimator"
    terms = []
    for h, size in sizes.items():
        ys = outcomes_by_stratum[h]
        count = len(ys)
        if count == size:
            continue
        if count < 2:
            return None, "non-census stratum has fewer than two observed outcomes"
        errors = sum(ys)
        sample_variance = errors * (count - errors) / (count * (count - 1))
        terms.append((size / n) ** 2 * (1 - count / size) * sample_variance / count)
    return area * (area * math.fsum(terms)), None


def estimate_r06_cross_section(
    selection,
    case_draw_map,
    labels,
    *,
    stored_bit: int,
    expected_selection_sha256: str,
    area_normalization_validated: bool,
) -> dict:
    """Estimate one r0.6 cell's SN1 cross section for one observed state.

    Supply the replay-verified selection.json and verified case-draw-map.json.
    Pin the canonical selection SHA from the independently verified admission.
    The caller attests to fixed uniform source-area normalization for this frame.
    Each label needs event_id, case_id, stored_bit, selection_sha256, integer y,
    status and scientific_acceptance both "accepted", accepted=True,
    acceptance_evidence_sha256, statistics_eligible=True, selection_mechanism,
    and scale_factor=1. Optional stratum_id and scalar inclusion_probability
    must match the frozen draw for that state.
    Invalid or incomplete evidence raises ValueError. Variance covers sampling
    from this finite frame only. Other blocks and states have separate estimates.
    """
    if type(stored_bit) is not int or stored_bit not in (0, 1):
        raise ValueError("stored_bit must be 0 or 1")
    if area_normalization_validated is not True:
        raise ValueError("source-area normalization has not been verified")
    if not isinstance(selection, dict) or selection.get("schema") != "r06-frozen-sample-v1":
        raise ValueError("r0.6 frozen sample receipt required")
    if not isinstance(case_draw_map, dict) or case_draw_map.get("schema") != "tcad-r06-cell-case-binding-v1":
        raise ValueError("r0.6 case/draw binding required")
    block = case_draw_map.get("block")
    if block not in ("R", "S", "HR", "HP"):
        raise ValueError("r0.6 estimation requires block R, S, HR or HP")
    method, mechanism = ("simple_random", "simple_random") if block == "R" else ("stratified", "stratified_pi")
    _sha256(expected_selection_sha256, "expected_selection_sha256")
    if any(doc.get("selection_sha256") != expected_selection_sha256 for doc in (selection, case_draw_map)):
        raise ValueError("selection SHA differs from the frozen binding")
    if digest({key: value for key, value in selection.items() if key != "selection_sha256"}) != expected_selection_sha256:
        raise ValueError("selection contents differ from the frozen SHA")
    condition = selection.get("condition")
    if not isinstance(condition, dict):
        raise ValueError("one selection condition required")
    for key in ("profile_id", "radiation_id"):
        if _identifier(condition.get(key), key) != case_draw_map.get(key):
            raise ValueError("selection condition differs from the frozen binding")
    for key in ("frame_sha256", "frozen_design_sha256", "response_context_sha256", "transport_input_sha256"):
        _sha256(selection.get(key), key)
    _sha256(case_draw_map.get("manifest_sha256"), "manifest_sha256")
    run_id = _identifier(selection.get("transport_run_id"), "transport_run_id")
    n = _positive_integer(selection.get("N_primary"), "N_primary")
    area = _number(selection.get("source_area_cm2"), "source_area_cm2", positive=True)
    sizes, draws, case_ids, rho0 = _r06_draws(selection, case_draw_map, n, method)
    expected = {event: draw for (event, bit), draw in draws.items() if bit == stored_bit}
    if not expected:
        raise ValueError("no allocated sample for the requested state")
    if not isinstance(labels, list):
        raise ValueError("label list required")
    outcomes = {}
    for row in labels:
        if not isinstance(row, dict):
            raise ValueError("label must be an object")
        event = _identifier(row.get("event_id"), "label event_id")
        if event not in expected or event in outcomes:
            raise ValueError("unexpected or duplicate selected label")
        if (row.get("selection_sha256") != expected_selection_sha256
                or row.get("case_id") != case_ids[event, stored_bit]
                or type(row.get("stored_bit")) is not int or row["stored_bit"] != stored_bit):
            raise ValueError("label selection, case or state differs from the frozen draw")
        if (row.get("selection_mechanism") != mechanism
                or _number(row.get("scale_factor"), "scale_factor", positive=True) != 1):
            raise ValueError("label must come from an unscaled probability-sampled response")
        if (row.get("statistics_eligible") is not True or row.get("accepted") is not True
                or row.get("status") != "accepted" or row.get("scientific_acceptance") != "accepted"):
            raise ValueError("every selected label requires scientific acceptance and statistical eligibility")
        _sha256(row.get("acceptance_evidence_sha256"), "acceptance_evidence_sha256")
        y = row.get("y")
        if type(y) is not int or y not in (0, 1):
            raise ValueError("selected label requires explicit integer y=0 or y=1")
        h, pi = expected[event]
        if (row.get("stratum_id", h) != h
                or _number(row.get("inclusion_probability", pi), "label inclusion_probability", positive=True) != pi):
            raise ValueError("label stratum or probability differs from the frozen draw")
        outcomes[event] = row
    if outcomes.keys() != expected.keys():
        raise ValueError("missing selected outcomes")

    outcomes_by_stratum = {h: [] for h in sizes}
    for event, (h, _) in expected.items():
        outcomes_by_stratum[h].append(outcomes[event]["y"])
    sigma = area * (math.fsum(outcomes[event]["y"] / pi for event, (_, pi) in expected.items()) / n)
    variance, variance_reason = _r06_variance(
        sizes, outcomes_by_stratum, n=n, area=area, subsampled_b0=stored_bit == 0 and rho0 < 1
    )
    if not math.isfinite(sigma) or (variance is not None and not math.isfinite(variance)):
        raise ValueError("cross section or sampling variance overflows")
    return {
        "schema": "r06-design-based-cross-section-v1",
        "estimator": "horvitz_thompson",
        "formula": "A_src/N_primary*sum(y_i/pi_i)",
        "block": block,
        "condition": dict(condition),
        "stored_bit": stored_bit,
        "conditional_b0_probability": rho0 if stored_bit == 0 else None,
        "statistics_eligible": True,
        "N_primary": n,
        "source_area_cm2": area,
        "selected_primary_count": len(expected),
        "cross_section_cm2_per_observed_bit": sigma,
        "design_variance_cm4_per_observed_bit_squared": variance,
        "variance_unavailable_reason": variance_reason,
        "manifest_sha256": case_draw_map["manifest_sha256"],
        "selection_sha256": expected_selection_sha256,
        "frame_sha256": selection["frame_sha256"],
        "frozen_design_sha256": selection["frozen_design_sha256"],
        "transport_run_id": run_id,
        "transport_input_sha256": selection["transport_input_sha256"],
        "response_context_sha256": selection["response_context_sha256"],
        "selected_draws": [
            {"event_id": event, "case_id": case_ids[event, stored_bit], "stratum_id": h,
             "inclusion_probability": pi, "y": outcomes[event]["y"],
             "acceptance_evidence_sha256": outcomes[event]["acceptance_evidence_sha256"]}
            for event, (h, pi) in expected.items()
        ],
    }
