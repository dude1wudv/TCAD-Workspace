"""Audited full-pool proxy aggregation and deterministic SI-second rate conversion.

This module never fills an absent event, bit or state with a zero prediction.
Predictions remain model-derived proxies even after probability calibration.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from numbers import Real

from .data import bits_for


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
) -> dict:
    """Aggregate a complete uniform transport pool into a per-state proxy.

    ``primary_id`` indexes rows, while ``source_primary_id`` identifies an
    independent emitted primary. Consistent aliases of a source count once.
    TCAD enrichment does not exclude an event that belongs to the full
    transport pool; pool_member=False events never alter the denominator.
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
            for source_id in sorted(sources) for state in (0, 1) for bit_id in bit_ids
            if (source_id, state, bit_id) not in probabilities
        ]
        if missing:
            audit["missing_probability_count"] = len(missing)
            audit["first_missing_probability"] = list(missing[0])
            raise ValueError("incomplete event/state/bit predictions; missing is not a zero")
        n_primaries = len(sources)
        means_by_state = [
            [
                math.fsum(probabilities[source_id, state, bit] for bit in bit_ids) / n_bits
                for source_id in sorted(sources)
            ]
            for state in (0, 1)
        ]
        sigma = [area * math.fsum(means) / n_primaries for means in means_by_state]
        standard_errors = []
        for means in means_by_state:
            if n_primaries == 1:
                standard_errors.append(None)
            else:
                average = math.fsum(means) / n_primaries
                variance = math.fsum((value - average) ** 2 for value in means) / (n_primaries - 1)
                standard_errors.append(area * math.sqrt(variance / n_primaries))
        weight = 1.0 if probability_status == "calibrated" else 0.25
        return {
            **base,
            "status": "ready",
            "condition_id": condition_id,
            "sigma_cm2_per_bit": sigma,
            "sigma_unit": "cm2/bit",
            "weights": [weight, weight],
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
