"""The supervisor's durable ledger (02-runtime-topology.md §1, §3; 11-mcp-server.md §4).

A SQLite file in the user's local app-data folder (`DEFAULT_PATH`, `--ledger` for another) that
records the control plane: the mutation lease of each project, the jobs (every mutating call the
supervisor admitted, with its key, precondition and terminal state), the revision acknowledged
per project and the outcomes the supervisor has seen. It is never a second editable document:
the project store's `operation` rows are the authority on what committed, and absence from the
ledger never proves that a mutation did not commit. Losing the file loses no project state; the
next reconciliation refills the outcomes from the operation rows. Projects and keys are
identified by the project's UUID, the scope of its idempotency keys.

Several supervisors may share the file: every write is one short transaction, and a lease whose
holder process has ended is taken over.
"""

from __future__ import annotations

import ctypes
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_PATH = (
    Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    / "UzPainter"
    / "supervisor"
    / "ledger.sqlite3"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS lease (
    project_uuid TEXT PRIMARY KEY,
    holder TEXT NOT NULL,
    holder_pid INTEGER NOT NULL,
    since TEXT NOT NULL,
    active_job TEXT
);
CREATE TABLE IF NOT EXISTS job (
    job_id TEXT PRIMARY KEY,
    project_uuid TEXT,
    tool TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    key_source TEXT NOT NULL,
    expected_revision INTEGER,
    state TEXT NOT NULL,
    created TEXT NOT NULL,
    finished TEXT,
    request_hash TEXT,
    committed_revision INTEGER,
    error_code TEXT
);
CREATE TABLE IF NOT EXISTS acknowledgement (
    project_uuid TEXT PRIMARY KEY,
    revision INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS outcome (
    project_uuid TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    committed_revision INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (project_uuid, idempotency_key)
);
"""


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def pid_alive(pid: int) -> bool:
    """Whether process `pid` is running (a lease of an ended process is stale)."""
    synchronize = 0x00100000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return False
    try:
        return int(kernel32.WaitForSingleObject(handle, 0)) != 0
    finally:
        kernel32.CloseHandle(handle)


@dataclass(frozen=True)
class Lease:
    project_uuid: str
    holder: str
    holder_pid: int
    since: str
    active_job: str | None

    def to_json(self) -> dict[str, Any]:
        return {"holder": self.holder, "since": self.since, "active_job": self.active_job}


class Ledger:
    """One connection to the ledger file, created with its folder when absent."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, timeout=30.0, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    # ── Leases ──────────────────────────────────────────────────────────────────────────────

    def lease(self, project_uuid: str) -> Lease | None:
        row = self._db.execute(
            "SELECT holder, holder_pid, since, active_job FROM lease WHERE project_uuid = ?",
            (project_uuid,),
        ).fetchone()
        return Lease(project_uuid, row[0], row[1], row[2], row[3]) if row else None

    def acquire(self, project_uuid: str, holder: str, holder_pid: int) -> Lease:
        """The project's lease: `holder`'s (taken when free or stale), or the live holder's."""
        self._db.execute("BEGIN IMMEDIATE")
        try:
            current = self.lease(project_uuid)
            if current and (current.holder == holder or pid_alive(current.holder_pid)):
                self._db.execute("COMMIT")
                return current
            self._db.execute(
                "INSERT OR REPLACE INTO lease (project_uuid, holder, holder_pid, since, active_job)"
                " VALUES (?, ?, ?, ?, NULL)",
                (project_uuid, holder, holder_pid, now_utc()),
            )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        lease = self.lease(project_uuid)
        assert lease is not None
        return lease

    def set_active_job(self, project_uuid: str, holder: str, job_id: str | None) -> None:
        self._db.execute(
            "UPDATE lease SET active_job = ? WHERE project_uuid = ? AND holder = ?",
            (job_id, project_uuid, holder),
        )

    def release(self, holder: str) -> None:
        """Ends every lease of `holder` (its session closed)."""
        self._db.execute("DELETE FROM lease WHERE holder = ?", (holder,))

    # ── Jobs ────────────────────────────────────────────────────────────────────────────────

    def begin_job(
        self,
        job_id: str,
        project_uuid: str | None,
        tool: str,
        key: str,
        key_source: str,
        expected_revision: int | None,
    ) -> None:
        self._db.execute(
            "INSERT INTO job (job_id, project_uuid, tool, idempotency_key, key_source, "
            "expected_revision, state, created) VALUES (?, ?, ?, ?, ?, ?, 'running', ?)",
            (job_id, project_uuid, tool, key, key_source, expected_revision, now_utc()),
        )

    def finish_job(
        self,
        job_id: str,
        state: str,
        request_hash: str | None,
        committed_revision: int | None,
        error_code: str | None,
    ) -> None:
        self._db.execute(
            "UPDATE job SET state = ?, finished = ?, request_hash = ?, committed_revision = ?, "
            "error_code = ? WHERE job_id = ?",
            (state, now_utc(), request_hash, committed_revision, error_code, job_id),
        )

    def job(self, job_id: str) -> dict[str, Any] | None:
        cursor = self._db.execute("SELECT * FROM job WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(zip([column[0] for column in cursor.description], row, strict=True))

    # ── Acknowledgements and outcomes ───────────────────────────────────────────────────────

    def acknowledged(self, project_uuid: str) -> int | None:
        """The revision up to which every commit of the project is recorded here."""
        row = self._db.execute(
            "SELECT revision FROM acknowledgement WHERE project_uuid = ?", (project_uuid,)
        ).fetchone()
        return int(row[0]) if row else None

    def acknowledge(self, project_uuid: str, revision: int) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO acknowledgement (project_uuid, revision) VALUES (?, ?)",
            (project_uuid, revision),
        )

    def record_outcome(
        self,
        project_uuid: str,
        key: str,
        request_hash: str,
        committed_revision: int,
        outcome: Any,
        source: str,
    ) -> None:
        """A committed mutation's outcome, from its reply or from its operation row."""
        self._db.execute(
            "INSERT OR REPLACE INTO outcome (project_uuid, idempotency_key, request_hash, "
            "committed_revision, outcome, source) VALUES (?, ?, ?, ?, ?, ?)",
            (
                project_uuid,
                key,
                request_hash,
                committed_revision,
                json.dumps(outcome, sort_keys=True),
                source,
            ),
        )

    def outcome(self, project_uuid: str, key: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT request_hash, committed_revision, outcome, source FROM outcome "
            "WHERE project_uuid = ? AND idempotency_key = ?",
            (project_uuid, key),
        ).fetchone()
        if row is None:
            return None
        return {
            "request_hash": row[0],
            "committed_revision": row[1],
            "outcome": json.loads(row[2]),
            "source": row[3],
        }
