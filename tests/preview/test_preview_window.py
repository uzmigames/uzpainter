"""Tests of phase2.1_preview-viewport-window: the preview window attached to a worker
(`UzPainter.exe --worker ... --preview`) and the standalone `UzPainter.exe --preview <file.uzp>`
(src/preview/preview.h, src/preview/cli.h).

The worker runs on DX12 with its own engine; the preview thread has a second device. The cases
open a real window, so they need the owner's desktop session and skip under `UZP_NO_GPU=1`
(hosted CI, decision 028). The test process is the worker's supervisor (tests/supervisor/
conftest.py `Pipe`); the stall hook is the Debug build's `test_fault preview_stall` (decision 120).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.preview.conftest import NO_GPU
from tests.supervisor.conftest import JSON_PREFIX, Pipe, make_project

pytestmark = pytest.mark.skipif(
    NO_GPU, reason="UZP_NO_GPU=1: needs a DX12 adapter and a desktop session (decision 028)"
)

WORKER = ("--gpu-backend", "dx12", "--allow-python", "--test-faults")
TITLE = "UzPainter preview"
SW_MINIMIZE = 6
SW_RESTORE = 9
WM_CLOSE = 0x0010
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004

EXPORT = """
import hashlib, os
import substance_painter.export as ex, substance_painter.textureset as ts
cfg = {"exportShaderParams": False, "exportPath": __OUT__, "defaultExportPreset": "p",
       "exportPresets": [{"name": "p", "maps": [{"fileName": "probe_BaseColor", "channels": [
           {"destChannel": c, "srcChannel": c, "srcMapType": "documentMap",
            "srcMapName": "baseColor"} for c in "RGB"]}]}],
       "exportList": [{"rootPath": s.name()} for s in ts.all_texture_sets()],
       "exportParameters": [{"parameters": {
           "fileFormat": "png", "bitDepth": "8", "dithering": False,
           "paddingAlgorithm": "passthrough"}}]}
r = ex.export_project_textures(cfg)
result = {k: hashlib.sha256(open(p, "rb").read()).hexdigest()
          for k, v in r.textures.items() for p in v}
