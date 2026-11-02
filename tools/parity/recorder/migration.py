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

from tools.parity.feasibility import png
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
    exported = export_config(config, repo_root)
    declared_maps(exported)  # a supported preset that declares a map twice is refused here
    file = input_file(project, assets_root.resolve(), store or locate())
    return MigrationJob(
        manifest,
        project["input_id"],
        project["sha256"],
        PurePosixPath(project["assets3d_path"]).name,
        file,
        config["input_id"],
        exported,
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


COLOUR_ENVIRONMENT = ("mode", "OCIO", "PAINTER_ACE_CONFIG")


def check_after_open(
    job: MigrationJob,
    environment_before: dict[str, Any],
    environment_after: dict[str, Any],
    texture_sets: dict[str, Any],
) -> None:
    """Refused before any export of an opened project, on two checks.

    - The session's colour-management environment is unchanged across the open: `hello`'s
      `colour_management` (the `OCIO` and `PAINTER_ACE_CONFIG` variables and the mode they
      select for `project.create`). That is environment stability only. It is not the opened
      project's own saved colour mode, which no documented call the recorder makes reads: that
      mode stays unconfirmed.
    - The project's state readback holds every texture set the configuration's `exportList`
      names (a real readback of the opened project)."""
    for key in COLOUR_ENVIRONMENT:
        if environment_after.get(key) != environment_before.get(key):
            raise RecorderError(
                f"{job.golden_id}: the session's colour-management environment {key} changed "
                f"across the open, from {environment_before.get(key)!r} to "
                f"{environment_after.get(key)!r}"
            )
    held = set(texture_sets)
    named = {str(entry["rootPath"]).split("/")[0] for entry in job.config["exportList"]}
    if named - held:
        raise RecorderError(
            f"{job.golden_id}: the opened project has no texture set {sorted(named - held)}; it "
            f"holds {sorted(held)}"
        )


Declared = tuple[dict[tuple[str, str], int], dict[str, Any]]


PNG_DEPTHS = {"8": 8, "16": 16}


def declared_maps(config: dict[str, Any]) -> Declared | None:
    """The maps a supported inline preset declares, by (texture set, file stem), with each map's
    channel count, and its one parameter rule. Supported means a default preset defined in the
    configuration and exported by one unfiltered `exportParameters` rule as PNG at `bitDepth`
    "8" or "16" (`sizeLog2` an integer or absent), `exportList` entries that name only their
    `rootPath`, and maps that name only `fileName` and `channels`, whose only token is
    `$textureSet`. Any other configuration (a shipped preset, OpenEXR, several or filtered rules,
    a per-entry preset) returns None and keeps the generic migration behaviour. A supported
    preset that repeats a file name is refused, before Painter."""
    if any(set(entry) != {"rootPath"} for entry in config["exportList"]):
        return None
    presets = {p["name"]: p for p in config.get("exportPresets", [])}
    preset = presets.get(config.get("defaultExportPreset"))
    rules = config["exportParameters"]
    if preset is None or len(rules) != 1 or set(rules[0]) != {"parameters"}:
        return None
    parameters: dict[str, Any] = rules[0]["parameters"]
    size = parameters.get("sizeLog2")
    if (
        parameters.get("fileFormat") != "png"
        or parameters.get("bitDepth") not in PNG_DEPTHS
        or (size is not None and (isinstance(size, bool) or not isinstance(size, int)))
        or any(
            set(item) != {"fileName", "channels"}
            or "$" in str(item["fileName"]).replace("$textureSet", "")
            for item in preset["maps"]
        )
    ):
        return None
    maps: dict[tuple[str, str], int] = {}
    for entry in config["exportList"]:
        root = str(entry["rootPath"])
        for item in preset["maps"]:
            name = str(item["fileName"]).replace("$textureSet", root)
            if (root, name) in maps:
                raise RecorderError(f"export configuration: {root}/{name} is declared twice")
            maps[root, name] = len(item["channels"])
    return maps, parameters


def exported_files(outputs: list[dict[str, Any]]) -> dict[tuple[str, str], list[Path]]:
    """Each exported file by (texture set, file stem), from the export call's own readback."""
    files: dict[tuple[str, str], list[Path]] = {}
    for output in outputs:
        if output["kind"] != "api_readback" or output.get("call") != EXPORT:
            continue
        for entry in output["value"]["textures"]:
            texture_set = entry["texture_set"] + (f"/{entry['stack']}" if entry["stack"] else "")
            for file_name in entry["files"]:
                files.setdefault((texture_set, Path(file_name).stem), []).append(Path(file_name))
    return files


def check_declared(job: MigrationJob, outputs: list[dict[str, Any]]) -> None:
    """Refused before admission: a supported inline preset's export (`declared_maps`) wrote
    exactly its declared maps, once each, every one a PNG of the declared depth, channel count
    and (when stated) size. Other configurations are not checked here."""
    declared = declared_maps(job.config)
    if declared is None:
        return
    expected, parameters = declared
    files = exported_files(outputs)
    maps = [(o["texture_set"], o["map"]) for o in outputs if o["kind"] == "exported_map"]
    if sorted(maps) != sorted(expected) or any(len(f) != 1 for f in files.values()):
        raise RecorderError(
            f"{job.golden_id}: the export wrote {sorted(maps)}, not the declared "
            f"{sorted(expected)} once each"
        )
    found = {(o["texture_set"], o["map"]): o for o in outputs if o["kind"] == "exported_map"}
    size = parameters.get("sizeLog2")
    for key, channels in sorted(expected.items()):
        stored = found[key]["storage_format"]
        want = {
            "container": "png",
            "bits_per_channel": PNG_DEPTHS[parameters["bitDepth"]],
            "channels": channels,
        }
        got = {name: stored[name] for name in want}
        if got != want:
            raise RecorderError(f"{job.golden_id}: {key[1]} is {got}, not the declared {want}")
        if size is not None:
            (path,) = files[key]
            header = png.chunks(path.read_bytes()[:64])[0][1]
            width, height = int.from_bytes(header[0:4], "big"), int.from_bytes(header[4:8], "big")
            if (width, height) != (1 << size, 1 << size):
                raise RecorderError(
                    f"{job.golden_id}: {key[1]} is {width}x{height}, not the declared "
                    f"{1 << size} px"
                )


def run_export(
    session: PainterSession, job: MigrationJob, directory: Path, name: str
) -> tuple[list[dict[str, Any]], list[Path]]:
    """One export into a fresh directory, verified like a texture golden's export and against
    the maps its configuration declares."""
    export = ConfigExport(2, job.config_id, job.config)
    outputs, files = run_config_export(session, export, directory / name, "migration_export")
    check_declared(job, outputs)
    return outputs, files


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
        sets = first[0]["value"]["texture_sets"]
        check_after_open(job, identity.colour_management, after_open, sets)
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
        after_reopen = session.call("hello")["colour_management"]
        sets = second[0]["value"]["texture_sets"]
        check_after_open(job, identity.colour_management, after_reopen, sets)
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
