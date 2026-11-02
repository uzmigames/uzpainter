"""OBJ files of the CPU baker's analytic fixtures for Painter's Tier 2b bake goldens (decision 384).

The geometry is `tests/bake/bake_fixtures.h`'s, ported line for line: the same constants, the same
corner order and winding, double arithmetic cast to float32 where the C++ casts, so the committed
files hold the float32 values the native fixtures hold. `tests/parity/tier2b_bakes/test_fixtures.py`
reads the C++ sources and fails when a constant here no longer equals its C++ counterpart.

| File | Objects | C++ source |
|---|---|---|
| `plane-low.obj` | `low` | `fixtures::Plane("low", -1, 1, -1, 1, 0)` |
| `plane-high.obj` | `normal_high` | `NormalHigh({0, 0, 1})` (`normal_bake_cases.h`) |
| `slab-high.obj` | `slab` | `CaseThicknessPlane`'s slab (`thickness_bake_cases.h`) |
| `sphere-on-ground.obj` | `sphere_on_ground` | `fixtures::SphereOnGround()`, baked low as high |
| `bevelled-cube-low.obj` | `cube_low`, `knob_low` | the `Bevel` fixture's low parts |
| `bevelled-cube-high.obj` | `cube_high`, `knob_high_ignorebf`, `decoy_high` | its highs |

Coordinates are the C++ ones, written as they are (z up, as the fixtures author them); OBJ states no
unit, so one file unit is one centimetre for Painter and for UzPainter's importer
(`12-mesh-import.md` §3), the C++ requests' `scale_to_internal` 1. Meshes without UVs in C++ (the
chamfered cube) are written without `vt`. Every object keeps its own corners (nothing welded), in
the C++ order. Low files name their texture set with `usemtl`.

    python -m tools.parity.tier2b_bakes write   (fixtures and requests)
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from tools.parity.schemas import REPO_ROOT

FIXTURE_DIR_NAME = "tier2b-bakes"
FIXTURE_DIR = REPO_ROOT / "parity" / "fixtures" / FIXTURE_DIR_NAME
GENERATOR = "tools/parity/tier2b_bakes/fixtures.py"

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]


def f32(value: float) -> float:
    """`static_cast<float>` of a double (round to nearest even)."""
    result: float = struct.unpack("<f", struct.pack("<f", value))[0]
    return result


def f3(x: float, y: float, z: float) -> Vec3:
    return (f32(x), f32(y), f32(z))


@dataclass
class Mesh:
    """One `BakeMesh`: per-vertex positions, normals and (optional) UVs, triangle indices."""

    name: str
    positions: list[Vec3] = field(default_factory=list)
    normals: list[Vec3] = field(default_factory=list)
    uvs: list[Vec2] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)


# ── bake_fixtures.h ──────────────────────────────────────────────────────────────────────────


def add_quad(mesh: Mesh, corners: Sequence[Vec3], normal: Vec3, uvs: Sequence[Vec2]) -> None:
    """`AddQuad`: a, b, c, d counter-clockwise from its front, as triangles (0,1,2) and (0,2,3)."""
    base = len(mesh.positions)
    for point in corners:
        mesh.positions.append(f3(*point))
        mesh.normals.append(f3(*normal))
    mesh.uvs.extend((f32(u), f32(v)) for u, v in uvs)
    mesh.indices.extend(base + i for i in (0, 1, 2, 0, 2, 3))


PLANE_UV0, PLANE_UV1 = (0.25, 0.25), (0.75, 0.75)


def plane(
    name: str,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    z: float,
    flipped: bool = False,
    uv0: Vec2 = PLANE_UV0,
    uv1: Vec2 = PLANE_UV1,
) -> Mesh:
    """`Plane`: the square [x0, x1] x [y0, y1] at height z, facing +z (-z when `flipped`)."""
    mesh = Mesh(name)
    x0, x1, y0, y1, z = (f32(v) for v in (x0, x1, y0, y1, z))
    a, b, c, d = (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)
    ua, ub, uc, ud = (uv0[0], uv0[1]), (uv1[0], uv0[1]), (uv1[0], uv1[1]), (uv0[0], uv1[1])
    if flipped:
        add_quad(mesh, (a, d, c, b), (0.0, 0.0, -1.0), (ua, ud, uc, ub))
    else:
        add_quad(mesh, (a, b, c, d), (0.0, 0.0, 1.0), (ua, ub, uc, ud))
    return mesh


def merge(name: str, parts: Sequence[Mesh]) -> Mesh:
    """`Merge`: one mesh holding the triangles of `parts`."""
    mesh = Mesh(name)
    for part in parts:
        base = len(mesh.positions)
        mesh.positions += part.positions
        mesh.normals += part.normals
        mesh.uvs += part.uvs
        mesh.indices += [base + i for i in part.indices]
    return mesh


SPHERE_CELLS, SPHERE_STACKS, SPHERE_SLICES = 8, 24, 48
GROUND_SIZE, SPHERE_RADIUS, SPHERE_CENTRE_Z = 4.0, 0.5, 0.5


def sphere_on_ground(
    cells: int = SPHERE_CELLS, stacks: int = SPHERE_STACKS, slices: int = SPHERE_SLICES
) -> Mesh:
    """`SphereOnGround`: a ground grid and a latitude-longitude sphere resting on it."""
    mesh = Mesh("sphere_on_ground")

    def x(k: int) -> float:
        return -2.0 + GROUND_SIZE * k / cells

    def u(k: int) -> float:
        return 0.01 + 0.48 * k / cells

    def v(k: int) -> float:
        return 0.01 + 0.98 * k / cells

    for j in range(cells):
        for i in range(cells):
            add_quad(
                mesh,
                (
                    (x(i), x(j), 0.0),
                    (x(i + 1), x(j), 0.0),
                    (x(i + 1), x(j + 1), 0.0),
                    (x(i), x(j + 1), 0.0),
                ),
                (0.0, 0.0, 1.0),
                ((u(i), v(j)), (u(i + 1), v(j)), (u(i + 1), v(j + 1)), (u(i), v(j + 1))),
            )
    base = len(mesh.positions)
    columns = slices + 1
    for i in range(stacks + 1):
        theta = math.pi * i / stacks
        for j in range(slices + 1):
            phi = 2.0 * math.pi * j / slices
            nx = math.sin(theta) * math.cos(phi)
            ny = math.sin(theta) * math.sin(phi)
            nz = math.cos(theta)
            mesh.positions.append(
                f3(SPHERE_RADIUS * nx, SPHERE_RADIUS * ny, SPHERE_CENTRE_Z + SPHERE_RADIUS * nz)
            )
            mesh.normals.append(f3(nx, ny, nz))
            mesh.uvs.append((f32(0.51 + 0.48 * j / slices), f32(0.99 - 0.98 * i / stacks)))
    for i in range(stacks):
        for j in range(slices):
            a = base + i * columns + j
            b = a + columns
            c = b + 1
            d = a + 1
            # The pole rows keep only their non-degenerate triangle.
            if i != stacks - 1:
                mesh.indices += [a, b, c]
            if i != 0:
                mesh.indices += [a, c, d]
    return mesh


# The bevelled cube with highs (decision 306).
ATLAS_WIDTH, ATLAS_HEIGHT, CELL, INSET, ISLAND = 128, 64, 32, 4, 24
TOP_FACE = 4
KNOB_CELL = 6
BEVEL = 0.15  # `kBevel` of bake_feasibility_test.cpp
CUBE_FACES: tuple[tuple[Vec3, Vec3, Vec3, Vec3, Vec3], ...] = (
    ((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1), (1, 0, 0)),
    ((-1, 1, -1), (-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 0, 0)),
    ((1, 1, -1), (-1, 1, -1), (-1, 1, 1), (1, 1, 1), (0, 1, 0)),
    ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1), (0, -1, 0)),
    ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1), (0, 0, 1)),
    ((-1, 1, -1), (1, 1, -1), (1, -1, -1), (-1, -1, -1), (0, 0, -1)),
)


def island_uv(cell: int) -> tuple[Vec2, Vec2]:
    """`IslandUv`: the UV rectangle of atlas cell `cell` (column cell % 4, row cell / 4 from the
    top), its edges on texel boundaries of the 128 x 64 atlas."""
    x0 = float((cell % 4) * CELL + INSET)
    y0 = float((cell // 4) * CELL + INSET)
    return (
        (f32(x0 / ATLAS_WIDTH), f32(1.0 - (y0 + ISLAND) / ATLAS_HEIGHT)),
        (f32((x0 + ISLAND) / ATLAS_WIDTH), f32(1.0 - y0 / ATLAS_HEIGHT)),
    )


def low_cube(name: str) -> Mesh:
    """`LowCube` (scale 1): the cube [-1, 1]^3, flat normals, face f in atlas cell f."""
    mesh = Mesh(name)
    for f, (a, b, c, d, n) in enumerate(CUBE_FACES):
        uv0, uv1 = island_uv(f)
        add_quad(mesh, (a, b, c, d), n, (uv0, (uv1[0], uv0[1]), uv1, (uv0[0], uv1[1])))
    return mesh


def chamfered_cube(name: str, b: float) -> Mesh:
    """`ChamferedCube`: the cube [-1, 1]^3 with every edge chamfered by `b`; 6 faces, 12 edge
    quads and 8 corner triangles, wound outward, flat normals, no UVs."""
    mesh = Mesh(name)
    m = 1.0 - b

    def point(axis: int, va: float, vb: float, vc: float) -> list[float]:
        p = [0.0, 0.0, 0.0]
        p[axis] = va
        p[(axis + 1) % 3] = vb
        p[(axis + 2) % 3] = vc
        return p

    def add(poly: list[list[float]]) -> None:
        e1 = [poly[1][k] - poly[0][k] for k in range(3)]
        e2 = [poly[2][k] - poly[0][k] for k in range(3)]
        n = [
            e1[1] * e2[2] - e1[2] * e2[1],
            e1[2] * e2[0] - e1[0] * e2[2],
            e1[0] * e2[1] - e1[1] * e2[0],
        ]
        if n[0] * poly[0][0] + n[1] * poly[0][1] + n[2] * poly[0][2] < 0.0:
            poly = poly[::-1]
            n = [-n[0], -n[1], -n[2]]
        length = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        normal = f3(n[0] / length, n[1] / length, n[2] / length)
        base = len(mesh.positions)
        for p in poly:
            mesh.positions.append(f3(p[0], p[1], p[2]))
            mesh.normals.append(normal)
        for i in range(1, len(poly) - 1):
            mesh.indices += [base, base + i, base + i + 1]

    for axis in range(3):
        for s in (-1.0, 1.0):
            add(
                [
                    point(axis, s, -m, -m),
                    point(axis, s, m, -m),
                    point(axis, s, m, m),
                    point(axis, s, -m, m),
                ]
            )
            for sc in (-1.0, 1.0):
                add(
                    [
                        point(axis, s, sc * m, -m),
                        point(axis, s * m, sc, -m),
                        point(axis, s * m, sc, m),
                        point(axis, s, sc * m, m),
                    ]
                )
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            for sz in (-1.0, 1.0):
                add([[sx, sy * m, sz * m], [sx * m, sy, sz * m], [sx * m, sy * m, sz]])
    return mesh


def knob_low(name: str) -> Mesh:
    """`KnobLow`: the plane [-0.5, 0.5]^2 at z = 3 facing up, in atlas cell 6."""
    uv0, uv1 = island_uv(KNOB_CELL)
    return plane(name, -0.5, 0.5, -0.5, 0.5, 3.0, False, uv0, uv1)


def knob_high(name: str) -> Mesh:
    """`KnobHigh`: its surface at z = 3 facing up under a cover at z = 3.02 facing down."""
    return merge(
        name, (plane("surface", -1, 1, -1, 1, 3.0), plane("cover", -1, 1, -1, 1, 3.02, True))
    )


def decoy(name: str) -> Mesh:
    """`Decoy`: [-1.5, 1.5]^2 at z = 1.02 facing down, over the cube's top face."""
    return plane(name, -1.5, 1.5, -1.5, 1.5, 1.02, True)


