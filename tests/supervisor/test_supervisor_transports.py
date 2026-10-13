"""The MCP transports, registry checks, roots and `run_python` through `UzPainter.exe --mcp`
(python/uzpainter_supervisor/main.py, registry.py, roots.py, transport_http.py; task
phase2.5_mcp-transport-registry items 3.1-3.6; decisions 158, 159).

CPU only: every supervisor runs `--gpu-backend vulkan` (no device is created), and the Debug build's
`--test-faults` gives the typed `test_mutation` and the long `test_job`. Each supervisor writes its
own ledger under the test's folder. The pure-Python halves of these checks are in
test_registry.py, test_roots.py and test_transport_http.py.
"""

from __future__ import annotations

import _winapi
import base64
import hashlib
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from tests.supervisor.conftest import Mcp, make_project

BASE = ("--gpu-backend", "vulkan", "--test-faults")
TOKEN = "phase2.5-test-token"
INSERT = (
    "from uzpainter import layerstack as ls, textureset as ts\n"
    "ls.insert_fill(ls.InsertPosition.from_textureset_stack(ts.get_active_stack()))\n"
)


def ledger_rows(ledger: Path, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    with sqlite3.connect(ledger) as db:
        rows = db.execute(sql, params).fetchall()
    db.close()
    return rows


def revision_of(session: Mcp) -> int:
    revision = session.call("project_inspect")["result"]["revision"]
    assert isinstance(revision, int)
    return revision


def test_stdio_carries_protocol_frames_only_under_logging_load(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.1, 2.2: while the worker writes to its stdout and stderr and the supervisor logs every
    call, stdout carries JSON-RPC frames only; the logs reach stderr and the ledger."""
    session = Mcp(painter, tmp_path, *BASE, "--allow-python")
    sessions.append(session)
    noise = (
        "import os, sys\n"
        "os.write(1, b'worker-stdout-noise\\n' * 200)\n"
        "os.write(2, b'worker-stderr-noise\\n' * 200)\n"
        "print('captured by the script')\n"
        "result = 1\n"
    )
    for _ in range(40):
        assert session.call("run_python", {"code": noise})["result"]["result"] == 1
        refused = session.call("project_save", {"mode": "bogus"})
        assert refused["error"]["code"] == "invalid_arguments"
    lines = list(session.stdout_lines)
    assert len(lines) >= 81
    for line in lines:
        frame = json.loads(line)
        assert frame["jsonrpc"] == "2.0" and ("id" in frame or "method" in frame), line
    assert all("noise" not in line for line in lines)
    assert session.close() == 0
    log = session.log()
    assert "worker-stdout-noise" in log and "worker-stderr-noise" in log
    assert "call run_python: ok" in log
    logged = ledger_rows(session.ledger, "SELECT level, message FROM log")
    assert sum(1 for _, message in logged if message.startswith("call run_python: ok")) == 40
    assert (
        sum(1 for _, message in logged if "project_save: error invalid_arguments" in message) == 40
    )


def test_schema_references_and_the_omission_rule_through_mcp(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.3, 3.6, 2.4, 2.5: out-of-bound, unknown-enum and dangling-reference arguments are
    refused before admission; a call without key and precondition gets both generated and
    returned; a key without its precondition is refused; results carry the contract fields."""
    project = make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, *BASE)
    sessions.append(session)
    revision = session.call("project_open", {"path": str(project), "wait": True})["result"][
        "revision"
    ]
    for name, arguments, argument, rule in (
        ("project_save", {"mode": "bogus"}, "/mode", "enum"),
        ("job_list", {"limit": 0}, "/limit", "minimum"),
        ("isolate_layer", {"uid": 0, "channels": ["BaseColor"], "path": "x"}, "/uid", "minimum"),
        ("isolate_layer", {"uid": 999999, "channels": ["BaseColor"], "path": "x"}, "/uid", None),
        ("evaluate_channel", {"channel": "BaseColor", "texture_set": "nope"}, "/texture_set", None),
        ("test_job", {"name": "J", "steps": "many"}, "/steps", "type"),
    ):
        reply = session.call(name, arguments)
        error = reply["error"]
        assert error["code"] == "invalid_arguments", reply
        [detail] = error["details"]["errors"]
        assert detail["argument"] == argument, reply
        if rule is None:
            assert detail["reason"] == "dangling_reference"
        else:
            assert detail["rule"] == rule
        assert reply.get("job_id") is None
    assert ledger_rows(session.ledger, "SELECT tool FROM job WHERE tool != 'project_open'") == []

    generated = session.call("test_mutation", {"name": "A"})
    receipt = generated["receipt"]
    assert receipt["key_source"] == "supervisor" and receipt["idempotency_key"].startswith("sup-")
    assert receipt["expected_revision"] == revision
    assert generated["revision"] == revision and generated["committed_revision"] == revision + 1
    [created] = generated["created"]
    assert generated["job_id"] == receipt["job_id"] and generated["warnings"] == []
    retry = session.call(
        "test_mutation",
        {"name": "A", "idempotency_key": receipt["idempotency_key"], "expected_revision": revision},
    )
    assert retry["receipt"]["admission"] == "stored_outcome" and retry["created"] == [created]
    keyed = session.call("test_mutation", {"name": "B", "idempotency_key": "k-only"})
    assert keyed["error"]["code"] == "invalid_arguments", keyed
    assert keyed["error"]["details"]["errors"][0]["argument"] == "/expected_revision"
    assert revision_of(session) == revision + 1
    assert (
        ledger_rows(session.ledger, "SELECT tool FROM job WHERE idempotency_key = 'k-only'") == []
    )
    found = session.call(
        "isolate_layer", {"uid": created, "channels": ["BaseColor"], "path": "iso"}
    )
    assert found["result"]["uid"] == created, found
    assert session.close() == 0


@pytest.mark.mcp_contract("path_outside_roots", transport="stdio")
def test_roots_confine_paths_and_never_echo_them(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.4, 2.7: with --roots, absolute, relative, `file:///` and reparse-point paths outside the
    root are refused before the worker sees them and never echoed; the Windows forms inside are
    normalised; results reference nothing outside the roots."""
    # The export root holds the output root the Mcp client names (tmp_path / "out").
    projects, exports, outside = tmp_path / "projects", tmp_path / "out", tmp_path / "outside"
    for folder in (projects, exports, outside):
        folder.mkdir()
    made = make_project(painter, tmp_path)
    inside = projects / "plane.uzp"
    shutil.copy(made, inside)
    shutil.copy(made, outside / "plane.uzp")
    _winapi.CreateJunction(str(outside), str(projects / "link"))
    session = Mcp(
        painter,
        tmp_path,
        *BASE,
        "--allow-python",
        "--roots",
        f"project={projects};export={exports}",
    )
    sessions.append(session)
    for path in (
        str(outside / "plane.uzp"),
        "..\\outside\\plane.uzp",
        (outside / "plane.uzp").as_uri(),
        "link\\plane.uzp",
        str(projects / "link" / "plane.uzp"),
        "\\\\?\\" + str(outside / "plane.uzp"),
    ):
        refused = session.call("project_open", {"path": path, "wait": True})
        assert refused["error"]["code"] == "path_outside_roots", (path, refused)
        assert refused["error"]["details"]["argument"] == "/path"
        assert refused["error"]["details"]["root"] == "project"
    echoes = [json.dumps(str(outside))[1:-1], json.dumps(r"outside\plane")[1:-1]]
    assert not [line for line in session.stdout_lines for echo in echoes if echo in line]
    assert ledger_rows(session.ledger, "SELECT tool FROM job") == []

    opened = session.call("project_open", {"path": inside.as_uri().upper(), "wait": True})
    assert "result" in opened, opened
    assert Path(opened["receipt"]["project"]).resolve() == inside.resolve()
    revision = opened["result"]["revision"]
    created = session.call("test_mutation", {"name": "A"})["created"][0]
    iso = session.call("isolate_layer", {"uid": created, "channels": ["BaseColor"], "path": "iso"})
    directory = Path(iso["result"]["export"]["directory"])
    assert directory.is_relative_to(exports.resolve() / "iso"), iso
    escape = session.call(
        "isolate_layer", {"uid": created, "channels": ["BaseColor"], "path": "..\\outside"}
    )
    assert escape["error"]["code"] == "path_outside_roots"
    assert escape["error"]["details"]["root"] == "export"
    # capture (decision 148): its path is confined to the export root, and its PNG comes back,
    # downscaled to 8 bits and at most 512 pixels by the supervisor (decision 165), as the one
    # image content block.
    shot = session.request(
        "tools/call", {"name": "capture", "arguments": {"mode": "base_color", "path": "caps/b.png"}}
    )
    body = Mcp.content(shot)
    png = Path(body["result"]["files"]["png"])
    assert png.is_relative_to(exports.resolve() / "caps"), shot
    [text, image] = shot["content"]
    assert text["type"] == "text" and text["text"].startswith("capture: ")
    assert image["type"] == "image" and image["mimeType"] == "image/png"
    block = base64.b64decode(image["data"])
    assert body["image"]["built"] is True
    assert body["image"]["sha256"] == hashlib.sha256(block).hexdigest()
    assert body["image"]["source_sha256"] == hashlib.sha256(png.read_bytes()).hexdigest()
    away = session.call("capture", {"mode": "base_color", "path": "..\\outside\\b.png"})
    assert away["error"]["code"] == "path_outside_roots"
    assert revision_of(session) == revision + 1
    # Roots never sandbox run_python, and its own result is not scrubbed.
    script = session.call("run_python", {"code": f"result = {str(outside)!r}"})
    assert script["result"]["result"] == str(outside)
    assert session.close() == 0

    for roots in (f"export={tmp_path / 'missing'}", f"project={projects}", "bogus=C:\\"):
        process = subprocess.run(
            [str(painter), "--mcp", "--roots", roots],
            capture_output=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        assert process.returncode == 2, (roots, process.stderr)
        assert process.stdout == b""
    os.rmdir(projects / "link")


def test_run_python_is_an_opt_in_with_partial_change_receipts(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.5, 2.8: without --allow-python `run_python` is not listed and a call is refused; with it,
    a script that raises after two committed calls returns the last committed revision and its
    partial changes; `path` runs a script file; result, stdout and stderr come separately."""
    closed = Mcp(painter, tmp_path, *BASE)
    sessions.append(closed)
    names = {tool["name"] for tool in closed.request("tools/list", {})["tools"]}
    assert "run_python" not in names and "test_mutation" in names
    assert closed.call("run_python", {"code": "result = 1"})["error"]["code"] == "python_disabled"
    assert closed.close() == 0

    project = make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, *BASE, "--allow-python")
    sessions.append(session)
    revision = session.call("project_open", {"path": str(project), "wait": True})["result"][
        "revision"
    ]
    raising = INSERT + INSERT + "print('out')\nimport sys\nprint('err', file=sys.stderr)\n"
    raising += "raise ValueError('third call')\n"
    failed = session.call("run_python", {"code": raising})
    error = failed["error"]
    assert error["code"] == "script_failed", failed
    assert error["details"]["last_committed_revision"] == revision + 2
    assert [call["revision"] for call in error["details"]["committed"]] == [
        revision + 1,
        revision + 2,
    ]
    assert error["details"]["stdout"] == "out\n" and error["details"]["stderr"] == "err\n"
    assert len(failed["created"]) == 2 and failed["committed_revision"] == revision + 2
    assert revision_of(session) == revision + 2

    script = tmp_path / "script.py"
    script.write_text("import sys\nprint('hello')\nresult = sys.argv[1:]\n", encoding="utf-8")
    ran = session.call("run_python", {"path": str(script), "args": ["a", "b"]})
    assert ran["result"]["result"] == ["a", "b"] and ran["result"]["stdout"] == "hello\n", ran
    both = session.call("run_python", {"code": "1", "path": str(script)})
    assert both["error"]["code"] == "invalid_arguments"
    assert session.close() == 0


class Http:
    """A Streamable HTTP MCP client session on a supervisor's `/mcp`."""

    def __init__(self, url: str, token: str = TOKEN, initialize: bool = True) -> None:
        self.url = url
        self.token = token
        self.ids = 0
        self.session_id: str | None = None
        if not initialize:
            return
        status, headers, _ = self.post(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "uzpainter-tests", "version": "0"},
            },
        )
        assert status == 200
        self.session_id = headers["mcp-session-id"]
        status, _, _ = self.post("notifications/initialized", None, notification=True)
        assert status == 202

    def raw(
        self, body: bytes, headers: dict[str, str], method: str = "POST"
    ) -> tuple[int, dict[str, str], str]:
        request = urllib.request.Request(self.url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return (
                    response.status,
                    {k.lower(): v for k, v in response.headers.items()},
                    response.read().decode("utf-8"),
                )
        except urllib.error.HTTPError as error:
            return error.code, {}, error.read().decode("utf-8")

    def headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if self.session_id is not None:
            headers["mcp-session-id"] = self.session_id
            headers["mcp-protocol-version"] = "2025-11-25"
        return headers

    def post(
        self, method: str, params: dict[str, Any] | None, notification: bool = False
    ) -> tuple[int, dict[str, str], dict[str, Any] | None]:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            self.ids += 1
            message["id"] = self.ids
        status, headers, text = self.raw(json.dumps(message).encode(), self.headers())
        reply = None
        for line in text.splitlines():
            if line.startswith("data:"):
                frame = json.loads(line[5:])
                if frame.get("id") == message.get("id"):
                    reply = frame
        return status, headers, reply

    def tool_names(self) -> set[str]:
        status, _, reply = self.post("tools/list", {})
        assert status == 200 and reply is not None
        return {tool["name"] for tool in reply["result"]["tools"]}

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        status, _, reply = self.post("tools/call", {"name": name, "arguments": arguments or {}})
        assert status == 200 and reply is not None, (status, reply)
        content = reply["result"]["structuredContent"]
        assert isinstance(content, dict)
        return content

    def close(self) -> int:
        """Ends the session (DELETE): the client disconnects."""
        status, _, _ = self.raw(b"", self.headers(), method="DELETE")
        return status


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert isinstance(port, int)
    return port


@pytest.mark.mcp_contract("http_reconnect", transport="http")
def test_http_transport_guards_and_reconnect(painter: Path, tmp_path: Path) -> None:
    """3.2, 2.3, 2.6: a bad Origin, a bad Host and a missing or wrong bearer are refused before
    the MCP layer; a non-loopback bind needs --allow-remote; a mutating call needs the session's
    owner; a client that disconnects during its long job reconnects with its lease and its job's
    state, and nothing is committed twice; Ctrl+Break stops the server and its worker."""
    for args in (["--mcp-http", "0.0.0.0:7777"], ["--mcp-http", "127.0.0.1"], ["--token", "t"]):
        usage = subprocess.run(
            [str(painter), "--mcp", *args],
            capture_output=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        assert usage.returncode == 2, (args, usage.stderr)
    assert (
        b"--allow-remote"
        in subprocess.run(
            [str(painter), "--mcp", "--mcp-http", "0.0.0.0:7777"],
            capture_output=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            check=False,
        ).stderr
    )

    project = make_project(painter, tmp_path)
    port = free_port()
    ledger = tmp_path / "ledger.sqlite3"
    log_path = tmp_path / "http-supervisor.log"
    log = log_path.open("wb")
    process = subprocess.Popen(
        [
            str(painter),
            "--mcp",
            "--mcp-http",
            f"127.0.0.1:{port}",
            "--token",
            TOKEN,
            "--output-root",
            str(tmp_path / "out"),
            "--crash-dir",
            str(tmp_path / "crashes"),
            "--ledger",
            str(ledger),
            *BASE,
        ],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        deadline = time.monotonic() + 120
        while "mcp http listening on" not in log_path.read_text(errors="replace"):
            assert process.poll() is None and time.monotonic() < deadline, log_path.read_text()
            time.sleep(0.05)
        url = f"http://127.0.0.1:{port}/mcp"
        probe = Http(url, initialize=False)
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
        good = probe.headers()
        assert probe.raw(body, {**good, "Origin": "http://evil.example"})[0] == 403
        assert probe.raw(body, {**good, "Host": f"evil.example:{port}"})[0] == 421
        assert probe.raw(body, {**good, "Authorization": "Bearer wrong"})[0] == 401
        assert probe.raw(body, {k: v for k, v in good.items() if k != "Authorization"})[0] == 401
        assert probe.raw(body, {**good, "Origin": f"http://localhost:{port}"})[0] != 403

        first = Http(url)
        assert {"lease_acquire", "lease_release", "lease_status"} <= first.tool_names()
        revision = first.call("project_open", {"path": str(project), "wait": True})["result"][
            "revision"
        ]
        unowned = first.call("test_mutation", {"name": "A"})
        assert unowned["error"]["code"] == "lease_required"
        assert first.call("lease_acquire", {"owner": "agent-a"})["result"]["lease"]["holder"] == (
            "agent-a"
        )
        job = {"name": "J", "steps": 30, "step_ms": 100, "commit_at": 20}
        started = first.call("test_job", job)
        job_id = started["result"]["job_id"]
        assert started["result"]["status"] == "running" and started["job_id"] == job_id
        key = started["receipt"]["idempotency_key"]
        assert first.close() in (200, 204)

        other = Http(url)
        held = other.call("lease_acquire", {"owner": "agent-b"})
        assert held["error"]["code"] == "lease_held"
        assert held["error"]["details"]["holder"] == "agent-a"

        again = Http(url)
        status = again.call("lease_status")["result"]
        assert status["owner"] is None and status["lease"]["holder"] == "agent-a"
        assert again.call("job_status", {"job_id": job_id})["result"]["job_id"] == job_id
        assert again.call("lease_acquire", {"owner": "agent-a"})["result"]["owner"] == "agent-a"
        assert "result" in again.call("wait_idle", {"timeout": 120})
        result = again.call("job_result", {"job_id": job_id})
        assert result["receipt"]["status"] == "succeeded", result
        replay = again.call(
            "test_job", {**job, "idempotency_key": key, "expected_revision": revision, "wait": True}
        )
        assert replay["receipt"]["admission"] == "stored_outcome", replay
        assert again.call("project_inspect")["result"]["revision"] == revision + 1
        committed = again.call("test_mutation", {"name": "B"})
        assert committed["committed_revision"] == revision + 2, committed
        assert again.call("lease_release")["result"] == {"released": "agent-a"}
        assert "result" in other.call("lease_acquire", {"owner": "agent-b"})

        os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        assert process.wait(60) == 0
    finally:
        if process.poll() is None:
            process.kill()
        log.close()
    text = log_path.read_text(errors="replace")
    assert TOKEN not in text  # a given token is never logged
    assert "recovered" not in text  # the stop reached the supervisor, not the worker
    assert ledger_rows(ledger, "SELECT count(*) FROM lease") == [(0,)]
    assert ledger_rows(ledger, "SELECT count(*) FROM log WHERE message LIKE ?", f"%{TOKEN}%") == [
        (0,)
    ]
