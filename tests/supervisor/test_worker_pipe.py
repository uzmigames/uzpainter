"""The worker role through its pipe, with the test process as its supervisor
(src/supervisor/worker.h; task phase2.1_supervisor-ipc-worker items 2.3-2.7, 2.10, 3.1, 3.6).

CPU only: every worker here runs `--gpu-backend vulkan`, which has no device before Phase 3
(`render::CreateDevice`), so the worker starts with `gpu_status: unavailable` and touches no GPU.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from tests.supervisor.conftest import INSERT_FILL, Pipe, make_project, wait_until_gone

KEY = {"idempotency_key": "k-1"}


def test_handshake_reports_the_worker(painter: Path, tmp_path: Path, pipes: list[Pipe]) -> None:
    """2.4: protocol, pid, build, backend, GPU status and Python policy."""
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "vulkan")
    pipes.append(pipe)
    assert pipe.handshake == {
        "protocol": "uzp-ipc/1",
        "worker_pid": pipe.process.pid,
        "build": "0.0.0+uzpainter-Debug",
        "gpu_backend": "vulkan",
        "gpu_status": "unavailable",
        "python": "disabled",
    }
    allowed = Pipe(painter, tmp_path, "--gpu-backend", "vulkan", "--allow-python")
    pipes.append(allowed)
    assert allowed.handshake["python"] == "allowed"


def test_python_disabled_at_the_pipe(painter: Path, tmp_path: Path, pipes: list[Pipe]) -> None:
    """2.7, 3.6: without --allow-python, run_python is not listed and is refused before anything
    else is looked at, even with a valid key and precondition."""
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "vulkan")
    pipes.append(pipe)
    names = [tool["name"] for tool in pipe.request({"method": "tools/list"})["result"]["tools"]]
    assert "run_python" not in names
    assert {
        "project_open",
        "project_close",
        "project_save",
        "project_inspect",
        "evaluate_channel",
    } <= set(names)
    marker = tmp_path / "ran.txt"
    reply = pipe.call(
        "run_python",
        {"code": f"open({str(marker)!r}, 'w').write('x')"},
        expected_revision=0,
        **KEY,
    )
    assert reply["error"]["code"] == "python_disabled"
    assert not marker.exists()


def test_unavailable_backend_refuses_gpu_calls_before_mutating(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """2.6, 3.6: `gpu_backend_unavailable {backend, reason}` for the GPU call, no revision moved,
    and project open, save and inspect still work."""
    project = make_project(painter, tmp_path)
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "vulkan")
    pipes.append(pipe)
    opened = pipe.call("project_open", {"path": str(project)})
    revision = opened["result"]["revision"]
    assert opened["committed_revision"] == revision
    reply = pipe.call("evaluate_channel", {"channel": "BaseColor"})
    error = reply["error"]
    assert error["code"] == "gpu_backend_unavailable"
    assert error["details"]["backend"] == "vulkan" and error["details"]["reason"]
    assert not (tmp_path / "out").exists()  # nothing written
    saved = pipe.call("project_save", {})
    assert saved["result"]["current"] == revision and saved["result"]["named"] == revision
    inspected = pipe.call("project_inspect")["result"]
    assert inspected["open"] and inspected["revision"] == revision
    assert inspected["path"] == project.as_posix()
    assert [s["name"] for s in inspected["texture_sets"]]


def test_mutating_calls_need_key_and_current_precondition(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """2.5: a mutating call without `idempotency_key` / `expected_revision` is an invalid request;
    a stale precondition is refused before the call runs; the reply carries
    `committed_revision`."""
    project = make_project(painter, tmp_path)
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "vulkan", "--allow-python")
    pipes.append(pipe)
    revision = pipe.call("project_open", {"path": str(project)})["result"]["revision"]
    for extra in (
        {},
        {"idempotency_key": "k"},
        {"expected_revision": revision},
        {"idempotency_key": "", "expected_revision": revision},
        {"idempotency_key": "k", "expected_revision": "1"},
    ):
        reply = pipe.call("run_python", {"code": INSERT_FILL}, **extra)
        assert reply["error"]["code"] == "invalid_request", extra
    stale = pipe.call("run_python", {"code": INSERT_FILL}, expected_revision=revision - 1, **KEY)
    assert stale["error"] == {
        "code": "stale_revision",
        "message": "the project is at another revision than the call expected",
        "details": {"expected": revision - 1, "current": revision},
    }
    pipe.events.clear()
    done = pipe.call("run_python", {"code": INSERT_FILL}, expected_revision=revision, **KEY)
    # The durable state is reported before the reply: the absolute store and its new revision.
    assert pipe.events == [
        {
            "event": "revision",
            "revision": revision + 1,
            "project": project.as_posix(),
            "untitled": False,
        }
    ]
    assert done["result"]["status"] == "ok"
    assert done["committed_revision"] == revision + 1
    assert done["result"]["last_committed_revision"] == revision + 1


def test_script_failure_is_structured_with_partial_changes(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """02 §5 at the pipe: a script raising after a committed call keeps that call; the error
    names the last committed revision and the traceback."""
    project = make_project(painter, tmp_path)
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "vulkan", "--allow-python")
    pipes.append(pipe)
    revision = pipe.call("project_open", {"path": str(project)})["result"]["revision"]
    reply = pipe.call(
        "run_python",
        {"code": INSERT_FILL + "\nraise ValueError('after one call')"},
        expected_revision=revision,
        **KEY,
    )
    error = reply["error"]
    assert error["code"] == "script_failed" and error["message"] == "after one call"
    assert error["details"]["last_committed_revision"] == revision + 1
    assert "ValueError" in error["details"]["error"]["traceback"]
    assert pipe.call("project_inspect")["result"]["revision"] == revision + 1


def test_protocol_errors_keep_the_worker_serving(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """2.3, 2.5: a bad frame, a missing id, an unknown method or tool each get a structured error
    and the worker keeps answering."""
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "vulkan")
    pipes.append(pipe)
    pipe.send_raw(b"this is not json\n")
    assert pipe.frame()["error"]["code"] == "invalid_frame"
    pipe.send_raw(b'{"method":"tools/list"}\n')
    assert pipe.frame()["error"]["code"] == "invalid_request"
    assert pipe.request({"method": "shutdown"})["error"]["code"] == "unknown_method"
    assert pipe.call("no_such_tool")["error"] == {
        "code": "unknown_tool",
        "message": "unknown tool no_such_tool",
        "details": {"name": "no_such_tool"},
    }
    assert pipe.call("project_inspect")["result"] == {"open": False}


def test_worker_exits_when_its_supervisor_closes_the_pipe(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """2.10: a broken pipe ends the worker (exit code 4) without committing anything further."""
    project = make_project(painter, tmp_path)
    pipe = Pipe(painter, tmp_path, "--gpu-backend", "vulkan")
    pipes.append(pipe)
    pipe.call("project_open", {"path": str(project)})
    pipe.file.close()
    assert pipe.process.wait(30) == 4


def test_worker_accepts_only_its_supervisor(painter: Path, tmp_path: Path) -> None:
    """2.3: the pipe name carries the supervisor's process id; any other client is disconnected,
    and a client reconnecting in a loop cannot hold the worker past its connect deadline."""
    stand_in = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        name = rf"\\.\pipe\uzpainter-{stand_in.pid}-{os.getpid()}"
        log = tmp_path / "worker.log"
        with log.open("wb") as stderr:
            worker = subprocess.Popen(
                [
                    str(painter),
                    "--worker",
                    "--pipe",
                    name,
                    "--gpu-backend",
                    "vulkan",
                    "--connect-timeout-ms",
                    "4000",
                    "--output-root",
                    str(tmp_path / "out"),
                ],
                stdout=stderr,
                stderr=stderr,
            )
            started = time.monotonic()
            handshakes = 0
            refused = 0
            while worker.poll() is None and time.monotonic() - started < 60:
                try:
                    with open(name, "r+b", buffering=0) as client:
                        refused += 1
                        try:
                            if client.read(1):
                                handshakes += 1
                        except OSError:
                            pass
                except OSError:
                    time.sleep(0.01)
            code = worker.wait(30)
        elapsed = time.monotonic() - started
        assert code == 3, log.read_text(errors="replace")
        assert handshakes == 0 and refused > 0
        assert elapsed < 30, elapsed
        assert "did not connect in time" in log.read_text(errors="replace")
    finally:
        stand_in.kill()
        stand_in.wait()


def test_worker_exits_when_its_supervisor_process_ends(painter: Path, tmp_path: Path) -> None:
    """2.10: a worker whose supervisor process is gone before it connected exits (code 3)."""
    stand_in = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
    name = rf"\\.\pipe\uzpainter-{stand_in.pid}-1"
    worker = subprocess.Popen(
        [
            str(painter),
            "--worker",
            "--pipe",
            name,
            "--gpu-backend",
            "vulkan",
            "--output-root",
            str(tmp_path / "out"),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    stand_in.wait()
    assert worker.wait(30) in (3, 4)
    assert wait_until_gone(worker.pid)


def test_worker_usage_errors(painter: Path) -> None:
    """2.1: the worker's command line is checked before anything starts."""
    for args in (
        ["--worker"],
        ["--worker", "--pipe", r"\\.\pipe\other-1-1", "--gpu-backend", "dx12"],
        ["--worker", "--pipe", r"\\.\pipe\uzpainter-1-1", "--gpu-backend", "metal"],
        ["--worker", "--pipe", r"\\.\pipe\uzpainter-1-1"],
        [
            "--worker",
            "--pipe",
            r"\\.\pipe\uzpainter-1-1",
            "--gpu-backend",
            "dx12",
            "--gpu-deadline-ms",
            "0",
        ],
        ["--worker", "--pipe", r"\\.\pipe\uzpainter-1-1", "--gpu-backend", "dx12", "--bogus"],
    ):
        process = subprocess.run(
            [str(painter), *args], capture_output=True, timeout=60, check=False
        )
        assert process.returncode == 2, args
        assert b"usage: UzPainter.exe --worker" in process.stderr
