"""The Tunic v10 inspection helper on authored data, with no Blender (decision 300 section 7).

The "Blender" of the host tests is a Python function that writes what the Blender side would
write; the Blender side's mesh reading runs on small authored stand-ins for its RNA collections.
Nothing here opens the Tunic `.blend`, runs Blender or claims anything about the real file.
"""

from __future__ import annotations

import ast
import hashlib
import json
import struct
import subprocess
import zlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import numpy as np
import pytest

from tools.parity.recorder import tunic
from tools.parity.recorder.job import sha256_file
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier1 import tunic_intermediates as host
from tools.parity.tier1 import tunic_intermediates_blender as side
from tools.parity.tier1.sash_low_export import SourcePin
from tools.parity.tier1.tunic_intermediates_blender import InspectError

Runner = Callable[[Sequence[str], Path, Mapping[str, str], Path, int], int]


# ----------------------------------------------------------------------------- pure helpers
def test_pins_follow_the_contract_and_the_recorder() -> None:
    assert host.SOURCE.sha256 == "f6243a577f673c2b00e5803c256cebfbe933187810b7446f81d56827f0d92cb9"
    assert host.SOURCE.assets3d_path == tunic.TUNIC_BLEND
    assert Path(tunic.TUNIC_BLEND).name == side.SOURCE_BLEND_NAME
    assert (host.NORMAL_IMAGE, host.NORMAL_SHA256) == tunic.NORMAL
    assert tunic.NORMAL[0] == side.NORMAL_IMAGE
    assert (side.LOW_OBJECT, side.HIGH_OBJECT) == ("18-Tunica-Low", "18-Tunica-High-OriginalFit")
    assert side.LINING_ATTRIBUTE == "LiningMask" and "Source_Lining" in side.CANDIDATE_NAMES


def test_the_blender_side_imports_nothing_from_the_repository() -> None:
    tree = ast.parse(Path(side.__file__).read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.Import)]
    modules = [alias.name for node in imports for alias in node.names] + [
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]
    assert not [m for m in modules if m.startswith("tools")]
    # No save call anywhere in the Blender side (`save_mainfile`, `image.save`, ...).
    assert not any(
        isinstance(node, ast.Attribute) and node.attr.startswith("save") for node in ast.walk(tree)
    )


def test_lining_summary_counts_crossings_on_edges_and_triangle_diagonals() -> None:
    # A quad 0-1-2-3 split on the diagonal 0-2; only vertex 2 is lining.
    values = [0.0, 0.25, 1.0, 0.5]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
    triangles = [(0, 1, 2), (0, 2, 3)]
    summary = side.lining_summary(values, edges, triangles)
    assert summary["count"] == summary["finite"] == 4
    assert (summary["below"], summary["at"], summary["above"]) == (2, 1, 1)
    assert (summary["min"], summary["max"], summary["distinct"]) == (0.0, 1.0, 4)
    assert summary["binary"] is False
    # 1-2 crosses; 2-3 touches 0.5 (product 0, not a crossing, as in the donor); 0-2 crosses.
    assert summary["crossings_mesh_edges"] == 1
    assert summary["crossings_triangle_edges"] == 2


def test_lining_summary_keeps_non_finite_values_out_of_the_range() -> None:
    summary = side.lining_summary([0.0, float("nan"), 1.0, float("inf")], [(0, 1), (0, 2)])
    assert (summary["count"], summary["finite"]) == (4, 2)
    assert (summary["min"], summary["max"]) == (0.0, 1.0)
    assert summary["binary"] is False
    assert summary["crossings_mesh_edges"] == 1
    assert summary["crossings_triangle_edges"] is None
    assert side.lining_summary([1.0, 0.0])["binary"] is True
    empty = side.lining_summary([])
    assert (empty["min"], empty["max"], empty["count"]) == (None, None, 0)


