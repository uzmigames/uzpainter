"""The Sash v5 low exporter on a tiny authored scene, with no Blender (decision 300 item 7).

The "scene" is a two-triangle quad described with plain objects that carry the attribute names
`sash_low_blender` reads from Blender (`vertices`, `loops`, `loop_triangles`, `uv_layers`,
`corner_normals`, `modifiers`, `matrix_world`, `material_slots`). The "Blender" of the host tests
is a Python function that writes what the Blender side would write, from the same authored
table. Nothing here opens the Sash `.blend`, runs Blender or claims anything about the real low:
the real export has not run yet.

Test limit: the OBJ and MTL texts are authored in the layout Blender's exporter is expected to
write; the first real run is what confirms that layout and the operator's option list.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import stat
import struct
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import pytest

from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore
from tools.parity.tier1 import sash_low_blender as side
from tools.parity.tier1 import sash_low_export as host
from tools.parity.tier1.sash_low_blender import ExportError, TriangleTable

IDENTITY = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
POSITIONS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.5), (0.0, 1.0, 0.25)]
LOOP_VERTICES = [0, 1, 2, 0, 2, 3]
TRIANGLES = [((0, 1, 2), (0, 1, 2)), ((0, 2, 3), (3, 4, 5))]
# Corners 0 and 3 share vertex 0 with different UVs and normals: per loop, never per vertex.
UVS = [(0.1, 0.2), (0.6, 0.2), (0.6, 0.9), (0.15, 0.25), (0.6, 0.9), (0.1, 0.9)]
NORMALS = [(0.0, 0.0, 1.0), (0.0, 0.6, 0.8), (0.0, 0.0, 1.0), (0.6, 0.0, 0.8)] + [
    (0.0, 0.0, 1.0)
] * 2


def authored_mesh(**changes: Any) -> NS:
    parts: dict[str, Any] = {
        "vertices": [NS(co=co) for co in POSITIONS],
        "loops": [NS(vertex_index=v) for v in LOOP_VERTICES],
        "loop_triangles": [NS(vertices=v, loops=lo) for v, lo in TRIANGLES],
        "uv_layers": {side.UV_MAP: NS(data=[NS(uv=uv) for uv in UVS])},
        "corner_normals": [NS(vector=n) for n in NORMALS],
    }
    parts.update(changes)
    return NS(**parts)


def authored_object(**changes: Any) -> NS:
    parts: dict[str, Any] = {
        "name": side.SOURCE_OBJECT,
        "type": "MESH",
        "modifiers": [],
        "matrix_world": IDENTITY,
        "material_slots": [NS(material=NS(name=name)) for name in side.SOURCE_MATERIALS],
        "data": NS(shape_keys=None, uv_layers={side.UV_MAP: NS()}),
    }
    parts.update(changes)
    return NS(**parts)


def matrix(diagonal: Sequence[float], translation: Sequence[float] = (0.0, 0.0, 0.0)) -> list[Any]:
    rows = [[0.0] * 4 for _ in range(4)]
    for i, value in enumerate(diagonal):
        rows[i][i] = value
    for i, value in enumerate(translation):
        rows[i][3] = value
    rows[3][3] = 1.0
    return rows


def table() -> TriangleTable:
    return side.triangle_table(authored_mesh(), side.UV_MAP)


# --- selection --------------------------------------------------------------------------------


def test_the_pinned_source_object_passes() -> None:
    assert side.source_problems(authored_object()) == []


@pytest.mark.parametrize(
    "world",
    [
        matrix((2.0, 1.0, 1.0)),  # non-uniform scale: normals would need the inverse-transpose
        matrix((-1.0, 1.0, 1.0)),  # negative determinant: winding would need flipping
        matrix((1.0, 1.0, 1.0), (0.0, 0.0, 0.5)),  # translation
        [[0.0, -1.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0, 0, 0, 1.0]],
    ],
    ids=["non-uniform", "mirrored", "translated", "rotated"],
)
def test_any_world_matrix_but_identity_is_refused(world: list[Any]) -> None:
    problems = side.source_problems(authored_object(matrix_world=world))
    assert len(problems) == 1
    assert "only the exact identity is admitted" in problems[0]


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"type": "CURVE"}, "not a MESH"),
        ({"modifiers": [NS(name="Triangulate", type="TRIANGULATE")]}, "modifier stack"),
        ({"material_slots": [NS(material=NS(name="25-Faixa-Cintura"))]}, "material slots"),
        ({"material_slots": [NS(material=None)]}, "material slots"),
        ({"data": NS(shape_keys=NS(), uv_layers={side.UV_MAP: NS()})}, "shape keys"),
        ({"data": NS(shape_keys=None, uv_layers={"UVMap.001": NS()})}, "no UV map"),
    ],
)
def test_source_mismatches_are_refused(changes: dict[str, Any], fragment: str) -> None:
    problems = side.source_problems(authored_object(**changes))
    assert any(fragment in problem for problem in problems), problems


def test_every_operator_option_is_pinned() -> None:
    browser = ["filepath", "check_existing", "filter_glob", "filter_folder", "display_type"]
    available = [*side.OBJ_EXPORT_OPTIONS, *browser, "rna_type"]
    assert side.option_problems(available, side.OBJ_EXPORT_OPTIONS) == []
    assert side.option_problems([*available, "export_new_option"], side.OBJ_EXPORT_OPTIONS) == [
        "wm.obj_export option 'export_new_option' is not pinned"
    ]
    missing = [name for name in available if name != "apply_transform"]
    assert side.option_problems(missing, side.OBJ_EXPORT_OPTIONS) == [
        "pinned option 'apply_transform' is not an option of wm.obj_export"
    ]


def test_the_pins_fix_axes_and_texture_free_export() -> None:
    options = side.OBJ_EXPORT_OPTIONS
    assert (options["forward_axis"], options["up_axis"]) == ("NEGATIVE_Z", "Y")
    assert options["path_mode"] == "STRIP"
    assert options["apply_modifiers"] is False and options["export_triangulated_mesh"] is False
    assert side.to_obj_axes((1.0, 2.0, 3.0)) == (1.0, 3.0, -2.0)


def test_the_blender_side_is_self_contained() -> None:
    """Blender runs the file directly: it imports only the standard library, and bpy only inside
    `main`, so the host and these tests import it without Blender."""
    text = Path(side.__file__).read_text(encoding="utf-8")
    top: set[str] = set()
    for node in ast.parse(text).body:
        if isinstance(node, ast.Import):
            top |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            top.add(node.module.split(".")[0])
    standard = {"__future__", "hashlib", "json", "math", "struct", "sys", "collections"}
    assert top <= standard | {"dataclasses", "pathlib", "typing"}
    assert "save_mainfile" not in text and "save_as_mainfile" not in text


# --- the evaluated table ----------------------------------------------------------------------


def test_uvs_and_normals_are_taken_per_loop() -> None:
    read = table()
    assert read.triangles == ((0, 1, 2), (0, 2, 3))
    assert read.loops == ((0, 1, 2), (3, 4, 5))
    assert read.uv[3] == (0.15, 0.25) and read.uv[0] == (0.1, 0.2)
    assert read.normals[3] == (0.6, 0.0, 0.8) and read.normals[0] == (0.0, 0.0, 1.0)


def test_digests_follow_the_documented_serialisation() -> None:
    def sha(fmt: str, rows: Sequence[Sequence[float]]) -> str:
        return hashlib.sha256(b"".join(struct.pack(fmt, *row) for row in rows)).hexdigest()

    corners = [0, 1, 2, 3, 4, 5]
    assert side.table_digests(table()) == {
        "positions": sha("<3f", POSITIONS),
        "triangulation": sha("<3I", [(0, 1, 2), (0, 2, 3)]),
        "corner_uv": sha("<2f", [UVS[c] for c in corners]),
        "corner_normals": sha("<3f", [NORMALS[c] for c in corners]),
    }


def test_one_changed_uv_changes_only_its_digest() -> None:
    changed = list(UVS)
    changed[4] = (0.6, 0.8)
    mesh = authored_mesh(uv_layers={side.UV_MAP: NS(data=[NS(uv=uv) for uv in changed])})
    before, after = (
        side.table_digests(table()),
        side.table_digests(side.triangle_table(mesh, "UVMap")),
    )
    assert {name for name in before if before[name] != after[name]} == {"corner_uv"}


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"loops": [NS(vertex_index=v) for v in [0, 1, 2, 0, 3, 3]]}, "is not on vertex"),
        ({"uv_layers": {}}, "no UV map"),
        ({"corner_normals": [NS(vector=n) for n in NORMALS[:5]]}, "corner normals"),
        (
            {"vertices": [NS(co=(float("nan"), 0.0, 0.0))] + [NS(co=c) for c in POSITIONS[1:]]},
            "not 3 finite numbers",
        ),
        ({"loop_triangles": [NS(vertices=(0, 1, 2, 3), loops=(0, 1, 2, 3))]}, "not 3"),
    ],
)
def test_bad_evaluated_meshes_are_refused(changes: dict[str, Any], fragment: str) -> None:
    with pytest.raises(ExportError, match=fragment):
        side.triangle_table(authored_mesh(**changes), side.UV_MAP)


# --- the files Blender writes -----------------------------------------------------------------


def authored_report(run_dir: Path, read: TriangleTable | None = None) -> dict[str, Any]:
    blender = {"version": [5, 2, 0], "version_string": "5.2.0", "build_hash": "authored"}
    source = {
        "blend": str(run_dir / side.SOURCE_BLEND_NAME),
        "object": side.SOURCE_OBJECT,
        "materials": list(side.SOURCE_MATERIALS),
        "modifiers": [],
        "uv_map": side.UV_MAP,
        "uv_map_active": True,
        "depsgraph_mode": side.DEPSGRAPH_MODE,
    }
    return side.report_document(blender, source, read or table())


def exported(read: TriangleTable | None = None) -> tuple[side.Vec3, ...]:
    """The copy's corner normals per triangle corner; Blender's custom-normal re-encoding is not
    modelled, so they equal the evaluated ones here."""
    read = read or table()
    return tuple(read.normals[loop] for corner_loops in read.loops for loop in corner_loops)


def authored_obj(
    *,
    read: TriangleTable | None = None,
    axes: bool = True,
    flip_v: bool = False,
    moved: Mapping[int, side.Vec3] | None = None,
    swap_uv: bool = False,
    normal: side.Vec3 | None = None,
) -> str:
    """The layout Blender's OBJ exporter writes: header, mtllib, object, positions, normals and
    UVs (both deduplicated), smoothing, material, then faces as v/vt/vn. The keywords author one
    corruption each: unmapped axes, flipped V, a moved vertex inside the bounds, two corners'
    UVs swapped, or one corner pointing at a wrong (existing) normal."""
    read = read or table()
    corner_normals = exported(read)
    lines = ["# Blender 5.2.0", "# www.blender.org", f"mtllib {side.MTL_NAME}"]
    lines.append(f"o {side.EXPORT_OBJECT}")
    for i, p in enumerate(read.positions):
        p = (moved or {}).get(i, p)
        q = side.to_obj_axes(p) if axes else p
        lines.append("v {:.6f} {:.6f} {:.6f}".format(*q))
    normals = sorted({*corner_normals, *([normal] if normal else [])})
    lines += ["vn {:.4f} {:.4f} {:.4f}".format(*side.to_obj_axes(n)) for n in normals]
    uvs = sorted(set(read.uv))
    lines += [f"vt {u:.6f} {(1.0 - v) if flip_v else v:.6f}" for u, v in uvs]
    lines += ["s 1", f"usemtl {side.TEXTURE_SET}"]
    for k, (corner_vertices, corner_loops) in enumerate(
        zip(read.triangles, read.loops, strict=True)
    ):
        uv_index = [uvs.index(read.uv[lo]) + 1 for lo in corner_loops]
        normal_index = [normals.index(corner_normals[3 * k + c]) + 1 for c in range(3)]
        if swap_uv and k == 1:
            uv_index[0], uv_index[1] = uv_index[1], uv_index[0]
        if normal is not None and k == 1:
            normal_index[2] = normals.index(normal) + 1
        corners = [
            f"{v + 1}/{t}/{n}"
            for v, t, n in zip(corner_vertices, uv_index, normal_index, strict=True)
        ]
        lines.append("f " + " ".join(corners))
    return "\n".join(lines) + "\n"


def authored_mtl(*extra: str) -> str:
    return "\n".join(
        [
            f"# Blender 5.2.0 MTL File: '{side.SOURCE_BLEND_NAME}'",
            "# www.blender.org",
            "",
            f"newmtl {side.TEXTURE_SET}",
            "Ns 250.000000",
            "Kd 0.800000 0.800000 0.800000",
            "d 1.000000",
            "illum 2",
            *extra,
        ]
    )


@pytest.fixture
def two_triangles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(side, "TRIANGLES", 2)


@pytest.mark.usefixtures("two_triangles")
def test_the_authored_export_passes_every_check(tmp_path: Path) -> None:
    report = authored_report(tmp_path)
    assert host.report_problems(report, tmp_path / side.SOURCE_BLEND_NAME) == []
    assert host.table_problems(table(), report) == []
    assert host.obj_problems(authored_obj(), table(), exported()) == []
    assert host.mtl_problems(authored_mtl()) == []


def test_the_table_file_round_trips_and_must_match_the_report(tmp_path: Path) -> None:
    document = json.loads(json.dumps(side.table_document(table(), exported())))
    assert side.table_from_document(document) == (table(), exported())
    report = authored_report(tmp_path)
    report["mesh"]["digests"]["corner_uv"] = "0" * 64
    assert host.table_problems(table(), report) == ["the table's digests differ from the report's"]
    document["exported_normals"].pop()
    with pytest.raises(ExportError, match="disagree in count"):
        side.table_from_document(document)


def test_the_custom_normal_change_is_measured() -> None:
    assert host.max_normal_change(table(), exported()) == 0.0
    shifted = (*exported()[:-1], (0.0, 0.0, 0.99))
    assert host.max_normal_change(table(), shifted) == pytest.approx(0.01)


@pytest.mark.usefixtures("two_triangles")
@pytest.mark.parametrize(
    ("obj", "fragment"),
    [
        (authored_obj(axes=False), "OBJ positions differ"),
        (authored_obj(moved={3: (0.0, 1.0, 0.3)}), "OBJ positions differ"),
        (authored_obj(flip_v=True), "corner UV"),
        (authored_obj(swap_uv=True), "corner UV"),
        (authored_obj(normal=(1.0, 0.0, 0.0)), "corner normal"),
        (authored_obj().replace("usemtl 25-Faixa-Cintura", "usemtl other"), "usemtl"),
        (authored_obj().replace("o 25-Faixa-Cintura_low", "o a\no b"), "OBJ o"),
        (authored_obj() + "l 1 2\n", "unexpected 'l'"),
        (authored_obj() + "f 1/1/1 2/2/1 3/3/1 4/4/1\n", "faces"),
        (authored_obj().replace("/1 2/", "/ 2/", 1), "not v/vt/vn"),
        (authored_obj().replace("f 1/1/", "f 9/1/", 1), "out of range"),
        (authored_obj().replace("# Blender 5.2.0", "# Blender 4.2.0"), "header"),
    ],
    ids=[
        "unmapped-axes",
        "moved-inside-bounds",
        "flipped-v",
        "swapped-uv",
        "wrong-normal",
        "material",
        "objects",
        "lines",
        "quad",
        "corner",
        "range",
        "version",
    ],
)
def test_obj_mismatches_are_refused(obj: str, fragment: str) -> None:
    problems = host.obj_problems(obj, table(), exported())
    assert any(fragment in problem for problem in problems), problems


@pytest.mark.usefixtures("two_triangles")
def test_tolerances_accept_rounding_and_refuse_one_unit() -> None:
    positions = [(0.12345675, 0.9876543, 0.33333334), *POSITIONS[1:]]
    normals = [NORMALS[0], NORMALS[1], (0.57735026, 0.57735026, 0.57735026), *NORMALS[3:]]
    mesh = authored_mesh(
        vertices=[NS(co=c) for c in positions], corner_normals=[NS(vector=n) for n in normals]
    )
    read = side.triangle_table(mesh, side.UV_MAP)
    assert host.obj_problems(authored_obj(read=read), read, exported(read)) == []
    off_position = authored_obj(moved={1: (1.000001, 0.0, 0.0)})
    off_normal = authored_obj(normal=(0.0, 0.0001, 1.0))
    for text, fragment in ((off_position, "OBJ positions differ"), (off_normal, "corner normal")):
        problems = host.obj_problems(text, table(), exported())
        assert any(fragment in problem for problem in problems), problems


@pytest.mark.usefixtures("two_triangles")
def test_reordered_faces_are_refused() -> None:
    lines = authored_obj().splitlines()
    faces = [line for line in lines if line.startswith("f ")]
    reordered = [line for line in lines if not line.startswith("f ")] + faces[::-1]
    problems = host.obj_problems("\n".join(reordered), table(), exported())
    assert any("corner vertex" in problem for problem in problems), problems


def test_mtl_mismatches_are_refused() -> None:
    assert host.mtl_problems(authored_mtl("map_Kd C:/textures/base.png")) == [
        "the MTL names textures: ['map_Kd C:/textures/base.png']"
    ]
    assert "MTL materials" in host.mtl_problems(authored_mtl("newmtl second"))[0]


@pytest.mark.usefixtures("two_triangles")
def test_report_mismatches_are_refused(tmp_path: Path) -> None:
    copy = tmp_path / side.SOURCE_BLEND_NAME
    report = authored_report(tmp_path)
    report["export"]["options"] = {**side.OBJ_EXPORT_OPTIONS, "up_axis": "Z"}
    report["source"]["object"] = "25-Faixa-Cintura-v5-Low"
    problems = host.report_problems(report, copy)
    assert len(problems) == 2 and "options" in problems[1] and "object" in problems[0]
    del report["mesh"]
    assert host.report_problems(report, copy)[0].startswith("the report is malformed")


# --- the host run, with an authored Blender ---------------------------------------------------


@pytest.fixture
def setup(tmp_path: Path, two_triangles: None) -> dict[str, Any]:
    blend = b"BLENDER-v405 authored stand-in, not a real .blend"
    pin = host.SourcePin(
        "sash-v5-blend",
        "Models3D/" + side.SOURCE_BLEND_NAME,
        hashlib.sha256(blend).hexdigest(),
        len(blend),
    )
    assets = tmp_path / "assets"
    (assets / "Models3D").mkdir(parents=True)
    (assets / pin.assets3d_path).write_bytes(blend)
    exe = tmp_path / "blender.exe"
    exe.write_bytes(b"authored executable")
    return {
        "pin": pin,
        "assets": assets,
        "exe": exe,
        "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
        "work": tmp_path / "work",
        "blend": blend,
    }


def plan(setup: Mapping[str, Any], run: str = "r1", **changes: Any) -> host.Plan:
    arguments: dict[str, Any] = {
        "source_pin": setup["pin"],
        "blender_sha256": setup["exe_sha256"],
        "work": setup["work"],
    }
    arguments.update(changes)
    return host.plan_export(
        setup["exe"], run, setup["assets"], arguments.pop("store", None), **arguments
    )


def fake_blender(extra: str | None = None, code: int = 0, touch_copy: bool = False) -> host.Runner:
    def run(command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path) -> int:
        assert command[-2:] == ("--", str(cwd))
        assert env["TEMP"] == env["TMP"] == env["TMPDIR"] == str(cwd)
        copy = cwd / side.SOURCE_BLEND_NAME
        assert command[command.index("--python") - 3] == str(copy)
        assert not os.access(copy, os.W_OK)  # opened read-only
        log.write_bytes(b"authored log\n")
        (cwd / side.REPORT_NAME).write_text(json.dumps(authored_report(cwd)), encoding="utf-8")
        document = side.table_document(table(), exported())
        (cwd / side.TABLE_NAME).write_text(json.dumps(document), encoding="utf-8")
        (cwd / side.OBJ_NAME).write_text(authored_obj(), encoding="utf-8")
        (cwd / side.MTL_NAME).write_text(authored_mtl(), encoding="utf-8")
        if extra is not None:
            (cwd / extra).write_bytes(b"")
        if touch_copy:
            os.chmod(copy, stat.S_IWRITE | stat.S_IREAD)
            copy.write_bytes(b"saved")
        return code

    return run


def test_a_run_records_its_outputs_and_a_repeat_reproduces_them(setup: dict[str, Any]) -> None:
    first = host.run_export(plan(setup), fake_blender())
    run_dir = setup["work"] / "r1"
    assert json.loads((run_dir / host.RECORD_NAME).read_text(encoding="utf-8")) == first
    obj = (run_dir / side.OBJ_NAME).read_bytes()
    assert first["outputs"]["obj"]["sha256"] == hashlib.sha256(obj).hexdigest()
    assert first["source"]["resolved_from"] == "assets3d"
    assert first["source"]["copy_sha256_after"] == setup["pin"].sha256
    assert first["script"]["donor"]["sha256"] == side.DONOR_SHA256
    assert (setup["assets"] / setup["pin"].assets3d_path).read_bytes() == setup["blend"]
    repeat = host.run_export(plan(setup, "r1-repeat"), fake_blender())
    assert host.compare_records(repeat, first) == []
    changed = json.loads(json.dumps(repeat))
    changed["outputs"]["mtl"]["sha256"] = "0" * 64
    earlier = first["outputs"]["mtl"]["sha256"]
    assert host.compare_records(changed, first) == [
        f"outputs.mtl.sha256 is {'0' * 64!r}, the earlier run's {earlier!r}"
    ]


def test_blender_command_order(setup: dict[str, Any]) -> None:
    planned = plan(setup)
    command = list(planned.command)
    head = [str(setup["exe"].resolve()), *host.BLENDER_OPTIONS]
    assert command[: len(host.BLENDER_OPTIONS) + 1] == head
    assert command.index("--python-exit-code") < command.index("--python")
    assert command[command.index("--python") + 1] == str(host.SCRIPT)
    assert not planned.run_dir.exists()  # planning writes nothing


def test_a_relative_executable_is_resolved_before_hashing(
    setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blender runs with the run directory as its working directory, so the command names the
    checked executable by its absolute path."""
    monkeypatch.chdir(setup["exe"].parent)
    planned = host.plan_export(
        Path(setup["exe"].name),
        "r1",
        setup["assets"],
        None,
        source_pin=setup["pin"],
        blender_sha256=setup["exe_sha256"],
        work=setup["work"],
    )
    assert planned.command[0] == str(setup["exe"].resolve())


