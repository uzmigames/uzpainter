"""The worker process and its pipe, fault detection and relaunch (02-runtime-topology.md §1, §5).

One `Supervisor` owns at most one worker at a time. Each launch (a generation `n`) runs
`UzPainter.exe --worker --pipe \\\\.\\pipe\\uzpainter-<supervisor-pid>-<n>` with the backend,
the Python policy and the deadline the supervisor was started with; the supervisor connects,
checks the handshake (a mismatch is fatal) and then forwards requests. The worker reports the
project it holds and its revision in a `revision` event after every commit and project switch,
before the reply of the call that caused it. A switch to another project goes to admission with
the frame of that call (the oldest request pending), so its owner takes the new project's lease
before any other call can see the project (decision 243).

When the worker ends (process exit, or a broken pipe followed by the exit), the supervisor:
1. notes the cause (`ipc.classify_exit`, refined by a `device_removed` / `timeout` reply just
   before the exit) and the minidump the crash handler wrote, if any;
2. launches the next generation with the same backend and Python policy and reopens the project
   the last `revision` event named: the file at rest holds the last committed revision (02 §6).
   The reopen is raced against the new worker's end; a worker that dies during it is replaced, up
   to `RECOVERY_ATTEMPTS` launches, after which the supervisor stops with a fatal error;
3. answers each call that was in flight with `interrupted {cause, committed_revision}`: it is
   never re-sent (recovery is never a silent replay); calls that arrived meanwhile were held and
   are forwarded to the new worker;
4. records the recovery, with its time from the detected death to the reopened project, and
   starts a new project epoch, so admission reconciles the project's operation rows before it
   admits the next call (admission.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import ipc

log = logging.getLogger("uzpainter.supervisor")

CONNECT_TIMEOUT_S = 120.0  # pipe connection and handshake (the worker creates its device first)
EXIT_GRACE_S = 10.0  # a worker whose pipe broke must exit within this, or it is killed
RECOVERY_ATTEMPTS = 3  # relaunches that may end before the project is reopened, then fatal
ERROR_PIPE_BUSY = 231


class FatalSupervisorError(Exception):
    """The supervisor cannot go on: a handshake mismatch, or a worker that cannot be started."""


@dataclass(frozen=True)
class WorkerConfig:
    exe: str
    gpu_backend: str
    allow_python: bool
    gpu_deadline_ms: int | None
    output_root: Path
    crash_root: Path
    test_faults: bool
    preview: bool = False
    protocol: str = ipc.PROTOCOL

    def argv(self, pipe: str, crash_dir: Path) -> list[str]:
        args = [self.exe, "--worker", "--pipe", pipe, "--gpu-backend", self.gpu_backend]
        if self.allow_python:
            args.append("--allow-python")
        if self.gpu_deadline_ms is not None:
            args += ["--gpu-deadline-ms", str(self.gpu_deadline_ms)]
        args += ["--output-root", str(self.output_root), "--crash-dir", str(crash_dir)]
        if self.test_faults:
            args.append("--test-faults")
        if self.preview:
            args.append("--preview")
        return args


class _PipeProtocol(asyncio.Protocol):
    def __init__(self, generation: _Generation) -> None:
        self._generation = generation
        self._decoder = ipc.FrameDecoder()

    def data_received(self, data: bytes) -> None:
        frames, errors = self._decoder.feed(data)
        for error in errors:
            log.error("worker %d sent a bad frame: %s", self._generation.number, error)
        for frame in frames:
            self._generation.on_frame(frame)

    def connection_lost(self, exc: Exception | None) -> None:
        self._generation.on_pipe_lost()


@dataclass
class _Generation:
    """One launch of the worker."""

    number: int
    pipe: str
    crash_dir: Path
    process: asyncio.subprocess.Process
    handshake_future: asyncio.Future[dict[str, Any]]
    # Receives each event with the frame of the request the worker ran when it sent it (`running`).
    on_event: Callable[[dict[str, Any], dict[str, Any] | None], None]
    pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    # The frame of each pending request, in the order it was sent.
    sent: dict[str, dict[str, Any]] = field(default_factory=dict)
    transport: asyncio.BaseTransport | None = None
    handshake: ipc.Handshake | None = None
    pipe_lost: asyncio.Event = field(default_factory=asyncio.Event)
    replaced: asyncio.Event = field(default_factory=asyncio.Event)  # the next generation is up
    last_fault_code: str | None = None

    def on_frame(self, frame: dict[str, Any]) -> None:
        if not self.handshake_future.done():
            self.handshake_future.set_result(frame)
            return
        request_id = frame.get("id")
        if isinstance(request_id, str) and request_id in self.pending:
            error = frame.get("error")
            if isinstance(error, dict) and error.get("code") in ("device_removed", "timeout"):
                self.last_fault_code = str(error["code"])
            future = self.pending.pop(request_id)
            self.sent.pop(request_id, None)
            if not future.done():
                future.set_result(frame)
        elif "id" in frame:
            log.error("worker %d replied to an unknown request: %s", self.number, frame)
        elif "event" in frame:
            self.on_event(frame, self.running())

    def running(self) -> dict[str, Any] | None:
        """The frame of the request the worker's command thread runs: the oldest one pending.
        The thread runs requests in the order they were sent, and each reply reaches the pipe
        before the next request's events; `worker/cancel` is the exception, answered at once by
        the worker's reader thread."""
        for frame in self.sent.values():
            if frame.get("method") != "worker/cancel":
                return frame
        return None

    def on_pipe_lost(self) -> None:
        self.pipe_lost.set()
        if not self.handshake_future.done():
            self.handshake_future.set_exception(
                ConnectionError("the pipe closed before the handshake")
            )

    def send(self, frame: dict[str, Any]) -> None:
        assert isinstance(self.transport, asyncio.WriteTransport)
        self.transport.write(ipc.encode_frame(frame))