def test_crossings_are_strict_on_both_sides() -> None:
    below, above = float(np.nextafter(0.5, 0.0)), float(np.nextafter(0.5, 1.0))
    assert side.crossings([below, above], [(0, 1)]) == 1
    assert side.crossings([0.5, above], [(0, 1)]) == 0
    assert side.crossings([below, 0.25], [(0, 1)]) == 0
    assert side.crossings([0.0, 1.0], []) == 0


def test_mesh_helpers() -> None:
    assert side.polygon_triangles([4, 3, 5]) == 2 + 1 + 3
    assert side.polygon_triangles([]) == 0
    edges = side.triangle_edges([(0, 1, 2), (2, 1, 3)])
    assert edges.tolist() == [[0, 1], [0, 2], [1, 2], [1, 3], [2, 3]]
    assert side.is_identity([[1.0, 0.0], [0.0, 1.0]])
    assert not side.is_identity([[1.0, 0.0], [0.0, 0.01]])
    assert side.matrix_json([(1, 2), (3, 4)]) == [[1.0, 2.0], [3.0, 4.0]]
    assert side.plain({"B", "A"}) == ["A", "B"]
    assert side.plain((1, (2.5, "x"))) == [1, [2.5, "x"]]
    assert side.plain(b"ab") == "ab"


def png_bytes(width: int, height: int, depth: int, colour: int) -> bytes:
    body = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, 0)
    chunk = struct.pack(">I", len(body)) + b"IHDR" + body
    return side.PNG_SIGNATURE + chunk + struct.pack(">I", zlib.crc32(b"IHDR" + body))


def test_png_header_and_packed_identity() -> None:
    data = png_bytes(4096, 2048, 16, 2)
    assert side.png_header(data) == {
        "width": 4096,
        "height": 2048,
        "bit_depth": 16,
        "colour_type": 2,
        "interlace": 0,
    }
    assert side.png_header(b"not a png at all, but long enough to read") is None
    identity = side.packed_identity(data)
    assert identity["sha256"] == hashlib.sha256(data).hexdigest()
    assert identity["sha1"] == hashlib.sha1(data).hexdigest()
    assert identity["size_bytes"] == len(data)


def rna(*props: tuple[str, str]) -> NS:
    return NS(properties=[NS(identifier=name, type=kind) for name, kind in props])


def test_rna_properties_reads_values_pointers_and_collections() -> None:
    class Broken:
        @property
        def bad(self) -> float:
            raise RuntimeError("context")

    struct_ = Broken()
    struct_.__dict__.update(
        {
            "bl_rna": rna(
                ("rna_type", "POINTER"),
                ("name", "STRING"),
                ("levels", "INT"),
                ("object", "POINTER"),
                ("none", "POINTER"),
                ("items", "COLLECTION"),
                ("offset", "FLOAT"),
                ("bad", "FLOAT"),
            ),
            "rna_type": object(),
            "name": "skipped",
            "levels": 2,
            "object": NS(name="Armature"),
            "none": None,
            "items": [1, 2, 3],
            "offset": (0.0, 1.5),
        }
    )
    found = side.rna_properties(struct_, ("name",))
    assert found == {
        "levels": 2,
        "object": "Armature",
        "none": None,
        "items": 3,
        "offset": [0.0, 1.5],
        "bad": "<unreadable: context>",
    }


def fake_image(data: bytes | None) -> NS:
    return NS(
        name=side.NORMAL_IMAGE,
        type="IMAGE",
        source="FILE",
        filepath="//t.png",
        filepath_raw="//t.png",
        packed_files=[] if data is None else [object()],
        packed_file=None if data is None else NS(data=data),
        colorspace_settings=NS(name="Non-Color", is_data=True),
        alpha_mode="STRAIGHT",
        file_format="PNG",
        is_dirty=False,
        size=(4096, 4096),
        channels=4,
        depth=64,
        is_float=True,
        use_half_precision=False,
        has_data=True,
    )


def test_image_report() -> None:
    data = png_bytes(4096, 4096, 16, 2)
    report = side.image_report(fake_image(data))
    assert report["packed"] == side.packed_identity(data)
    assert (report["colorspace"], report["depth"], report["is_float"]) == ("Non-Color", 64, True)
    assert report["size"] == [4096, 4096]
    assert side.image_report(fake_image(None))["packed"] is None


