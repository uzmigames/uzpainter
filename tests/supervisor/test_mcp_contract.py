"""The Phase 2 MCP contract fixtures of `docs/architecture/11-mcp-server.md` §7 (task
phase2.8_mcp-server items 2.1-2.3, 3.1-3.6; decision 186).

The children's tests that already run a fixture on a transport carry
`@pytest.mark.mcp_contract(<fixture>, transport=...)` where they are
(test_supervisor_admission.py, test_supervisor_transports.py); this file runs the fixtures and
transports they do not cover, through MCP clients on stdio (`Mcp`) and on Streamable HTTP
(`Http`). `UZP_MCP_CONTRACT_REPORT=<path>` merges the results into
`parity/reports/phase2/mcp-contract.json` (tools/parity/settling/mcp_contract.py).

Synthetic fixtures only (2.1), no oracle data: the project is UzmiGames' plane
(parity/fixtures/meshes/plane.obj), created and saved once through typed MCP tools; each test opens
a copy. The long job is the Debug build's `test_job` under `--test-faults` (a fill layer committed
with its operation row at a chosen step). Every supervisor runs with Python disabled on a Vulkan
worker, so no device is created.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.supervisor.conftest import PLANE, Mcp, wait_until_gone
from tests.supervisor.test_supervisor_transports import TOKEN, Http, free_port
from tests.supervisor.test_typed_tools import GAP_CALLS

BASE = ("--gpu-backend", "vulkan", "--test-faults")
# 2.1: the long-job fixture; its fill layer commits at step 1 of 30 (about 3 s in all).
LONG_JOB = {"name": "Job", "steps": 30, "step_ms": 100, "commit_at": 1}
# 3.6 (spec scenario): native bake, the procedural families, later node kinds and painter_iray.
LATER_FAMILIES = (
    "bake.start",
    "stack.procedural",
    "effect.insert_paint",
    "layer.instantiate",
    "effect.insert_anchor",
    "anchor.list",
    "capture.painter_iray",
)

_numbers = itertools.count(1)


def contract(fixture: str, *transports: str) -> pytest.MarkDecorator:
    """Runs the test once per transport, tagged as `fixture` on it."""
    return pytest.mark.parametrize(
        "transport",
        [
            pytest.param(t, marks=pytest.mark.mcp_contract(fixture, transport=t), id=t)
            for t in transports
        ],
    )


Client = Mcp | Http


class Supervisor:
    """`UzPainter.exe --mcp` on `transport`: one stdio session, or a resident HTTP server whose
    clients each bind a lease owner. Every client answers `call(name, arguments)` with the
    structured content of the tool's result."""

    def __init__(
        self,
        painter: Path,
        tmp_path: Path,
        transport: str,
        *args: str,
        ledger: Path | None = None,
    ) -> None:
        self.transport = transport
        self.ledger = ledger or tmp_path / f"contract-ledger-{next(_numbers)}.sqlite3"
        self.session: Mcp | None = None
        self.process: subprocess.Popen[bytes]
        if transport == "stdio":
            self.session = Mcp(painter, tmp_path, *BASE, *args, ledger=self.ledger)
            self.process = self.session.process
            return
        port = free_port()
        self.log_path = tmp_path / f"contract-http-{next(_numbers)}.log"
        self._log = self.log_path.open("wb")
        self.process = subprocess.Popen(
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
                str(self.ledger),
                *BASE,
                *args,
            ],
            stdin=subprocess.DEVNULL,
            stdout=self._log,
            stderr=self._log,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        deadline = time.monotonic() + 120
        while "mcp http listening on" not in self.log_path.read_text(errors="replace"):
            assert self.process.poll() is None and time.monotonic() < deadline, self.log()
            time.sleep(0.05)
        self.port = port
        self.url = f"http://127.0.0.1:{port}/mcp"

    def log(self) -> str:
        if self.session is not None:
            return self.session.log()
        self._log.flush()
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def client(self, owner: str = "agent-a") -> Client:
        """The stdio session (its owner is implicit), or a new HTTP session bound to `owner`."""
        if self.session is not None:
            return self.session
        client = Http(self.url)
        acquired = client.call("lease_acquire", {"owner": owner})
        assert acquired["result"]["owner"] == owner, acquired
        return client

    def close(self) -> int:
        if self.session is not None:
            return self.session.close()
        if self.process.poll() is None:
            os.kill(self.process.pid, signal.CTRL_BREAK_EVENT)
        try:
            return self.process.wait(60)
        finally:
            if self.process.poll() is None:
                self.process.kill()
            self._log.close()