"""

INSERT_FILL = """
from uzpainter import layerstack as ls, textureset as ts
ls.insert_fill(ls.InsertPosition.from_textureset_stack(ts.get_active_stack()))
result = None
"""

user32 = ctypes.WinDLL("user32", use_last_error=True)
_ENUM = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


def windows_of(pid: int) -> list[int]:
    """The visible top-level preview windows of process `pid`."""
    found: list[int] = []

    def visit(hwnd: int, _: int) -> bool:
        owner = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            buffer = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buffer, 256)
            if buffer.value.startswith(TITLE):
                found.append(hwnd)
        return True

    user32.EnumWindows(_ENUM(visit), 0)
    return found


def wait_for(condition: Callable[[], Any], timeout: float = 120.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("condition not met in time")


def status(pipe: Pipe) -> dict[str, Any]:
    result = pipe.call("preview_status")["result"]
    assert isinstance(result, dict)
    return result


class Run:
    """One worker session: evaluations and an export of `project`, results and revisions."""

    def __init__(self, pipe: Pipe, project: Path, out: Path) -> None:
        self.pipe = pipe
        self.revision = pipe.call("project_open", {"path": str(project)})["result"]["revision"]
        self.out = out
        self.revisions: list[int] = [self.revision]
        self.keys = 0

    def evaluate(self, channel: str) -> str:
        result = self.pipe.call("evaluate_channel", {"channel": channel})["result"]
        assert result["revision"] == self.revision
        data = Path(result["payload"]["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == result["payload"]["sha256"]
        return str(result["payload"]["sha256"])

    def python(self, code: str) -> Any:
        self.keys += 1
        reply = self.pipe.call(
            "run_python",
            {"code": code},
            expected_revision=self.revision,
            idempotency_key=f"k-{self.keys}",
        )
        assert "error" not in reply, reply
        if "committed_revision" in reply:
            self.revision = reply["committed_revision"]
            self.revisions.append(self.revision)
        return reply["result"]["result"]

    def export(self) -> dict[str, str]:
        exported = self.python(EXPORT.replace("__OUT__", repr(str(self.out))))
        assert isinstance(exported, dict) and exported
        return {Path(k).name: v for k, v in exported.items()}


def baseline(painter: Path, tmp_path: Path, project: Path, pipes: list[Pipe]) -> dict[str, Any]:
    """The same work in a worker without a preview."""
    pipe = Pipe(painter, tmp_path, *WORKER)
    pipes.append(pipe)
    if pipe.handshake["gpu_status"] != "ready":
        pytest.skip("no DX12 device on this machine")
    run = Run(pipe, project, tmp_path / "export-baseline")
    first = run.evaluate("BaseColor")
    run.python(INSERT_FILL)
    second = run.evaluate("BaseColor")
    return {"first": first, "second": second, "export": run.export(), "revisions": run.revisions}


def test_stalled_preview_never_delays_evaluation_or_export(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """2.4, 3.2: with the preview thread stalled by the test hook while it holds its frame,
    evaluation and export complete with the same bytes as without a preview; frames keep being
    published and are not taken until the stall ends."""
    project = make_project(painter, tmp_path)
    expected = baseline(painter, tmp_path, project, pipes)

    pipe = Pipe(painter, tmp_path, *WORKER, "--preview")
    pipes.append(pipe)
    tools = pipe.request({"method": "tools/list"})["result"]["tools"]
    assert "preview_status" in {tool["name"] for tool in tools}
    wait_for(lambda: status(pipe)["window_open"])
    run = Run(pipe, project, tmp_path / "export-preview")
    first = run.evaluate("BaseColor")
    wait_for(lambda: status(pipe)["frames_taken"] >= 1)

    stall = pipe.call("test_fault", {"fault": "preview_stall"})
    assert stall["result"] == {"armed": "preview_stall"}
    wait_for(lambda: status(pipe)["stalled"])
    held = status(pipe)
    started = time.monotonic()
    run.python(INSERT_FILL)
    second = run.evaluate("BaseColor")
    exported = run.export()
    elapsed = time.monotonic() - started
    during = status(pipe)
    assert during["stalled"] and during["frames_taken"] == held["frames_taken"]
    assert during["frames_published"] > held["frames_published"]

    resume = pipe.call("test_fault", {"fault": "preview_resume"})
    assert resume["result"] == {"armed": "preview_resume"}
    wait_for(lambda: status(pipe)["frames_taken"] > held["frames_taken"])
    assert (first, second, exported, run.revisions) == (
        expected["first"],
        expected["second"],
        expected["export"],
        expected["revisions"],
    )
    print(f"evaluation + export with the preview stalled: {elapsed:.2f} s")


def test_window_lifecycle_during_evaluation_changes_nothing(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """2.5, 3.3: the window opened, minimised, resized, restored and closed between and during
    evaluations: results and revision order are those of a worker without a preview, and the
    worker keeps serving after the window closed."""
    project = make_project(painter, tmp_path)
    expected = baseline(painter, tmp_path, project, pipes)

    pipe = Pipe(painter, tmp_path, *WORKER, "--preview")
    pipes.append(pipe)
    (hwnd,) = wait_for(lambda: windows_of(pipe.process.pid))
    run = Run(pipe, project, tmp_path / "export-window")
    user32.ShowWindow(hwnd, SW_MINIMIZE)
    first = run.evaluate("BaseColor")
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetWindowPos(hwnd, 0, 0, 0, 640, 360, SWP_NOMOVE | SWP_NOZORDER)
    run.python(INSERT_FILL)
    user32.SetWindowPos(hwnd, 0, 0, 0, 1100, 700, SWP_NOMOVE | SWP_NOZORDER)
    second = run.evaluate("BaseColor")
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    exported = run.export()
    wait_for(lambda: not status(pipe)["window_open"])
    assert not windows_of(pipe.process.pid)
    assert run.evaluate("BaseColor") == second
    assert (first, second, exported, run.revisions) == (
        expected["first"],
        expected["second"],
        expected["export"],
        expected["revisions"],
    )
    # A Legacy project (every project UzPainter creates today) is shown as the unsupported
    # configuration of decision 038, never drawn.
    assert "decision 038" in status(pipe)["last_error"]


def test_standalone_preview_opens_and_closes(painter: Path, tmp_path: Path) -> None:
    """2.5: `UzPainter.exe --preview <file.uzp>` evaluates the project, shows the read-only window
    with the unsupported-configuration message for a Legacy project, and reports on close."""
    project = make_project(painter, tmp_path)
    process = subprocess.Popen(
        [str(painter), "--preview", str(project), "--gpu-backend", "dx12"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        (hwnd,) = wait_for(lambda: windows_of(process.pid))
        time.sleep(1.0)
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        out, err = process.communicate(timeout=120)
    finally:
        if process.poll() is None:
            process.kill()
    assert process.returncode == 0, err.decode(errors="replace")
    lines = [line for line in out.decode().splitlines() if line.startswith(JSON_PREFIX)]
    report = json.loads(lines[-1][len(JSON_PREFIX) :])
    assert report["status"] == "closed" and report["frames_rendered"] == 0
    assert "decision 038" in report["last_error"] and "Legacy" in report["last_error"]
