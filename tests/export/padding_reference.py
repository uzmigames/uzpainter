"""The measured `infinite` padding of src/export/padding.h (phase1.25 item 2.7; decisions 197, 206,
267, 268, 270, 273, 275, 278, 279, 280, 281; measured only, decision 259), written again
independently in Python for the tests: the ring over an OBJ's triangles, then the jump flood.

The geometry (barycentrics, folds about seam edges, distances) is double precision with each
operation in padding.cpp's order, so that a far point at an exact half-texel boundary, where
decision 275's window is not identified (its open item (b)), falls on the same side as in
UzPainter. The comparator of equal shares (decision 273), the chain fractions (decision 268) and
the lerp chain are float32, each operation correctly rounded, through the recording GPU's
reciprocal and square root (tools/parity/fit/hwmath). So are decision 278's seam gate's face
normals and their dot product, and decision 280's far-tap distance and its fold. The coverage
snaps each vertex to 1/256 texel (decision 281). No Painter data is read.
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
EQUAL_SHARE = 1e-9
ZERO_DISTANCE = 1e-6
COPLANAR = 1e-6
KEPT = 8
# Decision 278's seam gate: the faces' float32 normal dot product at most FOLD_GATE; Painter's
# constant lies in (FOLD_LOW, FOLD_HIGH].
FOLD_GATE = F32(0.985)
FOLD_LOW = F32(0.98498905)
FOLD_HIGH = F32(0.98501915)
# Decision 279's seam reach: UV segment distance at most REACH_CAP texels; Painter's cap lies in
# (REACH_LOW, REACH_CAP].
REACH_CAP = 1.8
REACH_LOW = 1.7
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


def chain(values: Sequence[np.float32], t: Sequence[np.float32]) -> np.float32:
    """Decision 268's FMA lerp chain over `values` in tap order, then decision 206's 1 - (1 - m)."""
    n = len(values)
    m = values[0]
    if n > 1:
        last = f32(f32(1) - t[n - 2])
        m = fma(last, f32(values[n - 1] - values[n - 2]), values[n - 2])
        for level in range(n - 3, -1, -1):
            m = fma(t[level], f32(values[level] - m), m)
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
    """Decision 278's gate of a seam edge for ring point `q` (p a vertex of the edge): (gated, in
    the bracket, on the far plane)."""
    d = f32(f32(f32(n_own[0] * n_far[0]) + f32(n_own[1] * n_far[1])) + f32(n_own[2] * n_far[2]))
    side = dot((float(n_far[0]), float(n_far[1]), float(n_far[2])), sub(q, p))
    return (
        bool(d <= FOLD_GATE and side < 0.0),
        bool(FOLD_LOW < d <= FOLD_HIGH and side < 0.0),
        bool(side == 0.0 and d <= FOLD_HIGH),
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
    uv: np.ndarray, normalised: np.ndarray, width: int, height: int, x: int, y: int
) -> list[np.float32]:
    """Decision 273's float32 position of texel (x, y)'s centre through the triangle of float32 UVs
    `uv` (v up) and box-normalised corners `normalised`: the texel-centre UV, barycentrics from the
    UV inverse matrix based at the third corner with the GPU reciprocal, fma(l2, P2, fma(l0, P0,
    l1 P1))."""
    u = [(f32(a), f32(b)) for a, b in uv]
    e0u, e0v = f32(u[0][0] - u[2][0]), f32(u[0][1] - u[2][1])
    e1u, e1v = f32(u[1][0] - u[2][0]), f32(u[1][1] - u[2][1])
    det = f32(f32(e0u * e1v) - f32(e0v * e1u))
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
) -> np.float32:
    """Decision 273's comparator distance from ring texel `ring` to `tap` = (x, y), both through the
    triangle of float32 UVs `uv` (v up) and box-normalised corners `normalised`."""
    return distance32(
        position32(uv, normalised, width, height, *ring),
        position32(uv, normalised, width, height, *tap),
    )


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
    return int(np.array([x], F32).view(np.uint32)[0])


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

    def frame(self, p: Vec, k: int, tau: int, q: Vec) -> Vec:
        """`p` of triangle `k` in tau's frame for ring point `q`: as is in tau's planar face,
        rotated about an edge shared by the two faces, else hinge by hinge along the fewest-hinge
        face paths, the development nearest `q` (decision 281), else as is."""
        src, dst = self.tris[k].face, self.tris[tau].face
        if src == dst:
            return p
        h = self._hinge(dst, src)
        if h is not None:
            return unfold(h[1], p)
        best: Vec | None = None
        for path in self._paths(src, dst):
            r = p
            for a, b in itertools.pairwise(path):
                i, j, va, vb = self.links[b][a]
                r = unfold(hinge(self.tris[i], self.tris[j], va, vb), r)
            if best is None or norm(sub(q, r)) < norm(sub(q, best)):
                best = r
        return p if best is None else best

    def unfold32(self, p: Sequence[np.float32], k: int, e: int) -> list[np.float32]:
        """`p`, decision 273's float32 position of a point of triangle `k`, rotated in float32 into
        triangle `e`'s face about an edge the faces share (decision 280); else as is."""
        src, dst = self.tris[k].face, self.tris[e].face
        h = None if src == dst else self._hinge(dst, src)
        if h is None:
            return list(p)
        i, j, va, vb = h[0]
        own, other = self.tris[i], self.tris[j]
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
        along, out = _dot32(r, in_other), _dot32(r, _cross32(axis, in_other))
        return _add32(
            _add32(a, _scale32(axis, s)),
            _add32(_scale32(toward, along), _scale32(_cross32(axis, toward), out)),
        )

    def _ordered(
        self,
        x: int,
        y: int,
        cands: list[tuple[float, bool, tuple[int, int]]],
        seam: dict[tuple[int, int], tuple[int, tuple[int, int]]],
    ) -> tuple[list[tuple[float, bool, tuple[int, int]]], dict[tuple[int, int], set[str]]]:
        """`cands` in tap order (decision 280): nearest first; within equal distances own taps by
        decision 273's comparator, then OWN_ORDER; far taps (`seam`: texel -> E and its window's
        base) by the float32 |q_E - P|, then WINDOW_ORDER. And per texel of a tied group, the open
        tie classes of its group."""
        ordered = sorted(cands, key=lambda c: (c[0], c[2][1] * self.width + c[2][0]))
        result: list[tuple[float, bool, tuple[int, int]]] = []
        ties: dict[tuple[int, int], set[str]] = {}
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
                        du = tx - x
                        du = du - self.width if du > 1 else du + self.width if du < -1 else du
                        d = compare_distance(
                            k.uv, k.normalised, self.width, self.height, (x, y), c[2]
                        )
                        keys[c[2]] = (False, float(d), OWN_ORDER.index((du, y - ty)))
                    else:
                        e, (col0, row0) = seam[c[2]]
                        E = self.tris[e]
                        q_e = position32(E.uv, E.normalised, self.width, self.height, x, y)
                        p = self.unfold32(
                            position32(k.uv, k.normalised, self.width, self.height, tx, ty),
                            int(self.owner[ty, tx]),
                            e,
                        )
                        keys[c[2]] = (
                            True,
                            float(distance32(q_e, p)),
                            WINDOW_ORDER.index((tx - col0, row0 - ty)),
                        )
                group.sort(key=lambda c: keys[c[2]])
                tie: set[str] = set()
                for i, a in enumerate(group):
                    for b in group[i + 1 :]:
                        ka, kb = keys[a[2]], keys[b[2]]
                        pair = (min(ka[2], kb[2]), max(ka[2], kb[2]))
                        if a[1] != b[1]:
                            tie.add("own-far-tie")
                        elif not a[1]:
                            if ka[1] == kb[1] and pair in OWN_OPEN:
                                tie.add("own-order")
                        else:
                            fa = self.tris[int(self.owner[a[2][1], a[2][0]])].face
                            fb = self.tris[int(self.owner[b[2][1], b[2][0]])].face
                            if fa != fb:
                                tie.add("far-fold")
                            if ka[1] == kb[1] and (seam[a[2]] != seam[b[2]] or pair in WINDOW_OPEN):
                                tie.add("far-order")
                for c in group:
                    ties[c[2]] = tie
            result += group
        return result[:KEPT], ties

    def candidates(
        self, x: int, y: int, own: list[tuple[int, int]], tau: int
    ) -> tuple[list[tuple[float, bool, tuple[int, int]]], set[str]]:
        """Ring texel (x, y)'s candidates (distance, far, texel) in tap order, through `tau`, and
        where the rule (decisions 278, 279) does not decide them."""
        T = self.tris[tau]
        q = T.point(T.bary(x + 0.5, y + 0.5))
        # texel -> [distance in tau's frame, distance as an own neighbour outside tau's island or
        # None, own neighbour?]; texel -> the seam edges whose window holds it.
        pool: dict[tuple[int, int], list[Any]] = {}
        via: dict[tuple[int, int], list[int]] = {}

        def put(tx: int, ty: int) -> list[Any]:
            if (tx, ty) not in pool:
                k = int(self.owner[ty, tx])
                K = self.tris[k]
                p = K.point(K.bary(tx + 0.5, ty + 0.5))
                outside = None
                if K.chart != T.chart:
                    outside = min(norm(sub(K.point(K.bary(x + 0.5, y + 0.5)), p)), norm(sub(q, p)))
                pool[(tx, ty)] = [norm(sub(q, self.frame(p, k, tau, q))), outside, False]
            return pool[(tx, ty)]

        for tx, ty in own:
            put(tx, ty)[2] = True
        # Decision 279: the seam edges of every island owning an own neighbour, within REACH_CAP
        # texels (UV segment distance); decision 275: q folded into the far triangle, the far
        # island's covered texels of columns floor(f_u - 1/2) +- 1, rows ceil(f_v - 1/2) +- 1;
        # decision 278: the gate.
        edges: list[tuple[tuple[bool, bool, bool], float]] = []
        windows: list[tuple[int, tuple[int, int]]] = []  # per edge: E and its window's base
        charts = sorted({self.tris[int(self.owner[ty, tx])].chart for tx, ty in own})
        for chart in charts:
            for e_index, edge, j in self.seams.get(chart, []):
                E, J = self.tris[e_index], self.tris[j]
                reach = segment_distance(E.t[(edge + 1) % 3], E.t[(edge + 2) % 3], x + 0.5, y + 0.5)
                if reach > REACH_CAP:
                    continue
                va, vb = E.vertex[(edge + 1) % 3], E.vertex[(edge + 2) % 3]
                edges.append((seam_gate(E.normal, J.normal, q, E.p[(edge + 1) % 3]), reach))
                fu, fv = J.texel_of(fold(hinge(E, J, va, vb), q))
                col0, row0 = math.floor(fu - 0.5), math.ceil(fv - 0.5)
                windows.append((e_index, (col0, row0)))
                for row in range(row0 - 1, row0 + 2):
                    for col in range(col0 - 1, col0 + 2):
                        if not (0 <= row < self.height and 0 <= col < self.width):
                            continue
                        k = int(self.owner[row, col])
                        if k < 0 or self.tris[k].chart != J.chart:
                            continue
                        put(col, row)
                        lst = via.setdefault((col, row), [])
                        if not lst or lst[-1] != len(edges) - 1:
                            lst.append(len(edges) - 1)

        def build(
            is_open: Callable[[tuple[tuple[bool, bool, bool], float]], bool],
        ) -> list[tuple[float, bool, tuple[int, int]]]:
            out = []
            for texel, (frame, outside, is_own) in pool.items():
                inside = is_own and outside is None
                if not inside and any(is_open(edges[e]) for e in via.get(texel, [])):
                    out.append((frame, True, texel))
                elif is_own:
                    out.append((frame if inside else outside, False, texel))
            ordered, ties[0] = self._ordered(x, y, out, {t: windows[v[0]] for t, v in via.items()})
            return ordered

        ties: list[dict[tuple[int, int], set[str]]] = [{}]
        result = build(lambda e: not e[0][0])
        undecided: set[str] = set()
        n = tap_count(result)
        for c in result[:n]:
            undecided |= ties[0].get(c[2], set())
            tx, ty = c[2]
            framed = c[1] or self.tris[int(self.owner[ty, tx])].chart == T.chart
            if framed and not self.hinged(int(self.owner[ty, tx]), tau):
                undecided.add("multi-facet")
        if edges:
            inner = build(lambda e: not e[0][0] and e[1] <= REACH_LOW)
            if tap_count(inner) != n or inner[:n] != result[:n]:
                undecided.add("reach-bracket")
            ungated = build(lambda e: True)
            reaching = {
                e
                for lst in (result, ungated)
                for c in lst[: tap_count(lst)]
                if c[1]
                for e in via[c[2]]
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
            d = compare_distance(k.uv, k.normalised, self.width, self.height, (x, y), t)
            return (float(d), -t[0], t[1])

        nearest = min(own, key=key)
        return int(self.owner[nearest[1], nearest[0]])

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


def padding(values: np.ndarray, path: Path, material: str) -> np.ndarray:
    """`values` (rows top first, float32, H x W x C) padded over the coverage of `material`'s
    triangles in the OBJ at `path`: covered texels kept, the ring's chains, then every other texel
    a copy of its seed of the jump flood over the covered and ring texels (decision 197)."""
    height, width, channels = values.shape
    ring = Ring(path, material, width, height)
    covered = ring.owner >= 0
    out = values.astype(F32).copy()
    seed = covered.copy()
    for x, y, cands, taps in ring.texels():
        chosen = cands[:taps]
        t = fractions([c[0] for c in chosen])
        for c in range(channels):
            out[y, x, c] = chain([F32(values[ty, tx, c]) for _, _, (tx, ty) in chosen], t)
        seed[y, x] = True
    ys, xs = np.mgrid[0:height, 0:width]
    sy, sx = np.where(seed, ys, -1), np.where(seed, xs, -1)
    big = np.iinfo(np.int64).max
    k = max(width, height) // 2
    while k >= 1:
        by, bx = sy.copy(), sx.copy()
        best = np.where(by >= 0, (by - ys) ** 2 + (bx - xs) ** 2, big)
        for dy, dx in FLOOD:
            cy, cx = np.full_like(sy, -1), np.full_like(sx, -1)
            y0, y1 = max(0, -dy * k), min(height, height - dy * k)
            x0, x1 = max(0, -dx * k), min(width, width - dx * k)
            cy[y0:y1, x0:x1] = sy[y0 + dy * k : y1 + dy * k, x0 + dx * k : x1 + dx * k]
            cx[y0:y1, x0:x1] = sx[y0 + dy * k : y1 + dy * k, x0 + dx * k : x1 + dx * k]
            d = np.where(cy >= 0, (cy - ys) ** 2 + (cx - xs) ** 2, big)
            better = d < best
            by, bx = np.where(better, cy, by), np.where(better, cx, bx)
            best = np.where(better, d, best)
        sy, sx = by, bx
        k //= 2
    gutter = ~seed & (sy >= 0)
    out[gutter] = out[sy[gutter], sx[gutter]]
    return out
