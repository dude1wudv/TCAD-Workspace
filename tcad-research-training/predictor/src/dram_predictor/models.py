"""Small numeric networks; no data loading, fitting, or solver calls at import."""

from __future__ import annotations

import math
from typing import Sequence

import torch
from torch import Tensor, nn
from torch.nn import functional as F


def _mlp(input_dim: int, hidden: Sequence[int], output_dim: int) -> nn.Sequential:
    if input_dim < 1 or not hidden or any(n < 1 for n in hidden):
        raise ValueError("MLP dimensions must be positive")
    layers: list[nn.Module] = []
    width = input_dim
    for next_width in hidden:
        layers.extend([nn.Linear(width, int(next_width)), nn.SiLU()])
        width = int(next_width)
    layers.append(nn.Linear(width, output_dim))
    return nn.Sequential(*layers)


def _rectangular_torch(t: Tensor, duration: Tensor, tau: Tensor) -> Tensor:
    u = t.clamp_min(0)
    elapsed = torch.minimum(u, duration)
    z = elapsed / tau
    safe_z = torch.where(z > 1e-5, z, torch.ones_like(z))
    exprel = torch.where(
        z > 1e-5, -torch.expm1(-z) / safe_z, 1 - z / 2 + z.square() / 6
    )
    safe_d = torch.where(duration > 0, duration, torch.ones_like(duration))
    pulse = elapsed / safe_d * exprel * torch.exp(-(u - duration).clamp_min(0) / tau)
    result = torch.where(duration == 0, torch.exp(-u / tau), pulse)
    return torch.where(t >= 0, result, torch.zeros_like(result))


