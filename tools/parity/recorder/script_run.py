r"""Tier 1 goldens from UzmiGames pipeline scripts run byte-unchanged in Painter (decision 099).

    python -m tools.parity.recorder record-script <manifest.json> --assets-root <Assets3D>
    python -m tools.parity.recorder.script_run manifest --assets-root <Assets3D> --out <path>

The manifest's `instruction_sequence.interface` is `uzmigames_pipeline_scripts`: every step is one
script run (`uzmigames.pipeline.run_script`), and its inputs live in the UzmiGames asset
repository (Assets3D), named by SHA-256 and `assets3d_path` only. The job is three steps:

1. **create**: a Painter-side script that reads its arguments (`mesh`, `normal`, `ao`, `dst`,
   `name`) from a hard-coded path, creates the project and saves it to `dst`;
2. **sync**: the layer-stack command line run host-side (`sync --stack --masks --state`), which
   builds Painter-side code and hands it to its module function `execute(code)`;
3. **export**: a Painter-side script that reads `out` and `prefix` from a hard-coded path, saves
   the project and exports its maps into `out`.

Every script runs from its pinned bytes, read once and hashed; nothing is ever imported from
another copy. Two adaptations, both by the recorder, are the only changes to how the scripts run:

a. **Repointed arguments.** The inputs are hash-checked under `--assets-root` and copied into the
   private work directory. Each Painter-side script runs in a fresh namespace whose `open` maps
   exactly its one hard-coded arguments path (as written in the script) to a copy of the
   arguments file in which `mesh`, `normal` and `ao` name the staged copies, `dst` a project in
   the work directory and `out` a fresh export directory; every other key is unchanged
   (`painter_scripts.py`).
b. **Transport swap.** The sync script's own `execute(code)` is replaced by the recorder's remote
   control with the same contract (run the code in Painter, return the `result` it assigns), so
   the Painter-side code the script builds is the script's own.

Recordings: `r1` (`same_session`: create, sync, export), `r1-repeat` (`same_session`: export again
into a fresh directory) and `r2` (`after_save_reopen`: close, reopen the saved project, export
again). Each export is verified like a texture golden's (`capture.verify_current_outputs`: a
fresh empty directory holding exactly the files the script reports, written after the fence), and
each script's `result` is recorded as a private readback. Records go to the oracle inbox like
every other golden (`output.py`).
"""

from __future__ import annotations

import argparse
import ast
import base64
import json
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from tools.parity.recorder.capture import (
    MEDIA_TYPES,
    measure_storage_format,
    verify_current_outputs,
    write_fence,
)
from tools.parity.recorder.job import Job, canonical_json, sha256_bytes, sha256_file
from tools.parity.recorder.output import ensure_outside_repository, run_name, write_run
from tools.parity.recorder.session import PainterIdentity, PainterSession, RecorderError
from tools.parity.recorder.texture import (
    UNDETERMINED,
    Now,
    close_quietly,
    output_safe,
    require_colour_management,
    utc_now,
)
from tools.parity.schemas import Schema, load_json, validation_errors

INTERFACE = "uzmigames_pipeline_scripts"
RUN_SCRIPT = "uzmigames.pipeline.run_script"
ASSETS3D_LICENCE = "LicenseRef-UzmiGames-Assets3D"
PAINTER_SCRIPTS = Path(__file__).with_name("painter_scripts.py")

# Step argument names of each step; an input argument names the kinds its input may have.
CREATE_INPUTS = {
    "script": ("pipeline_script",),
    "args_file": ("recipe_json",),
    "mesh": ("mesh",),
    "mesh_material_library": ("mesh",),
    "normal": ("image",),
    "ao": ("image",),
}
SYNC_ARGS = frozenset({"script", "command", "stack", "masks", "mask_files"})
EXPORT_INPUTS = {"script": ("pipeline_script",), "args_file": ("recipe_json",)}
MASK_KINDS = ("mask", "image")
SYNC_COMMAND = "sync"

# Keys of the two arguments files: the repointed ones and those kept as authored.
CREATE_KEYS = frozenset({"mesh", "normal", "ao", "dst", "name"})
EXPORT_KEYS = frozenset({"out", "prefix"})

