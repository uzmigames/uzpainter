"""The recording GPU's float32 reciprocal square root, vectorised (`src/evaluator/hwmath.h`).

`rsqrt(y)` is the correctly rounded 1 / sqrt(y) moved by the measured offset of
`src/evaluator/tables/hw-rsqrt.zlib` (entry i for the i-th float32 in [1, 4); y = z 4^k scales the
result by 2^-k), for positive normal y, as `hw::Rsqrt` computes it on the CPU and in the kernels.
The table is UzmiGames' measurement of the GPU (`uzp-evaluator-tests fp-hardware`), not Painter
data. Subnormal, zero, negative, infinite and NaN inputs are not modelled here (the fits never
normalise them).
"""

from __future__ import annotations

import zlib
from fractions import Fraction
from functools import cache
from pathlib import Path

import numpy as np
import numpy.typing as npt

TABLES = Path(__file__).resolve().parents[3] / "src" / "evaluator" / "tables"
F32 = np.float32


@cache
def _rsqrt_deltas() -> npt.NDArray[np.int8]:
    words = np.frombuffer(zlib.decompress((TABLES / "hw-rsqrt.zlib").read_bytes()), "<u4")
    shifts = np.arange(16, dtype=np.uint32) * 2
    codes = ((words[:, None] >> shifts) & 3).reshape(-1).astype(np.int8)
    deltas: npt.NDArray[np.int8] = codes - 2
    return deltas


def _sign_exact(m: npt.NDArray[np.float64], y: npt.NDArray[np.float64]) -> npt.NDArray[np.int8]:
    """sign(m^2 y - 1) for the entries of `m` and `y`, in exact rational arithmetic."""
    out = np.empty(m.shape, np.int8)
    for i, (a, b) in enumerate(zip(m.ravel().tolist(), y.ravel().tolist(), strict=True)):
        v = Fraction(a) ** 2 * Fraction(b) - 1
        out.flat[i] = (v > 0) - (v < 0)
    return out


def rsqrt_correct(y: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """1 / sqrt(y) correctly rounded to float32 (positive normal y)."""
    yf = np.asarray(y, F32)
    c = (1.0 / np.sqrt(yf.astype(np.float64))).astype(F32)
    bits = c.view(np.uint32).astype(np.int64)
    up = (bits + 1).astype(np.uint32).view(F32).astype(np.float64)
    down = (bits - 1).astype(np.uint32).view(F32).astype(np.float64)
    cd = c.astype(np.float64)
    yd = yf.astype(np.float64)
    m_up = (cd + up) * 0.5
    m_down = (cd + down) * 0.5
    # m^2 is exact in double; m^2 y - 1 is within 2^-52 of its value, so only results within
    # 1e-12 of 0 need the exact sign.
    t_up = m_up * m_up * yd - 1.0
    t_down = m_down * m_down * yd - 1.0
    s_up = np.sign(t_up).astype(np.int8)
    s_down = np.sign(t_down).astype(np.int8)
    close_up = np.abs(t_up) < 1e-12
    close_down = np.abs(t_down) < 1e-12
    if close_up.any():
        s_up[close_up] = _sign_exact(m_up[close_up], yd[close_up])
    if close_down.any():
        s_down[close_down] = _sign_exact(m_down[close_down], yd[close_down])
    result = np.where(s_up < 0, bits + 1, np.where(s_down > 0, bits - 1, bits))
    out: npt.NDArray[np.float32] = result.astype(np.uint32).view(F32)
    return out


def rsqrt(y: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """The recording GPU's reciprocal square root (hw::Rsqrt) of positive normal float32 y."""
    yf = np.asarray(y, F32)
    bits = yf.view(np.uint32).astype(np.int64)
    k = np.floor_divide(((bits >> 23) & 0xFF) - 127, 2)
    index = bits - (k << 24) - 0x3F800000
    moved = rsqrt_correct(yf).view(np.uint32).astype(np.int64) + _rsqrt_deltas()[index]
    out: npt.NDArray[np.float32] = moved.astype(np.uint32).view(F32)
    return out
