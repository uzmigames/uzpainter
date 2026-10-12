"""The measured tables of the texture-unit replica and its validation against the recording GPU
(decision 084; task phase1.9_compositor-resample-gaps). Synthetic textures only; no Painter data is
read. RTX 4090, driver 617.14, Vulkan, through `vkprobe.cpp`.

    python -m tools.parity.vk_sampler_probe.tables measure <work-dir> [<out-dir>]
    python -m tools.parity.vk_sampler_probe.tables validate <work-dir> <uzp-evaluator-tests.exe>

`measure` acquires both tables and writes `tu-lod.zlib` and `tu-geometry.zlib` (by default into
`src/evaluator/tables`, the layout of `src/evaluator/texture_unit.h`), printing what it measured
(about 25 minutes). `validate` runs the replica (`uzp-evaluator-tests texture-unit`) against the
GPU on designed and random axis-aligned samples and prints the differing counts (all must be 0).

The LOD table holds lambda (1/256) for the 9-bit mantissas (m_major, m_minor) of every exponent
difference 0..2 at a major exponent of 3, and lambda_major for every m_major. The geometry of a
cell (rho, f, sign) is decoded from 256-phase column weights (`replica_gates.decode`): along the
lower level 2 and the upper level 3 of a 1024 texture, with one footprint of the cell, at bias 0
or -1.5 as reaches it. Three corrections follow the decoder:
- a probe of weight 0 (the last probe of a level, by the gradient's sign) is found by a search
  around the neighbouring cells, which the decoder does not attempt;
- column weights do not separate a pair at +-p of weights w from one probe of weight 2w when
  p w = 64; the row weights (a sample moving along y) do, and they are checked for every cell;
- a clamped LOD (lambda' < 0) reads the cell (rho, 0), measured at bias -8 on level 0 for every
  rho.
"""

from __future__ import annotations

import json
import math
import multiprocessing
import struct
import subprocess
import sys
import zlib
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.vk_sampler_probe import replica_gates as rg
from tools.parity.vk_sampler_probe.measure import REPO, Probe

TABLES = REPO / "src" / "evaluator" / "tables"
RHO, FRACTIONS = 513, 147  # rho 0..512; f below 147 (t < 256)
Cell = tuple[int, int]  # (rho, f)
Key = tuple[int, int, int, int, int]  # (exponent difference, m_major, m_minor, biased lambda, bias)
Geometry = rg.Geometry
GeoKey = tuple[int, int, int, int]  # (rho, f, sign, level 2 lower / 3 upper)


# ── LOD ───────────────────────────────────────────────────────────────────────


def lod_table(probe: Probe) -> dict[int, np.ndarray]:
    """lambda (1/256) of (m_major, m_minor) for exponent differences 0..3, major exponent 3."""
    m = np.arange(512)
    ma, mb = (g.ravel() for g in np.meshgrid(m, m, indexing="ij"))
    table: dict[int, np.ndarray] = {}
    for de in range(4):
        table[de] = rg.lod(probe, rg.keyed(3, ma), rg.keyed(3 - de, mb), 0.0).reshape(512, 512)
    return table


def major_lod(table: dict[int, np.ndarray]) -> np.ndarray:
    """lambda_major of every m_major: an exponent difference of 3 clamps the ratio to 4."""
    assert np.all(table[3] == table[3][:, :1]), "ratios above 4 clamp to 4"
    out: np.ndarray = table[3][:, 0] + 512
    return out


def cells(table: dict[int, np.ndarray]) -> dict[Cell, Key]:
    """One key per cell (rho, f) reached at bias 0 or -1.5: every cell with f < 147 and one with
    f >= 147 per rho (whose upper level holds the full-weight geometry)."""
    lmaj = major_lod(table)
    m = np.arange(512)
    reps: dict[Cell, Key] = {}
    for bias in (0, -384):
        for de in range(4):
            valid = np.ones((512, 512), bool) if de else (m[:, None] >= m[None, :])
            lam = table[de]
            rho = lmaj[:, None] - lam
            biased = lam + bias
            for ma, mb in zip(*np.nonzero(valid), strict=True):
                cell = (int(rho[ma, mb]), int(biased[ma, mb]) & 255)
                reps.setdefault(cell, (de, int(ma), int(mb), int(biased[ma, mb]), bias))
    need = {c: k for c, k in reps.items() if c[1] < FRACTIONS}
    full: dict[int, tuple[Cell, Key]] = {}
    for c, k in sorted(reps.items()):
        if c[1] >= FRACTIONS:
            full.setdefault(c[0], (c, k))
    need.update(dict(full.values()))
    return need


