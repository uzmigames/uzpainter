"""The Iray procedure probe against a fake Painter and a scripted operator (task
`phase0.6_render-reference-procedure`, items 2.1-2.8): every step runs, every saved render is
fence-checked, the analysis answers every probe row, and the answers merge into the report."""

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
    ROTATED_CAMERA,
    SAMPLES,
    SIZE,
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
BACKGROUND = (13, 13, 13)
PERSISTED = {
    "Min Sample": "37",
    "Max Sample": "37",
    "Max Time": "17",
    "Caustic Sampler": "on",
    "Firefly Filter": "on",
    "Width": "320",
    "Height": "192",
    "Environment Exposure": "0.5",
    "Environment Rotation": "33",
    "Emissive Intensity": "2",
    "IOR": "1.33",
}


def coverage(rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> list[int]:
    position = orbit_position(rotation, CAMERA_DISTANCE, CAMERA_HYPOTHESIS)
    camera = Camera(position, rotation, FIELD_OF_VIEW, "Perspective")
    mesh = load_obj(fixtures.FIXTURE_DIR / "sphere.obj")
    return coverage_rows(mesh, camera, SIZE, SIZE, CAMERA_HYPOTHESIS)


def synthetic(name: str) -> list[tuple[int, ...]]:
    """What Save Render would hold for each probe render (a plausible stand-in)."""
    rows = coverage(ROTATED_CAMERA if name == "H" else (0.0, 0.0, 0.0))
    noise = random.Random(7)
    pixels: list[tuple[int, ...]] = []
    for y in range(SIZE):
        for x in range(SIZE):
            inside = rows[y] >> x & 1
            base = 60 + (x + y) // 8
            if name == "D":
                pixels.append((255, 0, 255))
                continue
            if not inside:
                corner = name == "E" and (x - SIZE / 2) ** 2 + (y - SIZE / 2) ** 2 > (SIZE / 2) ** 2
                pixels.append((5, 5, 5) if corner else BACKGROUND)
                continue
            value = {
                "C": base * 4 // 5,
                "G": base + 20,
                "F": base + 20 + noise.randint(-3, 3),
                "I": base + noise.randint(-20, 20),
                "J": base + (25 if (x // 16) % 2 else 0),
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
        self.phase = "defaults"

    def tell(self, message: str) -> None:
        self.prompts.append(message)
        if "save the image as: " in message:
            self.target = Path(message.split("save the image as: ", 1)[1])
        if "saved, closed and reopened" in message:
            self.phase = "reopened"
        if "created a new project" in message:
            self.phase = "new"

    def ask(self, question: str) -> str:
        self.prompts.append(question)
        if question.startswith("Path of"):
            return str(self.panel)
        if "(sheet: " in question:
            shown = question.split("(sheet: ", 1)[1].rsplit("):", 1)[0]
            return shown.removesuffix(" min").removesuffix(" px")
        if question.endswith("value shown now:"):
            setting = question.split("] ", 1)[1].split(":", 1)[0]
            if self.phase == "reopened":
                return PERSISTED.get(setting, "0")
            return "1.5" if setting == "IOR" else "0"
        answers = {
            "Status shown": "Done",
            "Iterations shown": str(SAMPLES),
            "Rendering time shown": "12.5",
            "Open Save Render": "PNG, JPEG, OpenEXR (exr)",
            "Any other option": "none",
            "Does Status": "yes",
            "In Display Settings, is": "no",
            "Does the Iray view": "yes",
            "What did Status read": "Rendering",
        }
        for prefix, answer in answers.items():
            if question.startswith(prefix):
                return answer
        if question.startswith("Press Enter once the file is saved"):
            assert self.target is not None
            name = self.target.stem
            if self.target.suffix == ".exr":
                value = 0.25 if name == "A_exr" else 0.2
                self.target.write_bytes(fixtures.exr_half_rgb(4, 4, [(value, value, value)] * 16))
            else:
                key = "A" if name == "F" and self.stale_previous else name
                self.fake.write_png(self.target, SIZE, SIZE, synthetic(key), 8)
            return ""
        if "press Enter" in question:
            return ""
        raise AssertionError(f"unexpected prompt {question!r}")


def run(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path, **operator: Any
) -> tuple[Path, ProbeOperator]:
    script = ProbeOperator(fake, tmp_path / "operator", **operator)
    directory = run_probe(make_session(fake.FakeWorld()), script, tmp_path / "oracle-work")
    return directory, script


def test_probe_answers_every_probe_row(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path
) -> None:
    directory, script = run(fake, make_session, tmp_path)
    data = json.loads((directory / "probe.json").read_text(encoding="utf-8"))
    answers = data["answers"]
    assert set(answers) == set(ROWS) - {"readiness", "display_view_transform"}
    assert sorted(data["renders"]) == sorted(
        ["A", "A_exr", "B", "C", "C_exr", "D", "E", "F", "G", "H", "I", "J"]
    )
    assert answers["random_seed"]["bit_identical_same_session"] is True
    assert answers["random_seed"]["status"] == "uncontrolled"
    assert answers["save_render"]["png"]["tone_mapping_baked"] is True
    assert answers["save_render"]["exr"]["tone_mapping_changes_file"] is True
    assert answers["colour_lut"]["saved_render"] is True
    assert answers["display_settings"]["post_effect_vignette"] is True
    assert answers["stale_frame"]["outcome"] == "current_frame"
    assert answers["denoiser"]["status"] == "confirmed_by_probe"
    assert answers["denoiser"]["correlation"] < 0.3
    assert answers["height"]["interior_shading_changed"] is True
    assert answers["height"]["outline_changed"] == 0
    assert answers["camera_projection"]["confirmed_orders"] == [CAMERA_HYPOTHESIS]
    assert answers["camera_projection"]["unrotated_mismatches"] == 0
    assert answers["pixel_route"]["route"] == "save_render"
    persistence = answers["iray_settings"]["persistence"]
    assert persistence["Iray Settings/Max Time"]["kept_by_project"] is True
    assert persistence["Iray Settings/Max Time"]["kept_by_session"] is False
    assert answers["default_mdl_parameters"]["defaults"]["Viewer and MDL Settings/IOR"] == "1.5"
    for name, entry in data["files"].items():
        assert (directory / entry["file"]).is_file(), name
    assert data["camera_probe"]["readback"]["camera.rotation"] == list(ROTATED_CAMERA)
    assert any("Environment Rotation to 90" in p for p in script.prompts)

    merged = merge_probe(load_answers(), directory / "probe.json")
    assert problems(merged) == []
    assert pending(merged) == []
    assert "random_seed" in merged["uncontrolled"]


def test_stale_save_render_is_reported(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path
) -> None:
    directory, _ = run(fake, make_session, tmp_path, stale_previous=True)
    answers = json.loads((directory / "probe.json").read_text(encoding="utf-8"))["answers"]
    assert answers["stale_frame"]["outcome"] == "previous_frame"


def test_unfinished_render_stops_the_probe(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path
) -> None:
    script = ProbeOperator(fake, tmp_path / "operator")
    original = script.ask

    def not_done(question: str) -> str:
        return "no" if question.startswith("Does Status") else original(question)

    script.ask = not_done  # type: ignore[method-assign]
    with pytest.raises(RecorderError, match="has not finished"):
        run_probe(make_session(fake.FakeWorld()), script, tmp_path / "oracle-work")
    (kept,) = (tmp_path / "oracle-work" / "iray-probe").glob("*/probe.json")
    data = json.loads(kept.read_text(encoding="utf-8"))
    assert "has not finished" in data["failed"]
    assert data["entries"]["probe_sheet"] and "answers" not in data


def test_render_saved_before_the_fence_is_refused(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path
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
        run_probe(make_session(fake.FakeWorld()), script, tmp_path / "oracle-work")
