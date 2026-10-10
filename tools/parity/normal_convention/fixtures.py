"""UzmiGames-authored low/high mesh pairs of the normal-convention fixture (P0-NORMAL).

Both pairs are written from closed-form geometry so that the baked tangent-space normal field is
known analytically. Every high-poly mesh is *faceted*: each triangle has its own three vertices
and one normal, its geometric normal. Whatever point of a high triangle a bake ray hits, the
world-space normal it reads is that triangle's normal, so the field is constant per high
triangle and does not depend on where exactly a ray lands inside it. Texels whose ray could land
in a neighbouring triangle (near a triangle edge) are left out of the comparison domain.

Meshes are Y-up (Painter's convention for OBJ files); lengths are file units.

- `plane-dome`: the low mesh is the square [-1, 1]^2 in the XZ plane, normal +Y, with
  u = (x + 1) / 2 and v = (1 - z) / 2, so its MikkTSpace frame is the same at every texel:
  T = +X, B = -Z (the direction of increasing v), N = +Y, sign +1. The high mesh is a faceted
  spherical cap above it (sphere radius 1.6, centre on the -Y axis, footprint radius 0.8, apex
  height about 0.214), 16 segments by 6 rings. A bake ray leaves the plane along +Y; the texel
  reads the normal of the cap triangle whose XZ projection contains it, expressed in the
  constant frame: tangent = (n.x, -n.z, n.y). Texels outside the cap footprint have no hit.
  This pair settles the green-channel convention: cap triangles leaning towards -Z lean towards
  +v, i.e. towards +Y in tangent space.
- `hemisphere`: the low mesh is a coarse smooth unit hemisphere (y >= 0), 8 segments by 4
  rings plus the pole, vertex normals radial, UVs a top-down projection
  u = 0.5 + 0.45 x, v = 0.5 - 0.45 z. Its per-corner MikkTSpace frames vary inside every
  triangle, so the `PerVertex` and `PerFragment` frames differ. The high mesh is the same
  triangles scaled by 1.002 about the origin and faceted: the ray of any texel hits the scaled
  copy of its own triangle, whose normal is that triangle's geometric normal. The analytic field
  is therefore known in world space; its tangent-space value is what distinguishes the frames.

The bake resolution is 512 x 512 (`OutputSize` 2^9) for every pair.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

Array = npt.NDArray[np.float64]
Ids = npt.NDArray[np.int64]

RESOLUTION = 512
OUTPUT_SIZE_LOG2 = 9
FIXTURE_DIR_NAME = "normal-convention"

# plane-dome
PLANE_HALF_SIZE = 1.0
CAP_SPHERE_RADIUS = 1.6
CAP_FOOTPRINT_RADIUS = 0.8
CAP_SEGMENTS = 16
CAP_RINGS = 6
# hemisphere
HEMISPHERE_SEGMENTS = 8
HEMISPHERE_RINGS = 4
HEMISPHERE_UV_SCALE = 0.45
SHELL_SCALE = 1.002

# Texels whose (2 r + 1) x (2 r + 1) neighbourhood lies in one region form the domain.
DOMAIN_EROSION_RADIUS = 2


@dataclass(frozen=True)
class Mesh:
    """Triangles with per-vertex attributes; `faceted` meshes repeat vertices per triangle."""

    name: str
    positions: Array  # (n, 3)
    normals: Array  # (n, 3)
    uvs: Array | None  # (n, 2), None for a high mesh
    triangles: Ids  # (m, 3), counter-clockwise seen from outside
    faceted: bool


@dataclass(frozen=True)
class Corners:
    """A mesh as read from its OBJ file: attributes per triangle corner."""

    positions: Array  # (m, 3, 3)
    normals: Array  # (m, 3, 3)
    uvs: Array | None  # (m, 3, 2)


@dataclass(frozen=True)
class Pair:
    name: str
    low: Mesh
    high: Mesh
    # Common baking parameters the job sets besides `HipolyMesh` and `OutputSize`.
    common: dict[str, float | bool]
    # Whether the low mesh's frame varies, so that the domain is also split by low triangle.
    split_by_low_faces: bool


# ---------------------------------------------------------------- geometry


def face_normals(corners: Array) -> Array:
    """Unit geometric normals of triangles given as (m, 3, 3) corner positions."""
    cross = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    result: Array = cross / np.linalg.norm(cross, axis=1, keepdims=True)
    return result


def facet(name: str, positions: Array, triangles: Ids) -> Mesh:
    """The faceted copy of a triangle list: three own vertices and one normal per triangle."""
    corners = positions[triangles]
    normals = np.repeat(face_normals(corners), 3, axis=0)
    flat = corners.reshape(-1, 3)
    return Mesh(name, flat, normals, None, np.arange(len(flat)).reshape(-1, 3), True)


def plane_low() -> Mesh:
    h = PLANE_HALF_SIZE
    positions = np.array([[-h, 0, h], [h, 0, h], [h, 0, -h], [-h, 0, -h]], np.float64)
    uvs = np.stack([(positions[:, 0] + 1) / 2, (1 - positions[:, 2]) / 2], axis=1)
    normals = np.tile([0.0, 1.0, 0.0], (4, 1))
    return Mesh("plane-low", positions, normals, uvs, np.array([[0, 1, 2], [0, 2, 3]]), False)


def cap_centre_height() -> float:
    return -math.sqrt(CAP_SPHERE_RADIUS**2 - CAP_FOOTPRINT_RADIUS**2)


def dome_high() -> Mesh:
    """Faceted spherical cap: apex, then rings at polar angles k / K of the footprint angle."""
    centre = np.array([0.0, cap_centre_height(), 0.0])
    alpha_max = math.asin(CAP_FOOTPRINT_RADIUS / CAP_SPHERE_RADIUS)
    points = [centre + np.array([0.0, CAP_SPHERE_RADIUS, 0.0])]
    for k in range(1, CAP_RINGS + 1):
        alpha = alpha_max * k / CAP_RINGS
        for i in range(CAP_SEGMENTS):
            phi = 2 * math.pi * i / CAP_SEGMENTS
            direction = np.array(
                [math.sin(alpha) * math.cos(phi), math.cos(alpha), -math.sin(alpha) * math.sin(phi)]
            )
            points.append(centre + CAP_SPHERE_RADIUS * direction)
    positions = np.array(points)

    def ring(k: int, i: int) -> int:
        return 1 + (k - 1) * CAP_SEGMENTS + i % CAP_SEGMENTS

    triangles = [(0, ring(1, i), ring(1, i + 1)) for i in range(CAP_SEGMENTS)]
    for k in range(1, CAP_RINGS):
        for i in range(CAP_SEGMENTS):
            a, b = ring(k, i), ring(k, i + 1)
            c, d = ring(k + 1, i), ring(k + 1, i + 1)
            triangles += [(a, c, d), (a, d, b)]
    return facet("plane-dome-high", positions, orient_up(positions, np.array(triangles)))


def orient_up(positions: Array, triangles: Ids) -> Ids:
    """Flip triangles whose geometric normal points away from the cap's outside (+Y side)."""
    centre = np.array([0.0, cap_centre_height(), 0.0])
    corners = positions[triangles]
    outward = corners.mean(axis=1) - centre
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    flip = np.einsum("ij,ij->i", normals, outward) < 0
    fixed = triangles.copy()
    fixed[flip] = fixed[flip][:, [0, 2, 1]]
    return fixed


