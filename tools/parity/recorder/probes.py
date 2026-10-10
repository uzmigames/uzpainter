r"""Tier 0 API probe goldens (`phase0.6_tier0-api-probes`; operator guide `parity/RECORDER.md` §8).

    python -m tools.parity.recorder.probes record <manifest.json>

A probe golden observes Painter's documented API black-box: set->get readback through a freshly
resolved handle and after save/reopen, the mask-stack `None` rules, the active-channel reset,
`set_source(None, ...)` on a multichannel fill, the `insert_*` position rules and the lifecycle
event order. Its public manifest (`golden-public.json`) holds the UzmiGames instruction sequence:

1. `project.create`, then **state steps**, applied once; each outcome (the returned value or the
   exception Painter raised) is recorded in the first recording, and every inserted node's
   effective defaults go into the golden key.
2. **Probe steps**: every readback, and every edit marked `probe: true` (calls whose outcome,
   usually a documented error, is the observation). They run again in every recording.
3. Optional `export_project_textures` captures (as for texture goldens).

Recording `r1` (`same_session`) runs the probes in the session that built the state; the project
is then saved, closed and reopened, the nodes are found again at their recorded places, and
recording `r2` (`after_save_reopen`) runs the probes again. Node handles are resolved freshly
through `layerstack.get_node_by_uid` for every call, and each recording says whether every node
kept its uid.

The lifecycle golden (first step `event.Dispatcher.connect`) instead runs create -> save_as ->
close (`same_session`) and open -> save -> close (`after_save_reopen`) twice, recording the events
dispatched in each phase and the readiness states polled meanwhile.

Records go to the private oracle inbox exactly like texture goldens (`output.py`).
"""

from __future__ import annotations

import argparse
import ast
import base64
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import (
    EXPORT,
    ExportStep,
    Step,
    canonical_json,
    export_step,
    sha256_bytes,
    sha256_file,
)
from tools.parity.recorder.output import (
    ensure_outside_repository,
    inbox_root,
    run_name,
    work_root,
    write_run,
)
from tools.parity.recorder.provenance import documented_symbols
from tools.parity.recorder.session import (
    REMOTE_HOST,
    REMOTE_PORT,
    HttpTransport,
    PainterIdentity,
    PainterSession,
    ProjectState,
    RecorderError,
)
from tools.parity.recorder.texture import (
    Now,
    close_quietly,
    export_outputs,
    save_and_reopen,
    utc_now,
)
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors

PAINTER_PROBES = Path(__file__).with_name("painter_probes.py")
PROBE_FLAG = "probe"


@cache
def probe_constants() -> dict[str, Any]:
    """Literal top-level constants of `painter_probes.py` (it runs only inside Painter)."""
    tree = ast.parse(PAINTER_PROBES.read_text(encoding="utf-8"))
    constants: dict[str, Any] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.isupper()
        ):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return constants


CONSTANTS = probe_constants()
EDIT_CALLS: frozenset[str] = frozenset(CONSTANTS["EDIT_CALLS"])
GETTER_CALLS: frozenset[str] = frozenset(CONSTANTS["GETTER_CALLS"])
INSERT_CALLS: frozenset[str] = frozenset(CONSTANTS["INSERT_CALLS"])
VALUE_ARGS: dict[str, str] = CONSTANTS["VALUE_ARGS"]
IMPORT_RESOURCE: str = CONSTANTS["IMPORT_RESOURCE"]
EVENT_CONNECT: str = CONSTANTS["EVENT_CONNECT"]
PROJECT_SAVE_AS: str = CONSTANTS["PROJECT_SAVE_AS"]
PROJECT_SAVE: str = CONSTANTS["PROJECT_SAVE"]
PROJECT_CLOSE: str = CONSTANTS["PROJECT_CLOSE"]
PROJECT_OPEN: str = CONSTANTS["PROJECT_OPEN"]
PROJECT_STATE: str = CONSTANTS["PROJECT_STATE"]
GET_NODE_BY_UID = "substance_painter.layerstack.get_node_by_uid"

# Step arguments naming an input by input_id; the recorder passes the staged file's path.
INPUT_ARGS = {ps.CREATE: "mesh", IMPORT_RESOURCE: "image"}

# The lifecycle procedure, step by step (after `event.Dispatcher.connect`).
LIFECYCLE_STEPS = (
    EVENT_CONNECT,
    ps.CREATE,
    PROJECT_SAVE_AS,
    PROJECT_CLOSE,
    PROJECT_OPEN,
    PROJECT_SAVE,
    PROJECT_CLOSE,
)

