"""Tier 2b bake fixtures and their recording requests (decision 384): the committed OBJ files are
the generator's, the generator's constants are the C++ fixtures' (read from the C++ sources, so a
change on either side fails here), and every request is a valid recorder job of the current
envelope. No Painter, no GPU, no native build."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np

from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder.job import load_job, sha256_file
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.tier2b_bakes import fixtures as fx
from tools.parity.tier2b_bakes import requests as rq

BAKE_TESTS = REPO_ROOT / "tests" / "bake"


def cpp(name: str) -> str:
    """A C++ source with its whitespace collapsed."""
    return " ".join((BAKE_TESTS / name).read_text(encoding="utf-8").split())


def lit(value: float, suffix: str = "f") -> str:
    """A float literal as the C++ sources write it (`0.005f`, `3.0f`, `-2`)."""
    if float(value).is_integer() and suffix == "":
        return str(int(value))
    text = repr(float(value))
    return f"{text}{suffix}"


def test_generator_constants_are_the_cpp_fixtures() -> None:
    header = cpp("bake_fixtures.h")
    cells, stacks, slices = map(
        int,
        re.search(
            r"SphereOnGround\(std::uint32_t cells = (\d+), std::uint32_t stacks = (\d+), "
            r"std::uint32_t slices = (\d+)\)",
            header,
        ).groups(),  # type: ignore[union-attr]
    )
    assert (cells, stacks, slices) == (fx.SPHERE_CELLS, fx.SPHERE_STACKS, fx.SPHERE_SLICES)
    for snippet in (
        f"const double size = {fx.GROUND_SIZE!r};",
        f"const double radius = {fx.SPHERE_RADIUS!r};",
        f"const double cz = {fx.SPHERE_CENTRE_Z!r};",
        "return static_cast<float>(-2.0 + size * k / cells);",
        "return static_cast<float>(0.01 + 0.48 * k / cells);",
        "return static_cast<float>(0.01 + 0.98 * k / cells);",
        "static_cast<float>(0.51 + 0.48 * j / slices)",
        "static_cast<float>(0.99 - 0.98 * i / stacks)",
        f"Float2 uv0 = {{{lit(fx.PLANE_UV0[0])}, {lit(fx.PLANE_UV0[1])}}}",
        f"Float2 uv1 = {{{lit(fx.PLANE_UV1[0])}, {lit(fx.PLANE_UV1[1])}}}",
        f"kAtlasWidthLog2 = {int(math.log2(fx.ATLAS_WIDTH))};",
        f"kAtlasHeightLog2 = {int(math.log2(fx.ATLAS_HEIGHT))};",
        f"kCell = {fx.CELL};",
        f"kInset = {fx.INSET};",
        f"kIsland = {fx.ISLAND};",
        f"kTopFace = {fx.TOP_FACE};",
        f"IslandUv({fx.KNOB_CELL}, uv0, uv1); return Plane(std::move(name), -0.5f, 0.5f, -0.5f, "
        "0.5f, 3.0f, false, uv0, uv1);",
        'Plane("surface", -1, 1, -1, 1, 3.0f), Plane("cover", -1, 1, -1, 1, 3.02f, true)',
        "Plane(std::move(name), -1.5f, 1.5f, -1.5f, 1.5f, 1.02f, true)",
        "const double m = 1.0 - b;",
        # The structure the port follows: corner and index order, winding, loops, casts.
        "for (std::uint32_t i : {0u, 1u, 2u, 0u, 2u, 3u}) mesh.indices.push_back(base + i);",
        "const Float3 a{x0, y0, z}, b{x1, y0, z}, c{x1, y1, z}, d{x0, y1, z};",
        "const Float2 ua{uv0.x, uv0.y}, ub{uv1.x, uv0.y}, uc{uv1.x, uv1.y}, ud{uv0.x, uv1.y};",
        "AddQuad(mesh, a, d, c, b, {0.0f, 0.0f, -1.0f}, ua, ud, uc, ub);",
        "AddQuad(mesh, a, b, c, d, {0.0f, 0.0f, 1.0f}, ua, ub, uc, ud);",
        "for (std::uint32_t j = 0; j < cells; ++j) { for (std::uint32_t i = 0; i < cells; ++i) {",
        "AddQuad(mesh, {x(i), x(j), 0.0f}, {x(i + 1), x(j), 0.0f}, {x(i + 1), x(j + 1), 0.0f}, "
        "{x(i), x(j + 1), 0.0f}, {0.0f, 0.0f, 1.0f}, {u(i), v(j)}, {u(i + 1), v(j)}, "
        "{u(i + 1), v(j + 1)}, {u(i), v(j + 1)});",
        "const double theta = std::numbers::pi * i / stacks;",
        "const double phi = 2.0 * std::numbers::pi * j / slices;",
        "const double nx = std::sin(theta) * std::cos(phi);",
        "const double ny = std::sin(theta) * std::sin(phi);",
        "const double nz = std::cos(theta);",
        "static_cast<float>(cz + radius * nz)",
        "const std::uint32_t a = base + i * columns + j; const std::uint32_t b = a + columns; "
        "const std::uint32_t c = b + 1; const std::uint32_t d = a + 1;",
        "if (i != stacks - 1) { for (std::uint32_t k : {a, b, c}) mesh.indices.push_back(k); } "
        "if (i != 0) { for (std::uint32_t k : {a, c, d}) mesh.indices.push_back(k); }",
        "uv0 = {x0 / 128.0f, 1.0f - (y0 + kIsland) / 64.0f}; "
        "uv1 = {(x0 + kIsland) / 128.0f, 1.0f - y0 / 64.0f};",
        "AddQuad(mesh, s(face.a), s(face.b), s(face.c), s(face.d), face.n, uv0, {uv1.x, uv0.y}, "
        "uv1, {uv0.x, uv1.y});",
        "if (n[0] * poly[0][0] + n[1] * poly[0][1] + n[2] * poly[0][2] < 0.0) { "
        "std::reverse(poly.begin(), poly.end()); n = {-n[0], -n[1], -n[2]}; }",
        "for (std::uint32_t k : {0u, i, i + 1}) mesh.indices.push_back(base + k);",
        "for (int axis = 0; axis < 3; ++axis) { for (double s : {-1.0, 1.0}) {",
        "add({point(axis, s, -m, -m), point(axis, s, m, -m), point(axis, s, m, m), "
        "point(axis, s, -m, m)});",
        "for (double sc : {-1.0, 1.0}) { add({point(axis, s, sc * m, -m), "
        "point(axis, s * m, sc, -m), point(axis, s * m, sc, m), point(axis, s, sc * m, m)});",
        "for (double sx : {-1.0, 1.0}) { for (double sy : {-1.0, 1.0}) { "
        "for (double sz : {-1.0, 1.0}) add({P{sx, sy * m, sz * m}, P{sx * m, sy, sz * m}, "
        "P{sx * m, sy * m, sz}});",
        "for (const BakeMesh& part : parts) {",
    ):
        assert snippet in header, snippet
    table = header.split("kCubeFaces[6] = {", 1)[1].split("};", 1)[0]
    rows = re.findall(r"\{\{([^}]*)\}, \{([^}]*)\}, \{([^}]*)\}, \{([^}]*)\}, \{([^}]*)\}\}", table)
    faces = tuple(tuple(tuple(int(v) for v in c.split(",")) for c in row) for row in rows)
    assert faces == fx.CUBE_FACES

    driver = cpp("bake_feasibility_test.cpp")
    for snippet in (
        f"constexpr double kBevel = {fx.BEVEL!r};",
        'BakeMesh cube_low = fixtures::LowCube("cube_low");',
        'BakeMesh knob_low = fixtures::KnobLow("knob_low");',
        'BakeMesh cube_high = fixtures::ChamferedCube("cube_high", kBevel);',
        'BakeMesh knob_high = fixtures::KnobHigh("knob_high_ignorebf");',
        'BakeMesh decoy = fixtures::Decoy("decoy_high");',
        f"request.detail.max_height = {lit(fx.BEVEL_MAX_HEIGHT)};",
        "request.detail.filter_method = FilterMethod::ByMeshName;",
        "request.low = {&cube_low, &knob_low}; request.high = {&cube_high, &knob_high, &decoy};",
        f"const BakeRequest request = fixture.Request({lit(fx.BEVEL_MAX_DEPTH)});",
    ):
        assert snippet in driver, snippet
    normal = cpp("normal_bake_cases.h")
    assert f'fixtures::Plane("normal_high", -2, 2, -2, 2, {lit(fx.PLANE_HIGH_Z)})' in normal
    assert 'const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);' in normal
    assert (
        f"request.detail.max_height = request.detail.max_depth = {lit(fx.PLANE_MAX_HEIGHT)};"
        in (normal)
    )
    thickness = cpp("thickness_bake_cases.h")
    half = lit(fx.SLAB_HALF, "")
    for snippet in (
        f'fixtures::Plane("top", -{half}, {half}, -{half}, {half}, {lit(fx.SLAB_TOP_Z)})',
        f'fixtures::Plane("bottom", -{half}, {half}, -{half}, {half}, {lit(fx.SLAB_BOTTOM_Z)}, '
        "true)",
        # The slab case authors its distances in inches; in mesh units they are 0.05.
        f"base.detail.max_height = base.detail.max_depth = {lit(fx.PLANE_MAX_DEPTH)} * 2.54f;",
    ):
        assert snippet in thickness, snippet


def test_committed_fixtures_match_their_generator() -> None:
    committed = sorted(p.name for p in fx.FIXTURE_DIR.iterdir())
    assert committed == sorted(fx.committed_fixtures())
    for name, data in fx.committed_fixtures().items():
        assert (fx.FIXTURE_DIR / name).read_bytes() == data, name


def read_obj(path: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Each object's positions (float32, per corner) and normals, from the committed file."""
    v: list[list[float]] = []
    vn: list[list[float]] = []
    objects: dict[str, list[tuple[int, int]]] = {}
    current = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        kind, *rest = line.split()
        if kind == "o":
            current = rest[0]
            objects[current] = []
        elif kind == "v":
            v.append([float(x) for x in rest])
        elif kind == "vn":
            vn.append([float(x) for x in rest])
        elif kind == "f":
            for corner in rest:
                vi, _, ni = corner.split("/")
                objects[current].append((int(vi) - 1, int(ni) - 1))
    return {
        name: (
            np.array([v[i] for i, _ in corners], np.float32),
            np.array([vn[n] for _, n in corners], np.float32),
        )
        for name, corners in objects.items()
    }


