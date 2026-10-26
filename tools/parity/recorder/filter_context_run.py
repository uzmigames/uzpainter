"""Record recipe A with read-only F context boundaries in an owned Painter (decision 363).

The orchestration is `probes.record_api_probe`'s, unchanged in its state operations and probes,
with the context readbacks of `filter_context.py` at five boundaries: after the creation (before
step 2), after setup step 6, before step 16 in both rounds, and after the save/close/reopen with
fresh handles. Step 1 and the save, close and open are evidenced by explicitly named documented
readbacks of the ready state that followed each (`project.is_open`, `is_in_edition_state`,
`is_busy`, `file_path`): the transport does not return those calls' own values (documented as
None), and no helper aggregate is labelled as their result.

`f_evidence_from_record` rebuilds the trace and the context frames from the ordered outputs of
the recorded private record, never from a caller's document, and checks them with
`filter_context_contract.validate_context_sequence`. `check_capture` checks only the completed
run (READY, record schema and receipt); F acceptance stays blocked by `require_effective_settings`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.parity.filter_context_contract import (
    A_RECIPE_SHA256,
    SCHEMA,
    ContextRefused,
    FContextEvidence,
    typed,
    validate_context_sequence,
)
from tools.parity.recorder import project_configuration_survey as ownership
from tools.parity.recorder.filter_context import (
    PAINTER_FILTER_CONTEXT,
    context_outputs,
    extension_code,
)
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import MANIFEST_FILE, READY_FILE, RECORD_FILE, write_run
from tools.parity.recorder.probes import (
    GET_NODE_BY_UID,
    PROBE_FLAG,
    WAIT_FLAG,
    CleanupFailed,
    ProbeJob,
    ProbeStep,
    apply_state,
    cleanup_refusal,
    finish_probe,
    golden_key,
    preflight,
    private_record,
    probe_job_from_manifest,
    readback,
    record_probes,
    run_directory,
    stage_inputs,
)
from tools.parity.recorder.raw_capability_capture import (
    CapabilityPolicy,
    GuardedTransport,
    RawSession,
    Request,
    run_owned_capture,
)
from tools.parity.recorder.session import (
    PainterIdentity,
    PainterSession,
    ProjectState,
    RecorderError,
)
from tools.parity.recorder.texture import Now, require_colour_management, utc_now
from tools.parity.schemas import Schema, record_problems, validation_errors
from tools.parity.tier0_semantics import filter_context_control as control

Output = dict[str, Any]
PROJECT = "substance_painter.project."
# The documented getters the recorder's ready-state poll reads (`painter_side.state`).
STATE_GETTERS = ("is_open", "is_in_edition_state", "is_busy", "file_path")
PHASES = ("create", "save", "close", "open")
CONTEXT_ID = re.compile(r"context/([a-z0-9-]+)/[0-9]{4}-[A-Za-z_][A-Za-z0-9_]*")
LIFECYCLE_ID = re.compile(r"lifecycle/(create|save|close|open)/([a-z_]+)")
STEP_ID = re.compile(r"s([0-9]+)/([A-Za-z_][A-Za-z0-9_]*)")
TEMPLATE_ID = "template/texture-sets"
REBIND_ID = "identity/reopen"
# The nodes the probes insert and the F context reads by role (painter_filter_context: host is
# PROBE_NODES[3], filter PROBE_NODES[6]); identity/s<n> and the reopen rebind name exactly these,
# with the values painter_probes.probe_identity and probe_rebind return when the node is kept.
IDENTITY_STEPS = ("3", "6")
IDENTITY_VALUE = {"present": True, "uid_same_as_recorded": True, "uid_resolves_to_node": True}
REBIND_VALUE = {"found_by": dict.fromkeys(IDENTITY_STEPS, "location")}


def install(session: PainterSession) -> None:
    """Load the read-only F context extension next to the probe operations."""
    session.transport.run(extension_code(PAINTER_FILTER_CONTEXT.read_text(encoding="utf-8")))


class FContextSession(RawSession):
    """The owned Raw session (ownership guards unchanged) with the F context extension."""

    def connect(self) -> PainterIdentity:
        identity = super().connect()
        install(self)
        return identity


def state_readbacks(phase: str, state: ProjectState) -> list[Output]:
    """The documented getters the recorder's state poll actually called for the state a phase
    ended in (`painter_side.state`): `is_in_edition_state` only when the project is open,
    `file_path` only in edition; nothing it did not call is recorded."""
    values: dict[str, bool | str | None] = {"is_open": state.is_open}
    if state.is_open:
        values["is_in_edition_state"] = state.in_edition
    values["is_busy"] = state.busy
    if state.in_edition:
        values["file_path"] = state.file_path
    return [
        readback(f"lifecycle/{phase}/{getter}", PROJECT + getter, {}, {"value": value})
        for getter, value in values.items()
    ]


def save_close_reopen(session: PainterSession, project_file: Path) -> list[Output]:
    """`texture.save_and_reopen` with the documented state readbacks after each operation."""
    locations = session.call("node_locations")
    project_file.parent.mkdir(parents=True, exist_ok=True)
    session.call("save_as", path=project_file.as_posix())
    saved = session.wait_ready()
    if saved.file_path is None or Path(saved.file_path).resolve() != project_file.resolve():
        raise RecorderError(f"project was not saved to {project_file}")
    outputs = state_readbacks("save", saved)
    session.call("close_project")
    outputs += state_readbacks("close", session.wait_closed())
    session.call("open_project", path=project_file.as_posix())
    outputs += state_readbacks("open", session.wait_ready())
    session.call("rebind_nodes", locations=locations)
    return outputs


def check_job(job: ProbeJob) -> None:
    """Recipe A unchanged under the F context golden's identity; no export or lifecycle golden."""
    if (
        job.tier != "0"
        or job.golden_id != control.GOLDEN_ID
        or job.lifecycle
        or job.exports
        or hashlib.sha256(typed(job.manifest["instruction_sequence"])).hexdigest()
        != A_RECIPE_SHA256
    ):
        raise RecorderError("not the F context golden of the unchanged recipe A")


