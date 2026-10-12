"""The supervisor's admission and ledger (python/uzpainter_supervisor/admission.py, ledger.py;
task phase2.2_supervisor-admission-ledger items 2.1, 2.2, 2.6-2.8, 3.5, 3.6; decisions 138, 139).

Pure Python: the worker is a stand-in that records the frames it is sent, so neither the worker
binary nor a GPU is needed. The worker's own decisions over the operation rows, and the whole path
through `UzPainter.exe --mcp`, are covered in test_worker_pipe.py and test_supervisor_mcp.py.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

from python.uzpainter_supervisor.admission import Admission
from python.uzpainter_supervisor.ledger import Ledger

UUID = "6f1c2a6e-0000-4000-8000-000000000001"


class FakeWorker:
    """Holds project `UUID` at revision 5; a mutating call commits the next revision."""

    def __init__(self) -> None:
        self.project_path: str | None = "C:/p/plane.uzp"
        self.project_uuid: str | None = UUID
        self.durable_revision: int | None = 5
        self.project_epoch = 1
        self.frames: list[dict[str, Any]] = []
        self.gate: asyncio.Event | None = None
        self.operations: dict[str, Any] = {
            "result": {
                "project_uuid": UUID,
                "current_revision": 5,
                "horizon_revision": 0,
                "operations": [],
                "unreadable": [],
            }
        }

    async def wait_ready(self) -> None:
        return None

    async def request(self, frame: dict[str, Any]) -> dict[str, Any]:
        self.frames.append(frame)
        if frame["method"] == "worker/operations":
            return self.operations
        if self.gate is not None and "idempotency_key" in frame:
            await self.gate.wait()
        if "idempotency_key" not in frame:
            return {
                "id": "x",
                "result": {"open": True},
                "committed_revision": self.durable_revision,
            }
        assert self.durable_revision is not None
        self.durable_revision += 1
        return {
            "id": "x",
            "result": {"status": "committed", "committed_revision": self.durable_revision},
            "committed_revision": self.durable_revision,
            "admission": "executed",
            "request_hash": "h-" + frame["name"],
        }


def calls(worker: FakeWorker) -> list[dict[str, Any]]:
    return [frame for frame in worker.frames if frame["method"] == "tools/call"]


def test_a_second_writer_gets_lease_held(tmp_path: Path) -> None:
    """3.5: the lease is per project; another owner's mutating call is refused with the holder,
    the time it took the lease and its running job, and reaches no worker; reads need no lease."""

    async def scenario() -> None:
        worker = FakeWorker()
        admission = Admission(worker, Ledger(tmp_path / "ledger.sqlite3"))
        first = await admission.call("edit", {"idempotency_key": "a-1"}, True, owner="a")
        assert first["receipt"]["admission"] == "executed"
        worker.gate = asyncio.Event()
        running = asyncio.ensure_future(
            admission.call("edit", {"idempotency_key": "a-2"}, True, owner="a")
        )
        await asyncio.sleep(0.01)
        job_id = admission.running[UUID]
        refused = await admission.call(
            "edit", {"idempotency_key": "b-1", "expected_revision": 6}, True, owner="b"
        )
        lease = refused["error"]
        assert lease["code"] == "lease_held"
        assert lease["details"]["holder"] == "a"
        assert lease["details"]["active_job"] == job_id
        assert isinstance(lease["details"]["since"], str)
        assert refused["receipt"]["job_id"] is None
        read = await asyncio.wait_for(admission.call("inspect", {}, False, owner="b"), 1)
        assert "error" not in read
        worker.gate.set()
        assert "result" in await running
        assert [
            frame["idempotency_key"] for frame in calls(worker) if "idempotency_key" in frame
        ] == [
            "a-1",
            "a-2",
        ]

    asyncio.run(scenario())


def test_busy_refuses_instead_of_queueing_and_wait_idle_times_out(tmp_path: Path) -> None:
    """3.5, INT-05: a mutating call while another of the project runs returns `busy {job_id}`
    without reaching the worker; `wait_idle` fails explicitly on timeout and succeeds once idle."""

    async def scenario() -> None:
        worker = FakeWorker()
        ledger = Ledger(tmp_path / "ledger.sqlite3")
        admission = Admission(worker, ledger)
        worker.gate = asyncio.Event()
        running = asyncio.ensure_future(admission.call("edit", {"idempotency_key": "k-1"}, True))
        await asyncio.sleep(0.01)
        job_id = admission.running[UUID]
        busy = await admission.call("edit", {"idempotency_key": "k-2"}, True)
        assert busy["error"]["code"] == "busy"
        assert busy["error"]["details"] == {"job_id": job_id}
        timed_out = await admission.wait_idle(0.05)
        assert timed_out["error"]["code"] == "timeout"
        assert timed_out["error"]["details"]["running"] == [job_id]
        lease = ledger.lease(UUID)
        assert lease is not None and lease.active_job == job_id
        worker.gate.set()
        done = await running
        assert done["receipt"]["job_id"] == job_id
        assert (await admission.wait_idle(5))["result"]["idle"] is True
        assert [frame.get("idempotency_key") for frame in calls(worker)] == ["k-1"]
        job = ledger.job(job_id)
        assert job is not None
        assert (job["state"], job["committed_revision"], job["request_hash"]) == (
            "succeeded",
            6,
            "h-edit",
        )
        lease = ledger.lease(UUID)
        assert lease is not None and lease.active_job is None

    asyncio.run(scenario())


def test_reconciliation_precedes_admission_after_every_epoch(tmp_path: Path) -> None:
    """2.6: before the first call of a project epoch (a relaunch, a switch of project) the
    operation rows after the last acknowledged revision are read and recorded; acknowledgements
    then follow the replies."""

    async def scenario() -> None:
        worker = FakeWorker()
        ledger = Ledger(tmp_path / "ledger.sqlite3")
        ledger.acknowledge(UUID, 3)
        stored = {"status": "committed", "committed_revision": 5}
        worker.operations["result"]["operations"] = [
            {
                "idempotency_key": "k-5",
                "request_hash": "h",
                "outcome": stored,
                "committed_revision": 5,
            }
        ]
        admission = Admission(worker, ledger)
        await admission.call("inspect", {}, False)
        assert worker.frames[0] == {"method": "worker/operations", "after": 3}
        assert worker.frames[1]["method"] == "tools/call"
        assert ledger.outcome(UUID, "k-5") == {
            "request_hash": "h",
            "committed_revision": 5,
            "outcome": stored,
            "source": "operation_row",
        }
        assert ledger.acknowledged(UUID) == 5
        await admission.call("edit", {"idempotency_key": "k-6", "expected_revision": 5}, True)
        assert ledger.acknowledged(UUID) == 6
        recorded = ledger.outcome(UUID, "k-6")
        assert recorded is not None and recorded["source"] == "reply"
        assert [frame["method"] for frame in worker.frames].count("worker/operations") == 1
        worker.project_epoch += 1  # the worker was relaunched
        worker.frames.clear()
        await admission.call("inspect", {}, False)
        assert worker.frames[0] == {"method": "worker/operations", "after": 6}

    asyncio.run(scenario())


def test_unreadable_operation_records_give_outcome_unknown(tmp_path: Path) -> None:
    """2.6, 3.6: operation rows that cannot be read fail a mutating call with `outcome_unknown`
    and nothing runs, until a reconciliation succeeds; a key whose own row does not decode fails
    the same way while other keys are admitted."""

    async def scenario() -> None:
        worker = FakeWorker()
        admission = Admission(worker, Ledger(tmp_path / "ledger.sqlite3"))
        worker.operations = {
            "id": "x",
            "error": {"code": "outcome_unknown", "message": "disk I/O error", "details": {}},
        }
        refused = await admission.call(
            "edit", {"idempotency_key": "k-1", "expected_revision": 5}, True
        )
        assert refused["error"]["code"] == "outcome_unknown"
        assert refused["error"]["details"] == {"committed_revision": 5}
        assert calls(worker) == []
        assert "result" in await admission.call("inspect", {}, False)
        worker.operations = FakeWorker().operations
        worker.operations["result"]["unreadable"] = ["k-1"]
        again = await admission.call(
            "edit", {"idempotency_key": "k-1", "expected_revision": 5}, True
        )
        assert again["error"]["code"] == "outcome_unknown"
        assert again["error"]["details"] == {"key": "k-1", "committed_revision": 5}
        other = await admission.call(
            "edit", {"idempotency_key": "k-2", "expected_revision": 5}, True
        )
        assert other["receipt"]["admission"] == "executed"
        assert [frame.get("idempotency_key") for frame in calls(worker)] == [None, "k-2"]

    asyncio.run(scenario())


def test_key_and_precondition_omission_rule_and_receipts(tmp_path: Path) -> None:
    """2.8, 11 §4: without key and precondition the supervisor generates the key and resolves
    the precondition once; with a precondition only it generates the key; a client key without a
    precondition is forwarded without one. Every receipt names its target and both values."""

    async def scenario() -> None:
        worker = FakeWorker()
        admission = Admission(worker, Ledger(tmp_path / "ledger.sqlite3"))
        generated = await admission.call("edit", {"texture_set": "Plane"}, True)
        frame = calls(worker)[-1]
        assert frame["idempotency_key"].startswith("sup-")
        assert frame["expected_revision"] == 5
        assert frame["arguments"] == {"texture_set": "Plane"}
        receipt = generated["receipt"]
        assert receipt == {
            "tool": "edit",
            "job_id": receipt["job_id"],
            "revision": 5,
            "idempotency_key": frame["idempotency_key"],
            "key_source": "supervisor",
            "expected_revision": 5,
            "admission": "executed",
            "request_hash": "h-edit",
            "project": "C:/p/plane.uzp",
            "project_uuid": UUID,
            "texture_set": "Plane",
            "committed_revision": 6,
        }
        assert receipt["job_id"].startswith("job-")
        await admission.call("edit", {"expected_revision": 6}, True)
        frame = calls(worker)[-1]
        assert frame["idempotency_key"].startswith("sup-") and frame["expected_revision"] == 6
        keyed = await admission.call("edit", {"idempotency_key": "mine"}, True)
        frame = calls(worker)[-1]
        assert frame["idempotency_key"] == "mine" and "expected_revision" not in frame
        assert keyed["receipt"]["key_source"] == "client"
        assert keyed["receipt"]["expected_revision"] is None

    asyncio.run(scenario())


def test_the_ledger_is_durable_and_a_dead_holders_lease_is_taken_over(tmp_path: Path) -> None:
    """2.2: jobs, leases, acknowledgements and outcomes survive a reopened ledger; the lease of
    a process that has ended is taken over by the next owner."""
    path = tmp_path / "ledger.sqlite3"
    ledger = Ledger(path)
    ended = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        check=True,
        capture_output=True,
        text=True,
    )
    dead_pid = int(ended.stdout)
    ledger.acquire(UUID, "stdio:dead", dead_pid)
    ledger.begin_job("job-1", UUID, "edit", "k-1", "client", 5)
    ledger.finish_job("job-1", "interrupted", None, 6, "interrupted")
    ledger.acknowledge(UUID, 6)
    ledger.record_outcome(UUID, "k-1", "h", 6, {"status": "committed"}, "operation_row")
    ledger.close()
    reopened = Ledger(path)
    job = reopened.job("job-1")
    assert job is not None and job["state"] == "interrupted" and job["committed_revision"] == 6
    assert reopened.acknowledged(UUID) == 6
    assert reopened.outcome(UUID, "k-1") is not None
    taken = reopened.acquire(UUID, "stdio:new", 4242)
    assert (taken.holder, taken.holder_pid) == ("stdio:new", 4242)
    reopened.release("stdio:new")
    assert reopened.lease(UUID) is None
    reopened.close()
