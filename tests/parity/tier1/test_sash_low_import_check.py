"""The Sash low import check's comparator and bindings, on authored inspector documents."""

from __future__ import annotations

import _winapi
import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from tools.parity.recorder.session import (
    PainterIdentity,
    PainterSession,
    ProjectState,
    RecorderError,
)
from tools.parity.tier1 import sash_low_import_check as check

POSITIONS = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]]
UVS = [[0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]]
NORMAL = [0.0, 0.0, 1.0]


def document(triangles: list[list[int]], material: str = "m") -> dict[str, Any]:
    """An inspector document with one corner per (triangle, corner)."""
    corners: list[dict[str, Any]] = []
    indices: list[list[int]] = []
    for triangle in triangles:
        row = []
        for vertex in triangle:
            row.append(len(corners))
            corners.append(
                {
                    "position": vertex,
                    "uv0": list(UVS[vertex]),
                    "normal": list(NORMAL),
                    "material": 0,
                }
            )
        indices.append(row)
    return {
        "mesh": {
            "positions": copy.deepcopy(POSITIONS),
            "corners": corners,
            "objects": [{"name": "o", "triangles": indices}],
        },
        "report": {"materials": [{"index": 0, "name": material}]},
    }


SOURCE = document([[0, 1, 2], [1, 3, 2]])


def test_face_order_and_cyclic_rotation_are_equal() -> None:
    other = document([[3, 2, 1], [2, 0, 1]])
    result = check.compare(SOURCE, other, 0.0)
    assert result["full_multiset_equal"] and result["within_bounds"]
    assert result["normals"]["max_abs"] == 0.0


def test_reversed_winding_is_not_equal() -> None:
    other = document([[0, 2, 1], [1, 3, 2]])
    result = check.compare(SOURCE, other, 1.0)
    assert not result["position_uv_material_multiset_equal"] and not result["within_bounds"]
    assert result["diagnostics"]["identity_matches"] == 1
    assert result["diagnostics"]["reversed_winding_matches"] == 1


def test_v_mirror_is_not_equal_and_is_diagnosed() -> None:
    other = document([[0, 1, 2], [1, 3, 2]])
    for corner in other["mesh"]["corners"]:
        corner["uv0"][1] = 1.0 - corner["uv0"][1]
    result = check.compare(SOURCE, other, 1.0)
    assert not result["within_bounds"]
    assert result["diagnostics"]["v_mirrored_matches"] == 2


def test_material_name_and_moved_positions_are_compared() -> None:
    assert not check.compare(SOURCE, document([[0, 1, 2], [1, 3, 2]], "x"), 1.0)["within_bounds"]
    moved = document([[0, 1, 2], [1, 3, 2]])
    moved["mesh"]["positions"][3] = [1.0, 1.0, 1e-7]
    assert not check.compare(SOURCE, moved, 1.0)["within_bounds"]


def test_normals_are_held_to_the_declared_bound() -> None:
    other = document([[1, 2, 0], [1, 3, 2]])
    other["mesh"]["corners"][4]["normal"] = [0.0, 3e-5, 1.0]
    within = check.compare(SOURCE, other, 6.5e-5)
    assert within["position_uv_material_multiset_equal"] and not within["full_multiset_equal"]
    assert within["within_bounds"] and within["normals"]["differing_components"] == 1
    assert not check.compare(SOURCE, other, 1e-5)["within_bounds"]


def test_uv_tiles() -> None:
    other = document([[0, 1, 2]])
    other["mesh"]["corners"][0]["uv0"] = [1.5, 1.5]
    assert check.uv_tiles(SOURCE) == [1001]
    assert check.uv_tiles(other) == [1001, 1012]


def report_for(bounds: list[list[float]], **options: Any) -> dict[str, Any]:
    pinned = {
        "forward_axis": "NEGATIVE_Z",
        "up_axis": "Y",
        "global_scale": 1.0,
        "apply_transform": True,
    }
    return {
        "export": {"options": {**pinned, **options}},
        "mesh": {"bounds": bounds, "triangles": check.TRIANGLES},
    }


def bound_source() -> dict[str, Any]:
    doc = document([[0, 1, 2]])
    doc["mesh"]["positions"] = [[-1.0, 2.0, -6.0], [1.0, 3.0, -5.0], [0.0, 2.5, -5.5]]
    doc["report"].update(
        counts={"triangles": check.TRIANGLES}, flags={"v_flip": False}, units={"scale": 1.0}
    )
    return doc


