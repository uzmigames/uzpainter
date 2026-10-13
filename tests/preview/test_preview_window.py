"""Tests of phase2.1_preview-viewport-window: the preview window attached to a worker
(`UzPainter.exe --worker ... --preview`) and the standalone `UzPainter.exe --preview <file.uzp>`
(src/preview/preview.h, src/preview/cli.h).

The worker runs on DX12 with its own engine; the preview thread has a second device. The cases
open a real window, so they need a desktop session and skip under `UZP_NO_GPU=1` (hosted CI,
decision 028). The window opens on a private desktop nobody sees (`tests/desktop.py`, decision
252), so a run never puts it on the owner's screen; only the anti-flicker case, which reads the
screen, opens it there, and only when the owner asks for it with `UZP_SCREEN_TESTS=1`. The test
process is the worker's supervisor (tests/supervisor/conftest.py `Pipe`); the stall hook is the
Debug build's `test_fault preview_stall` (decision 120).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt
import pytest

from tests.desktop import PrivateDesktop, WindowRecorder, visible_windows
from tests.preview.conftest import ENVIRONMENT, NO_GPU, SPHERE, ocio_bundle
from tests.supervisor.conftest import JSON_PREFIX, Pipe, make_project

pytestmark = pytest.mark.skipif(
    NO_GPU, reason="UZP_NO_GPU=1: needs a DX12 adapter and a desktop session (decision 028)"
)
ON_SCREEN = os.environ.get("UZP_SCREEN_TESTS") == "1" and os.environ.get("UZP_HEADLESS") != "1"

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
PANEL_BGR = (28, 24, 24)  # src/preview/preview.cpp: the panel's RGB(24, 24, 28), as BGR
UOI_NAME = 2
DESKTOP_READOBJECTS = 0x0001

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


def windows_of(pid: int, desktop: PrivateDesktop | None) -> list[int]:
    """The visible top-level preview windows of process `pid` on `desktop`, or on the owner's
    desktop when it is None."""
    found = visible_windows(pid, None if desktop is None else desktop.handle)
    return [hwnd for hwnd, title in found if title.startswith(TITLE)]


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
    painter: Path, tmp_path: Path, pipes: list[Pipe], desktop: PrivateDesktop
) -> None:
    """2.4, 3.2: with the preview thread stalled by the test hook while it holds its frame,
    evaluation and export complete with the same bytes as without a preview; frames keep being
    published and are not taken until the stall ends."""
    baseline_project, project = projects(painter, tmp_path)
    expected = baseline(painter, tmp_path, baseline_project, pipes)

    pipe = Pipe(painter, tmp_path, *WORKER, "--preview", desktop=desktop)
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
    # The preview's own thread evaluates the committed edit and publishes it (decision 248).
    wait_for(lambda: status(pipe)["frames_published"] > held["frames_published"])
    during = status(pipe)
    assert during["stalled"] and during["frames_taken"] == held["frames_taken"]

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
    painter: Path, tmp_path: Path, pipes: list[Pipe], desktop: PrivateDesktop
) -> None:
    """2.5, 3.3: the window opened, minimised, resized, restored and closed between and during
    evaluations: results and revision order are those of a worker without a preview, and the
    worker keeps serving after the window closed."""
    baseline_project, project = projects(painter, tmp_path)
    expected = baseline(painter, tmp_path, baseline_project, pipes)

    pipe = Pipe(painter, tmp_path, *WORKER, "--preview", desktop=desktop)
    pipes.append(pipe)
    (hwnd,) = wait_for(lambda: windows_of(pipe.process.pid, desktop))
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
    assert not windows_of(pipe.process.pid, desktop)
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


def test_the_previews_evaluation_never_delays_or_changes_the_workers_results(
    painter: Path, tmp_path: Path, pipes: list[Pipe], desktop: PrivateDesktop
) -> None:
    """Decision 248 on the OCIO fixture, the projects the attached preview evaluates on its own
    thread and device (a Legacy project, as in the tests above, is published without being
    evaluated). The worker's evaluations, commits and export give the bytes and revisions of a
    worker without a preview while the preview evaluates the opened revision, and while the test
    hook holds the preview's evaluation thread inside its evaluation of the next one: nothing the
    worker does waits for it. The held revision, superseded by a commit made meanwhile, is never
    published; the newest one is, with its four maps."""
    bundle = ocio_bundle(painter, tmp_path / "fixture")
    copies = [tmp_path / name / bundle.name for name in ("baseline", "preview")]
    for copy in copies:
        shutil.copytree(bundle, copy)

    pipe = Pipe(painter, tmp_path, *WORKER)
    pipes.append(pipe)
    if pipe.handshake["gpu_status"] != "ready":
        pytest.skip("no DX12 device on this machine")
    run = Run(pipe, copies[0], tmp_path / "export-baseline")
    first = run.evaluate("BaseColor")
    run.python(INSERT_FILL)
    run.python(INSERT_FILL)
    expected = (first, run.evaluate("BaseColor"), run.export(), run.revisions)

    pipe = Pipe(painter, tmp_path, *WORKER, "--preview", desktop=desktop)
    pipes.append(pipe)
    wait_for(lambda: status(pipe)["window_open"])
    # A call that waited for the held evaluation would never reply: the watchdog then ends the
    # worker, and the call fails on the closed pipe.
    watchdog = threading.Timer(300, pipe.process.kill)
    watchdog.start()
    try:
        run = Run(pipe, copies[1], tmp_path / "export-preview")
        # The preview's thread evaluates the opened revision meanwhile, on its own device.
        first = run.evaluate("BaseColor")
        opened = wait_for(lambda: (s := status(pipe))["revision_shown"] == run.revision and s)
        assert len(opened["maps_shown"]) == 4 and opened["last_error"] == "", opened

        armed = pipe.call("test_fault", {"fault": "preview_evaluation_stall"})
        assert armed["result"] == {"armed": "preview_evaluation_stall"}
        run.python(INSERT_FILL)
        wait_for(lambda: status(pipe)["evaluation_stalled"])
        held = status(pipe)
        run.python(INSERT_FILL)  # supersedes the held revision
        second = run.evaluate("BaseColor")
        exported = run.export()
        during = status(pipe)
    finally:
        watchdog.cancel()
    assert during["evaluation_stalled"] and during["frames_published"] == held["frames_published"]
    assert during["revision_shown"] == run.revisions[0]

    resume = pipe.call("test_fault", {"fault": "preview_evaluation_resume"})
    assert resume["result"] == {"armed": "preview_evaluation_resume"}
    shown = wait_for(lambda: (s := status(pipe))["revision_shown"] == run.revision and s)
    assert shown["frames_published"] == held["frames_published"] + 1, (held, shown)
    assert len(shown["maps_shown"]) == 4 and shown["last_error"] == "", shown
    assert (first, second, exported, run.revisions) == expected


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


def desktop_unavailable() -> str | None:
    """Why the screen cannot be captured: the input desktop is not the user's `Default` one (the
    workstation is locked, or a secure desktop is up), or there is none; None when it can be."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.OpenInputDesktop.restype = ctypes.c_void_p
    user.OpenInputDesktop.argtypes = [
        ctypes.wintypes.DWORD,
        ctypes.wintypes.BOOL,
        ctypes.wintypes.DWORD,
    ]
    user.CloseDesktop.argtypes = [ctypes.c_void_p]
    user.GetUserObjectInformationW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.DWORD),
    ]
    desktop = user.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
    if not desktop:
        return (
            f"no input desktop (error {ctypes.get_last_error()}): the workstation is locked or the "
            "session is not interactive, so the screen cannot be captured"
        )
    try:
        name = ctypes.create_unicode_buffer(64)
        needed = ctypes.wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop, UOI_NAME, name, 128, ctypes.byref(needed)):
            return f"the input desktop's name cannot be read (error {ctypes.get_last_error()})"
        if name.value != "Default":
            return (
                f"the input desktop is {name.value!r}, not 'Default': the workstation is locked, "
                "so the screen cannot be captured"
            )
        return None
    finally:
        user.CloseDesktop(desktop)