def test_obj_files_read_back_the_generator_float32_values() -> None:
    for fixture in fx.fixture_files():
        read = read_obj(fx.FIXTURE_DIR / fixture.file_name)
        assert list(read) == [mesh.name for mesh in fixture.objects]
        for mesh in fixture.objects:
            positions, normals = read[mesh.name]
            expected = np.array([mesh.positions[i] for i in mesh.indices], np.float32)
            assert np.array_equal(positions, expected), mesh.name
            assert np.array_equal(normals, [mesh.normals[i] for i in mesh.indices]), mesh.name


def test_fixture_shapes() -> None:
    files = {f.stem: f for f in fx.fixture_files()}
    (sphere,) = files["sphere-on-ground"].objects
    assert len(sphere.positions) == 8 * 8 * 4 + 25 * 49
    assert len(sphere.indices) // 3 == 8 * 8 * 2 + 24 * 48 * 2 - 2 * 48
    cube, knob, decoy = files["bevelled-cube-high"].objects
    assert len(cube.indices) // 3 == 6 * 2 + 12 * 2 + 8 and not cube.uvs
    # Outward and closed: every facet faces away from the origin, and every edge (by position)
    # is used once in each direction.
    p = np.array(cube.positions, np.float64)
    triangles = np.array(cube.indices).reshape(-1, 3)
    tri = p[triangles]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    assert (np.einsum("ij,ij->i", cross, tri.mean(axis=1)) > 0).all()
    keys = [tuple(cube.positions[i]) for i in range(len(cube.positions))]
    directed = [(keys[t[k]], keys[t[(k + 1) % 3]]) for t in triangles for k in range(3)]
    assert len(set(directed)) == len(directed)
    assert all((b, a) in set(directed) for a, b in directed)
    assert np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() > 0
    assert [m.name for m in (cube, knob, decoy)] == [
        "cube_high",
        "knob_high_ignorebf",
        "decoy_high",
    ]
    # At the requests' 512 px every island edge lies on a texel boundary.
    for low in files["bevelled-cube-low"].objects:
        for u, v in low.uvs:
            assert (u * rq.RESOLUTION).is_integer() and (v * rq.RESOLUTION).is_integer()


