"""UzmiGames-authored fixtures of the procedural feasibility study: two meshes and their mesh maps.

`docs/architecture/05-procedural-content.md` §6 names the unit sphere and the bevelled cube.
Both are written here from closed-form geometry, and so are their mesh maps: every texel of a
map is evaluated analytically at the surface point its UV maps to, so the maps are exact inputs
of the study rather than bakes. Painter receives them through the documented
`TextureSet.set_mesh_map_resource`, and the prototypes read the same files, so a generator's
residual measures the generator, never a baker.

- `sphere`: radius 1 at the origin, longitude/latitude UVs (u = longitude / 2 pi, v = latitude).
- `rounded-cube`: the unit cube (half size 0.5) with every edge and corner rounded at radius
  0.1, i.e. the points at distance 0.1 from the box of half size 0.4. Six square UV islands in
  a 3 x 2 grid of cells one third wide; texels of a cell outside its island repeat the nearest
  island edge (the top third repeats the upper row).

Map conventions (authored, stated here and in the manifests):

| Map | Value |
|---|---|
| position | (p - bbox min) / (bbox max - bbox min) per axis, RGB |
| world_space_normal | n / 2 + 1/2, RGB |
| normal | tangent-space flat normal (1/2, 1/2, 1), RGB |
| ambient_occlusion | 1 (both meshes are convex, nothing occludes), grey |
| curvature | 1/2 + 1/2 clamp(H r_ref, -1, 1) with H the mean curvature and r_ref = 0.05, grey |
| thickness | chord length through the solid along -n divided by the bbox diagonal, grey |

All maps are 16-bit PNG at 1024 x 1024, the texture-set resolution of every case.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from tools.parity.feasibility import png

Array = npt.NDArray[np.float64]

RESOLUTION = 1024
CURVATURE_REFERENCE_RADIUS = 0.05
CUBE_INNER = 0.4
CUBE_RADIUS = 0.1
SPHERE_SEGMENTS = (96, 48)  # longitude, latitude
CUBE_FACE_SEGMENTS = 40
MAP_NAMES = (
    "position",
    "world_space_normal",
    "normal",
    "ambient_occlusion",
    "curvature",
    "thickness",
)

# Rounded-cube faces: (outward axis n, tangent t1 along u, tangent t2 along v), t1 x t2 = n.
CUBE_FACES = (
    ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
    ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
    ((0, 1, 0), (1, 0, 0), (0, 0, -1)),
    ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
    ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    ((0, 0, -1), (-1, 0, 0), (0, 1, 0)),
)
CELL = 1.0 / 3.0
ISLAND_MARGIN = 0.03  # of the cell size, on each side


@dataclass(frozen=True)
class Surface:
    """Surface samples: position, unit normal and mean curvature, arrays of shape (..., 3)."""

    position: Array
    normal: Array
    mean_curvature: Array


@dataclass(frozen=True)
class Mesh:
    name: str
    positions: Array  # (n, 3)
    normals: Array  # (n, 3)
    uvs: Array  # (n, 2)
    triangles: npt.NDArray[np.int64]  # (m, 3), counter-clockwise seen from outside
    bbox: tuple[tuple[float, float, float], tuple[float, float, float]]
    sdf: Callable[[Array], Array]


# ---------------------------------------------------------------- sphere


def sphere_surface(u: Array, v: Array) -> Surface:
    phi = 2.0 * math.pi * u
    theta = math.pi * v  # 0 at the south pole (y = -1), pi at the north pole
    ring = np.sin(theta)
    normal = np.stack([ring * np.cos(phi), -np.cos(theta), -ring * np.sin(phi)], axis=-1)
    return Surface(normal.copy(), normal, np.ones_like(u))


def sphere_sdf(points: Array) -> Array:
    result: Array = np.linalg.norm(points, axis=-1) - 1.0
    return result


def sphere_mesh() -> Mesh:
    lon, lat = SPHERE_SEGMENTS
    u, v = np.meshgrid(np.arange(lon + 1) / lon, np.arange(lat + 1) / lat)
    surface = sphere_surface(u.ravel(), v.ravel())
    triangles: list[tuple[int, int, int]] = []
    for j in range(lat):
        for i in range(lon):
            a, b = j * (lon + 1) + i, j * (lon + 1) + i + 1
            c, d = a + lon + 1, b + lon + 1
            if j > 0:
                triangles.append((a, b, d))
            if j < lat - 1:
                triangles.append((a, d, c))
    return Mesh(
        "sphere",
        surface.position,
        surface.normal,
        np.stack([u.ravel(), v.ravel()], axis=-1),
        orient(surface.position, surface.normal, np.array(triangles, np.int64)),
        ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)),
        sphere_sdf,
    )


# ---------------------------------------------------------------- rounded cube


def cube_point(face: int, s: Array, t: Array) -> Array:
    n, t1, t2 = (np.array(axis, np.float64) for axis in CUBE_FACES[face])
    half = CUBE_INNER + CUBE_RADIUS
    point: Array = half * (n + s[..., None] * t1 + t[..., None] * t2)
    return point


def rounded_cube_surface(face: int, s: Array, t: Array) -> Surface:
    """Project the outer-cube point to the rounded surface around the inner box."""
    p = cube_point(face, s, t)
    q = np.clip(p, -CUBE_INNER, CUBE_INNER)
    offset = p - q
    normal = offset / np.linalg.norm(offset, axis=-1, keepdims=True)
    rounded = np.count_nonzero(np.abs(offset) > 1e-12, axis=-1)  # 1 face, 2 edge, 3 corner
    curvature = np.choose(rounded - 1, [0.0, 0.5 / CUBE_RADIUS, 1.0 / CUBE_RADIUS])
    return Surface(q + CUBE_RADIUS * normal, normal, curvature.astype(np.float64))


def rounded_cube_sdf(points: Array) -> Array:
    outside = np.maximum(np.abs(points) - CUBE_INNER, 0.0)
    inside = np.minimum(np.max(np.abs(points) - CUBE_INNER, axis=-1), 0.0)
    result: Array = np.linalg.norm(outside, axis=-1) + inside - CUBE_RADIUS
    return result


def island_uv(face: int, s: Array, t: Array) -> tuple[Array, Array]:
    col, row = face % 3, face // 3
    span = 1.0 - 2.0 * ISLAND_MARGIN
    u = CELL * (col + ISLAND_MARGIN + span * (s + 1.0) / 2.0)
    v = CELL * (row + ISLAND_MARGIN + span * (t + 1.0) / 2.0)
    return u, v


def rounded_cube_mesh() -> Mesh:
    count = CUBE_FACE_SEGMENTS
    grid = np.linspace(-1.0, 1.0, count + 1)
    s, t = np.meshgrid(grid, grid)
    positions, normals, uvs, triangles = [], [], [], []
    for face in range(6):
        surface = rounded_cube_surface(face, s.ravel(), t.ravel())
        u, v = island_uv(face, s.ravel(), t.ravel())
        base = face * (count + 1) ** 2
        for j in range(count):
            for i in range(count):
                a = base + j * (count + 1) + i
                b, c, d = a + 1, a + count + 1, a + count + 2
                triangles += [(a, b, d), (a, d, c)]
        positions.append(surface.position)
        normals.append(surface.normal)
        uvs.append(np.stack([u, v], axis=-1))
    position, normal = np.vstack(positions), np.vstack(normals)
    return Mesh(
        "rounded-cube",
        position,
        normal,
        np.vstack(uvs),
        orient(position, normal, np.array(triangles, np.int64)),
        ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)),
        rounded_cube_sdf,
    )


def orient(
    positions: Array, normals: Array, triangles: npt.NDArray[np.int64]
) -> npt.NDArray[np.int64]:
    """Flip triangles whose winding disagrees with the outward vertex normals; drop degenerate."""
    a, b, c = (positions[triangles[:, k]] for k in range(3))
    cross = np.cross(b - a, c - a)
    area = np.linalg.norm(cross, axis=-1)
    facing = np.einsum("ij,ij->i", cross, normals[triangles].sum(axis=1))
    kept = triangles[area > 1e-12]
    flip = (facing < 0)[area > 1e-12]
    kept[flip] = kept[flip][:, [0, 2, 1]]
    result: npt.NDArray[np.int64] = kept.astype(np.int64)
    return result


# ---------------------------------------------------------------- texel evaluation


def texel_uv(resolution: int = RESOLUTION) -> tuple[Array, Array]:
    """UV of every texel centre; row 0 of an image is v = 1 (top)."""
    centres = (np.arange(resolution) + 0.5) / resolution
    u, v = np.meshgrid(centres, centres[::-1])
    return u, v


def sphere_texels(resolution: int = RESOLUTION) -> Surface:
    u, v = texel_uv(resolution)
    return sphere_surface(u, v)


def rounded_cube_texels(resolution: int = RESOLUTION) -> Surface:
    u, v = texel_uv(resolution)
    col = np.minimum((u / CELL).astype(int), 2)
    row = np.minimum((v / CELL).astype(int), 1)
    span = 1.0 - 2.0 * ISLAND_MARGIN
    s = np.clip(((u / CELL - col - ISLAND_MARGIN) / span) * 2.0 - 1.0, -1.0, 1.0)
    t = np.clip(((v / CELL - row - ISLAND_MARGIN) / span) * 2.0 - 1.0, -1.0, 1.0)
    face = row * 3 + col
    position = np.zeros((*u.shape, 3))
    normal = np.zeros((*u.shape, 3))
    curvature = np.zeros(u.shape)
    for index in range(6):
        where = face == index
        surface = rounded_cube_surface(index, s[where], t[where])
        position[where], normal[where] = surface.position, surface.normal
        curvature[where] = surface.mean_curvature
    return Surface(position, normal, curvature)


def chord_lengths(mesh: Mesh, surface: Surface, steps: int = 96) -> Array:
    """Distance from each surface point along -n to where the ray leaves the solid (SDF march)."""
    start = 1e-4
    origin = surface.position - start * surface.normal
    direction = -surface.normal
    travelled = np.zeros(surface.position.shape[:-1])
    for _ in range(steps):
        inside = -mesh.sdf(origin + travelled[..., None] * direction)
        travelled += np.maximum(inside, 0.0)
    result: Array = travelled + start
    return result


def quantise(values: Array) -> npt.NDArray[np.uint16]:
    result: npt.NDArray[np.uint16] = np.round(np.clip(values, 0.0, 1.0) * 65535.0).astype(np.uint16)
    return result


def mesh_maps(mesh: Mesh, surface: Surface) -> dict[str, npt.NDArray[np.uint16]]:
    low, high = (np.array(corner) for corner in mesh.bbox)
    diagonal = float(np.linalg.norm(high - low))
    shape = surface.position.shape[:-1]
    flat_normal = np.broadcast_to(np.array([0.5, 0.5, 1.0]), (*shape, 3))
    curvature = 0.5 + 0.5 * np.clip(surface.mean_curvature * CURVATURE_REFERENCE_RADIUS, -1, 1)
    return {
        "position": quantise((surface.position - low) / (high - low)),
        "world_space_normal": quantise(surface.normal * 0.5 + 0.5),
        "normal": quantise(flat_normal),
        "ambient_occlusion": quantise(np.ones(shape)),
        "curvature": quantise(curvature),
        "thickness": quantise(chord_lengths(mesh, surface) / diagonal),
    }


# ---------------------------------------------------------------- files


def obj_text(mesh: Mesh) -> str:
    material = "uzp_" + mesh.name.replace("-", "_")
    lines = [
        f"# UzPainter procedural feasibility fixture: {mesh.name} (tools/parity/feasibility/fixtures.py).",  # noqa: E501
        "# Authored by UzmiGames (Apache-2.0) from closed-form geometry.",
        f"o {material}",
    ]
    lines += [f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in mesh.positions]
    lines += [f"vt {u:.6f} {v:.6f}" for u, v in mesh.uvs]
    lines += [f"vn {x:.6f} {y:.6f} {z:.6f}" for x, y, z in mesh.normals]
    lines.append(f"usemtl {material}")
    lines += [
        "f " + " ".join(f"{i + 1}/{i + 1}/{i + 1}" for i in triangle) for triangle in mesh.triangles
    ]
    return "\n".join(lines) + "\n"


FIXTURES: dict[str, tuple[Callable[[], Mesh], Callable[[int], Surface]]] = {
    "sphere": (sphere_mesh, sphere_texels),
    "rounded-cube": (rounded_cube_mesh, rounded_cube_texels),
}


def fixture_files(directory: Path) -> dict[str, Path]:
    """Every file the study's fixtures consist of, by `<fixture>/<map or mesh>` id."""
    files: dict[str, Path] = {}
    for name in FIXTURES:
        files[f"{name}/mesh"] = directory / f"{name}.obj"
        for map_name in MAP_NAMES:
            files[f"{name}/{map_name}"] = directory / f"{name}-{map_name.replace('_', '-')}.png"
    return files


def write_fixtures(directory: Path, resolution: int = RESOLUTION) -> dict[str, Path]:
    files = fixture_files(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, (build_mesh, texels) in FIXTURES.items():
        mesh = build_mesh()
        files[f"{name}/mesh"].write_text(obj_text(mesh), encoding="utf-8", newline="\n")
        for map_name, samples in mesh_maps(mesh, texels(resolution)).items():
            png.write(files[f"{name}/{map_name}"], samples)
    return files
