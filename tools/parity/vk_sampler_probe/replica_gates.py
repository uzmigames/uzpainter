"""The gates of decision 061's tabulated texture-unit replica, measured on the recording GPU
through Vulkan (decision 071; task phase1.9_compositor-resample-gaps). Synthetic textures only;
no Painter data is read. Prints the statistics as JSON.

    python -m tools.parity.vk_sampler_probe.replica_gates <work-dir> [gate ...]

Conventions: footprints a (along x) and b (along y) are in level-0 texels; lambda is the LOD in
1/256; the kernel of a level is a set of probe pairs (p, wl, wr, m): m copies of a probe at -p
(weight wl) and of one at +p (weight wr), offsets in 1/256 of that level's texels, weights in
1/1024 (a probe of weight w in 1/512 is two copies of w in 1/1024). Rule F splits a probe of
weight w at fractions (fx, fy): x1 = rhu(w fx / 256), x0 = w - x1, w11 = rhu(x1 fy / 256),
w01 = rhd(x0 fy / 256) (rhu / rhd: round half up / down).
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.vk_sampler_probe.measure import Probe, nearest_ties_up

LINE = 1024
LO, HI = -5, 7  # marginal columns around the centre texel
NC = HI - LO
Pair = tuple[int, int, int, int]
Geometry = tuple[Pair, ...]
Taps = list[tuple[int, float]]


def rhu(x: Any) -> Any:
    return (x + 128) >> 8


def rhd(x: Any) -> Any:
    return (x + 127) >> 8


def split(w: Any, fx: Any, fy: Any) -> tuple[tuple[int, int, Any], ...]:
    """Rule F: the (dx, dy, weight) taps of one probe."""
    x1 = rhu(w * fx)
    x0 = w - x1
    w11 = rhu(x1 * fy)
    w01 = rhd(x0 * fy)
    return ((0, 0, x0 - w01), (1, 0, x1 - w11), (0, 1, w01), (1, 1, w11))


def sample(
    probe: Probe,
    levels: list[np.ndarray],
    u: np.ndarray,
    v: np.ndarray,
    ddx: tuple[Any, Any],
    ddy: tuple[Any, Any],
    bias: float,
    clamp: bool = False,
    srgb8: bool = False,
) -> np.ndarray:
    """SampleGrad at each (u, v): the RGBA results, one row per sample (an R8G8B8A8_SRGB
    texture of codes with `srgb8`)."""
    count = u.size
    params = np.zeros((-(-count // LINE) * LINE, 2, 4), np.float32)
    params[:count, 0, 0], params[:count, 0, 1] = u, v
    for (row, column), value in zip(((0, 2), (0, 3), (1, 0), (1, 1)), (*ddx, *ddy), strict=True):
        params[:count, row, column] = np.broadcast_to(np.asarray(value, np.float32), (count,))
    out = probe.run(levels, params.reshape(-1, 4), width=LINE, bias=bias, clamp=clamp, srgb8=srgb8)
    result: np.ndarray = out.reshape(-1, 4)[:count].astype(np.float64)
    return result


def chain(level0: np.ndarray) -> list[np.ndarray]:
    levels = [level0.astype(np.float32)]
    while levels[-1].shape[0] > 1:
        p = levels[-1].astype(np.float64)
        levels.append(
            nearest_ties_up((p[0::2, 0::2] + p[0::2, 1::2] + p[1::2, 0::2] + p[1::2, 1::2]) / 4)
        )
    return levels


def empty(size: int) -> list[np.ndarray]:
    return [np.zeros((size >> k, size >> k, 4), np.float32) for k in range(size.bit_length())]


def lod(probe: Probe, a: np.ndarray, b: np.ndarray, bias: float = 0.0) -> np.ndarray:
    """lambda (1/256) of footprints a x b, -1 where clamped to 0: the trilinear weight
    t = min(256, floor(7 f / 4)) read at the bias and half a level below."""
    size = 256
    levels = empty(size)
    for k, level in enumerate(levels):
        level[..., k % 2] = 1.0
        level[..., 2] = k / 16
    inverse: dict[int, int] = {}
    for f in range(256):
        inverse.setdefault(min((7 * f) >> 2, 256), f)
    lam = np.full(a.size, -1, np.int64)
    for shift, extra in ((0.0, 0), (-0.5, 128)):
        out = sample(
            probe,
            levels,
            np.full(a.size, 0.3),
            np.full(a.size, 0.6),
            (a / size, 0),
            (0, b / size),
            bias + shift,
        )
        level = np.floor(out[:, 2] * 16 + 1e-9).astype(np.int64)
        t = np.round(np.where(level % 2 == 0, out[:, 1], out[:, 0]) * 256).astype(np.int64)
        frac = np.array([inverse.get(int(x), -1) for x in t])
        ok = (lam < 0) & (t > 0) & (t < 256) & (frac >= 0)
        lam[ok] = level[ok] * 256 + frac[ok] + extra
    return lam


def footprint_gradients(
    a: Any,
    b: Any,
    size: int,
    sign: int = 1,
    axis: int = 0,
    swap: bool = False,
    minor_sign: int = 1,
) -> tuple[tuple[Any, Any], tuple[Any, Any]]:
    """ddx and ddy of an axis-aligned footprint in texels of a `size` texture: the major extent a
    along x (axis 0) or y (axis 1) with the sign `sign`, the minor extent b along the other axis
    with `minor_sign`; `swap` hands the v gradient to ddx (a rotation by 90 degrees)."""
    zero = np.zeros_like(np.asarray(a, np.float64))
    major = sign * np.asarray(a, np.float64) / size
    minor = minor_sign * np.asarray(b, np.float64) / size + zero
    gu, gv = ((major, zero), (zero, minor)) if axis == 0 else ((minor, zero), (zero, major))
    return (gv, gu) if swap else (gu, gv)


def marginals(
    probe: Probe,
    a: np.ndarray,
    b: np.ndarray,
    bias: float,
    level: int,
    sign: int = 1,
    axis: int = 0,
    swap: bool = False,
) -> np.ndarray:
    """[key, phase, column]: the weights (1/1024) of level `level` summed across the major axis,
    at the 256 sub-texel phases of a sample moving along it from a texel centre, columns (rows for
    axis 1) LO..HI-1, read as pairs per channel (1, 2^-12)."""
    size = 1024
    sk = size >> level
    phase = np.tile(np.arange(256), a.size)
    along = (400 + phase / 256 + 0.5) / sk
    across = np.full(along.size, (400 + 0.5) / sk)
    u, v = (along, across) if axis == 0 else (across, along)
    ddx, ddy = footprint_gradients(np.repeat(a, 256), np.repeat(b, 256), size, sign, axis, swap)
    result = np.zeros((u.size, NC), np.int64)
    for start in range(0, NC, 8):
        levels = empty(size)
        for q, d in enumerate(range(LO + start, min(HI, LO + start + 8))):
            value = 1.0 if q % 2 == 0 else 2.0**-12
            if axis == 0:
                levels[level][:, (400 + d) % sk, q // 2] = value
            else:
                levels[level][(400 + d) % sk, :, q // 2] = value
        out = sample(probe, levels, u, v, ddx, ddy, bias)
        for q in range(min(8, NC - start)):
            hi = np.floor(out[:, q // 2] * 1024 + 2.0**-14)
            result[:, start + q] = (
                hi if q % 2 == 0 else np.round((out[:, q // 2] * 1024 - hi) * 4096)
            )
    marg: np.ndarray = result.reshape(a.size, 256, NC)
    return marg


def phi(w: int, q: np.ndarray, down: bool = False) -> np.ndarray:
    """Mass of a probe of weight w left of a column boundary q/256 texels right of it; `down`
    rounds the split half down (rule F's y split of a probe at x phase 0, for the y axis)."""
    inner = w - (rhd if down else rhu)(w * (256 - np.clip(q, 0, 256)))
    out: np.ndarray = np.where(q <= 0, 0, np.where(q > 256, w, inner))
    return out


_Q = np.arange(600)
FIRST = {
    down: {w: int(_Q[np.argmax(phi(w, _Q, down) >= 1)]) for w in range(1, 1025)}
    for down in (False, True)
}
FULL = {
    down: {w: int(_Q[np.argmax(phi(w, _Q, down) >= w)]) for w in range(1, 1025)}
    for down in (False, True)
}


def search(
    z: np.ndarray,
    rest: np.ndarray,
    pairs: list[Pair],
    left: int,
    depth: int,
    found: list[Geometry],
    down: bool = False,
) -> None:
    """Peel probe pairs from the left: the leftmost remaining probe's first increment fixes its
    offset for each weight, the rightmost one's last increment must agree."""
    if len(found) >= 6:
        return
    if left == 0:
        if not np.any(rest):
            found.append(tuple(pairs))
        return
    if len(pairs) >= depth:
        return
    first = int(z[np.argmax(rest > 0)])
    last = int(z[len(z) - 1 - np.argmax(rest[::-1] < left)])
    for mult in (4, 2, 1):
        for wl in range(1, left // mult + 1):
            p = FIRST[down][wl] - first
            if p < 0 or (pairs and p > pairs[-1][0]):
                continue
            for wr in range(max(1, wl - 2), wl + 3):
                if mult * (wl + wr) > left or last - FULL[down][wr] + 1 != p:
                    continue
                r2 = rest - mult * (phi(wl, z + p, down) + phi(wr, z - p, down))
                if np.any(r2 < 0) or np.any(np.diff(r2) < 0):
                    continue
                pair = (p, wl, wr, mult)
                search(z, r2, [*pairs, pair], left - mult * (wl + wr), depth, found, down)


def decode(m: np.ndarray, down: bool = False) -> Geometry | None | str:
    """The probe pairs whose rule-F marginals reproduce m at every phase (fewest pairs, then the
    largest multiplicity); None when nothing fits, 'ambiguous' when several do. `down`: the
    marginals run along y (axis 1)."""
    cumulative = np.concatenate([np.zeros((256, 1), np.int64), np.cumsum(m, 1)], 1)
    z = (256 * (LO + np.arange(NC + 1))[None, :] - np.arange(256)[:, None]).ravel()
    order = np.argsort(z)
    z, mass = z[order], cumulative.ravel()[order]
    total = int(mass[-1])
    if total == 0:
        return ()
    for depth in (1, 2, 3):
        found: list[Geometry] = []
        search(z, mass.copy(), [], total, depth, found, down)
        if found:
            # Equal marginals: prefer the coarsest weight unit (largest multiplicity).
            top = max(min(pair[3] for pair in g) for g in found)
            best = sorted({g for g in found if min(pair[3] for pair in g) == top})
            return best[0] if len(best) == 1 else "ambiguous"
    return None


def keyed(e: int, m: np.ndarray) -> np.ndarray:
    """Footprints whose 9-bit mantissa is m (bin centre) with exponent e."""
    out: np.ndarray = 2.0**e * (1 + (m + 0.5) / 512)
    return out


def trilinear_and_split(probe: Probe) -> dict[str, int]:
    """One isotropic probe of 4 texels at biases -k/256: every level-1 and level-2 tap weight
    (1/256) of all 65 536 phases against t = min(256, floor(7 f / 4)) and rule F."""
    size = 256
    fx, fy = (g.ravel() for g in np.meshgrid(np.arange(256), np.arange(256)))
    u = (40 + fx / 256 + 0.5) / 128
    v = (50 + fy / 256 + 0.5) / 128
    samples = differing = 0
    for k in range(0, 257, 8):
        f = (256 - k) & 255
        t = min((7 * f) >> 2, 256) if k else 0
        for level, weight in ((1, 256 - t if k else 0), (2, t if k else 256)):
            levels = empty(size)
            n = size >> level
            y, x = np.mgrid[0:n, 0:n]
            for channel, (px, py) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
                levels[level][..., channel] = (x % 2 == px) & (y % 2 == py)
            got = np.round(
                sample(probe, levels, u, v, (4 / size, 0), (0, 4 / size), -k / 256) * 256
            )
            fixed_x = np.floor(256 * (u * n - 0.5) + 0.5).astype(np.int64)
            fixed_y = np.floor(256 * (v * n - 0.5) + 0.5).astype(np.int64)
            want = np.zeros_like(got)
            for dx, dy, w in split(weight, fixed_x & 255, fixed_y & 255):
                c = ((fixed_x >> 8) + dx) % 2 + 2 * (((fixed_y >> 8) + dy) % 2)
                np.add.at(want, (np.arange(c.size), c), w)
            samples += fx.size
            differing += int(np.any(got != want, axis=1).sum())
    return {"tap-weight samples": samples, "differing": differing}


def per_sample(value: Any, keys: np.ndarray, rep: int) -> np.ndarray:
    """A per-key gradient component repeated for the rep samples of each key."""
    out: np.ndarray = np.repeat(np.broadcast_to(np.asarray(value, np.float64), keys.shape), rep)
    return out


def kernels(probe: Probe, cfg: dict[str, Any], levels: Sequence[int], bias: float) -> np.ndarray:
    """[level, key, y, x]: two-dimensional kernels (1/1024) around the floor texel, radius 6."""
    size, radius = 512, 6
    u0, v0 = np.asarray(cfg["u0"]), np.asarray(cfg["v0"])
    d = np.arange(-radius, radius + 1)
    out = []
    for k in levels:
        sk = size >> k
        texture = empty(size)
        texture[k][sk // 2, sk // 2, 0] = 1.0
        uu = (
            u0[:, None, None]
            + (sk // 2 - (np.floor(u0 * sk - 0.5)[:, None, None] + d[None, None, :])) / sk
        )
        vv = (
            v0[:, None, None]
            + (sk // 2 - (np.floor(v0 * sk - 0.5)[:, None, None] + d[None, :, None])) / sk
        )
        uu, vv = np.broadcast_arrays(uu, vv)
        rep = (2 * radius + 1) ** 2

        got = sample(
            probe,
            texture,
            uu.ravel(),
            vv.ravel(),
            (per_sample(cfg["ddx"][0], u0, rep), per_sample(cfg["ddx"][1], u0, rep)),
            (per_sample(cfg["ddy"][0], u0, rep), per_sample(cfg["ddy"][1], u0, rep)),
            bias,
        )
        out.append(np.round(got[:, 0] * 1024).reshape(u0.size, 2 * radius + 1, 2 * radius + 1))
    return np.array(out)


def key_sufficiency(probe: Probe) -> dict[str, Any]:
    """Two-level kernels unchanged by the gradient bits below the 9-bit mantissa and by swapping
    the ddx / ddy roles; the sign of the major-axis gradient changes some."""
    rng = np.random.default_rng(21)
    size, n = 512, 300
    eb = rng.integers(0, 4, n)
    b = keyed(0, rng.integers(0, 512, n)) * 2.0**eb
    a = b * np.exp2(rng.uniform(0, 3, n))
    ea = np.floor(np.log2(a))
    a = 2.0**ea * (1 + np.floor((a / 2.0**ea - 1) * 512) / 512)
    b = 2.0**eb * (1 + np.floor((b / 2.0**eb - 1) * 512) / 512)
    a2 = (a + 2.0**ea * rng.uniform(0, 1 / 512, n) * 0.999).astype(np.float32).astype(np.float64)
    b2 = (b + 2.0**eb * rng.uniform(0, 1 / 512, n) * 0.999).astype(np.float32).astype(np.float64)
    u0 = (rng.integers(200 * 256, 300 * 256, n) / 256 + 0.5) / size
    v0 = (rng.integers(200 * 256, 300 * 256, n) / 256 + 0.5) / size
    report: dict[str, Any] = {}
    for bias in (0.0, -1.5):
        variants = {
            "base": ((a, 0), (0, b)),
            "bits below the 9-bit mantissas": ((a2, 0), (0, b2)),
            "ddx and ddy swapped (rotation 90)": ((0, b), (a, 0)),
            "sign of the major-axis gradient": ((-a, 0), (0, b)),
        }
        got = {
            name: kernels(
                probe,
                {
                    "u0": u0,
                    "v0": v0,
                    "ddx": (gx[0] / size, gx[1] / size),
                    "ddy": (gy[0] / size, gy[1] / size),
                },
                range(6),
                bias,
            )
            for name, (gx, gy) in variants.items()
        }
        for name in list(variants)[1:]:
            report[f"bias {bias}: {name}"] = {
                "kernels": n * 6,
                "differing": int(np.any(got["base"] != got[name], axis=(2, 3)).sum()),
            }
    return report


def geometry_cells(probe: Probe) -> dict[str, Any]:
    """The geometry of both levels as a function of (rho, f): rho = lambda_major - lambda,
    lambda_major the LOD of the major axis alone (four-to-one clamp), f = lambda_b & 255."""
    m = np.arange(512)
    major = lod(probe, keyed(3, m), keyed(3, m) / 6) - 256  # log2 table of the major mantissa
    lam = {}
    ma, mb = (g.ravel() for g in np.meshgrid(m, m, indexing="ij"))
    for de in (0, 1, 2):
        lam[de] = lod(probe, keyed(2, ma), keyed(2 - de, mb))
    rng = np.random.default_rng(61)
    cells: dict[tuple[int, int, float], list[tuple[int, int, int, int]]] = defaultdict(list)
    for de in (0, 1, 2):
        a, b = keyed(2, ma), keyed(2 - de, mb)
        for i in np.nonzero((a >= b) & (a / b <= 4.0) & (lam[de] >= 0))[0]:
            value = int(lam[de][i])
            rho = 512 + int(major[ma[i]]) - value
            for bias in (0.0, -1.5):
                biased = value + int(bias * 256)
                if biased >= 256:
                    cells[(rho, biased & 255, bias)].append((de, int(ma[i]), int(mb[i]), biased))

    def measure(keys: list[tuple[int, int, int, int]], bias: float, sign: int) -> list[Any]:
        de = np.array([k[0] for k in keys])
        a, b = (
            keyed(2, np.array([k[1] for k in keys])),
            keyed(0, np.array([k[2] for k in keys])) * 2.0 ** (2 - de),
        )
        lb = np.array([k[3] for k in keys])
        geometry: list[Any] = [[None, None] for _ in keys]
        for which in (0, 1):
            for level in (1, 2, 3):
                sel = np.nonzero((lb >> 8) + which == level)[0]
                if sel.size:
                    marg = marginals(probe, a[sel], b[sel], bias, level, sign)
                    for q, i in enumerate(sel):
                        geometry[i][which] = decode(marg[q])
        return geometry

    report: dict[str, Any] = {}
    same0 = [c for c, v in cells.items() if c[2] == 0.0 and len(v) >= 2]
    pick = [same0[j] for j in rng.choice(len(same0), 200, replace=False)]
    g1 = measure([cells[c][0] for c in pick], 0.0, 1)
    g2 = measure([cells[c][1] for c in pick], 0.0, 1)
    report["two keys per cell, bias 0"] = {
        "cells": len(pick),
        "different": sum(x != y for x, y in zip(g1, g2, strict=True)),
        "undecoded": sum(None in x or "ambiguous" in x for x in g1 + g2),
    }
    both = sorted(
        {(r, f) for r, f, b in cells if b == 0.0} & {(r, f) for r, f, b in cells if b == -1.5}
    )
    pick2 = [both[j] for j in rng.choice(len(both), 200, replace=False)]
    g0 = measure([cells[(r, f, 0.0)][0] for r, f in pick2], 0.0, 1)
    g15 = measure([cells[(r, f, -1.5)][0] for r, f in pick2], -1.5, 1)
    report["one key at bias 0, another at bias -1.5"] = {
        "cells": len(pick2),
        "different": sum(x != y for x, y in zip(g0, g15, strict=True)),
    }
    gm = measure([cells[(r, f, 0.0)][0] for r, f in pick2], 0.0, -1)
    report["sign of the major-axis gradient"] = {
        "cells": len(pick2),
        "different": sum(x != y for x, y in zip(g0, gm, strict=True)),
    }
    return report


def ordered_probes(
    levels: list[np.ndarray],
    u: float,
    v: float,
    lower: int,
    geometry: Sequence[Geometry],
    sign: int = 1,
    axis: int = 0,
) -> list[tuple[int, Taps]]:
    """The probes of a sample in the order the texture unit adds them (repeat addressing): the
    lower level first; within a level by offset along the major-axis gradient, ascending for a
    positive gradient; a pair at offset 0 is one probe of the pair's weight. Each probe is
    (level, taps), the taps (weight 1/1024, texel) of rule F with zero weights dropped."""
    out: list[tuple[int, Taps]] = []
    for k, pairs in zip((lower, lower + 1), geometry, strict=True):
        level = levels[k]
        h, w = level.shape
        x = math.floor(256 * (u * w - 0.5) + 0.5)
        y = math.floor(256 * (v * h - 0.5) + 0.5)
        found: list[tuple[int, Taps]] = []
        for p, wl, wr, mult in pairs:
            ends = ((0, wl), (0, wr)) if p == 0 else ((-p, wl), (p, wr))
            for offset, weight in ends:
                px, py = (x + offset, y) if axis == 0 else (x, y + offset)
                taps = [
                    (mult * ww, float(level[((py >> 8) + dy) % h, ((px >> 8) + dx) % w]))
                    for dx, dy, ww in split(weight, px & 255, py & 255)
                    if ww
                ]
                if p == 0 and found and found[-1][0] == 0:
                    taps = found.pop()[1] + taps
                found.append((offset, taps))
        found.sort(key=lambda item: sign * item[0])
        out += [(k, taps) for _, taps in found]
    return out


def probe_sums(
    levels: list[np.ndarray], u: float, v: float, lower: int, geometry: Sequence[Geometry]
) -> list[Taps]:
    """The taps (weight 1/1024, texel) of every probe of a sample (x-major, positive, repeat)."""
    return [taps for _, taps in ordered_probes(levels, u, v, lower, geometry)]


def exact_sum(probes: list[Taps], unit_bits: int) -> tuple[int, int]:
    """Decision 071's rule. Each probe: E the exponent of its largest texel, operands
    floor(t 2^(28 - E)), the integer sum; all probes summed exactly. Returns (n, e) with the
    value n 2^e."""
    parts = []
    for taps in probes:
        largest = max(t for _, t in taps)
        if largest > 0:
            e = math.frexp(largest)[1]
            parts.append((sum(w * math.floor(math.ldexp(t, 28 - e)) for w, t in taps), e))
    if not parts:
        return 0, 0
    low = min(e for _, e in parts)
    return sum(s << (e - low) for s, e in parts), low - 28 - unit_bits


def ties_up(n: int, e: int) -> float:
    """n 2^e rounded to the nearest float32, ties up."""
    if n == 0:
        return 0.0
    shift = max(n.bit_length() - 24, 0)
    q = n >> shift
    if shift and (n >> (shift - 1)) & 1:
        q += 1
    return math.ldexp(q, e + shift)


def coarse(e: int) -> int:
    """E lowered until the biased float32 exponent E + 126 is a multiple of 4."""
    return e - (e + 126) % 4


def probe_sum(taps: Taps) -> tuple[int, int] | None:
    """(S, E) of one probe: E the exponent of its largest texel (t in [2^(E-1), 2^E)), S the sum
    of w floor(t 2^(28 - E)) over its taps (w in 1/1024), the value S 2^(E - 38); None when every
    texel is 0."""
    largest = max((t for _, t in taps), default=0.0)
    if largest <= 0:
        return None
    e = math.frexp(largest)[1]
    return sum(w * math.floor(math.ldexp(t, 28 - e)) for w, t in taps), e


def accumulate(probes: Sequence[tuple[int, tuple[int, int] | None]]) -> float:
    """The texture unit's sum of (level, probe_sum) in its order (decision 083):

    - a probe of exponent E enters truncated to a multiple of 2^(coarse(E) - 36);
    - the probes of a level go in pairs (consecutive in the order; a level of one probe is one
      group); before each addition after the first, the running sum is truncated to a multiple
      of 2^(coarse(G) - 36), G the largest E of the probes of every pair up to and including the
      incoming probe's;
    - the sum is rounded to the nearest float32, ties up."""
    seen: Counter[int] = Counter()
    groups = []
    for level, _ in probes:
        groups.append((level, seen[level] // 2))
        seen[level] += 1
    total, low = 0, 0
    for i, (_, part) in enumerate(probes):
        if i >= 2 and total:
            g = max(
                (
                    q[1]
                    for q, group in zip((p for _, p in probes), groups, strict=True)
                    if q is not None and group <= groups[i]
                ),
                default=None,
            )
            if g is not None and coarse(g) - 36 > low:
                total, low = total >> (coarse(g) - 36 - low), coarse(g) - 36
        if part is None or part[0] == 0:
            continue
        s, e = part
        n, x = s, e - 38
        if coarse(e) - 36 > x:
            n, x = n >> (coarse(e) - 36 - x), coarse(e) - 36
        if total == 0:
            total, low = n, x
        else:
            lo = min(low, x)
            total, low = (total << (low - lo)) + (n << (x - lo)), lo
    return ties_up(total, low)


def accumulation(probe: Probe) -> dict[str, Any]:
    rng = np.random.default_rng(9)
    report: dict[str, Any] = {}
    # One probe per level (isotropic, 1/256): random texels over 24 octaves.
    size = 256
    count = equal = modelled = 0
    for k in (0, 60, 130, 200, 240):
        f = (256 - k) & 255
        t = min((7 * f) >> 2, 256) if k else 0
        weights = {1: 256 - t, 2: t} if k else {2: 256}
        levels = empty(size)
        for j in (1, 2):
            shape = levels[j].shape
            levels[j][...] = rng.integers(1 << 23, 1 << 24, shape) * np.exp2(
                -24.0 - rng.integers(0, 24, shape)
            )
        n = 20000
        u = ((rng.integers(0, 256 * 128, n) / 256 + 0.5) / 128).astype(np.float32)
        v = ((rng.integers(0, 256 * 128, n) / 256 + 0.5) / 128).astype(np.float32)
        got = sample(probe, levels, u, v, (4 / size, 0), (0, 4 / size), -k / 256)
        for i in range(n):
            for c in range(4):
                probes = []
                for j, w in weights.items():
                    if w == 0:
                        continue
                    sk = size >> j
                    x = math.floor(256 * (float(u[i]) * sk - 0.5) + 0.5)
                    y = math.floor(256 * (float(v[i]) * sk - 0.5) + 0.5)
                    probes.append(
                        [
                            (ww, float(levels[j][((y >> 8) + dy) % sk, ((x >> 8) + dx) % sk, c]))
                            for dx, dy, ww in split(w, x & 255, y & 255)
                            if ww
                        ]
                    )
                count += 1
                equal += ties_up(*exact_sum(probes, 8)) == got[i, c]
                parts = [(0, probe_sum([(4 * ww, t) for ww, t in taps])) for taps in probes]
                modelled += accumulate(parts) == got[i, c]
    report["one probe per level, texels over 24 octaves"] = {
        "samples": count,
        "equal": equal,
        "accumulator equal": modelled,
    }

    # Two probes (1.5 x 1 at bias -8: +-86/256, 256/512 each), texels with 3-bit mantissas.
    size = 256
    stats: Counter[str] = Counter()
    for _ in range(2):
        mant = rng.integers(4, 8, (size, size, 4))
        expo = np.where(
            rng.random((size, size, 4)) < 0.5,
            rng.integers(1, 4, (size, size, 4)),
            rng.integers(4, 40, (size, size, 4)),
        )
        level0 = (mant / 8 * np.exp2(-expo)).astype(np.float32)
        levels = [level0, *empty(size)[1:]]
        n = 40000
        xs = rng.integers(10 * 256, 240 * 256, n)
        ys = rng.integers(10 * 256, 240 * 256, n)
        us = ((xs / 256 + 0.5) / size).astype(np.float32)
        vs = ((ys / 256 + 0.5) / size).astype(np.float32)
        got = sample(probe, levels, us, vs, (1.5 / size, 0), (0, 1.0 / size), -8.0)
        for i in range(n):
            for c in range(4):
                probes = []
                for offset in (-86, 86):
                    px = int(xs[i]) + offset
                    yy = int(ys[i])
                    probes.append(
                        [
                            (ww, float(level0[(yy >> 8) + dy, (px >> 8) + dx, c]))
                            for dx, dy, ww in split(256, px & 255, yy & 255)
                            if ww
                        ]
                    )
                total, e = exact_sum(probes, 9)
                odd = total >> ((total & -total).bit_length() - 1) if total else 0
                key = "representable" if odd.bit_length() <= 24 else "rounded"
                stats[f"{key} samples"] += 1
                stats[f"{key} equal"] += ties_up(total, e) == got[i, c]
                parts = [(0, probe_sum([(2 * ww, t) for ww, t in taps])) for taps in probes]
                stats[f"{key} accumulator equal"] += accumulate(parts) == got[i, c]
    report["two probes, texels with 3-bit mantissas"] = dict(stats)

    # Probe sets decoded per footprint; three texture families with 16- and 8-bit codes.
    families: dict[str, Callable[[], np.ndarray]] = {
        "uniform 16-bit codes": lambda: rng.integers(0, 65536, (256, 256)) / 65535,
        "log-uniform dark 16-bit codes": lambda: np.floor(np.exp2(rng.uniform(0, 16, (256, 256))))
        / 65535,
        "log-uniform dark 8-bit codes": lambda: np.floor(np.exp2(rng.uniform(0, 8, (256, 256))))
        / 255,
    }
    footprints = [
        (1.2825, 1.2825, -1.5),
        (3.0, 1.2, 0.0),
        (7.371, 2.945, -1.5),
        (8.98, 1.733, 0.0),
        (5.5, 2.0, -0.25),
    ]
    for name, make in families.items():
        count = equal = modelled = 0
        for a, b, bias in footprints:
            lam = max(int(lod(probe, np.array([a]), np.array([b]), bias)[0]), 0)
            geometry = []
            for k in (lam >> 8, (lam >> 8) + 1):
                g = decode(marginals(probe, np.array([a]), np.array([b]), bias, k)[0])
                assert isinstance(g, tuple), g
                geometry.append(g)
            levels = chain(np.repeat(make().astype(np.float32)[..., None], 4, 2))
            n = 30000
            u = ((rng.integers(0, 256 * 256, n) / 256 + 0.5) / 256).astype(np.float32)
            v = ((rng.integers(0, 256 * 256, n) / 256 + 0.5) / 256).astype(np.float32)
            got = sample(probe, levels, u, v, (a / 256, 0), (0, b / 256), bias)[:, 0]
            red = [level[..., 0] for level in levels]
            for i in range(n):
                count += 1
                ordered = ordered_probes(red, float(u[i]), float(v[i]), lam >> 8, geometry)
                equal += ties_up(*exact_sum([taps for _, taps in ordered], 10)) == got[i]
                modelled += accumulate([(k, probe_sum(taps)) for k, taps in ordered]) == got[i]
        report[f"probes summed exactly, {name}"] = {
            "samples": count,
            "equal": equal,
            "accumulator equal": modelled,
        }
    report["one ulp above the rounding midpoint, rounded down"] = dial(probe)
    return report


def dial(probe: Probe) -> dict[str, int]:
    """Two probes (1.5 x 1, bias -8, centre 256 k + 86, 256 r + 1): probe A at 256 k holds
    T (weight 1/512, exponent EA) and d1 (255); probe B holds d1 (84), d2 (171) and a dial (1).
    The dial steps one operand unit of B across a float32 tie: where the hardware first rounds
    up gives its sum to one unit of B. The accumulator (decision 083) is compared at every step."""
    rng = np.random.default_rng(17)
    size, steps = 1024, 96

    def op(t: float, e: int) -> int:
        return math.floor(math.ldexp(t, 28 - e))

    cases = []
    for _ in range(1200):
        ea = -int(rng.integers(1, 6))
        t = float(np.float32(rng.integers(4, 8) / 8 * 2.0**ea))
        eb = ea - int(rng.integers(1, 22))
        d1 = float(np.float32(rng.integers(1 << 23, 1 << 24) * 2.0 ** (eb - 24)))
        d2 = float(
            np.float32(rng.integers(1 << 23, 1 << 24) * 2.0 ** (eb - 24 - int(rng.integers(0, 3))))
        )
        a_sum = op(t, ea) + 255 * op(d1, ea)
        b_sum = 84 * op(d1, eb) + 171 * op(d2, eb)
        base = (a_sum << (ea - eb)) + b_sum  # units 2^(eb - 37)
        ulp = 1 << max(base.bit_length() - 24, 0)
        tie = (base // ulp) * ulp + ulp // 2
        start = tie - base - steps // 2
        if ulp >= 2 and start >= 0 and start + steps < (1 << 24):
            cases.append((ea, t, eb, d1, d2, start, tie - base, a_sum))
    level0 = np.zeros((size, size, 4), np.float32)
    us, vs = [], []
    for q, (_, t, eb, d1, d2, start, _, _) in enumerate(cases):
        for j in range(steps):
            slot = q * steps + j
            k, row = 4 * (slot % 256), 4 * (slot // 256)
            level0[row, k], level0[row + 1, k], level0[row, k + 1] = d1, t, d2
            level0[row + 1, k + 1] = np.float32((start + j) * 2.0 ** (eb - 28))
            us.append(((256 * k + 86) / 256 + 0.5) / size)
            vs.append(((256 * row + 1) / 256 + 0.5) / size)
    got = sample(
        probe,
        [level0, *empty(size)[1:]],
        np.array(us, np.float32),
        np.array(vs, np.float32),
        (1.5 / size, 0),
        (0, 1 / size),
        -8.0,
    )[:, 0]
    result: Counter[str] = Counter()
    for q, (_, t, eb, d1, d2, start, need, a_sum) in enumerate(cases):
        values = got[q * steps : (q + 1) * steps]
        part_a = probe_sum([(2, t), (510, d1)])
        modelled = [
            accumulate(
                [
                    (0, part_a),
                    (
                        0,
                        probe_sum(
                            [
                                (168, d1),
                                (342, d2),
                                (2, float(np.float32((start + j) * 2.0 ** (eb - 28)))),
                            ]
                        ),
                    ),
                ]
            )
            for j in range(steps)
        ]
        same = sum(m == h for m, h in zip(modelled, values, strict=True))
        result["accumulator: steps equal"] += same
        result["accumulator: cases equal at every step"] += int(same == steps)
        result["steps"] += steps
        # the exact sum reaches the tie at step need - start; the hardware's first step above it
        flips = [j for j in range(steps) if values[j] > values[0]]
        exact_flip = need - start
        late = (flips[0] - exact_flip) if flips else steps
        parity = "odd" if a_sum % 2 else "even"
        result[f"A sum {parity}: hardware flips late"] += int(late > 0)
        result[f"A sum {parity}: hardware flips with the exact sum"] += int(late == 0)
        result[f"A sum {parity}: other"] += int(late < 0)
    return dict(result)


Family = Callable[[np.random.Generator, tuple[int, ...]], np.ndarray]
FAMILIES: dict[str, Family] = {
    # 24-bit mantissas over 24 octaves
    "wide": lambda rng, shape: rng.integers(1 << 23, 1 << 24, shape)
    * np.exp2(-24.0 - rng.integers(0, 24, shape)),
    "dark 16-bit": lambda rng, shape: np.floor(np.exp2(rng.uniform(0, 16, shape))) / 65535,
    "dark 8-bit": lambda rng, shape: np.floor(np.exp2(rng.uniform(0, 8, shape))) / 255,
    # uniform 16-bit codes, a fifth of them 0 and a tenth 65535
    "uniform 16-bit with 0 and 1": lambda rng, shape: np.select(
        [(r := rng.random(shape)) < 0.2, r < 0.3], [0, 65535], rng.integers(0, 65536, shape)
    )
    / 65535,
    # 3-bit mantissas over 20 octaves
    "sparse": lambda rng, shape: rng.integers(4, 8, shape)
    / 8
    * np.exp2(-rng.integers(0, 20, shape).astype(np.float64)),
}
# (a, b, bias, sign, minor sign, axis, swap, family): the footprints the accumulator rule was
# found on (decision 083) and footprints held out of the search.
Footprint = tuple[float, float, float, int, int, int, bool, str]
FOUND_ON: list[Footprint] = [
    (3.0, 1.2, 0.0, 1, 1, 0, False, "wide"),
    (3.0, 1.2, 0.0, -1, 1, 0, False, "wide"),
    (3.0, 1.2, 0.0, 1, 1, 1, False, "wide"),
    (3.0, 1.2, 0.0, -1, 1, 1, False, "wide"),
    (10.0, 2.5, 0.0, 1, 1, 0, False, "wide"),
    (10.0, 2.5, 0.0, -1, 1, 0, False, "wide"),
    (10.0, 2.5, 0.0, 1, 1, 1, False, "wide"),
    (10.0, 2.5, 0.0, -1, 1, 1, False, "wide"),
    (6.0, 2.0, 0.0, 1, 1, 0, False, "wide"),
    (6.0, 2.0, 0.0, -1, 1, 0, False, "wide"),
    (7.371, 2.945, -1.5, 1, 1, 0, False, "wide"),
    (8.98, 1.733, 0.0, 1, 1, 0, False, "wide"),
    (5.5, 2.0, -0.25, 1, 1, 0, False, "wide"),
    (20.0, 3.0, -1.5, 1, 1, 0, False, "wide"),
    (2.5, 1.0, 0.5, 1, 1, 0, False, "wide"),
    (1.5, 1.0, -8.0, 1, 1, 0, False, "wide"),
    (12.0, 4.0, 0.0, -1, -1, 1, True, "wide"),
    (1.2825, 1.2825, -1.5, 1, 1, 0, False, "wide"),
    (1.6, 1.6, 0.0, 1, 1, 0, False, "wide"),
    (1.212, 1.212, 0.0, 1, 1, 0, False, "wide"),
    (1.3, 1.3, 0.0, 1, 1, 0, False, "wide"),
    (2.5, 2.5, 0.0, 1, 1, 0, False, "wide"),
    (1.25, 1.1, 0.0, 1, 1, 0, False, "wide"),
]
HELD_OUT: list[Footprint] = [
    (4.7, 1.3, -1.5, 1, 1, 0, False, "wide"),
    (5.13, 5.13, 0.0, 1, -1, 0, False, "wide"),
    (13.2, 5.13, 0.0, 1, -1, 0, False, "dark 16-bit"),
    (2.2, 1.9, -1.5, -1, 1, 1, False, "wide"),
    (7.77, 7.77, -1.5, 1, -1, 0, False, "sparse"),
    (3.6, 1.1, 0.0, -1, -1, 1, True, "uniform 16-bit with 0 and 1"),
    (9.5, 2.1, -0.75, 1, 1, 1, True, "dark 8-bit"),
    (1.9, 1.05, 0.0, 1, 1, 0, False, "sparse"),
    (16.6, 4.0, 0.0, -1, 1, 0, False, "wide"),
    (2.9, 2.0, 0.3, 1, -1, 1, False, "uniform 16-bit with 0 and 1"),
]


def footprint_samples(
    probe: Probe, footprint: Footprint, seed: int, n: int = 20000
) -> dict[str, Any]:
    """Random texels on the two levels of one footprint, every channel: the hardware against the
    exact sum (decision 071) and the accumulator (decision 083)."""
    a, b, bias, sign, minor_sign, axis, swap, family = footprint
    rng = np.random.default_rng(seed)
    lam = int(lod(probe, np.array([a]), np.array([b]), bias)[0])
    lower = max(lam, 0) >> 8
    geometry = []
    for k in (lower, lower + 1):
        m = marginals(probe, np.array([a]), np.array([b]), bias, k, sign, axis, swap)
        g = decode(m[0], axis == 1)
        assert isinstance(g, tuple), g
        geometry.append(g)
    size = 256
    levels = empty(size)
    for k in (lower, lower + 1):
        levels[k][...] = FAMILIES[family](rng, levels[k].shape)
    u = ((rng.integers(0, 256 * size, n) / 256 + 0.5) / size).astype(np.float32)
    v = ((rng.integers(0, 256 * size, n) / 256 + 0.5) / size).astype(np.float32)
    ddx, ddy = footprint_gradients(a, b, size, sign, axis, swap, minor_sign)
    got = sample(probe, levels, u, v, ddx, ddy, bias)
    equal = modelled = 0
    for c in range(4):
        channel = [level[..., c] for level in levels]
        for i in range(n):
            ordered = ordered_probes(channel, float(u[i]), float(v[i]), lower, geometry, sign, axis)
            equal += ties_up(*exact_sum([taps for _, taps in ordered], 10)) == got[i, c]
            modelled += accumulate([(k, probe_sum(taps)) for k, taps in ordered]) == got[i, c]
    return {
        "footprint": f"{a} x {b}, bias {bias}, sign {sign}/{minor_sign}, axis {axis}"
        + (", swapped" if swap else "")
        + f", {family}",
        "lambda": lam,
        "geometry": geometry,
        "samples": 4 * n,
        "exact sum equal": equal,
        "accumulator equal": modelled,
    }


def accumulator_found_on(probe: Probe) -> dict[str, Any]:
    rows = [footprint_samples(probe, f, 100 + i) for i, f in enumerate(FOUND_ON)]
    return {
        "footprints": rows,
        "samples": sum(r["samples"] for r in rows),
        "accumulator equal": sum(r["accumulator equal"] for r in rows),
    }


def accumulator_held_out(probe: Probe) -> dict[str, Any]:
    rows = [footprint_samples(probe, f, 200 + i) for i, f in enumerate(HELD_OUT)]
    return {
        "footprints": rows,
        "samples": sum(r["samples"] for r in rows),
        "accumulator equal": sum(r["accumulator equal"] for r in rows),
    }


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m tools.parity.vk_sampler_probe.replica_gates <work-dir> [gate ...]")
        return 2
    probe = Probe(Path(argv[0]))
    sections: dict[str, Callable[[Probe], dict[str, Any]]] = {
        "gate 1: trilinear weight and tap split": trilinear_and_split,
        "gate 2: key sufficiency": key_sufficiency,
        "gate 2: geometry cells": geometry_cells,
        "gate 3: accumulation": accumulation,
        "gate 3: accumulator, footprints it was found on": accumulator_found_on,
        "gate 3: accumulator, held-out footprints": accumulator_held_out,
    }
    # Optional gate numbers select sections ("3" runs the gate-3 sections only).
    wanted = argv[1:]
    for name, section in sections.items():
        if wanted and name.split(":")[0].split()[1] not in wanted:
            continue
        print(json.dumps({name: section(probe)}, indent=1, default=int), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
