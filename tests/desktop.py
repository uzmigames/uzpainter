"""Windows the tests' own processes create, watched and kept off the owner's screen (decision 252).

- `PrivateDesktop`: a desktop of the test's own (`CreateDesktopW`) that is never switched to, so
  nobody sees it. `spawn` starts a process on it (`STARTUPINFO.lpDesktop`, which `subprocess` does
  not expose); the windows it opens live there, where `windows` finds them. A window there is
  created, shown, painted and sized as on the owner's desktop; only reading the screen is
  impossible, since that desktop is never composed onto it.
- `WindowRecorder`: every top-level window shown on a desktop while it records (the WinEvent
  `EVENT_OBJECT_SHOW`, out of context, on a thread with its own message loop), with the process
  that showed it, so a window that appears and disappears between two looks is still seen.
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.wintypes as wt
import msvcrt
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import IO, Any, ClassVar

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GENERIC_ALL = 0x10000000
STARTF_USESTDHANDLES = 0x00000100
CREATE_UNICODE_ENVIRONMENT = 0x00000400
WAIT_TIMEOUT = 0x102
INFINITE = 0xFFFFFFFF
EVENT_OBJECT_SHOW = 0x8002
OBJID_WINDOW = 0
WINEVENT_OUTOFCONTEXT = 0
GA_ROOT = 2
WM_QUIT = 0x0012
THREAD_QUERY_LIMITED_INFORMATION = 0x0800

_ENUM = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
_WINEVENT = ctypes.WINFUNCTYPE(
    None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG, wt.DWORD, wt.DWORD
)


class _StartupInfo(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("cb", wt.DWORD),
        ("lpReserved", wt.LPWSTR),
        ("lpDesktop", wt.LPWSTR),
        ("lpTitle", wt.LPWSTR),
        ("dwX", wt.DWORD),
        ("dwY", wt.DWORD),
        ("dwXSize", wt.DWORD),
        ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD),
        ("dwYCountChars", wt.DWORD),
        ("dwFillAttribute", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("wShowWindow", wt.WORD),
        ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wt.HANDLE),
        ("hStdOutput", wt.HANDLE),
        ("hStdError", wt.HANDLE),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("hProcess", wt.HANDLE),
        ("hThread", wt.HANDLE),
        ("dwProcessId", wt.DWORD),
        ("dwThreadId", wt.DWORD),
    ]


user32.CreateDesktopW.restype = wt.HANDLE
user32.CreateDesktopW.argtypes = [
    wt.LPCWSTR,
    wt.LPCWSTR,
    ctypes.c_void_p,
    wt.DWORD,
    wt.DWORD,
    ctypes.c_void_p,
]
user32.CloseDesktop.argtypes = [wt.HANDLE]
user32.SetThreadDesktop.argtypes = [wt.HANDLE]
user32.EnumDesktopWindows.argtypes = [wt.HANDLE, _ENUM, wt.LPARAM]
user32.EnumWindows.argtypes = [_ENUM, wt.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetAncestor.restype = wt.HWND
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user32.SetWinEventHook.restype = wt.HANDLE
user32.SetWinEventHook.argtypes = [
    wt.DWORD,
    wt.DWORD,
    wt.HMODULE,
    _WINEVENT,
    wt.DWORD,
    wt.DWORD,
    wt.DWORD,
]
user32.UnhookWinEvent.argtypes = [wt.HANDLE]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
kernel32.CreateProcessW.argtypes = [
    wt.LPCWSTR,
    wt.LPWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wt.BOOL,
    wt.DWORD,
    ctypes.c_void_p,
    wt.LPCWSTR,
    ctypes.POINTER(_StartupInfo),
    ctypes.POINTER(_ProcessInformation),
]
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.OpenThread.restype = wt.HANDLE
kernel32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.GetProcessIdOfThread.argtypes = [wt.HANDLE]
kernel32.GetProcessIdOfThread.restype = wt.DWORD


def _text(read: Any, hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    read(hwnd, buffer, 256)
    return buffer.value


def window_pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def visible_windows(pid: int, desktop: int | None = None) -> list[tuple[int, str]]:
    """The visible top-level windows of process `pid` with their titles, on `desktop` (a desktop
    handle) or on the calling thread's desktop."""
    found: list[tuple[int, str]] = []

    def visit(hwnd: int, _: int) -> bool:
        if window_pid(hwnd) == pid and user32.IsWindowVisible(hwnd):
            found.append((hwnd, _text(user32.GetWindowTextW, hwnd)))
        return True

    callback = _ENUM(visit)
    if desktop is None:
        user32.EnumWindows(callback, 0)
    else:
        user32.EnumDesktopWindows(desktop, callback, 0)
    return found


