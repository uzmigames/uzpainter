r"""Tier 1 migration goldens: a UzmiGames project saved by Painter, opened, exported (decision 194).

    python -m tools.parity.recorder record-migration <manifest.json> --assets-root <Assets3D>

The manifest's `instruction_sequence.interface` is `painter_project_migration`. An approved
production asset whose state exists only as its Painter project (Tunic v10: built interactively,
with no pipeline round to replay) is recorded from that project, read through Painter's documented
API while Painter is installed (owner Q6, decision 020). There is no `.spp` reader: UzPainter never
reads the project; only Painter opens it. The job has two steps:

1. `substance_painter.project.open` with `project`, a `painter_project` input named by SHA-256 and
   `assets3d_path` (resolved there, else from the private store by its hash, decision 144);
2. `substance_painter.export.export_project_textures` with `config`, an authored `recipe_json`
   input holding the `json_config` without `exportPath` (the recorder sets a fresh private
   directory, as for an export probe).

The project is hash-checked and copied into the private work directory; Painter opens the copy, so
the original is never opened, saved or touched. Recordings: `r1` (`same_session`: open, read back,
export), `r1-repeat` (`same_session`: export again into a fresh directory) and `r2`
(`after_save_reopen`: save the copy under a new name, close, reopen it, read back, export). Each
export is verified like a texture golden's (`capture.verify_current_outputs`). Each recording reads
back, privately, the project's state (`migration_readback` in `painter_side.py`: the mesh it was
last imported from, per texture set its resolution and mesh-map resources, per stack its channel
formats and every node with its sources, blending, opacity, visibility and mask) and the template
capture. Records go to the oracle inbox like every other golden (`output.py`).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from tools.parity.recorder.job import Job, canonical_json, sha256_bytes, sha256_file
from tools.parity.recorder.output import ensure_outside_repository, run_name, write_run
from tools.parity.recorder.script_run import (
    AFTER_SAVE_REOPEN,
    ASSETS3D_LICENCE,
    R1,
    R1_REPEAT,
    R2,
    SAME_SESSION,
    ConfigExport,
    export_config,
    input_file,
    recording,
    run_config_export,
    template_output,
)
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.recorder.texture import (
    Now,
    close_quietly,
    require_colour_management,
    utc_now,
)
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors
from tools.parity.store.store import OracleStore, locate

INTERFACE = "painter_project_migration"
OPEN = "substance_painter.project.open"
EXPORT = "substance_painter.export.export_project_textures"
# The readback's documented entry point: the stack walk starts at each stack's root layer nodes.
READBACK = "substance_painter.layerstack.get_root_layer_nodes"
PROJECT_KIND = "painter_project"
CONFIG_KIND = "recipe_json"


@dataclass(frozen=True)
class MigrationJob:
    manifest: dict[str, Any]
    project_id: str
    project_sha256: str
    project_name: str
    project_file: Path
    config_id: str
    config: dict[str, Any]

    @property
    def golden_id(self) -> str:
        return str(self.manifest["golden_id"])

    def input_hashes(self) -> list[dict[str, str]]:
        return [{"input_id": i["input_id"], "sha256": i["sha256"]} for i in self.manifest["inputs"]]


def step_input(
    inputs: dict[str, dict[str, Any]], step: dict[str, Any], arg: str, kind: str
) -> dict[str, Any]:
    args = step.get("args", {})
    if set(args) != {arg}:
        raise RecorderError(f"step {step['step']}: {step['call']} takes only `{arg}`")
    item = inputs.get(str(args[arg]))
    if item is None or item["kind"] != kind:
        raise RecorderError(f"step {step['step']}: `{arg}` must name a {kind} input")
    return item


def migration_job_from_manifest(
    manifest: dict[str, Any],
    assets_root: Path,
    store: OracleStore | None = None,
    repo_root: Path = REPO_ROOT,
) -> MigrationJob:
    """The job of a migration manifest; refused before Painter is touched on any input neither
    Assets3D nor the private store holds, or any step the recorder does not know."""
    golden_id = manifest["golden_id"]
    if manifest["instruction_sequence"]["interface"] != INTERFACE:
        raise RecorderError(f"{golden_id}: the interface is not {INTERFACE}")
    if manifest["tier"] != "1":
        raise RecorderError(f"{golden_id}: migration goldens are Tier 1")
    inputs = {item["input_id"]: item for item in manifest["inputs"]}
    steps = manifest["instruction_sequence"]["steps"]
    if [(s["step"], s["call"]) for s in steps] != [(1, OPEN), (2, EXPORT)]:
        raise RecorderError(f"{golden_id}: a migration golden runs step 1 {OPEN}, step 2 {EXPORT}")
    project = step_input(inputs, steps[0], "project", PROJECT_KIND)
    config = step_input(inputs, steps[1], "config", CONFIG_KIND)
    if set(inputs) != {project["input_id"], config["input_id"]}:
        raise RecorderError(f"{golden_id}: every input is the project or the export configuration")
    if "assets3d_path" not in project or project["provenance"]["licence"] != ASSETS3D_LICENCE:
        raise RecorderError(f"input {project['input_id']}: the project is an Assets3D input")
    file = input_file(project, assets_root.resolve(), store or locate())
    return MigrationJob(
        manifest,
        project["input_id"],
        project["sha256"],
        PurePosixPath(project["assets3d_path"]).name,
        file,
        config["input_id"],
        export_config(config, repo_root),
    )


def load_migration_job(
    path: Path, assets_root: Path, store: OracleStore | None = None
) -> MigrationJob:
    manifest = load_json(path)
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"{path}: not a valid public manifest: {problems}")
    return migration_job_from_manifest(manifest, assets_root, store)


def stage_project(job: MigrationJob, directory: Path) -> Path:
    """A hash-checked private copy of the project: the one file Painter opens."""
    target = directory / "project" / job.project_name
    target.parent.mkdir(parents=True)
    shutil.copyfile(job.project_file, target)
    if sha256_file(target) != job.project_sha256:
        raise RecorderError(f"input {job.project_id}: the staged copy differs from its pin")
    return target


def state_readback(session: PainterSession) -> dict[str, Any]:
    return {
        "output_id": "migration/state",
        "kind": "api_readback",
        "call": READBACK,
        "args": {},
        "value": session.call("migration_readback"),
    }


def open_project(session: PainterSession, project: Path) -> None:
    session.call("open_project", path=project.as_posix())
    opened = session.wait_ready()
    if opened.file_path is None or Path(opened.file_path).resolve() != project.resolve():
        raise RecorderError(f"Painter opened {opened.file_path}, not {project}")


def run_export(
    session: PainterSession, job: MigrationJob, directory: Path, name: str
) -> tuple[list[dict[str, Any]], list[Path]]:
    """One export into a fresh directory, verified like a texture golden's export."""
    export = ConfigExport(2, job.config_id, job.config)
    return run_config_export(session, export, directory / name, "migration_export")