# Recordings (golden-private.json conditions).
R1, R1_REPEAT, R2 = "r1", "r1-repeat", "r2"
SAME_SESSION, AFTER_SAVE_REOPEN = "same_session", "after_save_reopen"


@dataclass(frozen=True)
class PinnedInput:
    """An Assets3D input: its file under the assets root, hash-checked when the job loads."""

    input_id: str
    kind: str
    assets3d_path: str
    sha256: str
    file: Path
    data: bytes | None = None  # a pipeline script's exact bytes, read once

    @property
    def name(self) -> str:
        return PurePosixPath(self.assets3d_path).name


@dataclass(frozen=True)
class ScriptStep:
    step: int
    args: dict[str, Any]
    script: PinnedInput
    hard_coded_args: str | None = None  # the arguments path as written in the script
    arguments: dict[str, Any] | None = None  # the authored arguments file


@dataclass(frozen=True)
class ScriptJob:
    manifest: dict[str, Any]
    inputs: dict[str, PinnedInput]
    create: ScriptStep
    sync: ScriptStep
    export: ScriptStep

    @property
    def golden_id(self) -> str:
        return str(self.manifest["golden_id"])

    def input_hashes(self) -> list[dict[str, str]]:
        return [{"input_id": i["input_id"], "sha256": i["sha256"]} for i in self.manifest["inputs"]]


def tail_matches(path: str, assets3d_path: str) -> bool:
    """`path` (as a script or arguments file writes it) ends with the Assets3D-relative path."""
    written = PureWindowsPath(path).as_posix().lower()
    return written.endswith("/" + assets3d_path.lower())


def pinned_inputs(manifest: dict[str, Any], assets_root: Path) -> dict[str, PinnedInput]:
    inputs: dict[str, PinnedInput] = {}
    for item in manifest["inputs"]:
        where = f"input {item['input_id']}"
        if "assets3d_path" not in item or item["provenance"]["licence"] != ASSETS3D_LICENCE:
            raise RecorderError(f"{where}: a pipeline-script job names Assets3D inputs only")
        file = assets_root / item["assets3d_path"]
        if not file.is_file():
            raise RecorderError(f"{where}: {file} does not exist")
        data = file.read_bytes() if item["kind"] == "pipeline_script" else None
        actual = sha256_bytes(data) if data is not None else sha256_file(file)
        if actual != item["sha256"]:
            raise RecorderError(f"{where}: sha256 {actual} of {file} differs from the manifest")
        inputs[item["input_id"]] = PinnedInput(
            item["input_id"], item["kind"], item["assets3d_path"], item["sha256"], file, data
        )
    return inputs


def input_of(
    inputs: dict[str, PinnedInput], step: int, arg: str, value: Any, kinds: tuple[str, ...]
) -> PinnedInput:
    if not isinstance(value, str) or value not in inputs:
        raise RecorderError(f"step {step}: `{arg}` names no input ({value!r})")
    if inputs[value].kind not in kinds:
        raise RecorderError(f"step {step}: `{arg}` must be a {' or '.join(kinds)} input")
    return inputs[value]


def hard_coded_args_path(script: PinnedInput, arguments: PinnedInput, step: int) -> str:
    """The one string literal of the script naming its arguments file (redirected by `open`)."""
    assert script.data is not None
    tree = ast.parse(script.data, filename=script.name)
    found = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and tail_matches(node.value, arguments.assets3d_path)
    }
    if len(found) != 1:
        raise RecorderError(
            f"step {step}: {script.name} must name its arguments file "
            f"{arguments.assets3d_path} in exactly one string literal (found {sorted(found)})"
        )
    return found.pop()


def arguments_file(file: PinnedInput, keys: frozenset[str], step: int) -> dict[str, Any]:
    arguments = json.loads(file.file.read_bytes().decode("utf-8"))
    if not isinstance(arguments, dict) or set(arguments) != keys:
        raise RecorderError(f"step {step}: {file.name} must hold exactly the keys {sorted(keys)}")
    return arguments


