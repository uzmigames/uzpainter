"""The operator step of texture goldens against a fake Painter (`texture_sheet.py`; task
`phase0.7_tier0-semantics-ui-cases` item 3.4): UI-set values are applied before `r1`, read
again after the reopen, recorded privately, and any value that differs from the sheet refuses
the golden before anything is written."""

from __future__ import annotations

import copy
import json
import re
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.job import Job, job_from_manifest
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.recorder.texture import record_texture_golden
from tools.parity.recorder.texture_sheet import texture_sheet

MakeSession = Callable[[Any], PainterSession]
METHOD = "Texture Set Settings/Height to normal method (uzp_plane)"
BLENDING = "Layers/Blending mode (step 5, BaseColor)"


def sheet_job(sample_job: Job, entries: list[tuple[str, str]]) -> Job:
    manifest = copy.deepcopy(sample_job.manifest)
    manifest["applied_settings"] += [
        {"name": name, "value": value, "applied_by": "operator_settings_sheet"}
        for name, value in entries
    ]
    return job_from_manifest(manifest)


class ScriptedOperator:
    """Answers like the UI operator: the panel shows `shown` (per sheet name fragment)."""

    def __init__(self, images: Path, shown: dict[str, str]) -> None:
        self.images, self.shown = images, shown
        self.questions: list[str] = []

    def tell(self, message: str) -> None:
        self.questions.append(message)

    def ask(self, question: str) -> str:
        self.questions.append(question)
        if question.startswith("Path of an image"):
            self.images.mkdir(parents=True, exist_ok=True)
            path = self.images / f"panel-{len(self.questions)}.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([len(self.questions)]))
            return str(path)
        for fragment, value in self.shown.items():
            if fragment in question:
                return value
        raise AssertionError(f"unexpected prompt {question!r}")


def test_sheet_names_are_parsed_into_targets(sample_job: Job) -> None:
    job = sheet_job(sample_job, [(METHOD, "Smooth (Sobel)"), (BLENDING, "Multiply")])
    method, blending = texture_sheet(job)
    assert (method.texture_set, method.value) == ("uzp_plane", "Smooth (Sobel)")
    assert (blending.node_step, blending.channel, blending.value) == (5, "BaseColor", "Multiply")


@pytest.mark.parametrize(
    ("name", "value", "error"),
    [
        ("Texture Set Settings/Normal mixing (uzp_plane)", "Combine", "names no target"),
        (METHOD, "Soft", "is not one of"),
        ("Layers/Blending mode (step 4, BaseColor)", "Passthrough", "inserts no layer"),
    ],
)
def test_unknown_or_impossible_sheet_entries_are_refused(
    sample_job: Job, name: str, value: str, error: str
) -> None:
    with pytest.raises(RecorderError, match=error):
        texture_sheet(sheet_job(sample_job, [(name, value)]))


