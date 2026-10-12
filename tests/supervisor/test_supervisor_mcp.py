"""The supervisor through its stdio MCP session (src/supervisor/supervisor.h,
python/uzpainter_supervisor/; task phase2.1_supervisor-ipc-worker items 2.1, 2.2, 2.4, 2.8, 2.10,
3.1, 3.2, 3.5).

CPU only: the supervisors run `--gpu-backend vulkan` (no device before Phase 3), with
`--test-faults` (the Debug build has the hooks, decision 120). The device-fault and stall cases
are in test_supervisor_gpu.py.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from tests.supervisor.conftest import (
    INSERT_FILL,
    Mcp,
    Pipe,
    kill_pid,
    make_project,
    pid_alive,
    wait_until_gone,
)

BASE = ("--gpu-backend", "vulkan", "--allow-python", "--test-faults")


def opened_session(painter: Path, tmp_path: Path, sessions: list[Mcp]) -> tuple[Mcp, int]:
    """A supervisor with the plane project open and one committed mutation; its revision."""
    project = make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    revision = session.call("project_open", {"path": str(project)})["result"]["revision"]
    reply = session.call(
        "run_python", {"code": INSERT_FILL, "idempotency_key": "k-1", "expected_revision": revision}
    )
    assert reply["committed_revision"] == revision + 1, reply
    return session, revision + 1


def test_tools_are_forwarded_and_stdout_carries_protocol_frames_only(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.1, 2.2: the supervisor serves MCP on stdio and forwards the worker's tools; logs stay on
    stderr."""
    session = Mcp(painter, tmp_path, "--gpu-backend", "vulkan")
    sessions.append(session)
    tools = {tool["name"]: tool for tool in session.request("tools/list", {})["tools"]}
    assert set(tools) == {
        "supervisor_status",
        "project_open",
        "project_close",
        "project_save",
        "project_inspect",
        "evaluate_channel",
    }
    assert tools["project_open"]["inputSchema"]["required"] == ["path"]
    assert session.call("project_inspect") == {"result": {"open": False}}
    assert session.call("run_python", {"code": "1"})["error"]["code"] == "python_disabled"
    status = session.status()
    assert status["gpu_backend"] == "vulkan" and status["gpu_status"] == "unavailable"
    assert status["python"] == "disabled" and status["recoveries"] == []
    assert pid_alive(status["worker_pid"]) and status["worker_pid"] != session.process.pid
    assert session.stdout_is_protocol_only()
    assert "uzpainter supervisor: INFO" in session.log()
    assert session.close() == 0
    assert wait_until_gone(status["worker_pid"])


@pytest.mark.parametrize(
    ("override", "args", "message"),
    [
        (
            {"protocol": "uzp-ipc/0"},
            (),
            "protocol: requested 'uzp-ipc/1', worker reported 'uzp-ipc/0'",
        ),
        ({"gpu_backend": "dx12"}, (), "gpu_backend: requested 'vulkan', worker reported 'dx12'"),
        ({"python": "allowed"}, (), "python: requested 'disabled', worker reported 'allowed'"),
        (
            {"python": "disabled"},
            ("--allow-python",),
            "python: requested 'allowed', worker reported 'disabled'",
        ),
    ],
)
def test_handshake_mismatch_is_a_fatal_supervisor_error(
    painter: Path, tmp_path: Path, override: dict[str, Any], args: tuple[str, ...], message: str
) -> None:
    """2.4, 3.1: the supervisor admits no call to a worker whose handshake differs from what it
    requested and exits with status 4; the worker is ended."""
    session = Mcp(
        painter,
        tmp_path,
        "--gpu-backend",
        "vulkan",
        "--test-faults",
        *args,
        env={"UZP_TEST_HANDSHAKE": json.dumps(override)},
        initialize=False,
    )
    code = session.process.wait(120)
    session.close()
    log = session.log()
    assert code == 4, log
    assert "fatal supervisor error: worker handshake mismatch: " + message in log
    assert session.stdout_lines == []