def hemisphere_points() -> tuple[Array, Ids]:
    """Unit hemisphere y >= 0: rings at elevations k / K * 90 degrees (k < K), then the pole."""
    points = []
    for k in range(HEMISPHERE_RINGS):
        elevation = 0.5 * math.pi * k / HEMISPHERE_RINGS
        for i in range(HEMISPHERE_SEGMENTS):
            phi = 2 * math.pi * i / HEMISPHERE_SEGMENTS
            points.append(
                [
                    math.cos(elevation) * math.cos(phi),
                    math.sin(elevation),
                    -math.cos(elevation) * math.sin(phi),
                ]
            )
    points.append([0.0, 1.0, 0.0])
    positions = np.array(points)
    pole = len(points) - 1

    def ring(k: int, i: int) -> int:
        return k * HEMISPHERE_SEGMENTS + i % HEMISPHERE_SEGMENTS

    triangles = []
    for k in range(HEMISPHERE_RINGS - 1):
        for i in range(HEMISPHERE_SEGMENTS):
            a, b = ring(k, i), ring(k, i + 1)
            c, d = ring(k + 1, i), ring(k + 1, i + 1)
            triangles += [(a, b, d), (a, d, c)]
    top = HEMISPHERE_RINGS - 1
    triangles += [(ring(top, i), ring(top, i + 1), pole) for i in range(HEMISPHERE_SEGMENTS)]
    tris = np.array(triangles)
    corners = positions[tris]
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    if np.any(np.einsum("ij,ij->i", normals, corners.mean(axis=1)) <= 0):
        raise AssertionError("hemisphere triangles must be counter-clockwise seen from outside")
    return positions, tris