def record_filter_context_golden(
    session: PainterSession,
    job: ProbeJob,
    work: Path,
    inbox: Path,
    now: Now = utc_now,
    *,
    record_prefix: str = "",
) -> Path:
    """Record the golden and write it to the inbox; returns the run directory. The session must
    load the F context extension when it connects (`FContextSession`)."""
    check_job(job)
    identity = session.connect()
    require_colour_management(job, identity)
    if any(
        "resource_url" in step.args or step.args.get("require_unique") is True
        for step in job.state_steps
    ):
        session.wait_catalog_ready()
    directory = run_directory(job, identity, work, now)
    staged = stage_inputs(job.inputs, directory / "inputs")
    preflight(session, job)

    def before(round_index: int) -> Callable[[ProbeStep], list[Output]]:
        def hook(step: ProbeStep) -> list[Output]:
            return context_outputs(session, f"pre16-r{round_index}") if step.step == 16 else []

        return hook

    try:
        session.call("probe_reset", root=directory.as_posix())
        defaults, outcomes = apply_state(
            session,
            job,
            staged,
            directory / "r1" / "work-files",
            after_create=lambda ready: [
                *state_readbacks("create", ready),
                *context_outputs(session, "after-create"),
            ],
            after_setup=lambda: context_outputs(session, "after-setup6"),
        )
        locations = session.call("probe_locations")
        uids = {step: int(where["uid"]) for step, where in locations.items()}
        first, first_blobs = record_probes(
            session,
            job,
            identity,
            directory / "r1",
            "r1",
            "same_session",
            uids,
            outcomes,
            now,
            staged,
            before_step=before(1),
        )
        session.wait_ready()
        locations = session.call("probe_locations")
        lifecycle = save_close_reopen(session, directory / "project" / "probe.spp")
        if any("resource_url" in step.args for step in job.state_steps):
            session.wait_catalog_ready()
        found = session.call("probe_rebind", locations=locations)
        rebind = readback("identity/reopen", GET_NODE_BY_UID, {}, {"value": found})
        second, second_blobs = record_probes(
            session,
            job,
            identity,
            directory / "r2",
            "r2",
            "after_save_reopen",
            uids,
            [*lifecycle, rebind, *context_outputs(session, "after-reopen")],
            now,
            staged,
            before_step=before(2),
        )
    except BaseException as error:
        failures = finish_probe(session)
        if failures and isinstance(error, RecorderError):
            raise CleanupFailed(f"{error}; {cleanup_refusal(failures)}") from error
        if failures:
            error.add_note(cleanup_refusal(failures))
        raise
    failures = finish_probe(session)
    if failures:
        raise CleanupFailed(cleanup_refusal(failures))
    key = golden_key(job, identity, defaults, defaults["colour_management"])
    record = private_record(job, key, [first, second])
    return write_run(
        inbox,
        record,
        first_blobs + second_blobs,
        job.manifest,
        identity.session_id,
        environment=identity.environment,
        record_prefix=record_prefix,
    )