def script_step(raw: dict[str, Any], inputs: dict[str, PinnedInput]) -> tuple[str, ScriptStep]:
    """One step, with its role (create, sync or export) told by its argument names."""
    step, args = raw["step"], dict(raw.get("args", {}))
    if raw["call"] != RUN_SCRIPT:
        raise RecorderError(f"step {step}: {raw['call']} is not {RUN_SCRIPT}")
    if set(args) == set(CREATE_INPUTS):
        found = {k: input_of(inputs, step, k, args[k], kinds) for k, kinds in CREATE_INPUTS.items()}
        script, file = found["script"], found["args_file"]
        arguments = arguments_file(file, CREATE_KEYS, step)
        for key in ("mesh", "normal", "ao"):
            if not tail_matches(str(arguments[key]), found[key].assets3d_path):
                raise RecorderError(
                    f"step {step}: {file.name} `{key}` names {arguments[key]}, not the input "
                    f"{found[key].input_id} ({found[key].assets3d_path})"
                )
        if (
            PurePosixPath(found["mesh_material_library"].assets3d_path).parent
            != PurePosixPath(found["mesh"].assets3d_path).parent
        ):
            raise RecorderError(f"step {step}: the material library must lie next to the mesh")
        path = hard_coded_args_path(script, file, step)
        return "create", ScriptStep(step, args, script, path, arguments)
    if set(args) == set(EXPORT_INPUTS):
        found = {k: input_of(inputs, step, k, args[k], kinds) for k, kinds in EXPORT_INPUTS.items()}
        script, file = found["script"], found["args_file"]
        arguments = arguments_file(file, EXPORT_KEYS, step)
        path = hard_coded_args_path(script, file, step)
        return "export", ScriptStep(step, args, script, path, arguments)
    if set(args) == SYNC_ARGS:
        script = input_of(inputs, step, "script", args["script"], ("pipeline_script",))
        if args["command"] != SYNC_COMMAND:
            raise RecorderError(f"step {step}: only the `{SYNC_COMMAND}` command is recorded")
        stack = input_of(inputs, step, "stack", args["stack"], ("recipe_json",))
        masks, names = args["masks"], args["mask_files"]
        if not isinstance(masks, list) or not isinstance(names, list) or len(masks) != len(names):
            raise RecorderError(f"step {step}: `masks` and `mask_files` must be parallel lists")
        files = [input_of(inputs, step, "masks", m, MASK_KINDS) for m in masks]
        if [f.name for f in files] != names:
            raise RecorderError(f"step {step}: `mask_files` must be the masks' file names")
        if len({PurePosixPath(f.assets3d_path).parent for f in files}) != 1:
            raise RecorderError(f"step {step}: the masks must share one folder")
        referenced = stack_bitmaps(json.loads(stack.file.read_bytes().decode("utf-8")))
        if sorted(referenced) != sorted(PurePosixPath(n).stem for n in names):
            raise RecorderError(
                f"step {step}: the stack references the bitmaps {sorted(referenced)}, not the "
                f"masks given {sorted(names)}"
            )
        return "sync", ScriptStep(step, args, script)
    raise RecorderError(f"step {step}: arguments {sorted(args)} are no create, sync or export")


def stack_bitmaps(stack: dict[str, Any]) -> set[str]:
    """Bitmap names a stack JSON references (masks and `base_tex`), as the sync command reads."""
    names = {x["mask"] for x in stack["layers"] + stack["groups"] if x.get("mask")}
    return names | {x["base_tex"] for x in stack["layers"] if x.get("base_tex")}


def script_job_from_manifest(manifest: dict[str, Any], assets_root: Path) -> ScriptJob:
    """The job of a pipeline-script manifest; refused before Painter is touched on any missing
    input, hash mismatch or step the recorder does not know."""
    if manifest["instruction_sequence"]["interface"] != INTERFACE:
        raise RecorderError(f"{manifest['golden_id']}: the interface is not {INTERFACE}")
    if manifest["tier"] != "1":
        raise RecorderError(f"{manifest['golden_id']}: pipeline-script goldens are Tier 1")
    inputs = pinned_inputs(manifest, assets_root.resolve())
    steps = manifest["instruction_sequence"]["steps"]
    if [s["step"] for s in steps] != list(range(1, len(steps) + 1)):
        raise RecorderError("instruction steps must be numbered 1..n in order")
    roles = [script_step(raw, inputs) for raw in steps]
    if [role for role, _ in roles] != ["create", "sync", "export"]:
        raise RecorderError("a pipeline-script golden runs create, sync and export, in order")
    return ScriptJob(manifest, inputs, roles[0][1], roles[1][1], roles[2][1])


