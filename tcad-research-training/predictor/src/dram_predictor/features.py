"""Fold-fitted transforms with an explicit pre-/post-simulation feature boundary."""
from __future__ import annotations

import math
import numpy as np

from .data import DEVICE_FEATURES, F_FEATURES, SOURCE_FEATURES, DataError, LeakageError

LOG_FEATURES = {"acceptor_scale", "donor_scale", "acceptor_cm3", "donor_cm3",
                "capacitance_fF", "incident_energy_MeV"}
SOURCE_TIMING_FIELDS = ("source_time_ns", "deck_timing_version")
R_ONLY_FIELDS = frozenset(SOURCE_FEATURES + SOURCE_TIMING_FIELDS) | {
    "scale_factor", "selection_mechanism", "inclusion_probability",
}


def record(condition, primary=None, state=None, bit=None):
    result = dict(condition["features"])
    unknown = set(result) - set(F_FEATURES) - {"theta_deg", "phi_deg"}
    if unknown:
        raise LeakageError(f"Condition contains unapproved pre-simulation fields: {sorted(unknown)}")
    direction = ("direction_x", "direction_y", "direction_z")
    has_vector = any(k in result for k in direction)
    has_angles = "theta_deg" in result or "phi_deg" in result
    theta = math.radians(result.pop("theta_deg", 0.))
    phi = math.radians(result.pop("phi_deg", 0.))
    from_angles = (math.sin(theta)*math.cos(phi), math.sin(theta)*math.sin(phi), math.cos(theta))
    if has_vector:
        if not all(k in result and result[k] is not None for k in direction):
            raise DataError("Direction requires all three components")
        vector = tuple(float(result[k]) for k in direction)
        if not all(math.isfinite(v) for v in vector) or not math.isclose(
                sum(v*v for v in vector), 1., abs_tol=1e-6):
            raise DataError("Direction vector must be finite and have unit norm")
        if has_angles and not all(math.isclose(a, b, abs_tol=1e-6) for a, b in zip(vector, from_angles)):
            raise DataError("Incident angles and direction vector disagree")
    else:
        result.update(zip(direction, from_angles))
    result.update(condition["categories"])
    if primary is not None:
        result.update(primary["source_features"])
        scale = primary.get("scale_factor")
        if scale is not None:
            if (isinstance(scale, bool) or not isinstance(scale, (int, float))
                    or not math.isfinite(scale) or scale <= 0):
                raise DataError("scale_factor must be positive and finite")
            charge = result.get("generated_charge_fC")
            if charge is not None:
                result["generated_charge_fC"] = charge * scale
        for name in SOURCE_TIMING_FIELDS:
            if primary.get(name) is not None:
                result[name] = primary[name]
        result["source_off"] = float(primary["source_off"])
        if primary["source_off"]:
            # Irrelevant hit coordinates cannot create a residual for a fully off source.
            result = source_off_record(result)
    if state is not None:
        result["state"] = float(state)
    if bit is not None:
        result.update(bit_x_nm=bit["x_nm"], bit_y_nm=bit["y_nm"], bit_z_nm=bit["z_nm"])
    return result


def source_off_record(row):
    result = dict(row)
    for name in SOURCE_FEATURES:
        if name in result and (name != "deposited_energy_MeV" or not row.get("source_off")):
            result[name] = 0.
    result["source_off"] = 1.
    return result


class Encoder:
    def __init__(self, mode):
        if mode not in ("R", "F", "device"):
            raise ValueError(mode)
        self.mode = mode
        self.numeric = []
        self.categories = {}
        self.median = self.mean = self.std = self.low = self.high = None

    def _allowed(self):
        if self.mode == "device":
            return DEVICE_FEATURES + ("state",)
        if self.mode == "F":
            return F_FEATURES
        return F_FEATURES + SOURCE_FEATURES + ("state", "source_off", "bit_x_nm", "bit_y_nm", "bit_z_nm")

    def _matrix(self, rows):
        if self.mode == "F" and any(R_ONLY_FIELDS.intersection(row) for row in rows):
            raise LeakageError("F cannot consume deposited/source quantities or response metadata")
        a = np.empty((len(rows), len(self.numeric)), dtype=np.float64)
        for i, row in enumerate(rows):
            for j, name in enumerate(self.numeric):
                value = row.get(name)
                a[i, j] = np.nan if value is None else float(value)
                if name in LOG_FEATURES and np.isfinite(a[i, j]):
                    if a[i, j] <= 0:
                        raise DataError(f"{name} must be positive before log transform")
                    a[i, j] = np.log(a[i, j])
        if np.any(np.isinf(a)):
            raise DataError("Nonfinite feature")
        return a

    def fit(self, rows):
        if not rows:
            raise DataError("No training rows for preprocessing")
        self.numeric = [n for n in self._allowed() if any(r.get(n) is not None for r in rows)]
        names = ["structure_family"] if self.mode == "device" else ["structure_family", "particle"]
        self.categories = {n: sorted({str(r[n]) for r in rows}) for n in names}
        a = self._matrix(rows)
        self.median = np.nanmedian(a, axis=0)
        filled = np.where(np.isnan(a), self.median, a)
        self.mean = filled.mean(axis=0)
        self.std = filled.std(axis=0)
        self.std[self.std < 1e-12] = 1.
        self.low, self.high = np.nanmin(a, axis=0), np.nanmax(a, axis=0)
        return self

    def transform(self, rows):
        if self.mean is None:
            raise DataError("Encoder is not fitted")
        a = self._matrix(rows)
        missing = np.isnan(a)
        a = (np.where(missing, self.median, a) - self.mean) / self.std
        # A missing indicator avoids silently representing an imputed value as a measurement.
        parts = [a, missing.astype(float)]
        for key, values in self.categories.items():
            encoded = np.zeros((len(rows), len(values)))
            for i, row in enumerate(rows):
                value = str(row[key])
                if value not in values:
                    raise DataError(f"Unsupported categorical value: {key}={value}")
                encoded[i, values.index(value)] = 1.
            parts.append(encoded)
        return np.concatenate(parts, axis=1).astype(np.float32)

    @property
    def width(self):
        return 2 * len(self.numeric) + sum(len(v) for v in self.categories.values())

    def outside_support(self, rows):
        a = self._matrix(rows)
        return [sorted(self.numeric[j] for j in range(len(self.numeric))
                       if np.isfinite(a[i, j]) and (a[i, j] < self.low[j] or a[i, j] > self.high[j]))
                for i in range(len(rows))]

    def to_dict(self):
        return {"mode": self.mode, "numeric": self.numeric, "categories": self.categories,
                **{k: getattr(self, k).tolist() for k in ("median", "mean", "std", "low", "high")}}

    @classmethod
    def from_dict(cls, value):
        obj = cls(value["mode"])
        obj.numeric, obj.categories = value["numeric"], value["categories"]
        if not set(obj.numeric) <= set(obj._allowed()):
            raise LeakageError("Serialized encoder contains forbidden features")
        for k in ("median", "mean", "std", "low", "high"):
            setattr(obj, k, np.asarray(value[k], dtype=np.float64))
        return obj