def _phase_getters(phase: str) -> tuple[str, ...]:
    """The documented getters a phase records, in the recorder's call order; after the close
    the poll calls only `is_open` and `is_busy`."""
    return ("is_open", "is_busy") if phase == "close" else STATE_GETTERS


def _postcondition(phase: str, values: dict[str, Any], saved_path: Any) -> None:
    if phase == "close":
        ok = values["is_open"] is False
    else:
        ok = values["is_open"] is True and values["is_in_edition_state"] is True
        ok = ok and values["is_busy"] is False
        if phase == "save":
            ok = ok and type(values["file_path"]) is str and bool(values["file_path"])
        if phase == "open":
            ok = ok and values["file_path"] == saved_path
    if not ok:
        raise ContextRefused(f"{phase} did not reach its documented state")


def _readback(output: dict[str, Any], call: str, args: dict[str, Any], what: str) -> None:
    """An exact recorder readback: api_readback of `call` with `args`, not raised."""
    if (
        output.get("kind") != "api_readback"
        or output.get("call") != call
        or typed(output.get("args")) != typed(args)
        or "raised" in output
    ):
        raise ContextRefused(f"{what} differs from the recorder's")


def f_evidence_from_record(record: dict[str, Any], recipe: dict[str, Any]) -> FContextEvidence:
    """The F trace and context frames rebuilt from the record's ordered outputs, then checked
    against the unchanged recipe A. Every output must be an operation of A, a context leaf, one
    contiguous lifecycle phase in the recorder's getter order, or one of the exact additions the
    probe recorder makes for this job (the template capture first, then identity/s3 and
    identity/s6 before the probe steps, and the reopen rebind); anything else is refused."""
    if record.get("golden_id") != control.GOLDEN_ID:
        raise ContextRefused("not the F context golden")
    key = record["key"]["instruction_sequence_sha256"]
    if key != hashlib.sha256(canonical_json(recipe)).hexdigest():
        raise ContextRefused("record key is not recipe A")
    recordings = record["recordings"]
    if [r["condition"] for r in recordings] != ["same_session", "after_save_reopen"]:
        raise ContextRefused("F needs one same-session and one reopened recording")
    steps = {step["step"]: step for step in recipe["steps"]}
    trace: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    phases: dict[str, dict[str, Any]] = {}

    def close(phase: str | None) -> None:
        if phase is not None and tuple(phases[phase]) != _phase_getters(phase):
            raise ContextRefused(f"lifecycle phase {phase} is not its contiguous ordered readbacks")

    for recording in recordings:
        condition = recording["condition"]
        outputs = recording["outputs"]
        if not outputs or outputs[0].get("output_id") != TEMPLATE_ID:
            raise ContextRefused("a recording does not start with its template capture")
        if outputs[0].get("kind") != "template_capture":
            raise ContextRefused("the template capture differs from the recorder's")
        frame: dict[str, Any] | None = None
        phase: str | None = None
        identities: list[str] = []
        probed = False
        for output in outputs[1:]:
            oid = output["output_id"]
            lifecycle = LIFECYCLE_ID.fullmatch(oid)
            if phase is not None and not (lifecycle and lifecycle.group(1) == phase):
                close(phase)
                phase = None
            context = CONTEXT_ID.fullmatch(oid)
            if context:
                if frame is None or frame["boundary"] != context.group(1):
                    frame = {
                        "schema": SCHEMA,
                        "boundary": context.group(1),
                        "condition": condition,
                        "outputs": [],
                    }
                    frames.append(frame)
                    trace.append({"kind": "context", "boundary": context.group(1)})
                frame["outputs"].append(output)
                continue
            frame = None
            if oid == TEMPLATE_ID:
                raise ContextRefused("the template capture differs from the recorder's")
            if oid.startswith("identity/s"):
                step_id = oid[len("identity/s") :]
                _readback(output, GET_NODE_BY_UID, {"node_step": int(step_id)}, "identity readback")
                if (
                    step_id not in IDENTITY_STEPS
                    or step_id in identities
                    or probed
                    or typed(output["value"]) != typed(IDENTITY_VALUE)
                ):
                    raise ContextRefused("identity readback differs from the recorder's")
                identities.append(step_id)
                continue
            if lifecycle:
                name, getter = lifecycle.groups()
                _readback(output, PROJECT + getter, {}, "lifecycle readback")
                if phase is None:
                    if name in phases:
                        raise ContextRefused(f"lifecycle phase {name} is not contiguous")
                    if name == "create":
                        if condition != "same_session":
                            raise ContextRefused("project creation outside the first round")
                        event = {
                            "kind": "step",
                            "condition": condition,
                            "step": 1,
                            "call": steps[1]["call"],
                            "args": steps[1]["args"],
                        }
                    else:
                        event = {"kind": name}
                    # The call's own value (documented None) is not transported; the event
                    # exists only with its documented postcondition readbacks, checked below.
                    event["outcome"] = {"value": None}
                    trace.append(event)
                    phases[name] = {}
                    phase = name
                if getter in phases[name]:
                    raise ContextRefused(f"lifecycle phase {name} repeats a readback")
                phases[name][getter] = output["value"]
                continue
            if oid == REBIND_ID:
                _readback(output, GET_NODE_BY_UID, {}, "rebind readback")
                if typed(output["value"]) != typed(REBIND_VALUE):
                    raise ContextRefused("rebind readback differs from the recorder's")
                trace.append({"kind": "rebind", "outcome": {"value": output["value"]}})
                continue
            step = STEP_ID.fullmatch(oid)
            number = int(step.group(1)) if step else 0
            if (
                step is None
                or number not in steps
                or number == 1
                or step.group(2) != steps[number]["call"].rsplit(".", 1)[1]
                or output.get("kind") != "api_readback"
            ):
                raise ContextRefused("unknown recorded operation")
            # The recorder strips its scheduling flags from the arguments it runs and records;
            # every other argument must be the recipe's, which the trace then names.
            authored = steps[number]
            executed = {
                k: v for k, v in authored["args"].items() if k not in (PROBE_FLAG, WAIT_FLAG)
            }
            if output["call"] != authored["call"] or typed(output["args"]) != typed(executed):
                raise ContextRefused("recorded operation differs from recipe A")
            probed = probed or number >= 7
            outcome = {"value": output["value"]}
            if "raised" in output:
                outcome["raised"] = output["raised"]
            trace.append(
                {
                    "kind": "step",
                    "condition": condition,
                    "step": number,
                    "call": authored["call"],
                    "args": authored["args"],
                    "outcome": outcome,
                }
            )
        close(phase)
        if identities != list(IDENTITY_STEPS):
            raise ContextRefused("identity readbacks differ from the recorder's")
    if set(phases) != set(PHASES):
        raise ContextRefused("creation or reopen readbacks missing")
    saved = phases["save"]["file_path"]
    for name in PHASES:
        _postcondition(name, phases[name], saved)
    return validate_context_sequence(recipe, trace, frames)


