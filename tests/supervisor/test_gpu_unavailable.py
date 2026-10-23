"""Explicit Debug-only unavailable-device fixture (phase3.1 item 2.1)."""

import json
import time
from pathlib import Path

import pytest

from python.uzpainter_supervisor.main import _UsageError, parse_args
from python.uzpainter_supervisor.worker import WorkerConfig
from tests.supervisor.conftest import Mcp, kill_pid, make_project, wait_until_gone


@pytest.mark.parametrize("backend", ["dx12", "vulkan"])
def test_unavailable_fixture_arguments(backend: str, tmp_path: Path) -> None:
    args = ["--gpu-backend", backend, "--test-gpu-unavailable"]
    parsed = parse_args(args, hooks_compiled=True)
    assert parsed.test_gpu_unavailable and not parsed.test_faults
    assert parsed.gpu_backend == backend
    with pytest.raises(_UsageError, match="--test-gpu-unavailable needs a Debug build"):
        parse_args(args, hooks_compiled=False)
    assert not parse_args([], hooks_compiled=False).test_gpu_unavailable
    normal = WorkerConfig("UzPainter.exe", backend, False, None, tmp_path, tmp_path, False)
    assert "--test-gpu-unavailable" not in normal.argv("pipe", tmp_path)
    forced = WorkerConfig(
        "UzPainter.exe",
        backend,
        False,
        None,
        tmp_path,
        tmp_path,
        False,
        test_gpu_unavailable=True,
    )
    for generation in (1, 2):
        argv = forced.argv(f"pipe-{generation}", tmp_path / str(generation))
        assert argv.count("--test-gpu-unavailable") == 1
        assert argv[argv.index("--gpu-backend") + 1] == backend
        assert "--test-faults" not in argv


@pytest.mark.parametrize("backend", ["dx12", "vulkan"])
def test_unavailable_fixture_survives_worker_recovery(
    painter: Path, tmp_path: Path, sessions: list[Mcp], backend: str
) -> None:
    project = make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, "--gpu-backend", backend, "--test-gpu-unavailable")
    sessions.append(session)
    revision = session.call("project_open", {"path": str(project), "wait": True})["result"][
        "revision"
    ]
    before = session.status()
    assert before["gpu_status"] == "unavailable" and before["gpu_backend"] == backend
    kill_pid(before["worker_pid"])
    assert wait_until_gone(before["worker_pid"])
    deadline = time.monotonic() + 120
    while not session.status()["recoveries"] and time.monotonic() < deadline:
        time.sleep(0.05)
    after = session.status()
    assert after["generation"] == before["generation"] + 1
    assert after["gpu_status"] == "unavailable" and after["gpu_backend"] == backend
    refused = session.call("evaluate_channel", {"channel": "BaseColor"})
    assert refused["error"]["code"] == "gpu_backend_unavailable"
    assert refused["error"]["details"]["backend"] == backend
    assert session.call("project_inspect")["result"]["revision"] == revision
    from tests.supervisor.test_supervisor_jobs import EXPORT_CONFIG

    exported = session.call(
        "export",
        {
            "config": {**EXPORT_CONFIG, "exportPath": (tmp_path / "cpu-export").as_posix()},
            "wait": True,
        },
    )
    assert "result" in exported, exported
    receipt = json.loads(Path(exported["result"]["receipt"]).read_text(encoding="utf-8"))
    assert receipt["backend"] == "cpu"
    assert receipt["adapter"] is None and receipt["driver"] is None
