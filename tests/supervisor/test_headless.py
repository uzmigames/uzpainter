"""Headless operation (decision 252; `docs/prd.md` NFR-01): no window of any kind while agents
drive UzPainter.

- `UZP_HEADLESS=1`, or `--headless` (before any command, or among `--mcp`'s and `--preview`'s
  options), refuses every window as a usage error before anything is opened.
- Every role turns the Windows error dialogs off, and the switch reaches every child.
- A session started by a host without a console shows no window and gives no process a console
  window: an MCP session with `run_python`, a capture and a worker relaunch, an adapter call
  (`adapters/assets3d/client.py`) and a `run` started with no creation flags. The recorder that
  watches for windows sees the explicit preview's window in
  tests/preview/test_preview_window.py `test_standalone_preview_opens_and_closes`.

The Vulkan case uses the explicit unavailable-device fixture; the DX12 case creates the worker's
device and skips under `UZP_NO_GPU=1`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

from tests.desktop import WindowRecorder
from tests.supervisor.conftest import (
    JSON_PREFIX,
    NO_GPU,
    REPO_ROOT,
    Mcp,
    kill_pid,
    make_project,
    wait_until_gone,
)

CLIENT = REPO_ROOT / "adapters" / "assets3d" / "client.py"
NO_ERROR_DIALOGS = 0x8003  # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
# The process's console as it sees it, its error mode and the headless switch it inherited.
REPORT = """
import ctypes, os
kernel32 = ctypes.windll.kernel32
kernel32.GetConsoleWindow.restype = ctypes.c_void_p
processes = (ctypes.c_ulong * 8)()
result = {
    "pid": os.getpid(),
    "console_window": kernel32.GetConsoleWindow() or 0,
    "console_processes": kernel32.GetConsoleProcessList(processes, 8),
    "error_mode": kernel32.GetErrorMode(),
    "headless": os.environ.get("UZP_HEADLESS"),
}
"""
# A host without a console that starts `UzPainter.exe run` with no creation flags at all.
BARE_HOST = """
import subprocess, sys
done = subprocess.run(sys.argv[1:], stdin=subprocess.DEVNULL, capture_output=True, check=False)
sys.stdout.buffer.write(done.stdout)
sys.exit(done.returncode)
"""


def without_headless() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "UZP_HEADLESS"}


def report_of(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.startswith(JSON_PREFIX)]
    assert lines, stdout
    result = json.loads(lines[-1][len(JSON_PREFIX) :])["result"]
    assert isinstance(result, dict)
    return result


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (["--preview", "absent.uzp"], {"UZP_HEADLESS": "1"}),
        (["--headless", "--preview", "absent.uzp"], {}),
        (["--preview", "absent.uzp", "--headless"], {}),
        (["--mcp", "--preview"], {"UZP_HEADLESS": "1"}),
        (["--headless", "--mcp", "--preview"], {}),
        (["--mcp", "--headless", "--preview"], {}),
        (
            [
                "--worker",
                "--pipe",
                rf"\\.\pipe\uzpainter-{os.getpid()}-1",
                "--gpu-backend",
                "vulkan",
                "--preview",
            ],
            {"UZP_HEADLESS": "1"},
        ),
    ],
)
def test_headless_refuses_every_window_before_opening_anything(
    painter: Path, args: list[str], env: dict[str, str]
) -> None:
    """A preview while headless is a usage error (exit 2) that names the switch, before the
    project is opened (the absent file would fail with 1), a device created or a worker started."""
    process = subprocess.run(
        [str(painter), *args],
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
        env={**without_headless(), **env},
        check=False,
    )
    assert process.returncode == 2, process.stderr
    assert "headless refuses" in process.stderr and "decision 252" in process.stderr
    assert process.stdout == ""


def test_headless_reaches_every_child_and_no_role_shows_an_error_dialog(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """`run` sets the no-dialog error mode itself (it is started here with the default mode), and
    `--headless` before it reaches the script's environment; an `--mcp --headless` worker runs
    with both."""
    script = tmp_path / "report.py"
    script.write_text(REPORT, encoding="utf-8")
    ran = subprocess.run(
        [str(painter), "--headless", "run", str(script), "--gpu-backend", "vulkan"],
        capture_output=True,
        text=True,
        timeout=300,
        stdin=subprocess.DEVNULL,
        env=without_headless(),
        creationflags=subprocess.CREATE_DEFAULT_ERROR_MODE,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    report = report_of(ran.stdout)
    assert report["error_mode"] & NO_ERROR_DIALOGS == NO_ERROR_DIALOGS, report
    assert report["headless"] == "1"

    session = Mcp(
        painter,
        tmp_path,
        "--gpu-backend",
        "vulkan",
        "--test-gpu-unavailable",
        "--allow-python",
        "--headless",
        env={"UZP_HEADLESS": ""},
    )
    sessions.append(session)
    worker = session.call("run_python", {"code": REPORT})["result"]["result"]
    assert worker["pid"] == session.status()["worker_pid"]
    assert worker["error_mode"] & NO_ERROR_DIALOGS == NO_ERROR_DIALOGS, worker
    assert worker["headless"] == "1"


@pytest.mark.parametrize(
    ("backend", "gpu_unavailable"),
    [
        ("vulkan", True),
        pytest.param(
            "dx12",
            False,
            marks=pytest.mark.skipif(NO_GPU, reason="UZP_NO_GPU=1: the DX12 worker needs a GPU"),
        ),
    ],
)
def test_a_session_without_a_console_shows_no_window(
    painter: Path, tmp_path: Path, sessions: list[Mcp], backend: str, gpu_unavailable: bool
) -> None:
    """NFR-01: started by a host that has no console (`DETACHED_PROCESS`, as a GUI host or
    `pythonw` starts it), without `--headless`, an MCP session that runs Python, captures, loses
    its worker and relaunches it, an adapter call and a bare `run` show no top-level window from
    any of their processes (every show on the owner's desktop is recorded while they run), and
    none of those processes has a console window: each has a console without one, or none."""
    project = make_project(painter, tmp_path)
    script = tmp_path / "report.py"
    script.write_text(REPORT, encoding="utf-8")
    host = tmp_path / "bare_host.py"
    host.write_text(textwrap.dedent(BARE_HOST), encoding="utf-8")
    recorder = WindowRecorder().start()
    tree: set[int] = set()
    reports: list[dict[str, Any]] = []
    try:
        session = Mcp(
            painter,
            tmp_path,
            "--gpu-backend",
            backend,
            *(("--test-gpu-unavailable",) if gpu_unavailable else ()),
            "--allow-python",
            env={"UZP_HEADLESS": ""},
            creationflags=subprocess.DETACHED_PROCESS,
        )
        sessions.append(session)
        tree.add(session.process.pid)
        assert session.call("project_open", {"path": str(project), "wait": True})["result"]
        reports.append(session.call("run_python", {"code": REPORT})["result"]["result"])
        shot = session.call("capture", {"mode": "base_color", "path": "shot.png"})
        assert "error" not in shot, shot
        before = session.status()["worker_pid"]
        kill_pid(before)
        assert wait_until_gone(before)
        deadline = time.monotonic() + 120
        while not session.status()["recoveries"] and time.monotonic() < deadline:
            time.sleep(0.05)
        reports.append(session.call("run_python", {"code": REPORT})["result"]["result"])
        assert reports[1]["pid"] != reports[0]["pid"] == before

        arguments = tmp_path / "args.json"
        arguments.write_text(json.dumps({"code": REPORT}), encoding="utf-8")
        adapter = subprocess.Popen(
            [sys.executable, "-I", str(CLIENT), "execute_python", str(arguments)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **without_headless(),
                "UZPAINTER_EXE": str(painter),
                "UZP_ASSETS3D_SESSION": str(tmp_path / "adapter" / "session.json"),
            },
            creationflags=subprocess.DETACHED_PROCESS,
        )
        tree.add(adapter.pid)
        out, err = adapter.communicate(timeout=300)
        assert adapter.returncode == 0, err
        reply = json.loads(out)
        assert reply["success"] is True, reply
        reports.append(reply["data"])

        if sys.getwindowsversion().build >= 26100:  # the manifest's console policy, 11 24H2+
            bare = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(host),
                    str(painter),
                    "run",
                    str(script),
                    "--gpu-backend",
                    "vulkan",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=without_headless(),
                creationflags=subprocess.DETACHED_PROCESS,
            )
            tree.add(bare.pid)
            out, err = bare.communicate(timeout=300)
            assert bare.returncode == 0, err
            bare_report = report_of(out.decode())
            assert bare_report["console_processes"] == 0, bare_report  # no console at all
            reports.append(bare_report)
    finally:
        shown = recorder.stop()
    tree |= {report["pid"] for report in reports}
    assert recorder.of(tree) == [], recorder.of(tree)
    assert [report["console_window"] for report in reports] == [0] * len(reports), reports
    print(f"{len(shown)} windows shown on the desktop meanwhile, none by {sorted(tree)}: {reports}")
