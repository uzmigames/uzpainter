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

An *observed* probe golden (step 2 `event.Dispatcher.connect`, right after `project.create`)
records, after every later step, the events dispatched since the previous step and the states
polled until the step's asynchronous calls answered (`reload_mesh`, `execute_when_not_busy`,
`reload_modified_resources_async`), then a few more polls; a step with `wait: false` leaves its
events to the next step's record. Further step arguments the host resolves: `work_file` (a file
name in the recording's private work directory, the files of which are listed after every save
step), and on `reload_modified_resources_async`, `rewrite_input` / `with_input` (the staged copy
of one input is overwritten with another input's bytes just before the call).
`with_input_after_reopen` selects a different pinned input for that rewrite in r2, so repeated
reloads can observe new content rather than a version already imported in r1. An
`export_project_textures` step with `probe: true` is an export request among the probe steps:
its result or error, then the files present in its directory once the step settled.

Records go to the private oracle inbox exactly like texture goldens (`output.py`).
"""

from __future__ import annotations

import argparse
import ast
import base64
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
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
    UnseenBuild,
)
from tools.parity.recorder.texture import (
    Now,
    close_quietly,
    export_outputs,
    export_roots,
    require_colour_management,
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
# With the P22-B blocks of `painter_probes.py` (decision 295: texture sets, channels, project;
# decision 297: the host modules).
EDIT_CALLS: frozenset[str] = (
    frozenset(CONSTANTS["EDIT_CALLS"])
    | frozenset(CONSTANTS["P295_EDIT_CALLS"])
    | frozenset(CONSTANTS["HOST_EDIT_CALLS"])
    | frozenset(CONSTANTS["SUBSTANCE_EDIT_CALLS"])
    | frozenset(CONSTANTS["SUBSTANCE_VALUE_ARGS"])
)
GETTER_CALLS: frozenset[str] = (
    frozenset(CONSTANTS["GETTER_CALLS"])
    | frozenset(CONSTANTS["P295_GETTER_CALLS"])
    | frozenset(CONSTANTS["HOST_GETTER_CALLS"])
    | frozenset(CONSTANTS["SUBSTANCE_GETTER_CALLS"])
    | frozenset(CONSTANTS["SUBSTANCE_VALUE_ARGS"])
)
INSERT_CALLS: frozenset[str] = frozenset(CONSTANTS["INSERT_CALLS"])
VALUE_ARGS: dict[str, str] = {
    **CONSTANTS["VALUE_ARGS"],
    **CONSTANTS["P295_VALUE_ARGS"],
    **CONSTANTS["HOST_VALUE_ARGS"],
    **CONSTANTS["SUBSTANCE_VALUE_ARGS"],
}
IMPORT_RESOURCE: str = CONSTANTS["IMPORT_RESOURCE"]
EVENT_CONNECT: str = CONSTANTS["EVENT_CONNECT"]
PROJECT_SAVE_AS: str = CONSTANTS["PROJECT_SAVE_AS"]
PROJECT_SAVE: str = CONSTANTS["PROJECT_SAVE"]
PROJECT_CLOSE: str = CONSTANTS["PROJECT_CLOSE"]
PROJECT_OPEN: str = CONSTANTS["PROJECT_OPEN"]
PROJECT_STATE: str = CONSTANTS["PROJECT_STATE"]
PROJECT_SAVE_AS_COPY: str = CONSTANTS["PROJECT_SAVE_AS_COPY"]
RELOAD_MESH: str = CONSTANTS["RELOAD_MESH"]
RELOAD_RESOURCES: str = CONSTANTS["RELOAD_RESOURCES"]
SHELVES_ADD: str = CONSTANTS["SHELVES_ADD"]
GET_NODE_BY_UID = "substance_painter.layerstack.get_node_by_uid"
# Plugin probes (decision 297): `plugins.path` with `folder` adds a plugin root the host writes
# under the run's private directory, shared by both recordings; the plugin calls name one of its
# throwaway modules by `module`.
PLUGINS_PATH: str = CONSTANTS["PLUGINS_PATH"]
PROBE_PLUGIN_MODULES: tuple[str, ...] = CONSTANTS["PROBE_PLUGIN_MODULES"]
PROBE_PLUGIN_FOLDERS: dict[str, str] = CONSTANTS["PROBE_PLUGIN_FOLDERS"]
PLUGIN_HOOK_LOG_FILE: str = CONSTANTS["PLUGIN_HOOK_LOG_FILE"]
PLUGIN_CALLS = frozenset(
    {
        CONSTANTS["START_PLUGIN"],
        CONSTANTS["CLOSE_PLUGIN"],
        CONSTANTS["RELOAD_PLUGIN"],
        CONSTANTS["IS_PLUGIN_STARTED"],
    }
)
PLUGIN_FOLDER, PLUGIN_MODULE = "folder", "module"
PLUGIN_HOOKS = ("start_plugin", "close_plugin", "reload_plugin")

# Step arguments naming an input by input_id; the recorder passes the staged file's path.
INPUT_ARGS = {ps.CREATE: "mesh", IMPORT_RESOURCE: "image", RELOAD_MESH: "mesh"}

# A file name in the recording's private work directory (saves, a missing mesh to reload).
WORK_FILE = "work_file"
SAVE_CALLS = frozenset({PROJECT_SAVE_AS, PROJECT_SAVE_AS_COPY, PROJECT_SAVE})
# `reload_modified_resources_async`: the staged input to overwrite, and the input it becomes.
REWRITE_ARGS = ("rewrite_input", "with_input")
REWRITE_AFTER_REOPEN = "with_input_after_reopen"
# `project.create` of an API probe (P21-A, P21-B; decision 110): mesh-map files (inputs whose id
# is the file stem Painter reads, `<texture set>_<suffix>`), and folders the host makes in the
# recording's private work directory for the default save and export paths.
MESH_MAPS = "mesh_maps"
CREATE_FOLDERS = ("default_save_path", "export_path")
# `Shelves.add` (P21-D): a folder the host makes in the work directory, holding copies of inputs.
SHELF_FOLDER, SHELF_INPUTS = "folder", "inputs"
# An export probe step without `exportPath` (P21-B): Painter chooses where the files go.
DEFAULT_EXPORT_PATH = "default_export_path"
# An export probe step whose `exportPath` is taken by a regular file the host made in the run's
# private directory, so the export fails (P22-B, `ExportStatus.Error`; decision 295).
EXPORT_PATH_BLOCKED = "export_path_blocked"
# The lifecycle procedure with `create` and `open` timed by a second thread (P21-F, decision 109).
TIMING_FLAG = "timing"
# `wait: false`: the step's events and states are recorded with the next step's.
WAIT_FLAG = "wait"
# Limit for a step's asynchronous calls to answer; one still pending is recorded, not refused.
ASYNC_TIMEOUT_S = 600.0

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
    wait: bool = True

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
    timing: bool = False
    keyed_export_steps: frozenset[int] = frozenset()

    @property
    def lifecycle(self) -> bool:
        return bool(self.events)

    @property
    def observed(self) -> bool:
        """Events are connected (step 2): every later step records its events and states."""
        return bool(self.state_steps) and self.state_steps[0].call == EVENT_CONNECT

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


def is_plain_name(value: Any) -> bool:
    return isinstance(value, str) and value not in ("", ".", "..") and Path(value).name == value


def input_arg_key(call: str, args: dict[str, Any]) -> str | None:
    """The API and semantics recorders author different import input keys."""
    if call == IMPORT_RESOURCE:
        keys = [key for key in ("image", "input") if key in args]
        if len(keys) != 1:
            raise RecorderError("an import requires exactly one of `image` or `input`")
        return keys[0]
    return INPUT_ARGS.get(call)


def check_input_arg(step: Step, inputs: dict[str, Path]) -> None:
    unique_keys = {"require_unique", "resource_context", "resource_name"}
    if unique_keys.intersection(step.args):
        args = step.args
        expected = (
            {"node_step", "channel", "search", *unique_keys}
            if step.call == ps.SET_SOURCE
            else {"inside_step", "node_stack", "search", *unique_keys}
            if step.call == ps.INSERT_FILTER
            else set()
        )
        node_key = "node_step" if step.call == ps.SET_SOURCE else "inside_step"
        if (
            not expected
            or set(args) != expected
            or args.get("require_unique") is not True
            or any(
                type(args.get(k)) is not str or not args[k]
                for k in ("search", "resource_context", "resource_name")
            )
            or type(args.get(node_key)) is not int
            or args[node_key] < 1
            or (
                step.call == ps.SET_SOURCE
                and (type(args.get("channel")) is not str or not args["channel"])
            )
            or (step.call == ps.INSERT_FILTER and args.get("node_stack") != "Content")
        ):
            raise RecorderError(
                "unique resource selection requires a closed source or Content Filter recipe"
            )
    if "key_by_step" in step.args:
        raise RecorderError("key_by_step is only valid on a final capture export")
    if "color_space_type" in step.args:
        args = step.args
        if (
            step.call != CONSTANTS["SET_BITMAP_COLOR_SPACE"]
            or set(args) != {"node_step", "channel", "color_space", "color_space_type"}
            or args["color_space_type"] != "str"
            or args["color_space"] != "sRGB"
            or type(args["node_step"]) is not int
            or args["node_step"] < 1
            or not isinstance(args["channel"], str)
            or not args["channel"]
        ):
            raise RecorderError("literal bitmap colour space requires a node, channel and str sRGB")
    work_file = step.args.get(WORK_FILE)
    if work_file is not None and not is_plain_name(work_file):
        raise RecorderError(f"step {step.step}: `{WORK_FILE}` must be a plain file name")
    if step.call in SAVE_CALLS - {PROJECT_SAVE} and work_file is None:
        raise RecorderError(f"step {step.step}: a save to a new file needs `{WORK_FILE}`")
    if step.call == ps.CREATE:
        check_create_args(step, inputs)
    if step.call == SHELVES_ADD and (
        not is_plain_name(step.args.get(SHELF_FOLDER))
        or not isinstance(step.args.get(SHELF_INPUTS), list)
        or not all(i in inputs for i in step.args[SHELF_INPUTS])
    ):
        raise RecorderError(
            f"step {step.step}: `Shelves.add` takes `{SHELF_FOLDER}` (a plain folder name) and "
            f"`{SHELF_INPUTS}` (inputs with a path, copied into it)"
        )
    check_plugin_args(step)
    rewrite = [step.args.get(key) for key in REWRITE_ARGS]
    if REWRITE_AFTER_REOPEN in step.args and (
        step.call != RELOAD_RESOURCES
        or not all(isinstance(value, str) and value in inputs for value in rewrite)
        or not isinstance(step.args[REWRITE_AFTER_REOPEN], str)
        or step.args[REWRITE_AFTER_REOPEN] not in inputs
    ):
        raise RecorderError(
            f"step {step.step}: `{REWRITE_AFTER_REOPEN}` requires a reload rewrite "
            "and must name an input"
        )
    if step.call == RELOAD_RESOURCES and any(rewrite) and not all(r in inputs for r in rewrite):
        raise RecorderError(
            f"step {step.step}: `{REWRITE_ARGS[0]}` and `{REWRITE_ARGS[1]}` must both name "
            "inputs with a path"
        )
    key = input_arg_key(step.call, step.args)
    if step.call == RELOAD_MESH and work_file is not None and key not in step.args:
        return  # a reload of a file that does not exist (the failing path)
    if key is not None and step.args.get(key) not in inputs:
        raise RecorderError(f"step {step.step}: `{key}` must name an input with a path")


def check_plugin_args(step: Step) -> None:
    """A plugin root is a plain folder name; a plugin call names a probe module (decision 297)."""
    folder = step.args.get(PLUGIN_FOLDER)
    if step.call == PLUGINS_PATH and folder is not None and not is_plain_name(folder):
        raise RecorderError(f"step {step.step}: `{PLUGIN_FOLDER}` must be a plain folder name")
    if step.call in PLUGIN_CALLS and step.args.get(PLUGIN_MODULE) not in PROBE_PLUGIN_MODULES:
        raise RecorderError(
            f"step {step.step}: `{PLUGIN_MODULE}` must name a probe plugin module "
            f"({', '.join(PROBE_PLUGIN_MODULES)})"
        )


def check_create_args(step: Step, inputs: dict[str, Path]) -> None:
    """The probe-only `project.create` arguments name inputs and plain folder names."""
    maps = step.args.get(MESH_MAPS)
    if maps is not None and (
        not isinstance(maps, list) or not maps or not all(m in inputs for m in maps)
    ):
        raise RecorderError(f"step {step.step}: `{MESH_MAPS}` must list inputs with a path")
    for name in CREATE_FOLDERS:
        if name in step.args and not is_plain_name(step.args[name]):
            raise RecorderError(f"step {step.step}: `{name}` must be a plain folder name")


def lifecycle_job(manifest: dict[str, Any], inputs: dict[str, Path], steps: list[Step]) -> ProbeJob:
    if tuple(s.call for s in steps) != LIFECYCLE_STEPS:
        raise RecorderError(f"a lifecycle probe must be exactly the steps {list(LIFECYCLE_STEPS)}")
    events = steps[0].args.get("events")
    if not isinstance(events, list) or not events or not all(isinstance(e, str) for e in events):
        raise RecorderError("step 1: `events` must list the event class names to connect")
    timing = steps[0].args.get(TIMING_FLAG, False)
    if not isinstance(timing, bool):
        raise RecorderError(f"step 1: `{TIMING_FLAG}` must be true or false")
    check_input_arg(steps[1], inputs)
    return ProbeJob(manifest, inputs, steps[1], (), (), (), tuple(events), timing)


def check_connect(step: Step, probe: bool) -> None:
    """The events of an observed probe golden are connected once, right after the project."""
    if step.step != 2 or probe:
        raise RecorderError(f"step {step.step}: events are connected by state step 2 only")
    events = step.args.get("events")
    if not isinstance(events, list) or not events or not all(isinstance(e, str) for e in events):
        raise RecorderError(f"step {step.step}: `events` must list the event class names")


def probe_job_from_manifest(manifest: dict[str, Any], repo_root: Path = REPO_ROOT) -> ProbeJob:
    inputs = checked_inputs(manifest, repo_root)
    steps = [
        Step(s["step"], s["call"], dict(s.get("args", {})))
        for s in manifest["instruction_sequence"]["steps"]
    ]
    if [s.step for s in steps] != list(range(1, len(steps) + 1)):
        raise RecorderError("instruction steps must be numbered 1..n in order")
    for step in steps:
        if {"require_unique", "resource_context", "resource_name"}.intersection(step.args):
            check_input_arg(step, inputs)
        if "color_space_type" in step.args and step.call != CONSTANTS["SET_BITMAP_COLOR_SPACE"]:
            raise RecorderError("color_space_type is only valid on the bitmap colour-space setter")
        if "key_by_step" in step.args and (
            step.call != EXPORT
            or step.args["key_by_step"] is not True
            or step.args.get(PROBE_FLAG, False) is not False
        ):
            raise RecorderError("key_by_step must be true on a final capture export")
    if steps and steps[0].call == EVENT_CONNECT:
        return lifecycle_job(manifest, inputs, steps)
    if not steps or steps[0].call != ps.CREATE:
        raise RecorderError("the instruction sequence must start with project.create")
    check_input_arg(steps[0], inputs)
    state: list[ProbeStep] = []
    probes: list[ProbeStep] = []
    exports: list[ExportStep] = []
    keyed_export_steps: set[int] = set()
    for step in steps[1:]:
        if "key_by_step" in step.args:
            keyed_export_steps.add(step.step)
        if step.call == EXPORT and step.args.get(PROBE_FLAG) is not True:
            exports.append(export_step(step))
            continue
        if exports:
            raise RecorderError(f"step {step.step}: probe steps must precede the captures")
        if step.call not in EDIT_CALLS | GETTER_CALLS | {EXPORT}:
            raise RecorderError(f"step {step.step}: {step.call} is not in the probe vocabulary")
        flag = step.args.pop(PROBE_FLAG, False)
        wait = step.args.pop(WAIT_FLAG, True)
        if not isinstance(flag, bool) or not isinstance(wait, bool):
            raise RecorderError(
                f"step {step.step}: `{PROBE_FLAG}` and `{WAIT_FLAG}` must be true or false"
            )
        if step.call == EXPORT:
            export_step(step)  # an export request among the probes: checked like a capture
        if step.call == EVENT_CONNECT:
            check_connect(step, flag)
        check_input_arg(step, inputs)
        probe = flag or is_read(step.call, step.args)
        if probe and step.call == IMPORT_RESOURCE:
            raise RecorderError(f"step {step.step}: an import cannot be a probe step")
        if not probe and probes:
            raise RecorderError(f"step {step.step}: state steps must precede the probe steps")
        (probes if probe else state).append(ProbeStep(step.step, step.call, step.args, probe, wait))
    if not probes:
        raise RecorderError("a probe golden needs at least one probe step")
    return ProbeJob(
        manifest,
        inputs,
        steps[0],
        tuple(state),
        tuple(probes),
        tuple(exports),
        (),
        keyed_export_steps=frozenset(keyed_export_steps),
    )


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


def shelf_folder(step: ProbeStep, staged: dict[str, Path], work_dir: Path) -> Path:
    """The folder a `Shelves.add` step names, made in the work directory with copies of its
    inputs (the shelf crawls it)."""
    folder: Path = work_dir / str(step.args[SHELF_FOLDER])
    folder.mkdir(parents=True, exist_ok=True)
    for input_id in step.args[SHELF_INPUTS]:
        shutil.copyfile(staged[input_id], folder / staged[input_id].name)
    return folder


def plugin_module_source(name: str, log: Path) -> str:
    """A throwaway plugin module: each hook (and the import) appends a line to the run's hook log,
    whose path is written in it (no process-wide setting points it anywhere: SUP-028), and the
    probe reads the log back."""
    lines = [
        "def _hook(entry):",
        f"    with open({log.as_posix()!r}, 'a', encoding='utf-8') as log:",
        f"        log.write({name!r} + '.' + entry + '\\n')",
        "",
        "",
        *(f"def {hook}():\n    _hook({hook!r})\n\n" for hook in PLUGIN_HOOKS),
        "_hook('import')",
    ]
    return "\n".join(lines) + "\n"


def plugin_root(step: ProbeStep, work_dir: Path) -> Path:
    """The probe's plugin root (`plugins/`, `startup/`, `modules/`) under the run's private
    directory, the same for both recordings, with the throwaway modules written in it."""
    root: Path = work_dir.parents[1] / "plugin-roots" / str(step.args[PLUGIN_FOLDER])
    for sub in ("plugins", "startup", "modules"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    for name in PROBE_PLUGIN_MODULES:
        source = plugin_module_source(name, root / PLUGIN_HOOK_LOG_FILE)
        (root / PROBE_PLUGIN_FOLDERS[name] / f"{name}.py").write_text(source, encoding="utf-8")
    return root


def run_step(
    session: PainterSession, step: ProbeStep, staged: dict[str, Path], work_dir: Path
) -> dict[str, Any]:
    resolved: dict[str, str] = {}
    key = input_arg_key(step.call, step.args)
    if key is not None and key in step.args:
        transport_key = "image" if step.call == IMPORT_RESOURCE else key
        resolved[transport_key] = staged[step.args[key]].as_posix()
    if WORK_FILE in step.args:
        work_dir.mkdir(parents=True, exist_ok=True)
        resolved[WORK_FILE] = (work_dir / step.args[WORK_FILE]).as_posix()
    if step.call == SHELVES_ADD:
        resolved["shelf_path"] = shelf_folder(step, staged, work_dir).as_posix()
    if step.call == PLUGINS_PATH and PLUGIN_FOLDER in step.args:
        resolved["plugin_root"] = plugin_root(step, work_dir).as_posix()
    if step.call == RELOAD_RESOURCES and REWRITE_ARGS[0] in step.args:
        target, source = (step.args[name] for name in REWRITE_ARGS)
        shutil.copyfile(staged[source], staged[target])
    outcome: dict[str, Any] = session.call(
        "probe_step", step=step.step, call=step.call, args=step.args, resolved=resolved
    )
    return outcome


def work_files(directory: Path) -> list[str]:
    """Names of the files under a private work directory (relative paths, sorted)."""
    if not directory.is_dir():
        return []
    return sorted(p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file())


def observe(session: PainterSession, step: ProbeStep) -> list[dict[str, Any]]:
    """After an observed step: the states polled until its asynchronous calls answered (and
    `SETTLE_POLLS` more), then the events dispatched since the previous step."""
    states: list[dict[str, Any]] = []

    def note() -> list[str]:
        polled = dict(session.call("probe_state"))
        pending: list[str] = polled.pop("pending")
        if not states or states[-1] != polled:
            states.append(polled)
        return pending

    deadline = session.monotonic() + ASYNC_TIMEOUT_S
    pending = note()
    while pending and session.monotonic() < deadline:
        session.sleep(session.poll_interval_s)
        pending = note()
    for _ in range(SETTLE_POLLS):
        session.sleep(session.poll_interval_s)
        pending = note()
    events = session.call("events_take")["events"]
    args = {"step": step.step}
    outputs = [
        readback(f"s{step.step}/events", EVENT_CONNECT, args, {"value": events}),
        readback(f"s{step.step}/states", PROJECT_STATE, args, {"value": states}),
    ]
    if pending:
        outputs.append(readback(f"s{step.step}/pending", EVENT_CONNECT, args, {"value": pending}))
    return outputs


def step_outputs(
    session: PainterSession,
    job: ProbeJob,
    step: ProbeStep,
    work_dir: Path,
    outcome: dict[str, Any],
) -> list[dict[str, Any]]:
    """A step's readback, then (observed goldens) its events and states, and the work files
    after a save."""
    outputs = [readback(step.output_id, step.call, step.args, outcome)]
    if job.observed and step.call != EVENT_CONNECT and step.wait:
        outputs += observe(session, step)
    if step.call in SAVE_CALLS:
        files = {"value": work_files(work_dir)}
        outputs.append(readback(f"s{step.step}/files", step.call, {"step": step.step}, files))
    return outputs


def probe_export(
    session: PainterSession,
    job: ProbeJob,
    step: ProbeStep,
    template: dict[str, Any],
    directory: Path,
) -> list[dict[str, Any]]:
    """An export request among the probe steps: its result or error, then (once the step
    settled) the files in its directory with their SHA-256, compared by the capture exports."""
    export = export_step(Step(step.step, EXPORT, step.args))
    export_dir = directory / f"probe-export-step{step.step}"
    if step.args.get(EXPORT_PATH_BLOCKED) is True:
        export_dir.parent.mkdir(parents=True, exist_ok=True)
        export_dir.write_bytes(b"")
    else:
        export_dir.mkdir(parents=True)
    roots = [ts if not st else f"{ts}/{st}" for ts, st in export_roots(template)]
    config = export.config(export_dir, roots)
    default_path = step.args.get(DEFAULT_EXPORT_PATH) is True
    if default_path:
        del config["exportPath"]
    outcome = session.call("probe_export", step=step.step, config=config, locations=default_path)
    outputs = [readback(step.output_id, step.call, step.args, outcome)]
    if job.observed and step.wait:
        outputs += observe(session, step)
    files = [
        {"file_name": name, "sha256": sha256_file(export_dir / name)}
        for name in work_files(export_dir)
    ]
    if default_path:
        files = located_files(outcome, directory.parent)
    outputs.append(readback(f"s{step.step}/files", EXPORT, {"step": step.step}, {"value": files}))
    return outputs


def located_files(outcome: dict[str, Any], run_dir: Path) -> list[dict[str, Any]]:
    """The files an export without `exportPath` reported under the run's private directory,
    with their SHA-256 (a file Painter wrote elsewhere is listed by its returned location)."""
    files: list[dict[str, Any]] = []
    value = outcome.get("value") or {}
    for located in value.get("locations", {}).values():
        for where in located:
            parts = where.get("run_relative") if isinstance(where, dict) else None
            if parts is None:
                files.append({"location": where})
                continue
            path = run_dir.joinpath(*parts)
            digest = sha256_file(path) if path.is_file() else None
            files.append({"file_name": "/".join(parts), "sha256": digest})
    return files


def create_resolved(job: ProbeJob, staged: dict[str, Path], work_dir: Path) -> dict[str, Any]:
    """The staged mesh, and for an API probe its mesh-map files and default folders."""
    args = job.create.args
    resolved: dict[str, Any] = {"mesh": staged[args["mesh"]].as_posix()}
    if MESH_MAPS in args:
        resolved[MESH_MAPS] = [staged[m].as_posix() for m in args[MESH_MAPS]]
    for name in CREATE_FOLDERS:
        if name in args:
            folder = work_dir / args[name]
            folder.mkdir(parents=True, exist_ok=True)
            resolved[name] = folder.as_posix()
    return resolved


def create_project(
    session: PainterSession, job: ProbeJob, staged: dict[str, Path], work_dir: Path
) -> Any:
    return session.call(
        "apply_step",
        step=job.create.step,
        call=job.create.call,
        args=job.create.args,
        resolved=create_resolved(job, staged, work_dir),
    )


def apply_state(
    session: PainterSession, job: ProbeJob, staged: dict[str, Path], work_dir: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Create the project and apply the state steps once; returns defaults and step outcomes."""
    created = create_project(session, job, staged, work_dir)
    session.wait_ready()
    defaults: dict[str, Any] = {
        "project.create": session.call("template_capture"),
        "colour_management": created["colour_management"],
        "inserted": {},
    }
    outcomes: list[dict[str, Any]] = []
    closed: dict[str, Any] = {}
    for step in job.state_steps:
        outcome = run_step_rebinding(session, step, staged, work_dir, closed)
        if "defaults" in outcome:
            defaults["inserted"][str(step.step)] = outcome["defaults"]
        outcomes += step_outputs(session, job, step, work_dir, outcome)
        outcomes += rebound(session, step, closed)
    session.wait_ready()
    return defaults, outcomes


def run_step_rebinding(
    session: PainterSession,
    step: ProbeStep,
    staged: dict[str, Path],
    work_dir: Path,
    closed: dict[str, Any],
) -> dict[str, Any]:
    """Run a step; before a `project.close` the inserted nodes' places are kept, so the nodes
    can be found again once a later `project.open` has loaded the project (P21-G)."""
    if step.call == PROJECT_CLOSE:
        closed["locations"] = session.call("probe_locations")
    return run_step(session, step, staged, work_dir)


def rebound(session: PainterSession, step: ProbeStep, closed: dict[str, Any]) -> list[Any]:
    """After a `project.open` step settled: the inserted nodes found again (`s<n>/rebind`)."""
    if step.call != PROJECT_OPEN:
        return []
    session.wait_ready()
    found = session.call("probe_rebind", locations=closed.get("locations", {}))
    return [readback(f"s{step.step}/rebind", GET_NODE_BY_UID, {}, {"value": found})]


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


def step_for_recording(step: ProbeStep, condition: str) -> ProbeStep:
    """Resolve a reload's staged replacement without changing the pinned instruction sequence."""
    if condition != "after_save_reopen" or REWRITE_AFTER_REOPEN not in step.args:
        return step
    return replace(step, args={**step.args, "with_input": step.args[REWRITE_AFTER_REOPEN]})


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
    staged: dict[str, Path],
) -> tuple[dict[str, Any], list[Path]]:
    session.wait_ready()
    template = session.call("template_capture")
    if job.observed:
        # Events since the last recorded step (r2: the save, close and reopen).
        events = {"value": session.call("events_take")["events"]}
        first_outputs = [*first_outputs, readback("start/events", EVENT_CONNECT, {}, events)]
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
    work_dir = directory / "work-files"
    closed: dict[str, Any] = {}
    for step in job.probe_steps:
        step = step_for_recording(step, condition)
        if step.call == EXPORT:
            outputs += probe_export(session, job, step, template, directory)
            continue
        outcome = run_step_rebinding(session, step, staged, work_dir, closed)
        outputs += step_outputs(session, job, step, work_dir, outcome)
        outputs += rebound(session, step, closed)
    blobs: list[Path] = []
    for export in job.exports:
        keyed = (
            frozenset(out.name for out in export.maps)
            if export.step in job.keyed_export_steps
            else frozenset()
        )
        exported, files = export_outputs(session, export, template, directory, keyed)
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


