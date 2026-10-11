"""Display encoding of the fixed pipeline (task item 2.3; decisions 038, 042).

Painter's OCIO view `Default - sRGB` with Save Render's 16-bit PNG, modelled as
    code = round(65535 * encode(binary16(clamp(L, 0, 1))))
where L is the linear RGB render, binary16 the IEEE 754 half-precision rounding (round to
nearest even) and encode the IEC 61966-2-1 sRGB encoding (S-SRGB). The float16 stage is a
fitted, empirical model of the observed codes (`lattice_statistics`), not a claim about Iray's
internals: it states which 16-bit codes an Iray render can contain.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

F64 = npt.NDArray[np.float64]
FULL_SCALE = 65535.0


def encode(linear: F64) -> F64:
    x = np.clip(linear, 0.0, 1.0)
    result: F64 = np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)
    return result


def decode(encoded: F64) -> F64:
    c = np.clip(encoded, 0.0, 1.0)
    result: F64 = np.where(c <= 0.04045, c / 12.92, np.power((c + 0.055) / 1.055, 2.4))
    return result


def half(linear: F64) -> F64:
    result: F64 = np.clip(linear, 0.0, 65504.0).astype(np.float16).astype(np.float64)
    return result


def to_codes(linear: F64, through_half: bool = True) -> F64:
    """16-bit display codes of a linear render."""
    value = half(linear) if through_half else linear
    result: F64 = np.round(encode(value) * FULL_SCALE)
    return result


def to_linear(codes: F64) -> F64:
    result: F64 = decode(codes / FULL_SCALE)
    return result


def lattice() -> npt.NDArray[np.int64]:
    """Every code the model can produce: the encodings of all binary16 values in [0, 1]."""
    halves = np.arange(0, 0x3C01, dtype=np.uint16).view(np.float16).astype(np.float64)
    codes: npt.NDArray[np.int64] = np.unique(np.round(encode(halves) * FULL_SCALE).astype(np.int64))
    return codes


def lattice_statistics(images: list[F64]) -> dict[str, int | float]:
    """How many RGB samples of the renders lie on the model's lattice, and how far the others
    are from it (in 16-bit codes)."""
    allowed = lattice()
    counts = np.zeros(65536, dtype=np.int64)
    for image in images:
        counts += np.bincount(image.astype(np.int64).ravel(), minlength=65536)
    observed = np.nonzero(counts)[0]
    on = np.isin(observed, allowed)
    off = observed[~on]
    position = np.clip(np.searchsorted(allowed, off), 1, len(allowed) - 1)
    distance = np.minimum(np.abs(off - allowed[position - 1]), np.abs(allowed[position] - off))
    total = int(counts.sum())
    return {
        "samples": total,
        "samples_on_lattice": int(counts[observed[on]].sum()),
        "fraction_on_lattice": float(counts[observed[on]].sum() / total),
        "distinct_codes": len(observed),
        "distinct_codes_off_lattice": len(off),
        "max_distance_codes": int(distance.max()) if len(off) else 0,
        "lattice_codes": len(allowed),
    }