def test_source_binding_maps_blender_axes() -> None:
    # Blender bounds x [-1, 1], y [5, 6], z [2, 3]; the OBJ holds (x, z, -y).
    report = report_for([[-1.0, 5.0, 2.0], [1.0, 6.0, 3.0]])
    bound = check.source_binding(bound_source(), report)
    assert bound["max_bounds_delta"] == 0.0
    with pytest.raises(RecorderError, match="bounds differ"):
        check.source_binding(bound_source(), report_for([[-1.0, 2.0, 5.0], [1.0, 3.0, 6.0]]))
    with pytest.raises(RecorderError, match="up_axis"):
        check.source_binding(bound_source(), report_for(report["mesh"]["bounds"], up_axis="Z"))


def test_scene_versus_source() -> None:
    box = {"center": [0.0, 2.5, -5.5], "dimensions": [4.0, 2.0, 2.0], "radius": 1.0}
    result = check.scene_versus_source(box, {"min": [-1.0, 2.0, -6.0], "max": [1.0, 3.0, -5.0]})
    assert result["center_delta"] == [0.0, 0.0, 0.0]
    assert result["dimension_ratio"] == [2.0, 2.0, 2.0]


SCENE = {"center": [0.5, 0.5, 0.5], "dimensions": [1.0, 1.0, 1.0], "radius": 0.9}
SOURCE_BOUNDS = {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]}