class Collection(list[Any]):
    """An RNA collection stand-in: `foreach_get` fills a flat buffer from per-item tuples."""

    def __init__(self, items: Sequence[Any], fields: Mapping[str, Sequence[Any]]):
        super().__init__(items)
        self.fields = fields

    def foreach_get(self, name: str, buffer: Any) -> None:
        buffer[:] = np.asarray(self.fields[name]).ravel()

    def get(self, name: str) -> Any:
        return next((item for item in self if item.name == name), None)


def fake_mesh(lining: Sequence[float] | None, domain: str = "POINT") -> NS:
    """The quad and triangle: vertices 0-3 a quad, 2-4 a triangle (shared edge 2-3)."""
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (2, 4), (4, 3)]
    attributes: list[Any] = [NS(name="position", domain="POINT", data_type="FLOAT_VECTOR")]
    attributes.append(NS(name=".hidden", domain="POINT", data_type="BOOLEAN"))
    if lining is not None:
        attributes.append(
            NS(
                name=side.LINING_ATTRIBUTE,
                domain=domain,
                data_type="FLOAT",
                data=Collection(list(lining), {"value": lining}),
            )
        )
    uv = NS(name="UVMap", active_render=True)
    mesh = NS(
        name="mesh",
        vertices=[object()] * 5,
        edges=Collection(edges, {"vertices": edges}),
        polygons=Collection([0, 1], {"loop_total": [4, 3], "material_index": [0, 0]}),
        loops=[object()] * 7,
        uv_layers=Collection([uv], {}),
        attributes=Collection(attributes, {}),
        loop_triangles=Collection([], {}),
    )
    mesh.uv_layers.active = uv

    def calc_loop_triangles() -> None:
        tris = [(0, 1, 2), (0, 2, 3), (2, 4, 3)]
        mesh.loop_triangles = Collection(tris, {"vertices": tris})

    mesh.calc_loop_triangles = calc_loop_triangles
    return mesh


def test_mesh_reads_counts_layers_and_the_lining_crossings() -> None:
    mesh = fake_mesh([0.0, 0.0, 1.0, 0.0, 1.0])
    authored = side._mesh(mesh, triangulated=False)
    assert authored["counts"] == {
        "vertices": 5,
        "edges": 6,
        "polygons": 2,
        "loops": 7,
        "polygon_triangles": 3,
    }
    assert authored["uv"] == {"names": ["UVMap"], "active": "UVMap", "active_render": ["UVMap"]}
    assert authored["attributes"] == [
        ["LiningMask", "POINT", "FLOAT"],
        ["position", "POINT", "FLOAT_VECTOR"],
    ]
    assert authored["material_indices"] == {"0": 2}
    lining = authored["lining"]
    assert (lining["domain"], lining["data_type"], lining["size"]) == ("POINT", "FLOAT", 5)
    assert lining["values"]["crossings_mesh_edges"] == 3  # 1-2, 2-3, 4-3
    assert lining["values"]["crossings_triangle_edges"] is None
    evaluated = side._mesh(mesh, triangulated=True)
    assert evaluated["counts"]["loop_triangles"] == 3
    assert evaluated["lining"]["values"]["crossings_triangle_edges"] == 4  # and diagonal 0-2


def test_mesh_without_or_with_another_domain_of_lining() -> None:
    assert side._mesh(fake_mesh(None), triangulated=True)["lining"] is None
    face = side._mesh(fake_mesh([0.0, 1.0], domain="FACE"), triangulated=True)["lining"]
    assert face["domain"] == "FACE" and face["values"]["crossings_mesh_edges"] is None
    assert face["values"]["crossings_triangle_edges"] is None


