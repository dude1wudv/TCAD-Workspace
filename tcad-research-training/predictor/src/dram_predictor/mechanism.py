"""Training-side calibration of a local RC approximation.

The capacitance is a supplied physical input, not inferred from a profile name.
The RC relaxation and rectangular-source approximation must be justified by the
caller for the stated node/window.  Neither represents a complete DRAM readout.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

import numpy as np


def rectangular_response(time_ns, duration_ns, tau_ns) -> np.ndarray:
    """Unit-charge RC response; time is relative to injection.

    A rectangular current pulse of integral one produces
    tau/d * (1-exp(-min(t,d)/tau)) * exp(-max(t-d,0)/tau).
    The implementation avoids cancellation for short pulses and gives the
    impulse limit when duration is exactly zero. Negative time is causal zero.
    Inputs follow normal numpy broadcasting (batch scalars can use [:, None]).
    """
    t, d, tau = np.broadcast_arrays(
        np.asarray(time_ns, dtype=float),
        np.asarray(duration_ns, dtype=float),
        np.asarray(tau_ns, dtype=float),
    )
    if not (np.isfinite(t).all() and np.isfinite(d).all() and np.isfinite(tau).all()):
        raise ValueError("RC times, durations and time constants must be finite")
    if np.any(d < 0) or np.any(tau <= 0):
        raise ValueError("source duration must be nonnegative and tau positive")
    u = np.maximum(t, 0.0)
    elapsed = np.minimum(u, d)
    z = elapsed / tau
    safe_z = np.where(z > 1e-5, z, 1.0)
    exprel = np.where(
        z > 1e-5, -np.expm1(-z) / safe_z, 1.0 - z / 2.0 + z * z / 6.0
    )
    safe_d = np.where(d > 0, d, 1.0)
    pulse = elapsed / safe_d * exprel * np.exp(-np.maximum(u - d, 0.0) / tau)
    result = np.where(d == 0, np.exp(-u / tau), pulse)
    return np.where(t >= 0, result, 0.0)


def _matrix(value, rows: int | None = None) -> np.ndarray:
    a = np.asarray(value, dtype=float)
    if a.ndim != 2 or a.shape[1] < 1:
        raise ValueError("calibration features must be a two-dimensional numeric matrix")
    if rows is not None and len(a) != rows:
        raise ValueError("calibration feature and record counts differ")
    if not np.isfinite(a).all():
        raise ValueError("calibration features must be finite")
    return a


def _ridge(x: np.ndarray, y: np.ndarray, penalty: float) -> np.ndarray:
    design = np.column_stack([np.ones(len(x)), x])
    # The intercept is unpenalized; no profile-specific free parameters.
    regularizer = np.sqrt(penalty) * np.eye(design.shape[1])
    regularizer[0, 0] = 0.0
    coef = np.linalg.lstsq(
        np.vstack([design, regularizer]),
        np.concatenate([y, np.zeros(design.shape[1])]),
        rcond=None,
    )[0]
    if not np.isfinite(coef).all():
        raise ValueError("non-finite shared mechanism fit")
    return coef


def _trace(record: Mapping[str, Any], field: str):
    t = np.asarray(record["time_ns"], dtype=float)
    y = np.asarray(record[field], dtype=float)
    if t.ndim != 1 or y.shape != t.shape or len(t) < 2:
        raise ValueError("invalid calibration trace shape")
    if not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
        raise ValueError("calibration time must be finite and strictly increasing")
    return t, y


def _positive(record: Mapping[str, Any], key: str) -> float:
    value = float(record[key])
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f"{key} must be finite and positive")
    return value


class MechanismCalibrator:
    """Shared log-tau and signed-gain regressions, fitted on supplied records only."""

    VERSION = 1

    def __init__(self, ridge: float = 1e-4):
        if not np.isfinite(ridge) or ridge < 0:
            raise ValueError("ridge must be finite and nonnegative")
        self.ridge = float(ridge)
        self.feature_dim: int | None = None
        self.tau_coefficients: np.ndarray | None = None
        self.gain_coefficients: np.ndarray | None = None
        self.control_source_ids: list[str] = []
        self.response_source_ids: list[str] = []
        self.calibration_records: list[dict[str, Any]] = []

    def fit(
        self,
        control_x,
        controls: Sequence[Mapping[str, Any]],
        response_x,
        responses: Sequence[Mapping[str, Any]],
    ) -> "MechanismCalibrator":
        cx, rx = _matrix(control_x, len(controls)), _matrix(response_x, len(responses))
        if cx.shape[1] != rx.shape[1]:
            raise ValueError("control and response device feature dimensions differ")
        self.feature_dim = cx.shape[1]
        self.tau_coefficients = self.gain_coefficients = None
        self.control_source_ids = self._ids(controls, "control_id")
        self.response_source_ids = self._ids(responses, "response_id")
        self.calibration_records = []
        tau_rows, taus = [], []
        for i, record in enumerate(controls):
            entry = self._entry(record, "control", "control_id")
            try:
                if record.get("mechanism_validated") is not True:
                    raise ValueError("RC calibration applicability not established")
                _positive(record, "capacitance_fF")
                t, voltage = _trace(record, "voltage_V")
                ref = float(record["reference_voltage_V"])
                if not np.isfinite(ref):
                    raise ValueError("reference voltage must be finite")
                v = voltage - ref
                finite = np.isfinite(v)
                if not finite.any():
                    raise ValueError("no finite relaxation voltage")
                amplitude = np.max(np.abs(v[finite]))
                if amplitude == 0:
                    raise ValueError("zero control has no identifiable relaxation")
                good = finite & (np.abs(v) > amplitude * 1e-8)
                if good.sum() < 3:
                    raise ValueError("fewer than three identifiable relaxation points")
                if np.any(np.sign(v[good]) != np.sign(v[good][0])):
                    raise ValueError("relaxation crosses the declared reference")
                times = t[good] - t[good][0]
                logv = np.log(np.abs(v[good]))
                slope, intercept = np.linalg.lstsq(
                    np.column_stack([times, np.ones(len(times))]), logv, rcond=None
                )[0]
                if slope >= 0 or np.ptp(logv) < 1e-8:
                    raise ValueError("control does not identify a positive decay time")
                tau = -1.0 / slope
                if not np.isfinite(tau) or tau <= 0:
                    raise ValueError("non-finite relaxation time")
                tau_rows.append(i)
                taus.append(np.log(tau))
                entry.update(
                    status="used",
                    fitted_tau_ns=float(tau),
                    log_relaxation_rmse=float(
                        np.sqrt(np.mean((logv - (slope * times + intercept)) ** 2))
                    ),
                )
            except (KeyError, TypeError, ValueError) as exc:
                entry.update(status="skipped", reason=str(exc))
            self.calibration_records.append(entry)
        if not tau_rows:
            raise ValueError("no identifiable training-side RC control; no tau fabricated")
        self.tau_coefficients = _ridge(cx[tau_rows], np.asarray(taus), self.ridge)
        tau_response = self._tau(rx)
        gain_rows, gains = [], []
        for i, record in enumerate(responses):
            entry = self._entry(record, "response", "response_id")
            try:
                if record.get("mechanism_validated") is not True:
                    raise ValueError("irradiated calibration applicability not established")
                c = _positive(record, "capacitance_fF")
                q = float(record["generated_charge_fC"])
                duration = float(record["source_duration_ns"])
                if not np.isfinite(q) or q <= 0:
                    raise ValueError("zero/invalid source cannot identify collection gain")
                t, y = _trace(record, "delta_voltage_V")
                basis = q / c * rectangular_response(t, duration, tau_response[i])
                good = np.isfinite(y) & np.isfinite(basis)
                norm = float(np.dot(basis[good], basis[good]))
                if not good.any() or norm <= np.finfo(float).tiny:
                    raise ValueError("no identifiable irradiated response")
                gain = float(np.dot(basis[good], y[good]) / norm)
                if not np.isfinite(gain):
                    raise ValueError("non-finite signed collection gain")
                gain_rows.append(i)
                gains.append(gain)
                entry.update(
                    status="used",
                    fitted_gain=gain,
                    voltage_rmse=float(np.sqrt(np.mean((y[good] - gain * basis[good]) ** 2))),
                )
            except (KeyError, TypeError, ValueError) as exc:
                entry.update(status="skipped", reason=str(exc))
            self.calibration_records.append(entry)
        if not gain_rows:
            # A partially fitted object is never a usable prediction artifact.
            self.tau_coefficients = None
            raise ValueError("no identifiable training-side radiation response; no gain fabricated")
        self.gain_coefficients = _ridge(rx[gain_rows], np.asarray(gains), self.ridge)
        return self

    @staticmethod
    def _ids(records, key):
        ids = [str(record.get(key, "")) for record in records]
        if any(not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError(f"calibration {key} values must be nonempty and unique")
        return ids

    @staticmethod
    def _entry(record, kind, id_key):
        return {
            "kind": kind,
            "id": str(record[id_key]),
            **{key: copy.deepcopy(record[key]) for key in
               ("profile_id", "state", "source_hash", "run_id") if key in record},
        }

    def _tau(self, x):
        if self.tau_coefficients is None:
            raise ValueError("mechanism has not been calibrated")
        try:
            with np.errstate(over="raise", under="ignore", invalid="raise"):
                tau = np.exp(np.column_stack([np.ones(len(x)), x]) @ self.tau_coefficients)
        except FloatingPointError as exc:
            raise ValueError("mechanism extrapolation produced an invalid time constant") from exc
        if not np.isfinite(tau).all() or np.any(tau <= 0):
            raise ValueError("mechanism extrapolation produced an invalid time constant")
        return tau

    def predict(self, device_x) -> dict[str, np.ndarray]:
        x = _matrix(device_x)
        if self.feature_dim != x.shape[1] or self.gain_coefficients is None:
            raise ValueError("mechanism is unfitted or feature dimension differs")
        gain = np.column_stack([np.ones(len(x)), x]) @ self.gain_coefficients
        if not np.isfinite(gain).all():
            raise ValueError("mechanism extrapolation produced a non-finite gain")
        return {"tau_ns": self._tau(x), "gain": gain}

    def to_dict(self) -> dict[str, Any]:
        if self.tau_coefficients is None or self.gain_coefficients is None:
            raise ValueError("cannot serialize an uncalibrated mechanism")
        return {
            "version": self.VERSION,
            "formulation": "local_rc_rectangular_source_shared_ridge",
            "units": {"time": "ns", "capacitance": "fF", "charge": "fC", "voltage": "V"},
            "capacitance_source": "supplied_physical_input",
            "ridge": self.ridge,
            "feature_dim": self.feature_dim,
            "tau_coefficients": self.tau_coefficients.tolist(),
            "gain_coefficients": self.gain_coefficients.tolist(),
            "control_source_ids": list(self.control_source_ids),
            "response_source_ids": list(self.response_source_ids),
            "calibration_records": copy.deepcopy(self.calibration_records),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MechanismCalibrator":
        if payload.get("version") != cls.VERSION:
            raise ValueError("unsupported mechanism artifact version")
        result = cls(float(payload["ridge"]))
        result.feature_dim = int(payload["feature_dim"])
        if result.feature_dim < 1:
            raise ValueError("invalid mechanism feature dimension")
        for name in ("tau_coefficients", "gain_coefficients"):
            coef = np.asarray(payload[name], dtype=float)
            if coef.shape != (result.feature_dim + 1,) or not np.isfinite(coef).all():
                raise ValueError("invalid serialized mechanism coefficients")
            setattr(result, name, coef)
        result.control_source_ids = list(payload["control_source_ids"])
        result.response_source_ids = list(payload["response_source_ids"])
        result.calibration_records = copy.deepcopy(payload["calibration_records"])
        return result
