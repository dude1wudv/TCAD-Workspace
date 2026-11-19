"""Independent, read-only TCAD accounting; never submits or writes a ledger."""
from copy import deepcopy


class BudgetError(ValueError):
    pass


def count_tcad(attempts):
    """Charge every reservation regardless of outcome, including unknown exits."""
    labels = [a["label"] for a in attempts]
    if len(labels) != len(set(labels)):
        raise BudgetError("Duplicate attempt identity")
    tcad = [a for a in attempts if a["kind"] == "tcad"]
    for a in tcad:
        if type(a.get("corrective", False)) is not bool:
            raise BudgetError("Ambiguous corrective classification")
    corrective = sum(a.get("corrective", False) for a in tcad)
    return {
        "tcad_calls": len(tcad),
        "tcad_primary_calls": len(tcad) - corrective,
        "tcad_corrective_calls": corrective,
    }


def _validate(counts, limits):
    for key in ("tcad_calls", "tcad_primary_calls", "tcad_corrective_calls"):
        if type(counts.get(key)) is not int or counts[key] < 0:
            raise BudgetError("Invalid counter: " + key)
    if counts["tcad_calls"] != counts["tcad_primary_calls"] + counts["tcad_corrective_calls"]:
        raise BudgetError("TCAD counters do not reconcile")
    for counter, limit in (("tcad_calls", "tcad_total"),
                           ("tcad_primary_calls", "tcad_primary"),
                           ("tcad_corrective_calls", "tcad_corrective")):
        if counts[counter] > limits[limit]:
            raise BudgetError("Existing budget exceeded: " + limit)


def budget_view(original_budget, attempts):
    """Add a derived primary count, preserving and reconciling original counts."""
    counts = count_tcad(attempts)
    for key in ("tcad_calls", "tcad_corrective_calls"):
        if original_budget[key] != counts[key]:
            raise BudgetError("Original ledger disagrees with attempts: " + key)
    result = deepcopy(original_budget)
    result.update(counts)
    result["schema"] = "nuclear-closure-budget-view-r12"
    result["source_schema"] = original_budget["schema"]
    result["derived_only"] = True
    _validate(result, result["limits"])
    return result


def require_capacity(counts, limits, *, corrective):
    """Capacity only. Ownership, identity, repair and release gates remain required."""
    if type(corrective) is not bool:
        raise BudgetError("Explicit corrective classification required")
    _validate(counts, limits)
    proposed = dict(counts)
    proposed["tcad_calls"] += 1
    proposed["tcad_corrective_calls" if corrective else "tcad_primary_calls"] += 1
    _validate(proposed, limits)
    return proposed