class FakeSession:
    """A Painter lifecycle without Painter: its own create gives UUID `own`; `reopen_uuid` is the
    UUID the reopened file reports; `on_export(export index, fake)` runs after each export."""

    def __init__(
        self,
        reopen_uuid: str = "own",
        on_export: Callable[[int, FakeSession], None] | None = None,
        texture_sets: tuple[str, ...] = (check.TEXTURE_SET,),
    ) -> None:
        self.identity: PainterIdentity | None = None
        self.open = False
        self.path: str | None = None
        self.created: str | None = None
        self.uuid: str | None = None
        self.reopen_uuid = reopen_uuid
        self.on_export = on_export
        self.texture_sets = texture_sets
        self.exports = 0
        self.closes = 0

    def connect(self) -> PainterIdentity:
        self.identity = PainterIdentity("12.2.0", (12, 2, 0), "1.1.20", "session", {})
        return self.identity

    def state(self) -> ProjectState:
        return ProjectState(self.open, self.open, False, self.path, 0.0)

    def wait_ready(self) -> ProjectState:
        return self.state()

    def wait_closed(self) -> ProjectState:
        return self.state()

    def call(self, operation: str, **args: Any) -> Any:
        if operation == "apply_step":
            self.open, self.path, self.created, self.uuid = True, None, "own", "own"
            return {}
        if operation == "probe_step":
            assert args["args"] == {"owned_project": True}
            uuids = {"created_project_uuid": self.created, "current_project_uuid": self.uuid}
            return {"value": uuids}
        if operation == "texture_set_names":
            return [{"name": n, "original_name": n} for n in self.texture_sets]
        if operation == "scene_bounding_box":
            return copy.deepcopy(SCENE)
        if operation == "migration_readback":
            return {"texture_sets": {check.TEXTURE_SET: {"resolution": [2048, 2048]}}}
        if operation == "export_base_mesh":
            Path(args["path"]).write_text("base mesh", encoding="utf-8")
            if self.on_export is not None:
                self.on_export(self.exports, self)
            self.exports += 1
            return {"status": "Success", "message": ""}
        if operation == "save_as":
            Path(args["path"]).write_text("project", encoding="utf-8")
            self.path = args["path"]
            return {}
        if operation == "close_project":
            self.open, self.path = False, None
            self.closes += 1
            return {}
        if operation == "open_project":
            self.open, self.path, self.uuid = True, args["path"], self.reopen_uuid
            return {}
        raise AssertionError(f"unexpected operation {operation}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private root with authored stand-ins for the pinned sources; the inspector, the
    controls, the source binding and the envelope are replaced by fakes."""
    work = tmp_path / "work"
    source = work / check.SOURCE_RUN
    source.mkdir(parents=True)
    for name, attribute in (
        (check.OBJ_NAME, "OBJ_SHA256"),
        (check.MTL_NAME, "MTL_SHA256"),
        (check.EXPORT_REPORT_NAME, "EXPORT_REPORT_SHA256"),
    ):
        (source / name).write_text(json.dumps({"authored": name}), encoding="utf-8")
        monkeypatch.setattr(check, attribute, sha256(source / name))
    inspector = tmp_path / "inspector.exe"
    inspector.write_bytes(b"inspector")
    monkeypatch.setattr(check, "INSPECTOR", inspector)
    monkeypatch.setattr(check, "INSPECTOR_SHA256", sha256(inspector))
    monkeypatch.setattr(check, "check_controls", lambda path: {})
    inspected = copy.deepcopy(SOURCE)
    inspected["report"]["flags"] = {"v_flip": False}
    monkeypatch.setattr(check, "inspect", lambda path, directory: copy.deepcopy(inspected))
    monkeypatch.setattr(check, "source_binding", lambda document, report: {"bounds": SOURCE_BOUNDS})
    monkeypatch.setattr(check, "envelope_entry", lambda: {"envelope_id": "e"})
    monkeypatch.setattr(check, "verify", lambda session, entry, colour: None)
    return work


def run(root: Path, fake: FakeSession) -> dict[str, Any]:
    run_dir, report = check.execute(root, False, lambda: cast(PainterSession, fake))
    assert run_dir is not None and report is not None
    on_disk: dict[str, Any] = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == report["status"]
    return on_disk


def test_lifecycle_of_own_project(root: Path) -> None:
    fake = FakeSession()
    report = run(root, fake)
    assert report["status"] == "complete", report.get("error")
    assert report["verdict"]["import_consistent"] and report["verdict"]["differences"] == []
    assert report["cleanup"]["closed"] and not fake.open and fake.closes == 2
    assert [c["at"] for c in report["project_checks"]] == [
        "create",
        "export r1",
        "export repeat",
        "save",
        "saved",
        "reopen",
        "export reopen",
    ]


def test_mutated_original_refuses(root: Path) -> None:
    def mutate(index: int, fake: FakeSession) -> None:
        if index == 1:
            (root / check.SOURCE_RUN / check.OBJ_NAME).write_text("changed", encoding="utf-8")

    report = run(root, FakeSession(on_export=mutate))
    assert report["status"] == "refused"
    assert "source hashes" in report["final_hash_problems"][0]
    assert not report["verdict"]["import_consistent"]


def test_mutated_staged_copy_refuses(root: Path) -> None:
    def mutate(index: int, fake: FakeSession) -> None:
        staged = next((root / "sash-low-import-check").glob("run-*")) / "source"
        (staged / check.MTL_NAME).write_text("changed", encoding="utf-8")

    report = run(root, FakeSession(on_export=mutate))
    assert report["status"] == "refused"
    assert any("staged hashes" in p for p in report["final_hash_problems"])


def test_reopen_with_same_basename_and_new_uuid_refuses(root: Path) -> None:
    fake = FakeSession(reopen_uuid="substituted")
    report = run(root, fake)
    assert report["status"] == "refused" and "UUID differs" in report["error"]
    assert not report["cleanup"]["closed"] and fake.open and fake.closes == 1


def test_project_replaced_before_cleanup_stays_open(root: Path) -> None:
    def replace(index: int, fake: FakeSession) -> None:
        if index == 2:
            fake.uuid = "unrelated"

    fake = FakeSession(on_export=replace)
    report = run(root, fake)
    assert report["status"] == "refused" and "not closed" in report["error"]
    assert fake.open and fake.closes == 1


def test_other_texture_sets_are_a_difference(root: Path) -> None:
    report = run(root, FakeSession(texture_sets=(check.TEXTURE_SET, "extra")))
    assert report["status"] == "complete"
    assert not report["verdict"]["import_consistent"]
    assert report["verdict"]["differences"] == [
        "r1: texture sets == [25-Faixa-Cintura]",
        "reopen: texture sets == [25-Faixa-Cintura]",
    ]


def test_guarded_refuses_junctions_and_escapes(tmp_path: Path) -> None:
    root = tmp_path / "private"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    _winapi.CreateJunction(str(outside), str(root / "sash-low-import-check"))
    with pytest.raises(RecorderError, match="junction"):
        check.guarded(root / "sash-low-import-check" / "run-x", root)
    with pytest.raises(RecorderError, match="leaves the private root"):
        check.guarded(root / "a" / ".." / ".." / "outside" / "x", root)
    assert check.guarded(root / "run-x" / "source", root) == root / "run-x" / "source"
