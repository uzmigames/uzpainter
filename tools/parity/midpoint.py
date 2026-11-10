"""Midpoint texels of a procedural filter comparison (decision 430, EXC-015).

A Sharpen output texel is a 16-bit code. Where the exact value lies halfway between two codes,
Painter's tie-break is not reproduced (decision 426 §2). EXC-015 bounds those texels by one code
and holds every other texel exact. The midpoints are computed here from the filter's inputs: the
content's codes and the decimal parameter. They are never computed from the difference.

- `content_codes`: the 16-bit code k of each content texel. The content must be the channel value
  I(I(F(k))) of a code (decision 426 §1); anything else raises `ContentInputError`.
- `laplacian4_midpoints`: with L = 4k - (n + s + e + w), the four neighbours wrapping at the
  texture border, a texel is a midpoint when intensity x L, taken exactly from the decimal
  intensity, is a half-integer and k + intensity x L lies strictly between 0 and 65535. A value
  the clamp decides has one correct code, so it is not a midpoint.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.proc_filters.levels_candidate import ContentInputError, content_codes

__all__ = ["ContentInputError", "content_codes", "exact_decimal", "laplacian4_midpoints"]

CODES = 65535


def exact_decimal(value: float) -> Fraction:
    """The exact rational of a decimal parameter as written (0.63 is 63/100, not its float)."""
    return Fraction(repr(float(value)))


def laplacian4_midpoints(codes: npt.NDArray[Any], intensity: Fraction) -> npt.NDArray[np.bool_]:
    """The midpoint texels of a four-neighbour Laplacian sharpening of `codes` (rows by columns,
    wrapping at the texture border) with `intensity`."""
    k = np.asarray(codes, dtype=np.int64)
    if k.ndim != 2:
        raise ValueError(f"codes are rows by columns, not shape {k.shape}")
    vertical = np.roll(k, 1, axis=0) + np.roll(k, -1, axis=0)
    neighbours = vertical + np.roll(k, 1, axis=1) + np.roll(k, -1, axis=1)
    laplacian = 4 * k - neighbours
    p, q = intensity.numerator, intensity.denominator
    twice = 2 * p * laplacian  # q (2 intensity x L)
    half_integer = (twice % q == 0) & ((twice // q) % 2 == 1)
    scaled = 2 * q * k + twice  # 2 q (k + intensity x L)
    inside: npt.NDArray[np.bool_] = half_integer & (scaled > 0) & (scaled < 2 * q * CODES)
    return inside
