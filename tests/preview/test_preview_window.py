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
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt
import pytest

from tests.preview.conftest import NO_GPU, ocio_bundle
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
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = ctypes.c_void_p(-1)
GCLP_HBRBACKGROUND = -10
RDW_INVALIDATE = 0x0001
RDW_ERASE = 0x0004
RDW_UPDATENOW = 0x0100
PANEL_WIDTH = 300  # src/preview/preview.cpp kPanelWidth

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
result = {os.path.basename(p): hashlib.sha256(open(p, "rb").read()).hexdigest()
          for v in r.textures.values() for p in v}
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


def projects(painter: Path, tmp_path: Path) -> tuple[Path, Path]:
    """Two identical copies of the plane project: one for the baseline, one for the preview run
    (each run commits to its own copy)."""
    made = make_project(painter, tmp_path)
    copies = (tmp_path / "baseline.uzp", tmp_path / "preview.uzp")
    for copy in copies:
        shutil.copyfile(made, copy)
    return copies


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


@pytest.mark.preview_settling("preview_stall")
def test_stalled_preview_never_delays_evaluation_or_export(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """2.4, 3.2: with the preview thread stalled by the test hook while it holds its frame,
    evaluation and export complete with the same bytes as without a preview; frames keep being
    published and are not taken until the stall ends."""
    baseline_project, project = projects(painter, tmp_path)
    expected = baseline(painter, tmp_path, baseline_project, pipes)

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


@pytest.mark.preview_settling("preview_window_lifecycle")
def test_window_lifecycle_during_evaluation_changes_nothing(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """2.5, 3.3: the window opened, minimised, resized, restored and closed between and during
    evaluations: results and revision order are those of a worker without a preview, and the
    worker keeps serving after the window closed."""
    baseline_project, project = projects(painter, tmp_path)
    expected = baseline(painter, tmp_path, baseline_project, pipes)

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


class BitmapInfoHeader(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, type[Any]]]] = [
        ("size", ctypes.wintypes.DWORD),
        ("width", ctypes.wintypes.LONG),
        ("height", ctypes.wintypes.LONG),
        ("planes", ctypes.wintypes.WORD),
        ("bit_count", ctypes.wintypes.WORD),
        ("compression", ctypes.wintypes.DWORD),
        ("size_image", ctypes.wintypes.DWORD),
        ("x_pels_per_meter", ctypes.wintypes.LONG),
        ("y_pels_per_meter", ctypes.wintypes.LONG),
        ("colours_used", ctypes.wintypes.DWORD),
        ("colours_important", ctypes.wintypes.DWORD),
        ("colours", ctypes.wintypes.DWORD * 4),  # BITMAPINFO's colour table, unused at 32 bpp
    ]