def record_migration_golden(
    session: PainterSession,
    job: MigrationJob,
    work: Path,
    inbox: Path,
    now: Now = utc_now,
    *,
    record_prefix: str = "",
) -> Path:
    """Open a private copy of the project, record r1, r1-repeat and r2, write the run to the
    inbox."""
    identity = session.connect()
    require_colour_management(Job(job.manifest, {}, (), ()), identity)
    directory = ensure_outside_repository(work) / job.golden_id.replace("/", "__")
    directory = directory / run_name(identity.session_id, now())
    project = stage_project(job, directory)
    try:
        open_project(session, project)
        after_open = session.call("hello")["colour_management"]
        first = [state_readback(session), template_output(session)]
        exported, first_blobs = run_export(session, job, directory, R1)
        repeat, repeat_blobs = run_export(session, job, directory, R1_REPEAT)
        saved = directory / "reopen" / f"reopened-{job.project_name}"
        saved.parent.mkdir(parents=True)
        session.call("save_as", path=saved.as_posix())
        session.wait_ready()
        session.call("close_project")
        session.wait_closed()
        open_project(session, saved)
        second = [state_readback(session), template_output(session)]
        reopened, second_blobs = run_export(session, job, directory, R2)
    finally:
        close_quietly(session)
    record = {
        "schema": "uzpainter/parity/golden-private/1",
        "record_class": "private_oracle_record",
        "golden_id": job.golden_id,
        "tier": job.manifest["tier"],
        "key": {
            "inputs": job.input_hashes(),
            "instruction_sequence_sha256": sha256_bytes(
                canonical_json(job.manifest["instruction_sequence"])
            ),
            "effective_defaults": {"colour_management_after_open": after_open},
            "painter_build": identity.painter_build(),
            "project_settings": {
                "applied_settings": {
                    s["name"]: s["value"] for s in job.manifest["applied_settings"]
                },
                "colour_management": identity.colour_management,
            },
            "resource_hashes": [],
            "bake_backend": None,
            "render_state": None,
        },
        "recordings": [
            recording(R1, SAME_SESSION, identity, now, first + exported),
            recording(R1_REPEAT, SAME_SESSION, identity, now, repeat),
            recording(R2, AFTER_SAVE_REOPEN, identity, now, second + reopened),
        ],
    }
    return write_run(
        inbox,
        record,
        first_blobs + repeat_blobs + second_blobs,
        job.manifest,
        identity.session_id,
        environment=identity.environment,
        record_prefix=record_prefix,
    )
