"""The recording GPU's float32 arithmetic, vectorised (`src/evaluator/hwmath.h`).

`rsqrt(y)` is the correctly rounded 1 / sqrt(y) moved by the measured offset of
`src/evaluator/tables/hw-rsqrt.zlib` (entry i for the i-th float32 in [1, 4); y = z 4^k scales the
result by 2^-k), for positive normal y, as `hw::Rsqrt` computes it on the CPU and in the kernels;
`sqrt` and `rcp` likewise from `hw-sqrt.zlib` and `hw-rcp.zlib`. `sin` and `cos` read the measured
tables `hw-sin.zlib` and `hw-cos.zlib` at the fixed-point turn index of x in [0, float32(pi / 2)];
`acos` is the GPU's Vulkan arccosine built from the arcsine's polynomial (hwmath.h Acos). The
tables are UzmiGames' measurements of the GPU (`uzp-evaluator-tests fp-hardware`,
`trig-hardware`), not Painter data. Subnormal, zero, negative, infinite and NaN inputs of the
roots and the reciprocal are not modelled here (the fits never use them).
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


@cache
def _deltas(name: str) -> npt.NDArray[np.int8]:
    words = np.frombuffer(zlib.decompress((TABLES / f"hw-{name}.zlib").read_bytes()), "<u4")
    shifts = np.arange(16, dtype=np.uint32) * 2
    codes = ((words[:, None] >> shifts) & 3).reshape(-1).astype(np.int8)
    deltas: npt.NDArray[np.int8] = codes - 2
    return deltas


@cache
def _values(name: str) -> npt.NDArray[np.uint32]:
    """A table of measured float32 bit patterns stored as second differences (hwmath.h)."""
    d = np.frombuffer(zlib.decompress((TABLES / f"hw-{name}.zlib").read_bytes()), "<u4")
    first = np.cumsum(d.astype(np.uint64)) & 0xFFFFFFFF
    values: npt.NDArray[np.uint32] = (np.cumsum(first) & 0xFFFFFFFF).astype(np.uint32)
    return values


def sqrt(y: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """The recording GPU's square root (hw::Sqrt) of float32 y >= 0 (subnormals and zeros: 0)."""
    yf = np.asarray(y, F32)
    bits = yf.view(np.uint32).astype(np.int64)
    k = np.floor_divide(((bits >> 23) & 0xFF) - 127, 2)
    index = np.clip(bits - (k << 24) - 0x3F800000, 0, (1 << 24) - 1)
    correct = np.sqrt(yf.astype(np.float64)).astype(F32)
    moved = correct.view(np.uint32).astype(np.int64) + _deltas("sqrt")[index]
    out: npt.NDArray[np.float32] = np.where(
        (bits & 0x7FFFFFFF) < 0x00800000, F32(0), moved.astype(np.uint32).view(F32)
    )
    return out


