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

Jobs (phase2.3, decisions 140, 141): every admitted mutating call and every long call is a `job`
row, written by the supervisor that ran it (`supervisor`, its process id and creation time, so a
reused process id is not mistaken for it). A long job's row follows its progress and its commit
point while it runs, records a cancel request, and keeps its terminal reply (`reply`, with the
receipt) and, for an `interrupted` job, how its outcome was resolved (`resolution`), so terminal
states stay readable after a restart. The file is versioned with `PRAGMA user_version`; a version 0
file (phase2.2) is migrated in place in one transaction.
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

JOB_TABLE = """
CREATE TABLE IF NOT EXISTS job (
    job_id TEXT PRIMARY KEY,
    project_uuid TEXT,
    tool TEXT NOT NULL,
    idempotency_key TEXT,
    key_source TEXT,
    expected_revision INTEGER,
    state TEXT NOT NULL,
    created TEXT NOT NULL,
    finished TEXT,
    request_hash TEXT,
    committed_revision INTEGER,
    error_code TEXT,
    long INTEGER NOT NULL DEFAULT 0,
    supervisor TEXT,
    progress REAL,
    message TEXT,
    committed TEXT,
    cancel_requested TEXT,
    reply TEXT,
    resolution TEXT
);
"""
SCHEMA = (
    """
CREATE TABLE IF NOT EXISTS lease (
    project_uuid TEXT PRIMARY KEY,
    holder TEXT NOT NULL,
    holder_pid INTEGER NOT NULL,
    since TEXT NOT NULL,
    active_job TEXT
);
"""
    + JOB_TABLE
    + """
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
)


VERSION = 1
# The job columns of a version 0 file (phase2.2), copied by the migration.
_V0_JOB_COLUMNS = (
    "job_id, project_uuid, tool, idempotency_key, key_source, expected_revision, state, created, "
    "finished, request_hash, committed_revision, error_code"
)
TERMINAL = ("succeeded", "failed", "cancelled", "interrupted")


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def process_identity(pid: int) -> str | None:
    """`<pid>:<creation time>` of a running process, or None when `pid` is not running: a
    reused process id gets another creation time."""
    query_limited_information = 0x1000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if not handle:
        return None
    try:
        times = [ctypes.c_ulonglong() for _ in range(4)]
        if not kernel32.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            return None
        exit_code = ctypes.c_ulong()
        still_active = 259
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) and (
            exit_code.value != still_active
        ):
            return None
        return f"{pid}:{times[0].value}"
    finally:
        kernel32.CloseHandle(handle)


def identity_alive(identity: str) -> bool:
    """Whether the process `process_identity` named is still the running one."""
    pid = identity.split(":", 1)[0]
    return pid.isdigit() and process_identity(int(pid)) == identity


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
        self._migrate()
        self._db.executescript(SCHEMA)
        self._db.execute(f"PRAGMA user_version = {VERSION}")

    def _migrate(self) -> None:
        """Rebuilds a version 0 `job` table (its key was required) with the job columns."""
        self._db.execute("BEGIN IMMEDIATE")
        try:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            columns = [row[1] for row in self._db.execute("PRAGMA table_info(job)")]
            if version == 0 and columns and "long" not in columns:
                self._db.execute("ALTER TABLE job RENAME TO job_v0")
                self._db.execute(JOB_TABLE)
                self._db.execute(
                    f"INSERT INTO job ({_V0_JOB_COLUMNS}) SELECT {_V0_JOB_COLUMNS} FROM job_v0"
                )
                self._db.execute("DROP TABLE job_v0")
                self._db.execute(f"PRAGMA user_version = {VERSION}")
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

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
        key: str | None,
        key_source: str | None,
        expected_revision: int | None,
        long: bool = False,
        supervisor: str | None = None,
    ) -> None:
        """A running job; `key` and `key_source` are None for a long job that mutates nothing."""
        self._db.execute(
            "INSERT INTO job (job_id, project_uuid, tool, idempotency_key, key_source, "
            "expected_revision, state, created, long, supervisor, progress) "
            "VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)",
            (
                job_id,
                project_uuid,
                tool,
                key,
                key_source,
                expected_revision,
                now_utc(),
                int(long),
                supervisor,
                0.0 if long else None,
            ),
        )

    def progress_job(
        self, job_id: str, progress: float, message: str, committed: dict[str, Any] | None
    ) -> None:
        """A running long job's progress, message and commit point."""
        self._db.execute(
            "UPDATE job SET progress = ?, message = ?, committed = ? WHERE job_id = ?",
            (progress, message, None if committed is None else json.dumps(committed), job_id),
        )

    def request_cancel(self, job_id: str) -> None:
        """Records the first cancel request of a job."""
        self._db.execute(
            "UPDATE job SET cancel_requested = ? WHERE job_id = ? AND cancel_requested IS NULL",
            (now_utc(), job_id),
        )

    def finish_job(
        self,
        job_id: str,
        state: str,
        request_hash: str | None,
        committed_revision: int | None,
        error_code: str | None,
        reply: dict[str, Any] | None = None,
        resolution: dict[str, Any] | None = None,
    ) -> None:
        """The job's terminal state; `reply` is the body it answered (with its receipt)."""
        self._db.execute(
            "UPDATE job SET state = ?, finished = ?, request_hash = ?, committed_revision = ?, "
            "error_code = ?, reply = ?, resolution = ? WHERE job_id = ?",
            (
                state,
                now_utc(),
                request_hash,
                committed_revision,
                error_code,
                None if reply is None else json.dumps(reply, sort_keys=True),
                None if resolution is None else json.dumps(resolution, sort_keys=True),
                job_id,
            ),
        )

    def resolve_job(self, job_id: str, resolution: dict[str, Any]) -> None:
        self._db.execute(
            "UPDATE job SET resolution = ? WHERE job_id = ?",
            (json.dumps(resolution, sort_keys=True), job_id),
        )

    def job(self, job_id: str) -> dict[str, Any] | None:
        """The job's row; `committed`, `reply` and `resolution` decoded."""
        cursor = self._db.execute("SELECT * FROM job WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return self._decoded(cursor, row)

    def jobs(self, limit: int) -> list[dict[str, Any]]:
        """The newest `limit` jobs, newest first."""
        cursor = self._db.execute(
            "SELECT * FROM job ORDER BY created DESC, rowid DESC LIMIT ?", (limit,)
        )
        return [self._decoded(cursor, row) for row in cursor.fetchall()]

    def orphaned_jobs(self, supervisor: str) -> list[dict[str, Any]]:
        """Running jobs of other supervisors."""
        cursor = self._db.execute(
            "SELECT * FROM job WHERE state = 'running' AND (supervisor IS NULL OR supervisor != ?)",
            (supervisor,),
        )
        return [self._decoded(cursor, row) for row in cursor.fetchall()]

    def unresolved_jobs(self, project_uuid: str) -> list[dict[str, Any]]:
        """Interrupted jobs of the project with a key and an unknown outcome."""
        cursor = self._db.execute(
            "SELECT * FROM job WHERE project_uuid = ? AND state = 'interrupted' "
            "AND idempotency_key IS NOT NULL AND json_extract(resolution, '$.committed') IS NULL",
            (project_uuid,),
        )
        return [self._decoded(cursor, row) for row in cursor.fetchall()]

    @staticmethod
    def _decoded(cursor: sqlite3.Cursor, row: Any) -> dict[str, Any]:
        job = dict(zip([column[0] for column in cursor.description], row, strict=True))
        for field in ("committed", "reply", "resolution"):
            if job[field] is not None:
                job[field] = json.loads(job[field])
        job["long"] = bool(job["long"])
        return job

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
