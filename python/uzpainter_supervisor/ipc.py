"""The supervisor's side of the pipe protocol (src/supervisor/ipc.h, 02-runtime-topology.md §2).

Frames are newline-delimited UTF-8 JSON objects in the canonical form both sides write
(`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, which escapes every
control character, so a frame never holds a literal newline). The worker speaks first with the
handshake; any difference from what the supervisor requested is a fatal supervisor error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PROTOCOL = "uzp-ipc/1"
MAX_FRAME_BYTES = 16 << 20

# The worker's exit codes (src/supervisor/worker.h).
EXIT_USAGE = 2
EXIT_START_FAILED = 3
EXIT_SUPERVISOR_GONE = 4
EXIT_DEVICE_FAULT = 5
EXIT_TEST_KILL = 77  # fault_hooks.h, kKillExitCode
ABORT_EXCEPTION_CODE = 0x40000015  # STATUS_FATAL_APP_EXIT, how the worker reports abort()


def encode_frame(frame: dict[str, Any]) -> bytes:
    """The canonical text of `frame` and its newline; `ValueError` when it is too long."""
    text = json.dumps(frame, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    data = text.encode("utf-8")
    if len(data) > MAX_FRAME_BYTES:
        raise ValueError(f"frame of {len(data)} bytes exceeds {MAX_FRAME_BYTES}")
    return data + b"\n"


class FrameDecoder:
    """Splits a byte stream into frames."""

    def __init__(self) -> None:
        self._pending = bytearray()
        self._discarding = False

    def feed(self, data: bytes) -> tuple[list[dict[str, Any]], list[str]]:
        """The frames `data` completes, in order, and one message per rejected frame (not
        UTF-8 JSON, not an object, or longer than `MAX_FRAME_BYTES`)."""
        frames: list[dict[str, Any]] = []
        errors: list[str] = []
        while data:
            newline = data.find(b"\n")
            chunk = data if newline < 0 else data[:newline]
            data = b"" if newline < 0 else data[newline + 1 :]
            if self._discarding:
                self._discarding = newline < 0
                continue
            self._pending += chunk
            if len(self._pending) > MAX_FRAME_BYTES:
                self._pending.clear()
                self._discarding = newline < 0
                errors.append(f"frame exceeds {MAX_FRAME_BYTES} bytes")
                continue
            if newline < 0:
                break
            text = bytes(self._pending).rstrip(b"\r")
            self._pending.clear()
            if not text:
                continue
            try:
                value = json.loads(text.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                errors.append(f"frame is not JSON: {error}")
                continue
            if not isinstance(value, dict):
                errors.append("frame is not a JSON object")
                continue
            frames.append(value)
        return frames, errors


class HandshakeMismatch(Exception):
    """The worker's handshake differs from what the supervisor requested: a fatal error."""

    def __init__(self, mismatches: list[str]) -> None:
        super().__init__("worker handshake mismatch: " + "; ".join(mismatches))
        self.mismatches = mismatches


@dataclass(frozen=True)
class Requested:
    """What the supervisor asked its worker for."""

    protocol: str
    gpu_backend: str
    python_allowed: bool


@dataclass(frozen=True)
class Handshake:
    worker_pid: int
    build: str
    gpu_backend: str
    gpu_ready: bool
    python_allowed: bool


def check_handshake(frame: dict[str, Any], requested: Requested) -> Handshake:
    """The handshake `frame` reports; `HandshakeMismatch` naming every field that differs from
    `requested` (protocol, backend, Python policy) or is malformed. Never a fallback."""
    mismatches: list[str] = []
    protocol = frame.get("protocol")
    if protocol != requested.protocol:
        mismatches.append(
            f"protocol: requested {requested.protocol!r}, worker reported {protocol!r}"
        )
    backend = frame.get("gpu_backend")
    if backend != requested.gpu_backend:
        mismatches.append(
            f"gpu_backend: requested {requested.gpu_backend!r}, worker reported {backend!r}"
        )
    python = frame.get("python")
    wanted = "allowed" if requested.python_allowed else "disabled"
    if python != wanted:
        mismatches.append(f"python: requested {wanted!r}, worker reported {python!r}")
    gpu_status = frame.get("gpu_status")
    if gpu_status not in ("ready", "unavailable"):
        mismatches.append(f"gpu_status: {gpu_status!r} is neither 'ready' nor 'unavailable'")
    pid = frame.get("worker_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        mismatches.append(f"worker_pid: {pid!r} is not a process id")
    build = frame.get("build")
    if not isinstance(build, str) or not build:
        mismatches.append(f"build: {build!r} is not a build string")
    if mismatches:
        raise HandshakeMismatch(mismatches)
    assert isinstance(pid, int) and isinstance(build, str)
    return Handshake(pid, build, str(backend), gpu_status == "ready", python == "allowed")


def classify_exit(returncode: int) -> str:
    """Why a worker ended, from its exit code: `abort`, `native_fault` (an SEH exception the
    crash handler reported), `device_fault` (the deliberate exit after `device_removed` or
    `timeout`), `supervisor_gone`, `start_failed` or `terminated` (killed from outside)."""
    code = returncode & 0xFFFFFFFF
    if code == ABORT_EXCEPTION_CODE:
        return "abort"
    if code >= 0xC0000000:
        return "native_fault"
    if code == EXIT_DEVICE_FAULT:
        return "device_fault"
    if code == EXIT_SUPERVISOR_GONE:
        return "supervisor_gone"
    if code in (EXIT_START_FAILED, EXIT_USAGE):
        return "start_failed"
    return "terminated"
