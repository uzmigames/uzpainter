"""Mesh importers (phase1.4_mesh-importers, items 3.1-3.9; `docs/architecture/12-mesh-import.md`
§1-§3, §6, §8).

`uzp-mesh-tests.exe` (`tests/mesh/mesh_test.cpp`, `zig build mesh-tests`) holds the native cases
and imports files on request; these tests write the fixtures (`tests/mesh/mesh_fixtures.py`),
run it and check its reports. No GPU is involved: everything runs on the CPU lane.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.mesh.mesh_fixtures import (
    FbxGeometry,
    FbxModel,
    GltfNode,
    Primitive,
    fbx_ascii,
    gltf_document,
    obj_reference_hashes,
    png_rgba8,
    write_glb,
    write_gltf,
)
from tools.parity.polygon_triangulation.core import (
    SEMANTICS_PATH,
    OracleUnavailable,
    oracle_recordings,
    run_study,
    semantics_document,
    status,
    uzpainter_triangulations,
)
from tools.parity.schemas import load_json
from tools.parity.store.store import locate

REPO_ROOT = Path(__file__).resolve().parents[2]

NATIVE_CASES = (
    "auto_unwrap_rejected_first",
    "certificate_defects",
    "certificate_in_report",
    "coincident_opposite_faces",
    "fan_triangulation",
    "formats",
    "hard_edge",
    "hashes_separate_concerns",
    "mirrored_uvs",
    "obj_missing_attributes",
    "obj_negative_indices",
    "obj_objects_and_materials",
    "obj_parse_errors",
    "tangent_frame_rules",
    "texel_convention",
    "units",
    "uv_metrics_two_islands",
    "uv_tiles",
)

QUAD_POSITIONS = [(-1.0, 0.0, -1.0), (1.0, 0.0, -1.0), (1.0, 0.0, 1.0), (-1.0, 0.0, 1.0)]
QUAD_UVS = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]  # v grows upwards


@pytest.fixture(scope="session")
def mesh_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-mesh-tests.exe` of a fresh `zig build mesh-tests`."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-mesh-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("uzp-mesh-tests")
    build = subprocess.run(
        [zig, "build", "mesh-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-mesh-tests.exe"


def _run(exe: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(exe), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def imported(exe: Path, path: Path, *options: str) -> dict[str, Any]:
    """`{"mesh": {positions, corners, objects}, "report": ...}` of an accepted import."""
    proc = _run(exe, "import", str(path), *options)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result: dict[str, Any] = json.loads(proc.stdout)
    return result


def refused(exe: Path, path: Path, *options: str) -> tuple[str, str, dict[str, Any]]:
    """The error class, message and details of a refused import."""
    proc = _run(exe, "import", str(path), *options)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    first, details = proc.stderr.strip().split("\n", 1)
    error_class, message = first.split(": ", 1)
    parsed: dict[str, Any] = json.loads(details)
    return error_class, message, parsed


def project(exe: Path, path: Path, *options: str) -> tuple[int, dict[str, Any]]:
    """Exit code and output of an import into a new document in one transaction."""
    proc = _run(exe, "project", str(path), *options)
    assert proc.returncode in (0, 3), proc.stdout + proc.stderr
    result: dict[str, Any] = json.loads(proc.stdout)
    return proc.returncode, result


def _obj(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_native_cases(mesh_tests: Path) -> None:
    proc = _run(mesh_tests, "run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sorted(line.split()[1] for line in proc.stdout.splitlines()) == sorted(NATIVE_CASES)
    assert all(line.startswith("PASS ") for line in proc.stdout.splitlines())


# ---------------------------------------------------------------------------------------------
# 3.1 Corner preservation


# Triangulated low-poly body: hard edges, a duplicated and an unused position, two materials.
CORNER_FIXTURE = """o Body
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 0 1 0
v 9 9 9
v 0.5 0.5 1
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vt 0.5 0.5
vn 0 0 1
vn 0 0 -1
vn 0.70710678 0 0.70710678
vn 0 0.6 0.8
usemtl M_skin
f 1/1/1 2/2/1 3/3/1
f 1/1/2 3/3/2 4/4/2
usemtl M_cloth
f 2/2/3 7/5/3 3/3/4
f 5/4/4 3/3/3 7/5/4
usemtl M_skin
f 4/4/1 1/1/1 7/5/2
"""


def _corner_tuples(text: str) -> list[tuple[int, tuple[float, ...], tuple[float, ...]]]:
    """(position id, normal, uv) of every face reference, as written."""
    v_count, vts, vns = 0, [], []
    corners = []
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "v":
            v_count += 1
        elif parts[0] == "vt":
            vts.append(tuple(float(x) for x in parts[1:3]))
        elif parts[0] == "vn":
            vns.append(tuple(float(x) for x in parts[1:4]))
        elif parts[0] == "f":
            for ref in parts[1:]:
                p, t, n = (int(x) for x in ref.split("/"))
                corners.append((p - 1, vns[n - 1], vts[t - 1]))
    return corners


def test_corner_preservation(mesh_tests: Path, tmp_path: Path) -> None:
    """Corners, winding, corner normals, UVs and materials are kept exactly; the five hashes
    equal those computed from the source text; positions are neither welded nor compacted."""
    path = _obj(tmp_path / "body.obj", CORNER_FIXTURE)
    result = imported(mesh_tests, path)
    report, mesh = result["report"], result["mesh"]
    assert report["hashes"] == obj_reference_hashes(CORNER_FIXTURE)
    assert report["counts"] == {
        "corners": 15,
        "materials": 2,
        "objects": 1,
        "positions": 7,
        "triangles": 5,
    }
    assert report["triangulation"] == {"ngons_triangulated": 0, "rule": "fan_from_last_corner"}
    expected = _corner_tuples(CORNER_FIXTURE)
    for corner, (position, normal, uv) in zip(mesh["corners"], expected, strict=True):
        assert corner["position"] == position
        assert corner["normal"] == pytest.approx(normal, abs=1e-7)
        assert corner["uv0"] == pytest.approx(uv, abs=1e-7)
    assert mesh["objects"] == [
        {"name": "Body", "triangles": [[3 * i, 3 * i + 1, 3 * i + 2] for i in range(5)]}
    ]
    assert [c["material"] for c in mesh["corners"]] == [0] * 6 + [1] * 6 + [0] * 3
    assert mesh["positions"][3] == mesh["positions"][4]  # duplicated, not welded
    assert report["materials"] == [{"index": 0, "name": "M_skin"}, {"index": 1, "name": "M_cloth"}]
    code, out = project(mesh_tests, path)
    assert code == 0 and out["result"]["status"] == "committed"
    assert [s["name"] for s in out["project"]["texture_sets"]] == ["M_skin", "M_cloth"]


# ---------------------------------------------------------------------------------------------
# 3.2 Negative indices


def test_negative_indices_equal_positive_twin(mesh_tests: Path, tmp_path: Path) -> None:
    positive = (
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nvn 0 0 1\nf 1/1/1 2/2/1 3/3/1\n"
        "v 0 1 0\nvt 0 1\nf 1/1/1 3/3/1 4/4/1\n"
    )
    negative = (
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nvn 0 0 1\n"
        "f -3/-3/-1 -2/-2/-1 -1/-1/-1\n"
        "v 0 1 0\nvt 0 1\nf -4/-4/-1 -2/-2/-1 -1/-1/-1\n"
    )
    a = imported(mesh_tests, _obj(tmp_path / "positive.obj", positive))
    b = imported(mesh_tests, _obj(tmp_path / "negative.obj", negative))
    assert a["mesh"] == b["mesh"]
    assert a["report"]["hashes"] == b["report"]["hashes"] == obj_reference_hashes(positive)


# ---------------------------------------------------------------------------------------------
# 3.3 N-gons


def test_ngons_fan_triangulated_and_flagged(mesh_tests: Path, tmp_path: Path) -> None:
    text = (
        "v 0 0 0\nv 1 0 0\nv 2 0.5 0\nv 1 1 0\nv 0 1 0\nv 3 0 0\nf 1 2 3 4 5\nf 2 6 3\nf 1 2 4 5\n"
    )
    result = imported(mesh_tests, _obj(tmp_path / "ngons.obj", text))
    assert result["report"]["triangulation"] == {
        "ngons_triangulated": 2,
        "rule": "fan_from_last_corner",
    }
    assert result["mesh"]["objects"][0]["triangles"] == [
        [0, 1, 4],
        [1, 2, 4],
        [2, 3, 4],
        [5, 6, 7],
        [8, 9, 11],
        [9, 10, 11],
    ]
    assert result["report"]["hashes"] == obj_reference_hashes(text)

    quad = FbxGeometry(100, "Quad", QUAD_POSITIONS, [[0, 1, 2, 3]], uvs=QUAD_UVS)
    fbx = tmp_path / "quad.fbx"
    fbx.write_text(fbx_ascii([quad], [FbxModel(200, "Quad", 100)], {}), encoding="utf-8")
    fbx_result = imported(mesh_tests, fbx)
    assert fbx_result["report"]["triangulation"]["ngons_triangulated"] == 1
    assert fbx_result["mesh"]["objects"][0]["triangles"] == [[0, 1, 3], [1, 2, 3]]
    assert fbx_result["report"]["flags"]["corners_without_normal"] == 4


# ---------------------------------------------------------------------------------------------
# 3.4 Duplicate material names


def _triangle_primitive(material: int, x: float) -> Primitive:
    return Primitive(
        positions=[(x, 0.0, 0.0), (x + 1.0, 0.0, 0.0), (x, 1.0, 0.0)],
        indices=[0, 1, 2],
        normals=[(0.0, 0.0, 1.0)] * 3,
        uvs=[(0.1, 0.9), (0.9, 0.9), (0.1, 0.1)],
        material=material,
    )


def test_duplicate_material_names(mesh_tests: Path, tmp_path: Path) -> None:
    document, blob = gltf_document(
        [[_triangle_primitive(0, 0.0), _triangle_primitive(1, 2.0), _triangle_primitive(2, 4.0)]],
        [GltfNode("Body", mesh=0)],
        ["M_body", "M_body", "M_trim"],
        [0],
    )
    path = write_gltf(tmp_path / "duplicates.gltf", document, blob)
    error_class, message, details = refused(mesh_tests, path)
    assert error_class == "DuplicateMaterialNames"
    assert "'M_body' (materials 0 1)" in message
    assert details == {"duplicates": {"M_body": [0, 1]}}
    code, out = project(mesh_tests, path)
    assert code == 3
    assert out["project"]["texture_sets"] == [] and out["project"]["revision"] == 0
    assert out["project"]["mesh"] is None and out["project"]["resources"] == {}

    merged = imported(mesh_tests, path, "--allow-duplicate-material-names")["report"]
    assert merged["materials"] == [{"index": 0, "name": "M_body"}, {"index": 1, "name": "M_trim"}]
    assert merged["merged_materials"] == [{"merged_indices": [0, 1], "name": "M_body"}]
    code, out = project(mesh_tests, path, "--allow-duplicate-material-names")
    assert code == 0
    assert [s["name"] for s in out["project"]["texture_sets"]] == ["M_body", "M_trim"]

    # FBX: two Material objects named alike are two materials.
    geometry = FbxGeometry(
        100,
        "Body",
        QUAD_POSITIONS,
        [[0, 1, 2], [0, 2, 3]],
        uvs=[*QUAD_UVS[:3], QUAD_UVS[0], QUAD_UVS[2], QUAD_UVS[3]],
        polygon_materials=[0, 1],
    )
    fbx = tmp_path / "duplicates.fbx"
    fbx.write_text(
        fbx_ascii(
            [geometry], [FbxModel(200, "Body", 100, materials=[300, 301])], {300: "M", 301: "M"}
        ),
        encoding="utf-8",
    )
    assert refused(mesh_tests, fbx)[0] == "DuplicateMaterialNames"
    assert imported(mesh_tests, fbx, "--allow-duplicate-material-names")["report"]["materials"] == [
        {"index": 0, "name": "M"}
    ]


# ---------------------------------------------------------------------------------------------
# 3.5 Instances and transforms


def test_instances_and_transforms_gltf(mesh_tests: Path, tmp_path: Path) -> None:
    document, blob = gltf_document(
        [[_triangle_primitive(0, 0.0)]],
        [
            GltfNode("A", mesh=0, translation=(1.0, 0.0, 0.0)),
            GltfNode("Parent", translation=(0.0, 2.0, 0.0), scale=(2.0, 2.0, 2.0), children=[2]),
            GltfNode("B", mesh=0, translation=(0.0, 0.0, 3.0)),
        ],
        ["M"],
        [0, 1],
    )
    for path in (
        write_gltf(tmp_path / "instances.gltf", document, blob),
        write_glb(tmp_path / "instances.glb", document, blob),
    ):
        result = imported(mesh_tests, path)
        report = result["report"]
        assert [o["name"] for o in report["objects"]] == ["A", "B"]
        assert report["objects"][0]["transform"] == [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 1]
        # Parent (T(0,2,0) S(2)) * B (T(0,0,3)): translation (0, 2, 6), scale 2.
        assert report["objects"][1]["transform"] == [2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0, 0, 2, 6, 1]
        assert report["counts"]["positions"] == 3  # the instanced mesh's positions once
        assert report["counts"]["corners"] == 6 and report["counts"]["triangles"] == 2
        assert report["flags"]["v_flip"] is True and report["flags"]["uv_set"] == "TEXCOORD_0"
        assert result["mesh"]["corners"][0]["uv0"] == pytest.approx([0.1, 0.1])
    gltf = imported(mesh_tests, tmp_path / "instances.gltf")
    assert (
        imported(mesh_tests, tmp_path / "instances.glb")["report"]["hashes"]
        == gltf["report"]["hashes"]
    )


def test_instances_and_transforms_fbx(mesh_tests: Path, tmp_path: Path) -> None:
    geometry = FbxGeometry(
        100,
        "Tri",
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        [[0, 1, 2]],
        normals=[(0.0, 0.0, 1.0)] * 3,
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        polygon_materials=[0],
    )
    models = [
        FbxModel(200, "A", 100, translation=(10.0, 0.0, 0.0), materials=[300]),
        FbxModel(201, "B", 100, translation=(0.0, 5.0, 0.0), materials=[300]),
    ]
    path = tmp_path / "instances.fbx"
    path.write_text(fbx_ascii([geometry], models, {300: "M"}), encoding="utf-8")
    report = imported(mesh_tests, path)["report"]
    assert [o["name"] for o in report["objects"]] == ["A", "B"]
    assert report["objects"][0]["transform"][12:15] == [10, 0, 0]
    assert report["objects"][1]["transform"][12:15] == [0, 5, 0]
    assert report["counts"]["positions"] == 3 and report["counts"]["corners"] == 6
    assert report["flags"]["corners_without_normal"] == 0 and report["flags"]["v_flip"] is False
    assert report["materials"] == [{"index": 0, "name": "M"}]


# ---------------------------------------------------------------------------------------------
# 3.6 Units


def _fbx_triangle(path: Path, unit_scale_factor: float) -> Path:
    geometry = FbxGeometry(
        100, "Tri", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [[0, 1, 2]]
    )
    path.write_text(
        fbx_ascii([geometry], [FbxModel(200, "Tri", 100)], {}, unit_scale_factor=unit_scale_factor),
        encoding="utf-8",
    )
    return path


def test_units(mesh_tests: Path, tmp_path: Path) -> None:
    centimetres = _fbx_triangle(tmp_path / "cm.fbx", 1.0)
    metres = _fbx_triangle(tmp_path / "m.fbx", 100.0)
    cm = imported(mesh_tests, centimetres)["report"]["units"]
    assert cm == {
        "from": "file",
        "requested_mesh_unit_scale": None,
        "scale_to_internal": pytest.approx(1.0),
        "source": "centimeter",
        "source_meters_per_unit": pytest.approx(0.01),
    }
    m = imported(mesh_tests, metres)["report"]["units"]
    assert m["source"] == "meter" and m["scale_to_internal"] == pytest.approx(100.0)
    assert (
        imported(mesh_tests, metres, "--mesh-unit-scale", "0")["report"]["units"]["from"] == "file"
    )
    override = imported(mesh_tests, metres, "--mesh-unit-scale", "2.54")["report"]["units"]
    assert override["from"] == "mesh_unit_scale" and override["scale_to_internal"] == 2.54
    assert override["requested_mesh_unit_scale"] == 2.54 and override["source"] == "meter"

    document, blob = gltf_document(
        [[_triangle_primitive(0, 0.0)]], [GltfNode("T", mesh=0)], ["M"], [0]
    )
    gltf = imported(mesh_tests, write_gltf(tmp_path / "t.gltf", document, blob))["report"]["units"]
    assert gltf["source"] == "meter" and gltf["scale_to_internal"] == 100.0
    obj = imported(mesh_tests, _obj(tmp_path / "t.obj", "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"))
    assert obj["report"]["units"]["source"] == "unspecified"
    assert obj["report"]["units"]["source_meters_per_unit"] is None
    assert obj["report"]["units"]["scale_to_internal"] == 1.0


# ---------------------------------------------------------------------------------------------
# 3.7 Multi-set body


def test_multi_set_body_three_texture_sets_in_file_order(mesh_tests: Path, tmp_path: Path) -> None:
    text = (
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nvn 0 0 1\n"
        "o Body\nusemtl M_body\nf 1/1/1 2/2/1 3/3/1\n"
        "o Belt\nusemtl M_trim\nf 1/1/1 3/3/1 4/4/1\n"
        "o Body\nusemtl M_body\nf 1/1/1 2/2/1 4/4/1\n"
        "o Buckle\nusemtl M_buckle\nf 2/2/1 3/3/1 4/4/1\n"
    )
    path = _obj(tmp_path / "body.obj", text)
    code, out = project(mesh_tests, path)
    assert code == 0 and out["result"]["status"] == "committed"
    sets = out["project"]["texture_sets"]
    assert [s["name"] for s in sets] == ["M_body", "M_trim", "M_buckle"]
    assert [s["original_name"] for s in sets] == ["M_body", "M_trim", "M_buckle"]
    assert all(s["uv_tiles"] == 1 and s["stacks"] == 1 for s in sets)
    assert sets[0]["id"] < sets[1]["id"] < sets[2]["id"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert out["project"]["mesh"] == {"resource": digest}
    assert out["project"]["resources"] == {
        digest: [
            {"mime": "model/obj", "name": "body.obj", "size": path.stat().st_size, "usage": "mesh"}
        ]
    }
    # Material identity is separate from object identity: the objects follow the `o` sections
    # (Body twice), the texture sets the materials.
    assert [o["name"] for o in out["report"]["objects"]] == ["Body", "Belt", "Body", "Buckle"]


# ---------------------------------------------------------------------------------------------
# 3.8 Directional orientation (INT-12)


RED, GREEN, BLUE, BLACK = (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (0, 0, 0, 255)


def test_directional_orientation(mesh_tests: Path, tmp_path: Path) -> None:
    """An asymmetric mask (red top-left, green top-right, blue bottom-left) lands at the mesh
    corners whose geometry is top-left (-x, -z), top-right (+x, -z) and bottom-left (-x, +z) of a
    plane seen from +y with -z up, for OBJ (v up) and glTF (v down, flipped on import) alike."""
    pixels = [[BLACK] * 4 for _ in range(4)]
    pixels[0][0], pixels[0][3], pixels[3][0] = RED, GREEN, BLUE
    mask = tmp_path / "M_orientation.png"
    mask.write_bytes(png_rgba8(4, 4, pixels))
    expected = {(-1.0, -1.0): RED, (1.0, -1.0): GREEN, (-1.0, 1.0): BLUE, (1.0, 1.0): BLACK}

    obj = _obj(
        tmp_path / "plane.obj",
        "".join(f"v {x} {y} {z}\n" for x, y, z in QUAD_POSITIONS)
        + "".join(f"vt {u} {v}\n" for u, v in QUAD_UVS)
        + "vn 0 1 0\nf 1/1/1 4/4/1 3/3/1\nf 1/1/1 3/3/1 2/2/1\n",
    )
    document, blob = gltf_document(
        [
            [
                Primitive(
                    positions=QUAD_POSITIONS,
                    indices=[0, 3, 2, 0, 2, 1],
                    normals=[(0.0, 1.0, 0.0)] * 4,
                    uvs=[(u, 1.0 - v) for u, v in QUAD_UVS],
                    material=0,
                )
            ]
        ],
        [GltfNode("Plane", mesh=0)],
        ["M"],
        [0],
    )
    gltf = write_gltf(tmp_path / "plane.gltf", document, blob)
    for path in (obj, gltf):
        mesh = imported(mesh_tests, path)["mesh"]
        seen = set()
        for corner in mesh["corners"]:
            x, _, z = mesh["positions"][corner["position"]]
            u, v = corner["uv0"]
            proc = _run(mesh_tests, "texel", str(mask), repr(u), repr(v))
            assert proc.returncode == 0, proc.stderr
            texel = json.loads(proc.stdout)
            assert tuple(c // 257 for c in texel["rgba"]) == expected[(x, z)], (path.name, x, z)
            seen.add((x, z))
        assert seen == set(expected)


# ---------------------------------------------------------------------------------------------
# 3.9 Refusals


def test_uvs_outside_tile_refused_with_tile_list(mesh_tests: Path, tmp_path: Path) -> None:
    path = _obj(
        tmp_path / "udim.obj",
        "v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0.1 0.1\nvt 0.9 0.1\nvt 0.1 0.9\n"
        "vt 1.1 0.1\nvt 1.9 0.1\nvt 1.1 0.9\n"
        "f 1/1 2/2 3/3\nf 1/4 2/5 3/6\n",
    )
    error_class, message, details = refused(mesh_tests, path)
    assert error_class == "UVOutsideTile"
    assert "1002" in message
    assert details == {"tiles": [1002], "triangles_outside": 1}
    code, out = project(mesh_tests, path)
    assert code == 3 and out["project"]["texture_sets"] == [] and out["project"]["revision"] == 0


def test_release_gaps_and_auto_unwrap(mesh_tests: Path, tmp_path: Path) -> None:
    dae = tmp_path / "mesh.dae"
    dae.write_text("<COLLADA/>", encoding="utf-8")
    error_class, message, details = refused(mesh_tests, dae)
    assert error_class == "ReleaseGap" and "release gap" in message and details == {"format": "dae"}
    for ext in ("ply", "usd", "usdz"):
        other = tmp_path / f"mesh.{ext}"
        other.write_bytes(b"\0")
        assert refused(mesh_tests, other)[0] == "ReleaseGap"
    stl = tmp_path / "mesh.stl"
    stl.write_bytes(b"\0")
    assert refused(mesh_tests, stl)[0] == "UnsupportedFormat"

    obj = _obj(tmp_path / "t.obj", "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    error_class, _, details = refused(mesh_tests, obj, "--auto-unwrap", '{"padding":8}')
    assert error_class == "NotYetSupported" and details == {"auto_unwrap": {"padding": 8}}


# ---------------------------------------------------------------------------------------------
# Recorded, not used: extra UV sets and stored tangents (12 §2)


def test_gltf_extra_uv_sets_and_stored_tangents_recorded(mesh_tests: Path, tmp_path: Path) -> None:
    primitive = _triangle_primitive(0, 0.0)
    primitive.extra_texcoords = 2
    primitive.tangents = [(1.0, 0.0, 0.0, 1.0)] * 3
    document, blob = gltf_document([[primitive]], [GltfNode("T", mesh=0)], ["M"], [0])
    flags = imported(mesh_tests, write_gltf(tmp_path / "t.gltf", document, blob))["report"]["flags"]
    assert flags["ignored_uv_sets"] == ["TEXCOORD_1", "TEXCOORD_2"]
    assert flags["stored_tangents"] == 3 and flags["uv_set"] == "TEXCOORD_0"


# ---------------------------------------------------------------------------------------------
# 3.3 Tier 0: polygon triangulation against Painter (private oracle, owner's machine)


def test_tier0_polygon_triangulation_equals_painter(mesh_tests: Path) -> None:
    """The production importer splits every polygon of the Tier 0 fixture as Painter 12.1.0 did,
    and the comparison reproduces `parity/semantics/polygon-triangulation.json`."""
    maps = None
    try:
        maps = oracle_recordings(locate())
    except OracleUnavailable as error:
        pytest.skip(f"oracle_unavailable (no store, decision 028): {error}")
    study = run_study(maps, uzpainter_triangulations(mesh_tests))
    assert status(study) == "exact"
    assert semantics_document(study) == load_json(SEMANTICS_PATH)