@pytest.fixture
def supervisors() -> Iterator[list[Supervisor]]:
    started: list[Supervisor] = []
    yield started
    for supervisor in started:
        supervisor.close()


@pytest.fixture(scope="module")
def contract_project(painter: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """2.1: the synthetic project, the plane at 256 px created and saved through typed MCP tools
    with Python disabled."""
    folder = tmp_path_factory.mktemp("contract-project")
    path = folder / "plane.uzp"
    session = Mcp(painter, folder, *BASE)
    try:
        created = session.call(
            "project_create",
            {"mesh": str(PLANE), "settings": {"default_texture_resolution": 256}, "wait": True},
        )
        assert created["result"]["status"] == "committed", created
        saved = session.call("project_save_as", {"path": str(path), "wait": True})
        assert "error" not in saved, saved
    finally:
        session.close()
    return path


def project_copy(contract_project: Path, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    return Path(shutil.copy(contract_project, folder / f"plane-{next(_numbers)}.uzp"))


def opened(
    painter: Path,
    tmp_path: Path,
    supervisors: list[Supervisor],
    transport: str,
    project: Path,
    *args: str,
    ledger: Path | None = None,
) -> tuple[Supervisor, Client, int]:
    """A supervisor on `transport` with `project` open; its first client and the revision."""
    supervisor = Supervisor(painter, tmp_path, transport, *args, ledger=ledger)
    supervisors.append(supervisor)
    client = supervisor.client()
    reply = client.call("project_open", {"path": str(project), "wait": True})
    revision = reply["result"]["revision"]
    assert isinstance(revision, int), reply
    return supervisor, client, revision


def insert(client: Client, name: str, key: str | None, expected: int | None) -> dict[str, Any]:
    """A typed fill-layer insert, with its idempotency key and precondition when given."""
    arguments: dict[str, Any] = {"kind": "fill", "name": name}
    if key is not None:
        arguments["idempotency_key"] = key
    if expected is not None:
        arguments["expected_revision"] = expected
    return client.call("layer_insert", arguments)


def revision_of(client: Client) -> int:
    revision = client.call("project_inspect")["result"]["revision"]
    assert isinstance(revision, int)
    return revision


def operation_rows(project: Path, key: str) -> int:
    db = sqlite3.connect(project)
    try:
        count = db.execute(
            "SELECT count(*) FROM operation WHERE idempotency_key = ?", (key,)
        ).fetchone()[0]
    finally:
        db.close()
    assert isinstance(count, int)
    return count


def committed_job(client: Client, job_id: str, timeout: float = 120.0) -> dict[str, Any]:
    """The job's status once its commit is reported."""
    deadline = time.monotonic() + timeout
    while True:
        status = client.call("job_status", {"job_id": job_id})["result"]
        if status["committed"] is not None:
            assert isinstance(status, dict)
            return status
        assert time.monotonic() < deadline, status
        time.sleep(0.05)


def resource(client: Client, uri: str) -> Any:
    """The JSON document of resource `uri`."""
    if isinstance(client, Mcp):
        [content] = client.request("resources/read", {"uri": uri})["contents"]
    else:
        status, _, reply = client.post("resources/read", {"uri": uri})
        assert status == 200 and reply is not None, (status, reply)
        [content] = reply["result"]["contents"]
    return json.loads(content["text"])


# ── 3.1 two writers ─────────────────────────────────────────────────────────────────────────────


@contract("two_writers", "http")
def test_a_second_writer_receives_lease_held(
    painter: Path,
    tmp_path: Path,
    supervisors: list[Supervisor],
    contract_project: Path,
    transport: str,
) -> None:
    """3.1: two owners on one resident server; the first writer's mutation takes the project's
    lease, and the second's mutating call is refused `lease_held {holder, since, active_job}`
    with nothing committed, also while the holder's long job runs; reads need no lease. Once the
    holder releases, the second commits."""
    project = project_copy(contract_project, tmp_path / "projects")
    supervisor = Supervisor(painter, tmp_path, transport)
    supervisors.append(supervisor)
    first, second = supervisor.client("agent-a"), supervisor.client("agent-b")
    revision = first.call("project_open", {"path": str(project), "wait": True})["result"][
        "revision"
    ]
    assert insert(first, "A", None, None)["committed_revision"] == revision + 1

    held = insert(second, "B", None, None)
    assert held["error"]["code"] == "lease_held", held
    assert held["error"]["details"]["holder"] == "agent-a"
    assert held["error"]["details"]["active_job"] is None
    assert isinstance(held["error"]["details"]["since"], str)
    # A read needs no lease: "A" and Painter's default "Layer 1" (decision 348).
    assert len(second.call("layer_list")["result"]["nodes"]) == 2

    job_id = first.call("test_job", LONG_JOB)["result"]["job_id"]
    during = insert(second, "B", None, None)
    assert during["error"]["code"] == "lease_held", during
    assert during["error"]["details"]["active_job"] == job_id
    assert second.call("lease_acquire", {"owner": "agent-b"})["error"]["code"] == "lease_held"
    assert "result" in first.call("wait_idle", {"timeout": 120})
    assert revision_of(second) == revision + 2  # the holder's two commits, none of the second's

    assert first.call("lease_release")["result"] == {"released": "agent-a"}
    assert insert(second, "B", None, None)["committed_revision"] == revision + 3
    assert revision_of(first) == revision + 3


@contract("two_writers", "http")
def test_a_lease_taken_before_project_create_holds_the_created_project(
    painter: Path,
    tmp_path: Path,
    supervisors: list[Supervisor],
    contract_project: Path,
    transport: str,
) -> None:
    """Practical-e2e B8, decision 243: two owners take the lease with no project open; the
    project the first one creates is its own from the switch, so the second owner's mutation and a
    third client's `lease_acquire` are refused `lease_held` and the creator commits. The project
    the second owner then opens is the second owner's."""
    project = project_copy(contract_project, tmp_path / "projects")
    supervisor = Supervisor(painter, tmp_path, transport)
    supervisors.append(supervisor)
    first, second = supervisor.client("client-a"), supervisor.client("client-b")
    created = first.call(
        "project_create",
        {"mesh": str(PLANE), "settings": {"default_texture_resolution": 256}, "wait": True},
    )
    assert created["result"]["status"] == "committed", created
    revision = revision_of(first)

    held = insert(second, "B", None, None)
    assert held["error"]["code"] == "lease_held", held
    assert held["error"]["details"]["holder"] == "client-a"
    third = Http(supervisor.url)
    assert third.call("lease_status")["result"]["lease"]["holder"] == "client-a"
    refused = third.call("lease_acquire", {"owner": "client-c"})
    assert refused["error"]["code"] == "lease_held", refused
    assert insert(first, "A", None, None)["committed_revision"] == revision + 1

    assert "error" not in first.call("project_close", {"discard": True})
    opened = second.call("project_open", {"path": str(project), "wait": True})
    assert isinstance(opened["result"]["revision"], int), opened
    held = insert(first, "A", None, None)
    assert held["error"]["code"] == "lease_held", held
    assert held["error"]["details"]["holder"] == "client-b"
    assert insert(second, "B", None, None)["committed_revision"] == opened["result"]["revision"] + 1


# ── 3.2 lost acknowledgement, commit-then-die ───────────────────────────────────────────────────


def lose_stdio_reply(supervisor: Supervisor, job: dict[str, Any]) -> int:
    """Sends `job` waiting for its reply and ends the session once the job committed, before the
    reply is read; the worker's pid."""
    session = supervisor.session
    assert session is not None
    session.send("tools/call", {"name": "test_job", "arguments": job})
    status = session.status()
    while not status["running"]:
        status = session.status()
    committed_job(session, status["running"][status["project_uuid"]])
    assert session.process.stdin is not None
    session.process.stdin.close()
    assert session.process.wait(120) == 0, session.log()
    worker = status["worker_pid"]
    assert isinstance(worker, int)
    return worker


def lose_http_reply(supervisor: Supervisor, client: Http, job: dict[str, Any]) -> None:
    """Posts `job` waiting for its reply on a socket of its own and drops the connection once the
    job committed, before the reply is read."""
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "test_job", "arguments": job},
    }
    body = json.dumps(message).encode()
    headers = {**client.headers(), "Host": f"127.0.0.1:{supervisor.port}"}
    head = "".join(f"{name}: {value}\r\n" for name, value in headers.items())
    with socket.create_connection(("127.0.0.1", supervisor.port), timeout=120) as connection:
        connection.sendall(
            f"POST /mcp HTTP/1.1\r\n{head}Content-Length: {len(body)}\r\n\r\n".encode() + body
        )
        status = client.call("supervisor_status")["result"]
        while not status["running"]:
            status = client.call("supervisor_status")["result"]
        committed_job(client, status["running"][status["project_uuid"]])


