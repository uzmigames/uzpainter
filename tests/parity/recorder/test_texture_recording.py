"""Texture goldens against a fake Painter: session identity, state replay, readbacks, exports,
the two-recording rule and stale-capture refusal (task items 2.1-2.3, 2.6)."""

from __future__ import annotations

import copy
import json
import os
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.capture import StaleCaptureError
from tools.parity.recorder.job import Job, job_from_manifest
from tools.parity.recorder.session import PainterSession, RecorderError, bootstrap_code
from tools.parity.recorder.texture import record_texture_golden
from tools.parity.schemas import REPO_ROOT

MakeSession = Callable[[Any], PainterSession]


def record_of(run: Path) -> dict[str, Any]:
    record: dict[str, Any] = json.loads((run / "record.json").read_text(encoding="utf-8"))
    return record


def outputs(record: dict[str, Any], index: int, kind: str) -> list[dict[str, Any]]:
    return [o for o in record["recordings"][index]["outputs"] if o["kind"] == kind]


def test_session_records_painter_identity(
    fake: types.ModuleType, make_session: MakeSession
) -> None:
    session = make_session(fake.FakeWorld())
    identity = session.connect()
    assert identity.painter_build() == {
        "product": "Adobe Substance 3D Painter",
        "version": "12.1.0",
        "build_id": "12.1.0+js-api.1.1.20",
    }
    assert identity.colour_management["mode"] == "legacy"
    # Reconnecting to the same process keeps the session id; a new process gets a new one.
    assert session.connect().session_id == identity.session_id
    assert make_session(fake.FakeWorld()).connect().session_id != identity.session_id


def test_bootstrap_sends_only_the_painter_side_code() -> None:
    code = bootstrap_code("x = 1\n")
    assert "uzp_recorder['session_id'] = uzp_recorder_session_id" in code
    assert "substance_painter" not in code


def test_other_painter_versions_are_refused(
    fake: types.ModuleType, make_session: MakeSession
) -> None:
    world = fake.FakeWorld()
    world.version, world.version_info = "12.0.1", (12, 0, 1)
    with pytest.raises(RecorderError, match=r"must be Adobe Substance 3D Painter 12\.1\.0"):
        make_session(world).connect()