def test_committed_requests_match_the_generator() -> None:
    on_disk = sorted(p.name for p in rq.requests_dir().glob("*.json"))
    assert on_disk == sorted(f"{g.name}.json" for g in rq.GOLDENS)
    entry = current_envelope()
    for golden in rq.GOLDENS:
        path = rq.request_path(golden)
        committed = json.loads(path.read_text(encoding="utf-8"))
        assert committed == rq.manifest(golden), golden.name
        assert validation_errors(committed, Schema.GOLDEN_PUBLIC) == []
        assert committed["software"]["painter"]["build_id"] == entry["painter_build"]
        assert golden.task in committed["description"]
        assert (REPO_ROOT / ".rulebook" / "tasks" / golden.task / "tasks.md").is_file()
        job = load_job(path)
        assert [s.call for s in job.state_steps][-2:] == [
            "substance_painter.baking.BakingParameters.set_enabled_bakers",
            "substance_painter.baking.bake_async",
        ]
        assert len(job.exports) == 2


def test_every_fixture_file_is_declared_by_a_request() -> None:
    declared = {
        (item["path"], item["sha256"])
        for golden in rq.GOLDENS
        for item in rq.manifest(golden)["inputs"]
    }
    for name in fx.committed_fixtures():
        path = fx.FIXTURE_DIR / name
        relative = path.relative_to(REPO_ROOT).as_posix()
        assert (relative, sha256_file(path)) in declared, name


def test_the_requests_sweep_what_the_tasks_name() -> None:
    by_task: dict[str, set[str]] = {}
    for golden in rq.GOLDENS:
        by_task.setdefault(golden.task, set()).add(golden.scene)
    analytic = set(rq.ANALYTIC)
    for task in ("normal", "ao", "curvature", "position", "id", "world-space-normal"):
        prefix = "phase3.2_baker-" if task == "normal" else "phase3.4_baker-"
        assert by_task[prefix + task] == analytic
    assert by_task["phase3.4_baker-thickness"] == {"slab", "sphere", "bevelled-cube"}
    names = {g.name for g in rq.GOLDENS}
    assert {f"ao-{s}-{v}" for s in analytic for v in ("ground-plane", "no-ground-plane")} <= names
    assert {f"curvature-{s}-{m}" for s in analytic for m in ("from-mesh", "from-normal-map")} <= (
        names
    )
    assert len([n for n in names if n.startswith("position-")]) == 3 * (3 * 2 + 3)
    assert len([n for n in names if n.startswith("thickness-")]) == 3 * 3
    assert len([n for n in names if n.startswith("id-")]) == 3 * 3
