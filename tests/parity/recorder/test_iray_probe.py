"""The Iray procedure probe of the fixed pipeline against a fake Painter and a scripted operator
(task `phase0.6_render-reference-procedure`, decision 038): every step runs, every saved render
is fence-checked, the analysis answers every row of 07 §2.1 and both presets, and the answers
merge into the report."""

from __future__ import annotations

import json
import os
import random
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.capture import StaleCaptureError
from tools.parity.recorder.iray_probe import (
    CAMERA_DISTANCE,
    CAMERA_HYPOTHESIS,
    FIELD_OF_VIEW,
    NUDGED_FIELD_OF_VIEW,
    REF_MATCH_HDRI_SHA256,
    ROTATED_CAMERA,
    SAMPLES,
    run_probe,
)
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.render_procedure import fixtures
from tools.parity.render_procedure.answers import (
    ROWS,
    load_answers,
    merge_probe,
    pending,
    problems,
)
from tools.parity.render_procedure.projection import (
    Camera,
    coverage_rows,
    load_obj,
    orbit_position,
)

MakeSession = Callable[[Any], PainterSession]
SIZE = 48
V2_BACKGROUND = (89, 89, 89)
REF_BACKGROUND = (141, 142, 148)


def coverage(rotation: tuple[float, float, float], fov: float = FIELD_OF_VIEW) -> list[int]:
    position = orbit_position(rotation, CAMERA_DISTANCE, CAMERA_HYPOTHESIS)
    camera = Camera(position, rotation, fov, "Perspective")
    mesh = load_obj(fixtures.FIXTURE_DIR / "sphere.obj")
    return coverage_rows(mesh, camera, SIZE, SIZE, CAMERA_HYPOTHESIS)