class DesktopProcess:
    """A process `PrivateDesktop.spawn` started: the part of `subprocess.Popen` the tests use."""

    def __init__(self, info: _ProcessInformation, pipes: tuple[int, int] | None) -> None:
        self._handle = int(info.hProcess)
        self.pid = int(info.dwProcessId)
        self.returncode: int | None = None
        self._pipes = pipes

    def poll(self) -> int | None:
        if self.returncode is None and kernel32.WaitForSingleObject(self._handle, 0) == 0:
            code = wt.DWORD()
            kernel32.GetExitCodeProcess(self._handle, ctypes.byref(code))
            self.returncode = int(code.value)
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        milliseconds = INFINITE if timeout is None else int(timeout * 1000)
        if kernel32.WaitForSingleObject(self._handle, milliseconds) == WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired("desktop process", timeout or 0)
        code = self.poll()
        assert code is not None
        return code

    def kill(self) -> None:
        if self.poll() is None:
            kernel32.TerminateProcess(self._handle, 1)

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        """Its whole stdout and stderr (spawned with `capture=True`) once it has ended."""
        assert self._pipes is not None, "spawned without capture"
        outputs: list[bytes] = [b"", b""]

        def drain(index: int, fd: int) -> None:
            with os.fdopen(fd, "rb") as stream:
                outputs[index] = stream.read()

        readers = [
            threading.Thread(target=drain, args=(index, fd), daemon=True)
            for index, fd in enumerate(self._pipes)
        ]
        self._pipes = None
        for reader in readers:
            reader.start()
        self.wait(timeout)
        for reader in readers:
            reader.join(30)
        return outputs[0], outputs[1]

    def close(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = 0


class PrivateDesktop:
    """A desktop nobody sees, for the processes of a test that must open a real window."""

    def __init__(self) -> None:
        self.name = f"uzp-tests-{uuid.uuid4().hex[:12]}"
        self.handle = int(user32.CreateDesktopW(self.name, None, None, 0, GENERIC_ALL, None) or 0)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateDesktopW")
        self.processes: list[DesktopProcess] = []

    def spawn(
        self,
        argv: Sequence[str],
        *,
        output: IO[bytes] | None = None,
        capture: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> DesktopProcess:
        """Starts `argv` on this desktop: stdin is NUL; stdout and stderr go to `output` (an open
        file the caller keeps), or to pipes `communicate` reads with `capture`, or to NUL. `env`
        defaults to this process's environment."""
        variables = dict(os.environ if env is None else env)
        names = sorted(variables, key=str.upper)  # the block is sorted by name, ignoring case
        environment = ctypes.create_unicode_buffer(
            "".join(f"{name}={variables[name]}\0" for name in names) + "\0"
        )
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        info = _ProcessInformation()
        pipes: tuple[int, int] | None = None
        children: list[int] = []  # the pipe ends the child writes, closed here once it has them
        with open(os.devnull, "r+b") as null:
            outputs = (null.fileno(), null.fileno())
            if output is not None:
                outputs = (output.fileno(), output.fileno())
            elif capture:
                (out_read, out_write), (err_read, err_write) = os.pipe(), os.pipe()
                pipes = (out_read, err_read)
                outputs = (out_write, err_write)
                children = [out_write, err_write]
            handles = [msvcrt.get_osfhandle(fd) for fd in (null.fileno(), *outputs)]
            startup = _StartupInfo()
            startup.cb = ctypes.sizeof(startup)
            startup.lpDesktop = self.name
            startup.dwFlags = STARTF_USESTDHANDLES
            startup.hStdInput, startup.hStdOutput, startup.hStdError = handles
            try:
                for handle in handles:
                    os.set_handle_inheritable(handle, True)
                created = kernel32.CreateProcessW(
                    None,
                    command,
                    None,
                    None,
                    True,
                    CREATE_UNICODE_ENVIRONMENT,
                    environment,
                    None,
                    ctypes.byref(startup),
                    ctypes.byref(info),
                )
                if not created:
                    raise OSError(ctypes.get_last_error(), f"CreateProcessW {argv[0]}")
            finally:
                for handle in handles:
                    os.set_handle_inheritable(handle, False)
                for fd in children:
                    os.close(fd)
        kernel32.CloseHandle(info.hThread)
        process = DesktopProcess(info, pipes)
        self.processes.append(process)
        return process

    def windows(self, pid: int) -> list[tuple[int, str]]:
        """The visible top-level windows of process `pid` on this desktop, with their titles."""
        return visible_windows(pid, self.handle)

    def close(self) -> None:
        """Ends what is still running on it, then closes it."""
        for process in self.processes:
            process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(30)
            process.close()
        if self.handle:
            user32.CloseDesktop(self.handle)
            self.handle = 0


@dataclass(frozen=True)
class Shown:
    """A top-level window shown while a `WindowRecorder` recorded."""

    pid: int
    hwnd: int
    window_class: str
    title: str


class WindowRecorder:
    """Records every top-level window shown on `desktop` (a desktop handle; the default desktop
    when None) from `start` to `stop`."""

    def __init__(self, desktop: int | None = None) -> None:
        self.desktop = desktop
        self.shown: list[Shown] = []
        self._thread_id = 0
        self._ready = threading.Event()
        self._error: str | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> WindowRecorder:
        self._thread.start()
        self._ready.wait(30)
        assert self._error is None, self._error
        return self

    def stop(self) -> list[Shown]:
        # Events already queued are delivered before the loop sees WM_QUIT.
        time.sleep(0.5)
        user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(30)
        return self.shown

    def of(self, pids: set[int]) -> list[Shown]:
        return [shown for shown in self.shown if shown.pid in pids]

    def _on_event(
        self, hook: int, event: int, hwnd: int, object_id: int, child: int, thread: int, at: int
    ) -> None:
        if object_id != OBJID_WINDOW or not hwnd or user32.GetAncestor(hwnd, GA_ROOT) != hwnd:
            return
        pid = window_pid(hwnd)
        if not pid:  # already destroyed: the process of the thread that showed it
            handle = kernel32.OpenThread(THREAD_QUERY_LIMITED_INFORMATION, False, thread)
            if handle:
                pid = int(kernel32.GetProcessIdOfThread(handle))
                kernel32.CloseHandle(handle)
        self.shown.append(
            Shown(
                pid,
                hwnd,
                _text(user32.GetClassNameW, hwnd),
                _text(user32.GetWindowTextW, hwnd),
            )
        )

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        if self.desktop is not None and not user32.SetThreadDesktop(self.desktop):
            self._error = f"SetThreadDesktop failed: {ctypes.get_last_error()}"
            self._ready.set()
            return
        callback = _WINEVENT(self._on_event)
        hook = user32.SetWinEventHook(
            EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, None, callback, 0, 0, WINEVENT_OUTOFCONTEXT
        )
        if not hook:
            self._error = f"SetWinEventHook failed: {ctypes.get_last_error()}"
            self._ready.set()
            return
        message = wt.MSG()
        self._ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                pass
        finally:
            user32.UnhookWinEvent(hook)