def test_supervisor_usage_errors(painter: Path, tmp_path: Path) -> None:
    """2.1: the supervisor's command line; HTTP mode and roots belong to phase2.5."""
    for args in (
        ["--gpu-backend", "metal"],
        ["--mcp-http", "127.0.0.1:9000"],
        ["--roots", "C:/"],
        ["--gpu-deadline-ms", "0"],
        ["--bogus"],
    ):
        process = subprocess.run(
            [str(painter), "--mcp", *args],
            capture_output=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        assert process.returncode == 2, (args, process.stderr)
        assert process.stdout == b""


def recovery_after(session: Mcp, count: int) -> dict[str, Any]:
    status = session.status()
    assert len(status["recoveries"]) == count, status
    recovery = status["recoveries"][-1]
    assert isinstance(recovery, dict)
    return recovery


def test_worker_killed_from_outside(painter: Path, tmp_path: Path, sessions: list[Mcp]) -> None:
    """2.8, 3.2: TerminateProcess on the worker leaves the session alive; the next call is held
    until the relaunched worker has reopened the project at its last committed revision."""
    session, revision = opened_session(painter, tmp_path, sessions)
    before = session.status()
    kill_pid(before["worker_pid"])
    # A call racing the kill may reach the dying worker and is then answered `interrupted`
    # (test_native_fault_...); this one is sent once the supervisor has seen the death.
    assert wait_until_gone(before["worker_pid"])
    deadline = time.monotonic() + 120
    while not session.status()["recoveries"] and time.monotonic() < deadline:
        time.sleep(0.05)
    inspected = session.call("project_inspect")
    assert (
        inspected["result"]["revision"] == revision and inspected["committed_revision"] == revision
    )
    recovery = recovery_after(session, 1)
    assert recovery["cause"] == "terminated" and recovery["exit_code"] == 1
    assert recovery["minidump"] is None  # a process terminated from outside writes none
    assert (
        recovery["old_pid"] == before["worker_pid"] and recovery["new_pid"] != recovery["old_pid"]
    )
    assert recovery["revision"] == revision and recovery["recovery_ms"] > 0
    after = session.status()
    assert after["generation"] == before["generation"] + 1
    assert (after["gpu_backend"], after["python"]) == ("vulkan", "allowed")
    assert session.stdout_is_protocol_only()


@pytest.mark.parametrize(("fault", "cause"), [("abort", "abort"), ("seh", "native_fault")])
def test_native_fault_writes_a_minidump_and_relaunches(
    painter: Path, tmp_path: Path, sessions: list[Mcp], fault: str, cause: str
) -> None:
    """2.8, 3.2: abort() and an access violation in the worker: the call in flight is answered
    `interrupted` with the last committed revision and never re-sent; the crash handler's
    minidump is recorded; the same backend and Python policy are relaunched."""
    session, revision = opened_session(painter, tmp_path, sessions)
    old = session.status()["worker_pid"]
    reply = session.call("test_fault", {"fault": fault})
    error = reply["error"]
    assert error["code"] == "interrupted"
    assert error["details"]["cause"] == cause and error["details"]["committed_revision"] == revision
    recovery = recovery_after(session, 1)
    assert recovery["cause"] == cause and recovery["old_pid"] == old
    dump = Path(recovery["minidump"])
    assert dump.name == "crash.dmp" and dump.stat().st_size > 0
    report = json.loads((dump.parent / "crash.json").read_text(encoding="utf-8", errors="replace"))
    assert report  # the crash handler's structured report beside the dump
    assert session.call("project_inspect")["result"]["revision"] == revision
    assert session.status()["python"] == "allowed"
    # The relaunched worker serves mutations on from the reopened revision.
    reply = session.call(
        "run_python", {"code": INSERT_FILL, "idempotency_key": "k-2", "expected_revision": revision}
    )
    assert reply["committed_revision"] == revision + 1


def test_lost_acknowledgement_reports_the_durable_revision(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.8: a worker that commits and dies before its reply: the call is answered `interrupted`
    with the committed revision read back from the reopened file, and is not re-run."""
    session, revision = opened_session(painter, tmp_path, sessions)
    assert session.call("test_fault", {"fault": "kill_before_reply"})["result"] == {
        "armed": "kill_before_reply"
    }
    reply = session.call(
        "run_python", {"code": INSERT_FILL, "idempotency_key": "k-2", "expected_revision": revision}
    )
    assert reply["error"]["code"] == "interrupted"
    assert reply["error"]["details"]["committed_revision"] == revision + 1
    assert session.call("project_inspect")["result"]["revision"] == revision + 1


def test_calls_arriving_during_a_relaunch_wait_for_it(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """2.8: pending calls wait for the relaunch and are then forwarded once."""
    session, revision = opened_session(painter, tmp_path, sessions)
    old = session.status()["worker_pid"]
    kill_pid(old)
    time.sleep(0.05)  # inside the relaunch window
    reply = session.call(
        "run_python", {"code": INSERT_FILL, "idempotency_key": "k-2", "expected_revision": revision}
    )
    assert reply["committed_revision"] == revision + 1, reply
    assert recovery_after(session, 1)["old_pid"] == old


def test_supervisor_killed_ends_its_worker(
    painter: Path, tmp_path: Path, sessions: list[Mcp], pipes: list[Pipe]
) -> None:
    """2.10, 3.5: the worker exits once its supervisor dies, and the project file holds the last
    committed revision."""
    session, revision = opened_session(painter, tmp_path, sessions)
    status = session.status()
    kill_pid(session.process.pid)
    assert wait_until_gone(status["worker_pid"], 30)
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "vulkan")
    pipes.append(pipe)
    assert pipe.call("project_open", {"path": status["project"]})["result"]["revision"] == revision