def hemisphere_low() -> Mesh:
    positions, triangles = hemisphere_points()
    uvs = np.stack(
        [
            0.5 + HEMISPHERE_UV_SCALE * positions[:, 0],
            0.5 - HEMISPHERE_UV_SCALE * positions[:, 2],
        ],
        axis=1,
    )
    return Mesh("hemisphere-low", positions, positions.copy(), uvs, triangles, False)


def hemisphere_high() -> Mesh:
    positions, triangles = hemisphere_points()
    return facet("hemisphere-high", positions * SHELL_SCALE, triangles)


def pairs() -> dict[str, Pair]:
    return {
        "plane-dome": Pair(
            "plane-dome",
            plane_low(),
            dome_high(),
            # The cap rises about 0.21 above the plane: a frontal distance of 0.2 of the
            # bounding box reaches it whichever box measure Painter scales by (the plane's box
            # is 2 x 0 x 2).
            {"MaxHeight": 0.2},
            False,
        ),
        "hemisphere": Pair("hemisphere", hemisphere_low(), hemisphere_high(), {}, True),
    }


# ---------------------------------------------------------------- OBJ files


def obj_text(mesh: Mesh) -> str:
    material = "uzp_" + mesh.name.replace("-", "_")
    lines = [
        f"# UzPainter normal-convention fixture: {mesh.name} "
        "(tools/parity/normal_convention/fixtures.py).",
        "# Authored by UzmiGames (Apache-2.0) from closed-form geometry.",
        f"o {material}",
    ]
    lines += [f"v {x:.9f} {y:.9f} {z:.9f}" for x, y, z in mesh.positions]
    if mesh.uvs is not None:
        lines += [f"vt {u:.9f} {v:.9f}" for u, v in mesh.uvs]
    lines += [f"vn {x:.9f} {y:.9f} {z:.9f}" for x, y, z in mesh.normals]
    lines.append(f"usemtl {material}")
    for triangle in mesh.triangles:
        if mesh.uvs is not None:
            lines.append("f " + " ".join(f"{i + 1}/{i + 1}/{i + 1}" for i in triangle))
        else:
            lines.append("f " + " ".join(f"{i + 1}//{i + 1}" for i in triangle))
    return "\n".join(lines) + "\n"


def parse_obj(text: str) -> Corners:
    """Triangles of an OBJ file as written by `obj_text` (`v`, `vt`, `vn`, `f a/b/c`)."""
    v: list[list[float]] = []
    vt: list[list[float]] = []
    vn: list[list[float]] = []
    faces: list[list[tuple[int, int | None, int]]] = []
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "v":
            v.append([float(x) for x in parts[1:4]])
        elif parts[0] == "vt":
            vt.append([float(x) for x in parts[1:3]])
        elif parts[0] == "vn":
            vn.append([float(x) for x in parts[1:4]])
        elif parts[0] == "f":
            if len(parts) != 4:
                raise ValueError(f"only triangles are supported: {line!r}")
            corners = []
            for token in parts[1:]:
                p, t, n = token.split("/")
                corners.append((int(p) - 1, int(t) - 1 if t else None, int(n) - 1))
            faces.append(corners)
    positions = np.array([[v[p] for p, _, _ in f] for f in faces])
    normals = np.array([[vn[n] for _, _, n in f] for f in faces])
    has_uv = all(t is not None for f in faces for _, t, _ in f)
    uvs = np.array([[vt[t] for _, t, _ in f if t is not None] for f in faces]) if has_uv else None
    return Corners(positions, normals, uvs)


def fixture_files(directory: Path) -> dict[str, Path]:
    """`<pair>/low` and `<pair>/high` OBJ paths."""
    files: dict[str, Path] = {}
    for name in pairs():
        files[f"{name}/low"] = directory / f"{name}-low.obj"
        files[f"{name}/high"] = directory / f"{name}-high.obj"
    return files