# Polls taken after a lifecycle phase reached its end state, so late events are captured too.
SETTLE_POLLS = 3


def is_read(call: str, args: dict[str, Any]) -> bool:
    if call in VALUE_ARGS:
        return VALUE_ARGS[call] not in args
    return call in GETTER_CALLS


@dataclass(frozen=True)
class ProbeStep:
    step: int
    call: str
    args: dict[str, Any]
    probe: bool

    @property
    def output_id(self) -> str:
        return f"s{self.step}/{self.call.rsplit('.', 1)[1]}"


@dataclass(frozen=True)
class ProbeJob:
    manifest: dict[str, Any]
    inputs: dict[str, Path]
    create: Step
    state_steps: tuple[ProbeStep, ...]
    probe_steps: tuple[ProbeStep, ...]
    exports: tuple[ExportStep, ...]
    events: tuple[str, ...]

    @property
    def lifecycle(self) -> bool:
        return bool(self.events)

    @property
    def golden_id(self) -> str:
        return str(self.manifest["golden_id"])

    @property
    def tier(self) -> str:
        return str(self.manifest["tier"])

    @property
    def instruction_sequence_sha256(self) -> str:
        return sha256_bytes(canonical_json(self.manifest["instruction_sequence"]))

    def input_hashes(self) -> list[dict[str, str]]:
        return [{"input_id": i["input_id"], "sha256": i["sha256"]} for i in self.manifest["inputs"]]

    def project_settings(self) -> dict[str, Any]:
        return {k: v for k, v in self.create.args.items() if k != "mesh"}


def checked_inputs(manifest: dict[str, Any], repo_root: Path) -> dict[str, Path]:
    inputs: dict[str, Path] = {}
    for item in manifest["inputs"]:
        if "path" not in item:
            continue
        file = repo_root / item["path"]
        if not file.is_file():
            raise RecorderError(f"input {item['input_id']}: {item['path']} does not exist")
        actual = sha256_file(file)
        if actual != item["sha256"]:
            raise RecorderError(
                f"input {item['input_id']}: sha256 {actual} differs from the manifest"
            )
        inputs[item["input_id"]] = file
    return inputs


def check_input_arg(step: Step, inputs: dict[str, Path]) -> None:
    key = INPUT_ARGS.get(step.call)
    if key is not None and step.args.get(key) not in inputs:
        raise RecorderError(f"step {step.step}: `{key}` must name an input with a path")


def lifecycle_job(manifest: dict[str, Any], inputs: dict[str, Path], steps: list[Step]) -> ProbeJob:
    if tuple(s.call for s in steps) != LIFECYCLE_STEPS:
        raise RecorderError(f"a lifecycle probe must be exactly the steps {list(LIFECYCLE_STEPS)}")
    events = steps[0].args.get("events")
    if not isinstance(events, list) or not events or not all(isinstance(e, str) for e in events):
        raise RecorderError("step 1: `events` must list the event class names to connect")
    check_input_arg(steps[1], inputs)
    return ProbeJob(manifest, inputs, steps[1], (), (), (), tuple(events))


def probe_job_from_manifest(manifest: dict[str, Any], repo_root: Path = REPO_ROOT) -> ProbeJob:
    inputs = checked_inputs(manifest, repo_root)
    steps = [
        Step(s["step"], s["call"], dict(s.get("args", {})))
        for s in manifest["instruction_sequence"]["steps"]
    ]
    if [s.step for s in steps] != list(range(1, len(steps) + 1)):
        raise RecorderError("instruction steps must be numbered 1..n in order")
    if steps and steps[0].call == EVENT_CONNECT:
        return lifecycle_job(manifest, inputs, steps)
    if not steps or steps[0].call != ps.CREATE:
        raise RecorderError("the instruction sequence must start with project.create")
    check_input_arg(steps[0], inputs)
    state: list[ProbeStep] = []
    probes: list[ProbeStep] = []
    exports: list[ExportStep] = []
    for step in steps[1:]:
        if step.call == EXPORT:
            exports.append(export_step(step))
            continue
        if exports:
            raise RecorderError(f"step {step.step}: probe steps must precede the captures")
        if step.call not in EDIT_CALLS | GETTER_CALLS:
            raise RecorderError(f"step {step.step}: {step.call} is not in the probe vocabulary")
        flag = step.args.pop(PROBE_FLAG, False)
        if not isinstance(flag, bool):
            raise RecorderError(f"step {step.step}: `{PROBE_FLAG}` must be true or false")
        check_input_arg(step, inputs)
        probe = flag or is_read(step.call, step.args)
        if probe and step.call in INPUT_ARGS:
            raise RecorderError(f"step {step.step}: an import cannot be a probe step")
        if not probe and probes:
            raise RecorderError(f"step {step.step}: state steps must precede the probe steps")
        (probes if probe else state).append(ProbeStep(step.step, step.call, step.args, probe))
    if not probes:
        raise RecorderError("a probe golden needs at least one probe step")
    return ProbeJob(manifest, inputs, steps[0], tuple(state), tuple(probes), tuple(exports), ())


