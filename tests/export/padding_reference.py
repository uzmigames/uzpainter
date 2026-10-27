"""The measured `infinite` padding of src/export/padding.h (phase1.25 item 2.7; decisions 197, 206,
267, 268, 270, 273, 275, 278 to 282, 285, 288, 290, 291, 294, 356, 364; measured only, decision
259), written again independently in Python for the tests: the ring over an OBJ's triangles, then
the jump flood.

The geometry (barycentrics, folds about seam edges, distances) is double precision with each
operation in padding.cpp's order, so that a far point at an exact half-texel boundary, where
decision 275's window is not identified (its open item (b)), falls on the same side as in
UzPainter. The comparator of equal shares (decision 273), the chain fractions (decision 268) and
the lerp chain are float32, each operation correctly rounded, through the recording GPU's
reciprocal and square root (tools/parity/fit/hwmath). So are decision 278's seam gate's face
normals and their dot product (decision 278's seam gate and decision 282's hinge gate), and
decision 282's far-tap comparator and its fold. The coverage snaps each vertex to 1/256 texel
(decision 281). No Painter data is read.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.fit import hwmath

F32 = np.float32
LEVELS = ((4, 1023), (3, 255), (2, 63))
# The 8-neighbours as (dy, dx), in scan order; the jump flood's offsets in the order tried.
NEIGHBOURS = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)]
FLOOD = ((0, 1), (0, -1), (-1, 0), (1, 0), (-1, 1), (1, -1), (-1, -1), (1, 1))
# Decision 282's tie band (which holds decision 288's float32-precision ties).
EQUAL_SHARE = 1e-5
ZERO_DISTANCE = 1e-6
COPLANAR = 1e-6
# Decision 364: unit normals whose cross product is shorter than this are parallel.
PARALLEL = 1e-10
KEPT = 8
# Decision 278's seam gate: the faces' float32 normal dot product at most FOLD_GATE; Painter's
# constant lies in (FOLD_LOW, FOLD_HIGH].
FOLD_GATE = F32(0.985)
FOLD_LOW = F32(0.98498905)
FOLD_HIGH = F32(0.98501915)
# Decisions 279 and 285's seam reach: UV segment distance at most REACH_CAP texels; Painter's cap
# lies in [REACH_LOW, REACH_HIGH) (bevelled-cube-256 (4, 234)'s edge at 1.77200433 included, the
# Wand's (740, 1459) edge at 1.78724202 excluded, rounded inward).
REACH_CAP = 1.78
REACH_LOW = 1.7720044
REACH_HIGH = 1.787242
# Decision 294's corner reach: a seam edge of a triangle outside tau's planar face whose nearest
# point to the ring texel's centre is an end V, and which is not collinear (UV |sin| at most
# COLLINEAR) with another seam edge of the island ending at V, reaches CORNER_GATED texels when
# another seam edge of the ring texel ending at V is gated, else CORNER_OPEN. Painter's caps lie in
# [CORNER_GATED_LOW, CORNER_GATED_HIGH) and [CORNER_OPEN_LOW, CORNER_OPEN_HIGH), its collinear
# threshold below COLLINEAR_HIGH (flagged from COLLINEAR_LOW: an exact continuation is exempt).
# The bounds round the Wand's edges inward: kept at 0.97461490 (274, 1989) and 1.07592644
# (634, 1418), dropped at 1.02000402 (175, 1101) and 1.20807410 (566, 1439); decision 294 writes
# the open low end 1.075926, which would drop (634, 1418)'s edge.
CORNER_GATED = 1.0
CORNER_GATED_LOW = 0.974615
CORNER_GATED_HIGH = 1.020004
CORNER_OPEN = 1.15
CORNER_OPEN_LOW = 1.0759265
CORNER_OPEN_HIGH = 1.208074
COLLINEAR = 1e-3
COLLINEAR_LOW = 1e-6
COLLINEAR_HIGH = 0.0305
# The reaches of `Ring.candidates` (decision 285's cap, decision 294's two corner caps and its
# collinear threshold), as Painter's are taken.
# Seam-strip ownership replaces nominal corner caps; their brackets remain diagnostics.
REACHES = (REACH_CAP, REACH_CAP, REACH_CAP, COLLINEAR)
# Decision 294: adjacent own taps whose distances lie within OWN_BAND relative are ordered by
# decision 273's comparator.
OWN_BAND = 1e-4
# Decision 291: a far point within WINDOW_SIDE texel of a window boundary (f - 1/2 integral) on
# some axis; at most WINDOW_SIDES such axes are tried both ways (more are flagged untried).
WINDOW_SIDE = 1e-4
WINDOW_SIDES = 10
# Decision 281: the coverage's vertex precision (texels), and the most hinges of a face path.
SUB_TEXEL = 256
MAX_HINGES = 4
# Decision 280's fixed orders of exactly tied taps, v-up offsets (du, dv): an own tap's from the
# ring texel, a far tap's from its window's base (floor(f_u - 1/2), ceil(f_v - 1/2)).
OWN_ORDER = ((1, 0), (-1, 0), (0, -1), (0, 1), (1, 1), (1, -1), (-1, 1), (-1, -1))
WINDOW_ORDER = ((0, 0), (1, 0), (0, 1), (1, 1), (0, -1), (1, -1), (-1, 0), (-1, 1), (-1, -1))
# The rank pairs those orders leave open (decision 280 open item (c)).
OWN_OPEN = {(0, 1), (2, 3), (5, 6)}
WINDOW_OPEN = {
    (a, b)
    for a in range(9)
    for b in range(a + 1, 9)
    if b > 5 and (a, b) != (6, 7) and not (b == 8 and a <= 2)
}

Vec = tuple[float, float, float]


def f32(x: Any) -> np.float32:
    return F32(x)


def round_f32(x: Fraction) -> np.float32:
    """`x` rounded to the nearest float32, ties to even."""
    near = F32(float(x))
    best: tuple[Fraction, np.float32] | None = None
    for c in (np.nextafter(near, F32(-np.inf)), near, np.nextafter(near, F32(np.inf))):
        d = abs(Fraction(float(c)) - x)
        even = int(np.array([c], F32).view(np.uint32)[0]) % 2 == 0
        if best is None or d < best[0] or (d == best[0] and even):
            best = (d, F32(c))
    assert best is not None
    return best[1]


def fma(a: Any, b: Any, c: Any) -> np.float32:
    """The float32 fused multiply-add: one rounding of the exact a b + c."""
    return round_f32(Fraction(float(a)) * Fraction(float(b)) + Fraction(float(c)))


def fractions(distances: Sequence[float]) -> list[np.float32]:
    """Decision 268's chain fractions for taps at `distances`, in tap order."""
    out: list[np.float32] = []
    if len(distances) < 2:
        return out  # a copy
    inv = [1.0 / d for d in distances]
    for level in range(len(distances) - 1):
        k, levels = LEVELS[level]
        share = inv[level] / sum(inv[level:])
        u = min(max(round((share - 1 / k) * k / (k - 1) * levels), 0), levels)
        out.append(F32(float(Fraction(levels + (k - 1) * u, k * levels))))
    return out


def chain(
    values: Sequence[np.float32], t: Sequence[np.float32], rounded: bool = True
) -> np.float32:
    """Decision 268's FMA lerp chain over `values` in tap order, then decision 206's 1 - (1 - m)
    when `rounded` (the Height the virtual normal's stencil reads is the raw chain, decision 288
    (a))."""
    n = len(values)
    m = values[0]
    if n > 1:
        last = f32(f32(1) - t[n - 2])
        m = fma(last, f32(values[n - 1] - values[n - 2]), values[n - 2])
        for level in range(n - 3, -1, -1):
            m = fma(t[level], f32(values[level] - m), m)
    if not rounded:
        return F32(m)
    return f32(f32(1) - f32(f32(1) - m))