# ── The scenes' C++ request settings the goldens reproduce ───────────────────────────────────

# `NormalRequest` and `CaseThicknessPlane`: distance-based cage 0.05 / 0.05 mesh units;
# `Bevel::Request(0.04)` of `CaseMatchByName`: 0.05 frontal, 0.04 rear.
PLANE_MAX_HEIGHT = PLANE_MAX_DEPTH = 0.05
BEVEL_MAX_HEIGHT, BEVEL_MAX_DEPTH = 0.05, 0.04
SLAB_TOP_Z, SLAB_BOTTOM_Z, SLAB_HALF = 0.005, -0.245, 100.0
PLANE_HIGH_Z = 0.005


@dataclass(frozen=True)
class FixtureFile:
    file_name: str
    objects: tuple[Mesh, ...]
    material: str | None  # `usemtl` of a low file: the texture set Painter creates

    @property
    def stem(self) -> str:
        return self.file_name.rsplit(".", 1)[0]


def fixture_files() -> tuple[FixtureFile, ...]:
    return (
        FixtureFile("plane-low.obj", (plane("low", -1, 1, -1, 1, 0),), "uzp_plane"),
        FixtureFile("plane-high.obj", (plane("normal_high", -2, 2, -2, 2, PLANE_HIGH_Z),), None),
        FixtureFile(
            "slab-high.obj",
            (
                merge(
                    "slab",
                    (
                        plane("top", -SLAB_HALF, SLAB_HALF, -SLAB_HALF, SLAB_HALF, SLAB_TOP_Z),
                        plane(
                            "bottom",
                            -SLAB_HALF,
                            SLAB_HALF,
                            -SLAB_HALF,
                            SLAB_HALF,
                            SLAB_BOTTOM_Z,
                            True,
                        ),
                    ),
                ),
            ),
            None,
        ),
        FixtureFile("sphere-on-ground.obj", (sphere_on_ground(),), "uzp_sphere_on_ground"),
        FixtureFile(
            "bevelled-cube-low.obj",
            (low_cube("cube_low"), knob_low("knob_low")),
            "uzp_bevelled_cube",
        ),
        FixtureFile(
            "bevelled-cube-high.obj",
            (
                chamfered_cube("cube_high", BEVEL),
                knob_high("knob_high_ignorebf"),
                decoy("decoy_high"),
            ),
            None,
        ),
    )