def test_a_sheet_golden_without_an_operator_is_refused_before_painter_is_touched(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    world = fake.FakeWorld()
    job = sheet_job(sample_job, [(METHOD, "Sharp")])
    with pytest.raises(RecorderError, match="only Painter's UI can set"):
        record_texture_golden(make_session(world), job, work, inbox)
    assert not world.project_open and not inbox.exists() and not work.exists()


def test_ui_values_are_applied_reread_and_recorded_privately(
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    work: Path,
    inbox: Path,
    tmp_path: Path,
) -> None:
    world = fake.FakeWorld()
    job = sheet_job(sample_job, [(METHOD, "Smooth (Sobel)"), (BLENDING, "Multiply")])
    operator = ScriptedOperator(
        tmp_path / "images",
        {"Height to normal method": "Smooth (Sobel)", "Blending mode of layer": "Multiply"},
    )
    run = record_texture_golden(make_session(world), job, work, inbox, operator=operator)
    record = json.loads((run / "record.json").read_text(encoding="utf-8"))
    for recording in record["recordings"]:
        kinds = [o["kind"] for o in recording["outputs"]]
        assert kinds.count("operator_recorded_settings") == 1
        assert kinds.count("settings_panel_evidence") == 2
        (entries,) = [
            o["entries"] for o in recording["outputs"] if o["kind"] == "operator_recorded_settings"
        ]
        assert entries == [
            {
                "panel": "Texture Set Settings",
                "setting": "Height to normal method (uzp_plane)",
                "value": "Smooth (Sobel)",
            },
            {
                "panel": "Layers",
                "setting": "Blending mode (step 5, BaseColor)",
                "value": "Multiply",
            },
        ]
    applied = [q for q in operator.questions if "(sheet: " in q]
    reread = [q for q in operator.questions if q.endswith("value shown now:")]
    assert applied[0] == (
        "[Texture Set Settings] Height to normal method of texture set 'uzp_plane' "
        "(sheet: Smooth (Sobel)):"
    )
    assert re.fullmatch(
        r"\[Layers\] Blending mode of layer 'Fill layer \d+' in channel 'BaseColor' "
        r"\(sheet: Multiply\):",
        applied[1],
    )
    assert len(applied) == 2
    assert len(reread) == 2, "after the reopen the values are read, not applied"
    assert world.active_stacks.count("uzp_plane") == 4
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    stored = {r["kind"] for r in manifest["private_records"]}
    assert "settings_panel_evidence" in stored, "panel images are private blobs named by hash"


@pytest.mark.parametrize(
    ("shown", "error"),
    [
        ({"Height to normal method": "Sharp", "Blending mode of layer": "Multiply"}, "panel shows"),
        ({"Height to normal method": "Smooth (Sobel)", "Blending mode of layer": "Screen"}, ""),
    ],
)
def test_a_ui_value_that_differs_from_the_sheet_refuses_the_golden(
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    work: Path,
    inbox: Path,
    tmp_path: Path,
    shown: dict[str, str],
    error: str,
) -> None:
    """Item 3.4: the widget shows another value, or the documented readback disagrees."""
    world = fake.FakeWorld()
    blending = "Screen" if error == "" else "Multiply"
    job = sheet_job(sample_job, [(METHOD, "Smooth (Sobel)"), (BLENDING, blending)])
    operator = ScriptedOperator(tmp_path / "images", shown)
    with pytest.raises(RecorderError, match=error or "Node.get_blending_mode reads 'Multiply'"):
        record_texture_golden(make_session(world), job, work, inbox, operator=operator)
    assert not inbox.exists(), "a refused golden writes nothing"
    assert not world.project_open


def test_refresh_and_study_record_a_sheet_golden_with_the_ui_operator(
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    work: Path,
    inbox: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The envelope's corpus dispatch gives a sheet golden the UI operator by default."""
    from datetime import UTC, datetime

    from tools.parity.envelope import corpus

    job = sheet_job(sample_job, [(METHOD, "Sharp")])
    operator = ScriptedOperator(tmp_path / "images", {"Height to normal method": "Sharp"})
    made: list[Path] = []

    def ui_operator(at: Path) -> ScriptedOperator:
        made.append(at)
        return operator

    monkeypatch.setattr(corpus, "ui_operator", ui_operator)
    run = corpus.record_golden(
        make_session(fake.FakeWorld()), job.manifest, work, inbox, lambda: datetime.now(UTC)
    )
    assert made == [work] and (run / "READY").is_file()


RENAME = "Texture Set List/Name (uzp_plane)"


class RenamingOperator(ScriptedOperator):
    """The UI operator renaming a texture set in the Texture Set List: the fake's set takes the
    typed name and keeps the name it was imported under (`TextureSet.original_name`)."""

    def __init__(self, images: Path, world: Any, typed: str, shown: str) -> None:
        super().__init__(images, {"Name of texture set": shown})
        self.world, self.typed = world, typed

    def ask(self, question: str) -> str:
        if "(sheet: " in question:
            self.world.texture_set = self.typed
        return super().ask(question)


def test_a_texture_set_renamed_in_the_ui_is_read_back_through_the_api(
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    work: Path,
    inbox: Path,
    tmp_path: Path,
) -> None:
    """Decision 093: the sheet names the set by the name it was imported under; the operator
    renames it before r1, and `TextureSet.name` must read the sheet's value before r1 and
    after the reopen."""
    world = fake.FakeWorld()
    job = sheet_job(sample_job, [(RENAME, "renamed0")])
    (entry,) = texture_sheet(job)
    assert (entry.panel, entry.texture_set, entry.value) == (
        "Texture Set List",
        "uzp_plane",
        "renamed0",
    )
    operator = RenamingOperator(tmp_path / "images", world, "renamed0", "renamed0")
    run = record_texture_golden(make_session(world), job, work, inbox, operator=operator)
    applied = [q for q in operator.questions if "(sheet: " in q]
    reread = [q for q in operator.questions if q.endswith("value shown now:")]
    assert applied == ["[Texture Set List] Name of texture set 'uzp_plane' (sheet: renamed0):"]
    assert reread == ["[Texture Set List] Name of texture set 'renamed0': value shown now:"]
    record = json.loads((run / "record.json").read_text(encoding="utf-8"))
    for recording in record["recordings"]:
        maps = [o["output_id"] for o in recording["outputs"] if o["kind"] == "exported_map"]
        assert maps and all(m.startswith("renamed0/") for m in maps)


def test_a_rename_the_api_does_not_read_refuses_the_golden(
    fake: types.ModuleType,
    make_session: MakeSession,
    sample_job: Job,
    work: Path,
    inbox: Path,
    tmp_path: Path,
) -> None:
    world = fake.FakeWorld()
    job = sheet_job(sample_job, [(RENAME, "renamed0")])
    operator = RenamingOperator(tmp_path / "images", world, "other", "renamed0")
    with pytest.raises(RecorderError, match=r"TextureSet.name reads 'other'"):
        record_texture_golden(make_session(world), job, work, inbox, operator=operator)
    assert not inbox.exists()


@pytest.mark.parametrize("value", ["renamed 0", "a/b", "$textureSet", ""])
def test_a_texture_set_name_with_other_characters_is_refused(sample_job: Job, value: str) -> None:
    with pytest.raises(RecorderError, match="not a texture set name"):
        texture_sheet(sheet_job(sample_job, [(RENAME, value)]))