def face_normal(p: Sequence[Sequence[float]]) -> list[np.float32]:
    """Decision 278's unit face normal of the triangle at float32 positions `p`:
    cross(P1 - P0, P2 - P0) divided by its length, each float32 operation rounded."""
    q = [[f32(c) for c in v] for v in p]
    e1 = [f32(q[1][i] - q[0][i]) for i in range(3)]
    e2 = [f32(q[2][i] - q[0][i]) for i in range(3)]
    n = [
        f32(f32(e1[1] * e2[2]) - f32(e1[2] * e2[1])),
        f32(f32(e1[2] * e2[0]) - f32(e1[0] * e2[2])),
        f32(f32(e1[0] * e2[1]) - f32(e1[1] * e2[0])),
    ]
    length = f32(np.sqrt(f32(f32(f32(n[0] * n[0]) + f32(n[1] * n[1])) + f32(n[2] * n[2]))))
    with np.errstate(divide="ignore", invalid="ignore"):
        return [f32(c / length) for c in n]


def seam_gate(
    n_own: Sequence[np.float32], n_far: Sequence[np.float32], q: Vec, p: Vec
) -> tuple[bool, bool, bool]:
    """Decision 278's gate of a seam edge for ring point `q` (p a vertex of the edge, `n_own` the
    normal of the ring texel's triangle tau, not of the edge's own triangle: decision 292): (gated,
    in the bracket, on the far plane)."""
    d = f32(f32(f32(n_own[0] * n_far[0]) + f32(n_own[1] * n_far[1])) + f32(n_own[2] * n_far[2]))
    side = dot((float(n_far[0]), float(n_far[1]), float(n_far[2])), sub(q, p))
    return (
        bool(d <= FOLD_GATE and side < 0.0),
        bool(FOLD_LOW < d <= FOLD_HIGH and side < 0.0),
        bool(side == 0.0 and d <= FOLD_HIGH),
    )


def strip_covers(a: tuple[float, float], b: tuple[float, float], px: float, py: float) -> bool:
    """Whether the one-texel seam strip of the UV segment a b (straight ends) covers the sample
    point (px, py): inside, or on an edge of the strip whose outward normal points to -u, or to -v
    (up the tile) for an edge with no u component (the top-left fill rule)."""
    ex, ey = b[0] - a[0], b[1] - a[1]
    length2 = ex * ex + ey * ey
    along = (px - a[0]) * ex + (py - a[1]) * ey
    cross = (px - a[0]) * ey - (py - a[1]) * ex
    half = 0.5 * math.sqrt(length2)
    if along < 0 or along > length2 or abs(cross) > half:
        return False

    def kept(nx: float, ny: float) -> bool:
        return nx < 0 or (nx == 0 and ny < 0)

    return (
        (along != 0 or kept(-ex, -ey))
        and (along != length2 or kept(ex, ey))
        and (cross != half or kept(ey, -ex))
        and (cross != -half or kept(-ey, ex))
    )


def segment_distance(a: tuple[float, float], b: tuple[float, float], px: float, py: float) -> float:
    """The texel-space distance from (px, py) to the segment a b."""
    ex, ey = b[0] - a[0], b[1] - a[1]
    length = ex * ex + ey * ey
    u = 0.0 if length == 0.0 else min(max(((px - a[0]) * ex + (py - a[1]) * ey) / length, 0.0), 1.0)
    return math.hypot(px - a[0] - u * ex, py - a[1] - u * ey)


def tap_count(cands: Sequence[tuple[float, bool, tuple[int, int]]]) -> int:
    """The chain's number of taps over `cands` (tap order): 1 when the nearest is at distance 0
    relative to the nearest own candidate, or to the farthest when none is own (decision 280)."""
    nearest = min((c[0] for c in cands if not c[1]), default=cands[-1][0])
    return min(4, len(cands)) if cands[0][0] > ZERO_DISTANCE * nearest else 1


def covered_texels(
    uv: Sequence[tuple[float, float]], width: int, height: int
) -> list[tuple[int, int]]:
    """The texels (col, row) whose centre the triangle of float32 UVs `uv` (v up) covers: inside or
    on its boundary, each vertex first rounded in texel space to the nearest 1/256 texel (decision
    281), nothing when the snapped triangle is degenerate."""
    t = [
        (
            round(u * width * SUB_TEXEL) / SUB_TEXEL,
            round((1.0 - v) * height * SUB_TEXEL) / SUB_TEXEL,
        )
        for u, v in uv
    ]

    def edge(a: tuple[float, float], b: tuple[float, float], x: float, y: float) -> float:
        return (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])

    area = edge(t[0], t[1], t[2][0], t[2][1])
    if area == 0.0:
        return []
    xs, ys = [c[0] for c in t], [c[1] for c in t]
    out = []
    for row in range(
        int(max(0.0, math.floor(min(ys) - 0.5))),
        int(min(height - 1.0, math.ceil(max(ys) - 0.5))) + 1,
    ):
        for col in range(
            int(max(0.0, math.floor(min(xs) - 0.5))),
            int(min(width - 1.0, math.ceil(max(xs) - 0.5))) + 1,
        ):
            w = [edge(t[i], t[(i + 1) % 3], col + 0.5, row + 0.5) for i in range(3)]
            if all(e >= 0.0 for e in w) if area > 0.0 else all(e <= 0.0 for e in w):
                out.append((col, row))
    return out