def load_probe_job(path: Path, repo_root: Path = REPO_ROOT) -> ProbeJob:
    manifest = load_json(path)
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"{path}: not a valid public manifest: {problems}")
    return probe_job_from_manifest(manifest, repo_root)


def manifest_symbol_problems(manifest: dict[str, Any]) -> list[str]:
    """Calls of an instruction sequence that are not documented symbols the recorder lists."""
    known = documented_symbols()
    return [
        f"step {s['step']}: {s['call']} is not in documented_symbols.json"
        for s in manifest["instruction_sequence"]["steps"]
        if s["call"] not in known
    ]


def extension_code(source: str) -> str:
    """Statements that execute `painter_probes.py` into a copy of the recorder's namespace.

    The copy shares `painter_side.py`'s objects (its `OPERATIONS` dictionary included, where the
    probe operations register), but names the probes define never replace `painter_side.py`'s.
    """
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return (
        "import base64\n"
        "uzp_probes = dict(uzp_recorder)\n"
        f"exec(base64.b64decode('{encoded}').decode('utf-8'), uzp_probes)\n"
    )


class ProbeSession(PainterSession):
    """A recorder session with the probe operations loaded next to `painter_side.py`."""

    def connect(self) -> PainterIdentity:
        identity = super().connect()
        self.transport.run(extension_code(PAINTER_PROBES.read_text(encoding="utf-8")))
        return identity


def stage_inputs(inputs: dict[str, Path], directory: Path) -> dict[str, Path]:
    """Copy the inputs next to the throwaway project so Painter never reads the repository."""
    directory.mkdir(parents=True)
    staged: dict[str, Path] = {}
    for input_id, source in inputs.items():
        target = directory / f"{input_id}{source.suffix}"
        shutil.copyfile(source, target)
        staged[input_id] = target
    return staged


def readback(
    output_id: str, call: str, args: dict[str, Any], outcome: dict[str, Any]
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "output_id": output_id,
        "kind": "api_readback",
        "call": call,
        "args": args,
        "value": outcome.get("value"),
    }
    if "raised" in outcome:
        output["raised"] = outcome["raised"]
    return output


def run_step(session: PainterSession, step: ProbeStep, staged: dict[str, Path]) -> dict[str, Any]:
    resolved: dict[str, str] = {}
    key = INPUT_ARGS.get(step.call)
    if key is not None:
        resolved[key] = staged[step.args[key]].as_posix()
    outcome: dict[str, Any] = session.call(
        "probe_step", step=step.step, call=step.call, args=step.args, resolved=resolved
    )
    return outcome


def create_project(session: PainterSession, job: ProbeJob, staged: dict[str, Path]) -> Any:
    return session.call(
        "apply_step",
        step=job.create.step,
        call=job.create.call,
        args=job.create.args,
        resolved={"mesh": staged[job.create.args["mesh"]].as_posix()},
    )


