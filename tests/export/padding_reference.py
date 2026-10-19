"""The measured `infinite` padding of src/export/padding.h (phase1.25 item 2.7; decisions 197, 206,
267, 268, 270, 273, 275; measured only, decision 259), written again independently in Python
for the tests: the ring over an OBJ's triangles, then the jump flood.

The geometry (barycentrics, folds about seam edges, distances) is double precision with each
operation in padding.cpp's order, so that a far point at an exact half-texel boundary, where
decision 275's window is not identified (its open item (b)), falls on the same side as in
UzPainter. The comparator of equal shares (decision 273), the chain fractions (decision 268) and
the lerp chain are float32, each operation correctly rounded, through the recording GPU's
reciprocal and square root (tools/parity/fit/hwmath). No Painter data is read.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
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


def box_normalised(positions: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Decision 273's mesh-box normalisation of float32 `positions`: ext = hi - lo,
    c = lo + ext / 2, r = 1 / (max(ext) / 2), P r - c r, each float32 operation rounded."""
    lo, hi = lo.astype(F32), hi.astype(F32)
    ext = (hi - lo).astype(F32)
    c = (lo + (ext * F32(0.5)).astype(F32)).astype(F32)
    r = F32(F32(1) / F32(ext.max() * F32(0.5)))
    result: np.ndarray = ((positions.astype(F32) * r).astype(F32) - (c * r).astype(F32)).astype(F32)
    return result