def load_script_job(path: Path, assets_root: Path) -> ScriptJob:
    manifest = load_json(path)
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"{path}: not a valid public manifest: {problems}")
    return script_job_from_manifest(manifest, assets_root)


def extension_code(source: str) -> str:
    """Statements that execute `painter_scripts.py` into a copy of the recorder's namespace (the
    pattern of `probes.extension_code`): its operation registers into the shared `OPERATIONS`."""
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return (
        "import base64\n"
        "uzp_scripts = dict(uzp_recorder)\n"
        f"exec(base64.b64decode('{encoded}').decode('utf-8'), uzp_scripts)\n"
    )


class ScriptSession(PainterSession):
    """A recorder session with the script operation loaded next to `painter_side.py`."""

    def connect(self) -> PainterIdentity:
        identity = super().connect()
        self.transport.run(extension_code(PAINTER_SCRIPTS.read_text(encoding="utf-8")))
        return identity


def run_in_painter(
    session: PainterSession,
    data: bytes,
    file_name: str,
    redirect: tuple[str, Path] | None = None,
) -> Any:
    """Run exact bytes in Painter through the recorder's remote control; returns `result`."""
    reply = session.call(
        "run_script",
        source=base64.b64encode(data).decode("ascii"),
        sha256=sha256_bytes(data),
        file_name=file_name,
        args_path=redirect[0] if redirect else None,
        args_copy=str(redirect[1]) if redirect else None,
    )
    return reply["result"]


def stage_inputs(job: ScriptJob, root: Path) -> dict[str, Path]:
    """Copy every input to `root/<assets3d_path>` (file names and folders kept) and check each
    copy's hash: Painter reads only these copies, never the asset repository."""
    staged: dict[str, Path] = {}
    for item in job.inputs.values():
        target = root / item.assets3d_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.file, target)
        if sha256_file(target) != item.sha256:
            raise RecorderError(f"input {item.input_id}: the staged copy differs from its pin")
        staged[item.input_id] = target
    return staged


def write_arguments(path: Path, arguments: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(arguments), encoding="utf-8")
    return path


def readback(step: ScriptStep, value: Any) -> dict[str, Any]:
    return {
        "output_id": f"script/s{step.step}",
        "kind": "api_readback",
        "call": RUN_SCRIPT,
        "args": {"step": step.step, "script": step.script.input_id},
        "value": value,
    }


def run_create(
    session: PainterSession, job: ScriptJob, staged: dict[str, Path], directory: Path
) -> tuple[Any, Path]:
    step = job.create
    assert step.arguments is not None and step.hard_coded_args is not None
    project = directory / "project" / PureWindowsPath(str(step.arguments["dst"])).name
    project.parent.mkdir(parents=True)
    arguments = {
        **step.arguments,
        **{key: str(staged[step.args[key]]) for key in ("mesh", "normal", "ao")},
        "dst": str(project),
    }
    copy = write_arguments(directory / "arguments" / step.script.name, arguments)
    assert step.script.data is not None
    result = run_in_painter(
        session, step.script.data, step.script.name, (step.hard_coded_args, copy)
    )
    saved = session.wait_ready()
    if saved.file_path is None or Path(saved.file_path).resolve() != project.resolve():
        raise RecorderError(
            f"the project was not saved to {project} (Painter reports {saved.file_path})"
        )
    return result, project


