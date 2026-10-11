"""Iray capture path and operator form against a fake Painter and a scripted operator
(task items 2.4, 2.5, 2.6 for Tier 3; 07-preview-and-render-parity.md §2.2; current-frame
verification against the fixture projected from the recorded camera, task
`phase0.6_render-reference-procedure` item 3.2)."""

from __future__ import annotations

import hashlib
import json
import os
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.capture import StaleCaptureError
from tools.parity.recorder.iray import (
    K_TIMES_SAMPLES,
    SEPARATE_SESSION,
    record_iray_reference,
    settings_sheet,
)
from tools.parity.recorder.job import Job, job_from_manifest
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.render_procedure.projection import Camera, coverage_rows, load_obj
from tools.parity.schemas import REPO_ROOT, Schema, record_problems, validation_errors

MakeSession = Callable[[Any], PainterSession]
S = 16
SIZE = 32
SPHERE = REPO_ROOT / "parity" / "fixtures" / "render-procedure" / "sphere.obj"
CAMERA_Z = 60.0


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def object_pixels(
    fill: tuple[int, int, int], camera_z: float = CAMERA_Z, shift: int = 0
) -> list[tuple[int, ...]]:
    """A render of the sphere seen from (0, 0, camera_z): `fill` where the sphere projects."""
    camera = Camera((0.0, 0.0, camera_z), (0.0, 0.0, 0.0), 40.0, "Perspective")
    rows = coverage_rows(load_obj(SPHERE), camera, SIZE, SIZE)
    return [
        fill if 0 <= x - shift < SIZE and rows[y] >> (x - shift) & 1 else (0, 0, 0)
        for y in range(SIZE)
        for x in range(SIZE)
    ]


def sheet_setting(name: str, value: Any) -> dict[str, Any]:
    return {"name": name, "value": value, "applied_by": "recorder_api"}


@pytest.fixture
def iray_job(tmp_path: Path) -> Job:
    return make_iray_job(tmp_path)


def make_iray_job(
    tmp_path: Path,
    camera_z: float = CAMERA_Z,
    rotation: list[float] | None = None,
    capture: list[dict[str, Any]] | None = None,
) -> Job:
    root = tmp_path / "repo"
    (root / "fixtures").mkdir(parents=True, exist_ok=True)
    mesh = root / "fixtures" / "sphere.obj"
    mesh.write_bytes(SPHERE.read_bytes())
    environment = root / "fixtures" / "constant.exr"
    environment.write_bytes(b"authored constant environment")

    def authored(input_id: str, kind: str, path: Path) -> dict[str, Any]:
        return {
            "input_id": input_id,
            "kind": kind,
            "path": path.relative_to(root).as_posix(),
            "sha256": digest(path),
            "provenance": {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
        }

    def operator_setting(name: str, value: Any, unit: str | None = None) -> dict[str, Any]:
        item = {"name": name, "value": value, "applied_by": "operator_settings_sheet"}
        return item | ({"unit": unit} if unit else {})

    manifest = {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": "tests/tier3/sphere-constant",
        "tier": "3",
        "domain": "tier3/sphere-constant",
        "description": "Synthetic Tier 3 job for the recorder tests.",
        "inputs": [
            authored("sphere", "mesh", mesh),
            authored("env", "environment", environment),
        ],
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": "substance_painter_documented_python_api",
            "steps": [
                {"step": 1, "call": "substance_painter.project.create", "args": {"mesh": "sphere"}},
                {
                    "step": 2,
                    "call": "substance_painter.display.Camera.position",
                    "args": {"value": [0.0, 0.0, camera_z]},
                },
                {
                    "step": 3,
                    "call": "substance_painter.display.Camera.rotation",
                    "args": {"value": rotation or [0.0, 0.0, 0.0]},
                },
                {
                    "step": 4,
                    "call": "substance_painter.display.Camera.aperture",
                    "args": {"value": 0.0},
                },
                {
                    "step": 5,
                    "call": "substance_painter.display.set_environment_resource",
                    "args": {"environment": "env"},
                },
                {
                    "step": 6,
                    "call": "substance_painter.display.set_tone_mapping",
                    "args": {"function": "Linear"},
                },
            ],
        },
        "applied_settings": [
            operator_setting("Iray Settings/Min Sample", S),
            operator_setting("Iray Settings/Max Sample", S),
            operator_setting("Iray Settings/Max Time", 10, "min"),
            operator_setting("Iray Settings/Width", SIZE, "px"),
            operator_setting("Iray Settings/Height", SIZE, "px"),
            operator_setting("Iray Settings/Firefly Filter", False),
            operator_setting("Viewer and MDL Settings/Environment Exposure", 0.0, "EV"),
            *(
                capture
                if capture is not None
                else [
                    sheet_setting("capture.encoding", "display_referred"),
                    sheet_setting("capture.procedure", "iray-capture/1"),
                    sheet_setting("capture.route", "save_render"),
                ]
            ),
        ],
        "uncontrolled_settings": ["denoiser"],
        "expectations": [],
        "software": {
            "painter": {
                "product": "Adobe Substance 3D Painter",
                "version": "12.1.0",
                "build_id": "12.1.0+js-api.1.1.20",
            },
            "uzpainter_build_hash": None,
        },
        "private_records": [],
    }
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    return job_from_manifest(manifest, repo_root=root)


