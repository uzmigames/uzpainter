"""Designed-input measurements of the recording GPU's texture unit through Vulkan (decision 060;
task phase1.9_compositor-resample-gaps): what a software replica of Painter's minification would
have to reproduce, and why no closed form was found.

Runs `vkprobe.cpp` (via `measure.Probe`) on synthetic textures only (impulses, coordinate ramps,
random texels); no Painter data is read. Prints the statistics as JSON.

    python -m tools.parity.vk_sampler_probe.texture_unit <work-dir>

Conventions: gradients are given in texels of level 0 (`a` along x, `b` along y); a kernel is the
weight of each texel around the sample, measured by
sampling a texture holding a single 1.0 at level 0 (red) and level 1 (green), reported in units of
1/512 (the probes' weight unit) unless stated.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.vk_sampler_probe.measure import Probe, nearest_ties_up

SIZE = 64
CENTRE = 32
LINE = 256  # output texels per row of a probe run


def run(
    probe: Probe,
    levels: list[np.ndarray],
    u: np.ndarray,
    v: np.ndarray,
    gradients: tuple[Any, ...],
    *,
    level0: bool = False,
    bias: float = 0.0,
    clamp: bool = True,
) -> np.ndarray:
    """SampleGrad (or SampleLevel 0) at each (u, v); the RGBA results, one row per sample."""
    count = u.size
    rows = -(-count // LINE)
    params = np.zeros((rows * LINE, 2, 4), np.float32)
    params[:count, 0, 0], params[:count, 0, 1] = u.ravel(), v.ravel()
    # (u, v, ddx.x, ddx.y), (ddy.x, ddy.y, level-0 flag, 0): measure.KERNEL's layout.
    for (row, column), value in zip(((0, 2), (0, 3), (1, 0), (1, 1)), gradients, strict=True):
        params[:count, row, column] = np.broadcast_to(value, u.shape).ravel()
    params[:count, 1, 2] = float(level0)
    out = probe.run(levels, params.reshape(-1, 4), width=LINE, bias=bias, clamp=clamp)
    result: np.ndarray = out.reshape(-1, 4)[:count]
    return result


def impulses() -> list[np.ndarray]:
    levels = [np.zeros((SIZE >> k, SIZE >> k, 4), np.float32) for k in range(7)]
    levels[0][CENTRE, CENTRE, 0] = 1.0
    levels[1][CENTRE // 2, CENTRE // 2, 1] = 1.0
    return levels


def kernels(
    probe: Probe,
    footprints: Sequence[Sequence[float]],
    phases: list[tuple[int, int]],
    radius: int,
    bias: float,
) -> np.ndarray:
    """[footprint, phase, y, x]: the level-0 weight, in units of 2^-17, of the texel at
    (x, y) - radius from the base texel of a sample at sub-texel phase (px, py) / 256."""
    offsets = np.arange(-radius, radius + 1)
    shape = (len(footprints), len(phases), offsets.size, offsets.size)
    u = np.zeros(shape)
    v = np.zeros(shape)
    for k, (px, py) in enumerate(phases):
        u[:, k] = (CENTRE - offsets[None, :] + px / 256 + 0.5) / SIZE
        v[:, k] = (CENTRE - offsets[:, None] + py / 256 + 0.5) / SIZE
    g = np.asarray(footprints, np.float64)[:, None, None, None, :] / SIZE
    gradients = tuple(np.broadcast_to(g[..., c], shape).astype(np.float32) for c in range(4))
    out = run(probe, impulses(), u.astype(np.float32), v.astype(np.float32), gradients, bias=bias)
    weights: np.ndarray = np.round(out[:, 0].reshape(shape) * 512 * 256).astype(np.int64)
    return weights


def coordinates(probe: Probe) -> dict[str, int]:
    """X = floor(256 (u W - 1/2) + 1/2) from the float32 u, read from a texture holding x."""
    rng = np.random.default_rng(1)
    result = {}
    for width in (64, 1024, 4096):
        x = np.arange(width, dtype=np.float32)
        level = np.zeros((8, width, 4), np.float32)
        level[..., 0] = x
        k = rng.integers(-12 * width * 512, 12 * width * 512, 100_000)
        u = (k / (width * 512.0)).astype(np.float32)
        u = (u.view(np.int32) + rng.integers(-3, 4, u.size).astype(np.int32)).view(np.float32)
        u = u[np.isfinite(u)]
        out = run(
            probe,
            [level],
            u,
            np.full(u.shape, 0.5, np.float32),
            (0, 0, 0, 0),
            level0=True,
            clamp=False,
        )
        fixed = np.floor(256 * (u.astype(np.float64) * width - 0.5) + 0.5)
        x0 = np.mod(np.floor(fixed / 256), width)
        frac = fixed - 256 * np.floor(fixed / 256)
        predicted = np.where(x0 == width - 1, (256 - frac) * (width - 1), x0 * 256 + frac)
        result[f"W={width} samples"] = int(u.size)
        result[f"W={width} differing"] = int(
            (predicted != out[:, 0].astype(np.float64) * 256).sum()
        )
    return result


def lod_steps(probe: Probe) -> dict[str, int]:
    """Isotropic footprints p in [1, 2): where the level-1 weight changes, in 1/512 of p."""
    p = np.linspace(1.0, 2.0, 1 << 16, endpoint=False)
    levels = [np.full((SIZE >> k, SIZE >> k, 4), float(k), np.float32) for k in range(7)]
    g = (p / SIZE).astype(np.float32)
    out = run(
        probe,
        levels,
        np.full(p.shape, 0.3, np.float32),
        np.full(p.shape, 0.6, np.float32),
        (g, 0, 0, g),
        clamp=False,
    )
    t = np.round(out[:, 0].astype(np.float64) * 256).astype(np.int64)
    changes = np.nonzero(np.diff(t))[0] + 1
    on_grid = np.floor(p[changes] * 512) != np.floor(p[changes - 1] * 512)
    return {"changes": int(changes.size), "changes off the 1/512 grid": int((~on_grid).sum())}


def two_probe_table(probe: Probe) -> np.ndarray:
    """d[a, b]: the neighbour weight (1/512) of a centred sample for the 9-bit mantissas a >= b
    of [1, 2) at LOD bias -8 (level 0): the offset of the two probes in 1/256 texel."""
    bins = np.arange(512)
    a, b = np.meshgrid(1 + (bins + 0.5) / 512, 1 + (bins + 0.5) / 512, indexing="ij")
    keep = a >= b
    u = np.full(keep.sum(), (CENTRE + 1 + 0.5) / SIZE, np.float32)
    v = np.full(keep.sum(), (CENTRE + 0.5) / SIZE, np.float32)
    out = run(
        probe,
        impulses(),
        u,
        v,
        ((a[keep] / SIZE).astype(np.float32), 0, 0, (b[keep] / SIZE).astype(np.float32)),
        bias=-8.0,
    )
    table = np.full((512, 512), -1, np.int64)
    table[keep] = np.round(out[:, 0] * 512).astype(np.int64)
    return table


def mantissa_invariance(probe: Probe) -> dict[str, int]:
    """The two-probe weight at the two ends of each 9-bit mantissa bin of both gradients."""
    rng = np.random.default_rng(7)
    ka, kb = rng.integers(0, 512, 20_000), rng.integers(0, 512, 20_000)
    ka, kb = np.maximum(ka, kb), np.minimum(ka, kb)
    u = np.full(ka.shape, (CENTRE + 1 + 0.5) / SIZE, np.float32)
    v = np.full(ka.shape, (CENTRE + 0.5) / SIZE, np.float32)
    results = []
    for fa, fb in ((0.002, 0.002), (0.998, 0.002), (0.002, 0.998), (0.998, 0.998)):
        a = ((1 + (ka + fa) / 512) / SIZE).astype(np.float32)
        b = ((1 + (kb + fb) / 512) / SIZE).astype(np.float32)
        results.append(run(probe, impulses(), u, v, (a, 0, 0, b), bias=-8.0)[:, 0])
    return {"pairs": int(ka.size), "differing": int(sum((r != results[0]).sum() for r in results))}


def separable(table: np.ndarray) -> dict[str, Any]:
    """Linear-programming feasibility of d = G(F(a) + P(b)) with G, P monotone and F free, and of
    d = G(log2(a - b) + F(a)), over the measured table (scipy's HiGHS, on the owner's machine)."""
    from scipy.optimize import linprog
    from scipy.sparse import coo_matrix

    h = table // 2
    pairs = [(ka, kb) for ka in range(512) for kb in range(ka + 1)]
    result: dict[str, Any] = {
        "reversals along a": int(sum((np.diff(h[kb:, kb]) < 0).sum() for kb in range(512))),
        "reversals along b": int(sum((np.diff(h[ka, : ka + 1]) > 0).sum() for ka in range(512))),
    }
    top = int(h.max()) + 2
    eps = 1e-4

    def feasible(rows: list[tuple[list[int], list[float], float]], count: int) -> str:
        r, c, val, rhs = [], [], [], []
        for i, (cols, coeffs, bound) in enumerate(rows):
            r += [i] * len(cols)
            c += cols
            val += coeffs
            rhs.append(bound)
        matrix = coo_matrix((val, (r, c)), shape=(len(rows), count)).tocsr()
        bounds: list[tuple[float | None, float | None]] = [(None, None)] * count
        bounds[0] = (0.0, 0.0)
        res = linprog(
            np.zeros(count), A_ub=matrix, b_ub=np.array(rhs), bounds=bounds, method="highs"
        )
        return str(res.message)

    # G(F(a) + P(b)), d non-increasing in b: thresholds g[d] decreasing in the argument.
    nf, npb = 512, 512
    gi = nf + npb
    rows: list[tuple[list[int], list[float], float]] = []
    for ka, kb in pairs:
        d = int(h[ka, kb])
        rows.append(([gi + d, ka, nf + kb], [1.0, -1.0, -1.0], 0.0))
        if d >= 1:
            rows.append(([ka, nf + kb, gi + d - 1], [1.0, 1.0, -1.0], -eps))
    rows += [([nf + kb, nf + kb + 1], [1.0, -1.0], -eps) for kb in range(511)]
    result["G(F(a) + P(b))"] = feasible(rows, gi + top)
    # G(log2(a - b) + F(a)), d non-decreasing in the argument.
    rows = []
    for ka, kb in pairs:
        if ka == kb:
            continue
        d, x = int(h[ka, kb]), float(np.log2((ka - kb) / 512.0))
        rows.append(([nf + d, ka], [1.0, -1.0], x))
        if d + 1 < top:
            rows.append(([ka, nf + d + 1], [1.0, -1.0], -x - eps))
    result["G(log2(a - b) + F(a))"] = feasible(rows, nf + top)
    return result


def four_probes(probe: Probe) -> dict[str, Any]:
    """r = a / b in [2, 12] at phase 0: weights at -2..2 texels; K(+-1) and the clamp at r > 4."""
    ratios = [2.0, 2.25, 2.5, 3.0, 3.5, 4.0, 5.0, 8.0, 12.0]
    k = kernels(probe, [(r, 0, 0, 1.0) for r in ratios], [(0, 0)], 3, -8.0)[:, 0, 3, 1:6]
    return {f"r={r}": [int(x) // 256 for x in row] for r, row in zip(ratios, k, strict=True)}


def rotated(probe: Probe) -> dict[str, Any]:
    """Two-probe offsets (1/256 texel) decoded from the kernel of a 1.5 x 1 footprint rotated by
    theta, against the offset 86 of theta = 0 projected on the rotated axis."""

    def bilinear(px: int, py: int) -> dict[tuple[int, int], int]:
        fx, fy = px & 255, py & 255
        w11 = (fx * fy + 128) >> 8
        x0, y0 = px >> 8, py >> 8
        return {
            (x0, y0): 256 - fx - fy + w11,
            (x0 + 1, y0): fx - w11,
            (x0, y0 + 1): fy - w11,
            (x0 + 1, y0 + 1): w11,
        }

    result = {}
    for theta in (10, 30, 45, 60):
        t = np.deg2rad(theta)
        c, s = float(np.cos(t)), float(np.sin(t))
        measured = kernels(probe, [(1.5 * c, 1.5 * s, -s, c)], [(0, 0)], 2, -8.0)[0, 0]
        found = []
        for px in range(-160, 161):
            for py in range(-160, 161):
                model = np.zeros((5, 5), np.int64)
                for (x, y), w in bilinear(px, py).items():
                    model[2 + y, 2 + x] += w
                for (x, y), w in bilinear(-px, -py).items():
                    model[2 + y, 2 + x] += w
                if np.array_equal(model * 256, measured):
                    found.append((px, py))
        result[f"{theta} deg"] = {
            "decoded": max(found) if found else None,
            "along the axis": [round(86 * c, 1), round(86 * s, 1)],
        }
    return result


def accumulation(probe: Probe) -> dict[str, Any]:
    """Random texels sampled with multi-probe footprints at level 0, against the measured
    per-texel weights accumulated by the decision-043 rule (operands floor(t 2^(28 - E)), E the
    exponent of the largest weighed texel, one rounding to float32, ties up)."""
    rng = np.random.default_rng(11)
    footprints = [(1.5, 0, 0, 1.0), (2.5, 0, 0, 1.0), (3.0, 0, 0, 1.0), (2.2, 0, 0, 1.0)]
    phases = [(int(rng.integers(0, 256)), int(rng.integers(0, 256))) for _ in range(12)]
    weights = kernels(probe, footprints, phases, 4, -8.0)
    matched = total = 0
    for f, footprint in enumerate(footprints):
        texels = (rng.integers(0, 65536, (SIZE, SIZE)) / 65535).astype(np.float32)
        level = np.zeros((SIZE, SIZE, 4), np.float32)
        level[..., 0] = texels
        levels = [level]
        while levels[-1].shape[0] > 1:
            p = levels[-1].astype(np.float64)
            levels.append(
                nearest_ties_up((p[0::2, 0::2] + p[0::2, 1::2] + p[1::2, 0::2] + p[1::2, 1::2]) / 4)
            )
        bases = [(x, y) for x in range(8, 56, 4) for y in range(8, 56, 4)]
        for k, (px, py) in enumerate(phases):
            u = np.array([(x + px / 256 + 0.5) / SIZE for x, _ in bases], np.float32)
            v = np.array([(y + py / 256 + 0.5) / SIZE for _, y in bases], np.float32)
            g = (np.float32(footprint[0] / SIZE), 0, 0, np.float32(footprint[3] / SIZE))
            out = run(probe, levels, u, v, g, bias=-8.0)[:, 0]
            w = weights[f, k]
            for (x, y), value in zip(bases, out, strict=True):
                window = texels[y - 4 : y + 5, x - 4 : x + 5].astype(np.float64)
                largest = window[w > 0].max()
                if largest == 0:
                    continue
                exponent = int(np.frexp(largest)[1])
                acc = (w * np.floor(np.ldexp(window, 28 - exponent))).sum()
                rule = nearest_ties_up(np.array(np.ldexp(acc, exponent - 28 - 17)))
                matched += int(rule == value)
                total += 1
    return {"samples": total, "equal to the decision-043 rule": matched}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m tools.parity.vk_sampler_probe.texture_unit <work-dir>")
        return 2
    probe = Probe(Path(argv[0]))
    table = two_probe_table(probe)
    report = {
        "coordinates": coordinates(probe),
        "anisotropic LOD input": lod_steps(probe),
        "two-probe offset within 9-bit mantissa bins": mantissa_invariance(probe),
        "two-probe offset table": separable(table),
        "four probes (1/512, texels -2..2)": four_probes(probe),
        "rotated two-probe offsets": rotated(probe),
        "accumulation": accumulation(probe),
    }
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
