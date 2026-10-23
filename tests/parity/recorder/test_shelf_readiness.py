"""Shelf discovery gates preset capture, without a live Painter process."""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from tools.parity.recorder import texture
from tools.parity.recorder.job import Job, Step, job_from_manifest
from tools.parity.recorder.session import PainterIdentity, PainterSession, RecorderError


class CatalogSession(PainterSession):
    def __init__(self, replies: list[Any]) -> None:
        self.clock = 0.0
        self.operations: list[str] = []
        self.delays: list[float] = []
        self.replies = iter(replies)
        super().__init__(
            Mock(), sleep=self.advance, monotonic=lambda: self.clock, poll_interval_s=0.5
        )

    def advance(self, delay: float) -> None:
        self.delays.append(delay)
        self.clock += delay

    def call(self, operation: str, **args: Any) -> Any:
        self.operations.append(operation)
        return next(self.replies) if operation == "catalog_ready" else None


def test_catalog_polls_until_ready_and_refreshes_once() -> None:
    session = CatalogSession([False, False, True])
    session.wait_catalog_ready()
    assert session.operations == [
        "refresh_catalog",
        "catalog_ready",
        "catalog_ready",
        "catalog_ready",
    ]
    assert session.delays == [0.5, 0.5]


def test_ready_catalog_has_no_delay() -> None:
    session = CatalogSession([True])
    session.wait_catalog_ready()
    assert session.delays == []


def test_documented_remote_shelf_operations(
    fake: ModuleType, make_session: Callable[[Any], PainterSession]
) -> None:
    world = fake.FakeWorld()
    world.shelf_crawling_polls = 2
    session = make_session(world)
    session.read_identity()
    session.wait_catalog_ready()
    assert world.shelf_refreshes == 1 and world.shelf_crawling_polls == 0


def test_each_recording_refreshes_before_preset_capture(
    fake: ModuleType,
    make_session: Callable[[Any], PainterSession],
    sample_job: Job,
    work: Path,
    inbox: Path,
) -> None:
    manifest = copy.deepcopy(sample_job.manifest)
    steps = manifest["instruction_sequence"]["steps"]
    steps.append(
        {
            "step": len(steps) + 1,
            "call": "substance_painter.export.list_resource_export_presets",
            "args": {},
        }
    )
    world = fake.FakeWorld()
    world.shelf_crawling_polls = 2
    texture.record_texture_golden(make_session(world), job_from_manifest(manifest), work, inbox)
    assert world.shelf_refreshes == 2 and world.shelf_crawling_polls == 0


def test_crawling_timeout_is_bounded() -> None:
    session = CatalogSession([False] * 4)
    with pytest.raises(RecorderError, match="waiting for shelf discovery"):
        session.wait_catalog_ready(0.75)
    assert session.clock == 0.75
    assert session.delays == [0.5, 0.25]


@pytest.mark.parametrize("value", [None, {}, "true", 1])
def test_unverifiable_catalog_refuses(value: Any) -> None:
    session = CatalogSession([value])
    with pytest.raises(RecorderError, match="boolean"):
        session.wait_catalog_ready()


@pytest.mark.parametrize("failure", [False, True])
def test_preset_capture_runs_only_after_catalog_ready(
    failure: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[str] = []
    session = Mock(spec=PainterSession)
    session.wait_ready.side_effect = lambda: events.append("project")

    def catalog() -> None:
        events.append("catalog")
        if failure:
            raise RecorderError("catalog timeout")

    session.wait_catalog_ready.side_effect = catalog

    def call(operation: str) -> dict[str, Any]:
        events.append(operation)
        return {}

    def capture(*args: Any) -> dict[str, Any]:
        events.append("preset")
        return {}

    session.call.side_effect = call
    monkeypatch.setattr(texture, "readback_outputs", lambda *args: [])
    monkeypatch.setattr(texture, "capture_output", capture)
    step = Step(1, "substance_painter.export.list_resource_export_presets", {})
    job = cast(Job, SimpleNamespace(exports=(), export_probes=(), api_captures=(step,)))
    identity = cast(PainterIdentity, SimpleNamespace(session_id="test"))

    def run() -> None:
        texture.record_once(
            session, job, identity, tmp_path, "r1", "same_session", lambda: datetime.now(UTC)
        )

    if failure:
        with pytest.raises(RecorderError, match="catalog timeout"):
            run()
        assert events == ["project", "catalog"]
    else:
        run()
        assert events == ["project", "catalog", "template_capture", "preset"]
