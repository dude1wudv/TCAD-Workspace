"""Masked losses with no arithmetic on unavailable labels."""

from __future__ import annotations

import torch
from torch import Tensor
from torch.nn import functional as F


def _expand(value, like: Tensor, *, boolean=False) -> Tensor:
    value = torch.as_tensor(
        value, dtype=torch.bool if boolean else like.dtype, device=like.device
    )
    if value.ndim == 1 and like.ndim > 1 and len(value) == len(like):
        value = value.reshape(len(value), *([1] * (like.ndim - 1)))
    try:
        return torch.broadcast_to(value, like.shape)
    except RuntimeError as exc:
        raise ValueError("loss argument cannot broadcast to prediction shape") from exc


def _select(pred: Tensor, target, mask):
    target = _expand(target, pred)
    mask = _expand(mask, pred, boolean=True)
    # Index before subtracting/transforming: masked NaNs cannot contaminate
    # gradients through torch.where's unselected arithmetic branch.
    p, y = pred[mask], target[mask]
    if not torch.isfinite(p).all() or not torch.isfinite(y).all():
        raise ValueError("unmasked predictions and labels must be finite")
    return p, y, mask


def _empty(pred: Tensor) -> Tensor:
    # Unlike pred.sum()*0, this remains zero when every masked prediction is NaN.
    return pred.reshape(-1)[:0].sum()


def _scale(scale, pred, mask):
    scale = _expand(scale, pred)[mask]
    if not torch.isfinite(scale).all() or torch.any(scale <= 0):
        raise ValueError("active loss scales must be finite and positive")
    return scale


def masked_huber(pred: Tensor, target, mask, scale=1.0) -> Tensor:
    p, y, mask = _select(pred, target, mask)
    if not p.numel():
        return _empty(pred)
    s = _scale(scale, pred, mask)
    return F.huber_loss(p / s, y / s, reduction="mean", delta=1.0)


def masked_bce(logits: Tensor, target, mask) -> Tensor:
    p, y, _ = _select(logits, target, mask)
    if not p.numel():
        return _empty(logits)
    if torch.any((y != 0) & (y != 1)):
        raise ValueError("BCE labels must be valid binary outcomes, not an unknown class")
    return F.binary_cross_entropy_with_logits(p, y, reduction="mean")


def proxy_cross_section_loss(
    pred: Tensor, target, mask, scale, weights, *, max_weight: float = 100.0
) -> Tensor:
    p, y, mask = _select(pred, target, mask)
    if not p.numel():
        return _empty(pred)
    if torch.any(p < 0) or torch.any(y < 0):
        raise ValueError("proxy cross sections must be nonnegative")
    s = _scale(scale, pred, mask)
    w = _expand(weights, pred)[mask]
    if max_weight <= 0 or not torch.isfinite(torch.as_tensor(max_weight)):
        raise ValueError("maximum proxy weight must be finite and positive")
    if not torch.isfinite(w).all() or torch.any(w < 0):
        raise ValueError("active proxy weights must be finite and nonnegative")
    w = w.clamp_max(max_weight)
    if not torch.any(w > 0):
        return _empty(pred)
    errors = F.huber_loss(torch.asinh(p / s), torch.asinh(y / s), reduction="none")
    # Preserve absolute confidence against the separately normalized native
    # likelihood: uniformly reducing confidence must actually reduce this term.
    return (w * errors).sum() / (w > 0).sum()


def poisson_count_loss(sigma: Tensor, count, exposure, mask) -> Tensor:
    """Poisson NLL with exposure=fluence*N_bits; use only with that count contract."""
    s, k, mask = _select(sigma, count, mask)
    if not s.numel():
        return _empty(sigma)
    e = _expand(exposure, sigma)[mask]
    if torch.any(s < 0) or torch.any(k < 0) or torch.any(k != torch.round(k)):
        raise ValueError("cross sections/counts must be nonnegative; counts are integral")
    if not torch.isfinite(e).all() or torch.any(e <= 0):
        raise ValueError("active count exposures must be finite and positive")
    lam = s * e
    if not torch.isfinite(lam).all() or torch.any((k > 0) & (lam <= 0)):
        raise ValueError("positive observed counts require finite positive expected counts")
    # k=0 is exactly lambda, including lambda=0, without epsilon/pseudocount.
    safe_lam = torch.where(k > 0, lam, torch.ones_like(lam))
    return (lam - k * torch.log(safe_lam) + torch.lgamma(k + 1)).mean()