def compare_distance(
    uv: np.ndarray,
    normalised: np.ndarray,
    width: int,
    height: int,
    ring: tuple[int, int],
    tap: tuple[int, int],
) -> np.float32:
    """Decision 273's comparator distance from ring texel `ring` to `tap` = (x, y), both through the
    triangle of float32 UVs `uv` (v up) and box-normalised corners `normalised`: texel-centre UVs,
    barycentrics from the UV inverse matrix based at the third corner with the GPU reciprocal,
    fma(l2, P2, fma(l0, P0, l1 P1)), the FMA squared distance and the GPU square root."""
    u = [(f32(a), f32(b)) for a, b in uv]
    e0u, e0v = f32(u[0][0] - u[2][0]), f32(u[0][1] - u[2][1])
    e1u, e1v = f32(u[1][0] - u[2][0]), f32(u[1][1] - u[2][1])
    det = f32(f32(e0u * e1v) - f32(e0v * e1u))
    r = F32(hwmath.rcp(np.array([det], F32))[0])
    m00, m01, m10, m11 = f32(e1v * r), f32(-e1u * r), f32(-e0v * r), f32(e0u * r)
    n = normalised.astype(F32)

    def position(x: int, y: int) -> list[np.float32]:
        pu = f32(f32(x + 0.5) / f32(width))
        pv = f32(f32(1) - f32(f32(y + 0.5) / f32(height)))
        dx, dy = f32(pu - u[2][0]), f32(pv - u[2][1])
        l0 = fma(m00, dx, f32(m01 * dy))
        l1 = fma(m10, dx, f32(m11 * dy))
        l2 = f32(f32(1) - f32(l0 + l1))
        return [fma(l2, n[2][c], fma(l0, n[0][c], f32(l1 * n[1][c]))) for c in range(3)]

    q, p = position(*ring), position(*tap)
    d = [f32(q[c] - p[c]) for c in range(3)]
    squared = fma(d[2], d[2], fma(d[1], d[1], f32(d[0] * d[0])))
    return F32(hwmath.sqrt(np.array([squared], F32))[0])


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
            c2 = [(float(u), float(v)) for u, v in uv]

            def edge(a: tuple[float, float], b: tuple[float, float], u: float, v: float) -> float:
                return (b[0] - a[0]) * (v - a[1]) - (b[1] - a[1]) * (u - a[0])

            area = edge(c2[0], c2[1], c2[2][0], c2[2][1])
            us, vs = [c[0] for c in c2], [c[1] for c in c2]
            col_lo = max(0.0, math.floor(min(us) * width - 0.5))
            col_hi = min(width - 1.0, math.ceil(max(us) * width - 0.5))
            row_lo = max(0.0, math.floor((1.0 - max(vs)) * height - 0.5))
            row_hi = min(height - 1.0, math.ceil((1.0 - min(vs)) * height - 0.5))
            for row in range(int(row_lo), int(row_hi) + 1):
                for col in range(int(col_lo), int(col_hi) + 1):
                    u, v = (col + 0.5) / width, 1.0 - (row + 0.5) / height
                    w = (
                        edge(c2[0], c2[1], u, v),
                        edge(c2[1], c2[2], u, v),
                        edge(c2[2], c2[0], u, v),
                    )
                    inside = all(x >= 0.0 for x in w) if area > 0.0 else all(x <= 0.0 for x in w)
                    if inside and self.owner[row, col] < 0:
                        self.owner[row, col] = index[i]
        self.hinges: dict[tuple[int, int], Hinge | None] = {}

    @staticmethod
    def _coplanar(a: Triangle, b: Triangle) -> bool:
        na = cross(sub(a.p[1], a.p[0]), sub(a.p[2], a.p[0]))
        nb = cross(sub(b.p[1], b.p[0]), sub(b.p[2], b.p[0]))
        la, lb = norm(na), norm(nb)
        if la == 0.0 or lb == 0.0 or norm(cross(na, nb)) > COPLANAR * la * lb:
            return False
        return abs(dot(na, sub(b.p[0], a.p[0]))) / la <= COPLANAR * math.sqrt(la)

    def frame(self, p: Vec, k: int, tau: int) -> Vec:
        """`p` of triangle `k` in tau's frame: as is in tau's planar face, rotated about an edge
        shared by the two faces, else as is."""
        src, dst = self.tris[k].face, self.tris[tau].face
        if src == dst:
            return p
        if (dst, src) not in self.hinges:
            found: Hinge | None = None
            for i in self.faces[dst]:
                for e in range(3):
                    if found is not None:
                        break
                    a, b = self.tris[i].vertex[(e + 1) % 3], self.tris[i].vertex[(e + 2) % 3]
                    for j in self.edges[(min(a, b), max(a, b))]:
                        if self.tris[j].face == src:
                            found = hinge(self.tris[i], self.tris[j], a, b)
                            break
                if found is not None:
                    break
            self.hinges[(dst, src)] = found
        h = self.hinges[(dst, src)]
        return p if h is None else unfold(h, p)

    def candidates(
        self, x: int, y: int, own: list[tuple[int, int]], tau: int
    ) -> list[tuple[float, bool, tuple[int, int]]]:
        """Ring texel (x, y)'s candidates (distance, far, texel) in tap order, through `tau`."""
        T = self.tris[tau]
        q = T.point(T.bary(x + 0.5, y + 0.5))
        out: dict[tuple[int, int], tuple[float, bool, tuple[int, int]]] = {}

        def put(tx: int, ty: int, far: bool) -> None:
            k = int(self.owner[ty, tx])
            p = self.frame(self.tris[k].point(self.tris[k].bary(tx + 0.5, ty + 0.5)), k, tau)
            out[(tx, ty)] = (norm(sub(q, p)), far, (tx, ty))

        for tx, ty in own:
            put(tx, ty, False)
        # Decision 275: every seam edge of tau's island, q folded into the far triangle, and the
        # far island's covered texels of columns floor(f_u - 1/2) +- 1, rows ceil(f_v - 1/2) +- 1.
        for e_index, edge, j in self.seams.get(T.chart, []):
            E, J = self.tris[e_index], self.tris[j]
            va, vb = E.vertex[(edge + 1) % 3], E.vertex[(edge + 2) % 3]
            fu, fv = J.texel_of(fold(hinge(E, J, va, vb), q))
            col0, row0 = math.floor(fu - 0.5), math.ceil(fv - 0.5)
            for row in range(row0 - 1, row0 + 2):
                for col in range(col0 - 1, col0 + 2):
                    if not (0 <= row < self.height and 0 <= col < self.width):
                        continue
                    k = int(self.owner[row, col])
                    if k < 0 or self.tris[k].chart != J.chart or (col, row) in out:
                        continue
                    put(col, row, True)
        ordered = sorted(out.values(), key=lambda c: (c[0], c[2][1] * self.width + c[2][0]))
        result: list[tuple[float, bool, tuple[int, int]]] = []
        while ordered:
            group = [ordered[0]]
            for c in ordered[1:]:
                if c[0] > ordered[0][0] * (1.0 + EQUAL_SHARE):
                    break
                group.append(c)
            ordered = ordered[len(group) :]
            if len(group) > 1:

                def key(c: tuple[float, bool, tuple[int, int]]) -> tuple[Any, ...]:
                    if c[1]:
                        return (True, 0.0, -c[2][0], c[2][1])
                    k = self.tris[int(self.owner[c[2][1], c[2][0]])]
                    d = compare_distance(k.uv, k.normalised, self.width, self.height, (x, y), c[2])
                    return (False, float(d), -c[2][0], c[2][1])

                group.sort(key=key)
            result += group
        return result[:KEPT]

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
                tau = max(int(self.owner[ty, tx]) for tx, ty in own)
                cands = self.candidates(x, y, own, tau)
                nearest = min((c[0] for c in cands if not c[1]), default=math.inf)
                taps = min(4, len(cands)) if cands[0][0] > ZERO_DISTANCE * nearest else 1
                out.append((x, y, cands, taps))
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