class Sampler(threading.Thread):
    """The window's client area as the desktop compositor (DWM) shows it, sampled once per
    composition (`DwmFlush`, then a BitBlt from the screen), and the samples that show an
    unbuffered window: a view that is uniformly (0, 0, 0), the class brush's erase, or a panel
    status box without one pixel of its text (every channel at least 150), cleared before its
    text was drawn. A sample whose client rectangle changed while it was taken is discarded."""

    def __init__(self, hwnd: int) -> None:
        super().__init__(daemon=True)
        self.hwnd = hwnd
        self.stop = threading.Event()
        self.paused = threading.Event()
        self.samples = 0
        self.failures: list[str] = []
        self.error: BaseException | None = None
        # Own function pointers: GDI handles are pointer-sized, so these need their types.
        handle = ctypes.c_void_p
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.dwmapi = ctypes.WinDLL("dwmapi")
        self.user32.GetDC.restype = handle
        self.user32.GetDC.argtypes = [handle]
        self.user32.ReleaseDC.argtypes = [handle, handle]
        self.user32.SetThreadDpiAwarenessContext.argtypes = [handle]
        self.gdi32.CreateCompatibleDC.restype = handle
        self.gdi32.CreateCompatibleDC.argtypes = [handle]
        self.gdi32.CreateCompatibleBitmap.restype = handle
        self.gdi32.CreateCompatibleBitmap.argtypes = [handle, ctypes.c_int, ctypes.c_int]
        self.gdi32.SelectObject.restype = handle
        self.gdi32.SelectObject.argtypes = [handle, handle]
        self.gdi32.DeleteObject.argtypes = [handle]
        self.gdi32.DeleteDC.argtypes = [handle]
        integer, unsigned = ctypes.c_int, ctypes.c_uint
        self.gdi32.BitBlt.argtypes = [handle, *[integer] * 4, handle, integer, integer, unsigned]
        self.gdi32.GetDIBits.argtypes = [*[handle] * 2, unsigned, unsigned, *[handle] * 2, unsigned]

    def client(self) -> tuple[int, int, int, int] | None:
        """The client area on the screen (left, top, width, height); none while minimised."""
        if self.user32.IsIconic(self.hwnd):
            return None
        rect = ctypes.wintypes.RECT()
        origin = ctypes.wintypes.POINT(0, 0)
        if not self.user32.GetClientRect(self.hwnd, ctypes.byref(rect)):
            return None
        self.user32.ClientToScreen(self.hwnd, ctypes.byref(origin))
        if rect.right <= PANEL_WIDTH + 24 or rect.bottom <= 24:
            return None
        return origin.x, origin.y, rect.right, rect.bottom

    def grab(self, screen: int, area: tuple[int, int, int, int]) -> npt.NDArray[np.uint8]:
        """The BGRA pixels of `area` of the screen, rows top first."""
        left, top, width, height = area
        memory = self.gdi32.CreateCompatibleDC(screen)
        bitmap = self.gdi32.CreateCompatibleBitmap(screen, width, height)
        try:
            previous = self.gdi32.SelectObject(memory, bitmap)
            self.gdi32.BitBlt(memory, 0, 0, width, height, screen, left, top, 0x00CC0020)
            self.gdi32.SelectObject(memory, previous)  # GetDIBits needs it deselected
            header = BitmapInfoHeader(40, width, -height)  # 40: BITMAPINFOHEADER's size
            header.planes, header.bit_count = 1, 32
            pixels = np.zeros((height, width, 4), np.uint8)
            lines = self.gdi32.GetDIBits(
                memory, bitmap, 0, height, pixels.ctypes.data, ctypes.addressof(header), 0
            )
            assert lines == height, f"GetDIBits: {lines} lines, error {ctypes.get_last_error()}"
            return pixels
        finally:
            self.gdi32.DeleteObject(bitmap)
            self.gdi32.DeleteDC(memory)

    def check(self, pixels: npt.NDArray[np.uint8]) -> str | None:
        height, width = pixels.shape[:2]
        view_width = width - PANEL_WIDTH
        # Inside the window's rounded corners, which show the desktop behind it.
        if not pixels[16:-16, 16 : view_width - 16, :3].any():
            return "the view is uniformly (0, 0, 0): the window was erased"
        box = pixels[12 : height // 2, view_width + 12 : width - 12, :3]
        if not (box >= 150).all(axis=-1).any():
            return "the panel shows no text: it was cleared before its text was drawn"
        return None

    def run(self) -> None:
        try:
            # Physical pixels, as the per-monitor-aware preview window uses them.
            self.user32.SetThreadDpiAwarenessContext(-4)
            screen = self.user32.GetDC(None)
            try:
                while not self.stop.is_set():
                    self.dwmapi.DwmFlush()
                    area = None if self.paused.is_set() else self.client()
                    if area is None:
                        continue
                    pixels = self.grab(screen, area)
                    if self.client() != area:
                        continue
                    self.samples += 1
                    problem = self.check(pixels)
                    if problem:
                        self.failures.append(f"sample {self.samples} {area[2:]}: {problem}")
            finally:
                self.user32.ReleaseDC(None, screen)
        except BaseException as error:  # reported by the test's thread
            self.error = error


def test_window_presents_only_complete_frames(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """Decision 227 (the owner saw the window flicker): the window is double buffered. Each frame
    is composed off screen and presented whole by one BitBlt in WM_PAINT, nothing erases the
    window (no class background brush, WM_ERASEBKGND answered without erasing), and an unchanged
    window is not redrawn. Through resizes, a minimise and restore, forced repaints and a new
    evaluation, the screen never shows an erased view or a panel cleared of its text."""
    bundle = ocio_bundle(painter, tmp_path / "fixture")
    pipe = Pipe(painter, tmp_path, *WORKER, "--preview")
    pipes.append(pipe)
    if pipe.handshake["gpu_status"] != "ready":
        pytest.skip("no DX12 device on this machine")
    (hwnd,) = wait_for(lambda: windows_of(pipe.process.pid))
    run = Run(pipe, bundle, tmp_path / "export")
    run.evaluate("BaseColor")
    wait_for(lambda: status(pipe)["frames_rendered"] >= 1)
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 40, 40, 960, 640, SWP_NOACTIVATE)

    # Nothing erases the window, and an unchanged window is not redrawn.
    class_long = ctypes.WinDLL("user32").GetClassLongPtrW
    class_long.restype = ctypes.c_size_t
    class_long.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    assert class_long(hwnd, GCLP_HBRBACKGROUND) == 0, "the window class erases with a brush"
    wait_for(lambda: status(pipe)["frames_rendered"] >= 2)  # the resize's render
    time.sleep(1.0)
    idle = status(pipe)
    time.sleep(1.0)
    assert status(pipe)["presents"] == idle["presents"], "an unchanged window was redrawn"
    # A repaint Windows asks for presents the frame again.
    user32.RedrawWindow(hwnd, None, None, RDW_INVALIDATE | RDW_ERASE | RDW_UPDATENOW)
    wait_for(lambda: status(pipe)["presents"] > idle["presents"])

    sampler = Sampler(hwnd)
    sampler.start()
    try:
        # Resizes further apart than the 200 ms render period: each one renders again.
        for width, height in ((700, 450), (1100, 700), (640, 360), (1000, 640), (800, 520)):
            user32.SetWindowPos(hwnd, 0, 0, 0, width, height, SWP_NOMOVE | SWP_NOZORDER)
            time.sleep(0.3)
        # The compositor animates a minimise and a restore; the screen then shows the
        # animation, not the window.
        sampler.paused.set()
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        time.sleep(0.5)
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.6)
        sampler.paused.clear()
        for _ in range(10):
            user32.RedrawWindow(hwnd, None, None, RDW_INVALIDATE | RDW_ERASE | RDW_UPDATENOW)
            time.sleep(0.1)
        rendered = status(pipe)["frames_rendered"]
        run.python(INSERT_FILL)
        run.evaluate("BaseColor")
        wait_for(lambda: status(pipe)["frames_rendered"] > rendered)
        time.sleep(0.5)
    finally:
        sampler.stop.set()
        sampler.join(30)
    assert sampler.error is None, sampler.error
    assert sampler.samples >= 20, f"only {sampler.samples} samples"
    assert not sampler.failures, (
        f"{len(sampler.failures)} of {sampler.samples} samples: {sampler.failures[:5]}"
    )
    print(f"{sampler.samples} composed frames sampled, none erased or half drawn")


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
