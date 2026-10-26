"""Capture one authored Raw capability in an owned Painter; never export or admit.

Runtime requires coordinator release after review. All receipts, paths and failure
details remain in exclusively reserved private evidence; stdout contains counts/hashes.
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from tools.parity.envelope.colour_sessions import declaration, launch_environment
from tools.parity.preserve_diagnostic_evidence import file_fingerprint, private_path
from tools.parity.recorder import project_configuration_survey as ownership
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.launcher import PainterLauncher, endpoint_answers
from tools.parity.recorder.output import inbox_root, work_root
from tools.parity.recorder.probes import (
    ProbeJob,
    ProbeSession,
    probe_job_from_manifest,
    record_probe_golden,
)
from tools.parity.recorder.session import HttpTransport
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import ocio16_raw_readout_control as control

CAPTURE_SECONDS = 900.0
CLEANUP_SECONDS = 120.0
OWNER = "Codex/uzpainter-raw-capability"


@dataclass(frozen=True)
class Request:
    state: str
    manifest: Path
    painter_exe: Path
    output_prefix: Path


class Evidence:
    def __init__(self, prefix: Path, stack: ExitStack) -> None:
        prefix = private_path(prefix, REPO_ROOT)
        ownership.require(prefix.parent.is_dir() and bool(prefix.name), "private parent required")
        self.paths: dict[str, Path] = {}
        self.handles: dict[str, BinaryIO] = {}
        for name, suffix in (("report", ".report.json"), ("log", ".events.jsonl")):
            path = private_path(prefix.with_name(prefix.name + suffix), REPO_ROOT)
            self.paths[name] = path
            self.handles[name] = stack.enter_context(path.open("xb"))
        self.console = stack.enter_context(
            prefix.with_name(prefix.name + ".console.log").open("x", encoding="utf-8")
        )

    def json(self, name: str, value: Any) -> None:
        data = canonical_json(value) + b"\n"
        ownership.require(self.handles[name].write(data) == len(data), "short evidence write")
        self.handles[name].flush()

    def log(self, event: str, **fields: Any) -> None:
        self.json("log", {"event": event, **fields})


class BoundedTransport(HttpTransport):
    deadline: float

    def run(self, code: str) -> Any:
        remaining = self.deadline - time.monotonic()
        ownership.require(remaining > 0, "capture deadline exceeded")
        self.timeout_s = min(10.0, remaining)
        value = super().run(code)
        ownership.require(time.monotonic() < self.deadline, "capture deadline exceeded")
        return value


class GuardedTransport(ownership.OwnedTransport):
    lost = False

    def verify(self) -> None:
        ownership.require_owned(not self.lost, "ownership loss already observed")
        try:
            super().verify()
        except ownership.OwnershipLost:
            self.lost = True
            raise

    def run(self, code: str) -> Any:
        try:
            return super().run(code)
        except ownership.OwnershipLost:
            self.lost = True
            raise


class RawSession(ProbeSession):
    owned: GuardedTransport
    created_uuid: str | None = None
    saved_path: Path | None = None
    created = False

    @classmethod
    def attached(cls, owned: GuardedTransport, build_id: str) -> RawSession:
        session = cls(owned, verify_calls=True, allowed_builds=lambda: frozenset({build_id}))
        session.owned = owned
        owned.closed_expected = True
        return session

    def call(self, operation: str, **args: Any) -> Any:
        try:
            return self.owned_call(operation, **args)
        except ownership.OwnershipLost:
            self.owned.lost = True
            raise

    def owned_call(self, operation: str, **args: Any) -> Any:
        create = operation == "apply_step" and args.get("call") == ownership.CREATE
        if create:
            ownership.require(not self.created, "only one owned creation allowed")
            self.created = True
        if operation == "save_as":
            ownership.require(self.created_uuid is not None, "no owned project to save")
            path = private_path(Path(args["path"]), REPO_ROOT)
            ownership.require(self.saved_path is None, "only one full save allowed")
            self.saved_path = path
        if operation == "open_project":
            ownership.require_owned(
                self.owned.closed_expected
                and self.created_uuid is not None
                and self.saved_path is not None
                and Path(args["path"]).resolve() == self.saved_path,
                "only the owned saved project may reopen",
            )
        value = super().call(operation, **args)
        if create:
            self.created_uuid = self.owned.claim_created()
        elif operation == "close_project":
            self.owned.project_uuid = None
            self.owned.closed_expected = True
        elif operation == "open_project":
            self.owned.closed_expected = False
            self.owned.project_uuid = self.created_uuid
            self.owned.verify()
        return value


def prepared(request: Request) -> ProbeJob:
    ownership.require(request.state in control.STATES, "unknown Raw state")
    authored = control.request(request.state)
    manifest = json.loads(request.manifest.read_bytes())
    ownership.require(
        canonical_json(manifest) == canonical_json(authored), "authored request differs"
    )
    job = probe_job_from_manifest(manifest)
    ownership.require(not job.exports and not job.events and not job.lifecycle, "capability only")
    ownership.require(request.painter_exe.is_file(), "Painter executable unavailable")
    return job


def capture(request: Request) -> dict[str, Any]:
    with ExitStack() as stack:
        evidence = Evidence(request.output_prefix, stack)
        report: dict[str, Any] = {
            "schema": "uzpainter/raw-capability-capture/1",
            "status": "refused",
            "state": request.state,
            "stage": "preflight",
            "captures": 0,
            "exports": 0,
            "admissions": 0,
            "capture_seconds": CAPTURE_SECONDS,
            "cleanup_seconds": CLEANUP_SECONDS,
        }
        lock = ownership.Lock(evidence, owner=OWNER, task="One authored Raw capability capture")
        launcher = PainterLauncher(request.painter_exe, ready_timeout_s=120, stop_timeout_s=15)
        raw = BoundedTransport(timeout_s=10)
        raw.deadline = time.monotonic() + CAPTURE_SECONDS
        owned = None
        session = None
        preserve = False
        with redirect_stdout(evidence.console), redirect_stderr(evidence.console):
            try:
                job = prepared(request)
                limits = ownership.Request(request.painter_exe, request.output_prefix)
                work, inbox = work_root(), inbox_root()
                environment = launch_environment(declaration(job.manifest), request.painter_exe)
                host = ownership.host_state()
                evidence.log(
                    "preflight",
                    processes=host.processes,
                    physical_free=host.physical_free,
                    commit_free=host.commit_free,
                )
                ownership.resources_available(host, limits)
                ownership.require(not ownership.painters(host), "existing Painter process")
                ownership.require(not endpoint_answers(), "existing Painter endpoint")
                report["stage"] = "lock"
                lock.acquire()
                host = ownership.host_state()
                ownership.resources_available(host, limits)
                ownership.require(
                    not ownership.painters(host) and not endpoint_answers(),
                    "Painter appeared before launch",
                )
                report["stage"] = "launch"
                launcher.start(environment=environment)
                current = ownership.unique(
                    ownership.painters(ownership.host_state()), "one newly owned Painter required"
                )
                ownership.require_owned(
                    current["pid"] == launcher.pid
                    and isinstance(current["started"], str)
                    and bool(current["started"]),
                    "owned Painter unavailable",
                )
                evidence.log("owned_process", pid=launcher.pid, started=current["started"])
                owned = GuardedTransport(raw, launcher, lock, current["started"])
                owned.closed_expected = True
                owned.verify()
                session = RawSession.attached(
                    owned, job.manifest["software"]["painter"]["build_id"]
                )
                report["stage"] = "capture"
                run = record_probe_golden(session, job, work, inbox)
                report.update(captures=1, run=str(run))
                evidence.log("capture_ready", captures=1, run=str(run))
                owned.verify()
                run_manifest = json.loads((run / "manifest.json").read_bytes())
                report.update(
                    status="complete",
                    private_records=run_manifest["private_records"],
                )
            except Exception as error:
                report["error"] = traceback.format_exc()
                preserve = isinstance(error, ownership.OwnershipLost) or (
                    owned is not None and owned.lost
                )
            finally:
                raw.deadline = time.monotonic() + CLEANUP_SECONDS
                report["stage_at_cleanup"] = report["stage"]
                ownership.cleanup_owned(launcher, session, owned, lock, report, preserve=preserve)
                evidence.json("report", report)
        return {
            "status": report["status"],
            "captures": report["captures"],
            "report_sha256": file_fingerprint(evidence.paths["report"])[0],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", choices=control.STATES, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--painter-exe", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = capture(Request(**vars(args)))
    except Exception:
        result = {"status": "refused"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
