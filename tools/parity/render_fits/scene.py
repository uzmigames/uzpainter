"""Camera, mesh and ray queries of the feasibility prototype (07 §3.4; decision 046).

Camera: Painter's documented Perspective camera in its Y-up scene space, as qualified by the
capture procedure (`iray-capture-procedure.md` §5): the camera looks along its local -Z with
+Y up, the field of view spans the square image, and the fixtures' cameras are unrotated (the
recorder refuses anything else for these goldens). A ray through image position (x, y) in
pixels (origin at the top-left corner) has direction
    normalize(((2 x / W) - 1) tan(fov / 2), (1 - (2 y / H)) tan(fov / 2), -1).

Meshes: Wavefront OBJ with positions, texture coordinates and normals per corner (the
committed UzmiGames fixtures). Shading normals and UVs are interpolated with the hit's
barycentric weights; tangents follow the UV derivatives per triangle, averaged per vertex
(the MikkTSpace frame for these smooth, unmirrored UV layouts; `tangent-frame.json`).

Ray queries: primary rays test the triangles whose projected bounding box (grown by the pixel
filter's radius) covers the pixel, with the Moller-Trumbore test (PBRT 4th ed. §6.5.3,
P-PBRT, uses an equivalent watertight form); the nearest hit wins. A facet whose plane has
every vertex of the mesh on one side has an empty side (`empty_side`: +1 or -1 along the facet
normal, 2 for a planar mesh where both sides are empty, 0 otherwise): a secondary ray that
leaves the facet into its empty side cannot meet the mesh again, which is exact. On the closed
convex meshes and the plane of decision 046 that is every ray leaving the outside; any other
secondary ray is tested against every triangle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import numpy.typing as npt

F64 = npt.NDArray[np.float64]
I64 = npt.NDArray[np.int64]
EPSILON = 1e-9


@dataclass(frozen=True)
class Camera:
    position: tuple[float, float, float]
    field_of_view: float
    width: int
    height: int

    def rays(self, x: F64, y: F64) -> tuple[F64, F64]:
        """Origins and unit directions through continuous pixel positions."""
        if self.width != self.height:
            raise ValueError("the field-of-view axis is qualified for square renders only")
        tangent = math.tan(math.radians(self.field_of_view) / 2.0)
        dx = (2.0 * x / self.width - 1.0) * tangent
        dy = (1.0 - 2.0 * y / self.height) * tangent
        directions = np.stack([dx, dy, -np.ones_like(dx)], axis=-1)
        directions /= np.linalg.norm(directions, axis=-1, keepdims=True)
        origins = np.broadcast_to(np.asarray(self.position, dtype=np.float64), directions.shape)
        return np.array(origins), directions

    def project(self, points: F64) -> F64:
        """Continuous pixel positions of scene points (N, 3) -> (N, 2)."""
        tangent = math.tan(math.radians(self.field_of_view) / 2.0)
        local = points - np.asarray(self.position)
        depth = -local[:, 2]
        if np.any(depth <= 1e-6):
            raise ValueError("the mesh is not entirely in front of the camera")
        x = (local[:, 0] / (depth * tangent) + 1.0) * self.width / 2.0
        y = (1.0 - local[:, 1] / (depth * tangent)) * self.height / 2.0
        return np.stack([x, y], axis=-1)


@dataclass
class Mesh:
    positions: F64  # (V, 3)
    uvs: F64  # (T, 3, 2) per corner
    normals: F64  # (T, 3, 3) per corner
    triangles: I64  # (T, 3) position indices
    tangents: F64 = field(init=False)  # (T, 3, 3) per corner
    convex: bool = field(init=False)
    empty_side: npt.NDArray[np.int64] = field(init=False)

    def __post_init__(self) -> None:
        self.a = self.positions[self.triangles[:, 0]]
        self.e1 = self.positions[self.triangles[:, 1]] - self.a
        self.e2 = self.positions[self.triangles[:, 2]] - self.a
        face = np.cross(self.e1, self.e2)
        self.face_normals = face / np.linalg.norm(face, axis=1, keepdims=True)
        self.tangents = self._tangents()
        self.empty_side = empty_sides(self)
        self.convex = bool(np.all(self.empty_side != 0))

    def _tangents(self) -> F64:
        duv1 = self.uvs[:, 1] - self.uvs[:, 0]
        duv2 = self.uvs[:, 2] - self.uvs[:, 0]
        det = duv1[:, 0] * duv2[:, 1] - duv2[:, 0] * duv1[:, 1]
        safe = np.where(np.abs(det) > 1e-20, det, 1.0)
        t = (self.e1 * duv2[:, 1:2] - self.e2 * duv1[:, 1:2]) / safe[:, None]
        t = np.where(np.abs(det)[:, None] > 1e-20, t, 0.0)
        accum = np.zeros_like(self.positions)
        np.add.at(accum, self.triangles.ravel(), np.repeat(t, 3, axis=0))
        per_corner = accum[self.triangles]
        n = self.normals
        per_corner -= n * np.sum(per_corner * n, axis=-1, keepdims=True)
        length = np.linalg.norm(per_corner, axis=-1, keepdims=True)
        result: F64 = np.where(length > 1e-12, per_corner / np.maximum(length, 1e-12), 0.0)
        return result


def load_obj(path: Path) -> Mesh:
    positions: list[list[float]] = []
    uvs: list[list[float]] = []
    normals: list[list[float]] = []
    tri_v: list[list[int]] = []
    tri_t: list[list[int]] = []
    tri_n: list[list[int]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            positions.append([float(p) for p in parts[1:4]])
        elif parts[0] == "vt":
            uvs.append([float(p) for p in parts[1:3]])
        elif parts[0] == "vn":
            normals.append([float(p) for p in parts[1:4]])
        elif parts[0] == "f":
            corners = []
            for ref in parts[1:]:
                fields = [*ref.split("/"), "", ""][:3]
                corners.append([int(f) - 1 if f else -1 for f in fields])
            for k in range(1, len(corners) - 1):
                tri = (corners[0], corners[k], corners[k + 1])
                tri_v.append([c[0] for c in tri])
                tri_t.append([c[1] for c in tri])
                tri_n.append([c[2] for c in tri])
    pos = np.asarray(positions, dtype=np.float64)
    tv = np.asarray(tri_v, dtype=np.int64)
    tt = np.asarray(tri_t, dtype=np.int64)
    tn = np.asarray(tri_n, dtype=np.int64)
    if np.any(tt < 0) or np.any(tn < 0):
        raise ValueError(f"{path.name}: every corner needs a texture coordinate and a normal")
    # Zero-area triangles (a UV sphere's pole fans) carry no surface: drop them.
    points = pos[tv]
    area = np.linalg.norm(
        np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]), axis=1
    )
    keep = area > 1e-12 * max(float(np.ptp(pos)), 1.0) ** 2
    tv, tt, tn = tv[keep], tt[keep], tn[keep]
    uv = np.asarray(uvs, dtype=np.float64)[tt]
    nrm = np.asarray(normals, dtype=np.float64)[tn]
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    return Mesh(pos, uv, nrm, tv)


def empty_sides(mesh: Mesh) -> npt.NDArray[np.int64]:
    """Per facet: +1 when no vertex lies in front of its plane (along the facet normal), -1 when
    none lies behind it, 2 when every vertex lies in the plane, 0 otherwise."""
    offsets = mesh.positions @ mesh.face_normals.T - np.sum(mesh.a * mesh.face_normals, axis=1)
    tolerance = 1e-6 * float(np.ptp(mesh.positions))
    front_empty = offsets.max(axis=0) <= tolerance
    back_empty = offsets.min(axis=0) >= -tolerance
    sides: npt.NDArray[np.int64] = np.where(
        front_empty & back_empty, 2, np.where(front_empty, 1, np.where(back_empty, -1, 0))
    ).astype(np.int64)
    return sides


@dataclass
class Hits:
    valid: npt.NDArray[np.bool_]
    triangle: I64
    t: F64
    b1: F64
    b2: F64


def intersect(mesh: Mesh, origins: F64, directions: F64, candidates: I64) -> Hits:
    """Nearest hit among candidate triangles (N, C) (-1 = none), Moller-Trumbore."""
    n, c = candidates.shape
    best_t = np.full(n, np.inf)
    best_tri = np.full(n, -1, dtype=np.int64)
    best_b1 = np.zeros(n)
    best_b2 = np.zeros(n)
    for k in range(c):
        tri = candidates[:, k]
        live = tri >= 0
        if not np.any(live):
            continue
        idx = np.nonzero(live)[0]
        tr = tri[idx]
        e1, e2, a = mesh.e1[tr], mesh.e2[tr], mesh.a[tr]
        d = directions[idx]
        p = np.cross(d, e2)
        det = np.sum(e1 * p, axis=1)
        ok = np.abs(det) > EPSILON
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = origins[idx] - a
        b1 = np.sum(s * p, axis=1) * inv
        q = np.cross(s, e1)
        b2 = np.sum(d * q, axis=1) * inv
        t = np.sum(e2 * q, axis=1) * inv
        hit = ok & (b1 >= 0) & (b2 >= 0) & (b1 + b2 <= 1) & (t > 1e-7) & (t < best_t[idx])
        sel = idx[hit]
        best_t[sel] = t[hit]
        best_tri[sel] = tr[hit]
        best_b1[sel] = b1[hit]
        best_b2[sel] = b2[hit]
    return Hits(best_tri >= 0, best_tri, best_t, best_b1, best_b2)


def pixel_candidates(mesh: Mesh, camera: Camera, pixels: I64, radius: float) -> I64:
    """Per pixel index (y * W + x), the triangles whose projected box, grown by `radius`
    pixels, overlaps the pixel's square (padded with -1)."""
    corners = camera.project(mesh.positions)[mesh.triangles]  # (T, 3, 2)
    low = np.floor(corners.min(axis=1) - radius).astype(np.int64)
    high = np.floor(corners.max(axis=1) + radius).astype(np.int64)
    width = camera.width
    lists: dict[int, list[int]] = {}
    wanted = set(pixels.tolist())
    for tri in range(len(corners)):
        x0, y0 = max(int(low[tri, 0]), 0), max(int(low[tri, 1]), 0)
        x1, y1 = min(int(high[tri, 0]), camera.width - 1), min(int(high[tri, 1]), camera.height - 1)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                key = y * width + x
                if key in wanted:
                    lists.setdefault(key, []).append(tri)
    size = max((len(v) for v in lists.values()), default=1)
    table = np.full((len(pixels), size), -1, dtype=np.int64)
    for row, key in enumerate(pixels.tolist()):
        found = lists.get(key, [])
        table[row, : len(found)] = found
    return table