def synthetic(name: str) -> list[tuple[int, ...]]:
    """What Save Render would hold for each probe render (a plausible stand-in)."""
    if name == "H":
        rows = coverage(ROTATED_CAMERA)
    elif name in ("F", "G"):
        rows = coverage((0.0, 0.0, 0.0), NUDGED_FIELD_OF_VIEW)
    else:
        rows = coverage((0.0, 0.0, 0.0))
    noise = random.Random(7)
    pixels: list[tuple[int, ...]] = []
    for y in range(SIZE):
        for x in range(SIZE):
            if not rows[y] >> x & 1:
                pixels.append(REF_BACKGROUND if name == "R" else V2_BACKGROUND)
                continue
            base = 140 + (x + y) // 4
            value = {
                "G": base + 20,
                "F": base + 20 + noise.randint(-3, 3),
                "I": base + noise.randint(-30, 30),
                "J": base + (25 if (x // 8) % 2 else 0),
            }.get(name, base)
            pixels.append((value, value // 2 + 20, 40))
    return pixels


class ProbeOperator:
    def __init__(self, fake: types.ModuleType, folder: Path, stale_previous: bool = False) -> None:
        self.fake = fake
        self.target: Path | None = None
        self.stale_previous = stale_previous
        self.prompts: list[str] = []
        folder.mkdir(parents=True, exist_ok=True)
        self.panel = folder / "panel.png"
        fake.write_png(self.panel, 1, 1, [(7, 7, 7)], 8)
        self.view = folder / "view.png"
        fake.write_png(self.view, 40, 30, [(9, 9, 9)] * 1200, 8)
        self.shown: dict[str, str] = {}

    def tell(self, message: str) -> None:
        self.prompts.append(message)
        if "save the image as: " in message:
            self.target = Path(message.split("save the image as: ", 1)[1])

    def ask(self, question: str) -> str:
        self.prompts.append(question)
        if question.startswith("Path of an image of the 3D viewport"):
            return str(self.view)
        if question.startswith("Path of an image of"):
            return str(self.panel)
        if "(sheet: " in question:
            setting = question.split("] ", 1)[1].split(" (sheet: ", 1)[0]
            shown = question.split("(sheet: ", 1)[1].rsplit("):", 1)[0]
            shown = shown.removesuffix(" s").removesuffix(" px")
            self.shown[setting] = shown
            return shown
        if question.startswith("Set "):
            setting, value = question[4:].split(" / ", 1)[1].rsplit(" to ", 1)
            self.shown[setting] = value.removesuffix(", then press Enter.")
            return ""
        if question.endswith("value shown now:"):
            setting = question.split("] ", 1)[1].split(":", 1)[0]
            return self.shown.get(setting, "Infinite sphere")
        answers = {
            "Status shown": "Done",
            "Iterations shown": str(SAMPLES),
            "Rendering time shown": "3",
            "Open Save Render": "PNG (*.png), EXR (*.exr)",
            "Any other option": "none",
            "Does Status": "yes",
            "What did Status read": "Rendering",
        }
        for prefix, answer in answers.items():
            if question.startswith(prefix):
                return answer
        if question.startswith("Press Enter once the file is saved"):
            assert self.target is not None
            name = self.target.stem
            if self.target.suffix == ".exr":
                self.target.write_bytes(fixtures.exr_half_rgb(4, 4, [(0.1, 0.1, 0.1)] * 16))
            else:
                key = "A" if name == "F" and self.stale_previous else name
                self.fake.write_png(self.target, SIZE, SIZE, synthetic(key), 8)
            return ""
        raise AssertionError(f"unexpected prompt {question!r}")


@pytest.fixture
def hdri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "ref-match.exr"
    path.write_bytes(b"authored ref_match hdri stand-in")
    from tools.parity.recorder import iray_probe
    from tools.parity.recorder.job import sha256_file

    monkeypatch.setattr(iray_probe, "REF_MATCH_HDRI_SHA256", sha256_file(path))
    monkeypatch.setenv("OCIO", "C:/Painter/resources/ocio/substance/config.ocio")
    return path


def run(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path, hdri: Path, **operator: Any
) -> tuple[Path, ProbeOperator]:
    script = ProbeOperator(fake, tmp_path / "operator", **operator)
    directory = run_probe(
        make_session(fake.FakeWorld()), script, tmp_path / "oracle-work", hdri, size=SIZE
    )
    return directory, script


def test_probe_answers_every_row_of_the_fixed_pipeline(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path, hdri: Path
) -> None:
    directory, script = run(fake, make_session, tmp_path, hdri)
    data = json.loads((directory / "probe.json").read_text(encoding="utf-8"))
    answers = data["answers"]
    assert set(answers) == set(ROWS) | {"presets"}
    assert sorted(data["renders"]) == sorted(["A", "A_exr", "B", "F", "G", "H", "I", "J", "R"])
    assert answers["random_seed"]["bit_identical_same_session"] is True
    assert answers["random_seed"]["status"] == "uncontrolled"
    assert answers["save_render"]["png"]["display_referred"] is True
    assert answers["display_view_transform"]["status"] == "confirmed_by_probe"
    for row in ("colour_lut", "display_settings", "default_mdl_parameters"):
        assert answers[row]["status"] == "not_required" and "pinned" in answers[row]
    assert answers["iray_settings"]["pinned"]["Iray Settings/Max Sample"] == SAMPLES
    assert answers["stale_frame"]["outcome"] == "current_frame"
    assert answers["denoiser"]["status"] == "confirmed_by_probe"
    assert answers["denoiser"]["correlation"] < 0.3
    assert answers["height"]["interior_shading_changed"] is True
    assert answers["height"]["outline_changed"] == 0
    assert CAMERA_HYPOTHESIS in answers["camera_projection"]["confirmed_orders"]
    assert answers["camera_projection"]["unrotated_mismatches"] == 0
    assert answers["pixel_route"]["route"] == "save_render"
    assert answers["pixel_route"]["live_view"] == [40, 30]
    assert answers["pixel_route"]["live_view_one_to_one"] is False
    assert answers["presets"]["ref_match"]["applied_and_verified"] is True
    assert answers["presets"]["base_color"]["applied_and_verified"] is True
    for name, entry in data["files"].items():
        assert (directory / entry["file"]).is_file(), name
    assert data["camera_probe"]["readback"]["camera.rotation"] == list(ROTATED_CAMERA)
    assert any("Clear color value to 8D8E94" in p for p in script.prompts)

    merged = merge_probe(load_answers(), directory / "probe.json")
    assert problems(merged) == []
    assert pending(merged) == []
    assert "random_seed" in merged["uncontrolled"]
    assert merged["presets"]["ref_match"]["applied_and_verified"] is True


def test_stale_save_render_is_reported(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path, hdri: Path
) -> None:
    directory, _ = run(fake, make_session, tmp_path, hdri, stale_previous=True)
    answers = json.loads((directory / "probe.json").read_text(encoding="utf-8"))["answers"]
    assert answers["stale_frame"]["outcome"] == "previous_frame"


def test_unfinished_render_stops_the_probe(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path, hdri: Path
) -> None:
    script = ProbeOperator(fake, tmp_path / "operator")
    original = script.ask

    def not_done(question: str) -> str:
        return "no" if question.startswith("Does Status") else original(question)

    script.ask = not_done  # type: ignore[method-assign]
    with pytest.raises(RecorderError, match="has not finished"):
        run_probe(make_session(fake.FakeWorld()), script, tmp_path / "oracle-work", hdri, size=SIZE)
    (kept,) = (tmp_path / "oracle-work" / "iray-probe").glob("*/probe.json")
    data = json.loads(kept.read_text(encoding="utf-8"))
    assert "has not finished" in data["failed"]
    assert data["entries"]["v2"] and "answers" not in data


def test_render_saved_before_the_fence_is_refused(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path, hdri: Path
) -> None:
    script = ProbeOperator(fake, tmp_path / "operator")
    original = script.ask

    def backdated(question: str) -> str:
        answer = original(question)
        if question.startswith("Press Enter once the file is saved") and script.target:
            old = script.target.stat().st_mtime_ns - 3_600_000_000_000
            os.utime(script.target, ns=(old, old))
        return answer

    script.ask = backdated  # type: ignore[method-assign]
    with pytest.raises(StaleCaptureError):
        run_probe(make_session(fake.FakeWorld()), script, tmp_path / "oracle-work", hdri, size=SIZE)


def test_legacy_colour_management_is_refused(
    fake: types.ModuleType,
    make_session: MakeSession,
    tmp_path: Path,
    hdri: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OCIO")
    with pytest.raises(RecorderError, match="colour managed"):
        run(fake, make_session, tmp_path, hdri)


def test_a_different_ref_match_hdri_is_refused(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path, hdri: Path
) -> None:
    other = tmp_path / "other.exr"
    other.write_bytes(b"another file")
    assert REF_MATCH_HDRI_SHA256  # the standard's hash stays a module constant
    with pytest.raises(RecorderError, match="not the ref_match HDRI"):
        run(fake, make_session, tmp_path, other)