def rcp(x: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """The recording GPU's reciprocal (hw::Rcp) of positive normal float32 x."""
    xf = np.asarray(x, F32)
    bits = xf.view(np.uint32).astype(np.int64)
    correct = (F32(1) / xf).astype(F32)
    moved = correct.view(np.uint32).astype(np.int64) + _deltas("rcp")[bits & 0x7FFFFF]
    out: npt.NDArray[np.float32] = moved.astype(np.uint32).view(F32)
    return out


TURNS_PER_RADIAN = np.uint32(0x3E22F983).view(F32)  # float32(1 / (2 pi))


def trig_index(x: npt.ArrayLike) -> npt.NDArray[np.int64]:
    """hw::TrigIndex: x float32(1 / (2 pi)) toward zero to float32, times 2^25, truncated."""
    exact = np.asarray(x, F32).astype(np.float64) * np.float64(TURNS_PER_RADIAN)
    u = exact.astype(F32)
    over = np.abs(u.astype(np.float64)) > np.abs(exact)
    u = np.where(over, (u.view(np.uint32) - 1).view(F32), u)
    index: npt.NDArray[np.int64] = np.floor(u.astype(np.float64) * 33554432.0).astype(np.int64)
    return index


def sin(x: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """The recording GPU's sine for x in [0, float32(pi / 2)] (hw::Sin)."""
    out: npt.NDArray[np.float32] = _values("sin")[trig_index(x)].view(F32)
    return out


def cos(x: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """The recording GPU's cosine for x in [0, float32(pi / 2)] (hw::Cos)."""
    out: npt.NDArray[np.float32] = _values("cos")[trig_index(x)].view(F32)
    return out


ASIN_C = tuple(
    F32(c) for c in (1.666701424e-1, 7.484657646e-2, 4.675685871e-2, 1.816697683e-2, 5.175137819e-2)
)
HALF_PI = F32(1.57079632679489661923)


def _fma(x: npt.ArrayLike, y: npt.ArrayLike, z: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """The exact product plus z in double, rounded to float32 (hwmath.cpp FusedMulAdd)."""
    out: npt.NDArray[np.float32] = (
        np.asarray(x, F32).astype(np.float64) * np.asarray(y, F32).astype(np.float64)
        + np.asarray(z, F32).astype(np.float64)
    ).astype(F32)
    return out


def _asin_polynomial(a: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    s = (a * a).astype(F32)
    r = np.full_like(a, ASIN_C[4])
    for c in (ASIN_C[3], ASIN_C[2], ASIN_C[1], ASIN_C[0]):
        r = _fma(r, s, c)
    return _fma((r * s).astype(F32), a, a)


def acos(x: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """The recording GPU's Vulkan arccosine (hw::Acos) for float32 x in [0, 1]."""
    xf = np.asarray(x, F32)
    t = np.where(xf.view(np.uint32) < 0x00800000, F32(0), xf)
    upper = t > F32(0.57)
    root = sqrt(np.maximum(_fma(F32(-0.5), t, F32(0.5)), F32(0)))
    high = (F32(2) * _asin_polynomial(root)).astype(F32)
    low = (HALF_PI - _asin_polynomial(t)).astype(F32)
    out: npt.NDArray[np.float32] = np.where(upper, high, low)
    return out


def log2(x: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """The recording GPU's base-2 logarithm (hw::Log2) from `hw-lg2-hi.zlib` and `hw-lg2-lo.zlib`:
    log2(2^e (1 + m 2^-23)) is e + hi[m] (e >= 1), hi[m] (e = 0), lo[m] (e = -1) or
    (e + 1) + lo[m] (e <= -2), the sum exact in double and rounded toward zero to float32; zeros
    and subnormals give -inf, negative numbers and NaN the quiet NaN, +inf gives +inf."""
    xf = np.asarray(x, F32)
    bits = xf.view(np.uint32).astype(np.int64)
    biased = (bits >> 23) & 0xFF
    e = biased - 127
    m = bits & 0x7FFFFF
    hi = _values("lg2-hi").view(F32)[m].astype(np.float64)
    lo = _values("lg2-lo").view(F32)[m].astype(np.float64)
    exact = np.where(e >= 1, e + hi, np.where(e == 0, hi, np.where(e == -1, lo, (e + 1) + lo)))
    f = exact.astype(F32)
    toward = np.abs(f.astype(np.float64)) > np.abs(exact)
    f = np.where(toward, np.nextafter(f, F32(0)), f)
    negative = (bits >> 31) == 1
    out: npt.NDArray[np.float32] = np.where(
        np.isnan(xf) | (negative & ((bits & 0x7FFFFFFF) != 0)),
        F32(np.nan),
        np.where(
            (bits & 0x7FFFFFFF) < 0x00800000,
            F32(-np.inf),
            np.where(np.isposinf(xf), F32(np.inf), f),
        ),
    ).astype(F32)
    return out


def exp2(y: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """The recording GPU's base-2 exponential (hw::Exp2) from `hw-ex2-pos.zlib` and
    `hw-ex2-neg.zlib`: |y| = k + f (integer k, f in [0, 1)), j = floor(f 2^23), ex2-pos[j] 2^k
    for y >= 0 and ex2-neg[j] 2^-k for y < 0; results below 2^-126 flush to +0, results at or
    above 2^128 are +inf, NaN gives the quiet NaN."""
    yf = np.asarray(y, F32)
    v = yf.astype(np.float64)
    finite = np.isfinite(v)
    a = np.where(finite, np.abs(v), 0.0)
    k = np.floor(a)
    j = np.clip(np.floor((a - k) * 2.0**23).astype(np.int64), 0, (1 << 23) - 1)
    pos = _values("ex2-pos").view(F32)[j].astype(np.float64)
    neg = _values("ex2-neg").view(F32)[j].astype(np.float64)
    with np.errstate(over="ignore"):
        r = np.where(v >= 0, pos * np.exp2(k), neg * np.exp2(-k))
    r = np.where(r < 2.0**-126, 0.0, r)
    r = np.where(r >= 2.0**128, np.inf, r)
    r = np.where(np.isposinf(v), np.inf, np.where(np.isneginf(v), 0.0, r))
    out: npt.NDArray[np.float32] = np.where(np.isnan(v), np.nan, r).astype(F32)
    return out


def pow(x: npt.ArrayLike, g: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """The recording GPU's pow (hw::Pow): exp2(g log2 x), the product one float32 multiply."""
    with np.errstate(invalid="ignore"):
        product = (np.asarray(g, F32) * log2(x)).astype(F32)
    return exp2(product)