def test_lookup_hits_on_the_inspected_objects() -> None:
    def entry(attributes: list[list[str]], groups: list[str]) -> dict[str, Any]:
        mesh = {"attributes": attributes, "uv": {"names": ["UVMap"]}}
        return {
            "present": True,
            "type": "MESH",
            "vertex_groups": groups,
            "materials": {"slots": [{"name": "DefaultMaterial"}]},
            "shape_keys": None,
            "authored": mesh,
            "evaluated": mesh,
        }

    objects = {
        side.LOW_OBJECT: entry([["LiningMask", "POINT", "FLOAT"]], ["Source_Lining"]),
        side.HIGH_OBJECT: {"present": False},
    }
    assert side.lookup_hits("LiningMask", objects) == [
        {"object": side.LOW_OBJECT, "kind": "authored_attributes"},
        {"object": side.LOW_OBJECT, "kind": "evaluated_attributes"},
    ]
    assert side.lookup_hits("Source_Lining", objects) == [
        {"object": side.LOW_OBJECT, "kind": "vertex_groups"}
    ]
    assert side.lookup_hits("Other", objects) == []


# ------------------------------------------------------------------------------- the host
def object_entry(name: str, lining: Mapping[str, Any] | None) -> dict[str, Any]:
    counts = {"vertices": 5, "edges": 6, "polygons": 2, "loops": 7, "polygon_triangles": 3}
    mesh = {
        "name": name,
        "counts": counts,
        "uv": {"names": ["UVMap"], "active": "UVMap", "active_render": ["UVMap"]},
        "attributes": [["position", "POINT", "FLOAT_VECTOR"]],
        "material_indices": {"0": 2},
        "lining": lining,
    }
    return {
        "name": name,
        "present": True,
        "type": "MESH",
        "modifiers": [{"name": "Armature", "type": "ARMATURE", "properties": {}}],
        "constraints": [],
        "materials": {"slots": [{"index": 0, "name": "DefaultMaterial"}], "data": []},
        "shape_keys": None,
        "vertex_groups": ["Lining"],
        "authored": mesh,
        "evaluated": {**mesh, "counts": {**counts, "loop_triangles": 3}},
    }


NORMAL_BYTES = png_bytes(4096, 4096, 16, 2)


def authored_report(cwd: Path, **changes: Any) -> dict[str, Any]:
    lining = {
        "name": side.LINING_ATTRIBUTE,
        "domain": "POINT",
        "data_type": "FLOAT",
        "size": 5,
        "values": side.lining_summary([0.0, 0.0, 1.0, 0.0, 1.0], [(1, 2)], [(0, 1, 2)]),
    }
    report = {
        "inspector": side.INSPECTOR,
        "mode": "inspect",
        "blender": {"version": [5, 2, 3]},
        "blend": str(cwd / side.SOURCE_BLEND_NAME),
        "depsgraph_mode": "VIEWPORT",
        "objects": {
            side.LOW_OBJECT: object_entry(side.LOW_OBJECT, lining),
            side.HIGH_OBJECT: {"name": side.HIGH_OBJECT, "present": False},
        },
        "images": {side.NORMAL_IMAGE: {"packed": side.packed_identity(NORMAL_BYTES)}},
        "lookups": {name: {"data_blocks": [], "on_objects": []} for name in side.CANDIDATE_NAMES},
    }
    report.update(changes)
    return report


def fake_blender(
    code: int = 0,
    extra: str | None = None,
    touch_copy: bool = False,
    timeout: bool = False,
    **changes: Any,
) -> Runner:
    def run(
        command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path, seconds: int
    ) -> int:
        assert command[-2:] == ("inspect", str(cwd)) and env["TEMP"] == str(cwd)
        assert seconds == host.TIMEOUT_S
        copy = cwd / side.SOURCE_BLEND_NAME
        assert copy.stat().st_mode & 0o222 == 0  # read-only copy
        log.write_text("authored\n", encoding="utf-8")
        if timeout:
            raise subprocess.TimeoutExpired(list(command), seconds)
        if touch_copy:
            copy.chmod(0o666)
            copy.write_bytes(b"changed")
        if code:
            return code
        side.write_json(cwd / side.REPORT_NAME, authored_report(cwd, **changes))
        if extra:
            (cwd / extra).write_text("left behind", encoding="utf-8")
        return 0

    return run