def run_sync(
    session: PainterSession, job: ScriptJob, staged: dict[str, Path], directory: Path
) -> Any:
    """Run the sync command line host-side from the pinned bytes, its `execute` swapped for the
    recorder's remote control (same contract: run the code, return its `result`)."""
    step = job.sync
    script = step.script
    assert script.data is not None
    namespace: dict[str, Any] = {
        "__name__": "uzp_pipeline_layer_stack",
        "__file__": str(script.file),
    }
    exec(compile(script.data, str(script.file), "exec", dont_inherit=True), namespace)
    if not callable(namespace.get("execute")) or not callable(namespace.get("main")):
        raise RecorderError(f"{script.name} defines no `execute(code)` and `main()` to run")
    results: list[Any] = []

    def execute(code: str) -> Any:
        value = run_in_painter(session, code.encode("utf-8"), f"{script.name} {SYNC_COMMAND}")
        results.append(value)
        return value

    namespace["execute"] = execute
    state = directory / "sync-state.json"
    if state.exists():
        raise RecorderError(f"{state} already exists: the sync state must start empty")
    masks = staged[step.args["masks"][0]].parent
    argv = [
        script.name,
        SYNC_COMMAND,
        "--stack",
        str(staged[step.args["stack"]]),
        "--masks",
        str(masks),
        "--state",
        str(state),
    ]
    saved_argv = sys.argv
    sys.argv = argv
    try:
        namespace["main"]()
    finally:
        sys.argv = saved_argv
    if len(results) != 1:
        raise RecorderError(f"{script.name} sync ran {len(results)} Painter calls, not one")
    session.wait_ready()
    return results[0]


def texture_set_of(key: str) -> str:
    """`str((texture_set, stack))` as the export script reports it -> `set` or `set/stack`."""
    try:
        value = ast.literal_eval(key)
    except (ValueError, SyntaxError):
        return key
    if isinstance(value, tuple) and len(value) == 2 and all(isinstance(v, str) for v in value):
        return value[0] if not value[1] else f"{value[0]}/{value[1]}"
    return key


def run_export(
    session: PainterSession, job: ScriptJob, directory: Path, recording: str
) -> tuple[list[dict[str, Any]], list[Path]]:
    """One export into a fresh directory, verified like a texture golden's export."""
    step = job.export
    assert step.arguments is not None and step.hard_coded_args is not None
    assert step.script.data is not None
    out = directory / recording / "export"
    out.mkdir(parents=True)
    copy = write_arguments(
        directory / recording / "arguments" / step.script.name,
        {**step.arguments, "out": str(out)},
    )
    session.wait_ready()
    fence_ns = write_fence(directory / recording / "fence")
    result = run_in_painter(
        session, step.script.data, step.script.name, (step.hard_coded_args, copy)
    )
    session.wait_ready()
    if str(result.get("status", "")).rsplit(".", 1)[-1] != "Success":
        raise RecorderError(f"{recording}: export {result.get('status')}: {result.get('message')}")
    groups: dict[str, list[str]] = result["files"]
    files = [Path(name) for names in groups.values() for name in names]
    verify_current_outputs(files, out, fence_ns)
    outputs: list[dict[str, Any]] = [readback(step, result)]
    for key, names in sorted(groups.items()):
        for name in names:
            path = Path(name)
            measured = measure_storage_format(path)
            encoding, basis = (
                (measured.encoding, "file")
                if measured.encoding is not None
                else (UNDETERMINED, "pipeline_script_export")
            )
            outputs.append(
                {
                    "output_id": f"export/{output_safe(path.stem)}",
                    "kind": "exported_map",
                    "texture_set": texture_set_of(key),
                    "map": path.stem,
                    "blob": {
                        "sha256": sha256_file(path),
                        "size_bytes": path.stat().st_size,
                        "media_type": MEDIA_TYPES[measured.container],
                    },
                    "storage_format": measured.as_schema(encoding),
                    "export_settings": {
                        "step": step.step,
                        "script": step.script.input_id,
                        "encoding_basis": basis,
                    },
                }
            )
    return outputs, files


def template_output(session: PainterSession) -> dict[str, Any]:
    return {
        "output_id": "template/texture-sets",
        "kind": "template_capture",
        "subject": "texture sets, stacks and channel formats of the project",
        "values": session.call("template_capture"),
    }


def recording(
    recording_id: str,
    condition: str,
    identity: PainterIdentity,
    now: Now,
    outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "recording_id": recording_id,
        "condition": condition,
        "session_id": identity.session_id,
        "recorded_at": now().isoformat(),
        "outputs": outputs,
    }