# ── OBJ ──────────────────────────────────────────────────────────────────────────────────────


def number(value: float) -> str:
    """The shortest decimal that reads back as the same float32."""
    return str(np.format_float_positional(np.float32(value), unique=True, trim="-"))


def obj_text(fixture: FixtureFile) -> str:
    lines = [
        f"# UzPainter Tier 2b bake fixture {fixture.file_name} ({GENERATOR}, decision 384).",
        "# Authored by UzmiGames (Apache-2.0): tests/bake/bake_fixtures.h geometry, float32.",
    ]
    offset_v = offset_t = 0
    for mesh in fixture.objects:
        lines.append(f"o {mesh.name}")
        lines += [f"v {' '.join(number(c) for c in p)}" for p in mesh.positions]
        lines += [f"vt {' '.join(number(c) for c in uv)}" for uv in mesh.uvs]
        lines += [f"vn {' '.join(number(c) for c in n)}" for n in mesh.normals]
        if fixture.material is not None:
            lines.append(f"usemtl {fixture.material}")
        has_uvs = bool(mesh.uvs)
        for t in range(0, len(mesh.indices), 3):
            corners = []
            for i in mesh.indices[t : t + 3]:
                v = offset_v + i + 1
                uv = f"{offset_t + i + 1}" if has_uvs else ""
                corners.append(f"{v}/{uv}/{v}")
            lines.append("f " + " ".join(corners))
        offset_v += len(mesh.positions)
        offset_t += len(mesh.uvs)
    return "\n".join(lines) + "\n"


def committed_fixtures() -> dict[str, bytes]:
    return {f.file_name: obj_text(f).encode("utf-8") for f in fixture_files()}


def write_fixtures(directory: Path = FIXTURE_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, data in committed_fixtures().items():
        path = directory / name
        path.write_bytes(data)
        written.append(path)
    return written