@pytest.fixture
def scene(tmp_path: Path) -> NS:
    blend = b"authored blend bytes"
    pin = SourcePin(
        "blend", "piece/" + side.SOURCE_BLEND_NAME, hashlib.sha256(blend).hexdigest(), len(blend)
    )
    assets = tmp_path / "assets"
    source = assets / pin.assets3d_path
    source.parent.mkdir(parents=True)
    source.write_bytes(blend)
    blender = tmp_path / "blender.exe"
    blender.write_bytes(b"authored blender bytes")
    return NS(root=tmp_path, assets=assets, source=source, pin=pin, blender=blender)


def planned(scene: NS, run: str = "inspect-r1") -> host.Plan:
    return host.plan_inspect(
        scene.blender,
        run,
        scene.assets,
        None,
        source_pin=scene.pin,
        blender_sha256=sha256_file(scene.blender),
        work=scene.root / "work",
    )


def test_plan_pins_the_command_and_writes_nothing(scene: NS) -> None:
    plan = planned(scene)
    run_dir = scene.root / "work" / "inspect-r1"
    assert plan.run_dir == run_dir.resolve() and not run_dir.exists()
    assert plan.source == scene.source and plan.source_origin == "assets3d"
    assert plan.command == (
        str(scene.blender.resolve()),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "--offline-mode",
        "-noaudio",
        str(plan.run_dir / side.SOURCE_BLEND_NAME),
        "--python-exit-code",
        "1",
        "--python",
        str(host.SCRIPT),
        "--",
        "inspect",
        str(plan.run_dir),
    )
    document = plan.as_json()
    assert document["script"]["blender_side"] == "tools/parity/tier1/tunic_intermediates_blender.py"
    assert document["script"]["host_sha256"] == sha256_file(Path(host.__file__))
    temp = ("TEMP", "TMP", "TMPDIR")
    assert document["environment"] == {name: str(plan.run_dir) for name in temp}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"blender_sha256": "0" * 64}, "pinned"),
        ({"run": "../escape"}, "run name"),
        ({"source_pin": "wrong-size"}, "bytes, pinned"),
        ({"source_pin": "wrong-name"}, "source name"),
    ],
)
def test_plan_refuses_a_pin(scene: NS, change: Mapping[str, Any], message: str) -> None:
    kwargs: dict[str, Any] = {
        "source_pin": scene.pin,
        "blender_sha256": sha256_file(scene.blender),
        "work": scene.root / "work",
    }
    run = str(change.get("run", "inspect-r1"))
    if "blender_sha256" in change:
        kwargs["blender_sha256"] = change["blender_sha256"]
    if change.get("source_pin") == "wrong-size":
        kwargs["source_pin"] = SourcePin(
            "blend", scene.pin.assets3d_path, scene.pin.sha256, scene.pin.size_bytes + 1
        )
    if change.get("source_pin") == "wrong-name":
        kwargs["source_pin"] = SourcePin("blend", "piece/other.blend", scene.pin.sha256, 1)
    with pytest.raises(InspectError, match=message):
        host.plan_inspect(scene.blender, run, scene.assets, None, **kwargs)


def test_plan_refuses_an_existing_run_and_the_repository(scene: NS) -> None:
    (scene.root / "work" / "inspect-r1").mkdir(parents=True)
    with pytest.raises(InspectError, match="already exists"):
        planned(scene)
    with pytest.raises(Exception, match="repository"):
        host.plan_inspect(
            scene.blender,
            "inspect-r1",
            scene.assets,
            None,
            source_pin=scene.pin,
            blender_sha256=sha256_file(scene.blender),
            work=REPO_ROOT / "tmp" / "scratch",
        )


def test_plan_refuses_a_source_that_is_not_pinned(scene: NS) -> None:
    scene.source.write_bytes(b"other bytes")
    with pytest.raises(Exception, match="private store"):
        planned(scene)


def record_on_disk(plan: host.Plan) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(
        (plan.run_dir / host.RECORD_NAME).read_text(encoding="utf-8")
    )
    return document