def record_script_golden(
    session: PainterSession,
    job: ScriptJob,
    work: Path,
    inbox: Path,
    now: Now = utc_now,
    *,
    record_prefix: str = "",
) -> Path:
    """Run the pinned scripts, record r1, r1-repeat and r2, and write the run to the inbox."""
    identity = session.connect()
    require_colour_management(Job(job.manifest, {}, (), ()), identity)
    directory = ensure_outside_repository(work) / job.golden_id.replace("/", "__")
    directory = directory / run_name(identity.session_id, now())
    staged = stage_inputs(job, directory / "inputs")
    try:
        created, project = run_create(session, job, staged, directory)
        after_create = session.call("hello")["colour_management"]
        synced = run_sync(session, job, staged, directory)
        first = [readback(job.create, created), readback(job.sync, synced)]
        first.append(template_output(session))
        exported, first_blobs = run_export(session, job, directory, R1)
        repeat, repeat_blobs = run_export(session, job, directory, R1_REPEAT)
        session.call("close_project")
        session.wait_closed()
        session.call("open_project", path=project.as_posix())
        session.wait_ready()
        second = [template_output(session)]
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
            "effective_defaults": {"colour_management_after_create": after_create},
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


# --- The R9 manifest (phase1/tier1/wand-v1) ---------------------------------------------------

WAND = "_tmp/claude/varinha11-v1"
WAND_SCRIPTS = "Pipeline/retopology/wand11-v1"
WAND_INPUTS: tuple[tuple[str, str, str], ...] = (
    ("painter-create-py", "pipeline_script", f"{WAND_SCRIPTS}/painter_create.py"),
    ("painter-layer-stack-py", "pipeline_script", "Pipeline/painting/painter_layer_stack.py"),
    ("painter-export-py", "pipeline_script", f"{WAND_SCRIPTS}/painter_export.py"),
    ("painter-create-args", "recipe_json", f"{WAND}/painter_create_args.json"),
    ("painter-export-args", "recipe_json", f"{WAND}/painter_export_args.json"),
    ("wand-stack", "recipe_json", f"{WAND}/paint/stack-wand.json"),
    ("wand-mesh", "mesh", f"{WAND}/paint/11-Varinha-Madeira-v1_low.obj"),
    ("wand-mesh-mtl", "mesh", f"{WAND}/paint/11-Varinha-Madeira-v1_low.mtl"),
    ("wand-normal", "image", f"{WAND}/bake/11-Varinha-Madeira_Normal_OpenGL_v1.png"),
    ("wand-ao", "image", f"{WAND}/paint/11-Varinha-Madeira_AO_v1.png"),
)
WAND_MASKS = f"{WAND}/paint/masks"
WAND_STACK = f"{WAND}/paint/stack-wand.json"

WAND_SETTINGS: tuple[tuple[str, Any, str], ...] = (
    ("OCIO", "resources/ocio/substance/config.ocio", "environment_variable"),
    ("project.normal_map_format", "OpenGL", "recorder_api"),
    ("project.default_texture_resolution", 2048, "recorder_api"),
    ("project.import_cameras", False, "recorder_api"),
    ("project.save_mode", "Full", "recorder_api"),
    ("export.file_format", "png", "recorder_api"),
    ("export.png.bit_depth", 16, "recorder_api"),
    ("export.size_log2", 11, "recorder_api"),
    ("export.padding", "infinite", "recorder_api"),
    ("export.dithering", False, "recorder_api"),
    ("export.shader_params", False, "recorder_api"),
)