class ScriptedOperator:
    """Answers the form like an operator would; `save` writes the render on Save Render."""

    def __init__(
        self,
        fake: types.ModuleType,
        panel_dir: Path,
        samples: int,
        overrides: dict[str, str] | None = None,
        render: list[tuple[int, ...]] | None = None,
        backdate: bool = False,
    ) -> None:
        self.fake = fake
        self.samples = samples
        self.overrides = overrides or {}
        self.render = render or object_pixels((180, 120, 60))
        self.backdate = backdate
        self.target: Path | None = None
        self.messages: list[str] = []
        panel_dir.mkdir(parents=True, exist_ok=True)
        self.panel = panel_dir / "panel.png"
        fake.write_png(self.panel, 1, 1, [(7, 7, 7)], 8)

    def tell(self, message: str) -> None:
        self.messages.append(message)
        if "save the image as: " in message:
            self.target = Path(message.split("save the image as: ", 1)[1])

    def ask(self, question: str) -> str:
        for key, answer in self.overrides.items():
            if key in question:
                return answer
        if question.startswith("["):
            return question.split("(sheet: ", 1)[1].split(")", 1)[0].split(" ", 1)[0]
        if question.startswith("Path of an image"):
            return str(self.panel)
        if question.startswith("Status"):
            return "Done"
        if question.startswith("Iterations"):
            return str(self.samples)
        if question.startswith("Rendering time"):
            return "42.5"
        if question.startswith("Press Enter"):
            assert self.target is not None
            self.fake.write_png(self.target, SIZE, SIZE, self.render, 8)
            if self.backdate:
                old = self.target.stat().st_mtime_ns - 3_600_000_000_000
                os.utime(self.target, ns=(old, old))
            return ""
        raise AssertionError(f"unexpected question {question!r}")


def record(
    fake: types.ModuleType,
    make_session: MakeSession,
    job: Job,
    work: Path,
    inbox: Path,
    condition: str,
    session: PainterSession | None = None,
    k: int | None = None,
    **operator: Any,
) -> Path | None:
    samples = S * (k or 1)
    script = ScriptedOperator(fake, work.parent / "panels", samples, **operator)
    return record_iray_reference(
        session or make_session(fake.FakeWorld()), job, condition, script, work, inbox, k
    )