class CleanupFailed(RecorderError):
    """Painter's state was not all restored after a probe golden (SUP-017): nothing was written
    to the inbox. A recording error the cleanup followed is the exception's cause."""


def preflight(session: PainterSession, job: ProbeJob) -> None:
    """Before the run changes anything, Painter refuses it if a shelf it adds exists already or a
    probe plugin module it uses could be someone else's (SUP-016); the refusal is the recorder's
    failure, never evidence."""
    steps = (*job.state_steps, *job.probe_steps)
    shelves = sorted({str(s.args["name"]) for s in steps if s.call == SHELVES_ADD})
    plugins = any(s.call == PLUGINS_PATH or s.call in PLUGIN_CALLS for s in steps)
    if shelves or plugins:
        modules = list(PROBE_PLUGIN_MODULES) if plugins else []
        session.call("probe_preflight", shelves=shelves, modules=modules)


def finish_probe(session: PainterSession) -> list[str]:
    """Re-enable engine computations a probe disabled, disconnect the events and restore the
    host-module state, discard the throwaway project, then remove the shelves and plugin state a
    probe added. Every stage runs whatever an earlier one did; returns what failed (SUP-017)."""
    failures: list[str] = []
    for operation in ("probe_finish", "close_project", "probe_cleanup"):
        # Any failure of a stage, the transport's or a malformed reply's too (SUP-028), is listed
        # and the next stage still runs; the caller publishes nothing then.
        try:
            result = session.call(operation)
            failures += [
                f"{operation} {f['stage']}: {f['raised']['type']}: {f['raised']['message']}"
                for f in result.get("cleanup_failures", [])
            ]
        except Exception as error:
            failures.append(f"{operation}: {error!r}")
    return failures