WAND_DESCRIPTION = (
    "Tier 1 pilot golden of the UzmiGames wand 11-Varinha-Madeira v1 (phase1.25 items 2.2, 2.3, "
    "3.1; decision 099). Three UzmiGames pipeline scripts run byte-unchanged in Painter, each "
    "pinned by SHA-256, through Painter's documented remote control (never the community MCP "
    "bridge): painter_create.py (a new project from the low-poly OBJ under OCIO with Painter's "
    "substance config, OpenGL normals, 2048 px, no cameras; imports the Normal and AO mesh maps; "
    "save_as Full), painter_layer_stack.py sync (the stack-wand.json group: 4 groups, 13 fills, "
    "the 13 UV masks and the T_base colour bitmap) and painter_export.py (BaseColor, Roughness, "
    "Metallic, Height and Normal_OpenGL as 16-bit PNG, sizeLog2 11, infinite padding, no "
    "dithering). Two adaptations, both by the recorder: (1) the Painter-side scripts read their "
    "arguments from a hard-coded Assets3D path; the recorder hash-checks and copies every input "
    "into its private work directory and runs each script in a namespace whose open maps exactly "
    "that path to a copy of the arguments in which mesh, normal, ao, dst and out name the staged "
    "copies and the work directory, every other key unchanged; (2) the sync command's own "
    "remote-execution function is replaced by the recorder's remote control with the same "
    "contract, so the Painter-side code the script builds is its own. Recordings: r1 (same "
    "session: create, sync, export), r1-repeat (same session, export again) and r2 (after save, "
    "close and reopen, export again). Recorded on Painter 12.1.5 (the current envelope; "
    "phase1.25's text says 12.1.0)."
)


def assets3d_input(input_id: str, kind: str, path: str, assets_root: Path) -> dict[str, Any]:
    file = assets_root / path
    if not file.is_file():
        raise RecorderError(f"{file} does not exist")
    return {
        "input_id": input_id,
        "kind": kind,
        "assets3d_path": path,
        "sha256": sha256_file(file),
        "provenance": {"origin": "uzmigames_authored", "licence": ASSETS3D_LICENCE},
    }


def wand_manifest(assets_root: Path) -> dict[str, Any]:
    """The R9 manifest, hashing the current Assets3D files (`--assets-root`)."""
    stack = json.loads((assets_root / WAND_STACK).read_bytes().decode("utf-8"))
    bitmaps = sorted(stack_bitmaps(stack))
    inputs = [assets3d_input(i, k, p, assets_root) for i, k, p in WAND_INPUTS]
    masks = [
        assets3d_input(
            f"mask-{name.lower()}",
            "mask" if name.startswith("M_") else "image",
            f"{WAND_MASKS}/{name}.png",
            assets_root,
        )
        for name in bitmaps
    ]
    create = {
        "script": "painter-create-py",
        "args_file": "painter-create-args",
        "mesh": "wand-mesh",
        "mesh_material_library": "wand-mesh-mtl",
        "normal": "wand-normal",
        "ao": "wand-ao",
    }
    manifest: dict[str, Any] = {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": "phase1/tier1/wand-v1",
        "tier": "1",
        "domain": "tier1/pilot/wand-v1",
        "description": WAND_DESCRIPTION,
        "inputs": inputs + masks,
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": INTERFACE,
            "steps": [
                {"step": 1, "call": RUN_SCRIPT, "args": create},
                {
                    "step": 2,
                    "call": RUN_SCRIPT,
                    "args": {
                        "script": "painter-layer-stack-py",
                        "command": SYNC_COMMAND,
                        "stack": "wand-stack",
                        "masks": [m["input_id"] for m in masks],
                        "mask_files": [f"{name}.png" for name in bitmaps],
                    },
                },
                {
                    "step": 3,
                    "call": RUN_SCRIPT,
                    "args": {"script": "painter-export-py", "args_file": "painter-export-args"},
                },
            ],
        },
        "applied_settings": [
            {"name": name, "value": value, "applied_by": by} for name, value, by in WAND_SETTINGS
        ],
        "expectations": [],
        "software": {
            "painter": {
                "product": "Adobe Substance 3D Painter",
                "version": "12.1.5",
                "build_id": "12.1.5+js-api.1.1.20",
            },
            "uzpainter_build_hash": None,
        },
        "private_records": [],
    }
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"the wand manifest is invalid: {problems}")
    script_job_from_manifest(manifest, assets_root)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.recorder.script_run")
    commands = parser.add_subparsers(dest="command", required=True)
    write = commands.add_parser("manifest", help="write the R9 wand manifest (hashes Assets3D)")
    write.add_argument("--assets-root", type=Path, required=True)
    write.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        manifest = wand_manifest(args.assets_root.resolve())
    except RecorderError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