def test_reference_golden_is_assembled_from_three_sessions(
    fake: types.ModuleType, make_session: MakeSession, iray_job: Job, work: Path, inbox: Path
) -> None:
    assert record(fake, make_session, iray_job, work, inbox, SEPARATE_SESSION) is None
    assert record(fake, make_session, iray_job, work, inbox, SEPARATE_SESSION) is None
    run = record(fake, make_session, iray_job, work, inbox, K_TIMES_SAMPLES, k=4)
    assert run is not None
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    conditions = sorted(r["condition"] for r in data["recordings"])
    assert conditions == [K_TIMES_SAMPLES, SEPARATE_SESSION, SEPARATE_SESSION]
    references = [
        o for r in data["recordings"] for o in r["outputs"] if o["kind"] == "iray_reference"
    ]
    assert sorted(o["samples"] for o in references) == [S, S, 4 * S]
    reference = references[0]
    assert reference["convergence"]["max_time_s"] == 600.0
    assert reference["storage_format"]["encoding"] == "display_referred"
    assert reference["uncontrolled_settings"] == ["denoiser"]
    assert reference["current_frame_verified"] is True
    render_state = data["key"]["render_state"]
    assert render_state["camera.position"] == [0.0, 0.0, CAMERA_Z]
    assert render_state["camera.aperture"] == 0.0
    assert render_state["environment_url"] == "resource://project0/env"
    assert render_state["tone_mapping"] == "Linear"
    assert render_state["scene_bounding_box"]["dimensions"] == [20.0, 20.0, 20.0]
    kinds = {r["kind"] for r in manifest["private_records"]}
    assert kinds == {
        "private_oracle_record",
        "iray_reference",
        "settings_panel_evidence",
        "oracle_environment_record",
    }
    assert not (work / "iray-staging" / "tests__tier3__sphere-constant").exists()
    route = {s["name"]: s["value"] for s in manifest["applied_settings"]}
    assert (route["capture.procedure"], route["capture.route"]) == ("iray-capture/1", "save_render")


def test_operator_entries_and_panel_images_are_private_evidence(
    fake: types.ModuleType, make_session: MakeSession, iray_job: Job, work: Path, inbox: Path
) -> None:
    for condition, k in ((SEPARATE_SESSION, None), (SEPARATE_SESSION, None), (K_TIMES_SAMPLES, 2)):
        run = record(fake, make_session, iray_job, work, inbox, condition, k=k)
    assert run is not None
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    first = data["recordings"][0]["outputs"]
    (settings,) = [o for o in first if o["kind"] == "operator_recorded_settings"]
    entries = {(e["panel"], e["setting"]): e["value"] for e in settings["entries"]}
    assert entries[("Iray Settings", "Max Time")] == 10
    assert entries[("Iray Settings", "Firefly Filter")] is False
    panels = sorted(o["panel"] for o in first if o["kind"] == "settings_panel_evidence")
    assert panels == ["Iray Settings", "Viewer and MDL Settings"]
    k_entries = next(
        o["entries"]
        for r in data["recordings"]
        if r["condition"] == K_TIMES_SAMPLES
        for o in r["outputs"]
        if o["kind"] == "operator_recorded_settings"
    )
    assert {e["setting"]: e["value"] for e in k_entries}["Min Sample"] == 2 * S


