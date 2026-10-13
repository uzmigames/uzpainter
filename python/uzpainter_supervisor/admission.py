"""Command admission: the mutation lease, busy state, idempotency keys, reconciliation and
receipts (02-runtime-topology.md §3, 11-mcp-server.md §4; task phase2.2, decisions 138, 139).

Every `tools/call` goes through `Admission.call`:

1. **Reconciliation.** Before any call for the project the worker holds, the supervisor reads
   that project's `operation` rows committed after the revision it last acknowledged
   (`worker/operations`) once per project epoch: after every worker relaunch and every switch of
   project. They are recorded in the ledger as acknowledged outcomes. If they cannot be read, a
   mutating call fails with `outcome_unknown {committed_revision}` until a later reconciliation
   succeeds; a key whose row does not decode fails the same way.
2. **Keys and preconditions.** A mutating call without `idempotency_key` and
   `expected_revision` gets a generated key and the reconciled current revision as its
   precondition; one with `expected_revision` only gets a generated key. A client key without a
   precondition is sent without one: the worker returns that key's stored outcome or
   `outcome_unknown`, and never runs it. The worker decides the rest from the operation rows
   (known key and request hash first, then the precondition).
3. **Lease.** One mutation lease per project UUID, recorded in the ledger. A stdio session
   holds it implicitly (its owner is the session); a mutating call from another owner returns
   `lease_held {holder, since, active_job}`. Reads need no lease. A call during which the worker
   switches to another project (`project_create`, `project_open`, a script) takes the new
   project's lease for its owner when the worker reports the switch, before any other call can
   see the project, unless another live owner holds it; an HTTP session that has named no owner
   takes none (decision 243).
4. **Busy.** A mutating call while another mutating call of the same project runs returns
   `busy {job_id}`; it is not queued. `wait_idle {timeout}` waits for no call to run; its
   timeout is an error.
5. **Receipts.** Every reply carries `receipt`: the project the worker holds afterwards (path
   and UUID), the texture set the call named or returned, the job, the revision the call was
   admitted on and the committed revision; a mutating call adds its key (`key_source`: client
   or supervisor), its precondition, its request hash and the worker's admission
   (`executed` or `stored_outcome`).
6. **Long jobs** (phase2.3, decisions 140, 141). A tool the worker lists as `long` runs as a job:
   the call returns `{job_id, status: "running"}` at once, or with `wait=true` waits for the end
   while `notify` streams `{job_id, status, progress, message}`. A long job holds its project's
   running slot like a mutating call (`busy {job_id}`), and its row in the ledger follows its
   progress and its commit point. `job_status`, `job_result`, `job_cancel` and `job_list` answer
   from this supervisor and its ledger; `job_cancel` records the request and sends
   `worker/cancel`, which the worker acknowledges at once. The terminal receipt adds `status`
   (`succeeded`, `failed`, `cancelled` or `interrupted`), the worker's job receipt (`job`:
   `committed`, `stopped` before or after the commit point, `cancel_requested`, `no_op`) and, for
   an `interrupted` job, its `resolution`: a worker death is resolved from the operation rows the
   reconciliation reads (the key's row, or none), never by running the job again. Running jobs a
   supervisor that has ended left in the ledger are marked `interrupted` (outcome unknown) when
   the next supervisor starts; a later reconciliation that finds their key's row resolves them.
7. **Result contract** (phase2.5, decision 158). Every reply also carries `revision`,
   `committed_revision`, `job_id`, `changed`, `created`, `hidden`, `imported`, `skipped` and
   `warnings` at its top level (`contract`), and the ledger keeps it as answered.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .ledger import TERMINAL, Ledger, identity_alive, process_identity

# Streams one `{job_id, status, progress, message}` event of a long job waited for.
Notify = Callable[[dict[str, Any]], Awaitable[None]]


class Worker(Protocol):
    """What admission needs of `worker.Supervisor`."""

    project_path: str | None
    project_uuid: str | None
    durable_revision: int | None
    project_epoch: int

    async def wait_ready(self) -> None: ...

    async def request(self, frame: dict[str, Any]) -> dict[str, Any]: ...


def error_reply(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


CHANGE_LISTS = ("created", "hidden", "imported", "skipped")


def _ordered(values: list[Any]) -> list[Any]:
    seen: list[Any] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def contract(body: dict[str, Any], durable_revision: int | None = None) -> dict[str, Any]:
    """`body` with the result contract of 11 §2 at its top level; `committed_revision` falls back
    to `durable_revision`, the project's committed revision the worker last reported (an error
    reply carries none of its own)."""
    receipt = body.get("receipt") if isinstance(body.get("receipt"), dict) else {}
    assert isinstance(receipt, dict)
    result = body.get("result")
    error = body.get("error")
    transactions: list[dict[str, Any]] = []
    details = error.get("details") if isinstance(error, dict) else None
    for source in (result, details):
        committed = source.get("committed") if isinstance(source, dict) else None
        if isinstance(committed, list):  # a script's committed calls (also when it raised)
            transactions += [item for item in committed if isinstance(item, dict)]
    changes = (*CHANGE_LISTS, "modified", "removed")
    if isinstance(result, dict) and any(key in result for key in changes):
        transactions.append(result)  # one transaction's result
    lists: dict[str, list[Any]] = {name: [] for name in ("changed", *CHANGE_LISTS)}
    for transaction in transactions:
        for name in ("modified", "removed"):
            lists["changed"] += list(transaction.get(name) or [])
        for name in CHANGE_LISTS:
            lists[name] += list(transaction.get(name) or [])
    warnings = result.get("warnings") if isinstance(result, dict) else None
    committed_revision = body.get("committed_revision", receipt.get("committed_revision"))
    if committed_revision is None:
        committed_revision = durable_revision
    return {
        **body,
        "revision": receipt.get("revision"),
        "committed_revision": committed_revision,
        "job_id": receipt.get("job_id"),
        **{name: _ordered(values) for name, values in lists.items()},
        "warnings": list(warnings) if isinstance(warnings, list) else [],
    }


@dataclass
class LiveJob:
    """A long job this supervisor runs."""

    job_id: str
    tool: str
    progress: float = 0.0
    message: str = ""
    committed: dict[str, Any] | None = None
    cancel_requested: bool = False
    task: asyncio.Future[dict[str, Any]] | None = None
    queues: list[asyncio.Queue[dict[str, Any]]] = field(default_factory=list)

    def event(self, status: str = "running") -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": status,
            "progress": self.progress,
            "message": self.message,
        }


class Admission:
    """The admission of one supervisor's calls, over its worker and its ledger."""

    def __init__(self, worker: Worker, ledger: Ledger) -> None:
        self.worker = worker
        self.ledger = ledger
        self.pid = os.getpid()
        # The running mutating call (its job id) per project UUID ("" while none is open).
        self.running: dict[str, str] = {}
        self._idle = asyncio.Event()
        self._idle.set()
        self._reconciled_epoch: int | None = None
        self._unreadable: set[str] = set()
        # The long jobs this supervisor runs, by job id.
        self.live: dict[str, LiveJob] = {}
        # The admitted calls of an owner that the worker has not answered yet, by job id (an
        # anonymous call takes no lease, so it is not among them).
        self._runs: dict[str, _Run] = {}
        self.identity = process_identity(self.pid) or f"{self.pid}:0"
        self._sweep()

    def _sweep(self) -> None:
        """Marks the running jobs of supervisors that have ended `interrupted` (02 §5)."""
        for job in self.ledger.orphaned_jobs(self.identity):
            if job["supervisor"] is not None and identity_alive(job["supervisor"]):
                continue
            self.ledger.finish_job(
                job["job_id"],
                "interrupted",
                job["request_hash"],
                job["committed_revision"],
                "interrupted",
                resolution={"committed": None, "source": "supervisor_ended"},
            )

    def stdio_owner(self) -> str:
        """The implicit lease owner of the stdio session (its only client)."""
        return f"stdio:{self.pid}"

    def close(self) -> None:
        self.ledger.release(self.stdio_owner())

    # ── Reconciliation ──────────────────────────────────────────────────────────────────────

    async def reconcile(self) -> dict[str, Any] | None:
        """Reconciles the ledger with the open project's operation rows once per project epoch;
        the `outcome_unknown` error when they cannot be read."""
        worker = self.worker
        epoch = worker.project_epoch
        project_uuid = worker.project_uuid
        if project_uuid is None or self._reconciled_epoch == epoch:
            return None
        after = self.ledger.acknowledged(project_uuid) or 0
        reply = await worker.request({"method": "worker/operations", "after": after})
        result = reply.get("result")
        if not isinstance(result, dict) or result.get("project_uuid") != project_uuid:
            error = reply.get("error") if isinstance(reply.get("error"), dict) else {}
            assert isinstance(error, dict)
            return error_reply(
                "outcome_unknown",
                "the project's operation records cannot be read: "
                + str(error.get("message", "the worker holds another project")),
                {"committed_revision": worker.durable_revision},
            )
        for row in result["operations"]:
            self.ledger.record_outcome(
                project_uuid,
                row["idempotency_key"],
                row["request_hash"],
                row["committed_revision"],
                row["outcome"],
                "operation_row",
            )
        self.ledger.acknowledge(project_uuid, int(result["current_revision"]))
        self._unreadable = set(result["unreadable"])
        # Interrupted jobs whose outcome was unknown: their key's row resolves them.
        for job in self.ledger.unresolved_jobs(project_uuid):
            outcome = self.ledger.outcome(project_uuid, job["idempotency_key"])
            if outcome is not None:
                self.ledger.resolve_job(
                    job["job_id"],
                    {
                        "committed": True,
                        "committed_revision": outcome["committed_revision"],
                        "source": "operation_row",
                    },
                )
        if epoch == worker.project_epoch:
            self._reconciled_epoch = epoch
        return None

    # ── Calls ───────────────────────────────────────────────────────────────────────────────

    async def call(
        self,
        name: str,
        arguments: dict[str, Any],
        mutating: bool,
        owner: str | None = None,
        *,
        long: bool = False,
        commit_point: str | None = None,
        notify: Notify | None = None,
        anonymous: bool = False,
    ) -> dict[str, Any]:
        """Admits and forwards one tool call; the reply body with its receipt. A long call
        (`long`, with the worker's `commit_point`) runs as a job: `wait` among its arguments
        waits for its end, streaming its events to `notify`. `owner` is the stdio session's when
        omitted; an `anonymous` call (an HTTP session that has named no owner) takes no lease."""
        worker = self.worker
        owner = owner or self.stdio_owner()
        arguments = dict(arguments)
        key = arguments.pop("idempotency_key", None)
        expected = arguments.pop("expected_revision", None)
        wait = arguments.pop("wait", False) is True if long else False
        while True:
            # Reconciled for the project the worker holds now: a relaunch or a switch of project
            # during the reconciliation starts it over.
            await worker.wait_ready()
            epoch = worker.project_epoch
            refused = await self.reconcile()
            if epoch == worker.project_epoch:
                break
        project_uuid = worker.project_uuid
        admitted_revision = worker.durable_revision
        receipt: dict[str, Any] = {"tool": name, "job_id": None, "revision": admitted_revision}
        frame: dict[str, Any] = {"method": "tools/call", "name": name, "arguments": arguments}
        if not mutating and not long:
            for field_name, value in (("idempotency_key", key), ("expected_revision", expected)):
                if value is not None:
                    frame[field_name] = value
            return self._finish(await worker.request(frame), receipt, arguments)

        key_source: str | None = None
        if mutating:
            key_source = "client"
            if key is None:
                key, key_source = f"sup-{uuid.uuid4().hex}", "supervisor"
                if expected is None:
                    expected = admitted_revision if admitted_revision is not None else 0
            receipt.update(
                {"idempotency_key": key, "key_source": key_source, "expected_revision": expected}
            )
            if refused is None and project_uuid is not None and key in self._unreadable:
                refused = error_reply(
                    "outcome_unknown",
                    "the key's operation record cannot be read: the call is not run",
                    {"key": key, "committed_revision": admitted_revision},
                )
            if refused is None and project_uuid is not None:
                refused = self.check_lease(project_uuid, owner)
        else:
            refused = None
        scope = project_uuid or ""
        if refused is None and scope in self.running:
            refused = error_reply(
                "busy",
                "another mutating call or long job of this project is running; the call is not "
                "queued",
                {"job_id": self.running[scope]},
            )
        if refused is not None:
            return self._finish(refused, receipt, arguments)

        job_id = f"job-{uuid.uuid4().hex}"
        receipt["job_id"] = job_id
        self.ledger.begin_job(
            job_id,
            project_uuid,
            name,
            key if mutating else None,
            key_source,
            expected if mutating else None,
            long=long,
            supervisor=self.identity,
        )
        self.running[scope] = job_id
        self._idle.clear()
        if mutating and project_uuid is not None:
            self.ledger.set_active_job(project_uuid, owner, job_id)
        if mutating:
            frame["idempotency_key"] = key
            if expected is not None:
                frame["expected_revision"] = expected
        run = _Run(
            job_id, scope, project_uuid, owner, key, mutating, long, commit_point, epoch, frame
        )
        if not anonymous:
            self._runs[job_id] = run
        if not long:
            return await self._run(run, frame, receipt, arguments)
        frame["job_id"] = job_id
        live = LiveJob(job_id, name)
        self.live[job_id] = live
        live.task = asyncio.ensure_future(self._run(run, frame, receipt, arguments))
        if not wait:
            started = self._finish(
                {"result": {"job_id": job_id, "status": "running"}}, dict(receipt), arguments
            )
            started["receipt"]["status"] = "running"
            return started
        return await self._wait(live, notify)

    async def _run(
        self,
        run: _Run,
        frame: dict[str, Any],
        receipt: dict[str, Any],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Forwards an admitted job's call and records its end; the reply body."""
        try:
            reply = await self.worker.request(frame)
        finally:
            del self.running[run.scope]
            self._runs.pop(run.job_id, None)
            if not self.running:
                self._idle.set()
            if run.mutating and run.project_uuid is not None:
                self.ledger.set_active_job(run.project_uuid, run.owner, None)
        state = _state(reply)
        live = self.live.get(run.job_id)
        resolution = None
        if state == "interrupted":
            resolution = await self._resolve(run, live.committed if live else None)
        body = self._finish(reply, receipt, arguments)
        if run.long:
            body["receipt"]["status"] = state
            body["receipt"]["job"] = reply.get("job")
        if resolution is not None:
            body["receipt"]["resolution"] = resolution
        self._record(run, reply, state, body, resolution)
        self.live.pop(run.job_id, None)
        return body

    def refused(self, name: str, reply: dict[str, Any]) -> dict[str, Any]:
        """A call the registry refused before admission (registry.py): its error with the receipt
        of a call that was never admitted (no job, no key)."""
        receipt: dict[str, Any] = {
            "tool": name,
            "job_id": None,
            "revision": self.worker.durable_revision,
        }
        return self._finish(reply, receipt, {})

    def check_lease(self, project_uuid: str, owner: str) -> dict[str, Any] | None:
        """Takes the project's lease for `owner`, or the `lease_held` error of its holder."""
        lease = self.ledger.acquire(project_uuid, owner, self.pid)
        if lease.holder == owner:
            return None
        return error_reply(
            "lease_held", "another client holds the project's mutation lease", lease.to_json()
        )

    def on_project_switch(self, frame: dict[str, Any] | None) -> None:
        """The worker switched to another project while it ran `frame` (worker.py reports it with
        the project, before the call's reply): the owner of that call takes the new project's
        lease now, so a lease taken before `project_create` or `project_open` holds the project
        they make and no other client can take it first (decision 243). A live holder's lease
        stays; a call that is not one of an owner's (an anonymous call, a supervisor request)
        takes none."""
        project_uuid = self.worker.project_uuid
        run = next((run for run in self._runs.values() if run.frame is frame), None)
        if project_uuid is not None and run is not None:
            self.ledger.acquire(project_uuid, run.owner, self.pid)

    async def _resolve(self, run: _Run, committed: dict[str, Any] | None) -> dict[str, Any]:
        """The outcome of a job its worker's death interrupted, read, never re-run (02 §5): a
        mutating job's from the operation rows the reconciliation of the relaunched worker reads
        (its key's row, or none); a long job's from the commit point it reported."""
        worker = self.worker
        if run.mutating and run.project_uuid is not None:
            await worker.wait_ready()
            refused = await self.reconcile()
            reconciled = (
                refused is None
                and worker.project_uuid == run.project_uuid
                and self._reconciled_epoch == worker.project_epoch
            )
            if not reconciled or run.key in self._unreadable:
                return {"committed": None, "source": "operation_rows_unreadable"}
            assert run.key is not None
            outcome = self.ledger.outcome(run.project_uuid, run.key)
            if outcome is None:
                return {"committed": False, "source": "operation_row"}
            return {
                "committed": True,
                "committed_revision": outcome["committed_revision"],
                "source": "operation_row",
            }
        if committed is not None:
            return {"committed": True, "what": committed, "source": "job_event"}
        if run.commit_point is None:
            return {"committed": False, "source": "no_commit_point"}
        # The worker may have died between its commit and the event that reports it.
        return {"committed": None, "source": "no_commit_event", "commit_point": run.commit_point}

    def _record(
        self,
        run: _Run,
        reply: dict[str, Any],
        state: str,
        body: dict[str, Any],
        resolution: dict[str, Any] | None,
    ) -> None:
        error = reply.get("error")
        committed = reply.get("committed_revision")
        error_code = None
        if isinstance(error, dict):
            error_code = str(error.get("code"))
            details = error.get("details")
            if committed is None and isinstance(details, dict):
                committed = details.get("committed_revision")
        if resolution is not None and resolution.get("committed") is True:
            committed = resolution.get("committed_revision", committed)
        request_hash = reply.get("request_hash")
        self.ledger.finish_job(
            run.job_id,
            state,
            request_hash if isinstance(request_hash, str) else None,
            committed if isinstance(committed, int) else None,
            error_code,
            reply=body,
            resolution=resolution,
        )
        worker = self.worker
        project_uuid = run.project_uuid
        same_project = project_uuid is not None and worker.project_uuid == project_uuid
        if not run.mutating or state != "succeeded" or not same_project:
            return
        if not isinstance(committed, int):
            return
        assert project_uuid is not None and run.key is not None
        if isinstance(request_hash, str) and reply.get("admission") == "executed":
            result = reply.get("result")
            if isinstance(result, dict) and result.get("status") == "committed":
                self.ledger.record_outcome(
                    project_uuid, run.key, request_hash, committed, result, "reply"
                )
        # Every commit since the reconciliation went through this supervisor: the record is
        # complete up to the committed revision.
        if self._reconciled_epoch == run.epoch == worker.project_epoch:
            self.ledger.acknowledge(project_uuid, committed)

    # ── Long jobs ───────────────────────────────────────────────────────────────────────────

    def on_job_event(self, frame: dict[str, Any]) -> None:
        """A worker's `job_progress` event: the job's progress, message and commit point."""
        live = self.live.get(str(frame.get("job_id")))
        if live is None:
            return
        progress = frame.get("progress")
        if isinstance(progress, int | float) and not isinstance(progress, bool):
            live.progress = float(progress)
        message = frame.get("message")
        live.message = message if isinstance(message, str) else ""
        committed = frame.get("committed")
        if isinstance(committed, dict):
            live.committed = committed
        self.ledger.progress_job(live.job_id, live.progress, live.message, live.committed)
        for queue in live.queues:
            queue.put_nowait(live.event())

    async def _wait(self, live: LiveJob, notify: Notify | None) -> dict[str, Any]:
        """Waits for a long job's end, streaming its events; the terminal reply. A wait that is
        itself cancelled (the client cancelled its request) cancels the job."""
        assert live.task is not None
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        live.queues.append(queue)
        try:
            if notify is not None:
                await notify(live.event())
            while not live.task.done():
                getter = asyncio.ensure_future(queue.get())
                await asyncio.wait({getter, live.task}, return_when=asyncio.FIRST_COMPLETED)
                if getter.done():
                    if notify is not None:
                        await notify(getter.result())
                else:
                    getter.cancel()
            while not queue.empty():
                event = queue.get_nowait()
                if notify is not None:
                    await notify(event)
            body = live.task.result()
            if notify is not None:
                job = body["receipt"].get("job")
                if isinstance(job, dict) and isinstance(job.get("progress"), int | float):
                    live.progress = float(job["progress"])
                await notify(live.event(str(body["receipt"].get("status"))))
            return body
        except asyncio.CancelledError:
            if not live.task.done():
                with contextlib.suppress(Exception):
                    await asyncio.shield(self.cancel(live.job_id))
            raise
        finally:
            if queue in live.queues:
                live.queues.remove(queue)

    async def cancel(self, job_id: str) -> dict[str, Any]:
        """`job_cancel`: acknowledges the intent; the job stops at its next checkpoint and its
        terminal receipt says whether that was before or after its commit point."""
        live = self.live.get(job_id)
        if live is None:
            row = self.ledger.job(job_id)
            if row is None:
                return error_reply("unknown_job", f"no job {job_id}", {"job_id": job_id})
            if row["state"] == "running":
                return error_reply(
                    "not_cancellable",
                    "the job is not a long job of this supervisor",
                    {"job_id": job_id, "supervisor": row["supervisor"], "long": row["long"]},
                )
            receipt = (row["reply"] or {}).get("receipt", {})
            return {
                "result": {
                    "job_id": job_id,
                    "status": row["state"],
                    "cancel": "already_ended",
                    "job": receipt.get("job"),
                }
            }
        live.cancel_requested = True
        self.ledger.request_cancel(job_id)
        ack = await self.worker.request({"method": "worker/cancel", "job_id": job_id})
        result = ack.get("result")
        return {
            "result": {
                "job_id": job_id,
                "status": "running",
                "cancel": "requested",
                "worker": result if isinstance(result, dict) else ack.get("error"),
            }
        }

    def job_status(self, job_id: str) -> dict[str, Any]:
        """`job_status`: a running job's progress, or a finished one's terminal state."""
        live = self.live.get(job_id)
        if live is not None:
            return {
                "result": {
                    **live.event(),
                    "tool": live.tool,
                    "long": True,
                    "committed": live.committed,
                    "cancel_requested": live.cancel_requested,
                }
            }
        row = self.ledger.job(job_id)
        if row is None:
            return error_reply("unknown_job", f"no job {job_id}", {"job_id": job_id})
        return {"result": _summary(row)}

    def job_result(self, job_id: str) -> dict[str, Any]:
        """`job_result`: a finished job's reply as it was answered (with its receipt)."""
        live = self.live.get(job_id)
        if live is not None:
            return error_reply("job_running", f"job {job_id} is still running", live.event())
        row = self.ledger.job(job_id)
        if row is None:
            return error_reply("unknown_job", f"no job {job_id}", {"job_id": job_id})
        if row["state"] not in TERMINAL:
            return error_reply(
                "job_running",
                f"job {job_id} is still running",
                {"job_id": job_id, "status": row["state"]},
            )
        if row["reply"] is not None:
            reply: dict[str, Any] = row["reply"]
            return reply
        return error_reply(
            str(row["error_code"] or row["state"]),
            "the job ended without a recorded reply",
            {"job_id": job_id, "status": row["state"], "resolution": row["resolution"]},
        )

    def job_list(self, limit: int) -> dict[str, Any]:
        """`job_list`: the ledger's newest jobs, running ones with their live progress."""
        jobs = []
        for row in self.ledger.jobs(limit):
            live = self.live.get(row["job_id"])
            jobs.append(self.job_status(row["job_id"])["result"] if live else _summary(row))
        return {"result": {"jobs": jobs}}

    def _finish(
        self, reply: dict[str, Any], receipt: dict[str, Any], arguments: dict[str, Any]
    ) -> dict[str, Any]:
        body = {key: value for key, value in reply.items() if key != "id"}
        admission = body.pop("admission", None)
        request_hash = body.pop("request_hash", None)
        if "idempotency_key" in receipt:
            receipt["admission"] = admission
            receipt["request_hash"] = request_hash
        result = body.get("result")
        texture_set = arguments.get("texture_set")
        if texture_set is None and isinstance(result, dict):
            texture_set = result.get("texture_set")
        committed = body.get("committed_revision")
        error = body.get("error")
        if committed is None and isinstance(error, dict):
            details = error.get("details")
            if isinstance(details, dict):
                committed = details.get("committed_revision")
        receipt.update(
            {
                "project": self.worker.project_path,
                "project_uuid": self.worker.project_uuid,
                "texture_set": texture_set if isinstance(texture_set, str) else None,
                "committed_revision": committed if isinstance(committed, int) else None,
            }
        )
        body["receipt"] = receipt
        # The result contract of 11 §2 (phase2.5, decision 158), part of the reply as answered, so
        # `job_result` returns the same body after a restart.
        return contract(body, self.worker.durable_revision)

    # ── Idle ────────────────────────────────────────────────────────────────────────────────

    async def wait_idle(self, timeout: float) -> dict[str, Any]:
        """Waits until no mutating call runs; a timeout is an error, never a continuation."""
        started = time.perf_counter()
        try:
            await asyncio.wait_for(self._idle.wait(), timeout)
        except TimeoutError:
            return error_reply(
                "timeout",
                f"the supervisor did not become idle within {timeout} s",
                {"timeout": timeout, "running": sorted(self.running.values())},
            )
        return {"result": {"idle": True, "waited_s": round(time.perf_counter() - started, 3)}}

    def status(self) -> dict[str, Any]:
        project_uuid = self.worker.project_uuid
        lease = self.ledger.lease(project_uuid) if project_uuid else None
        return {
            "ledger": str(self.ledger.path),
            "lease": None if lease is None else {**lease.to_json(), "project_uuid": project_uuid},
            "running": dict(self.running),
            "acknowledged_revision": self.ledger.acknowledged(project_uuid)
            if project_uuid
            else None,
        }


@dataclass(frozen=True)
class _Run:
    """An admitted job's call."""

    job_id: str
    scope: str
    project_uuid: str | None
    owner: str
    key: str | None
    mutating: bool
    long: bool
    commit_point: str | None
    epoch: int
    frame: dict[str, Any]  # the request sent for it (on_project_switch finds the call by it)


def _state(reply: dict[str, Any]) -> str:
    """The terminal state of a job's reply."""
    error = reply.get("error")
    if not isinstance(error, dict):
        return "succeeded"
    code = error.get("code")
    if code in ("interrupted", "cancelled"):
        return str(code)
    return "failed"


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    """A ledger job as `job_status` and `job_list` report it."""
    receipt = (row["reply"] or {}).get("receipt", {})
    return {
        "job_id": row["job_id"],
        "tool": row["tool"],
        "long": row["long"],
        "status": row["state"],
        "progress": row["progress"],
        "message": row["message"],
        "committed": row["committed"],
        "cancel_requested": row["cancel_requested"] is not None,
        "project_uuid": row["project_uuid"],
        "idempotency_key": row["idempotency_key"],
        "committed_revision": row["committed_revision"],
        "error_code": row["error_code"],
        "created": row["created"],
        "finished": row["finished"],
        "job": receipt.get("job"),
        "resolution": row["resolution"],
    }
