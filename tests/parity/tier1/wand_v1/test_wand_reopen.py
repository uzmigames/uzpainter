"""Host cases of the Wand v1 runner's save/reopen step (phase1.25 item 3.3; `runner.reopened`).

A stand-in for the adapter's `Wand` answers the save and identity calls and publishes each export
into the same `out` folder with its receipt, as `painter_export.py` does, so these cases need no
UzPainter: the first export's bytes are kept before the save even when the export after the reopen
overwrites them, and the record states a changed project (between the first export and the save,
at the save, at the reopen or against the first export's receipt), changed bytes or a refusal.
The real run is `test_wand_v1.py`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from tests.adapters.assets3d.wand import Call, Wand
from tests.parity.tier1.wand_v1.runner import (
    BACKEND,
    DECIDED_REFUSALS,
    IDENTITY,
    SAVE,
    Project,
    RunError,
    exported,
    initial_project,
    relied_exceptions,
    reopened,
)
from tools.parity.tier1.compare import CandidateRun

SET = "wand"
UUID = "6c1d7a52-2f4e-4c55-9a44-0d8f0e0a1b2c"


class Stand:
    """`Wand`'s `work`, `argument` (`out`, and `dst`: the created project), `probe` and `export`;
    every identity read names `project` and `uuid`. Each export writes `maps` into `out` with
    a receipt naming `receipt_project`: conformant, or under `diagnostic` the measure mode's,
    marked `non_conformant` with `bypassed` unless `unmarked`; `modes` lists each export's
    `diagnostic`; `refuse` makes the next export refuse as UzPainter does; the save sets the
    project's UUID to `uuid_after_save` and leaves it needing a save when `stays_unsaved`."""

    def __init__(self, work: Path, maps: dict[str, bytes]) -> None:
        self.work = work
        self.out = work / "out"
        self.project = work / "assets" / "wand.spp"
        self.dst = self.project
        self.maps = maps
        self.uuid = UUID
        self.uuid_after_save = UUID
        self.receipt_project = self.project.name
        self.stays_unsaved = False
        self.refuse = False
        self.calls: list[str] = []
        self.modes: list[bool] = []
        self.bypassed = [{"path": name, "refusal": DECIDED_REFUSALS[0]} for name in maps]
        self.unmarked = False
        self.env: dict[str, str] = {}  # no `UZP_ASSETS3D_GPU_BACKEND`: the verb's default backend
        work.mkdir()

    def argument(self, step: str, key: str) -> Path:
        return {("export", "out"): self.out, ("create", "dst"): self.dst}[(step, key)]

    def read(self, needs_saving: bool) -> dict[str, Any]:
        return {"file": str(self.project), "uuid": self.uuid, "needs_saving": needs_saving}

    def probe(self, name: str, body: str) -> Any:
        self.calls.append(name)
        assert body == {"built": IDENTITY, "save": SAVE, "reopened": IDENTITY}[name]
        if name != "save":
            return self.read(False)
        before = self.read(True)
        self.uuid = self.uuid_after_save
        return {"before": before, "after": self.read(self.stays_unsaved)}

    def export(self, diagnostic: bool = False) -> Call:
        self.calls.append("export")
        self.modes.append(diagnostic)
        if self.refuse:
            error = {"type": "NotYetSupported", "message": "the padding is not exact"}
            return Call(1, "", json.dumps({"error": error}) + "\n")
        self.out.mkdir(exist_ok=True)
        files = []
        for name, data in self.maps.items():
            (self.out / name).write_bytes(data)
            files.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
        receipt: dict[str, Any] = {
            "backend": BACKEND,
            "files": files,
            "manifest_files": {"project": {"path": self.receipt_project}},
        }
        if diagnostic and not self.unmarked:
            marking = {"mode": "diagnostic-measure", "decision": "286", "bypassed": self.bypassed}
            receipt["non_conformant"] = marking
        (self.out / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        (self.out / "current.json").write_text('{"receipt": "receipt.json"}', encoding="utf-8")
        names = [str(self.out / name) for name in self.maps]
        reply = {"status": "ExportStatus.Success", "files": {str((SET, "")): names}}
        return Call(0, json.dumps(reply), "")


MAPS = {"wand_BaseColor.png": b"base color", "wand_Normal.png": b"normal"}


@pytest.fixture
def stand(tmp_path: Path) -> Stand:
    return Stand(tmp_path / "run-1", dict(MAPS))


def start(stand: Stand) -> tuple[CandidateRun, Project]:
    """The built project's identity, then the first export (`runner._evidence`)."""
    initial = initial_project(cast(Wand, stand))
    return exported(cast(Wand, stand), stand.export()), initial


def test_the_same_project_exports_the_first_bytes_again(stand: Stand) -> None:
    """An identity read, the first export, the save, a fresh export and an identity read, in that
    order; the record holds 3.3, and the run the comparison reads is the copies taken before the
    save."""
    first, initial = start(stand)
    kept, record = reopened(cast(Wand, stand), first, initial)
    assert stand.calls == ["built", "export", "save", "export", "reopened"]
    same = Project(stand.project, UUID)
    assert record.initial == record.unsaved == record.saved == record.reopened == same
    assert record.exported == "wand.spp" and record.same_project
    assert record.refusal == "" and record.differing == [] and record.equal
    assert set(record.first) == {(SET, "wand_BaseColor"), (SET, "wand_Normal")}
    for key, path in kept.files.items():
        assert path.parent == stand.work / "first-export"
        assert path.read_bytes() == MAPS[f"{key[1]}.png"]


def test_the_first_bytes_are_kept_when_the_export_after_the_reopen_overwrites_them(
    stand: Stand,
) -> None:
    """The second export publishes changed bytes into the same `out`: the copies keep the first
    export's bytes and the record names the changed map."""
    first, initial = start(stand)
    stand.maps["wand_Normal.png"] = b"normal, changed"
    kept, record = reopened(cast(Wand, stand), first, initial)
    assert (stand.out / "wand_Normal.png").read_bytes() == b"normal, changed"
    assert kept.files[(SET, "wand_Normal")].read_bytes() == b"normal"
    assert record.differing == [(SET, "wand_Normal")]
    assert not record.equal


def test_a_missing_map_after_the_reopen_differs(stand: Stand) -> None:
    first, initial = start(stand)
    del stand.maps["wand_BaseColor.png"]  # its old file stays in `out`, unnamed by the reply
    _, record = reopened(cast(Wand, stand), first, initial)
    assert record.differing == [(SET, "wand_BaseColor")]
    assert not record.equal


def test_a_save_that_changes_the_uuid_fails_with_equal_bytes(stand: Stand) -> None:
    """Codex root review: the save replaces the UUID and the reopen keeps the new one; the bytes
    are equal, yet it is not the project that was exported."""
    first, initial = start(stand)
    stand.uuid_after_save = "another"
    _, record = reopened(cast(Wand, stand), first, initial)
    assert record.saved == record.reopened and record.differing == []
    assert record.unsaved != record.saved
    assert not record.same_project and not record.equal


def test_another_project_after_the_reopen_is_not_the_saved_one(stand: Stand) -> None:
    """A reopen that lands on another project (a new UUID) fails 3.3 with equal bytes."""
    first, initial = start(stand)

    def renewed(name: str, body: str) -> Any:
        found = Stand.probe(stand, name, body)
        return {**found, "uuid": "another"} if name == "reopened" else found

    stand.probe = renewed  # type: ignore[method-assign]
    _, record = reopened(cast(Wand, stand), first, initial)
    assert record.differing == [] and record.reopened != record.saved
    assert not record.same_project and not record.equal


def test_a_built_project_other_than_the_create_dst_stops_the_run(stand: Stand) -> None:
    """Codex root review: the project read before the first export must be the create step's
    `dst`, not another file of the same name."""
    stand.dst = stand.work / "elsewhere" / stand.project.name
    with pytest.raises(RunError, match="not the create step's"):
        initial_project(cast(Wand, stand))


def test_a_save_and_reopen_of_another_file_of_the_same_name_fails(stand: Stand) -> None:
    """Codex root review: the first export is of `dst`; the save and the reopen land on another
    `wand.spp` with the same UUID and maps. The receipt's file name alone would pass it."""
    first, initial = start(stand)
    stand.project = stand.work / "other" / stand.project.name
    _, record = reopened(cast(Wand, stand), first, initial)
    assert record.unsaved == record.saved == record.reopened and record.differing == []
    assert record.unsaved.file.name == record.exported
    assert record.initial != record.unsaved
    assert not record.same_project and not record.equal


def test_a_uuid_changed_between_the_first_export_and_the_save_fails(stand: Stand) -> None:
    """Codex root review: the UUID read before the save (and kept through the reopen) is not the
    one read before the first export."""
    first, initial = start(stand)
    stand.uuid = stand.uuid_after_save = "another"
    _, record = reopened(cast(Wand, stand), first, initial)
    assert record.unsaved == record.saved == record.reopened and record.differing == []
    assert record.initial.uuid == UUID != record.unsaved.uuid
    assert not record.same_project and not record.equal


def test_a_first_export_of_another_project_file_fails(stand: Stand) -> None:
    """The first export's receipt names another project file than the one saved and reopened."""
    stand.receipt_project = "other.spp"
    first, initial = start(stand)
    _, record = reopened(cast(Wand, stand), first, initial)
    assert record.unsaved == record.saved == record.reopened and record.differing == []
    assert record.exported == "other.spp"
    assert not record.same_project and not record.equal


def test_a_receipt_that_does_not_list_the_first_bytes_stops_the_run(stand: Stand) -> None:
    first, initial = start(stand)
    (stand.out / "wand_Normal.png").write_bytes(b"changed after the receipt")
    with pytest.raises(RunError, match="does not list"):
        reopened(cast(Wand, stand), first, initial)
    assert stand.calls == ["built", "export"]


def test_a_refused_export_after_the_reopen_is_recorded_not_passed(stand: Stand) -> None:
    """The refusal leaves the first export's `out` as it was and is recorded with its message."""
    first, initial = start(stand)
    stand.refuse = True
    kept, record = reopened(cast(Wand, stand), first, initial)
    assert record.refusal == "the padding is not exact"
    assert record.again == {} and record.differing == sorted(record.first)
    assert not record.equal
    assert kept.files[(SET, "wand_Normal")].read_bytes() == b"normal"


def test_a_refused_export_that_changed_its_out_folder_stops_the_run(stand: Stand) -> None:
    first, initial = start(stand)
    stand.refuse = True
    export = stand.export

    def leaking(diagnostic: bool = False) -> Call:
        (stand.out / "partial.png").write_bytes(b"partial")
        return export(diagnostic)

    stand.export = leaking  # type: ignore[method-assign]
    with pytest.raises(RunError, match="changed"):
        reopened(cast(Wand, stand), first, initial)


def test_a_refused_export_that_overwrote_a_file_stops_the_run(stand: Stand) -> None:
    """Panel review: the same paths with other bytes are a changed `out` too."""
    first, initial = start(stand)
    stand.refuse = True
    export = stand.export

    def overwriting(diagnostic: bool = False) -> Call:
        (stand.out / "wand_Normal.png").write_bytes(b"overwritten")
        return export(diagnostic)

    stand.export = overwriting  # type: ignore[method-assign]
    with pytest.raises(RunError, match="changed"):
        reopened(cast(Wand, stand), first, initial)


def test_a_save_that_leaves_the_project_unsaved_stops_the_run(stand: Stand) -> None:
    first, initial = start(stand)
    stand.stays_unsaved = True
    with pytest.raises(RunError, match="still needs saving"):
        reopened(cast(Wand, stand), first, initial)
    assert stand.calls == ["built", "export", "save"]


# --- decision 395: the Tier 1 run's exports are all the measure mode's --------------------------


def start_measured(stand: Stand) -> tuple[CandidateRun, Project]:
    """`start` with the first export in the diagnostic measure mode."""
    initial = initial_project(cast(Wand, stand))
    return exported(cast(Wand, stand), stand.export(diagnostic=True)), initial


def test_a_measured_first_export_is_exported_again_in_the_measure_mode(stand: Stand) -> None:
    """The export after the reopen runs in the first export's mode, its receipt marked and naming
    only decided refusals, and the record holds 3.3."""
    first, initial = start_measured(stand)
    _, record = reopened(cast(Wand, stand), first, initial, diagnostic=True)
    assert stand.modes == [True, True]
    assert record.equal, record


def test_a_measured_reopen_whose_receipt_is_unmarked_stops_the_run(stand: Stand) -> None:
    first, initial = start_measured(stand)
    stand.unmarked = True
    with pytest.raises(RunError, match="is not marked non_conformant"):
        reopened(cast(Wand, stand), first, initial, diagnostic=True)


def test_a_measured_reopen_bypassing_an_undecided_refusal_stops_the_run(stand: Stand) -> None:
    first, initial = start_measured(stand)
    stand.bypassed = [{"path": "wand_Normal.png", "refusal": "a resize is not recorded"}]
    with pytest.raises(RunError, match="no decision names"):
        reopened(cast(Wand, stand), first, initial, diagnostic=True)


# --- decision 417: a production export's exceptions, per file ------------------------------------


def test_a_production_receipt_names_its_exceptions_per_file(tmp_path: Path) -> None:
    """`relied_exceptions`: each file gets the ids its receipt's `exceptions_relied_on` lists for
    its path (EXC-013 for every padded file, EXC-014 for the Normal only), none without the
    field; a file the receipt does not list, or a file name it lists twice, stops the run."""
    files = {(SET, "wand_BaseColor"): tmp_path / "wand_BaseColor.png"}
    files[SET, "wand_Normal"] = tmp_path / "wand_Normal.png"
    listed = [{"path": p.name, "sha256": "0" * 64} for p in files.values()]
    receipt: dict[str, Any] = {
        "files": listed,
        "exceptions_relied_on": [
            {"exception_id": "EXC-013", "version": 1, "decision": "414", "paths": list(MAPS)},
            {
                "exception_id": "EXC-014",
                "version": 1,
                "decision": "417",
                "paths": ["wand_Normal.png"],
            },
        ],
    }
    assert relied_exceptions(receipt, files) == {
        (SET, "wand_BaseColor"): frozenset({"EXC-013"}),
        (SET, "wand_Normal"): frozenset({"EXC-013", "EXC-014"}),
    }
    assert relied_exceptions({"files": listed}, files) == dict.fromkeys(files, frozenset())
    with pytest.raises(RunError, match="does not list"):
        relied_exceptions({"files": listed[:1]}, files)
    with pytest.raises(RunError, match="twice"):
        relied_exceptions({"files": [*listed, listed[0]]}, files)
