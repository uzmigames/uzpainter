"""Start and stop the Painter process a study or refresh needs (decisions 034 (b), 037).

The stability study needs a freshly started Painter process, and a refresh may need Painter
started again after an update. The launcher starts Painter with `--enable-remote-scripting`
(the documented remote control, `parity/RECORDER.md` §1), waits until the endpoint answers,
and stops only the process it started:

1. close the project through the documented API (`project.close`, the recorder's
   `close_project` operation) when one is open;
2. end the process it started (`Popen.terminate`, then `kill` after a grace period). The
   documented Python API offers no call that quits Painter.

It refuses to start when the endpoint already answers (a Painter it did not start is running and
must never be stopped by the recorder), and refuses when the process it started exits while an
endpoint answers (that endpoint is not its process).
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from tools.parity.recorder.session import (
    REMOTE_HOST,
    REMOTE_PORT,
    HttpTransport,
    PainterSession,
    RecorderError,
)

PAINTER_EXE_ENV = "UZP_PAINTER_EXE"
DEFAULT_PAINTER_EXE = Path(
    r"C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe"
)
REMOTE_SCRIPTING_ARGS = ("--enable-remote-scripting",)
READY_TIMEOUT_S = 600.0
STOP_TIMEOUT_S = 120.0


class Process(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


def default_painter_exe() -> Path:
    configured = os.environ.get(PAINTER_EXE_ENV)
    return Path(configured) if configured else DEFAULT_PAINTER_EXE


def endpoint_answers(host: str = REMOTE_HOST, port: int = REMOTE_PORT) -> bool:
    """True when the documented remote control executes a trivial expression."""
    try:
        reply: object = HttpTransport(host, port, timeout_s=5.0).run("1")
    except (OSError, RecorderError, ValueError):
        return False
    return reply == 1


class PainterLauncher:
    """One Painter process at a time, started and stopped by the recorder."""

    def __init__(
        self,
        exe: Path | None = None,
        args: Sequence[str] = REMOTE_SCRIPTING_ARGS,
        host: str = REMOTE_HOST,
        port: int = REMOTE_PORT,
        ready_timeout_s: float = READY_TIMEOUT_S,
        stop_timeout_s: float = STOP_TIMEOUT_S,
        popen: Callable[[list[str]], Process] | None = None,
        answers: Callable[[], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        poll_interval_s: float = 2.0,
    ) -> None:
        self.exe = exe if exe is not None else default_painter_exe()
        self.args = list(args)
        self.ready_timeout_s = ready_timeout_s
        self.stop_timeout_s = stop_timeout_s
        self.popen = popen if popen is not None else self.spawn
        self.answers = answers if answers is not None else (lambda: endpoint_answers(host, port))
        self.sleep = sleep
        self.monotonic = monotonic
        self.poll_interval_s = poll_interval_s
        self.process: Process | None = None
        self.starts = 0

    @staticmethod
    def spawn(command: list[str]) -> Any:
        return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def start(self) -> None:
        if self.process is not None:
            raise RecorderError("the launcher already runs a Painter process; stop it first")
        if self.answers():
            raise RecorderError(
                "a Painter remote endpoint already answers: close the Painter that is running "
                "(the recorder stops only processes it started itself)"
            )
        if self.popen is self.spawn and not self.exe.is_file():
            raise RecorderError(f"Painter executable not found: {self.exe} (set {PAINTER_EXE_ENV})")
        self.process = self.popen([str(self.exe), *self.args])
        self.starts += 1
        deadline = self.monotonic() + self.ready_timeout_s
        while not self.answers():
            if self.process.poll() is not None:
                self.process = None
                raise RecorderError("Painter exited before its remote endpoint answered")
            if self.monotonic() >= deadline:
                self.end_process()
                raise RecorderError(
                    f"Painter's remote endpoint did not answer within {self.ready_timeout_s:.0f} s"
                )
            self.sleep(self.poll_interval_s)
        if self.process.poll() is not None:
            self.process = None
            raise RecorderError(
                "the started Painter process exited while an endpoint answers: that endpoint "
                "belongs to a process the recorder did not start"
            )

    def stop(self, session: PainterSession | None = None) -> None:
        """Close the project through the documented API, then end the started process."""
        if self.process is None:
            return
        if session is not None and self.process.poll() is None:
            try:
                if session.state().is_open:
                    session.call("close_project")
                    session.wait_closed(timeout_s=self.stop_timeout_s)
            except (RecorderError, OSError):
                pass  # the process is ended below either way
        self.end_process()

    def end_process(self) -> None:
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=self.stop_timeout_s)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=self.stop_timeout_s)
        deadline = self.monotonic() + self.stop_timeout_s
        while self.answers():
            if self.monotonic() >= deadline:
                raise RecorderError("Painter's remote endpoint still answers after it was stopped")
            self.sleep(self.poll_interval_s)