class ResponseNet(nn.Module):
    """RC baseline + source-off-subtracted residual-current coefficients.

    The four default coefficients have charge units fC, each multiplying the
    exact RC response of one constant-current interval in the frozen window.
    They may be signed. Auxiliary port charge has its own head and is never
    defined as C*deltaV. The default constant-C capacitor output is a dependent
    physical quantity, not an independent validation measurement.
    """

    def __init__(
        self,
        input_dim: int,
        hidden: Sequence[int] = (64, 64),
        residual_bins: int = 4,
        mode: str = "hybrid",
        *,
        window_ns: float | None = None,
    ):
        super().__init__()
        if mode not in {"hybrid", "plain", "mechanism_only"}:
            raise ValueError("unknown response model mode")
        if residual_bins < 2:
            raise ValueError("at least two response basis coefficients are required")
        if window_ns is not None and (not math.isfinite(window_ns) or window_ns <= 0):
            raise ValueError("response window must be finite and positive")
        self.input_dim = int(input_dim)
        self.hidden = tuple(int(v) for v in hidden)
        self.residual_bins = int(residual_bins)
        self.mode = mode
        self.trainable_auxiliary = mode != "mechanism_only"
        self.network = (
            None if mode == "mechanism_only"
            else _mlp(input_dim, hidden, residual_bins + 3)
        )
        self.register_buffer(
            "response_window_ns", torch.tensor(float("nan") if window_ns is None else window_ns)
        )

    def forward(
        self,
        x: Tensor,
        x_off: Tensor,
        *,
        time_ns: Tensor,
        capacitance_fF: Tensor,
        tau_ns: Tensor,
        gain: Tensor,
        generated_charge_fC: Tensor,
        source_duration_ns: Tensor,
    ) -> dict[str, Tensor]:
        if x.ndim != 2 or x.shape[1] != self.input_dim or x_off.shape != x.shape:
            raise ValueError("response feature shape mismatch")
        if not torch.isfinite(x).all() or not torch.isfinite(x_off).all():
            raise ValueError("response features must be finite")
        batch = len(x)
        time_ns = torch.as_tensor(time_ns, dtype=x.dtype, device=x.device)
        if time_ns.ndim == 1:
            time_ns = time_ns.unsqueeze(0).expand(batch, -1)
        if time_ns.ndim != 2 or time_ns.shape[0] != batch or time_ns.shape[1] < 1:
            raise ValueError("time must be a common grid or one grid per response")
        if not torch.isfinite(time_ns).all():
            raise ValueError("response times must be finite")
        if time_ns.shape[1] > 1 and torch.any(torch.diff(time_ns, dim=1) <= 0):
            raise ValueError("response time grids must be strictly increasing")
        scalars = {}
        for key, value in (
            ("capacitance_fF", capacitance_fF), ("tau_ns", tau_ns), ("gain", gain),
            ("generated_charge_fC", generated_charge_fC),
            ("source_duration_ns", source_duration_ns),
        ):
            value = torch.as_tensor(value, dtype=x.dtype, device=x.device)
            if value.shape != (batch,) or not torch.isfinite(value).all():
                raise ValueError(f"{key} must have one finite value per response")
            scalars[key] = value[:, None]
        c, tau = scalars["capacitance_fF"], scalars["tau_ns"]
        duration, q = scalars["source_duration_ns"], scalars["generated_charge_fC"]
        if torch.any(c <= 0) or torch.any(tau <= 0) or torch.any(duration < 0) or torch.any(q < 0):
            raise ValueError("C/tau must be positive; source charge/duration nonnegative")
        baseline = scalars["gain"] * q / c * _rectangular_torch(time_ns, duration, tau)
        if self.mode == "mechanism_only":
            unsupported = x.new_full((batch,), float("nan"))
            return {
                "delta_voltage_V": baseline,
                "capacitor_charge_fC": baseline * c,
                "port_charge_fC": unsupported,
                "margin_V": unsupported.clone(),
                "upset_logit": unsupported.clone(),
                "residual_coefficients": x.new_zeros((batch, self.residual_bins)),
            }
        if torch.isnan(self.response_window_ns):
            horizon = time_ns.max().detach()
            if horizon <= 0:
                raise ValueError("the initial response grid needs a positive frozen window")
            # This is an input-grid contract, not a label-dependent fitted time.
            with torch.no_grad():
                self.response_window_ns.copy_(horizon)
        window = self.response_window_ns.to(dtype=x.dtype, device=x.device)
        outputs = self.network(x)
        if self.mode == "hybrid":
            off = self.network(x_off)
            coefficients = outputs[:, :self.residual_bins] - off[:, :self.residual_bins]
            width = window / self.residual_bins
            starts = torch.arange(self.residual_bins, dtype=x.dtype, device=x.device) * width
            kernels = _rectangular_torch(
                time_ns[:, :, None] - starts[None, None, :],
                width,
                tau[:, :, None],
            )
            wave = baseline + (kernels * coefficients[:, None, :]).sum(dim=-1) / c
            port_charge = outputs[:, self.residual_bins] - off[:, self.residual_bins]
        else:
            # A comparable-capacity free waveform approximation. It neither
            # receives a physics penalty nor uses RC tau/gain to form deltaV.
            coefficients = outputs[:, :self.residual_bins]
            knots = torch.linspace(0, 1, self.residual_bins, dtype=x.dtype, device=x.device)
            relative = (time_ns / window).clamp(0, 1)
            hats = (1 - (relative[:, :, None] - knots).abs() * (self.residual_bins - 1)).clamp_min(0)
            wave = (hats * coefficients[:, None, :]).sum(dim=-1)
            port_charge = outputs[:, self.residual_bins]
        return {
            "delta_voltage_V": wave,
            "capacitor_charge_fC": wave * c,
            "port_charge_fC": port_charge,
            "margin_V": outputs[:, self.residual_bins + 1],
            "upset_logit": outputs[:, self.residual_bins + 2],
            "residual_coefficients": coefficients,
        }


class CrossSectionNet(nn.Module):
    """Two state-specific positive cross sections; physical mixing is external."""

    def __init__(
        self, input_dim: int, hidden: Sequence[int] = (32, 32), sigma_scale: float = 1e-12
    ):
        super().__init__()
        if not math.isfinite(sigma_scale) or sigma_scale <= 0:
            raise ValueError("sigma_scale must be finite and positive")
        self.input_dim = int(input_dim)
        self.hidden = tuple(int(v) for v in hidden)
        self.network = _mlp(input_dim, hidden, 2)
        self.register_buffer("sigma_scale", torch.tensor(sigma_scale))

    def forward(self, x: Tensor) -> Tensor:
        if x.ndim != 2 or x.shape[1] != self.input_dim or not torch.isfinite(x).all():
            raise ValueError("cross-section features must be finite with the trained dimension")
        output = self.sigma_scale.to(dtype=x.dtype) * F.softplus(self.network(x))
        # This protects representability of a model output, not data labels:
        # zero observed counts remain exactly zero in the count likelihood.
        return output.clamp_min(torch.finfo(output.dtype).tiny)