@dataclass
class Surface:
    triangle: I64
    position: F64
    geometric: F64  # facet normal facing the incoming ray's side
    shading: F64
    tangent: F64
    uv: F64


def surface(mesh: Mesh, hits: Hits, directions: F64) -> Surface:
    tri = hits.triangle
    w1, w2 = hits.b1[:, None], hits.b2[:, None]
    w0 = 1.0 - w1 - w2
    position = mesh.a[tri] + w1 * mesh.e1[tri] + w2 * mesh.e2[tri]
    n = mesh.normals[tri]
    shading = w0 * n[:, 0] + w1 * n[:, 1] + w2 * n[:, 2]
    shading /= np.linalg.norm(shading, axis=1, keepdims=True)
    t = mesh.tangents[tri]
    tangent = w0 * t[:, 0] + w1 * t[:, 1] + w2 * t[:, 2]
    uv = mesh.uvs[tri]
    uv_hit = w0 * uv[:, 0] + w1 * uv[:, 1] + w2 * uv[:, 2]
    geometric = mesh.face_normals[tri]
    # Facing: the facet normal points to the side the ray came from.
    flip = np.sum(geometric * directions, axis=1) > 0
    geometric = np.where(flip[:, None], -geometric, geometric)
    shading = np.where((np.sum(shading * geometric, axis=1) < 0)[:, None], -shading, shading)
    return Surface(tri, position, geometric, shading, tangent, uv_hit)
