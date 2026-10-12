"""Admission, idempotency and the ledger through `UzPainter.exe --mcp`
(python/uzpainter_supervisor/admission.py, src/supervisor/worker.cpp; task
phase2.2_supervisor-admission-ledger items 2.1, 2.2, 2.6-2.8, 3.1, 3.2, 3.5; decisions 138, 139).

CPU only: the supervisors run `--gpu-backend vulkan` with `--test-faults` (Debug build), so the
typed `test_mutation` exists. Each supervisor writes its own ledger under the test's folder.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from tests.supervisor.conftest import Mcp, make_project

BASE = ("--gpu-backend", "vulkan", "--allow-python", "--test-faults")


def opened(
    painter: Path, tmp_path: Path, sessions: list[Mcp], project: Path | None = None, **kwargs: Any
) -> tuple[Mcp, Path, int]:
    project = project or make_project(painter, tmp_path)
    session = Mcp(painter, tmp_path, *BASE, **kwargs)
    sessions.append(session)
    revision = session.call("project_open", {"path": str(project)})["result"]["revision"]
    assert isinstance(revision, int)
    return session, project, revision


def mutate(session: Mcp, name: str, key: str | None, expected: int | None) -> dict[str, Any]:
    arguments: dict[str, Any] = {"name": name}
    if key is not None:
        arguments["idempotency_key"] = key
    if expected is not None:
        arguments["expected_revision"] = expected
    return session.call("test_mutation", arguments)


def revision_of(session: Mcp) -> int:
    revision = session.call("project_inspect")["result"]["revision"]
    assert isinstance(revision, int)
    return revision


def ledger_rows(ledger: Path, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    db = sqlite3.connect(ledger)
    try:
        return list(db.execute(sql, params))
    finally:
        db.close()


def test_lost_acknowledgement_returns_the_stored_outcome(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.1, 2.6: the worker dies after the durable commit and before its reply; the supervisor
    reconciles the operation rows before the next call; the retry returns the stored outcome
    with no second revision, and a changed request with the same key is
    `idempotency_conflict`."""
    session, _, revision = opened(painter, tmp_path, sessions)
    assert "result" in session.call("test_fault", {"fault": "kill_before_reply"})
    lost = mutate(session, "A", "k-1", revision)
    assert lost["error"]["code"] == "interrupted"
    assert lost["error"]["details"]["committed_revision"] == revision + 1
    assert lost["receipt"]["idempotency_key"] == "k-1"
    assert lost["receipt"]["expected_revision"] == revision

    retry = mutate(session, "A", "k-1", revision)
    assert retry["receipt"]["admission"] == "stored_outcome"
    assert retry["result"]["committed_revision"] == revision + 1
    assert retry["committed_revision"] == revision + 1
    assert revision_of(session) == revision + 1
    conflict = mutate(session, "B", "k-1", revision)
    assert conflict["error"]["code"] == "idempotency_conflict"
    assert conflict["error"]["details"] == {"key": "k-1", "committed_revision": revision + 1}
    assert revision_of(session) == revision + 1

    uuid = session.status()["project_uuid"]
    assert ledger_rows(
        session.ledger,
        "SELECT committed_revision, source FROM outcome WHERE project_uuid = ? "
        "AND idempotency_key = 'k-1'",
        uuid,
    ) == [(revision + 1, "operation_row")]
    assert sorted(
        ledger_rows(session.ledger, "SELECT state FROM job WHERE idempotency_key = 'k-1'")
    ) == [("failed",), ("interrupted",), ("succeeded",)]
    assert session.status()["acknowledged_revision"] == revision + 1


def test_a_replay_beyond_retention_with_a_lost_ledger_never_mutates(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.2, 3.3: a known key replayed inside the window after the revision advanced returns the
    stored result; once the project advanced past the Q11 window and was compacted and the
    supervisor ledger is deleted, replaying the original key with its original precondition and
    with none creates no mutation."""
    session, project, revision = opened(painter, tmp_path, sessions)
    first = mutate(session, "A", "k-1", revision)
    assert first["committed_revision"] == revision + 1
    advance = (
        "from uzpainter import layerstack as ls, textureset as ts\n"
        "for _ in range(55):\n"
        "    ls.insert_fill(ls.InsertPosition.from_textureset_stack(ts.get_active_stack()))\n"
    )
    advanced = session.call(
        "run_python",
        {"code": advance, "idempotency_key": "k-adv", "expected_revision": revision + 1},
    )
    current = advanced["committed_revision"]
    assert current == revision + 56, advanced
    inside = mutate(session, "A", "k-1", revision)
    assert inside["receipt"]["admission"] == "stored_outcome"
    assert inside["result"] == first["result"]
    assert "result" in session.call("project_save", {"mode": "full"})
    session.call("project_close")
    ledger = session.ledger
    assert session.close() == 0

    with sqlite3.connect(project) as db:
        horizon = int(
            db.execute(
                "SELECT value FROM meta WHERE key = 'operation_horizon_revision'"
            ).fetchone()[0]
        )
        pruned = db.execute(
            "SELECT count(*) FROM operation WHERE idempotency_key = 'k-1'"
        ).fetchone()[0]
    db.close()
    assert horizon > revision + 1 and pruned == 0
    ledger.unlink()
    for suffix in ("-wal", "-shm"):
        Path(f"{ledger}{suffix}").unlink(missing_ok=True)

    fresh, _, reopened = opened(painter, tmp_path, sessions, project=project, ledger=ledger)
    assert reopened == current
    for expected in (revision, None):
        replay = mutate(fresh, "A", "k-1", expected)
        assert replay["error"]["code"] == "outcome_unknown", replay
        assert replay["error"]["details"]["committed_revision"] == current
    assert revision_of(fresh) == current


def test_busy_lease_and_wait_idle_through_mcp(
    painter: Path, tmp_path: Path, sessions: list[Mcp]
) -> None:
    """3.5, 2.1, 2.7: while a mutating call runs, another mutating call returns `busy {job_id}`
    instead of queueing; `wait_idle` times out with an error, then succeeds; the stdio session
    holds the project's lease (a second owner is refused in test_admission.py)."""
    session, _, revision = opened(painter, tmp_path, sessions)
    slow = (
        "import time\n"
        "from uzpainter import layerstack as ls, textureset as ts\n"
        "time.sleep(4)\n"
        "ls.insert_fill(ls.InsertPosition.from_textureset_stack(ts.get_active_stack()))\n"
    )
    running = session.send(
        "tools/call",
        {
            "name": "run_python",
            "arguments": {"code": slow, "idempotency_key": "k-slow", "expected_revision": revision},
        },
    )
    status = session.status()
    while not status["running"]:
        status = session.status()
    job_id = status["running"][status["project_uuid"]]
    assert status["lease"]["holder"] == f"stdio:{session.process.pid}"
    assert status["lease"]["active_job"] == job_id
    busy = mutate(session, "B", "k-b", revision)
    assert busy["error"] == {
        "code": "busy",
        "message": "another mutating call of this project is running; the call is not queued",
        "details": {"job_id": job_id},
    }
    assert session.call("wait_idle", {"timeout": 0.2})["error"]["code"] == "timeout"
    assert session.call("wait_idle", {"timeout": 120})["result"]["idle"] is True
    done = Mcp.content(session.reply(running))
    assert done["committed_revision"] == revision + 1
    assert done["receipt"]["job_id"] == job_id
    assert done["receipt"]["project_uuid"] == status["project_uuid"]
    assert session.status()["lease"]["active_job"] is None
    assert revision_of(session) == revision + 1
