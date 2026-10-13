"""Shared fixtures of the supervisor and worker tests (src/supervisor/,
python/uzpainter_supervisor/; task phase2.1_supervisor-ipc-worker).

`UzPainter.exe` comes from one `zig build painter` (Debug, so the worker's fault hooks are
compiled in, decision 120) into a temporary prefix per test session. Two clients drive it:

- `Mcp`: an MCP client on the supervisor's stdio (`UzPainter.exe --mcp`), speaking JSON-RPC
  lines and checking that every line on stdout is a protocol frame;
- `Pipe`: the test process acting as a worker's supervisor. The worker accepts only the process
  whose id its pipe name carries, so the test names the pipe after its own process id.

Settling evidence (task phase2.4_supervisor-worker, decision 150): a test that settles a case of
`docs/architecture/02-runtime-topology.md` §7 carries `@pytest.mark.settling(<case>, ...)`. With
`UZP_SETTLING_REPORT=<path>` the run merges each tagged test's result, run time and the
recoveries its supervisors reported, and the overhead measurements, into that report
(`tools/parity/settling/report.py`). `UZP_SUPERVISOR_BACKEND` (default `vulkan`) is the backend
the tagged MCP tests start their supervisors on.

MCP contract evidence (task phase2.8_mcp-server, decision 186): a test that runs a Phase 2
contract fixture of `docs/architecture/11-mcp-server.md` §7 carries
`@pytest.mark.mcp_contract(<fixture>, transport=<stdio|http>)`. With
`UZP_MCP_CONTRACT_REPORT=<path>` the run merges each fixture's result per transport (a fixture
fails when any of its tests fails), its test count and run time into that report
(`tools/parity/settling/mcp_contract.py`).
"""

from __future__ import annotations

import ctypes
import datetime
import hashlib
import itertools
import json
import os
import queue
import shutil
import subprocess
import textwrap
import threading
import time
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

import pytest

from tools.parity.settling import mcp_contract
from tools.parity.settling import report as settling_report

REPO_ROOT = Path(__file__).resolve().parents[2]
PLANE = REPO_ROOT / "parity" / "fixtures" / "meshes" / "plane.obj"
# Painter's substance config (decisions 134, 207): the one OCIO configuration a project is made in.
OCIO_CONFIG = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"
JSON_PREFIX = "UZP_JSON:"
NO_GPU = os.environ.get("UZP_NO_GPU") == "1"
BACKEND = os.environ.get("UZP_SUPERVISOR_BACKEND", "vulkan")

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
    exe = prefix / "bin" / "UzPainter.exe"
    _settled.exe_sha256 = hashlib.sha256(exe.read_bytes()).hexdigest()
    return exe


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


def run_script(painter: Path, tmp_path: Path, body: str, backend: str = "vulkan") -> Any:
    """`UzPainter.exe run` of `body` (single process) on `backend`; the script's `result`."""
    path = tmp_path / f"script-{next(_pipe_numbers)}.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    process = subprocess.run(
        [str(painter), "run", str(path), "--gpu-backend", backend],
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
        creationflags: int = 0,
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
            creationflags=creationflags,
        )
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.stdout_lines: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()
        self._ids = itertools.count(1)
        self._replies: dict[int, dict[str, Any]] = {}
        self.notifications: list[dict[str, Any]] = []  # in arrival order
        self.last_status: dict[str, Any] | None = None  # the last `supervisor_status` result
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
        self.last_status = result
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