def footprint(key: Key) -> tuple[float, float, float]:
    """(major, minor, bias) of a key, scaled so that the biased lambda lies on level 2."""
    de, ma, mb, biased, bias = key
    e = 3 + 2 - (biased >> 8)
    return (
        2.0**e * (1 + (ma + 0.5) / 512),
        2.0 ** (e - de) * (1 + (mb + 0.5) / 512),
        bias / 256,
    )


# ── Geometry ──────────────────────────────────────────────────────────────────


def _near(
    z: np.ndarray,
    rest: np.ndarray,
    pairs: list[rg.Pair],
    left: int,
    hint: Geometry,
    found: list[Geometry],
) -> None:
    """replica_gates.search restricted to pairs near `hint` (offset +-12, weight +-6)."""
    k = len(pairs)
    if left == 0:
        if not np.any(rest):
            found.append(tuple(pairs))
        return
    if k >= len(hint):
        return
    hp, hwl, _, hm = hint[k]
    first = int(z[np.argmax(rest > 0)])
    last = int(z[len(z) - 1 - np.argmax(rest[::-1] < left)])
    for mult in (4, 2, 1):
        centre = hwl * hm // mult
        for wl in range(max(1, centre - 6), centre + 7):
            p = rg.FIRST[False][wl] - first
            if p < 0 or abs(p - hp) > 12 or (pairs and p > pairs[-1][0]):
                continue
            for wr in range(max(1, wl - 2), wl + 3):
                if mult * (wl + wr) > left or last - rg.FULL[False][wr] + 1 != p:
                    continue
                r2 = rest - mult * (rg.phi(wl, z + p) + rg.phi(wr, z - p))
                if np.any(r2 < 0) or np.any(np.diff(r2) < 0):
                    continue
                _near(z, r2, [*pairs, (p, wl, wr, mult)], left - mult * (wl + wr), hint, found)


def decode_near(m: np.ndarray, hint: Geometry | None) -> Geometry | None | str:
    """The decoder's result, found first among geometries near `hint`."""
    if hint:
        cumulative = np.concatenate([np.zeros((256, 1), np.int64), np.cumsum(m, 1)], 1)
        z = (256 * (rg.LO + np.arange(rg.NC + 1))[None, :] - np.arange(256)[:, None]).ravel()
        order = np.argsort(z)
        z, mass = z[order], cumulative.ravel()[order]
        found: list[Geometry] = []
        _near(z, mass.copy(), [], int(mass[-1]), hint, found)
        if found:
            top = max(min(pair[3] for pair in g) for g in found)
            best = sorted({g for g in found if min(pair[3] for pair in g) == top})
            if len(best) == 1:
                return best[0]
    return rg.decode(m)


def _decode_sequences(
    jobs: list[tuple[tuple[int, int, int], list[tuple[int, np.ndarray]]]],
) -> dict[GeoKey, Any]:
    out: dict[GeoKey, Any] = {}
    for (rho, sign, level), sequence in jobs:
        hint: Geometry | None = None
        for f, m in sequence:
            g = decode_near(m, hint)
            out[(rho, f, sign, level)] = g
            if isinstance(g, tuple) and g:
                hint = g
    return out


def columns(g: Sequence[rg.Pair]) -> np.ndarray:
    """The 256-phase column weights (1/1024) of a geometry, for a sample moving along x."""
    m = np.zeros((256, rg.NC), np.int64)
    phase = np.arange(256)
    for p, wl, wr, mult in g:
        for offset, w in ((-p, wl), (p, wr)):
            if w == 0:
                continue
            x = phase + offset
            x1 = rg.rhu(w * (x & 255))
            np.add.at(m, (phase, (x >> 8) - rg.LO), mult * (w - x1))
            np.add.at(m, (phase, (x >> 8) + 1 - rg.LO), mult * x1)
    return m