@contract("lost_acknowledgement_retry", "stdio", "http")
def test_a_lost_acknowledgement_is_retried_to_the_stored_outcome(
    painter: Path,
    tmp_path: Path,
    supervisors: list[Supervisor],
    contract_project: Path,
    transport: str,
) -> None:
    """3.2: the client loses the reply of a long mutation that committed (stdio: the session ends;
    HTTP: the connection drops) and retries with the same key and precondition: the stored
    outcome, no second revision and one operation row; a changed request with the same key is
    `idempotency_conflict`."""
    project = project_copy(contract_project, tmp_path / "projects")
    supervisor, client, revision = opened(painter, tmp_path, supervisors, transport, project)
    job = {**LONG_JOB, "wait": True, "idempotency_key": "k-lost", "expected_revision": revision}
    if isinstance(client, Mcp):
        assert wait_until_gone(lose_stdio_reply(supervisor, job))
        supervisor, client, reopened = opened(
            painter, tmp_path, supervisors, transport, project, ledger=supervisor.ledger
        )
        assert reopened == revision + 1
    else:
        lose_http_reply(supervisor, client, job)
        client = supervisor.client()  # the owner reconnects
        assert "result" in client.call("wait_idle", {"timeout": 120})
    retry = client.call("test_job", job)
    assert retry["receipt"]["admission"] == "stored_outcome", retry
    assert retry["committed_revision"] == revision + 1
    changed = client.call("test_job", {**job, "name": "Other"})
    assert changed["error"]["code"] == "idempotency_conflict", changed
    assert revision_of(client) == revision + 1
    assert operation_rows(project, "k-lost") == 1