def test_an_open_project_is_never_touched(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    world = fake.FakeWorld()
    world.project_open = True
    with pytest.raises(RecorderError, match="already open"):
        record_texture_golden(make_session(world), sample_job, work, inbox)
    assert world.project_open and not inbox.exists() and not work.exists()


def test_sample_golden_is_recorded_twice(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    world = fake.FakeWorld()
    run = record_texture_golden(make_session(world), sample_job, work, inbox)
    record = record_of(run)
    assert [r["condition"] for r in record["recordings"]] == ["same_session", "after_save_reopen"]
    assert record["recordings"][0]["session_id"] == record["recordings"][1]["session_id"]
    first, second = outputs(record, 0, "exported_map"), outputs(record, 1, "exported_map")
    assert len(first) == len(second) == 1
    assert first[0]["storage_format"] == {
        "container": "png",
        "sample_type": "uint",
        "bits_per_channel": 16,
        "channels": 3,
        "encoding": "srgb",
    }
    assert first[0]["export_settings"]["encoding_basis"] == "source_channel_format"
    assert first[0]["export_settings"]["bitDepth"] == "16"
    assert first[0]["blob"] == second[0]["blob"]
    # The project was saved in the private work directory and closed afterwards.
    assert not world.project_open
    assert list(work.rglob("golden.spp"))


def test_effective_defaults_and_readbacks_are_recorded(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    record = record_of(
        record_texture_golden(make_session(fake.FakeWorld()), sample_job, work, inbox)
    )
    defaults = record["key"]["effective_defaults"]
    assert defaults["insert_fill"]["5"]["per_channel"]["BaseColor"] == {
        "blending_mode": "Normal",
        "opacity": 1.0,
    }
    assert defaults["project.create"]["texture_sets"]["uzp_plane"]["resolution"] == [256, 256]
    assert record["key"]["project_settings"]["create"] == {
        "normal_map_format": "OpenGL",
        "default_texture_resolution": 256,
    }
    for index in (0, 1):
        readbacks = {
            (o["call"].rsplit(".", 1)[1], o["args"].get("node_step")): o["value"]
            for o in outputs(record, index, "api_readback")
        }
        assert readbacks[("get_blending_mode", 5)] == "Multiply"
        assert readbacks[("get_opacity", 5)] == 1.0
        assert readbacks[("active_channels", 2)] == ["BaseColor"]
        assert readbacks[("get_source", 5)] == {"uniform_color_working": [0.5, 0.25, 1.0]}


def renumbered(manifest: dict[str, Any], index: int, step: dict[str, Any]) -> Job:
    steps = manifest["instruction_sequence"]["steps"]
    steps.insert(index, step)
    for number, item in enumerate(steps, start=1):
        item["step"] = number
    return job_from_manifest(manifest)


def test_failing_instruction_aborts_the_recording(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    job = renumbered(
        copy.deepcopy(sample_job.manifest),
        7,
        {
            "step": 0,
            "call": "substance_painter.layerstack.FillLayerNode.active_channels",
            "args": {"node_step": 5, "channels": ["Roughness"]},
        },
    )
    world = fake.FakeWorld()
    with pytest.raises(RecorderError, match="apply_step"):
        record_texture_golden(make_session(world), job, work, inbox)
    assert not inbox.exists() and not world.project_open


def test_failing_readback_records_the_documented_error(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    job = renumbered(
        copy.deepcopy(sample_job.manifest),
        9,
        {
            "step": 0,
            "call": "substance_painter.layerstack.FillLayerNode.active_channels",
            "args": {"node_step": 2, "channels": ["Roughness"]},
        },
    )
    record = record_of(record_texture_golden(make_session(fake.FakeWorld()), job, work, inbox))
    for index in (0, 1):
        (raised,) = [
            o
            for o in outputs(record, index, "api_readback")
            if o["args"] == {"node_step": 2, "channel": "BaseColor"}
        ]
        assert raised["value"] is None
        assert raised["raised"]["type"] == "RuntimeError"


def test_substance_source_properties_are_read_back(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    job = renumbered(
        copy.deepcopy(sample_job.manifest),
        9,
        {
            "step": 0,
            "call": "substance_painter.layerstack.FillLayerNode.set_source",
            "args": {
                "node_step": 2,
                "channel": "BaseColor",
                "resource": "resource://starter_assets/Grunge Map 001",
            },
        },
    )
    record = record_of(record_texture_golden(make_session(fake.FakeWorld()), job, work, inbox))
    for index in (0, 1):
        (readback,) = [
            o
            for o in outputs(record, index, "api_readback")
            if o["args"] == {"node_step": 2, "channel": "BaseColor"}
        ]
        assert readback["value"]["substance_properties"] == {
            "scale": {"value": 1.5, "widget_type": "Slider", "label": "Scale"},
            "seed": {"value": 7, "widget_type": "RandomSeed", "label": "Random Seed"},
            "tint": {
                "value": [{"working": [0.25, 0.5, 1.0]}, 0.5],
                "widget_type": "Color",
                "label": "Tint",
            },
        }


def test_stale_export_is_refused_and_no_golden_is_written(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    def backdate(path: Path) -> None:
        old = path.stat().st_mtime_ns - 3_600_000_000_000
        os.utime(path, ns=(old, old))

    world = fake.FakeWorld(export_hook=backdate)
    with pytest.raises(StaleCaptureError, match="before the last applied instruction"):
        record_texture_golden(make_session(world), sample_job, work, inbox)
    assert not inbox.exists()
    assert not world.project_open


def test_extra_file_in_the_export_is_refused(
    fake: types.ModuleType, make_session: MakeSession, sample_job: Job, work: Path, inbox: Path
) -> None:
    def leftover(path: Path) -> None:
        (path.parent / "leftover.png").write_bytes(b"x")

    with pytest.raises(StaleCaptureError, match="unlisted"):
        record_texture_golden(
            make_session(fake.FakeWorld(export_hook=leftover)), sample_job, work, inbox
        )
    assert not inbox.exists()


def test_job_vocabulary_is_enforced(sample_job: Job) -> None:
    manifest = copy.deepcopy(sample_job.manifest)
    manifest["instruction_sequence"]["steps"][1]["call"] = (
        "substance_painter.layerstack.insert_paint"
    )
    with pytest.raises(RecorderError, match="not in the recorder vocabulary"):
        job_from_manifest(manifest)
    manifest = copy.deepcopy(sample_job.manifest)
    steps = manifest["instruction_sequence"]["steps"]
    steps[-1], steps[-2] = steps[-2], steps[-1]
    steps[-1]["step"], steps[-2]["step"] = len(steps), len(steps) - 1
    with pytest.raises(RecorderError, match="must precede the captures"):
        job_from_manifest(manifest)


def test_input_hash_mismatch_is_refused(sample_job: Job, tmp_path: Path) -> None:
    mesh = tmp_path / "parity" / "fixtures" / "meshes" / "plane.obj"
    mesh.parent.mkdir(parents=True)
    mesh.write_bytes(
        (REPO_ROOT / "parity" / "fixtures" / "meshes" / "plane.obj").read_bytes() + b"#"
    )
    with pytest.raises(RecorderError, match="differs from the manifest"):
        job_from_manifest(sample_job.manifest, repo_root=tmp_path)