def rows(g: Sequence[rg.Pair]) -> np.ndarray:
    """The 256-phase row weights (1/1024) of a geometry, for a sample moving along y at x phase 0:
    rule F's y split of each probe's two columns."""
    m = np.zeros((256, rg.NC), np.int64)
    phase = np.arange(256)
    row, fy = phase >> 8, phase & 255
    for p, wl, wr, mult in g:
        for offset, w in ((-p, wl), (p, wr)):
            if w == 0:
                continue
            x1 = rg.rhu(w * (offset & 255))
            for part, rnd in ((w - x1, rg.rhd), (x1, rg.rhu)):
                below = rnd(part * fy)
                np.add.at(m, (phase, row - rg.LO), mult * (part - below))
                np.add.at(m, (phase, row + 1 - rg.LO), mult * below)
    return m


def row_marginals(
    probe: Probe, a: np.ndarray, b: np.ndarray, bias: float, level: int, sign: int
) -> np.ndarray:
    """[key, phase, row]: the weights (1/1024) of level `level` summed along x, at the 256
    phases of a sample moving along y from a texel centre (x-major footprints)."""
    size = 1024
    sk = size >> level
    phase = np.tile(np.arange(256), a.size)
    v = (400 + phase / 256 + 0.5) / sk
    u = np.full(v.size, (400 + 0.5) / sk)
    ddx, ddy = rg.footprint_gradients(np.repeat(a, 256), np.repeat(b, 256), size, sign)
    result = np.zeros((v.size, rg.NC), np.int64)
    for start in range(0, rg.NC, 8):
        levels = rg.empty(size)
        for q, d in enumerate(range(rg.LO + start, min(rg.HI, rg.LO + start + 8))):
            levels[level][(400 + d) % sk, :, q // 2] = 1.0 if q % 2 == 0 else 2.0**-12
        out = rg.sample(probe, levels, u, v, ddx, ddy, bias)
        for q in range(min(8, rg.NC - start)):
            hi = np.floor(out[:, q // 2] * 1024 + 2.0**-14)
            result[:, start + q] = (
                hi if q % 2 == 0 else np.round((out[:, q // 2] * 1024 - hi) * 4096)
            )
    marg: np.ndarray = result.reshape(a.size, 256, rg.NC)
    return marg


def zero_weight(m: np.ndarray, neighbours: list[Geometry]) -> Geometry | None:
    """A geometry whose outer pair has a probe of weight 0, near the neighbouring cells'."""
    found: set[Geometry] = set()
    for hint in neighbours:
        base = list(hint)
        if len(base) == 1:
            wider = [h for h in neighbours if len(h) == 2]
            if not wider:
                continue
            base = [wider[0][0], base[0]]
        if len(base) != 2:
            continue
        (p1, _, _, m1), (p2, wl2, wr2, m2) = base
        inner = {
            (q, a, b, m2): columns([(q, a, b, m2)])
            for q in range(max(1, p2 - 8), p2 + 9)
            for a in range(max(0, wl2 - 4), wl2 + 5)
            for b in range(max(0, wr2 - 4), wr2 + 5)
        }
        for q in range(max(0, p1 - 12), p1 + 13):
            for a in range(4):
                for b in range(4):
                    if a + b == 0 or (a and b):
                        continue
                    rest = m - columns([(q, a, b, m1)])
                    if rest.min() < 0:
                        continue
                    for pair, cols in inner.items():
                        if q > pair[0] and np.array_equal(cols, rest):
                            found.add(((q, a, b, m1), pair))
    return found.pop() if len(found) == 1 else None


def merged(g: Geometry) -> Geometry:
    """The geometry with every pair at +-p of weight w (p w = 64, multiplicity m >= 2) replaced
    by one probe of weight 2w at offset 0 (multiplicity m / 2): equal column weights."""
    return tuple(
        (0, 2 * wl, 2 * wr, mult // 2)
        if p and p * wl == 64 and wl == wr and mult >= 2
        else (p, wl, wr, mult)
        for p, wl, wr, mult in g
    )


def acquire(probe: Probe, need: dict[Cell, Key]) -> tuple[dict[GeoKey, Geometry], Counter[str]]:
    stats: Counter[str] = Counter()
    geometry: dict[GeoKey, Any] = {}
    groups: dict[int, list[tuple[Cell, Key]]] = defaultdict(list)
    for cell, key in sorted(need.items()):
        groups[key[4]].append((cell, key))
    batches: list[tuple[int, list[tuple[Cell, Key]]]] = []
    for bias, items in sorted(groups.items()):
        by_rho: dict[int, list[tuple[Cell, Key]]] = defaultdict(list)
        for cell, key in items:
            by_rho[cell[0]].append((cell, key))
        chunk: list[tuple[Cell, Key]] = []
        for rho in sorted(by_rho):
            chunk += by_rho[rho]
            if len(chunk) >= 2048:
                batches.append((bias, chunk))
                chunk = []
        if chunk:
            batches.append((bias, chunk))
    with multiprocessing.Pool(16) as pool:
        pending = []
        for bias, batch in batches:
            prints = [footprint(key) for _, key in batch]
            a = np.array([x[0] for x in prints])
            b = np.array([x[1] for x in prints])
            lam = rg.lod(probe, a, b, bias / 256)
            want = np.array([key[3] + 256 * (2 - (key[3] >> 8)) for _, key in batch])
            assert np.array_equal(lam, want), "every footprint lies on level 2"
            sequences: dict[tuple[int, int, int], list[tuple[int, np.ndarray]]] = defaultdict(list)
            for sign in (1, -1):
                for level in (2, 3):
                    marg = rg.marginals(probe, a, b, bias / 256, level, sign)
                    for i, (cell, _) in enumerate(batch):
                        t = min(256, (7 * cell[1]) >> 2)
                        if (level == 2 and t == 256) or (level == 3 and t == 0):
                            geometry[(cell[0], cell[1], sign, level)] = ()
                        else:
                            sequences[(cell[0], sign, level)].append((cell[1], marg[i]))
            jobs = [((k, sorted(v, key=lambda x: x[0]))) for k, v in sequences.items()]
            pending.append(pool.map_async(_decode_sequences, [jobs[j::16] for j in range(16)]))
        for result in pending:
            for part in result.get():
                geometry.update(part)
    # Probes of weight 0.
    for gkey, g in sorted(geometry.items()):
        if isinstance(g, tuple):
            continue
        rho, f, sign, level = gkey
        major, minor, shift = footprint(need[(rho, f)])
        m = rg.marginals(probe, np.array([major]), np.array([minor]), shift, level, sign)[0]
        near = [geometry.get((rho, f + d, sign, level)) for d in (-2, -1, 1, 2)]
        fixed = zero_weight(m, [h for h in near if isinstance(h, tuple) and h])
        assert fixed is not None, gkey
        geometry[gkey] = fixed
        stats["probes of weight 0"] += 1
    # Row weights separate the merged probes.
    for bias, batch in batches:
        prints = [footprint(key) for _, key in batch]
        a = np.array([x[0] for x in prints])
        b = np.array([x[1] for x in prints])
        for sign in (1, -1):
            for level in (2, 3):
                marg = row_marginals(probe, a, b, bias / 256, level, sign)
                for i, (cell, _) in enumerate(batch):
                    gkey = (cell[0], cell[1], sign, level)
                    g = geometry[gkey]
                    if not g or np.array_equal(rows(g), marg[i]):
                        stats["row weights equal"] += 1
                        continue
                    alternative = merged(g)
                    assert np.array_equal(rows(alternative), marg[i]), gkey
                    geometry[gkey] = alternative
                    stats["merged by the row weights"] += 1
    return geometry, stats


def clamped(probe: Probe, need: dict[Cell, Key], geometry: dict[GeoKey, Geometry]) -> Counter[str]:
    """The level-0 geometry at bias -8 (lambda' < 0) of every rho against the cell (rho, 0)."""
    stats: Counter[str] = Counter()
    keys: dict[int, Key] = {}
    for cell, key in sorted(need.items()):
        keys.setdefault(cell[0], key)
    rhos = sorted(keys)
    prints = [footprint(keys[r]) for r in rhos]
    a = np.array([x[0] for x in prints])
    b = np.array([x[1] for x in prints])
    for sign in (1, -1):
        cols = rg.marginals(probe, a, b, -8.0, 0, sign)
        rws = row_marginals(probe, a, b, -8.0, 0, sign)
        for rho, m, r in zip(rhos, cols, rws, strict=True):
            hint = geometry.get((rho, 0, sign, 2)) or geometry.get((rho, 1, sign, 2))
            g = decode_near(m, hint)
            assert isinstance(g, tuple), (rho, sign)
            if not np.array_equal(rows(g), r):
                g = merged(g)
                assert np.array_equal(rows(g), r), (rho, sign)
            known = geometry.get((rho, 0, sign, 2))
            if known is None:
                geometry[(rho, 0, sign, 2)] = g
                geometry[(rho, 0, sign, 3)] = ()
                stats["clamped only"] += 1
            else:
                stats["equal to (rho, 0)" if known == g else "different from (rho, 0)"] += 1
    return stats


def pack_lod(table: dict[int, np.ndarray]) -> bytes:
    values = np.concatenate(
        [table[0].ravel(), table[1].ravel(), table[2].ravel(), major_lod(table)]
    )
    return zlib.compress(values.astype("<u2").tobytes(), 9)


def pack_geometry(geometry: dict[GeoKey, Geometry]) -> bytes:
    words = np.zeros((RHO * FRACTIONS * 4 + RHO * 2, 4), np.uint32)
    words[:, 0] = 0xFF

    def entry(g: Geometry) -> list[int]:
        w = [len(g), 0, 0, 0]
        for k, (p, wl, wr, mult) in enumerate(g):
            w[0] |= mult << (8 + 8 * k)
            w[1] |= p << (16 * k)
            w[2 + k] = wl | (wr << 16)
        return w

    full: dict[tuple[int, int], Geometry] = {}
    for (rho, f, sign, level), g in geometry.items():
        s = 0 if sign > 0 else 1
        if f < FRACTIONS:
            words[((rho * FRACTIONS + f) * 2 + s) * 2 + level - 2] = entry(g)
        elif level == 3:
            assert full.setdefault((rho, s), g) == g
    for (rho, s), g in full.items():
        words[RHO * FRACTIONS * 4 + rho * 2 + s] = entry(g)
    return zlib.compress(words.astype("<u4").tobytes(), 9)


def measure(work: Path, out: Path) -> dict[str, Any]:
    probe = Probe(work)
    table = lod_table(probe)
    need = cells(table)
    geometry, stats = acquire(probe, need)
    stats.update(clamped(probe, need, geometry))
    full = [
        g == geometry.get((rho, 0, sign, 2))
        for (rho, f, sign, level), g in geometry.items()
        if f >= FRACTIONS and level == 3 and (rho, 0, sign, 2) in geometry
    ]
    out.mkdir(parents=True, exist_ok=True)
    (out / "tu-lod.zlib").write_bytes(pack_lod(table))
    (out / "tu-geometry.zlib").write_bytes(pack_geometry(geometry))
    shapes = Counter(
        "empty" if not g else f"{len(g)} pair(s)" for g in geometry.values() if isinstance(g, tuple)
    )
    return {
        "cells": len(need),
        "level geometries": len(geometry),
        "shapes": dict(shapes),
        "corrections": dict(stats),
        "full-weight upper level equal to the lower level at f = 0": f"{sum(full)} of {len(full)}",
    }


# ── Validation ────────────────────────────────────────────────────────────────


def replica(exe: Path, work: Path, levels: list[np.ndarray], records: np.ndarray) -> np.ndarray:
    """uzp-evaluator-tests texture-unit on a mip chain (rows bottom up) and sample records."""
    folder = work / "texture-unit"
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "tu-in.bin", "wb") as f:
        f.write(struct.pack("<I", levels[0].shape[0]))
        for level in levels:
            f.write(np.ascontiguousarray(level[..., :3], "<f4").tobytes())
        f.write(struct.pack("<I", len(records)))
        f.write(np.ascontiguousarray(records, "<u4").tobytes())
    subprocess.run(
        [str(exe), "texture-unit", str(REPO / "assets"), str(folder)],
        check=True,
        capture_output=True,
    )
    out: np.ndarray = np.fromfile(folder / "tu-out.bin", "<f4").reshape(-1, 3)
    return out


def records(
    u: np.ndarray,
    v: np.ndarray,
    ddx: tuple[np.ndarray, np.ndarray],
    ddy: tuple[np.ndarray, np.ndarray],
    bias: int,
    flags: int,
) -> np.ndarray:
    r = np.zeros((u.size, 8), np.uint32)
    for k, value in enumerate((u, v, ddx[0], ddx[1], ddy[0], ddy[1])):
        r[:, k] = np.asarray(value, np.float32).view(np.uint32)
    r[:, 6] = np.int32(bias).view(np.uint32)
    r[:, 7] = flags
    return r


FAMILIES = {
    "uniform 16-bit": lambda rng, shape: rng.integers(0, 65536, shape) / 65535,
    "dark 16-bit": lambda rng, shape: np.floor(np.exp2(rng.uniform(0, 16, shape))) / 65535,
    "uniform 8-bit": lambda rng, shape: rng.integers(0, 256, shape) / 255,
}


def random_set(
    rng: np.random.Generator, n: int, size: int, kind: str
) -> tuple[np.ndarray, np.ndarray, tuple[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]:
    """u, v, ddx, ddy of n axis-aligned samples: footprints from a quarter texel to twice the
    texture, ratios 1 to 11, both signs, both axes, ddx and ddy swapped; `kind` "near" keeps the
    two lengths within four 9-bit bins (near-isotropic), "edges" puts the lengths on 9-bit bin
    edges and LOD steps."""
    major = np.exp2(rng.uniform(-2, math.log2(size) + 1, n))
    if kind == "near":
        minor = major * (1 + rng.integers(-4, 5, n) / 512 + rng.uniform(-1, 1, n) / 2048)
    else:
        choice = rng.integers(0, 4, n)
        ratio = np.select(
            [choice == 0, choice == 1, choice == 2],
            [np.ones(n), rng.uniform(1, 2, n), rng.uniform(2, 4.5, n)],
            np.exp2(rng.uniform(0, 3.5, n)),
        )
        minor = major / ratio
    if kind == "edges":
        # 9-bit bin edges: the length rounded to the bin start, then nudged by -1, 0 or +1 ulp
        for lengths in (major, minor):
            e = np.floor(np.log2(lengths))
            m = np.floor((lengths / 2.0**e - 1) * 512)
            edge = (2.0**e * (1 + m / 512)).astype(np.float32)
            step = rng.integers(-1, 2, n).astype(np.int32)
            lengths[:] = (edge.view(np.int32) + step).view(np.float32)
    sign = rng.choice([-1, 1], n)
    msign = rng.choice([-1, 1], n)
    axis = rng.integers(0, 2, n)
    swap = rng.integers(0, 2, n).astype(bool)
    ga = (sign * major / size).astype(np.float32)
    gb = (msign * minor / size).astype(np.float32)
    zero = np.zeros(n, np.float32)
    gx = (np.where(axis == 0, ga, gb), zero)  # the gradient along x
    gy = (zero, np.where(axis == 0, gb, ga))
    ddx = (np.where(swap, gy[0], gx[0]), np.where(swap, gy[1], gx[1]))
    ddy = (np.where(swap, gx[0], gy[0]), np.where(swap, gx[1], gy[1]))
    u = rng.uniform(-1, 2, n).astype(np.float32)
    v = rng.uniform(-1, 2, n).astype(np.float32)
    return u, v, ddx, ddy


def validate(work: Path, exe: Path) -> dict[str, Any]:
    probe = Probe(work)
    report: dict[str, Any] = {}
    plan = [
        (size, family, bias, clamp, kind)
        for size, family in (
            (32, "uniform 16-bit"),
            (64, "dark 16-bit"),
            (256, "uniform 8-bit"),
            (1024, "uniform 16-bit"),
        )
        for bias in (0.0, -1.5)
        for clamp in (False, True)
        for kind in ("random", "near", "edges")
    ]
    total = differing = 0
    for index, (size, family, bias, clamp, kind) in enumerate(plan):
        rng = np.random.default_rng(1000 + index)
        levels = rg.chain(FAMILIES[family](rng, (size, size, 4)).astype(np.float32))
        n = 20000
        u, v, ddx, ddy = random_set(rng, n, size, kind)
        got = rg.sample(probe, levels, u, v, ddx, ddy, bias, clamp=clamp)[:, :3]
        ours = replica(
            exe, work, levels, records(u, v, ddx, ddy, round(256 * bias), 0 if clamp else 3)
        )
        miss = int(np.any(ours != got, axis=1).sum())
        name = f"{size}, {family}, bias {bias}, {'clamp' if clamp else 'repeat'}, {kind}"
        report[name] = {"samples": n, "differing": miss}
        total += n
        differing += miss
    report["all"] = {"samples": total, "differing": differing}
    return report


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "measure":
        out = Path(argv[2]) if len(argv) > 2 else TABLES
        print(json.dumps(measure(Path(argv[1]), out), indent=1))
        return 0
    if len(argv) == 3 and argv[0] == "validate":
        print(json.dumps(validate(Path(argv[1]), Path(argv[2])), indent=1))
        return 0
    print(
        "usage: python -m tools.parity.vk_sampler_probe.tables measure <work-dir> [<out-dir>] | "
        "validate <work-dir> <uzp-evaluator-tests.exe>"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