def check_capture(run: Path) -> dict[str, Any]:
    """Completion only, never the F domain or the effective settings: READY last; a schema-valid
    private record of the F context golden with exactly the two rounds r1 (same_session) and r2
    (after_save_reopen); its key, and the run's schema-valid public manifest, both naming recipe
    A unchanged (the manifest is the authored request but for its software build and private
    records); and the manifest's receipt naming the record and every blob of the run by hash and
    size."""
    if not (run / READY_FILE).is_file():
        raise RecorderError("run is not READY")
    record_bytes = (run / RECORD_FILE).read_bytes()
    record = json.loads(record_bytes)
    problems = record_problems(record)
    if problems:
        raise RecorderError(f"private record invalid: {problems}")
    rounds = [(r["recording_id"], r["condition"]) for r in record["recordings"]]
    if record["golden_id"] != control.GOLDEN_ID or rounds != [
        ("r1", "same_session"),
        ("r2", "after_save_reopen"),
    ]:
        raise RecorderError("not the two rounds of the F context golden")
    authored = control.request()
    recipe_key = hashlib.sha256(canonical_json(authored["instruction_sequence"])).hexdigest()
    if record["key"]["instruction_sequence_sha256"] != recipe_key:
        raise RecorderError("record key is not recipe A")
    manifest = json.loads((run / MANIFEST_FILE).read_bytes())
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"public manifest invalid: {problems}")

    def comparable(document: dict[str, Any]) -> dict[str, Any]:
        rest = {k: v for k, v in document.items() if k not in ("private_records", "software")}
        return {
            **rest,
            "painter": {k: v for k, v in document["software"].items() if k != "painter"},
        }

    if (
        canonical_json(comparable(manifest)) != canonical_json(comparable(authored))
        or manifest["software"]["painter"] != record["key"]["painter_build"]
    ):
        raise RecorderError("run manifest is not the authored recipe A request")
    digest = hashlib.sha256(record_bytes).hexdigest()
    refs = manifest["private_records"]
    records = [r for r in refs if r["kind"] == "private_oracle_record"]
    if len(records) != 1 or (records[0]["sha256"], records[0]["size_bytes"]) != (
        digest,
        len(record_bytes),
    ):
        raise RecorderError("run does not name its F context record")
    for ref in refs:
        if ref is records[0]:
            continue
        blob = run / "blobs" / ref["sha256"]
        # A missing blob refuses even when its receipt names the empty content.
        if not blob.is_file():
            raise RecorderError("run blob differs from its receipt")
        data = blob.read_bytes()
        if (hashlib.sha256(data).hexdigest(), len(data)) != (ref["sha256"], ref["size_bytes"]):
            raise RecorderError("run blob differs from its receipt")
    return {"golden_id": record["golden_id"], "record_sha256": digest, "recordings": len(rounds)}