@pytest.mark.parametrize(
    ("runner", "fragment"),
    [
        (fake_blender(extra="blender.crash.txt"), "unexpected"),
        (fake_blender(code=1), "Blender exited 1"),
        (fake_blender(touch_copy=True), "changed the private copy"),
    ],
    ids=["leftover", "exit-code", "saved-copy"],
)
def test_failed_runs_are_refused(setup: dict[str, Any], runner: host.Runner, fragment: str) -> None:
    with pytest.raises(ExportError, match=fragment):
        host.run_export(plan(setup), runner)
    assert not (setup["work"] / "r1" / host.RECORD_NAME).exists()


INSIDE = REPO_ROOT / "tmp" / "scratch"  # an existing repository folder; nothing is created in it
PROBE = "front-n-guard-probe"


def never_called(command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path) -> int:
    raise AssertionError("the runner ran for a run directory inside the repository")


def test_a_run_directory_inside_the_repository_is_refused(setup: dict[str, Any]) -> None:
    with pytest.raises(RecorderError, match="inside the repository"):
        plan(setup, PROBE, work=INSIDE)
    inside = dataclasses.replace(plan(setup), run_dir=INSIDE / PROBE)
    with pytest.raises(RecorderError, match="inside the repository"):
        host.run_export(inside, never_called)
    assert not (INSIDE / PROBE).exists()
    assert not (setup["work"] / "r1").exists()