def test_inspect_records_hashes_and_a_public_summary_of_counts(scene: NS) -> None:
    plan = planned(scene)
    record = host.run_inspect(plan, fake_blender())
    assert record == record_on_disk(plan)
    assert record["status"] == "inspected" and record["label"] == host.LABEL
    assert record["source"] == {
        **scene.pin.as_json(),
        "resolved_from": "assets3d",
        **dict.fromkeys(host.HASH_KEYS, scene.pin.sha256),
    }
    assert {p.name for p in plan.run_dir.iterdir()} == host.OUTPUTS | {host.RECORD_NAME}
    public = record["public"]
    assert record["report"] == {"file": side.REPORT_NAME, **public["report"]}
    assert public["report"] == {
        "sha256": sha256_file(plan.run_dir / side.REPORT_NAME),
        "size_bytes": (plan.run_dir / side.REPORT_NAME).stat().st_size,
    }
    low = public["objects"]["low"]
    assert low["evaluated"]["loop_triangles"] == 3 and low["modifiers"] == 1
    assert low["authored"]["lining"] == {
        "present": True,
        "size": 5,
        "read": True,
        "count": 5,
        "finite": 5,
        "distinct": 2,
        "below": 3,
        "at": 0,
        "above": 2,
        "crossings_mesh_edges": 1,
        "crossings_triangle_edges": 2,
    }
    assert public["objects"]["high"] == {"present": False}
    assert public["normal"]["sha256"] == hashlib.sha256(NORMAL_BYTES).hexdigest()
    assert public["normal"]["sha256_equals_pin"] is False  # authored bytes, not the Normal
    assert public["lookups"] == {
        "lining_attribute": {"data_blocks": 0, "on_objects": 0},
        "source_lining": {"data_blocks": 0, "on_objects": 0},
    }
    # Hashes and counts only, under role labels: the exact public schema, and no private text.
    assert sorted(public) == ["lookups", "normal", "objects", "report", "source_sha256"]
    assert sorted(public["objects"]) == ["high", "low"]
    assert sorted(low) == [
        "authored",
        "constraints",
        "evaluated",
        "material_slots",
        "modifiers",
        "present",
        "shape_keys",
        "vertex_groups",
    ]
    assert_public(json.dumps(public), scene)


def assert_public(text: str, scene: NS) -> None:
    for private in (
        *side.OBJECTS,
        *side.CANDIDATE_NAMES,
        side.NORMAL_IMAGE,
        side.SOURCE_BLEND_NAME,
        "POINT",
        "FLOAT",
        "UVMap",
        "DefaultMaterial",
        "Armature",
        "VIEWPORT",
        str(scene.root),
        json.dumps(str(scene.root))[1:-1],
    ):
        assert private not in text