@contract("commit_then_die_retry", "http")
def test_commit_then_die_over_http(
    painter: Path,
    tmp_path: Path,
    supervisors: list[Supervisor],
    contract_project: Path,
    transport: str,
) -> None:
    """3.2 (the stdio run is test_supervisor_admission.py's): the worker dies after the durable
    commit of a typed insert and before its reply; the call is `interrupted` with the committed
    revision; the same request returns the stored outcome with no second revision, and a changed
    request with the same key is `idempotency_conflict`."""
    project = project_copy(contract_project, tmp_path / "projects")
    _, client, revision = opened(painter, tmp_path, supervisors, transport, project)
    assert "result" in client.call("test_fault", {"fault": "kill_before_reply"})
    lost = insert(client, "A", "k-1", revision)
    assert lost["error"]["code"] == "interrupted", lost
    assert lost["error"]["details"]["committed_revision"] == revision + 1
    retry = insert(client, "A", "k-1", revision)
    assert retry["receipt"]["admission"] == "stored_outcome", retry
    assert retry["committed_revision"] == revision + 1
    conflict = insert(client, "B", "k-1", revision)
    assert conflict["error"]["code"] == "idempotency_conflict", conflict
    assert conflict["error"]["details"] == {"key": "k-1", "committed_revision": revision + 1}
    assert revision_of(client) == revision + 1
    assert operation_rows(project, "k-1") == 1