def test_a_symbolic_link_into_the_repository_is_refused(
    setup: dict[str, Any], tmp_path: Path
) -> None:
    """A symbolic link, or on Windows without the symlink privilege a directory junction (the
    same reparse-point resolution), is followed before the guard."""
    link = tmp_path / "link-into-repository"
    try:
        link.symlink_to(INSIDE, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            raise
        import _winapi

        _winapi.CreateJunction(str(INSIDE), str(link))
    try:
        with pytest.raises(RecorderError, match="inside the repository"):
            plan(setup, PROBE, work=link)
        inside = dataclasses.replace(plan(setup), run_dir=link / PROBE)
        with pytest.raises(RecorderError, match="inside the repository"):
            host.run_export(inside, never_called)
        assert not (INSIDE / PROBE).exists()
    finally:
        if link.is_junction():  # remove the link only, never its target's contents
            os.rmdir(link)
        else:
            link.unlink()


def test_planning_refuses_unpinned_inputs(setup: dict[str, Any]) -> None:
    with pytest.raises(ExportError, match="pinned"):
        plan(setup, blender_sha256="0" * 64)
    with pytest.raises(ExportError, match="must match"):
        plan(setup, "../escape")
    (setup["work"] / "r1").mkdir(parents=True)
    with pytest.raises(ExportError, match="already exists"):
        plan(setup)
    (setup["assets"] / setup["pin"].assets3d_path).write_bytes(b"changed after the round")
    with pytest.raises(RecorderError, match="no private store here"):
        plan(setup, "r2")


def test_the_source_falls_back_to_the_private_store(setup: dict[str, Any], tmp_path: Path) -> None:
    source = setup["assets"] / setup["pin"].assets3d_path
    store = OracleStore.init(tmp_path / "store")
    store.add_input(source, setup["pin"].sha256, setup["pin"].assets3d_path)
    source.unlink()
    planned = plan(setup, store=store)
    assert planned.source_origin == "store"
    assert host.run_export(planned, fake_blender())["source"]["resolved_from"] == "store"


def test_the_cli_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UZP_ORACLE_WORK", str(tmp_path / "work"))
    store = OracleStore.init(tmp_path / "store")
    argv = ["--blender", str(tmp_path / "none.exe"), "--assets-root", str(tmp_path), "--dry-run"]
    assert host.main([*argv, "--store", str(store.root)]) == 2
    assert not (tmp_path / "work").exists()
