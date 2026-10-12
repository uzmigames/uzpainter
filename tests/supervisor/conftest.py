"""Shared fixtures of the supervisor and worker tests (src/supervisor/,
python/uzpainter_supervisor/; task phase2.1_supervisor-ipc-worker).

`UzPainter.exe` comes from one `zig build painter` (Debug, so the worker's fault hooks are
compiled in, decision 120) into a temporary prefix per test session. Two clients drive it:

- `Mcp`: an MCP client on the supervisor's stdio (`UzPainter.exe --mcp`), speaking JSON-RPC
  lines and checking that every line on stdout is a protocol frame;
- `Pipe`: the test process acting as a worker's supervisor. The worker accepts only the process
  whose id its pipe name carries, so the test names the pipe after its own process id.
"""

from __future__ import annotations

import ctypes
import itertools
import json
import os
import queue
import shutil
import subprocess
import textwrap
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLANE = REPO_ROOT / "parity" / "fixtures" / "meshes" / "plane.obj"
JSON_PREFIX = "UZP_JSON:"
NO_GPU = os.environ.get("UZP_NO_GPU") == "1"

_pipe_numbers = itertools.count(int(time.time()) % 100000 * 1000)


@pytest.fixture(scope="session")
def painter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`UzPainter.exe` of a fresh Debug `zig build painter` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; UzPainter.exe cannot be built")
    prefix = tmp_path_factory.mktemp("painter")
    build = subprocess.run(
        [zig, "build", "painter", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "UzPainter.exe"


def pid_alive(pid: int) -> bool:
    """Whether process `pid` is still running."""
    synchronize = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return False
    try:
        return int(ctypes.windll.kernel32.WaitForSingleObject(handle, 0)) != 0
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def wait_until_gone(pid: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.05)
    return False


def kill_pid(pid: int) -> None:
    """Terminates process `pid` from outside (TerminateProcess)."""
    terminate = 0x0001
    handle = ctypes.windll.kernel32.OpenProcess(terminate, False, pid)
    assert handle, f"cannot open process {pid}"
    try:
        assert ctypes.windll.kernel32.TerminateProcess(handle, 1)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def run_script(painter: Path, tmp_path: Path, body: str) -> Any:
    """`UzPainter.exe run` of `body` (single process); the script's `result`."""
    path = tmp_path / f"script-{next(_pipe_numbers)}.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    process = subprocess.run(
        [str(painter), "run", str(path), "--gpu-backend", "vulkan"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    lines = [line for line in process.stdout.splitlines() if line.startswith(JSON_PREFIX)]
    assert process.returncode == 0 and lines, process.stdout + process.stderr
    return json.loads(lines[-1][len(JSON_PREFIX) :])["result"]


def make_project(painter: Path, tmp_path: Path) -> Path:
    """A saved project of the plane fixture, made by `UzPainter.exe run`."""
    path = tmp_path / "plane.uzp"
    run_script(
        painter,
        tmp_path,
        f"""
        from uzpainter import project
        project.create({str(PLANE.as_posix())!r}, project.Settings(default_texture_resolution=256))
        project.save_as({str(path.as_posix())!r})
        result = True
        """,
    )
    return path


INSERT_FILL = """
from uzpainter import layerstack as ls, project, textureset as ts
ls.insert_fill(ls.InsertPosition.from_textureset_stack(ts.get_active_stack()))
result = None
"""


class Pipe:
    """The test process as a worker's supervisor, on the worker's pipe."""

    def __init__(self, painter: Path, tmp_path: Path, *args: str) -> None:
        self.name = rf"\\.\pipe\uzpainter-{os.getpid()}-{next(_pipe_numbers)}"
        self.stderr_path = tmp_path / f"worker-{next(_pipe_numbers)}.log"
        self._stderr = self.stderr_path.open("wb")
        self.process = subprocess.Popen(
            [
                str(painter),
                "--worker",
                "--pipe",
                self.name,
                "--output-root",
                str(tmp_path / "out"),
                "--crash-dir",
                str(tmp_path / "crashes"),
                *args,
            ],
            stdin=subprocess.DEVNULL,
            stdout=self._stderr,
            stderr=self._stderr,
        )
        self.file = self._open()
        self._buffer = b""
        self._ids = itertools.count(1)
        self.events: list[dict[str, Any]] = []  # notifications, in arrival order
        self.handshake = self.frame()

    def _open(self) -> IO[bytes]:
        deadline = time.monotonic() + 120
        while True:
            try:
                return open(self.name, "r+b", buffering=0)
            except OSError:
                if self.process.poll() is not None or time.monotonic() > deadline:
                    raise AssertionError(f"worker did not open its pipe: {self.log()}") from None
                time.sleep(0.02)

    def log(self) -> str:
        if not self._stderr.closed:
            self._stderr.flush()
        return self.stderr_path.read_text(encoding="utf-8", errors="replace")

    def frame(self) -> dict[str, Any]:
        while b"\n" not in self._buffer:
            try:
                chunk = self.file.read(65536)
            except OSError:
                chunk = b""
            if not chunk:
                raise EOFError(f"the worker closed the pipe: {self.log()}")
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        value = json.loads(line)
        assert isinstance(value, dict)
        return value

    def send_raw(self, data: bytes) -> None:
        self.file.write(data)

    def request(self, frame: dict[str, Any]) -> dict[str, Any]:
        request_id = f"t{next(self._ids)}"
        self.send_raw((json.dumps({**frame, "id": request_id}) + "\n").encode())
        reply = self.frame()
        while "event" in reply and "id" not in reply:
            self.events.append(reply)
            reply = self.frame()
        assert reply.get("id") == request_id, reply
        return reply

    def call(
        self, name: str, arguments: dict[str, Any] | None = None, **extra: Any
    ) -> dict[str, Any]:
        return self.request(
            {"method": "tools/call", "name": name, "arguments": arguments or {}, **extra}
        )

    def close(self) -> None:
        self.file.close()
        try:
            self.process.wait(30)
        finally:
            if self.process.poll() is None:
                self.process.kill()
            self._stderr.close()


class Mcp:
    """An MCP client on `UzPainter.exe --mcp`'s stdio."""

    def __init__(
        self,
        painter: Path,
        tmp_path: Path,
        *args: str,
        env: dict[str, str] | None = None,
        initialize: bool = True,
        ledger: Path | None = None,
    ) -> None:
        # Never the user's own ledger: one per test unless the test shares one.
        self.ledger = ledger or tmp_path / f"ledger-{next(_pipe_numbers)}.sqlite3"
        self.stderr_path = tmp_path / f"supervisor-{next(_pipe_numbers)}.log"
        self._stderr = self.stderr_path.open("wb")
        self.process = subprocess.Popen(
            [
                str(painter),
                "--mcp",
                "--output-root",
                str(tmp_path / "out"),
                "--crash-dir",
                str(tmp_path / "crashes"),
                "--ledger",
                str(self.ledger),
                *args,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            env={**os.environ, **(env or {})},
        )
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.stdout_lines: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()
        self._ids = itertools.count(1)
        self._replies: dict[int, dict[str, Any]] = {}
        self.notifications: list[dict[str, Any]] = []  # in arrival order
        if initialize:
            self.request(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "uzpainter-tests", "version": "0"},
                },
            )
            self.notify("notifications/initialized")

    def _read(self) -> None:
        assert self.process.stdout is not None
        for raw in self.process.stdout:
            line = raw.decode("utf-8")
            self.stdout_lines.append(line)
            self.lines.put(line)
        self.lines.put(None)

    def log(self) -> str:
        if not self._stderr.closed:
            self._stderr.flush()
        return self.stderr_path.read_text(encoding="utf-8", errors="replace")

    def _write(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        self.process.stdin.flush()

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def send(self, method: str, params: dict[str, Any]) -> int:
        """Writes a request without waiting for its reply; its id (`reply` reads the reply)."""
        request_id = next(self._ids)
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return request_id

    def request(self, method: str, params: dict[str, Any], timeout: float = 300) -> dict[str, Any]:
        return self.reply(self.send(method, params), timeout)

    def reply(self, request_id: int, timeout: float = 300) -> dict[str, Any]:
        """The result of request `request_id`; replies to other requests are kept for them."""
        if request_id in self._replies:
            return self._replies.pop(request_id)
        method = f"request {request_id}"
        deadline = time.monotonic() + timeout
        while True:
            try:
                line = self.lines.get(timeout=max(deadline - time.monotonic(), 0.01))
            except queue.Empty:
                raise AssertionError(f"no reply to {method} in {timeout} s: {self.log()}") from None
            if line is None:
                raise AssertionError(f"the supervisor closed stdout: {self.log()}")
            message = json.loads(line)
            assert message.get("jsonrpc") == "2.0", line
            if "id" not in message or "method" in message:  # a notification or server request
                if "id" not in message:
                    self.notifications.append(message)
                continue
            assert "error" not in message, message
            result = message["result"]
            assert isinstance(result, dict)
            if message["id"] == request_id:
                return result
            self._replies[message["id"]] = result

    def call(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The structured content of a tool call: `{result, committed_revision?, receipt}` or
        `{error, receipt}`; `meta` is the request's `_meta` (a progress token)."""
        params: dict[str, Any] = {"name": name, "arguments": arguments or {}}
        if meta is not None:
            params["_meta"] = meta
        return self.content(self.request("tools/call", params))

    @staticmethod
    def content(result: dict[str, Any]) -> dict[str, Any]:
        content = result["structuredContent"]
        assert isinstance(content, dict)
        assert result.get("isError", False) == ("error" in content)
        return content

    def status(self) -> dict[str, Any]:
        result = self.call("supervisor_status")["result"]
        assert isinstance(result, dict)
        return result

    def stdout_is_protocol_only(self) -> bool:
        return all(json.loads(line).get("jsonrpc") == "2.0" for line in self.stdout_lines)

    def close(self) -> int:
        assert self.process.stdin is not None
        if self.process.poll() is None:
            self.process.stdin.close()
        try:
            return self.process.wait(60)
        finally:
            if self.process.poll() is None:
                self.process.kill()
            self._stderr.close()


@pytest.fixture
def pipes(painter: Path, tmp_path: Path) -> Iterator[list[Pipe]]:
    opened: list[Pipe] = []
    yield opened
    for pipe in opened:
        if pipe.process.poll() is None:
            pipe.process.kill()
        pipe.close()


@pytest.fixture
def sessions() -> Iterator[list[Mcp]]:
    opened: list[Mcp] = []
    yield opened
    for session in opened:
        session.close()