# ── 3.4 roots, stale revision ───────────────────────────────────────────────────────────────────


@contract("path_outside_roots", "http")
def test_a_path_outside_the_roots_over_http(
    painter: Path,
    tmp_path: Path,
    supervisors: list[Supervisor],
    contract_project: Path,
    transport: str,
) -> None:
    """3.4 (the stdio run is test_supervisor_transports.py's): with --roots, a project path
    outside the project root, absolute, relative or `file:///`, is refused before admission (no
    job) and an output path escaping the export root is refused; the path inside opens."""
    projects, outside = tmp_path / "projects", tmp_path / "outside"
    inside = project_copy(contract_project, projects)
    away = project_copy(contract_project, outside)
    (tmp_path / "out").mkdir()
    supervisor = Supervisor(
        painter,
        tmp_path,
        transport,
        "--roots",
        f"project={projects};export={tmp_path / 'out'}",
    )
    supervisors.append(supervisor)
    client = supervisor.client()
    for path in (str(away), f"..\\outside\\{away.name}", away.as_uri()):
        refused = client.call("project_open", {"path": path, "wait": True})
        assert refused["error"]["code"] == "path_outside_roots", (path, refused)
        assert refused["error"]["details"]["root"] == "project"
        assert refused["receipt"]["job_id"] is None
    revision = client.call("project_open", {"path": str(inside), "wait": True})["result"][
        "revision"
    ]
    escape = client.call("capture", {"mode": "base_color", "path": "..\\outside\\b.png"})
    assert escape["error"]["code"] == "path_outside_roots", escape
    assert escape["error"]["details"]["root"] == "export"
    assert not (outside / "b.png").exists()
    assert revision_of(client) == revision


@contract("stale_revision", "stdio", "http")
def test_a_stale_revision_is_refused_with_both_revisions(
    painter: Path,
    tmp_path: Path,
    supervisors: list[Supervisor],
    contract_project: Path,
    transport: str,
) -> None:
    """3.4: a new key whose precondition is older than the current revision is refused
    `stale_revision {expected, current}` and commits nothing."""
    project = project_copy(contract_project, tmp_path / "projects")
    _, client, revision = opened(painter, tmp_path, supervisors, transport, project)
    assert insert(client, "A", "k-1", revision)["committed_revision"] == revision + 1
    stale = insert(client, "B", "k-2", revision)
    assert stale["error"]["code"] == "stale_revision", stale
    assert stale["error"]["details"] == {"expected": revision, "current": revision + 1}
    assert revision_of(client) == revision + 1
    assert operation_rows(project, "k-2") == 0


# ── 3.5 replay inside the window and beyond retention ───────────────────────────────────────────


