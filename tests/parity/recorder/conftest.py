"""Fixtures for the recorder tests: the committed Tier 0 sample job and a fake Painter.

The fake lives in `fake_painter.py` next to this file and is loaded by path (the test tree is
not an importable package).
"""

from __future__ import annotations

import importlib.util
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.job import Job, load_job
from tools.parity.recorder.session import PainterSession
from tools.parity.schemas import REPO_ROOT

SAMPLE_JOB = (
    REPO_ROOT / "parity" / "manifests" / "tier0" / "recorder-sample" / "blend-multiply-plane.json"
)
FAKE_NAME = "uzp_recorder_fake_painter"


def load_fake() -> types.ModuleType:
    if FAKE_NAME in sys.modules:
        return sys.modules[FAKE_NAME]
    spec = importlib.util.spec_from_file_location(
        FAKE_NAME, Path(__file__).with_name("fake_painter.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[FAKE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake() -> types.ModuleType:
    return load_fake()


@pytest.fixture
def make_session(fake: types.ModuleType) -> Callable[[Any], PainterSession]:
    def make(world: Any) -> PainterSession:
        return PainterSession(fake.LocalTransport(world), sleep=lambda seconds: None)

    return make


@pytest.fixture
def sample_job() -> Job:
    return load_job(SAMPLE_JOB)


@pytest.fixture
def work(tmp_path: Path) -> Path:
    return tmp_path / "oracle-work"


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    return tmp_path / "oracle-inbox"