def cleanup_refusal(failures: list[str]) -> str:
    return "Painter's state was not restored, nothing was written: " + "; ".join(failures)


def record_api_probe(
    session: PainterSession, job: ProbeJob, work: Path, inbox: Path, now: Now, record_prefix: str
) -> Path:
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
    try:
        session.call("probe_reset", root=directory.as_posix())
        defaults, outcomes = apply_state(session, job, staged, directory / "r1" / "work-files")
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
        )
        session.wait_ready()
        locations = session.call("probe_locations")
        save_and_reopen(session, directory / "project" / "probe.spp")
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
            [rebind],
            now,
            staged,
        )
    except BaseException as error:
        # The recording error stays the one raised; a failed cleanup is added to it.
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

    def create() -> Any:
        if not job.timing:
            return create_project(session, job, staged, project_file.parent)
        resolved = create_resolved(job, staged, project_file.parent)
        return session.call("timed_call", phase="create", args=job.create.args, resolved=resolved)

    def open_() -> Any:
        if not job.timing:
            return session.call("open_project", path=path)
        return session.call("timed_call", phase="open", path=path)

    created = [
        *lifecycle_phase(session, "create", create, ready),
        *timing_outputs(session, job, "create"),
        *lifecycle_phase(
            session, "save_as", lambda: session.call("save_as", path=path), saved_to_file
        ),
        *lifecycle_phase(session, "close", lambda: session.call("close_project"), closed),
    ]
    reopened = [
        *lifecycle_phase(session, "open", open_, ready),
        *timing_outputs(session, job, "open"),
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


def timing_outputs(session: PainterSession, job: ProbeJob, phase: str) -> list[dict[str, Any]]:
    """A timed lifecycle's `<phase>/thread_polls`: the second thread's readiness polls."""
    if not job.timing:
        return []
    polls = session.call("timing_take")
    args = {"phase": phase}
    return [readback(f"{phase}/thread_polls", PROJECT_STATE, args, {"value": polls})]


def record_lifecycle(
    session: PainterSession, job: ProbeJob, work: Path, inbox: Path, now: Now, record_prefix: str
) -> Path:
    identity = session.connect()
    require_colour_management(job, identity)
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
    return write_run(
        inbox,
        record,
        [],
        job.manifest,
        identity.session_id,
        environment=identity.environment,
        record_prefix=record_prefix,
    )


def record_probe_golden(
    session: PainterSession,
    job: ProbeJob,
    work: Path,
    inbox: Path,
    now: Now = utc_now,
    *,
    record_prefix: str = "",
) -> Path:
    """Record one API-probe golden and write it to the inbox; returns the run directory."""
    if job.tier != "0":
        raise RecorderError("API probes are Tier 0 goldens")
    if job.lifecycle:
        return record_lifecycle(session, job, work, inbox, now, record_prefix)
    return record_api_probe(session, job, work, inbox, now, record_prefix)


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
    except UnseenBuild as error:
        from tools.parity.recorder.__main__ import refresh_after_unseen_build

        return refresh_after_unseen_build(args, error)
    except RecorderError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    print(f"recorded: {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