def write_fixtures(directory: Path) -> dict[str, Path]:
    files = fixture_files(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, pair in pairs().items():
        files[f"{name}/low"].write_text(obj_text(pair.low), encoding="utf-8", newline="\n")
        files[f"{name}/high"].write_text(obj_text(pair.high), encoding="utf-8", newline="\n")
    return files


def read_corners(path: Path) -> Corners:
    return parse_obj(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- analytic field


def texel_centres(resolution: int = RESOLUTION) -> tuple[Array, Array]:
    """(u, v) of every texel centre, shape (resolution, resolution); row 0 is v = 1."""
    centres = (np.arange(resolution) + 0.5) / resolution
    u, v = np.meshgrid(centres, 1.0 - centres)
    return u, v


def locate(points: Array, triangles: Array) -> Ids:
    """Index of the first 2-D triangle (m, 3, 2) containing each point (..., 2), else -1."""
    flat = points.reshape(-1, 2)
    result = np.full(len(flat), -1, np.int64)
    for index, (a, b, c) in enumerate(triangles):
        denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(denominator) < 1e-15:
            continue
        w0 = ((b[1] - c[1]) * (flat[:, 0] - c[0]) + (c[0] - b[0]) * (flat[:, 1] - c[1])) / (
            denominator
        )
        w1 = ((c[1] - a[1]) * (flat[:, 0] - c[0]) + (a[0] - c[0]) * (flat[:, 1] - c[1])) / (
            denominator
        )
        inside = (w0 >= 0) & (w1 >= 0) & (w0 + w1 <= 1) & (result < 0)
        result[inside] = index
    located: Ids = result.reshape(points.shape[:-1])
    return located


@dataclass(frozen=True)
class Field:
    """The analytic bake of one pair at the bake resolution (row 0 is v = 1)."""

    low_face: Ids  # (h, w): low triangle containing the texel centre, -1 outside the UVs
    high_face: Ids  # (h, w): high triangle the texel's ray hits, -1 for no hit
    world_normal: Array  # (h, w, 3): normal read from the high mesh (0 where no hit)
    domain: npt.NDArray[np.bool_]  # covered texels whose neighbourhood is one region


def analytic_field(name: str, low: Corners, high: Corners, resolution: int = RESOLUTION) -> Field:
    """The field of pair `name` from its OBJ files' corners (`fixture_files`)."""
    if low.uvs is None:
        raise ValueError("the low mesh needs UVs")
    u, v = texel_centres(resolution)
    uv = np.stack([u, v], axis=-1)
    low_face = locate(uv, low.uvs)
    high_normals = face_normals(high.positions)
    if name == "plane-dome":
        # Rays leave the plane along +Y; the hit is the cap triangle above the texel.
        x, z = 2 * u - 1, 1 - 2 * v
        high_face = locate(np.stack([x, z], axis=-1), high.positions[:, :, [0, 2]])
        high_face[low_face < 0] = -1
        split = False
    elif name == "hemisphere":
        # The shell is the low mesh scaled about the origin: same triangle order.
        high_face = low_face.copy()
        split = True
    else:
        raise ValueError(f"unknown pair {name!r}")
    world = np.where((high_face >= 0)[..., None], high_normals[np.maximum(high_face, 0)], 0.0)
    region = high_face * (len(low.positions) + 1) + low_face if split else high_face
    region = np.where(low_face >= 0, region, -2)
    return Field(low_face, high_face, world, uniform_neighbourhood(region, low_face >= 0))


def uniform_neighbourhood(
    region: Ids, covered: npt.NDArray[np.bool_], radius: int = DOMAIN_EROSION_RADIUS
) -> npt.NDArray[np.bool_]:
    """Covered texels whose (2 r + 1)^2 neighbourhood is covered and lies in their region."""
    height, width = region.shape
    padded = np.pad(region, radius, constant_values=-3)
    keep = covered.copy()
    for dy in range(2 * radius + 1):
        for dx in range(2 * radius + 1):
            keep &= padded[dy : dy + height, dx : dx + width] == region
    return keep


def plane_tangent_normal(world: Array) -> Array:
    """World normals in the plane's constant frame T = +X, B = -Z, N = +Y."""
    return np.stack([world[..., 0], -world[..., 2], world[..., 1]], axis=-1)