def apply_state(
    session: PainterSession, job: ProbeJob, staged: dict[str, Path]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Create the project and apply the state steps once; returns defaults and step outcomes."""
    created = create_project(session, job, staged)
    session.wait_ready()
    defaults: dict[str, Any] = {
        "project.create": session.call("template_capture"),
        "colour_management": created["colour_management"],
        "inserted": {},
    }
    outcomes: list[dict[str, Any]] = []
    for step in job.state_steps:
        outcome = run_step(session, step, staged)
        if "defaults" in outcome:
            defaults["inserted"][str(step.step)] = outcome["defaults"]
        outcomes.append(readback(step.output_id, step.call, step.args, outcome))
    session.wait_ready()
    return defaults, outcomes


def identity_outputs(session: PainterSession, uids: dict[str, int]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for step, uid in sorted(uids.items(), key=lambda item: int(item[0])):
        value = session.call("probe_identity", node_step=int(step), recorded_uid=uid)
        outputs.append(
            readback(
                f"identity/s{step}", GET_NODE_BY_UID, {"node_step": int(step)}, {"value": value}
            )
        )
    return outputs


def record_probes(
    session: PainterSession,
    job: ProbeJob,
    identity: PainterIdentity,
    directory: Path,
    recording_id: str,
    condition: str,
    uids: dict[str, int],
    first_outputs: list[dict[str, Any]],
    now: Now,
) -> tuple[dict[str, Any], list[Path]]:
    session.wait_ready()
    template = session.call("template_capture")
    outputs: list[dict[str, Any]] = [
        {
            "output_id": "template/texture-sets",
            "kind": "template_capture",
            "subject": "texture sets, stacks and channel formats of the project",
            "values": template,
        },
        *first_outputs,
        *identity_outputs(session, uids),
    ]
    for step in job.probe_steps:
        outputs.append(readback(step.output_id, step.call, step.args, run_step(session, step, {})))
    blobs: list[Path] = []
    for export in job.exports:
        exported, files = export_outputs(session, export, template, directory)
        outputs += exported
        blobs += files
    recording = {
        "recording_id": recording_id,
        "condition": condition,
        "session_id": identity.session_id,
        "recorded_at": now().isoformat(),
        "outputs": outputs,
    }
    return recording, blobs


def golden_key(
    job: ProbeJob, identity: PainterIdentity, defaults: dict[str, Any], colour: Any
) -> dict[str, Any]:
    return {
        "inputs": job.input_hashes(),
        "instruction_sequence_sha256": job.instruction_sequence_sha256,
        "effective_defaults": defaults,
        "painter_build": identity.painter_build(),
        "project_settings": {"create": job.project_settings(), "colour_management": colour},
        "resource_hashes": [],
        "bake_backend": None,
        "render_state": None,
    }


def private_record(job: ProbeJob, key: dict[str, Any], recordings: list[Any]) -> dict[str, Any]:
    return {
        "schema": "uzpainter/parity/golden-private/1",
        "record_class": "private_oracle_record",
        "golden_id": job.golden_id,
        "tier": job.tier,
        "key": key,
        "recordings": recordings,
    }


def run_directory(job: ProbeJob, identity: PainterIdentity, work: Path, now: Now) -> Path:
    directory = ensure_outside_repository(work) / job.golden_id.replace("/", "__")
    return directory / run_name(identity.session_id, now())


def record_api_probe(
    session: PainterSession, job: ProbeJob, work: Path, inbox: Path, now: Now
) -> Path:
    identity = session.connect()
    directory = run_directory(job, identity, work, now)
    staged = stage_inputs(job.inputs, directory / "inputs")
    try:
        session.call("probe_reset")
        defaults, outcomes = apply_state(session, job, staged)
        locations = session.call("probe_locations")
        uids = {step: int(where["uid"]) for step, where in locations.items()}
        first, first_blobs = record_probes(
            session, job, identity, directory / "r1", "r1", "same_session", uids, outcomes, now
        )
        session.wait_ready()
        locations = session.call("probe_locations")
        save_and_reopen(session, directory / "project" / "probe.spp")
        found = session.call("probe_rebind", locations=locations)
        rebind = readback("identity/reopen", GET_NODE_BY_UID, {}, {"value": found})
        second, second_blobs = record_probes(
            session, job, identity, directory / "r2", "r2", "after_save_reopen", uids, [rebind], now
        )
    finally:
        close_quietly(session)
    key = golden_key(job, identity, defaults, defaults["colour_management"])
    record = private_record(job, key, [first, second])
    return write_run(inbox, record, first_blobs + second_blobs, job.manifest, identity.session_id)


def state_entry(state: ProjectState) -> dict[str, bool]:
    return {"is_open": state.is_open, "in_edition": state.in_edition, "busy": state.busy}


def lifecycle_phase(
    session: PainterSession,
    name: str,
    action: Callable[[], Any],
    done: Callable[[ProjectState], bool],
    timeout_s: float = 600.0,
) -> list[dict[str, Any]]:
    """Run one lifecycle call; record the events it dispatched and the states polled meanwhile."""
    session.call("events_take")
    action()
    states: list[dict[str, bool]] = []

    def note(state: ProjectState) -> ProjectState:
        entry = state_entry(state)
        if not states or states[-1] != entry:
            states.append(entry)
        return state

    deadline = session.monotonic() + timeout_s
    while not done(note(session.state())):
        if session.monotonic() >= deadline:
            raise RecorderError(f"lifecycle phase {name}: timed out after {timeout_s:.0f} s")
        session.sleep(session.poll_interval_s)
    for _ in range(SETTLE_POLLS):
        session.sleep(session.poll_interval_s)
        note(session.state())
    events = session.call("events_take")["events"]
    args = {"phase": name}
    return [
        readback(f"{name}/events", EVENT_CONNECT, args, {"value": events}),
        readback(f"{name}/states", PROJECT_STATE, args, {"value": states}),
    ]


def lifecycle_recordings(
    session: PainterSession,
    job: ProbeJob,
    identity: PainterIdentity,
    staged: dict[str, Path],
    project_file: Path,
    cycle: int,
    now: Now,
) -> list[dict[str, Any]]:
    """One cycle: create -> save_as -> close, then open -> save -> close."""
    path = project_file.as_posix()

    def saved_to_file(state: ProjectState) -> bool:
        return (
            state.ready
            and state.file_path is not None
            and Path(state.file_path).resolve() == project_file.resolve()
        )

    def closed(state: ProjectState) -> bool:
        return not state.is_open

    def ready(state: ProjectState) -> bool:
        return state.ready

    project_file.parent.mkdir(parents=True)
    created = [
        *lifecycle_phase(session, "create", lambda: create_project(session, job, staged), ready),
        *lifecycle_phase(
            session, "save_as", lambda: session.call("save_as", path=path), saved_to_file
        ),
        *lifecycle_phase(session, "close", lambda: session.call("close_project"), closed),
    ]
    reopened = [
        *lifecycle_phase(session, "open", lambda: session.call("open_project", path=path), ready),
        *lifecycle_phase(session, "save", lambda: session.call("project_save"), saved_to_file),
        *lifecycle_phase(session, "close", lambda: session.call("close_project"), closed),
    ]
    return [
        {
            "recording_id": f"r{2 * cycle - 1}",
            "condition": "same_session",
            "session_id": identity.session_id,
            "recorded_at": now().isoformat(),
            "outputs": created,
        },
        {
            "recording_id": f"r{2 * cycle}",
            "condition": "after_save_reopen",
            "session_id": identity.session_id,
            "recorded_at": now().isoformat(),
            "outputs": reopened,
        },
    ]


def record_lifecycle(
    session: PainterSession, job: ProbeJob, work: Path, inbox: Path, now: Now
) -> Path:
    identity = session.connect()
    directory = run_directory(job, identity, work, now)
    staged = stage_inputs(job.inputs, directory / "inputs")
    recordings: list[dict[str, Any]] = []
    try:
        session.call("events_connect", events=list(job.events))
        for cycle in (1, 2):
            project_file = directory / f"cycle{cycle}" / "lifecycle.spp"
            recordings += lifecycle_recordings(
                session, job, identity, staged, project_file, cycle, now
            )
    finally:
        try:
            session.call("events_disconnect")
        finally:
            close_quietly(session)
    defaults = {"events_connected": list(job.events)}
    key = golden_key(job, identity, defaults, identity.colour_management)
    record = private_record(job, key, recordings)
    return write_run(inbox, record, [], job.manifest, identity.session_id)


def record_probe_golden(
    session: PainterSession, job: ProbeJob, work: Path, inbox: Path, now: Now = utc_now
) -> Path:
    """Record one API-probe golden and write it to the inbox; returns the run directory."""
    if job.tier != "0":
        raise RecorderError("API probes are Tier 0 goldens")
    if job.lifecycle:
        return record_lifecycle(session, job, work, inbox, now)
    return record_api_probe(session, job, work, inbox, now)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.recorder.probes")
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record")
    record.add_argument("manifest", type=Path)
    record.add_argument("--host", default=REMOTE_HOST)
    record.add_argument("--port", type=int, default=REMOTE_PORT)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        job = load_probe_job(args.manifest)
        session = ProbeSession(HttpTransport(args.host, args.port))
        run = record_probe_golden(session, job, work_root(), inbox_root())
    except RecorderError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    print(f"recorded: {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