@dataclass
class Recovery:
    generation: int
    cause: str
    exit_code: int
    fault_code: str | None
    minidump: str | None
    old_pid: int
    new_pid: int
    project: str | None
    revision: int | None
    recovery_ms: float
    attempts: int = 1
    failed_attempts: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


class Supervisor:
    """The worker lifecycle and the request path to it."""

    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self.recoveries: list[Recovery] = []
        # What the worker durably holds, from its `revision` events: they arrive before the
        # reply of the call that caused them, so a lost reply loses neither (02 §5).
        self.project_path: str | None = None
        self.project_uuid: str | None = None
        self.project_untitled = False
        self.durable_revision: int | None = None
        # Changes with every relaunch and every switch of project: admission reconciles the
        # project's operation rows once per epoch (admission.py).
        self.project_epoch = 0
        self._numbers = itertools.count(1)
        self._current: _Generation | None = None
        self._ready = asyncio.Event()
        self._monitor: asyncio.Task[None] | None = None
        self._closing = False
        self.fatal: str | None = None
        # Receives the worker's `job_progress` events (admission.Admission.on_job_event).
        self.on_job_event: Callable[[dict[str, Any]], None] | None = None
        # Receives the frame of the request during which the worker switched to another project,
        # as soon as the new project is recorded (admission.Admission.on_project_switch).
        self.on_project_switch: Callable[[dict[str, Any] | None], None] | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launches the first worker; `FatalSupervisorError` when it cannot be used."""
        self._current = await self._launch()
        self._ready.set()
        self._monitor = asyncio.get_running_loop().create_task(self._watch())

    async def close(self) -> None:
        """Ends the worker: closing the pipe makes it exit without committing anything further."""
        self._closing = True
        if self._monitor:
            self._monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor
        generation = self._current
        if generation and generation.transport:
            generation.transport.close()
            try:
                await asyncio.wait_for(generation.process.wait(), EXIT_GRACE_S)
            except TimeoutError:
                generation.process.kill()

    async def _launch(self) -> _Generation:
        number = next(self._numbers)
        pipe = rf"\\.\pipe\uzpainter-{os.getpid()}-{number}"
        crash_dir = self.config.crash_root / f"{os.getpid()}-{number}"
        stdout: int = subprocess.DEVNULL
        with contextlib.suppress(AttributeError, OSError, ValueError):
            stdout = sys.stderr.fileno()  # the worker's stdout never reaches the MCP stream
        # A process group of its own: a console Ctrl+C or Ctrl+Break stops the supervisor (HTTP
        # mode), never the worker behind it, which ends when its supervisor does (02 §5).
        process = await asyncio.create_subprocess_exec(
            *self.config.argv(pipe, crash_dir),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=None,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        loop = asyncio.get_running_loop()
        generation = _Generation(
            number, pipe, crash_dir, process, loop.create_future(), self._on_event
        )
        try:
            await asyncio.wait_for(self._connect(generation), CONNECT_TIMEOUT_S)
            frame = await asyncio.wait_for(generation.handshake_future, CONNECT_TIMEOUT_S)
        except (OSError, ConnectionError, TimeoutError) as error:
            await self._discard(generation)
            raise FatalSupervisorError(
                f"worker {number} did not start: {error} (exit code {process.returncode})"
            ) from error
        try:
            generation.handshake = ipc.check_handshake(
                frame,
                ipc.Requested(
                    self.config.protocol, self.config.gpu_backend, self.config.allow_python
                ),
            )
        except ipc.HandshakeMismatch as mismatch:
            await self._discard(generation)
            raise FatalSupervisorError(str(mismatch)) from mismatch
        log.info("worker %d ready: %s", number, frame)
        return generation

    async def _connect(self, generation: _Generation) -> None:
        loop = asyncio.get_running_loop()
        while True:
            if generation.process.returncode is not None:
                raise ConnectionError(f"the worker exited with {generation.process.returncode}")
            try:
                transport, _ = await loop.create_pipe_connection(  # type: ignore[attr-defined]
                    lambda: _PipeProtocol(generation), generation.pipe
                )
            except FileNotFoundError:
                await asyncio.sleep(0.02)
                continue
            except OSError as error:
                if getattr(error, "winerror", None) == ERROR_PIPE_BUSY:
                    await asyncio.sleep(0.02)
                    continue
                raise
            generation.transport = transport
            return

    async def _discard(self, generation: _Generation) -> None:
        if generation.transport:
            generation.transport.close()
        if generation.process.returncode is None:
            generation.process.kill()
        await generation.process.wait()

    async def _watch(self) -> None:
        """Relaunches the worker each time it ends."""
        while not self._closing:
            generation = self._current
            assert generation is not None
            exited = asyncio.ensure_future(generation.process.wait())
            lost = asyncio.ensure_future(generation.pipe_lost.wait())
            await asyncio.wait({exited, lost}, return_when=asyncio.FIRST_COMPLETED)
            if not exited.done():
                try:
                    await asyncio.wait_for(asyncio.shield(exited), EXIT_GRACE_S)
                except TimeoutError:
                    generation.process.kill()
                    await exited
            lost.cancel()
            if self._closing:
                return
            await self._recover(generation)

    async def _recover(self, dead: _Generation) -> None:
        detected = time.perf_counter()
        self._ready.clear()
        returncode = dead.process.returncode if dead.process.returncode is not None else -1
        cause = ipc.classify_exit(returncode)
        minidump = _newest_minidump(dead.crash_dir)
        if dead.transport:
            dead.transport.close()
        old_pid = dead.handshake.worker_pid if dead.handshake else dead.process.pid
        log.error(
            "worker %d (pid %d) ended: %s, exit code %d, minidump %s",
            dead.number,
            old_pid,
            cause,
            returncode,
            minidump,
        )
        attempts = 0
        failed: list[dict[str, Any]] = []
        while True:
            attempts += 1
            try:
                fresh = await self._launch()
            except FatalSupervisorError as error:
                self._fatal(str(error))
                return
            alive, revision = await self._reopen(fresh)
            if alive:
                break
            code = fresh.process.returncode if fresh.process.returncode is not None else -1
            failed.append(
                {
                    "generation": fresh.number,
                    "cause": ipc.classify_exit(code),
                    "exit_code": code,
                    "minidump": _newest_minidump(fresh.crash_dir),
                }
            )
            log.error("worker %d ended while reopening the project: %s", fresh.number, failed[-1])
            if attempts >= RECOVERY_ATTEMPTS:
                self._fatal(
                    f"recovery failed: {attempts} relaunched workers ended before they reopened "
                    f"{self.project_path}"
                )
                return
        self._current = fresh
        dead.replaced.set()
        recovery = Recovery(
            generation=fresh.number,
            cause=cause,
            exit_code=returncode,
            fault_code=dead.last_fault_code,
            minidump=minidump,
            old_pid=old_pid,
            new_pid=fresh.handshake.worker_pid if fresh.handshake else fresh.process.pid,
            project=self.project_path,
            revision=revision,
            recovery_ms=round((time.perf_counter() - detected) * 1000.0, 3),
            attempts=attempts,
            failed_attempts=failed,
        )
        self.recoveries.append(recovery)
        self.project_epoch += 1
        log.info("recovered: %s", recovery.to_json())
        for request_id, future in list(dead.pending.items()):
            if not future.done():
                future.set_result(_interrupted(request_id, recovery))
        dead.pending.clear()
        dead.sent.clear()
        self._ready.set()

    async def _reopen(self, fresh: _Generation) -> tuple[bool, int | None]:
        """Reopens the project the dead worker held in `fresh`: whether `fresh` is still alive,
        and the revision it reopened. The reply is raced against `fresh`'s end, so a worker that
        dies during the reopen cannot leave the recovery waiting."""
        if self.project_path is None:
            return True, None
        reply = self._post(
            fresh,
            {
                "method": "worker/reopen",
                "path": self.project_path,
                "untitled": self.project_untitled,
            },
        )
        exited = asyncio.ensure_future(fresh.process.wait())
        lost = asyncio.ensure_future(fresh.pipe_lost.wait())
        waiters: set[asyncio.Future[Any]] = {reply, exited, lost}
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        lost.cancel()
        if not reply.done():
            reply.cancel()
            fresh.pending.clear()
            fresh.sent.clear()
            try:
                await asyncio.wait_for(exited, EXIT_GRACE_S)
            except TimeoutError:
                fresh.process.kill()
                await fresh.process.wait()
            if fresh.transport:
                fresh.transport.close()
            return False, None
        exited.cancel()
        frame = reply.result()
        if "error" in frame:
            log.error("the relaunched worker could not reopen %s: %s", self.project_path, frame)
            self.project_path = None
            self.project_uuid = None
            self.project_untitled = False
            self.durable_revision = None
            return True, None
        revision = frame["result"]["revision"]
        assert isinstance(revision, int)
        return True, revision

    def _on_event(self, frame: dict[str, Any], running: dict[str, Any] | None) -> None:
        """A worker's `revision` event: the absolute store it holds (the saved file, or an
        untitled project's temporary store; None when none is open), its UUID, whether it is
        untitled, and its revision, sent after every commit and switch. A switch to another
        project goes to `on_project_switch` with the frame of the request that `running` names.
        A `job_progress` event goes to `on_job_event`."""
        if frame.get("event") == "job_progress" and self.on_job_event is not None:
            self.on_job_event(frame)
        if frame.get("event") == "revision":
            project = frame.get("project")
            project_uuid = frame.get("project_uuid")
            revision = frame.get("revision")
            path = project if isinstance(project, str) else None
            held = project_uuid if isinstance(project_uuid, str) and path is not None else None
            if (path, held) != (self.project_path, self.project_uuid):
                self.project_epoch += 1
            switched = held is not None and held != self.project_uuid
            self.project_path = path
            self.project_uuid = held
            self.project_untitled = frame.get("untitled") is True and self.project_path is not None
            self.durable_revision = revision if isinstance(revision, int) else None
            if switched and self.on_project_switch is not None:
                self.on_project_switch(running)

    def _fatal(self, message: str) -> None:
        """A fatal supervisor error after the session started: no call reaches a worker again."""
        self.fatal = message
        log.critical("fatal supervisor error: %s", message)
        sys.stderr.flush()
        os._exit(4)

    # ── Requests ─────────────────────────────────────────────────────────────────────────────

    async def wait_ready(self) -> None:
        """Returns once no relaunch is under way."""
        await self._ready.wait()

    async def request(self, frame: dict[str, Any]) -> dict[str, Any]:
        """Sends `frame` (an `id` is added) and returns the worker's reply, held while the worker
        is relaunched; a call in flight when its worker died returns `interrupted`."""
        while True:
            await self._ready.wait()
            generation = self._current
            assert generation is not None
            if (
                not generation.pipe_lost.is_set()
                and generation.process.returncode is None
                and generation.last_fault_code is None
            ):
                break
            # The worker is known to be gone, or replied `device_removed` / `timeout` and exits
            # right after that reply (02 §5), so the call was not sent: hold it for the relaunch.
            await generation.replaced.wait()
        return await self._post(generation, frame)

    def _post(
        self, generation: _Generation, frame: dict[str, Any]
    ) -> asyncio.Future[dict[str, Any]]:
        """Sends `frame` with a fresh `id`; the future of its reply."""
        request_id = str(uuid.uuid4())
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        generation.pending[request_id] = future
        generation.sent[request_id] = frame
        generation.send({**frame, "id": request_id})
        return future

    def status(self) -> dict[str, Any]:
        generation = self._current
        handshake = generation.handshake if generation else None
        return {
            "generation": generation.number if generation else None,
            "worker_pid": handshake.worker_pid if handshake else None,
            "build": handshake.build if handshake else None,
            "gpu_backend": self.config.gpu_backend,
            "gpu_status": ("ready" if handshake.gpu_ready else "unavailable")
            if handshake
            else None,
            "python": "allowed" if self.config.allow_python else "disabled",
            "project": self.project_path,
            "project_uuid": self.project_uuid,
            "untitled": self.project_untitled,
            "revision": self.durable_revision,
            "crash_dir": str(generation.crash_dir) if generation else None,
            "recoveries": [recovery.to_json() for recovery in self.recoveries],
        }


def _interrupted(request_id: str, recovery: Recovery) -> dict[str, Any]:
    return {
        "id": request_id,
        "error": {
            "code": "interrupted",
            "message": (
                f"the worker ended ({recovery.cause}) before it replied; the call is not re-sent"
            ),
            "details": {
                "cause": recovery.cause,
                "exit_code": recovery.exit_code,
                "fault_code": recovery.fault_code,
                "committed_revision": recovery.revision,
            },
        },
    }


def _newest_minidump(crash_dir: Path) -> str | None:
    dumps = sorted(crash_dir.glob("crashes/*/crash.dmp"), key=lambda path: path.stat().st_mtime)
    return str(dumps[-1]) if dumps else None