class FContextPolicy(CapabilityPolicy):
    """The Raw owned-capture path (lock, owned launch, guards, cleanup) recording the F golden."""

    schema = "uzpainter/filter-context-capture/1"
    task = "Claude/F: one recipe A capture with read-only context boundaries"

    def prepare(self, request: Request) -> ProbeJob:
        ownership.require(request.state == control.NAME, "unknown F capture")
        manifest = json.loads(request.manifest.read_bytes())
        ownership.require(
            canonical_json(manifest) == canonical_json(control.request()),
            "authored request differs",
        )
        job = probe_job_from_manifest(manifest)
        check_job(job)
        ownership.require(request.painter_exe.is_file(), "Painter executable unavailable")
        return job

    def authorize(self, request: Request, job: ProbeJob, evidence: Any) -> dict[str, Any]:
        ownership.require(not job.exports, "no export in the F context golden")
        return {}

    def ready(self, job: ProbeJob, run: Path, manifest: dict[str, Any]) -> None:
        check_capture(run)

    def session(self, owned: GuardedTransport, build_id: str) -> RawSession:
        return FContextSession.attached(owned, build_id)

    def record(self, session: RawSession, job: ProbeJob, work: Path, inbox: Path) -> Path:
        return record_filter_context_golden(session, job, work, inbox)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--painter-exe", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_owned_capture(
            Request(control.NAME, args.manifest, args.painter_exe, args.output_prefix),
            FContextPolicy(),
        )
    except Exception:
        result = {"status": "refused"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
