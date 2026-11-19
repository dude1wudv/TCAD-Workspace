"""Deterministic connected-provenance grouping, never a random split of waveform rows."""
from __future__ import annotations

import random
from dataclasses import dataclass

from .data import View, digest, LeakageError


def connected_groups(view: View) -> list[frozenset[str]]:
    parents = {p: p for p in view.profiles}

    def find(a):
        while parents[a] != a:
            parents[a] = parents[parents[a]]
            a = parents[a]
        return a

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parents[max(a, b)] = min(a, b)

    sources = {}
    for p in view.primaries:
        profile = view.snapshot.conditions[p["condition_id"]]["profile_id"]
        prior = sources.setdefault(("primary", p["source_primary_id"]), profile)
        union(profile, prior)
    for count in view.counts:
        profile = view.snapshot.conditions[count["condition_id"]]["profile_id"]
        for source in count["source_primary_ids"]:
            prior = sources.setdefault(("primary", source), profile)
            union(profile, prior)
    for c in view.controls:
        source = c.get("source_control_id", c["control_id"])
        prior = sources.setdefault(("control", source), c["profile_id"])
        union(prior, c["profile_id"])
    result = {}
    for condition in view.conditions:
        result.setdefault(find(condition["profile_id"]), set()).add(condition["condition_id"])
    return sorted((frozenset(x) for x in result.values()), key=lambda x: tuple(sorted(x)))


@dataclass(frozen=True)
class Fold:
    number: int
    train: View
    validation: View

    def to_dict(self):
        return {"fold": self.number, "train": self.train.footprint(),
                "validation": self.validation.footprint()}


def grouped_folds(view: View, n_splits=3, seed=20261116) -> list[Fold]:
    groups = connected_groups(view)
    if len(groups) < n_splits or n_splits < 2:
        raise LeakageError(f"Need {n_splits} independent source groups, found {len(groups)}; "
                           "do not split reused events to manufacture folds")
    # Labels never participate. Seed only resolves equal-size assignment ties.
    rng = random.Random(seed)
    rng.shuffle(groups)
    groups.sort(key=len, reverse=True)
    buckets = [set() for _ in range(n_splits)]
    for group in groups:
        index = min(range(n_splits), key=lambda i: (len(buckets[i]), i))
        buckets[index].update(group)
    folds = []
    for number, held in enumerate(buckets):
        training = view.snapshot.view(view.condition_ids - held)
        validation = view.snapshot.view(held)
        training.assert_disjoint(validation)
        folds.append(Fold(number, training, validation))
    return folds


def stopping_split(view: View, seed=20261116, fraction=.2) -> tuple[View, View] | None:
    groups = connected_groups(view)
    if len(groups) < 2:
        return None
    random.Random(seed).shuffle(groups)
    count = max(1, min(len(groups) - 1, round(len(groups) * fraction)))
    held = frozenset().union(*groups[:count])
    fit, stop = view.snapshot.view(view.condition_ids - held), view.snapshot.view(held)
    fit.assert_disjoint(stop)
    return fit, stop


def split_manifest(view: View, seed=20261116) -> dict:
    folds = grouped_folds(view, 3, seed)
    payload = {"schema_version": 1, "split_seed": seed, "labels_used_to_assign_groups": False,
               "development_fingerprint": view.fingerprint(),
               "connected_groups": [sorted(x) for x in connected_groups(view)],
               "folds": [f.to_dict() for f in folds],
               "sealed": {c: sorted(k for k, v in view.snapshot.conditions.items() if v["cohort"] == c)
                          for c in ("new_combination", "high_energy", "device_extrapolation")}}
    payload["split_hash"] = digest(payload)
    return payload