@contract("replay_inside_window", "http")
@pytest.mark.mcp_contract("replay_beyond_retention_lost_ledger", transport="http")
def test_replays_inside_and_beyond_the_window_over_http(
    painter: Path,
    tmp_path: Path,
    supervisors: list[Supervisor],
    contract_project: Path,
    transport: str,
) -> None:
    """3.5 (the stdio run is test_supervisor_admission.py's): a known key replayed inside the
    window after the revision advanced returns the stored result; after 55 more typed commits, a
    full save's compaction and the supervisor ledger deleted, the original key replayed with its
    original precondition is `outcome_unknown` and without one is refused before admission:
    neither creates a mutation."""
    project = project_copy(contract_project, tmp_path / "projects")
    supervisor, client, revision = opened(painter, tmp_path, supervisors, transport, project)
    first = insert(client, "A", "k-1", revision)
    assert first["committed_revision"] == revision + 1
    for index in range(55):
        assert "result" in insert(client, f"F{index}", None, None)
    current = revision_of(client)
    assert current == revision + 56
    inside = insert(client, "A", "k-1", revision)
    assert inside["receipt"]["admission"] == "stored_outcome", inside
    assert inside["result"] == first["result"]
    assert "result" in client.call("project_save", {"mode": "full"})
    assert "result" in client.call("project_close")
    ledger = supervisor.ledger
    supervisors.remove(supervisor)
    assert supervisor.close() == 0

    db = sqlite3.connect(project)
    try:
        horizon = int(
            db.execute(
                "SELECT value FROM meta WHERE key = 'operation_horizon_revision'"
            ).fetchone()[0]
        )
    finally:
        db.close()
    assert horizon > revision + 1 and operation_rows(project, "k-1") == 0
    for suffix in ("", "-wal", "-shm"):
        Path(f"{ledger}{suffix}").unlink(missing_ok=True)

    _, fresh, reopened = opened(painter, tmp_path, supervisors, transport, project, ledger=ledger)
    assert reopened == current
    replay = insert(fresh, "A", "k-1", revision)
    assert replay["error"]["code"] == "outcome_unknown", replay
    assert replay["error"]["details"]["committed_revision"] == current
    bare = insert(fresh, "A", "k-1", None)
    assert bare["error"]["code"] == "invalid_arguments", bare
    assert bare["receipt"]["job_id"] is None
    assert revision_of(fresh) == current


# ── 3.6 capability gaps ─────────────────────────────────────────────────────────────────────────


@contract("capability_gaps", "stdio", "http")
def test_unavailable_families_and_python_needs_are_gaps(
    painter: Path,
    tmp_path: Path,
    supervisors: list[Supervisor],
    contract_project: Path,
    transport: str,
) -> None:
    """3.6, spec scenario: in `uzpainter://capabilities` every unavailable family is a release-gap
    tool, native bake, the procedural families, later node kinds and painter_iray are
    `capability gap` rows of the operation matrix, and every row that still needs Python is
    `needs Python`, a gap, never `available`. Each unavailable family is refused
    `capability_gap` before admission and nothing is committed."""
    project = project_copy(contract_project, tmp_path / "projects")
    _, client, revision = opened(painter, tmp_path, supervisors, transport, project)
    document = resource(client, "uzpainter://capabilities")
    gaps = {row["tool"] for row in document["tools"] if row["status"] == "release-gap"}
    assert gaps == set(GAP_CALLS)
    rows = {row["operation"]: row for row in document["operation_matrix"]}
    for operation in LATER_FAMILIES:
        assert rows[operation]["status"] == "capability gap", rows[operation]
    python_rows = {name for name, row in rows.items() if row["tool"] == "run_python"}
    assert {name for name, row in rows.items() if row["status"] == "needs Python"} == python_rows
    assert {row["status"] for row in rows.values()} <= {
        "available",
        "capability gap",
        "needs Python",
    }

    for name, arguments in GAP_CALLS.items():
        reply = client.call(name, arguments)
        assert reply["error"]["code"] == "capability_gap", (name, reply)
        assert reply["receipt"]["job_id"] is None, name
    painted = client.call("effect_insert", {"uid": 1, "stack": "content", "kind": "paint"})
    assert painted["error"]["code"] == "capability_gap", painted
    assert set(client.call("capabilities")["result"]["gaps"]) == set(GAP_CALLS)
    assert revision_of(client) == revision
