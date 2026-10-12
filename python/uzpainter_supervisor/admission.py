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
   `lease_held {holder, since, active_job}`. Reads need no lease.
4. **Busy.** A mutating call while another mutating call of the same project runs returns
   `busy {job_id}`; it is not queued. `wait_idle {timeout}` waits for no call to run; its
   timeout is an error.
5. **Receipts.** Every reply carries `receipt`: the project the worker holds afterwards (path
   and UUID), the texture set the call named or returned, the job, the revision the call was
   admitted on and the committed revision; a mutating call adds its key (`key_source`: client
   or supervisor), its precondition, its request hash and the worker's admission
   (`executed` or `stored_outcome`).
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any, Protocol

from .ledger import Ledger


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
        if epoch == worker.project_epoch:
            self._reconciled_epoch = epoch
        return None

    # ── Calls ───────────────────────────────────────────────────────────────────────────────

    async def call(
        self, name: str, arguments: dict[str, Any], mutating: bool, owner: str | None = None
    ) -> dict[str, Any]:
        """Admits and forwards one tool call; the reply body with its receipt."""
        worker = self.worker
        owner = owner or self.stdio_owner()
        arguments = dict(arguments)
        key = arguments.pop("idempotency_key", None)
        expected = arguments.pop("expected_revision", None)
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
        if not mutating:
            for field, value in (("idempotency_key", key), ("expected_revision", expected)):
                if value is not None:
                    frame[field] = value
            return self._finish(await worker.request(frame), receipt, arguments)

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
        scope = project_uuid or ""
        if refused is None and scope in self.running:
            refused = error_reply(
                "busy",
                "another mutating call of this project is running; the call is not queued",
                {"job_id": self.running[scope]},
            )
        if refused is not None:
            return self._finish(refused, receipt, arguments)

        job_id = f"job-{uuid.uuid4().hex}"
        receipt["job_id"] = job_id
        self.ledger.begin_job(job_id, project_uuid, name, key, key_source, expected)
        self.running[scope] = job_id
        self._idle.clear()
        if project_uuid is not None:
            self.ledger.set_active_job(project_uuid, owner, job_id)
        frame["idempotency_key"] = key
        if expected is not None:
            frame["expected_revision"] = expected
        try:
            reply = await worker.request(frame)
        finally:
            del self.running[scope]
            if not self.running:
                self._idle.set()
            if project_uuid is not None:
                self.ledger.set_active_job(project_uuid, owner, None)
        self._record(job_id, project_uuid, key, reply, epoch)
        return self._finish(reply, receipt, arguments)

    def check_lease(self, project_uuid: str, owner: str) -> dict[str, Any] | None:
        """Takes the project's lease for `owner`, or the `lease_held` error of its holder."""
        lease = self.ledger.acquire(project_uuid, owner, self.pid)
        if lease.holder == owner:
            return None
        return error_reply(
            "lease_held", "another client holds the project's mutation lease", lease.to_json()
        )

    def _record(
        self,
        job_id: str,
        project_uuid: str | None,
        key: str,
        reply: dict[str, Any],
        epoch: int,
    ) -> None:
        error = reply.get("error")
        committed = reply.get("committed_revision")
        state = "succeeded"
        error_code = None
        if isinstance(error, dict):
            error_code = str(error.get("code"))
            state = "interrupted" if error_code == "interrupted" else "failed"
            details = error.get("details")
            if committed is None and isinstance(details, dict):
                committed = details.get("committed_revision")
        request_hash = reply.get("request_hash")
        self.ledger.finish_job(
            job_id,
            state,
            request_hash if isinstance(request_hash, str) else None,
            committed if isinstance(committed, int) else None,
            error_code,
        )
        worker = self.worker
        same_project = project_uuid is not None and worker.project_uuid == project_uuid
        if state != "succeeded" or not same_project or not isinstance(committed, int):
            return
        assert project_uuid is not None
        if isinstance(request_hash, str) and reply.get("admission") == "executed":
            result = reply.get("result")
            if isinstance(result, dict) and result.get("status") == "committed":
                self.ledger.record_outcome(
                    project_uuid, key, request_hash, committed, result, "reply"
                )
        # Every commit since the reconciliation went through this supervisor: the record is
        # complete up to the committed revision.
        if self._reconciled_epoch == epoch == worker.project_epoch:
            self.ledger.acknowledge(project_uuid, committed)

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
        return body

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