def test_the_cli_prints_only_the_public_summary(
    scene: NS, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = planned(scene, host.DEFAULT_RUN)
    run_inspect = host.run_inspect
    monkeypatch.setattr(host, "locate", lambda: None)
    monkeypatch.setattr(host, "plan_inspect", lambda blender, run, assets, store: plan)
    monkeypatch.setattr(host, "run_inspect", lambda plan: run_inspect(plan, fake_blender()))
    argv = ["inspect", "--blender", str(scene.blender), "--assets-root", str(scene.assets)]
    assert host.main(argv) == 0
    out = capsys.readouterr().out
    document = json.loads(out)
    assert document == {"run": host.DEFAULT_RUN, **record_on_disk(plan)["public"]}
    assert_public(out, scene)


def test_a_blender_or_script_changed_after_the_plan_is_not_launched(scene: NS) -> None:
    plan = planned(scene)
    scene.blender.write_bytes(b"another executable")

    def never(*args: Any) -> int:
        raise AssertionError("launched")

    with pytest.raises(InspectError, match="Blender executable"):
        host.run_inspect(plan, never)
    record = record_on_disk(plan)
    assert record["status"] == "refused"
    assert all(record["source"][key] == scene.pin.sha256 for key in host.HASH_KEYS)
    stale = host.Plan(**{**plan.__dict__, "script_sha256": "0" * 64, "run_dir": plan.run_dir / "x"})
    scene.blender.write_bytes(b"authored blender bytes")
    with pytest.raises(InspectError, match="Blender side"):
        host.run_inspect(stale, never)


def test_an_unreadable_file_is_recorded_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreadable(path: Path) -> str:
        raise PermissionError("denied")

    present = tmp_path / "file"
    present.write_bytes(b"x")
    monkeypatch.setattr(host, "sha256_file", unreadable)
    assert host._hash_if_file(present) == "unreadable: denied"
    assert host._hash_if_file(tmp_path / "absent") is None


def test_the_cli_prints_the_dry_run_plan(
    scene: NS, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = planned(scene, host.DEFAULT_RUN)  # before the patch: the real plan_inspect
    monkeypatch.setattr(host, "locate", lambda: None)
    monkeypatch.setattr(host, "plan_inspect", lambda blender, run, assets, store: plan)
    argv = ["inspect", "--blender", str(scene.blender), "--assets-root", str(scene.assets)]
    assert host.main([*argv, "--dry-run"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["command"][-2] == "inspect"
    assert not (scene.root / "work").exists()


@pytest.mark.parametrize(
    ("runner", "message"),
    [
        (fake_blender(code=3), "exited 3"),
        (fake_blender(extra="blender.crash.txt"), "unexpected"),
        (fake_blender(touch_copy=True), "private copy"),
        (fake_blender(blend="elsewhere.blend"), "opened file"),
        (fake_blender(objects={side.LOW_OBJECT: {}}), "objects"),
        (fake_blender(mode="extract"), "mode"),
    ],
)
def test_a_refused_run_still_records_the_hashes(scene: NS, runner: Runner, message: str) -> None:
    plan = planned(scene)
    with pytest.raises(InspectError, match=message):
        host.run_inspect(plan, runner)
    record = record_on_disk(plan)
    assert record["status"] == "refused" and message in record["error"]
    source = record["source"]
    assert source["original_sha256_before"] == source["original_sha256_after"] == scene.pin.sha256
    assert source["copy_sha256_before"] == scene.pin.sha256
    if "copy" in message:
        assert source["copy_sha256_after"] == hashlib.sha256(b"changed").hexdigest()
    else:
        assert source["copy_sha256_after"] == scene.pin.sha256


def test_a_timeout_records_the_after_hashes(scene: NS) -> None:
    plan = planned(scene)
    with pytest.raises(subprocess.TimeoutExpired):
        host.run_inspect(plan, fake_blender(timeout=True))
    record = record_on_disk(plan)
    assert record["status"] == "refused" and "TimeoutExpired" in record["error"]
    assert all(record["source"][key] == scene.pin.sha256 for key in host.HASH_KEYS)


def test_a_source_changed_before_the_copy_is_refused_with_its_hash(scene: NS) -> None:
    plan = planned(scene)
    scene.source.write_bytes(b"changed after the plan")
    with pytest.raises(InspectError, match="before the run"):
        host.run_inspect(plan, fake_blender())
    source = record_on_disk(plan)["source"]
    changed = hashlib.sha256(b"changed after the plan").hexdigest()
    assert source["original_sha256_before"] == source["original_sha256_after"] == changed
    assert source["copy_sha256_before"] is None and source["copy_sha256_after"] is None


def test_report_problems_on_a_malformed_report(tmp_path: Path) -> None:
    copy = tmp_path / side.SOURCE_BLEND_NAME
    assert host.report_problems(authored_report(tmp_path), copy) == []
    assert host.report_problems({"inspector": side.INSPECTOR}, copy)[0].startswith(
        "the report is malformed"
    )
    report = authored_report(tmp_path)
    del report["objects"][side.LOW_OBJECT]["evaluated"]
    assert host.report_problems(report, copy) == [
        f"report object {side.LOW_OBJECT!r} has no evaluated counts"
    ]
