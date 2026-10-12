"""Tier 0 defaults and template captures (task `phase0.6_tier0-defaults-templates`).

Baking defaults (`06-baking.md` §2): on a fresh project (mesh only, every project setting left
to Painter), each capture step of the job reads, on every texture set,
`BakingParameters.common()` or `baker(usage)` with every documented `properties.Property` getter
of every key (value, name, short name, label, widget type, enum values, the enum value of each
enum label, meta properties), or one of the documented baking state getters. Recordings:
`r1` same session, `r2` after save and reopen, `r3` on a second fresh project in the same
session.

Project templates (`03-project-model.md` §2): the shipped templates are the `.spt` files of the
documented application shelf (`resource.Shelves.application_shelf`), named by their
shelf-relative path; the recorder lists the names only. The job creates one project per template
with `project.create(template_file_path=...)` and no other setting, and records each texture
set's stacks, channels and `ChannelFormat` (`r1`), then again after save and reopen (`r2`). The
template list the job names must equal the shipped list, so every shipped template is captured.

Every capture is a private oracle record; only its hash reaches the public manifest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import Job, Step
from tools.parity.recorder.output import ensure_outside_repository, run_name, write_run
from tools.parity.recorder.session import (
    PainterCallError,
    PainterIdentity,
    PainterSession,
    RecorderError,
)
from tools.parity.recorder.texture import (
    Now,
    close_quietly,
    output_safe,
    replay,
    save_and_reopen,
    stage_inputs,
    utc_now,
)

PARAMETER_CAPTURES = frozenset({ps.BAKING_COMMON, ps.BAKING_BAKER})
TEMPLATE_ENUMERATION_ID = "templates/shipped"


def baking_output_id(step: Step) -> str:
    if step.call == ps.BAKING_COMMON:
        return "baking/common"
    if step.call == ps.BAKING_BAKER:
        return f"baking/baker/{step.args['usage']}"
    return f"baking/{step.call.rsplit('.', 1)[1]}"


def check_baking_job(job: Job) -> None:
    """A fresh project, then `common()` and the ten bakers, each captured exactly once."""
    if len(job.state_steps) != 1 or job.state_steps[0].call != ps.CREATE:
        raise RecorderError("a baking-defaults job creates one project and changes nothing else")
    if set(job.state_steps[0].args) != {"mesh"}:
        raise RecorderError("defaults are read on a fresh project: create takes only `mesh`")
    if job.exports or job.export_probes:
        raise RecorderError("a baking-defaults job exports nothing")
    ids = [baking_output_id(step) for step in job.captures]
    if len(ids) != len(set(ids)):
        raise RecorderError(f"a capture is named twice: {sorted(ids)}")
    for step in job.captures:
        if step.call == ps.BAKING_BAKER and step.args.get("usage") not in ps.BAKER_USAGES:
            raise RecorderError(f"step {step.step}: `usage` must be one of {ps.BAKER_USAGES}")
    required = {"baking/common", *(f"baking/baker/{usage}" for usage in ps.BAKER_USAGES)}
    missing = sorted(required - set(ids))
    if missing:
        raise RecorderError(f"the job must capture every key of common() and all bakers: {missing}")


def property_problems(where: str, described: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    raised = described.get("raised", {})
    for field in ps.PROPERTY_FIELDS:
        if field not in described and field not in raised:
            problems.append(f"{where}: `{field}` neither read nor raised")
    labels = described.get("enum_values")
    if isinstance(labels, dict) and labels:
        values = described.get("enum_value", {})
        failed = {name.split("/", 1)[1] for name in raised if name.startswith("enum_value/")}
        unread = sorted(set(labels) - set(values) - failed)
        if unread:
            problems.append(f"{where}: enum_value() not read for {unread}")
    return problems


def capture_problems(output_id: str, values: dict[str, Any]) -> list[str]:
    """Completeness of one `common()` / `baker()` capture: every key described in full.

    An empty `keys()` is recorded as observed (some bakers expose no parameter), and so is an
    enumeration whose `enum_values()` is empty; labels that are returned must each have their
    `enum_value()` read, so enum integers are never inferred.
    """
    sets = values.get("texture_sets")
    if not isinstance(sets, dict) or not sets:
        return [f"{output_id}: no texture set captured"]
    problems: list[str] = []
    for name, parameters in sorted(sets.items()):
        keys, properties = parameters.get("keys"), parameters.get("properties")
        if not isinstance(keys, list) or not isinstance(properties, dict):
            problems.append(f"{output_id}/{name}: keys or properties missing")
            continue
        if set(keys) != set(properties):
            problems.append(f"{output_id}/{name}: described keys differ from keys()")
        for key in sorted(properties):
            problems += property_problems(f"{output_id}/{name}/{key}", properties[key])
    return problems


def key_sets(recording: dict[str, Any]) -> dict[str, Any]:
    return {
        output["output_id"]: {
            name: sorted(parameters["keys"])
            for name, parameters in output["values"]["texture_sets"].items()
        }
        for output in recording["outputs"]
        if output["output_id"] == "baking/common" or output["output_id"].startswith("baking/baker/")
    }


def baking_recording(
    session: PainterSession,
    job: Job,
    identity: PainterIdentity,
    recording_id: str,
    condition: str,
    now: Now,
) -> dict[str, Any]:
    session.wait_ready()
    outputs: list[dict[str, Any]] = []
    problems: list[str] = []
    for step in job.captures:
        output_id = baking_output_id(step)
        values = session.call("baking_capture", call=step.call, args=step.args)
        if step.call in PARAMETER_CAPTURES:
            problems += capture_problems(output_id, values)
        outputs.append(
            {
                "output_id": output_id,
                "kind": "effective_default_capture",
                "subject": f"{step.call} {step.args}" if step.args else step.call,
                "values": values,
            }
        )
    if problems:
        raise RecorderError(f"{recording_id}: incomplete defaults capture: {problems}")
    return {
        "recording_id": recording_id,
        "condition": condition,
        "session_id": identity.session_id,
        "recorded_at": now().isoformat(),
        "outputs": outputs,
    }


def private_record(
    job: Job,
    identity: PainterIdentity,
    defaults: dict[str, Any],
    settings: dict[str, Any],
    recordings: list[dict[str, Any]],
    note: str,
) -> dict[str, Any]:
    return {
        "schema": "uzpainter/parity/golden-private/1",
        "record_class": "private_oracle_record",
        "golden_id": job.golden_id,
        "tier": job.tier,
        "note": note,
        "key": {
            "inputs": job.input_hashes(),
            "instruction_sequence_sha256": job.instruction_sequence_sha256,
            "effective_defaults": defaults,
            "painter_build": identity.painter_build(),
            "project_settings": settings,
            "resource_hashes": [],
            "bake_backend": None,
            "render_state": None,
        },
        "recordings": recordings,
    }


def work_directory(job: Job, work: Path, identity: PainterIdentity, now: Now) -> Path:
    directory = ensure_outside_repository(work) / job.golden_id.replace("/", "__")
    return directory / run_name(identity.session_id, now())


def record_baking_defaults(
    session: PainterSession,
    job: Job,
    work: Path,
    inbox: Path,
    now: Now = utc_now,
    *,
    record_prefix: str = "",
) -> Path:
    """Record the baking defaults three times and write the golden to the inbox."""
    check_baking_job(job)
    identity = session.connect()
    directory = work_directory(job, work, identity, now)
    staged = stage_inputs(job, directory / "inputs")
    try:
        defaults = replay(session, job, staged)
        first = baking_recording(session, job, identity, "r1", "same_session", now)
        save_and_reopen(session, directory / "project" / "defaults.spp")
        second = baking_recording(session, job, identity, "r2", "after_save_reopen", now)
        session.call("close_project")
        session.wait_closed()
        replay(session, job, staged)
        third = baking_recording(session, job, identity, "r3", "same_session", now)
    finally:
        close_quietly(session)
    recordings = [first, second, third]
    expected = key_sets(first)
    for recording in recordings[1:]:
        if key_sets(recording) != expected:
            raise RecorderError(
                f"{recording['recording_id']}: baking parameter keys differ from r1; "
                "the oracle is unstable"
            )
    record = private_record(
        job,
        identity,
        defaults,
        {"create": job.project_settings(), "colour_management": defaults["colour_management"]},
        recordings,
        "r1: fresh project; r2: the same project after save and reopen; "
        "r3: a second fresh project in the same session.",
    )
    return write_run(
        inbox,
        record,
        [],
        job.manifest,
        identity.session_id,
        environment=identity.environment,
        record_prefix=record_prefix,
    )


def list_shipped_templates(session: PainterSession) -> list[str]:
    templates = session.call("shipped_templates")["templates"]
    return [str(t) for t in templates]


def check_template_job(job: Job) -> list[str]:
    """One `project.create(mesh, template)` per template; returns the template identifiers."""
    if job.exports or job.export_probes or job.captures:
        raise RecorderError("a template job only creates projects; it exports nothing")
    named: list[str] = []
    for step in job.state_steps:
        if step.call != ps.CREATE or set(step.args) != {"mesh", "template"}:
            raise RecorderError(
                f"step {step.step}: a template job is project.create with `mesh` and `template`"
            )
        named.append(str(step.args["template"]))
    if len(named) != len(set(named)):
        raise RecorderError("a template is named twice")
    ids = [template_output_id(t) for t in named]
    if len(ids) != len(set(ids)) or TEMPLATE_ENUMERATION_ID in ids:
        raise RecorderError(f"template identifiers collide as output ids: {sorted(ids)}")
    return named


def template_output_id(template: str) -> str:
    return f"templates/{output_safe(template)}"


def enumeration_output(templates: list[str]) -> dict[str, Any]:
    return {
        "output_id": TEMPLATE_ENUMERATION_ID,
        "kind": "template_capture",
        "subject": "project templates (.spt) of the application shelf",
        "values": {"templates": sorted(templates)},
    }


def template_output(template: str, values: dict[str, Any]) -> dict[str, Any]:
    return {
        "output_id": template_output_id(template),
        "kind": "template_capture",
        "subject": f"texture sets, stacks and channel formats of a project from {template}",
        "values": {"template": template, **values},
    }


def create_from_template(
    session: PainterSession, step: Step, staged: dict[str, Path]
) -> dict[str, Any]:
    """Create the project; a refusal of the documented API is recorded, not raised."""
    try:
        result = session.call(
            "apply_step",
            step=step.step,
            call=step.call,
            args=step.args,
            resolved={"mesh": staged[step.args["mesh"]].as_posix()},
        )
    except PainterCallError as error:
        close_quietly(session)
        return {"accepted": False, "raised": {"type": error.kind, "message": error.message}}
    session.wait_ready()
    return {"accepted": True, "colour_management": result["colour_management"]}


def template_pair(
    session: PainterSession, step: Step, staged: dict[str, Path], directory: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """Capture one template twice: as created, then after save and reopen (or two refusals)."""
    template = str(step.args["template"])
    created = create_from_template(session, step, staged)
    if not created["accepted"]:
        again = create_from_template(session, step, staged)
        if again["accepted"]:
            raise RecorderError(f"{template}: refused once, then accepted; the oracle is unstable")
        first = template_output(template, {"accepted": False, "raised": created["raised"]})
        second = template_output(template, {"accepted": False, "raised": again["raised"]})
        return first, second, None
    first = template_output(template, {"accepted": True, **session.call("template_capture")})
    save_and_reopen(session, directory / f"project-step{step.step}" / "template.spp")
    second = template_output(template, {"accepted": True, **session.call("template_capture")})
    session.call("close_project")
    session.wait_closed()
    return first, second, created["colour_management"]


def record_project_templates(
    session: PainterSession,
    job: Job,
    work: Path,
    inbox: Path,
    now: Now = utc_now,
    *,
    record_prefix: str = "",
) -> Path:
    """Record the channel sets and formats of every shipped template twice."""
    named = check_template_job(job)
    identity = session.connect()
    shipped = list_shipped_templates(session)
    if not shipped:
        raise RecorderError("the application shelf holds no project template")
    if set(named) != set(shipped):
        raise RecorderError(
            "the job must name exactly the shipped templates: "
            f"not in the job {sorted(set(shipped) - set(named))}, "
            f"not shipped {sorted(set(named) - set(shipped))}"
        )
    directory = work_directory(job, work, identity, now)
    staged = stage_inputs(job, directory / "inputs")
    started = now().isoformat()
    first_outputs = [enumeration_output(shipped)]
    second_outputs: list[dict[str, Any]] = []
    colour: dict[str, Any] | None = None
    try:
        for step in job.state_steps:
            first, second, management = template_pair(session, step, staged, directory)
            first_outputs.append(first)
            second_outputs.append(second)
            colour = colour or management
    finally:
        close_quietly(session)
    again = list_shipped_templates(session)
    if again != shipped:
        raise RecorderError("the shipped template list changed during the recording")
    recordings = [
        {
            "recording_id": "r1",
            "condition": "same_session",
            "session_id": identity.session_id,
            "recorded_at": started,
            "outputs": first_outputs,
        },
        {
            "recording_id": "r2",
            "condition": "after_save_reopen",
            "session_id": identity.session_id,
            "recorded_at": now().isoformat(),
            "outputs": [enumeration_output(again), *second_outputs],
        },
    ]
    record = private_record(
        job,
        identity,
        {},
        {"create": {}, "colour_management": colour},
        recordings,
        "One project per shipped template, no project setting given (template values apply); "
        "r1 as created, r2 after save and reopen.",
    )
    return write_run(
        inbox,
        record,
        [],
        job.manifest,
        identity.session_id,
        environment=identity.environment,
        record_prefix=record_prefix,
    )