def box_normalised(positions: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Decision 273's mesh-box normalisation of float32 `positions`: ext = hi - lo,
    c = lo + ext / 2, r = 1 / (max(ext) / 2), P r - c r, each float32 operation rounded."""
    lo, hi = lo.astype(F32), hi.astype(F32)
    ext = (hi - lo).astype(F32)
    c = (lo + (ext * F32(0.5)).astype(F32)).astype(F32)
    r = F32(F32(1) / F32(ext.max() * F32(0.5)))
    result: np.ndarray = ((positions.astype(F32) * r).astype(F32) - (c * r).astype(F32)).astype(F32)
    return result


def position32(
    uv: np.ndarray,
    normalised: np.ndarray,
    width: int,
    height: int,
    x: int,
    y: int,
    *,
    fused_determinant: bool = False,
) -> list[np.float32]:
    """Decision 273's float32 position of texel (x, y)'s centre through the triangle of float32 UVs
    `uv` (v up) and box-normalised corners `normalised`: the texel-centre UV, barycentrics from the
    UV inverse matrix based at the third corner with the GPU reciprocal, fma(l2, P2, fma(l0, P0,
    l1 P1))."""
    u = [(f32(a), f32(b)) for a, b in uv]
    e0u, e0v = f32(u[0][0] - u[2][0]), f32(u[0][1] - u[2][1])
    e1u, e1v = f32(u[1][0] - u[2][0]), f32(u[1][1] - u[2][1])
    det = (
        fma(e0u, e1v, -f32(e0v * e1u))
        if fused_determinant
        else f32(f32(e0u * e1v) - f32(e0v * e1u))
    )
    r = F32(hwmath.rcp(np.array([det], F32))[0])
    m00, m01, m10, m11 = f32(e1v * r), f32(-e1u * r), f32(-e0v * r), f32(e0u * r)
    n = normalised.astype(F32)
    pu = f32(f32(x + 0.5) / f32(width))
    pv = f32(f32(1) - f32(f32(y + 0.5) / f32(height)))
    dx, dy = f32(pu - u[2][0]), f32(pv - u[2][1])
    l0 = fma(m00, dx, f32(m01 * dy))
    l1 = fma(m10, dx, f32(m11 * dy))
    l2 = f32(f32(1) - f32(l0 + l1))
    return [fma(l2, n[2][c], fma(l0, n[0][c], f32(l1 * n[1][c]))) for c in range(3)]


def distance32(q: Sequence[np.float32], p: Sequence[np.float32]) -> np.float32:
    """The FMA squared distance and the GPU square root."""
    d = [f32(q[c] - p[c]) for c in range(3)]
    squared = fma(d[2], d[2], fma(d[1], d[1], f32(d[0] * d[0])))
    return F32(hwmath.sqrt(np.array([squared], F32))[0])


def compare_distance(
    uv: np.ndarray,
    normalised: np.ndarray,
    width: int,
    height: int,
    ring: tuple[int, int],
    tap: tuple[int, int],
    *,
    fused_determinant: bool = True,
) -> np.float32:
    """Own-order comparator; tau explicitly keeps the split UV determinant."""
    q = position32(uv, normalised, width, height, *ring, fused_determinant=fused_determinant)
    p = position32(uv, normalised, width, height, *tap, fused_determinant=fused_determinant)
    d = [f32(q[c] - p[c]) for c in range(3)]
    squared = fma(d[2], d[2], fma(d[0], d[0], f32(d[1] * d[1])))
    return F32(hwmath.sqrt(np.array([squared], F32))[0])


def _dot32(a: Sequence[np.float32], b: Sequence[np.float32]) -> np.float32:
    return f32(f32(f32(a[0] * b[0]) + f32(a[1] * b[1])) + f32(a[2] * b[2]))


def _cross32(a: Sequence[np.float32], b: Sequence[np.float32]) -> list[np.float32]:
    return [
        f32(f32(a[1] * b[2]) - f32(a[2] * b[1])),
        f32(f32(a[2] * b[0]) - f32(a[0] * b[2])),
        f32(f32(a[0] * b[1]) - f32(a[1] * b[0])),
    ]


def _unit32(a: Sequence[np.float32]) -> list[np.float32]:
    length = F32(hwmath.sqrt(np.array([_dot32(a, a)], F32))[0])
    return [f32(c / length) for c in a]


def _sub32(a: Sequence[np.float32], b: Sequence[np.float32]) -> list[np.float32]:
    return [f32(a[c] - b[c]) for c in range(3)]


def _add32(a: Sequence[np.float32], b: Sequence[np.float32]) -> list[np.float32]:
    return [f32(a[c] + b[c]) for c in range(3)]


def _scale32(a: Sequence[np.float32], s: np.float32) -> list[np.float32]:
    return [f32(c * s) for c in a]


# ── Double-precision geometry, in padding.cpp's operation order ────────────


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec) -> Vec:
    return scale(a, 1.0 / norm(a))


def bits(x: float) -> int:
    """The float32 bits of `x`, -0 as +0: vertices weld by value (decision 288)."""
    return int(np.array([float(x) + 0.0], F32).view(np.uint32)[0])


Hinge = tuple[Vec, Vec, Vec, Vec]  # a point of the edge, the edge's unit, toward own, toward other


class Triangle:
    def __init__(
        self, p: list[Vec], uv: list[tuple[float, float]], width: int, height: int
    ) -> None:
        self.p = p
        self.uv = np.array(uv, F32)
        self.t = [(u * width, (1.0 - v) * height) for u, v in uv]
        self.vertex: list[int] = []
        self.corner: list[int] = []
        self.chart = 0
        self.face = 0
        self.normalised = np.zeros((3, 3), F32)
        self.normal = face_normal(p)

    def bary(self, x: float, y: float) -> tuple[float, float, float]:
        a, b, c = self.t
        area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        l1 = ((x - a[0]) * (c[1] - a[1]) - (y - a[1]) * (c[0] - a[0])) / area
        l2 = ((b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])) / area
        return (1.0 - l1 - l2, l1, l2)

    def point(self, w: tuple[float, float, float]) -> Vec:
        return add(add(scale(self.p[0], w[0]), scale(self.p[1], w[1])), scale(self.p[2], w[2]))

    def texel_of(self, q: Vec) -> tuple[float, float]:
        e1, e2, v = sub(self.p[1], self.p[0]), sub(self.p[2], self.p[0]), sub(q, self.p[0])
        a, b, c = dot(e1, e1), dot(e1, e2), dot(e2, e2)
        det = a * c - b * b
        l1 = (c * dot(e1, v) - b * dot(e2, v)) / det
        l2 = (a * dot(e2, v) - b * dot(e1, v)) / det
        l0 = 1.0 - l1 - l2
        t = self.t
        return (
            l0 * t[0][0] + l1 * t[1][0] + l2 * t[2][0],
            l0 * t[0][1] + l1 * t[1][1] + l2 * t[2][1],
        )

    def corner_at(self, v: int) -> int:
        return self.corner[self.vertex.index(v)]


def hinge(own: Triangle, other: Triangle, va: int, vb: int) -> Hinge:
    ia, ib = own.vertex.index(va), own.vertex.index(vb)
    ja, jb = other.vertex.index(va), other.vertex.index(vb)
    a = own.p[ia]
    e = unit(sub(own.p[ib], a))

    def across(to: Vec) -> Vec:
        v = sub(to, a)
        return unit(sub(v, scale(e, dot(v, e))))

    return a, e, across(own.p[3 - ia - ib]), across(other.p[3 - ja - jb])


def unfold(h: Hinge, p: Vec) -> Vec:
    """`p`, on the other triangle's side, rotated about the edge onto the own plane's far side."""
    a, e, in_own, in_other = h
    v = sub(p, a)
    s = dot(v, e)
    r = sub(v, scale(e, s))
    to = scale(in_own, -1.0)
    along, out = dot(r, in_other), dot(r, cross(e, in_other))
    return add(add(a, scale(e, s)), add(scale(to, along), scale(cross(e, to), out)))


def fold(h: Hinge, p: Vec) -> Vec:
    """The inverse of `unfold`."""
    a, e, in_own, in_other = h
    v = sub(p, a)
    s = dot(v, e)
    r = sub(v, scale(e, s))
    to = scale(in_own, -1.0)
    along, out = dot(r, to), dot(r, cross(e, to))
    return add(add(a, scale(e, s)), add(scale(in_other, along), scale(cross(e, in_other), out)))


def segment_gap(a: Vec, b: Vec, q: Vec) -> float:
    """The 3D distance from `q` to the segment a b."""
    e = sub(b, a)
    t = min(max(dot(sub(q, a), e) / dot(e, e), 0.0), 1.0)
    return norm(sub(q, add(a, scale(e, t))))


def plane_rotation(p: Vec, source: Triangle, target: Triangle) -> Vec:
    """Decision 364: `p` turned rigidly about the line where the plane of `source` meets the plane
    of `target`, by the angle between their unit face normals m and n (Rodrigues), so that the
    source plane lands on the target plane; as is when the planes are parallel or their normals
    meet at a dot product above FOLD_GATE (decision 282's gate). The line's point solves
    n.x = n.P_target, m.x = m.P_source, a.x = 0 (a the unit axis m x n) by Cramer's rule."""
    n = unit(tuple(float(c) for c in target.normal))  # type: ignore[arg-type]
    m = unit(tuple(float(c) for c in source.normal))  # type: ignore[arg-type]
    axis = cross(m, n)
    sine = norm(axis)
    cosine = dot(m, n)
    if sine < PARALLEL or cosine > float(FOLD_GATE):
        return p
    axis = scale(axis, 1.0 / sine)
    dn, dm = dot(n, target.p[0]), dot(m, source.p[0])
    across = cross(m, axis)
    det = dot(n, across)
    origin = scale(add(scale(across, dn), scale(cross(axis, n), dm)), 1.0 / det)
    v = sub(p, origin)
    turned = add(add(origin, scale(v, cosine)), scale(cross(axis, v), sine))
    return add(turned, scale(axis, dot(axis, v) * (1.0 - cosine)))


def obj_mesh(
    path: Path, material: str
) -> tuple[list[tuple[list[Vec], list[tuple[float, float]]]], np.ndarray, np.ndarray]:
    """The triangles of `material` in the OBJ at `path` (positions, UVs; polygons fanned from their
    last corner) and the box of every triangle corner of the mesh."""
    positions: list[Vec] = []
    uvs: list[tuple[float, float]] = []
    found: list[tuple[list[Vec], list[tuple[float, float]]]] = []
    corners_all: list[Vec] = []
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        keyword, _, rest = line.partition(" ")
        tokens = rest.split()
        if keyword == "v":
            x, y, z = (float(F32(float(t))) for t in tokens[:3])
            positions.append((x, y, z))
        elif keyword == "vt":
            uvs.append((float(F32(float(tokens[0]))), float(F32(float(tokens[1])))))
        elif keyword == "usemtl":
            current = rest.strip()
        elif keyword == "f":
            refs = [(int(r.split("/")[0]) - 1, int(r.split("/")[1]) - 1) for r in tokens]
            for i in range(len(refs) - 2):
                tri = (refs[i], refs[i + 1], refs[-1])
                corners_all += [positions[v] for v, _ in tri]
                if current == material:
                    found.append(([positions[v] for v, _ in tri], [uvs[t] for _, t in tri]))
    allp = np.array(corners_all, F32)
    return found, allp.min(0), allp.max(0)


class Ring:
    """The ring of the measured padding over the triangles of an OBJ material on a W x H tile."""

    def __init__(self, path: Path, material: str, width: int, height: int) -> None:
        self.width, self.height = width, height
        found, lo, hi = obj_mesh(path, material)
        self.tris: list[Triangle] = []
        vertices: dict[tuple[int, int, int], int] = {}
        corners: dict[tuple[int, int, int], int] = {}
        index: list[int] = []
        for p, uv in found:
            d = [(float(u), float(v)) for u, v in uv]
            area = (d[1][0] - d[0][0]) * (d[2][1] - d[0][1]) - (d[1][1] - d[0][1]) * (
                d[2][0] - d[0][0]
            )
            if area == 0.0:
                index.append(-1)
                continue
            k = Triangle(p, d, width, height)
            k.normalised = box_normalised(np.array(p, F32), lo, hi)
            for c in range(3):
                key = (bits(p[c][0]), bits(p[c][1]), bits(p[c][2]))
                k.vertex.append(vertices.setdefault(key, len(vertices)))
                ck = (k.vertex[c], bits(d[c][0]), bits(d[c][1]))
                k.corner.append(corners.setdefault(ck, len(corners)))
            index.append(len(self.tris))
            self.tris.append(k)
        n = len(self.tris)
        self.edges: dict[tuple[int, int], list[int]] = {}
        for i, k in enumerate(self.tris):
            for e in range(3):
                a, b = k.vertex[(e + 1) % 3], k.vertex[(e + 2) % 3]
                self.edges.setdefault((min(a, b), max(a, b)), []).append(i)
        chart, face = list(range(n)), list(range(n))

        def find(parent: list[int], i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for (va, vb), lst in sorted(self.edges.items()):
            for i in range(len(lst)):
                for j in range(i + 1, len(lst)):
                    ta, tb = self.tris[lst[i]], self.tris[lst[j]]
                    if ta.corner_at(va) == tb.corner_at(va) and ta.corner_at(vb) == tb.corner_at(
                        vb
                    ):
                        chart[find(chart, lst[i])] = find(chart, lst[j])
                    if self._coplanar(ta, tb):
                        face[find(face, lst[i])] = find(face, lst[j])
        faces: dict[int, int] = {}
        self.faces: list[list[int]] = []
        for i, k in enumerate(self.tris):
            k.chart = find(chart, i)
            root = find(face, i)
            if root not in faces:
                faces[root] = len(self.faces)
                self.faces.append([])
            k.face = faces[root]
            self.faces[k.face].append(i)
        # Each island's UV seam edges (own triangle, edge, far triangle).
        self.seams: dict[int, list[tuple[int, int, int]]] = {}
        for i, k in enumerate(self.tris):
            for e in range(3):
                a, b = k.vertex[(e + 1) % 3], k.vertex[(e + 2) % 3]
                for j in self.edges[(min(a, b), max(a, b))]:
                    o = self.tris[j]
                    if j == i or (
                        o.corner_at(a) == k.corner[(e + 1) % 3]
                        and o.corner_at(b) == k.corner[(e + 2) % 3]
                    ):
                        continue
                    self.seams.setdefault(k.chart, []).append((i, e, j))
        # The covering triangle of each texel centre: the first in mesh order.
        self.owner = np.full((height, width), -1, np.int64)
        for i, (_, uv) in enumerate(found):
            if index[i] < 0:
                continue
            for col, row in covered_texels(uv, width, height):
                if self.owner[row, col] < 0:
                    self.owner[row, col] = index[i]
        # Decision 281's face graph: per face, its neighbour faces in edge order, each with its
        # first shared edge (a triangle of the face, one of the neighbour, the edge's vertices).
        self.links: list[dict[int, tuple[int, int, int, int]]] = [{} for _ in self.faces]
        for (va, vb), lst in sorted(self.edges.items()):
            for i in lst:
                for j in lst:
                    fi, fj = self.tris[i].face, self.tris[j].face
                    if fi != fj and fj not in self.links[fi]:
                        self.links[fi][fj] = (i, j, va, vb)
        self.paths: dict[tuple[int, int], list[list[int]]] = {}
        self.hinges: dict[tuple[int, int], tuple[tuple[int, int, int, int], Hinge] | None] = {}
        # Per island, its seams' runs (seam_runs).
        self.runs: dict[int, dict[tuple[int, int, int], int]] = {}
        # Per ring texel (texels()): where decision 278's gate does not decide its taps.
        self.undecided: dict[tuple[int, int], set[str]] = {}

    @staticmethod
    def _coplanar(a: Triangle, b: Triangle) -> bool:
        na = cross(sub(a.p[1], a.p[0]), sub(a.p[2], a.p[0]))
        nb = cross(sub(b.p[1], b.p[0]), sub(b.p[2], b.p[0]))
        la, lb = norm(na), norm(nb)
        if la == 0.0 or lb == 0.0 or norm(cross(na, nb)) > COPLANAR * la * lb:
            return False
        return abs(dot(na, sub(b.p[0], a.p[0]))) / la <= COPLANAR * math.sqrt(la)

    def _hinge(self, dst: int, src: int) -> tuple[tuple[int, int, int, int], Hinge] | None:
        """The first edge of face `dst`'s triangles shared with face `src`, and its hinge."""
        if (dst, src) not in self.hinges:
            found: tuple[tuple[int, int, int, int], Hinge] | None = None
            for i in self.faces[dst]:
                for e in range(3):
                    if found is not None:
                        break
                    a, b = self.tris[i].vertex[(e + 1) % 3], self.tris[i].vertex[(e + 2) % 3]
                    for j in self.edges[(min(a, b), max(a, b))]:
                        if self.tris[j].face == src:
                            found = ((i, j, a, b), hinge(self.tris[i], self.tris[j], a, b))
                            break
                if found is not None:
                    break
            self.hinges[(dst, src)] = found
        return self.hinges[(dst, src)]

    def hinged(self, k: int, tau: int) -> bool:
        """Whether triangle `k`'s planar face is tau's or shares a 3D edge with it."""
        src, dst = self.tris[k].face, self.tris[tau].face
        return src == dst or self._hinge(dst, src) is not None

    def _paths(self, src: int, dst: int) -> list[list[int]]:
        """The fewest-hinge simple face paths from `src` to `dst` (at most MAX_HINGES), breadth
        first."""
        if (src, dst) not in self.paths:
            out: list[list[int]] = []
            queue = [[src]]
            while queue:
                path = queue.pop(0)
                if out and len(path) > len(out[0]):
                    break
                if path[-1] == dst:
                    out.append(path)
                    continue
                if len(path) > MAX_HINGES:
                    continue
                queue += [[*path, n] for n in self.links[path[-1]] if n not in path]
            self.paths[(src, dst)] = out
        return self.paths[(src, dst)]

    def folded(self, a: int, b: int) -> bool:
        """Decision 282's hinge gate: whether the float32 unit face normals of triangles `a` and
        `b` meet at a dot product of at most FOLD_GATE (decision 278's test). A shallower hinge is
        not unfolded."""
        return bool(_dot32(self.tris[a].normal, self.tris[b].normal) <= FOLD_GATE)

    def frame(self, p: Vec, k: int, tau: int, q: Vec, window: int | None = None) -> Vec:
        """`p` of triangle `k` in tau's frame for ring point `q`. A far tap (k in another chart
        than tau) is rotated rigidly from the plane of a far triangle J into tau's (decision 364,
        `plane_rotation`): J is the far triangle of the seam edge of tau's island, into k's island,
        whose 3D segment is nearest `q` (the first on a tie), else `window`, the far triangle of
        the window that puts the tap. Otherwise: as is in tau's planar face, rotated about an edge
        shared by the two faces, else hinge by hinge along the fewest-hinge face paths, the
        development nearest `q` (decision 281), else as is. A hinge is rotated about only when
        folded past the gate (decision 282: `folded`, of k and tau across a shared edge, of the
        path's two triangles at each hinge). A far tap with no J keeps its own chart rigid: a hinge
        whose two triangles are both in k's chart is not rotated about (decision 342)."""
        target = self.tris[tau]
        if self.tris[k].chart != target.chart:
            source = window
            nearest = math.inf
            for e, edge, j in self.seams.get(target.chart, []):
                if self.tris[j].chart != self.tris[k].chart:
                    continue
                E = self.tris[e]
                gap = segment_gap(E.p[(edge + 1) % 3], E.p[(edge + 2) % 3], q)
                if gap < nearest:
                    source, nearest = j, gap
            if source is not None:
                return plane_rotation(p, self.tris[source], target)
        src, dst = self.tris[k].face, target.face
        if src == dst:
            return p
        h = self._hinge(dst, src)
        if h is not None:
            return unfold(h[1], p) if self.folded(k, tau) else p
        chart = self.tris[k].chart
        far_tap = chart != self.tris[tau].chart
        best: Vec | None = None
        for path in self._paths(src, dst):
            r = p
            for a, b in itertools.pairwise(path):
                i, j, va, vb = self.links[b][a]
                if far_tap and self.tris[i].chart == chart == self.tris[j].chart:
                    continue
                if self.folded(i, j):
                    r = unfold(hinge(self.tris[i], self.tris[j], va, vb), r)
            if best is None or norm(sub(q, r)) < norm(sub(q, best)):
                best = r
        return p if best is None else best

    def fold32(self, p: Sequence[np.float32], e: int, edge: int, j: int) -> list[np.float32]:
        """`p`, decision 273's float32 position of a point of triangle `e`, rotated in float32
        about e's seam edge `edge` into the plane of its far triangle `j` (decision 282: `fold`
        over the box-normalised positions, each float32 operation rounded)."""
        own, other = self.tris[e], self.tris[j]
        va, vb = own.vertex[(edge + 1) % 3], own.vertex[(edge + 2) % 3]
        ia, ib = own.vertex.index(va), own.vertex.index(vb)
        ja, jb = other.vertex.index(va), other.vertex.index(vb)
        n0, n1 = own.normalised.astype(F32), other.normalised.astype(F32)
        a = list(n0[ia])
        axis = _unit32(_sub32(n0[ib], a))

        def across(to: Sequence[np.float32]) -> list[np.float32]:
            v = _sub32(to, a)
            return _unit32(_sub32(v, _scale32(axis, _dot32(v, axis))))

        in_own, in_other = across(n0[3 - ia - ib]), across(n1[3 - ja - jb])
        v = _sub32(p, a)
        s = _dot32(v, axis)
        r = _sub32(v, _scale32(axis, s))
        toward = _scale32(in_own, F32(-1))
        along, out = _dot32(r, toward), _dot32(r, _cross32(axis, toward))
        return _add32(
            _add32(a, _scale32(axis, s)),
            _add32(_scale32(in_other, along), _scale32(_cross32(axis, in_other), out)),
        )

    def _ordered(
        self,
        x: int,
        y: int,
        cands: list[tuple[float, bool, tuple[int, int]]],
        seam: dict[tuple[int, int], tuple[int, tuple[int, int], int, int]],
    ) -> tuple[list[tuple[float, bool, tuple[int, int]]], dict[tuple[int, int], set[str]]]:
        """`cands` in tap order (decisions 280, 282, 294): nearest first; within distances equal to
        EQUAL_SHARE relative, by the float32 distance (an own tap's decision 273 comparator, a far
        tap's |fold(q_E) - P|: `seam` maps a texel to E, its window's base, the seam edge and its
        far triangle J; q_E folded into J's plane when the edge is folded past the gate, P not
        rotated), then own before far, then OWN_ORDER or WINDOW_ORDER; then adjacent own taps
        within OWN_BAND relative by the comparator, then OWN_ORDER. And per texel of a tied group,
        the open tie classes of its group."""
        ordered = sorted(cands, key=lambda c: (c[0], c[2][1] * self.width + c[2][0]))
        result: list[tuple[float, bool, tuple[int, int]]] = []
        ties: dict[tuple[int, int], set[str]] = {}

        def own_rank(texel: tuple[int, int]) -> int:
            du = texel[0] - x
            du = du - self.width if du > 1 else du + self.width if du < -1 else du
            return OWN_ORDER.index((du, y - texel[1]))

        while ordered:
            group = [ordered[0]]
            for c in ordered[1:]:
                if c[0] > ordered[0][0] * (1.0 + EQUAL_SHARE):
                    break
                group.append(c)
            ordered = ordered[len(group) :]
            if len(group) > 1:
                keys: dict[tuple[int, int], tuple[bool, float, int]] = {}
                for c in group:
                    tx, ty = c[2]
                    k = self.tris[int(self.owner[ty, tx])]
                    if not c[1]:
                        d = compare_distance(
                            k.uv, k.normalised, self.width, self.height, (x, y), c[2]
                        )
                        keys[c[2]] = (False, float(d), own_rank(c[2]))
                    else:
                        e, (col0, row0), edge, j = seam[c[2]]
                        E = self.tris[e]
                        q_e = position32(E.uv, E.normalised, self.width, self.height, x, y)
                        if self.folded(e, j):
                            q_e = self.fold32(q_e, e, edge, j)
                        p = position32(k.uv, k.normalised, self.width, self.height, tx, ty)
                        keys[c[2]] = (
                            True,
                            float(distance32(q_e, p)),
                            WINDOW_ORDER.index((tx - col0, row0 - ty)),
                        )
                # Decision 294 (b): the float32 distance first, own before far only at equal ones.
                group.sort(key=lambda c: (keys[c[2]][1], keys[c[2]][0], keys[c[2]][2]))
                tie: set[str] = set()
                for i, a in enumerate(group):
                    for b in group[i + 1 :]:
                        ka, kb = keys[a[2]], keys[b[2]]
                        pair = (min(ka[2], kb[2]), max(ka[2], kb[2]))
                        if a[1] != b[1]:
                            if ka[1] == kb[1]:
                                tie.add("own-far-tie")
                        elif not a[1]:
                            if ka[1] == kb[1] and pair in OWN_OPEN:
                                tie.add("own-order")
                        else:
                            fa = self.tris[int(self.owner[a[2][1], a[2][0]])].face
                            fb = self.tris[int(self.owner[b[2][1], b[2][0]])].face
                            if fa != fb:
                                tie.add("far-fold")
                            if ka[1] == kb[1] and (
                                seam[a[2]][:2] != seam[b[2]][:2] or pair in WINDOW_OPEN
                            ):
                                tie.add("far-order")
                for c in group:
                    ties[c[2]] = tie
            result += group
        # Decision 294 (c): adjacent own taps within OWN_BAND relative, by the comparator, then
        # OWN_ORDER (an open pair tied on the comparator flagged).
        compared: dict[tuple[int, int], tuple[float, int]] = {}

        def own_key(texel: tuple[int, int]) -> tuple[float, int]:
            if texel not in compared:
                k = self.tris[int(self.owner[texel[1], texel[0]])]
                d = compare_distance(k.uv, k.normalised, self.width, self.height, (x, y), texel)
                compared[texel] = (float(d), own_rank(texel))
            return compared[texel]

        changed = True
        while changed:
            changed = False
            for i in range(len(result) - 1):
                a, b = result[i], result[i + 1]
                if a[1] or b[1] or b[0] > a[0] * (1.0 + OWN_BAND):
                    continue
                oa, ob = own_key(a[2]), own_key(b[2])
                if oa[0] == ob[0] and (min(oa[1], ob[1]), max(oa[1], ob[1])) in OWN_OPEN:
                    for t in (a[2], b[2]):
                        ties[t] = ties.get(t, set()) | {"own-order"}
                if ob < oa:
                    result[i], result[i + 1] = b, a
                    changed = True
        return result[:KEPT], ties

    def strip_winners(self, chart: int, x: int, y: int) -> set[tuple[int, int, int]]:
        """Last seam drawn at each sample of the ring texel's 3x3 neighbourhood (`strip_covers`)."""
        winners: set[tuple[int, int, int]] = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                winner = None
                for e, edge, j in self.seams.get(chart, []):
                    triangle = self.tris[e]
                    a, b = triangle.t[(edge + 1) % 3], triangle.t[(edge + 2) % 3]
                    if strip_covers(a, b, x + dx + 0.5, y + dy + 0.5):
                        winner = (e, edge, j)
                if winner is not None:
                    winners.add(winner)
        return winners

    def global_winners(self, x: int, y: int) -> set[tuple[int, int, int]]:
        """Last seam drawn, over the seams of every chart in mesh order (triangle, edge), at each
        sample of the ring texel's 3x3 neighbourhood: one strip map shared by all charts (decision
        356)."""
        grid = self.__dict__.get("_seam_grid")
        if grid is None:
            grid = {}
            order = sorted(s for lst in self.seams.values() for s in lst)
            for s in order:
                e, edge, _ = s
                a, b = self.tris[e].t[(edge + 1) % 3], self.tris[e].t[(edge + 2) % 3]
                rows = range(math.floor(min(a[1], b[1]) - 1), math.floor(max(a[1], b[1]) + 1) + 1)
                cols = range(math.floor(min(a[0], b[0]) - 1), math.floor(max(a[0], b[0]) + 1) + 1)
                for gy in rows:
                    for gx in cols:
                        grid.setdefault((gx, gy), []).append(s)
            self.__dict__["_seam_grid"] = grid
        winners: set[tuple[int, int, int]] = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                winner = None
                for e, edge, j in grid.get((x + dx, y + dy), []):
                    triangle = self.tris[e]
                    a, b = triangle.t[(edge + 1) % 3], triangle.t[(edge + 2) % 3]
                    if strip_covers(a, b, x + dx + 0.5, y + dy + 0.5):
                        winner = (e, edge, j)
                if winner is not None:
                    winners.add(winner)
        return winners

    def seam_runs(self, chart: int) -> dict[tuple[int, int, int], int]:
        """Each seam of `chart`'s run: seams joined end to end through a shared UV end, collinear
        (UV |sin| at most COLLINEAR) and with far triangles of one island, transitively."""
        if chart not in self.runs:
            seams = self.seams.get(chart, [])
            parent = list(range(len(seams)))

            def find(i: int) -> int:
                while parent[i] != i:
                    parent[i] = parent[parent[i]]
                    i = parent[i]
                return i

            at: dict[tuple[float, float], list[int]] = {}
            for i, (e, edge, _) in enumerate(seams):
                for end in (1, 2):
                    at.setdefault(self.tris[e].t[(edge + end) % 3], []).append(i)
            for lst in at.values():
                for i, k in itertools.combinations(lst, 2):
                    (e, f, j), (e2, f2, j2) = seams[i], seams[k]
                    if self.tris[j].chart != self.tris[j2].chart:
                        continue
                    a, b = self.tris[e].t[(f + 1) % 3], self.tris[e].t[(f + 2) % 3]
                    c, d = self.tris[e2].t[(f2 + 1) % 3], self.tris[e2].t[(f2 + 2) % 3]
                    ex, ey, fx, fy = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
                    lengths = math.sqrt(ex * ex + ey * ey) * math.sqrt(fx * fx + fy * fy)
                    if abs(ex * fy - ey * fx) <= COLLINEAR * lengths:
                        parent[find(i)] = find(k)
            self.runs[chart] = {s: find(i) for i, s in enumerate(seams)}
        return self.runs[chart]

    def candidates(
        self,
        x: int,
        y: int,
        own: list[tuple[int, int]],
        tau: int,
        flip: frozenset[tuple[int, int]] = frozenset(),
    ) -> tuple[list[tuple[float, bool, tuple[int, int]]], set[str]]:
        """Ring texel (x, y)'s candidates (distance, far, texel) in tap order, through `tau`, and
        where the rule (decisions 278, 279, 285, 291, 294) does not decide them. `flip` holds the
        (edge, axis) pairs whose far window is taken on the other side of a boundary (decision
        291); with any, only the candidates are computed."""
        T = self.tris[tau]
        q = T.point(T.bary(x + 0.5, y + 0.5))
        # texel -> [distance in tau's frame, distance as an own neighbour outside tau's island or
        # None, own neighbour?]; texel -> the seam edges whose window holds it.
        pool: dict[tuple[int, int], list[Any]] = {}
        via: dict[tuple[int, int], list[int]] = {}

        def put(tx: int, ty: int, window: int | None = None) -> list[Any]:
            if (tx, ty) not in pool:
                k = int(self.owner[ty, tx])
                K = self.tris[k]
                p = K.point(K.bary(tx + 0.5, ty + 0.5))
                outside = None
                if K.chart != T.chart:
                    outside = min(norm(sub(K.point(K.bary(x + 0.5, y + 0.5)), p)), norm(sub(q, p)))
                pool[(tx, ty)] = [norm(sub(q, self.frame(p, k, tau, q, window))), outside, False]
            return pool[(tx, ty)]

        # Decision 285: an own neighbour of tau's island in another triangle K sharing a UV edge
        # (two corners) with tau is measured through K, |q_K - P|; one sharing a corner only keeps
        # tau's frame (decision 279).
        through: set[tuple[int, int]] = set()
        for tx, ty in own:
            put(tx, ty)[2] = True
            k = int(self.owner[ty, tx])
            K = self.tris[k]
            if k != tau and K.chart == T.chart and len(set(K.corner) & set(T.corner)) >= 2:
                p = K.point(K.bary(tx + 0.5, ty + 0.5))
                pool[(tx, ty)][0] = norm(sub(K.point(K.bary(x + 0.5, y + 0.5)), p))
                through.add((tx, ty))
        # Decisions 279 and 285: the seam edges of every island owning an own neighbour, within
        # REACH_CAP texels (UV segment distance; those within REACH_HIGH kept for the reach flag);
        # none whose far triangle is tau (decision 288) or whose UV ends both lie on the tile's
        # left or right border (decision 290); decision 275: q folded into the far triangle, the
        # covered texels, of any island (decision 364), of columns floor(f_u - 1/2) +- 1, rows
        # ceil(f_v - 1/2) +- 1;
        # decision 278: the gate, with tau's normal (decision 292). Decision 291: the axes whose
        # f - 1/2 lies within WINDOW_SIDE of an integer.
        edges: list[tuple[tuple[bool, bool, bool], float]] = []
        # per edge: E, its window's base, the edge and its far triangle J
        windows: list[tuple[int, tuple[int, int], int, int]] = []
        sides: list[tuple[int, int]] = []
        charts = sorted({self.tris[int(self.owner[ty, tx])].chart for tx, ty in own})
        for chart in charts:
            # A strip writes its seam's run into the one map of every chart (decision 356); the
            # query discovers every seam of this chart's runs that owns a sample of the 3x3
            # neighbourhood.
            runs = self.seam_runs(chart)
            owned = {runs[w] for w in self.global_winners(x, y) if w in runs}
            for e_index, edge, j in self.seams.get(chart, []):
                E, J = self.tris[e_index], self.tris[j]
                ua, ub = E.t[(edge + 1) % 3][0], E.t[(edge + 2) % 3][0]
                if j == tau or (ua == ub and ua in (0.0, float(self.width))):
                    continue
                reach = segment_distance(E.t[(edge + 1) % 3], E.t[(edge + 2) % 3], x + 0.5, y + 0.5)
                if reach >= REACH_HIGH or runs[(e_index, edge, j)] not in owned:
                    continue
                va, vb = E.vertex[(edge + 1) % 3], E.vertex[(edge + 2) % 3]
                edges.append((seam_gate(T.normal, J.normal, q, E.p[(edge + 1) % 3]), reach))
                fu, fv = J.texel_of(fold(hinge(E, J, va, vb), q))
                col0, row0 = math.floor(fu - 0.5), math.ceil(fv - 0.5)
                for axis, m in ((0, fu - 0.5), (1, fv - 0.5)):
                    if abs(m - round(m)) < WINDOW_SIDE:
                        sides.append((len(edges) - 1, axis))
                        if (len(edges) - 1, axis) in flip:
                            # The other side: columns round(m) - 1 | round(m), rows round(m) |
                            # round(m) + 1.
                            if axis == 0:
                                col0 = 2 * round(m) - 1 - col0
                            else:
                                row0 = 2 * round(m) + 1 - row0
                windows.append((e_index, (col0, row0), edge, j))
                for row in range(row0 - 1, row0 + 2):
                    for col in range(col0 - 1, col0 + 2):
                        if not (0 <= row < self.height and 0 <= col < self.width):
                            continue
                        if self.owner[row, col] < 0:
                            continue
                        put(col, row, j)
                        lst = via.setdefault((col, row), [])
                        if not lst or lst[-1] != len(edges) - 1:
                            lst.append(len(edges) - 1)
        # Decision 294 (a): per edge, when E lies outside tau's planar face and the edge's nearest
        # point to the texel centre is an end V (its projection outside [0, 1]): whether another
        # edge of `edges` ending at V is gated, and the least UV |sin| with another seam edge of
        # E's island ending at V (infinite when none); else None.
        px, py = x + 0.5, y + 0.5
        ends = [
            (self.tris[w[0]].t[(w[2] + 1) % 3], self.tris[w[0]].t[(w[2] + 2) % 3]) for w in windows
        ]
        corners: list[tuple[bool, float] | None] = []
        for i, (e_index, _, edge, _) in enumerate(windows):
            E = self.tris[e_index]
            a, b = ends[i]
            ex, ey = b[0] - a[0], b[1] - a[1]
            along = ((px - a[0]) * ex + (py - a[1]) * ey) / (ex * ex + ey * ey)
            if E.face == T.face or 0.0 <= along <= 1.0:
                corners.append(None)
                continue
            v = a if along < 0.0 else b
            sine = math.inf
            for f_index, f_edge, _ in self.seams[E.chart]:
                F = self.tris[f_index]
                fa, fb = F.t[(f_edge + 1) % 3], F.t[(f_edge + 2) % 3]
                if (f_index, f_edge) == (e_index, edge) or v not in (fa, fb):
                    continue
                fx, fy = fb[0] - fa[0], fb[1] - fa[1]
                length = math.sqrt(ex * ex + ey * ey) * math.sqrt(fx * fx + fy * fy)
                sine = min(sine, abs(ex * fy - ey * fx) / length)
            gated = any(edges[k][0][0] for k in range(len(edges)) if k != i and v in ends[k])
            corners.append((gated, sine))

        def within(e: int, reaches: Sequence[float]) -> bool:
            """Whether edge `e` reaches the texel under `reaches` (as REACHES)."""
            cap, gated_cap, open_cap, collinear = reaches
            corner = corners[e]
            if corner is not None and corner[1] > collinear:
                return edges[e][1] <= (gated_cap if corner[0] else open_cap)
            return edges[e][1] <= cap

        def build(
            is_open: Callable[[tuple[tuple[bool, bool, bool], float]], bool],
            reaches: Sequence[float] = REACHES,
        ) -> list[tuple[float, bool, tuple[int, int]]]:
            """The candidates when the edges that reach the texel under `reaches` and are
            `is_open` feed the far windows; a far tap's E and window are the first reaching edge's
            that holds it."""
            out = []
            first: dict[tuple[int, int], tuple[int, tuple[int, int], int, int]] = {}
            for texel, (frame, outside, is_own) in pool.items():
                inside = is_own and outside is None
                held = [e for e in via.get(texel, []) if within(e, reaches)]
                if held:
                    first[texel] = windows[held[0]]
                if not inside and any(is_open(edges[e]) for e in held):
                    out.append((frame, True, texel))
                elif is_own:
                    out.append((frame if inside else outside, False, texel))
            ordered, ties[0] = self._ordered(x, y, out, first)
            return ordered

        ties: list[dict[tuple[int, int], set[str]]] = [{}]
        result = build(lambda e: not e[0][0])
        undecided: set[str] = set()
        if flip:
            return result, undecided
        n = tap_count(result)
        # Decision 291: a far window taken on the other side of a boundary, on any of the near
        # axes, that changes the taps; more than WINDOW_SIDES such axes are not tried.
        if len(sides) > WINDOW_SIDES:
            undecided.add("window-side")
        elif sides:
            for chosen in itertools.product((False, True), repeat=len(sides)):
                if not any(chosen):
                    continue
                flipped = frozenset(s for s, f in zip(sides, chosen, strict=True) if f)
                other, _ = self.candidates(x, y, own, tau, flipped)
                if tap_count(other) != n or other[:n] != result[:n]:
                    undecided.add("window-side")
                    break
        for c in result[:n]:
            undecided |= ties[0].get(c[2], set())
            tx, ty = c[2]
            framed = c[1] or self.tris[int(self.owner[ty, tx])].chart == T.chart
            if framed and c[2] not in through and not self.hinged(int(self.owner[ty, tx]), tau):
                undecided.add("multi-facet")
        if edges:
            # Decision 285: a cap anywhere in [REACH_LOW, REACH_HIGH) that changes the taps;
            # decision 294: a corner cap anywhere in its bracket, or a collinear threshold anywhere
            # in [COLLINEAR_LOW, COLLINEAR_HIGH). Each is tried at its bracket's low end and at
            # each edge's value inside it (the settings that differ).
            sines = [c[1] for c in corners if c is not None]
            reaches = [e[1] for e in edges]
            for slot, low, high, values, flag in (
                (0, REACH_LOW, REACH_HIGH, reaches, "reach-bracket"),
                (1, CORNER_GATED_LOW, CORNER_GATED_HIGH, reaches, "corner-reach-bracket"),
                (2, CORNER_OPEN_LOW, CORNER_OPEN_HIGH, reaches, "corner-reach-bracket"),
                (3, COLLINEAR_LOW, COLLINEAR_HIGH, sines, "corner-reach-bracket"),
            ):
                for value in [low] + [v for v in values if low < v < high]:
                    tried = (*REACHES[:slot], value, *REACHES[slot + 1 :])
                    if all(within(e, tried) == within(e, REACHES) for e in range(len(edges))):
                        continue
                    other = build(lambda e: not e[0][0], tried)
                    if tap_count(other) != n or other[:n] != result[:n]:
                        undecided.add(flag)
                        break
            ungated = build(lambda e: True)
            reaching = {
                e
                for lst in (result, ungated)
                for c in lst[: tap_count(lst)]
                if c[1]
                for e in via[c[2]]
                if within(e, REACHES)
            }
            if any(edges[e][0][1] for e in reaching):
                undecided.add("fold-bracket")
            if any(edges[e][0][2] for e in reaching):
                undecided.add("on-far-plane")
            if len({edges[e][0][0] for e in reaching}) > 1:
                undecided.add("mixed-gates")
        return result, undecided

    def tau(self, x: int, y: int, own: list[tuple[int, int]]) -> int:
        """Decision 279: the triangle of the own neighbour nearest under decision 273's comparator
        (through its own triangle), an exact tie toward +u, then +v."""
        triangles = {int(self.owner[ty, tx]) for tx, ty in own}
        if len(triangles) == 1:
            return triangles.pop()

        def key(t: tuple[int, int]) -> tuple[float, int, int]:
            k = self.tris[int(self.owner[t[1], t[0]])]
            d = compare_distance(
                k.uv, k.normalised, self.width, self.height, (x, y), t, fused_determinant=False
            )
            return (float(d), -t[0], t[1])

        nearest = min(own, key=key)
        return int(self.owner[nearest[1], nearest[0]])

    def chain_fractions(
        self, x: int, y: int, chosen: Sequence[tuple[float, bool, tuple[int, int]]]
    ) -> list[np.float32]:
        """Single-triangle own chains quantise distances from box-normalised float32 positions.

        Selection and ordering keep their geometric distances. Mixed-triangle and far chains
        retain the existing distance rule; their frame arithmetic is not inferred here.
        Float32 collapse or non-finite distances also leave the geometric rule unchanged.
        """
        distances = [c[0] for c in chosen]
        if len(chosen) > 1 and all(not c[1] for c in chosen):
            triangles = {int(self.owner[ty, tx]) for _, _, (tx, ty) in chosen}
            if len(triangles) == 1:
                own = [
                    ((x + dx) % self.width, y + dy)
                    for dy, dx in NEIGHBOURS
                    if 0 <= y + dy < self.height and self.owner[y + dy, (x + dx) % self.width] >= 0
                ]
                tau = self.tau(x, y, own)
                if triangles == {tau}:
                    T = self.tris[tau]
                    measured = [
                        float(
                            compare_distance(
                                T.uv, T.normalised, self.width, self.height, (x, y), c[2]
                            )
                        )
                        for c in chosen
                    ]
                    if all(math.isfinite(d) and d > 0.0 for d in measured):
                        distances = measured
        return fractions(distances)

    def texels(self) -> list[tuple[int, int, list[tuple[float, bool, tuple[int, int]]], int]]:
        """Every ring texel: (x, y, candidates in tap order, the chain's number of taps)."""
        covered = self.owner >= 0
        out = []
        for y in range(self.height):
            for x in range(self.width):
                if covered[y, x]:
                    continue
                own = [
                    ((x + dx) % self.width, y + dy)
                    for dy, dx in NEIGHBOURS
                    if 0 <= y + dy < self.height and covered[y + dy, (x + dx) % self.width]
                ]
                if not own:
                    continue
                cands, self.undecided[(x, y)] = self.candidates(x, y, own, self.tau(x, y, own))
                out.append((x, y, cands, tap_count(cands)))
        return out


def padding(values: np.ndarray, path: Path, material: str, rounded: bool = True) -> np.ndarray:
    """`values` (rows top first, float32, H x W x C) padded over the coverage of `material`'s
    triangles in the OBJ at `path`: covered texels kept, the ring's chains (`chain` with
    `rounded`), then every other texel a copy of its seed of the jump flood over the covered and
    ring texels (decision 197), its reads outside the image clamped to the nearest edge texel
    (decision 285)."""
    height, width, channels = values.shape
    ring = Ring(path, material, width, height)
    covered = ring.owner >= 0
    out = values.astype(F32).copy()
    seed = covered.copy()
    for x, y, cands, taps in ring.texels():
        chosen = cands[:taps]
        t = ring.chain_fractions(x, y, chosen)
        for c in range(channels):
            out[y, x, c] = chain([F32(values[ty, tx, c]) for _, _, (tx, ty) in chosen], t, rounded)
        seed[y, x] = True
    return flood(out, seed)


def island_normal(values: np.ndarray, covered: np.ndarray) -> np.ndarray:
    """Decision 287's padding of the mesh-free normal `values` (H x W x 3, float32) over `covered`:
    each ring texel (an uncovered texel with a covered 8-neighbour, x wrapping) copies its nearest
    covered 8-neighbour without wrap-around, ties in the flood's offset order, or keeps its value
    when its covered neighbours all lie across the x border; then the flood over the covered and
    ring texels."""
    height, width, _ = values.shape
    out = values.astype(F32).copy()
    seed = covered.copy()
    for y in range(height):
        for x in range(width):
            if covered[y, x]:
                continue
            ring = [
                (dy, dx)
                for dy, dx in NEIGHBOURS
                if 0 <= y + dy < height and covered[y + dy, (x + dx) % width]
            ]
            if not ring:
                continue
            seed[y, x] = True
            for dy, dx in FLOOD:  # sides first, then diagonals
                if 0 <= x + dx < width and (dy, dx) in ring:
                    out[y, x] = values[y + dy, x + dx]
                    break
    return flood(out, seed)


def flood(out: np.ndarray, seed: np.ndarray) -> np.ndarray:
    """Decision 197's jump flood: every texel of `out` (H x W x C) that is not a `seed` copies its
    seed's values, reads outside the image clamped to the nearest edge texel (decision 285)."""
    height, width = seed.shape
    ys, xs = np.mgrid[0:height, 0:width]
    sy, sx = np.where(seed, ys, -1), np.where(seed, xs, -1)
    big = np.iinfo(np.int64).max
    k = max(width, height) // 2
    while k >= 1:
        by, bx = sy.copy(), sx.copy()
        best = np.where(by >= 0, (by - ys) ** 2 + (bx - xs) ** 2, big)
        for dy, dx in FLOOD:
            rows = np.clip(np.arange(height) + dy * k, 0, height - 1)
            cols = np.clip(np.arange(width) + dx * k, 0, width - 1)
            cy, cx = sy[rows][:, cols], sx[rows][:, cols]
            d = np.where(cy >= 0, (cy - ys) ** 2 + (cx - xs) ** 2, big)
            better = d < best
            by, bx = np.where(better, cy, by), np.where(better, cx, bx)
            best = np.where(better, d, best)
        sy, sx = by, bx
        k //= 2
    gutter = ~seed & (sy >= 0)
    out[gutter] = out[sy[gutter], sx[gutter]]
    return out