def with_a_refused_bitmap(session: Mcp, tmp_path: Path) -> int:
    """An untitled Legacy project of the plane at 256 px whose fill takes BaseColor from a 512x256
    8-bit colour bitmap: bilinear minification of a non-square image, where the texture unit is not
    measured (decision 084), so the evaluator refuses it with `NotYetSupported` (practical-e2e B4).
    The support check reads no image in Legacy; under OCIO a bitmap Session O does not record is
    refused before mutation instead (decision 240). The fill's uid."""
    created = session.call(
        "project_create",
        {"mesh": str(PLANE), "settings": {"default_texture_resolution": 256}, "wait": True},
    )
    assert created["result"]["status"] == "committed", created
    width, height = 512, 256

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return len(data).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")

    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    rows = (b"\x00" + bytes([200, 120, 40]) * width) * height
    wide = tmp_path / "wide.png"
    wide.write_bytes(
        bytes([0x89])
        + b"PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    imported = session.call("resource_import", {"path": str(wide), "usage": "TEXTURE"})
    assert imported["result"]["status"] == "committed", imported
    inserted = session.call(
        "layer_insert", {"kind": "fill", "params": {"active_channels": ["BaseColor"]}}
    )
    fill = inserted["result"]["returned"]["node"]
    assert isinstance(fill, int), inserted
    bitmap = {"kind": "bitmap", "resource": "wide", "color_space": "sRGB"}
    sourced = session.call("source_set", {"uid": fill, "channel": "BaseColor", "source": bitmap})
    assert sourced["result"]["status"] == "committed", sourced
    return fill


@pytest.fixture
def pipes(painter: Path, tmp_path: Path) -> Iterator[list[Pipe]]:
    opened: list[Pipe] = []
    yield opened
    for pipe in opened:
        if pipe.process.poll() is None:
            pipe.process.kill()
        pipe.close()


@pytest.fixture
def sessions(request: pytest.FixtureRequest) -> Iterator[list[Mcp]]:
    opened: list[Mcp] = []
    yield opened
    for session in opened:
        session.close()
    _settled.statuses.setdefault(request.node.nodeid, []).extend(
        session.last_status for session in opened if session.last_status is not None
    )


# --- settling evidence (decision 150) --------------------------------------------------------


class _Settled:
    """What this run settled: per tagged test, its outcome and its sessions' last statuses."""

    def __init__(self) -> None:
        self.exe_sha256: str | None = None
        self.calls: dict[str, tuple[tuple[str, ...], str, float]] = {}
        self.statuses: dict[str, list[dict[str, Any]]] = {}
        self.metrics: dict[str, dict[str, float]] = {}
        self.overhead: list[dict[str, Any]] = []
        # Per (fixture, transport): the outcome and run time of each tagged test.
        self.contract: dict[tuple[str, str], list[tuple[str, float]]] = {}


_settled = _Settled()


class Settling:
    """A tagged test's handle on the report: numbers it measured itself."""

    def __init__(self, nodeid: str) -> None:
        self._nodeid = nodeid

    def metric(self, name: str, value: float) -> None:
        _settled.metrics.setdefault(self._nodeid, {})[name] = round(value, 3)

    def overhead(self, entry: dict[str, Any]) -> None:
        _settled.overhead.append(entry)

    @staticmethod
    def stamp() -> dict[str, str]:
        assert _settled.exe_sha256 is not None
        return {"date": datetime.date.today().isoformat(), "exe_sha256": _settled.exe_sha256}


@pytest.fixture
def settling(request: pytest.FixtureRequest) -> Settling:
    return Settling(request.node.nodeid)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "settling(*cases): the test settles these 02 §7 cases (decision 150)"
    )
    config.addinivalue_line(
        "markers",
        "mcp_contract(*fixtures, transport): the test runs these 11 §7 Phase 2 contract fixtures "
        "on that transport (decision 186)",
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Any:
    report = yield
    marker = item.get_closest_marker("settling")
    if marker is not None and report.when == "call":
        _settled.calls[item.nodeid] = (tuple(marker.args), report.outcome, report.duration)
    for contract in item.iter_markers("mcp_contract"):
        if report.when == "call" and report.outcome != "skipped":
            for fixture in contract.args:
                key = (fixture, contract.kwargs["transport"])
                _settled.contract.setdefault(key, []).append((report.outcome, report.duration))
    return report


def _case_entries() -> list[dict[str, Any]]:
    entries = []
    for nodeid, (cases, outcome, seconds) in _settled.calls.items():
        if outcome == "skipped":
            continue
        statuses = _settled.statuses.get(nodeid, [])
        recoveries = [
            {
                "cause": settling_report.identifier(recovery["cause"]),
                "recovery_ms": round(float(recovery["recovery_ms"]), 3),
                "attempts": int(recovery.get("attempts", 1)),
            }
            for status in statuses
            for recovery in status["recoveries"]
        ]
        for case in cases:
            entry: dict[str, Any] = {
                "id": case,
                "backend": statuses[-1]["gpu_backend"] if statuses else BACKEND,
                "result": "pass" if outcome == "passed" else "fail",
                "seconds": round(seconds, 3),
                "recoveries": recoveries,
                **Settling.stamp(),
            }
            if statuses:
                entry["gpu_status"] = statuses[-1]["gpu_status"]
            if nodeid in _settled.metrics:
                entry["metrics"] = _settled.metrics[nodeid]
            entries.append(entry)
    return entries


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    target = os.environ.get("UZP_SETTLING_REPORT")
    if target and (_settled.calls or _settled.overhead):
        settling_report.write(Path(target), _case_entries(), _settled.overhead)
    contract = os.environ.get("UZP_MCP_CONTRACT_REPORT")
    if contract and _settled.contract:
        mcp_contract.write(
            Path(contract),
            [
                {
                    "id": fixture,
                    "transport": transport,
                    "result": "pass" if all(o == "passed" for o, _ in runs) else "fail",
                    "tests": len(runs),
                    "seconds": round(sum(seconds for _, seconds in runs), 3),
                    **Settling.stamp(),
                }
                for (fixture, transport), runs in _settled.contract.items()
            ],
        )