def test_same_session_cannot_record_two_references(
    fake: types.ModuleType, make_session: MakeSession, iray_job: Job, work: Path, inbox: Path
) -> None:
    transport = fake.LocalTransport(fake.FakeWorld())  # one Painter process

    def same_process() -> PainterSession:
        return PainterSession(transport, sleep=lambda seconds: None)

    record(fake, make_session, iray_job, work, inbox, SEPARATE_SESSION, session=same_process())
    with pytest.raises(RecorderError, match="restart Painter"):
        record(fake, make_session, iray_job, work, inbox, SEPARATE_SESSION, session=same_process())


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"Max Sample": "32"}, "sheet says"),
        ({"Status": "Rendering"}, "not converged"),
        ({"Iterations": "15"}, "not converged"),
        ({"Rendering time": "600"}, "not converged"),
    ],
)
def test_unqualified_reference_is_refused(
    fake: types.ModuleType,
    make_session: MakeSession,
    iray_job: Job,
    work: Path,
    inbox: Path,
    overrides: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(RecorderError, match=message):
        record(fake, make_session, iray_job, work, inbox, SEPARATE_SESSION, overrides=overrides)
    assert not inbox.exists()
    assert not (work / "iray-staging").exists()


def test_stale_render_is_refused(
    fake: types.ModuleType, make_session: MakeSession, iray_job: Job, work: Path, inbox: Path
) -> None:
    with pytest.raises(StaleCaptureError, match="before the last applied instruction"):
        record(fake, make_session, iray_job, work, inbox, SEPARATE_SESSION, backdate=True)
    assert not (work / "iray-staging").exists()


def test_wrong_frame_is_refused_by_the_silhouette(
    fake: types.ModuleType, make_session: MakeSession, iray_job: Job, work: Path, inbox: Path
) -> None:
    shifted = object_pixels((180, 120, 60), shift=5)
    with pytest.raises(StaleCaptureError, match="wrong frame or geometry"):
        record(fake, make_session, iray_job, work, inbox, SEPARATE_SESSION, render=shifted)


def test_render_from_another_camera_is_refused(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path, work: Path, inbox: Path
) -> None:
    """The render shows the sphere from z = 60, but the recorded camera is at z = 40."""
    job = make_iray_job(tmp_path, camera_z=40.0)
    with pytest.raises(StaleCaptureError, match="wrong frame or geometry"):
        record(fake, make_session, job, work, inbox, SEPARATE_SESSION)
    assert not (work / "iray-staging").exists()


def test_silhouette_follows_the_recorded_camera(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path, work: Path, inbox: Path
) -> None:
    job = make_iray_job(tmp_path, camera_z=40.0)
    render = object_pixels((180, 120, 60), camera_z=40.0)
    assert record(fake, make_session, job, work, inbox, SEPARATE_SESSION, render=render) is None


def test_rotated_camera_needs_the_confirmed_euler_order(
    fake: types.ModuleType, make_session: MakeSession, tmp_path: Path, work: Path, inbox: Path
) -> None:
    job = make_iray_job(tmp_path, rotation=[0.0, 5.0, 0.0])
    with pytest.raises(RecorderError, match="camera_rotation_order"):
        record(fake, make_session, job, work, inbox, SEPARATE_SESSION)


def test_moved_fixture_is_refused(
    fake: types.ModuleType, make_session: MakeSession, iray_job: Job, work: Path, inbox: Path
) -> None:
    world = fake.FakeWorld()
    original = world.modules["substance_painter.project"].create

    def create_moved(mesh_file_path: str, *args: Any, **kwargs: Any) -> None:
        original(mesh_file_path, *args, **kwargs)
        low, high = world.scene_bounds
        world.scene_bounds = ([v + 3.0 for v in low], [v + 3.0 for v in high])

    world.modules["substance_painter.project"].create = create_moved
    with pytest.raises(RecorderError, match="moved or rescaled"):
        record(
            fake, make_session, iray_job, work, inbox, SEPARATE_SESSION, session=make_session(world)
        )


@pytest.mark.parametrize(
    ("capture", "message"),
    [
        ([sheet_setting("capture.route", "save_render")], "capture.procedure"),
        (
            [
                sheet_setting("capture.procedure", "iray-capture/1"),
                sheet_setting("capture.route", "external_observation_1to1"),
            ],
            "only the Save Render route",
        ),
    ],
)
def test_sheet_names_procedure_and_route(
    tmp_path: Path, capture: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(RecorderError, match=message):
        settings_sheet(make_iray_job(tmp_path, capture=capture))


def test_k_must_exceed_one(
    fake: types.ModuleType, make_session: MakeSession, iray_job: Job, work: Path, inbox: Path
) -> None:
    with pytest.raises(RecorderError, match="k > 1"):
        record(fake, make_session, iray_job, work, inbox, K_TIMES_SAMPLES, k=1)


def test_texture_jobs_are_not_iray_jobs(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    with pytest.raises(RecorderError, match="Tier 3"):
        record(fake, make_session, sample_job, work, inbox, SEPARATE_SESSION)
