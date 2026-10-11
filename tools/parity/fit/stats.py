"""|Δ| statistics at native depth (`parity/CONTRACT.md` §3.1, §8.1).

Integer maps compare code values; float maps compare values as numbers, where a NaN matches
only a NaN (a NaN against a number counts as differing with |Δ| = inf). Every result carries
max, mean and nearest-rank p99 together with the differing count and the texel counts, never
a mean alone. The field names are those of `parity/schema/semantics.json` (`difference`).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

Array = npt.NDArray[Any]


@dataclass(frozen=True)
class Difference:
    max: float
    mean: float
    p99: float
    differing: int  # differing values (every channel of every compared texel)
    total: int
    affected_texels: int  # texels with at least one differing channel
    texels: int

    @property
    def equal(self) -> bool:
        return self.differing == 0

    def as_dict(self) -> dict[str, Any]:
        """JSON form: integer statistics stay integers when both sides are integer maps."""
        result = asdict(self)
        for key in ("max", "p99"):
            value = result[key]
            if math.isfinite(value) and float(value).is_integer():
                result[key] = int(value)
        return result


def abs_differences(a: Array, b: Array, domain: Array | None = None) -> Array:
    """|a - b| per texel of `domain` (all when None) and channel, shape (texels, channels), as
    float64: integer maps by code, float maps as numbers (NaN against NaN and equal infinities
    0, NaN against a number inf).

    `a` and `b` have shape (h, w, c) or (h, w); `domain` is a boolean (h, w) mask.
    """
    if a.shape != b.shape:
        raise ValueError(f"shape {a.shape} differs from {b.shape}")
    if a.ndim == 2:
        a, b = a[:, :, None], b[:, :, None]
    if domain is None:
        domain = np.ones(a.shape[:2], np.bool_)
    left, right = a[domain], b[domain]
    if left.size == 0:
        raise ValueError("empty comparison domain")
    if np.issubdtype(left.dtype, np.integer) and np.issubdtype(right.dtype, np.integer):
        delta: Array = np.abs(left.astype(np.int64) - right.astype(np.int64)).astype(np.float64)
        return delta
    lf, rf = left.astype(np.float64), right.astype(np.float64)
    both_nan = np.isnan(lf) & np.isnan(rf)
    with np.errstate(invalid="ignore"):
        delta = np.abs(lf - rf)
    delta[both_nan] = 0.0
    delta[np.isnan(delta)] = math.inf
    same_inf = np.isinf(lf) & (lf == rf)
    delta[same_inf] = 0.0
    return delta


def difference(a: Array, b: Array, domain: Array | None = None) -> Difference:
    """Statistics of |a - b| over every channel of the texels in `domain` (all when None).

    `a` and `b` have shape (h, w, c) or (h, w); `domain` is a boolean (h, w) mask.
    """
    delta = abs_differences(a, b, domain)
    flat = delta.ravel()
    ordered = np.sort(flat)
    rank = math.ceil(0.99 * ordered.size)
    per_texel = delta.reshape(delta.shape[0], -1)
    return Difference(
        float(ordered[-1]),
        float(flat.mean()) if math.isfinite(float(ordered[-1])) else math.inf,
        float(ordered[rank - 1]),
        int(np.count_nonzero(flat)),
        int(flat.size),
        int(np.count_nonzero(per_texel.any(axis=1))),
        int(per_texel.shape[0]),
    )
