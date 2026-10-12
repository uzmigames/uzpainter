"""The worker process and its pipe, fault detection and relaunch (02-runtime-topology.md §1, §5).

One `Supervisor` owns at most one worker at a time. Each launch (a generation `n`) runs
`UzPainter.exe --worker --pipe \\\\.\\pipe\\uzpainter-<supervisor-pid>-<n>` with the backend,
the Python policy and the deadline the supervisor was started with; the supervisor connects,
checks the handshake (a mismatch is fatal) and then forwards requests.

When the worker ends (process exit, or a broken pipe followed by the exit), the supervisor:
1. notes the cause (`ipc.classify_exit`, refined by a `device_removed` / `timeout` reply just
   before the exit) and the minidump the crash handler wrote, if any;
2. launches the next generation with the same backend and Python policy and reopens the project
   that was open: the file at rest holds the last committed revision (02 §6);
3. answers each call that was in flight with `interrupted {cause, committed_revision}`: it is
   never re-sent (recovery is never a silent replay); calls that arrived meanwhile were held and
   are forwarded to the new worker;
4. records the recovery, with its time from the detected death to the reopened project.
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import ipc

log = logging.getLogger("uzpainter.supervisor")

CONNECT_TIMEOUT_S = 120.0  # pipe connection and handshake (the worker creates its device first)
EXIT_GRACE_S = 10.0  # a worker whose pipe broke must exit within this, or it is killed
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
    pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
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
            if not future.done():
                future.set_result(frame)
        elif "id" in frame:
            log.error("worker %d replied to an unknown request: %s", self.number, frame)
        # Notifications (jobs, revisions) are delivered by phase2.3; nothing subscribes yet.

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

    def to_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


class Supervisor:
    """The worker lifecycle and the request path to it."""

    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self.recoveries: list[Recovery] = []
        self.project_path: str | None = None
        self._numbers = itertools.count(1)
        self._current: _Generation | None = None
        self._ready = asyncio.Event()
        self._monitor: asyncio.Task[None] | None = None
        self._closing = False
        self.fatal: str | None = None

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
        process = await asyncio.create_subprocess_exec(
            *self.config.argv(pipe, crash_dir), stdin=subprocess.DEVNULL, stdout=stdout, stderr=None
        )
        loop = asyncio.get_running_loop()
        generation = _Generation(number, pipe, crash_dir, process, loop.create_future())
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
        try:
            fresh = await self._launch()
        except FatalSupervisorError as error:
            self._fatal(str(error))
            return
        self._current = fresh
        dead.replaced.set()
        revision: int | None = None
        if self.project_path is not None:
            reply = await self._send(fresh, _call("project_open", {"path": self.project_path}))
            if "error" in reply:
                log.error("the relaunched worker could not reopen %s: %s", self.project_path, reply)
                self.project_path = None
            else:
                revision = reply["result"]["revision"]
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
        )
        self.recoveries.append(recovery)
        log.info("recovered: %s", recovery.to_json())
        for request_id, future in list(dead.pending.items()):
            if not future.done():
                future.set_result(_interrupted(request_id, recovery))
        dead.pending.clear()
        self._ready.set()

    def _fatal(self, message: str) -> None:
        """A fatal supervisor error after the session started: no call reaches a worker again."""
        self.fatal = message
        log.critical("fatal supervisor error: %s", message)
        sys.stderr.flush()
        os._exit(4)

    # ── Requests ─────────────────────────────────────────────────────────────────────────────

    async def request(self, frame: dict[str, Any]) -> dict[str, Any]:
        """Sends `frame` (an `id` is added) and returns the worker's reply, held while the worker
        is relaunched; a call in flight when its worker died returns `interrupted`."""
        while True:
            await self._ready.wait()
            generation = self._current
            assert generation is not None
            if not generation.pipe_lost.is_set() and generation.process.returncode is None:
                break
            # The worker is known to be gone, so the call was not sent: hold it for the relaunch.
            await generation.replaced.wait()
        reply = await self._send(generation, frame)
        if frame.get("method") == "tools/call" and frame.get("name") == "run_python":
            # A script may open, save or close projects itself, and keeps what it did before it
            # raised: ask the worker what it holds now.
            await self._refresh_project(generation)
        else:
            self._track_project(frame, reply)
        return reply

    async def _send(self, generation: _Generation, frame: dict[str, Any]) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        generation.pending[request_id] = future
        generation.send({**frame, "id": request_id})
        return await future

    def _track_project(self, frame: dict[str, Any], reply: dict[str, Any]) -> None:
        """The project the worker holds, for the relaunch."""
        if frame.get("method") != "tools/call":
            return
        name = frame.get("name")
        result = reply.get("result")
        if not isinstance(result, dict):
            return
        if name == "project_open":
            self.project_path = str(result["path"])
        elif name == "project_close":
            self.project_path = None
        elif name == "project_inspect":
            self.project_path = result.get("path") if result.get("open") else None

    async def _refresh_project(self, generation: _Generation) -> None:
        if generation is not self._current or not self._ready.is_set():
            return  # the worker died meanwhile; the relaunch reopened what it knew
        reply = await self._send(generation, _call("project_inspect", {}))
        result = reply.get("result")
        if isinstance(result, dict) and generation is self._current:
            self.project_path = result.get("path") if result.get("open") else None

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
            "crash_dir": str(generation.crash_dir) if generation else None,
            "recoveries": [recovery.to_json() for recovery in self.recoveries],
        }


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"method": "tools/call", "name": name, "arguments": arguments}


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