class CaptureUnavailable(Exception):
    """The screen could not be captured: the reason the test is skipped."""


class Sampler(threading.Thread):
    """The window's client area as the desktop compositor (DWM) shows it, sampled once per
    composition (`DwmFlush`, then a BitBlt from the screen), and the samples that do not show one
    whole composed frame (`check`). A sample whose client rectangle changed while it was taken is
    discarded. When the screen cannot be captured (`DwmFlush` or the BitBlt fails because the
    workstation is locked), `unavailable` says why and sampling stops; any other failure of those
    calls is an error."""

    def __init__(self, hwnd: int) -> None:
        super().__init__(daemon=True)
        self.hwnd = hwnd
        self.stop = threading.Event()
        self.paused = threading.Event()
        self.samples = 0
        self.failures: list[str] = []
        self.error: BaseException | None = None
        self.unavailable: str | None = None
        # Own function pointers: GDI handles are pointer-sized, so these need their types.
        handle = ctypes.c_void_p
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.dwmapi = ctypes.WinDLL("dwmapi")
        self.dwmapi.DwmFlush.restype = ctypes.c_long  # an HRESULT
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
        self.gdi32.BitBlt.restype = ctypes.wintypes.BOOL
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
            copied = self.gdi32.BitBlt(memory, 0, 0, width, height, screen, left, top, 0x00CC0020)
            error = ctypes.get_last_error()
            self.gdi32.SelectObject(memory, previous)  # GetDIBits needs it deselected
            if not copied:
                reason = desktop_unavailable()
                if reason:
                    raise CaptureUnavailable(reason)
                raise AssertionError(f"BitBlt from the screen failed (error {error})")
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
        """Why `pixels` (BGRA) is not one whole composed frame: a row of the view that is all
        (0, 0, 0) (an erase, even of a band only: the image and the message never hold a black
        row), a panel whose background is not its colour (erased), or a panel without the text
        of either of its boxes (cleared before its text was drawn)."""
        height, width = pixels.shape[:2]
        view_width = width - PANEL_WIDTH
        # Inside the window's rounded corners, which show the desktop behind it.
        view = pixels[16:-16, 16 : view_width - 16, :3]
        erased = int((~view.any(axis=(1, 2))).sum())
        if erased:
            return f"{erased} rows of the view are (0, 0, 0): the window was erased"
        panel = pixels[16:-16, view_width + 4 : width - 16, :3].astype(np.int16)
        background = float((np.abs(panel - np.array(PANEL_BGR)) <= 4).all(axis=-1).mean())
        if background < 0.5:
            return f"{background:.0%} of the panel shows its background colour: it was erased"
        box = pixels[12 : height // 2, view_width + 12 : width - 12, :3]
        if not (box >= 150).all(axis=-1).any():
            return "the panel's status box shows no text: it was cleared before its text was drawn"
        # The painter_iray line, RGB(220, 190, 90).
        iray = pixels[height // 2 : height - 12, view_width + 12 : width - 12, :3]
        if not ((iray[..., 2] >= 180) & (iray[..., 1] >= 150) & (iray[..., 0] <= 130)).any():
            return "the panel's painter_iray box shows no text: it was cleared before its text"
        return None

    def run(self) -> None:
        try:
            # Physical pixels, as the per-monitor-aware preview window uses them.
            self.user32.SetThreadDpiAwarenessContext(-4)
            screen = self.user32.GetDC(None)
            try:
                while not self.stop.is_set():
                    flushed = self.dwmapi.DwmFlush()
                    if flushed < 0:
                        reason = desktop_unavailable()
                        if reason:
                            raise CaptureUnavailable(reason)
                        hresult = flushed & 0xFFFFFFFF
                        raise AssertionError(f"DwmFlush failed (HRESULT {hresult:#010x})")
                    area = None if self.paused.is_set() else self.client()
                    if area is None:
                        continue
                    pixels = self.grab(screen, area)
                    if self.client() != area:
                        continue
                    self.samples += 1
                    problem = self.check(pixels)
                    if problem:
                        # A desktop locked while sampling may hand back a black screen.
                        if reason := desktop_unavailable():
                            raise CaptureUnavailable(reason)
                        self.failures.append(f"sample {self.samples} {area[2:]}: {problem}")
            finally:
                self.user32.ReleaseDC(None, screen)
        except CaptureUnavailable as reason:
            self.unavailable = str(reason)
        except BaseException as error:  # reported by the test's thread
            self.error = error


@pytest.mark.skipif(
    not ON_SCREEN,
    reason="reads the owner's screen, so it opens the window there: the owner runs it by hand with "
    "UZP_SCREEN_TESTS=1 and without UZP_HEADLESS=1 (decision 252)",
)
def test_window_presents_only_complete_frames(
    painter: Path, tmp_path: Path, pipes: list[Pipe]
) -> None:
    """Decision 227 (the owner saw the window flicker): the window is double buffered. Each frame
    is composed off screen and presented whole by one BitBlt in WM_PAINT, nothing erases the
    window (no class background brush, WM_ERASEBKGND answered without erasing), and an unchanged
    window is not redrawn. Through resizes, a minimise and restore, forced repaints and a new
    evaluation, the screen never shows an erased view or a panel cleared of its text."""
    if reason := desktop_unavailable():
        pytest.skip(reason)
    bundle = ocio_bundle(painter, tmp_path / "fixture")
    pipe = Pipe(painter, tmp_path, *WORKER, "--preview")
    pipes.append(pipe)
    if pipe.handshake["gpu_status"] != "ready":
        pytest.skip("no DX12 device on this machine")
    (hwnd,) = wait_for(lambda: windows_of(pipe.process.pid, None))
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
    if sampler.unavailable:
        pytest.skip(sampler.unavailable)
    assert sampler.error is None, sampler.error
    assert sampler.samples >= 20, f"only {sampler.samples} samples"
    assert not sampler.failures, (
        f"{len(sampler.failures)} of {sampler.samples} samples: {sampler.failures[:5]}"
    )
    print(f"{sampler.samples} composed frames sampled, none erased or half drawn")


def test_a_new_evaluation_of_the_same_mesh_keeps_the_camera(
    painter: Path, tmp_path: Path, pipes: list[Pipe], desktop: PrivateDesktop
) -> None:
    """The preview evaluates every committed revision. It fits its camera on the first frame and
    again only for another mesh, so an edit does not undo the user's orbit."""
    bundle = ocio_bundle(painter, tmp_path / "fixture")
    pipe = Pipe(painter, tmp_path, *WORKER, "--preview", desktop=desktop)
    pipes.append(pipe)
    if pipe.handshake["gpu_status"] != "ready":
        pytest.skip("no DX12 device on this machine")
    wait_for(lambda: status(pipe)["window_open"])
    run = Run(pipe, bundle, tmp_path / "export")
    wait_for(lambda: status(pipe)["revision_shown"] == run.revision)
    assert status(pipe)["camera_fits"] == 1
    run.python(INSERT_FILL)
    wait_for(lambda: status(pipe)["revision_shown"] == run.revision)
    assert len(run.revisions) == 2 and status(pipe)["camera_fits"] == 1


REBUILD = """
import hashlib, os, shutil
from uzpainter import project
dump = project.dump_recipe()
os.makedirs(__RES__, exist_ok=True)
for path in __SOURCES__:
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    if sha in dump["rebuild"]["/resource_catalog"]:
        shutil.copyfile(path, os.path.join(__RES__, sha + os.path.splitext(path)[1]))
project.close()
project.rebuild_from_recipe(dump, __RES__)
result = project.revision()
"""


def test_the_attached_preview_shows_the_committed_revision(
    painter: Path, tmp_path: Path, pipes: list[Pipe], desktop: PrivateDesktop
) -> None:
    """B7 of the practical end-to-end report (decision 248): the attached preview evaluates every
    committed revision itself, on its own thread and device. Without any `evaluate_channel` it
    shows the project after `project_open`, after a committed edit and after a rebuild from a
    recipe, each time with every map it displays (base colour, metalness, roughness and the
    combined normal), and it shows that no project is open once the project is closed."""
    bundle = ocio_bundle(painter, tmp_path / "fixture")
    pipe = Pipe(painter, tmp_path, *WORKER, "--preview", desktop=desktop)
    pipes.append(pipe)
    if pipe.handshake["gpu_status"] != "ready":
        pytest.skip("no DX12 device on this machine")
    wait_for(lambda: status(pipe)["window_open"])

    def shown(revision: int) -> None:
        found = wait_for(lambda: (s := status(pipe))["revision_shown"] == revision and s)
        (texture_set,) = pipe.call("project_inspect")["result"]["texture_sets"]
        slots = ("BaseColor", "Metalness", "Roughness", "Normal")
        assert sorted(found["maps_shown"]) == sorted(f"{texture_set['name']}/{s}" for s in slots)
        assert found["display"] == "OCIO, Painter's substance config, Default - sRGB (decision 042)"
        assert found["last_error"] == ""

    run = Run(pipe, bundle, tmp_path / "export")
    shown(run.revision)
    run.python(INSERT_FILL)
    assert len(run.revisions) == 2
    shown(run.revision)

    # Rebuilt from its recipe into a new untitled project, which the session then holds.
    code = REBUILD.replace("__RES__", repr(str(tmp_path / "res"))).replace(
        "__SOURCES__", repr([str(SPHERE), str(ENVIRONMENT)])
    )
    rebuilt = pipe.call(
        "run_python", {"code": code}, expected_revision=run.revision, idempotency_key="rebuild"
    )
    assert "error" not in rebuilt and rebuilt["result"]["status"] == "ok", rebuilt
    revision = rebuilt["result"]["result"]
    shown(revision)
    event = [e for e in pipe.events if e.get("event") == "revision"][-1]
    assert event["revision"] == revision and event["untitled"] and event["project"], event

    assert "error" not in pipe.call("project_close", {"discard": True})
    closed = wait_for(lambda: (s := status(pipe))["revision_shown"] == -1 and s)
    assert closed["maps_shown"] == [] and closed["display"] == "-" and closed["last_error"] == ""


def test_standalone_preview_opens_and_closes(
    painter: Path, tmp_path: Path, desktop: PrivateDesktop
) -> None:
    """2.5: `UzPainter.exe --preview <file.uzp>` evaluates the project, shows the read-only window
    with the unsupported-configuration message for a Legacy project, and reports on close; its
    panel labels the Legacy display as not displayed (B13 of the practical end-to-end report: it
    read "OCIO, Painter's substance config"). Decision 252: headless is only the default, and a
    preview asked for explicitly still opens its window; the recorder that proves no window in
    tests/supervisor/test_headless.py sees it."""
    project = make_project(painter, tmp_path)
    recorder = WindowRecorder(desktop.handle).start()
    env = {k: v for k, v in os.environ.items() if k != "UZP_HEADLESS"}
    process = desktop.spawn(
        [str(painter), "--preview", str(project), "--gpu-backend", "dx12"], capture=True, env=env
    )
    try:
        (hwnd,) = wait_for(lambda: windows_of(process.pid, desktop))
        time.sleep(1.0)
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        out, err = process.communicate(timeout=120)
    finally:
        process.kill()
        shown = recorder.stop()
    assert process.returncode == 0, err.decode(errors="replace")
    shown_titles = {item.title for item in shown if item.hwnd == hwnd and item.pid == process.pid}
    assert shown_titles == {"UzPainter preview - plane.uzp"}, shown
    lines = [line for line in out.decode().splitlines() if line.startswith(JSON_PREFIX)]
    report = json.loads(lines[-1][len(JSON_PREFIX) :])
    assert report["status"] == "closed" and report["frames_rendered"] == 0
    assert "decision 038" in report["last_error"] and "Legacy" in report["last_error"]
    assert report["display"].startswith(
        "Legacy colour management with tone mapping Linear: not displayed"
    )
