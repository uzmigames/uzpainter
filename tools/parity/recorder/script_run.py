r"""Tier 1 goldens from UzmiGames pipeline scripts run byte-unchanged in Painter (decision 099).

    python -m tools.parity.recorder record-script <manifest.json> --assets-root <Assets3D>
    python -m tools.parity.recorder.script_run manifest --assets-root <Assets3D> --out <path> \
        [--pilot wand|wand-float|wand-normal-float|belt|sash|tunic|tunic-rebuild|
                 wand-gltf|sash-gltf|tunic-gltf] [--store]

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
another copy. An input resolves at its `assets3d_path` when the file there holds the pinned bytes,
else from the private store by its hash (`tools.parity.store`, `input` command): Assets3D's `_tmp`
is volatile, and a pin must outlive it (decision 144). Two adaptations, both by the recorder, are
the only changes to how the scripts run:

a. **Repointed arguments.** The inputs are hash-checked under `--assets-root` and copied into the
   private work directory. Each Painter-side script runs in a fresh namespace whose `open` maps
   exactly its one hard-coded arguments path (as written in the script) to a copy of the
   arguments file in which `mesh`, `normal` and `ao` name the staged copies, `dst` a project in
   the work directory and `out` a fresh export directory; every other key is unchanged
   (`painter_scripts.py`).
b. **Transport swap.** The sync script's own `execute(code, token=None)` is replaced by the
   recorder's remote control with the same contract (run the code in Painter, return the `result`
   it assigns), so the Painter-side code the script builds is the script's own. Its route guard
   (Assets3D `9a718b9`, decision 144) sends its own probe (`GUARD_CODE`) through the same function
   before the sync; the modules the script imports from Assets3D (`route_check`; `run` since
   Assets3D c6b74c2) are pinned inputs named by the sync step's `imports` and loaded from their
   pinned bytes for the run. The
   project lies in the private work directory, outside a production character's folder, so the
   guard passes without an attempt token; any other verdict is refused.

A sync step may also carry, for a current round (decision 300 item 7):

- `resource_prefix`, `resource_group` and `texture_set`: narrowly typed values the recorder
  appends to the command line as the script's own `--resource-prefix`, `--resource-group` and
  `--texture-set` options, in that order; the guard probe the script must send is the one for
  that texture set. Without them the command line is the legacy one.
- `import_closure`: the pinned helpers the `imports` import when they are imported. The job
  resolves every import-time import of the sync script and of each pinned module (the standard
  library, or a pinned module; a helper lies next to the module importing it) and refuses a
  missing, unpinned, unreachable, duplicate or cyclic module; the run loads the helpers first.
- `mask_folder` in place of `masks` and `mask_files` (the public schema bounds a list at 16
  items): the bitmaps are exactly the mask and image inputs in that Assets3D folder.

A fourth step may close the sequence: `substance_painter.export.export_project_textures` with
`config`, an authored `recipe_json` repository file holding the `json_config` without `exportPath`
(as a migration golden's export, decision 194). The recorder runs it after every script export,
on the same document, into a fresh directory of its own: the Wand's float recording exports the
same maps as OpenEXR 32f with the script's padding (decision 283).

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
import copy
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import re
import shutil
import sys
import sysconfig
import types
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from tools.parity.recorder.capture import (
    MEDIA_TYPES,
    measure_storage_format,
    verify_current_outputs,
    write_fence,
)
from tools.parity.recorder.job import (
    Job,
    canonical_json,
    pinned_assets3d_file,
    sha256_bytes,
    sha256_file,
)
from tools.parity.recorder.output import ensure_outside_repository, run_name, write_run
from tools.parity.recorder.session import PainterIdentity, PainterSession, RecorderError
from tools.parity.recorder.sidecars import gltf_sidecars
from tools.parity.recorder.texture import (
    UNDETERMINED,
    Now,
    close_quietly,
    output_safe,
    require_colour_management,
    utc_now,
)
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors
from tools.parity.store.store import OracleStore, Status, locate

INTERFACE = "uzmigames_pipeline_scripts"
RUN_SCRIPT = "uzmigames.pipeline.run_script"
ASSETS3D_LICENCE = "LicenseRef-UzmiGames-Assets3D"
PAINTER_SCRIPTS = Path(__file__).with_name("painter_scripts.py")
PAINTER_NATIVE = Path(__file__).with_name("painter_native.py")  # the native create's mesh map

# Step argument names of each step; an input argument names the kinds its input may have.
CREATE_INPUTS = {
    "script": ("pipeline_script",),
    "args_file": ("recipe_json",),
    "mesh": ("mesh",),
    "mesh_material_library": ("mesh",),
    "normal": ("image",),
    "ao": ("image",),
}
SYNC_ARGS = frozenset({"script", "command", "stack", "masks", "mask_files", "imports"})
SYNC_FOLDER_ARGS = frozenset({"script", "command", "stack", "mask_folder", "imports"})
IMPORT_CLOSURE = "import_closure"
# The optional sync options: argument -> (the sync script's flag, the values it may take). Each
# given option becomes `flag value` on the command line, in this order.
SYNC_OPTIONS: dict[str, tuple[str, re.Pattern[str]]] = {
    "resource_prefix": ("--resource-prefix", re.compile(r"[A-Za-z0-9_]{1,32}")),
    "resource_group": ("--resource-group", re.compile(r"[A-Za-z0-9_]{1,64}")),
    "texture_set": ("--texture-set", re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")),
}
EXPORT_INPUTS = {"script": ("pipeline_script",), "args_file": ("recipe_json",)}
MASK_KINDS = ("mask", "image")
SYNC_COMMAND = "sync"
# The optional closing step: the recorder's export of an authored `json_config` (decision 283).
CONFIG_EXPORT = "substance_painter.export.export_project_textures"
# Keys of an export `json_config` the authored configuration may hold (`exportPath` is the
# recorder's, a fresh private directory per recording).
CONFIG_KEYS = frozenset(
    {"exportShaderParams", "defaultExportPreset", "exportPresets", "exportList", "exportParameters"}
)

# The recorder-native create (decision 300 item 7, the Tunic): `project.create` from a staged
# mesh with every `project.Settings` field the recorder passes given explicitly, no template, one
# texture set, and one mesh map, the named Normal, imported as a project resource and bound.
NATIVE_CREATE = "substance_painter.project.create"
NATIVE_INPUTS = {"mesh": ("mesh",), "mesh_material_library": ("mesh",), "normal": ("image",)}
NATIVE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
NATIVE_NAMES = ("texture_set", "normal_name", "normal_group")
# Each setting and the values it may take (painter_side.py's documented members).
NATIVE_SETTINGS: dict[str, Callable[[Any], bool]] = {
    "normal_map_format": lambda v: v in ("OpenGL", "DirectX"),
    "tangent_space_mode": lambda v: v in ("PerVertex", "PerFragment"),
    "project_workflow": lambda v: v in ("Default", "TextureSetPerUVTile", "UVTile"),
    "default_texture_resolution": lambda v: (
        type(v) is int and v in (128, 256, 512, 1024, 2048, 4096, 8192)
    ),
    "import_cameras": lambda v: type(v) is bool,
    "mesh_unit_scale": lambda v: type(v) in (int, float) and v > 0,
}
NATIVE_ARGS = frozenset({*NATIVE_INPUTS, *NATIVE_NAMES, *NATIVE_SETTINGS})
NORMAL_USAGE = "Normal"  # the one mesh-map slot the native create binds
# The ten `textureset.MeshMapUsage` slots a readback must hold (painter_side.MESH_MAP_USAGES),
# and the fields of a resource readback (painter_side.resource_id_value).
MESH_MAP_SLOTS = frozenset(
    {
        "Normal",
        "WorldSpaceNormal",
        "ID",
        "AO",
        "Curvature",
        "Position",
        "Thickness",
        "Height",
        "BentNormals",
        "Opacity",
    }
)
RESOURCE_FIELDS = frozenset({"url", "context", "name", "version"})
PROJECT_CONTEXT = re.compile(r"project[0-9]+")  # the context a reopen may renumber
GET_MESH_MAP = "substance_painter.textureset.TextureSet.get_mesh_map_resource"
# The optional F03-style override of a sync's stack: the stack must be the recipe (a recipe_json
# input, at `recipe_keys`) with exactly one layer's mask replaced, nothing else (decision 194).
SYNC_OVERRIDE = ("recipe", "recipe_keys", "override_layer", "override_mask")

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

    @property
    def module(self) -> str:
        """The module name an import of this file uses: its file stem."""
        return PurePosixPath(self.assets3d_path).stem


@dataclass(frozen=True)
class ScriptStep:
    step: int
    args: dict[str, Any]
    script: PinnedInput
    hard_coded_args: str | None = None  # the arguments path as written in the script
    arguments: dict[str, Any] | None = None  # the authored arguments file
    imports: tuple[PinnedInput, ...] = ()  # pinned modules the sync script imports
    masks: tuple[PinnedInput, ...] = ()  # the sync's bitmaps, in one folder
    options: tuple[tuple[str, str], ...] = ()  # the sync's optional `flag value` pairs, in order
    load_order: tuple[PinnedInput, ...] = ()  # pinned modules loaded first, dependencies first


@dataclass(frozen=True)
class NativeCreate:
    """The recorder-native create step: the staged mesh, the Normal, the settings and names."""

    step: int
    args: dict[str, Any]
    mesh: PinnedInput
    normal: PinnedInput

    @property
    def settings(self) -> dict[str, Any]:
        return {key: self.args[key] for key in NATIVE_SETTINGS}


@dataclass(frozen=True)
class ConfigExport:
    """The closing recorder export: an authored `json_config` (a repository file)."""

    step: int
    config_id: str
    config: dict[str, Any]


@dataclass(frozen=True)
class ScriptJob:
    manifest: dict[str, Any]
    inputs: dict[str, PinnedInput]
    create: ScriptStep
    sync: ScriptStep
    export: ScriptStep
    config_export: ConfigExport | None = None

    @property
    def golden_id(self) -> str:
        return str(self.manifest["golden_id"])

    def input_hashes(self) -> list[dict[str, str]]:
        return [{"input_id": i["input_id"], "sha256": i["sha256"]} for i in self.manifest["inputs"]]


@dataclass(frozen=True)
class NativeJob:
    """A current round the recorder creates itself (decision 300 item 7, the Tunic): the native
    create, the unchanged sync, and the closing config export as the only export."""

    manifest: dict[str, Any]
    inputs: dict[str, PinnedInput]
    create: NativeCreate
    sync: ScriptStep
    config_export: ConfigExport

    @property
    def golden_id(self) -> str:
        return str(self.manifest["golden_id"])

    def input_hashes(self) -> list[dict[str, str]]:
        return [{"input_id": i["input_id"], "sha256": i["sha256"]} for i in self.manifest["inputs"]]


def tail_matches(path: str, assets3d_path: str) -> bool:
    """`path` (as a script or arguments file writes it) ends with the Assets3D-relative path."""
    written = PureWindowsPath(path).as_posix().lower()
    return written.endswith("/" + assets3d_path.lower())


def input_file(item: dict[str, Any], assets_root: Path, store: OracleStore | None) -> Path:
    """The file holding an input's pinned bytes: its Assets3D path when the file there matches the
    pin, else the private store's blob of that hash; refused when neither holds them."""
    return pinned_assets3d_file(item, assets_root, store)


def pinned_inputs(
    manifest: dict[str, Any], assets_root: Path, store: OracleStore | None
) -> dict[str, PinnedInput]:
    inputs: dict[str, PinnedInput] = {}
    for item in manifest["inputs"]:
        if "path" in item:
            continue  # a repository file: only a config export's configuration (checked by the job)
        where = f"input {item['input_id']}"
        if "assets3d_path" not in item or item["provenance"]["licence"] != ASSETS3D_LICENCE:
            raise RecorderError(f"{where}: a pipeline-script job names Assets3D inputs only")
        file = input_file(item, assets_root, store)
        data = file.read_bytes() if item["kind"] == "pipeline_script" else None
        if data is not None and sha256_bytes(data) != item["sha256"]:
            raise RecorderError(f"{where}: {file} changed while it was read")
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


def imported_modules(script: PinnedInput) -> set[str]:
    """Top-level module names the script's `import` and `from ... import` statements name."""
    assert script.data is not None
    names: set[str] = set()
    for node in ast.walk(ast.parse(script.data, filename=script.name)):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


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
    optional = {*SYNC_OPTIONS, IMPORT_CLOSURE, *SYNC_OVERRIDE}
    if set(args) - optional in (SYNC_ARGS, SYNC_FOLDER_ARGS):
        return "sync", sync_step(step, args, inputs)
    raise RecorderError(f"step {step}: arguments {sorted(args)} are no create, sync or export")


def sync_step(step: int, args: dict[str, Any], inputs: dict[str, PinnedInput]) -> ScriptStep:
    script = input_of(inputs, step, "script", args["script"], ("pipeline_script",))
    if args["command"] != SYNC_COMMAND:
        raise RecorderError(f"step {step}: only the `{SYNC_COMMAND}` command is recorded")
    stack = input_of(inputs, step, "stack", args["stack"], ("recipe_json",))
    stack_json = json.loads(stack.file.read_bytes().decode("utf-8"))
    if any(key in args for key in SYNC_OVERRIDE):
        stack_override(step, args, inputs, stack_json)
    files = sync_masks(step, args, inputs)
    names = [f.name for f in files]
    referenced = stack_bitmaps(stack_json)
    if sorted(referenced) != sorted(PurePosixPath(n).stem for n in names):
        raise RecorderError(
            f"step {step}: the stack references the bitmaps {sorted(referenced)}, not the "
            f"masks given {sorted(names)}"
        )
    if not isinstance(args["imports"], list):
        raise RecorderError(f"step {step}: `imports` must be a list of pipeline-script inputs")
    modules = tuple(
        input_of(inputs, step, "imports", m, ("pipeline_script",)) for m in args["imports"]
    )
    missing = {m.module for m in modules} - imported_modules(script)
    if missing:
        raise RecorderError(f"step {step}: {script.name} imports no module {sorted(missing)}")
    load_order = modules
    if IMPORT_CLOSURE in args:
        load_order = import_closure(step, script, modules, args[IMPORT_CLOSURE], inputs)
    return ScriptStep(
        step,
        args,
        script,
        imports=modules,
        masks=tuple(files),
        options=sync_options(step, args, script),
        load_order=load_order,
    )


def stack_override(
    step: int, args: dict[str, Any], inputs: dict[str, PinnedInput], stack: Any
) -> None:
    """The stack is the recipe (the `recipe` input at `recipe_keys`) with exactly one layer,
    `override_layer`, binding `override_mask` instead of its own mask, and nothing else changed
    (the Tunic's F03 override, decision 194); refused otherwise."""
    if not all(key in args for key in SYNC_OVERRIDE):
        raise RecorderError(f"step {step}: an override names all of {list(SYNC_OVERRIDE)}")
    source = input_of(inputs, step, "recipe", args["recipe"], ("recipe_json",))
    keys, layer_id, mask = args["recipe_keys"], args["override_layer"], args["override_mask"]
    if not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
        raise RecorderError(f"step {step}: `recipe_keys` must be a list of keys")
    for key, value in (("override_layer", layer_id), ("override_mask", mask)):
        if not isinstance(value, str) or not NATIVE_NAME.fullmatch(value):
            raise RecorderError(f"step {step}: `{key}` must match {NATIVE_NAME.pattern}")
    recipe: Any = json.loads(source.file.read_bytes().decode("utf-8"))
    for key in keys:
        if not isinstance(recipe, dict) or key not in recipe:
            raise RecorderError(f"step {step}: {source.name} holds no {'.'.join(keys)}")
        recipe = recipe[key]
    if not isinstance(recipe, dict) or not isinstance(recipe.get("layers"), list):
        raise RecorderError(f"step {step}: {'.'.join(keys)} is no stack with layers")
    derived = copy.deepcopy(recipe)
    layers = [x for x in derived["layers"] if isinstance(x, dict) and x.get("id") == layer_id]
    if len(layers) != 1:
        raise RecorderError(
            f"step {step}: the recipe has {len(layers)} layers {layer_id!r}, not exactly one"
        )
    if layers[0].get("mask") == mask:
        raise RecorderError(f"step {step}: {layer_id} already binds {mask}: nothing to override")
    layers[0]["mask"] = mask
    if derived != stack:
        raise RecorderError(
            f"step {step}: the stack is not the recipe with {layer_id} alone binding {mask}"
        )


def sync_masks(
    step: int, args: dict[str, Any], inputs: dict[str, PinnedInput]
) -> list[PinnedInput]:
    """The sync's bitmaps: the parallel `masks` and `mask_files` lists, or every input in the
    `mask_folder` (each a mask or image named `<bitmap>.png`, none twice)."""
    if "mask_folder" not in args:
        masks, names = args["masks"], args["mask_files"]
        if not isinstance(masks, list) or not isinstance(names, list) or len(masks) != len(names):
            raise RecorderError(f"step {step}: `masks` and `mask_files` must be parallel lists")
        files = [input_of(inputs, step, "masks", m, MASK_KINDS) for m in masks]
        if [f.name for f in files] != names:
            raise RecorderError(f"step {step}: `mask_files` must be the masks' file names")
        if len({PurePosixPath(f.assets3d_path).parent for f in files}) != 1:
            raise RecorderError(f"step {step}: the masks must share one folder")
        return files
    folder = args["mask_folder"]
    if not isinstance(folder, str) or not folder:
        raise RecorderError(f"step {step}: `mask_folder` must name an Assets3D folder")
    files = sorted(
        (
            i
            for i in inputs.values()
            if PurePosixPath(i.assets3d_path).parent == PurePosixPath(folder)
        ),
        key=lambda i: i.name,
    )
    if not files:
        raise RecorderError(f"step {step}: no input lies in the mask folder {folder}")
    others = sorted(f.input_id for f in files if f.kind not in MASK_KINDS)
    if others:
        raise RecorderError(f"step {step}: the mask folder {folder} also holds {others}")
    names = [f.name for f in files]
    if len(set(names)) != len(names) or any(PurePosixPath(n).suffix != ".png" for n in names):
        raise RecorderError(f"step {step}: the mask folder must hold each bitmap once, as .png")
    return files


def string_constants(script: PinnedInput) -> set[str]:
    assert script.data is not None
    return {
        node.value
        for node in ast.walk(ast.parse(script.data, filename=script.name))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def sync_options(
    step: int, args: dict[str, Any], script: PinnedInput
) -> tuple[tuple[str, str], ...]:
    """The optional sync options given, as `(flag, value)` in `SYNC_OPTIONS` order; refused on a
    value of another shape or a flag the pinned script does not name."""
    options: list[tuple[str, str]] = []
    for key, (flag, pattern) in SYNC_OPTIONS.items():
        if key not in args:
            continue
        value = args[key]
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise RecorderError(f"step {step}: `{key}` must match {pattern.pattern} ({value!r})")
        if flag not in string_constants(script):
            raise RecorderError(f"step {step}: {script.name} defines no {flag} option")
        options.append((flag, value))
    return tuple(options)


def catches_import_error(node: ast.Try) -> bool:
    """Whether a handler of the `try` catches `ImportError` (bare, `ImportError`, `Exception` or
    `BaseException`; `ModuleNotFoundError` does not catch a failed relative import)."""
    names = {"ImportError", "Exception", "BaseException"}
    for handler in node.handlers:
        kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        if any(k is None or (isinstance(k, ast.Name) and k.id in names) for k in kinds):
            return True
    return False


def import_time_imports(item: PinnedInput) -> list[tuple[int, str, int, bool]]:
    """`(line, module, level, guarded)` of every import a module runs when it is imported: at
    module scope, including `try`, `if`, `with` and class bodies, never inside a function.
    `from . import a` gives `a` at level 1; `guarded` is whether a `try` around it catches
    `ImportError`."""
    assert item.data is not None
    found: list[tuple[int, str, int, bool]] = []

    def visit(nodes: Any, guarded: bool) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(node, ast.Import):
                found.extend((node.lineno, alias.name, 0, guarded) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    found.append((node.lineno, node.module, node.level, guarded))
                else:
                    found.extend(
                        (node.lineno, alias.name, node.level, guarded) for alias in node.names
                    )
            elif isinstance(node, ast.Try):
                visit(node.body, guarded or catches_import_error(node))
                for handler in node.handlers:
                    visit(handler.body, guarded)
                visit(node.orelse, guarded)
                visit(node.finalbody, guarded)
            else:
                visit(ast.iter_child_nodes(node), guarded)

    visit(ast.parse(item.data, filename=item.name).body, False)
    return found


def import_closure(
    step: int,
    script: PinnedInput,
    imports: tuple[PinnedInput, ...],
    names: Any,
    inputs: dict[str, PinnedInput],
) -> tuple[PinnedInput, ...]:
    """The sync script's pinned imports and their helpers (`import_closure`) in load order, each
    module after the modules it imports. Every import-time import of the script is the standard
    library or one of its `imports`; every absolute import-time import of a pinned module is the
    standard library or a pinned helper next to it. A pinned module is loaded without a package,
    so its relative import always fails: it is accepted only inside a `try` that catches
    `ImportError`, whose handler's imports are resolved instead. Refused on any other import, a
    module named twice, a helper no pinned import reaches, or a cycle."""
    if not isinstance(names, list):
        raise RecorderError(
            f"step {step}: `{IMPORT_CLOSURE}` must be a list of pipeline-script inputs"
        )
    helpers = tuple(input_of(inputs, step, IMPORT_CLOSURE, m, ("pipeline_script",)) for m in names)
    pinned = imports + helpers
    ids, stems = [m.input_id for m in pinned], [m.module for m in pinned]
    if len(set(ids)) != len(ids) or len(set(stems)) != len(stems):
        raise RecorderError(f"step {step}: the sync's imports and closure name a module twice")
    roots = {m.module for m in imports}
    for line, name, level, _ in import_time_imports(script):
        top = name.split(".")[0]
        if level or (top not in sys.stdlib_module_names and top not in roots):
            raise RecorderError(
                f"step {step}: {script.name} line {line} imports {'.' * level}{name} when "
                "imported: neither the standard library nor one of its pinned `imports`"
            )
    by_stem = {m.module: m for m in pinned}
    edges: dict[str, list[str]] = {}
    for module in pinned:
        folder = PurePosixPath(module.assets3d_path).parent
        edges[module.input_id] = []
        for line, name, level, guarded in import_time_imports(module):
            top = name.split(".")[0]
            if level and guarded:
                continue  # fails at load (no package): the handler's fallback is what runs
            if level:
                raise RecorderError(
                    f"step {step}: {module.name} line {line} imports {'.' * level}{name} outside "
                    "a `try` that catches ImportError: a pinned module is loaded without a "
                    "package, so a relative import cannot run"
                )
            if top in sys.stdlib_module_names:
                continue
            target = by_stem.get(top)
            if (
                "." in name
                or target is None
                or PurePosixPath(target.assets3d_path).parent != folder
            ):
                raise RecorderError(
                    f"step {step}: {module.name} line {line} imports {name} when imported, which "
                    f"is neither the standard library nor a pinned module of `{IMPORT_CLOSURE}` "
                    f"({folder}/{top}.py)"
                )
            edges[module.input_id].append(target.input_id)
    order: list[str] = []

    def visit(node: str, path: tuple[str, ...]) -> None:
        if node in path:
            raise RecorderError(f"step {step}: the sync's imports form a cycle {[*path, node]}")
        if node in order:
            return
        for target in sorted(set(edges[node])):
            visit(target, (*path, node))
        order.append(node)

    for module in imports:
        visit(module.input_id, ())
    unreached = [m.input_id for m in helpers if m.input_id not in order]
    if unreached:
        raise RecorderError(
            f"step {step}: `{IMPORT_CLOSURE}` names {unreached}, which no pinned import imports "
            "when imported"
        )
    by_id = {m.input_id: m for m in pinned}
    return tuple(by_id[i] for i in order)


def stack_bitmaps(stack: dict[str, Any]) -> set[str]:
    """Bitmap names a stack JSON references (masks and `base_tex`), as the sync command reads."""
    names = {x["mask"] for x in stack["layers"] + stack["groups"] if x.get("mask")}
    return names | {x["base_tex"] for x in stack["layers"] if x.get("base_tex")}


def export_config(item: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    """The authored `json_config` (a repository file, hash-checked) without `exportPath`."""
    if "path" not in item:
        raise RecorderError(f"input {item['input_id']}: the export configuration is a repo file")
    file = repo_root / item["path"]
    if not file.is_file() or sha256_file(file) != item["sha256"]:
        raise RecorderError(f"input {item['input_id']}: {file} is missing or not the pinned bytes")
    config = json.loads(file.read_bytes().decode("utf-8"))
    if not isinstance(config, dict) or not set(config) <= CONFIG_KEYS:
        raise RecorderError(
            f"input {item['input_id']}: an export configuration holds only {sorted(CONFIG_KEYS)} "
            "(the recorder sets `exportPath`)"
        )
    if not config.get("exportList") or not config.get("exportParameters"):
        raise RecorderError(f"input {item['input_id']}: `exportList` and `exportParameters`")
    return config


def config_export_step(
    raw: dict[str, Any], manifest: dict[str, Any], repo_root: Path
) -> ConfigExport:
    step, args = raw["step"], raw.get("args", {})
    if set(args) != {"config"}:
        raise RecorderError(f"step {step}: {CONFIG_EXPORT} takes only `config`")
    item = next((i for i in manifest["inputs"] if i["input_id"] == args["config"]), None)
    if item is None or item["kind"] != "recipe_json":
        raise RecorderError(f"step {step}: `config` must name a recipe_json input")
    return ConfigExport(step, item["input_id"], export_config(item, repo_root))


def script_job_from_manifest(
    manifest: dict[str, Any],
    assets_root: Path,
    store: OracleStore | None = None,
    repo_root: Path = REPO_ROOT,
) -> ScriptJob:
    """The job of a pipeline-script manifest; refused before Painter is touched on any input
    neither Assets3D nor the private store (`store`, default: this machine's) holds, or any step
    the recorder does not know. A native-create manifest is refused here
    (`pipeline_job_from_manifest` loads it)."""
    if is_native(manifest):
        raise RecorderError(
            f"{manifest['golden_id']}: a {NATIVE_CREATE} job is a native job "
            "(pipeline_job_from_manifest)"
        )
    inputs, steps, config_export = job_parts(manifest, assets_root, store, repo_root)
    roles = [script_step(raw, inputs) for raw in steps]
    if [role for role, _ in roles] != ["create", "sync", "export"]:
        raise RecorderError("a pipeline-script golden runs create, sync and export, in order")
    return ScriptJob(manifest, inputs, roles[0][1], roles[1][1], roles[2][1], config_export)


def is_native(manifest: dict[str, Any]) -> bool:
    steps = manifest["instruction_sequence"]["steps"]
    return bool(steps) and steps[0]["call"] == NATIVE_CREATE


def job_parts(
    manifest: dict[str, Any], assets_root: Path, store: OracleStore | None, repo_root: Path
) -> tuple[dict[str, PinnedInput], list[dict[str, Any]], ConfigExport | None]:
    """The pinned inputs, the steps before a closing config export, and that export."""
    if manifest["instruction_sequence"]["interface"] != INTERFACE:
        raise RecorderError(f"{manifest['golden_id']}: the interface is not {INTERFACE}")
    if manifest["tier"] != "1":
        raise RecorderError(f"{manifest['golden_id']}: pipeline-script goldens are Tier 1")
    inputs = pinned_inputs(manifest, assets_root.resolve(), store or locate())
    steps = manifest["instruction_sequence"]["steps"]
    if [s["step"] for s in steps] != list(range(1, len(steps) + 1)):
        raise RecorderError("instruction steps must be numbered 1..n in order")
    config_export = None
    if steps and steps[-1]["call"] == CONFIG_EXPORT:
        config_export = config_export_step(steps[-1], manifest, repo_root)
        steps = steps[:-1]
    repo_files = {i["input_id"] for i in manifest["inputs"] if "path" in i}
    if repo_files != ({config_export.config_id} if config_export else set()):
        raise RecorderError(
            f"{manifest['golden_id']}: a repository-file input is only the configuration of a "
            f"closing {CONFIG_EXPORT}"
        )
    return inputs, steps, config_export


def native_create_step(raw: dict[str, Any], inputs: dict[str, PinnedInput]) -> NativeCreate:
    """The native create's arguments, refused before Painter is touched unless they are exactly
    the mesh and its material library (the one the OBJ's `mtllib` names, next to it), the Normal,
    the three names and every setting, each of its type."""
    step, args = raw["step"], dict(raw.get("args", {}))
    if set(args) != NATIVE_ARGS:
        raise RecorderError(
            f"step {step}: {NATIVE_CREATE} takes exactly {sorted(NATIVE_ARGS)}; missing "
            f"{sorted(NATIVE_ARGS - set(args))}, unknown {sorted(set(args) - NATIVE_ARGS)}"
        )
    found = {k: input_of(inputs, step, k, args[k], kinds) for k, kinds in NATIVE_INPUTS.items()}
    mesh, library = found["mesh"], found["mesh_material_library"]
    if PurePosixPath(library.assets3d_path).parent != PurePosixPath(mesh.assets3d_path).parent:
        raise RecorderError(f"step {step}: the material library must lie next to the mesh")
    if material_library(mesh.file) != library.name:
        raise RecorderError(f"step {step}: {mesh.name}'s `mtllib` does not name {library.name}")
    for key in NATIVE_NAMES:
        if not isinstance(args[key], str) or not NATIVE_NAME.fullmatch(args[key]):
            raise RecorderError(f"step {step}: `{key}` must match {NATIVE_NAME.pattern}")
    for key, valid in NATIVE_SETTINGS.items():
        if not valid(args[key]):
            raise RecorderError(f"step {step}: `{key}` is not a value the recorder passes")
    return NativeCreate(step, args, mesh, found["normal"])


def native_job_from_manifest(
    manifest: dict[str, Any],
    assets_root: Path,
    store: OracleStore | None = None,
    repo_root: Path = REPO_ROOT,
) -> NativeJob:
    """The job of a native-create manifest: the native create, one sync and the closing config
    export, in that order and nothing else; refused before Painter is touched like a script job."""
    inputs, steps, config_export = job_parts(manifest, assets_root, store, repo_root)
    if config_export is None or len(steps) != 2 or steps[0]["call"] != NATIVE_CREATE:
        raise RecorderError(
            f"{manifest['golden_id']}: a native job runs {NATIVE_CREATE}, sync and "
            f"{CONFIG_EXPORT}, in order"
        )
    create = native_create_step(steps[0], inputs)
    role, sync = script_step(steps[1], inputs)
    if role != "sync":
        raise RecorderError(f"step {steps[1]['step']}: a native job's second step is the sync")
    if sync.args.get("texture_set") != create.args["texture_set"]:
        raise RecorderError(
            f"step {sync.step}: the sync's texture set {sync.args.get('texture_set')!r} is not "
            f"the created project's {create.args['texture_set']!r}"
        )
    return NativeJob(manifest, inputs, create, sync, config_export)


def pipeline_job_from_manifest(
    manifest: dict[str, Any],
    assets_root: Path,
    store: OracleStore | None = None,
    repo_root: Path = REPO_ROOT,
) -> ScriptJob | NativeJob:
    """A native job when the first step is the native create, else a script job."""
    if is_native(manifest):
        return native_job_from_manifest(manifest, assets_root, store, repo_root)
    return script_job_from_manifest(manifest, assets_root, store, repo_root)


def load_manifest(path: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = load_json(path)
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"{path}: not a valid public manifest: {problems}")
    return manifest


def load_script_job(path: Path, assets_root: Path, store: OracleStore | None = None) -> ScriptJob:
    return script_job_from_manifest(load_manifest(path), assets_root, store)


def load_pipeline_job(
    path: Path, assets_root: Path, store: OracleStore | None = None
) -> ScriptJob | NativeJob:
    """The job `record-script` records: a script job or a native job."""
    return pipeline_job_from_manifest(load_manifest(path), assets_root, store)


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
    """A recorder session with the script operation and the native create's mesh-map operation
    loaded next to `painter_side.py`."""

    def connect(self) -> PainterIdentity:
        identity = super().connect()
        self.transport.run(extension_code(PAINTER_SCRIPTS.read_text(encoding="utf-8")))
        self.transport.run(extension_code(PAINTER_NATIVE.read_text(encoding="utf-8")))
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


STAGED_ROOT_MARKER = "AGENTS.md"  # the file the pipeline scripts find their Assets3D root by


def stage_inputs(job: ScriptJob | NativeJob, root: Path) -> dict[str, Path]:
    """Copy every input to `root/<assets3d_path>` (file names and folders kept) and check each
    copy's hash: Painter reads only these copies, never the asset repository. A root marker makes
    a script run from its staged copy find `root` as its Assets3D root, so what it imports from
    there is the staged, pinned copy."""
    root.mkdir(parents=True, exist_ok=True)
    (root / STAGED_ROOT_MARKER).write_text(
        "Staged copy of pinned Assets3D inputs (UzPainter recorder; decision 144).\n",
        encoding="utf-8",
    )
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


def pinned_module(item: PinnedInput, file: Path) -> types.ModuleType:
    """The module an import of `item` gives, executed from its pinned bytes as `file`."""
    assert item.data is not None
    spec = importlib.util.spec_from_file_location(item.module, file)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    exec(compile(item.data, str(file), "exec", dont_inherit=True), vars(module))
    return module


STANDARD_ROOTS = tuple(
    Path(p).resolve()
    for p in sorted(
        {
            sysconfig.get_path("stdlib"),
            sysconfig.get_path("platstdlib"),
            str(Path(sys.base_exec_prefix) / "DLLs"),
        }
    )
)


def standard_library(fullname: str, path: Sequence[str] | None) -> bool:
    """Whether an import is the interpreter's own standard library: a built-in or frozen module, or
    a module or submodule of a standard-library name whose file lies under the standard library's
    directories outside site-packages. A same-named file elsewhere on `sys.path` or on a package's
    `__path__` is not. A standard-library name no finder here finds fails as it would."""
    top = fullname.partition(".")[0]
    if top in sys.builtin_module_names:
        return True
    if top not in sys.stdlib_module_names:
        return False
    if importlib.machinery.FrozenImporter.find_spec(fullname) is not None:
        return True
    spec = importlib.machinery.PathFinder.find_spec(fullname, path)
    if spec is None:
        return True  # nothing to load
    if spec.origin is None:
        return False
    origin = Path(spec.origin).resolve()
    return "site-packages" not in origin.parts and any(
        origin.is_relative_to(root) for root in STANDARD_ROOTS
    )


class PinnedImports(importlib.abc.MetaPathFinder):
    """While `on`, refuses (and records) every import of a module not loaded yet that is not the
    standard library, so what static resolution cannot see (`importlib.import_module`, a function
    called at import time, a file on `sys.path` shadowing a standard-library name) never loads
    unpinned code. On only while pinned code runs, never while the recorder talks to Painter."""

    def __init__(self) -> None:
        self.on = False
        self.refused: list[str] = []

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: types.ModuleType | None = None,
    ) -> None:
        if self.on and not standard_library(fullname, path):
            self.refused.append(fullname)
            raise ImportError(f"{fullname} is neither a pinned module nor the standard library")
        return None

    def check(self) -> None:
        if self.refused:
            raise RecorderError(
                f"the pinned sync imports {sorted(set(self.refused))}, which are neither pinned "
                "modules nor the standard library"
            )


def run_sync(
    session: PainterSession, job: ScriptJob | NativeJob, staged: dict[str, Path], directory: Path
) -> Any:
    """Run the sync command line host-side from the pinned bytes, with the script's Assets3D
    imports loaded from their pinned bytes (an import closure's helpers first, under
    `PinnedImports`); `sys.path`, `sys.modules` and `sys.meta_path` are restored after."""
    modules = job.sync.load_order or job.sync.imports
    imports_guard = PinnedImports() if IMPORT_CLOSURE in job.sync.args else None
    saved_path = list(sys.path)
    saved_modules = {item.module: sys.modules.get(item.module) for item in modules}
    if imports_guard is not None:
        sys.meta_path.insert(0, imports_guard)
        imports_guard.on = True
    try:
        for item in modules:
            sys.modules[item.module] = pinned_module(item, staged[item.input_id])
        if imports_guard is not None:
            imports_guard.check()
        result = sync_command(session, job.sync, staged, directory, imports_guard)
        if imports_guard is not None:
            imports_guard.check()
        return result
    except ImportError:
        if imports_guard is not None:
            imports_guard.check()
        raise
    finally:
        if imports_guard is not None:
            imports_guard.on = False
            sys.meta_path.remove(imports_guard)
        sys.path[:] = saved_path
        for name, module in saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def sync_command(
    session: PainterSession,
    step: ScriptStep,
    staged: dict[str, Path],
    directory: Path,
    imports_guard: PinnedImports | None = None,
) -> Any:
    """The sync command line, its `execute` swapped for the recorder's remote control (same
    contract: run the code, return its `result`). The script's route guard sends its probe through
    it first; a verdict other than "outside the production layout" (no attempt token) is
    refused. The script runs as its staged copy, so its Assets3D root is the staged mirror. A
    script that defines `PROJECT_PROBE_CODE` sends that probe before its guard probe; the guard
    probe is `GUARD_CODE` for the step's `texture_set` (None when it gives none)."""
    script = step.script
    assert script.data is not None
    file = staged[script.input_id]
    namespace: dict[str, Any] = {"__name__": "uzp_pipeline_layer_stack", "__file__": str(file)}
    exec(compile(script.data, str(file), "exec", dont_inherit=True), namespace)
    if not callable(namespace.get("execute")) or not callable(namespace.get("main")):
        raise RecorderError(f"{script.name} defines no `execute(code)` and `main()` to run")
    if not isinstance(namespace.get("GUARD_CODE"), str):
        raise RecorderError(f"{script.name} defines no route guard probe `GUARD_CODE`")
    texture_set = dict(step.options).get(SYNC_OPTIONS["texture_set"][0])
    guard = namespace["GUARD_CODE"].replace("__TS__", repr(texture_set))
    probe = namespace.get("PROJECT_PROBE_CODE")
    expected = ([probe] if isinstance(probe, str) else []) + [guard]
    calls: list[tuple[str, Any]] = []

    def wrong_calls(count: int) -> RecorderError:
        return RecorderError(
            f"{script.name} sync ran {count} Painter calls, not its route guard's "
            f"{len(expected)} probe(s) and then one sync"
        )

    def execute(code: str, token: str | None = None) -> Any:
        if token is not None:
            raise RecorderError(
                f"{script.name}'s route guard placed the project in a production character's "
                "paint attempt (it returned an attempt token): the recorder runs the wand only "
                "outside the production layout"
            )
        # Each probe is checked before it is sent, so wrong probes never let the sync code run.
        if len(calls) > len(expected) or (
            len(calls) < len(expected) and code != expected[len(calls)]
        ):
            raise wrong_calls(len(calls) + 1)
        if imports_guard is None:
            value = run_in_painter(session, code.encode("utf-8"), f"{script.name} {SYNC_COMMAND}")
        else:
            imports_guard.check()  # nothing reaches Painter after a refused import
            imports_guard.on = False
            try:
                value = run_in_painter(
                    session, code.encode("utf-8"), f"{script.name} {SYNC_COMMAND}"
                )
            finally:
                imports_guard.on = True
        calls.append((code, value))
        return value

    namespace["execute"] = execute
    state = directory / "sync-state.json"
    if state.exists():
        raise RecorderError(f"{state} already exists: the sync state must start empty")
    masks = staged[step.masks[0].input_id].parent
    argv = [
        script.name,
        SYNC_COMMAND,
        "--stack",
        str(staged[step.args["stack"]]),
        "--masks",
        str(masks),
        "--state",
        str(state),
        *(part for option in step.options for part in option),
    ]
    saved_argv = sys.argv
    sys.argv = argv
    try:
        namespace["main"]()
    except SystemExit as exit:
        raise RecorderError(f"{script.name} {SYNC_COMMAND} exited: {exit.code}") from exit
    finally:
        sys.argv = saved_argv
        if imports_guard is not None:
            imports_guard.on = False  # the pinned code is done
    if len(calls) != len(expected) + 1:
        raise wrong_calls(len(calls))
    if imports_guard is not None:
        imports_guard.check()  # before the recorder talks to Painter again
    session.wait_ready()
    return calls[-1][1]


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


def names_shelf_preset(config: dict[str, Any]) -> bool:
    """True when the configuration names a `resource://` preset (a shelf resource), by its
    `defaultExportPreset` or an `exportList` item's `exportPreset`."""
    presets = [config.get("defaultExportPreset")]
    presets += [item.get("exportPreset") for item in config.get("exportList") or []]
    return any(isinstance(p, str) and p.startswith("resource://") for p in presets)


def run_config_export(
    session: PainterSession, export: ConfigExport, base: Path, basis: str, prefix: str = "export"
) -> tuple[list[dict[str, Any]], list[Path]]:
    """The authored configuration exported into a fresh directory `base/export`, verified like a
    texture golden's export; `basis` is the encoding basis of a map whose file tells none. The
    glTF scene files Painter writes beside a glTF preset's textures, absent from its reply
    (R-314, decision 314), are admitted only as validated glTF sidecars (`gltf_sidecars`) and
    recorded as `exported_sidecar` blobs, never as maps. `prefix` heads the output id of every
    file (a script job's closing export takes its own, so that its maps never share a record id
    with the script's: record ids are lowercase)."""
    out = base / "export"
    out.mkdir(parents=True)
    session.wait_ready()
    if names_shelf_preset(export.config):
        # A shelf preset (R-322's starter-assets Unreal preset) is undefined until the shelf
        # crawl of a freshly started Painter ends: the same gate as a texture golden's presets.
        session.wait_catalog_ready()
    fence_ns = write_fence(base / "fence")
    reply = session.call("export_textures", config={**export.config, "exportPath": out.as_posix()})
    session.wait_ready()
    if reply["status"] != "Success":
        raise RecorderError(f"{base.name}: export {reply['status']}: {reply['message']}")
    files = [Path(f) for entry in reply["textures"] for f in entry["files"]]
    root = out.resolve()
    listed = {f.resolve() for f in files}
    unlisted = sorted(p.resolve() for p in root.rglob("*") if p.is_file())
    sidecars = gltf_sidecars([p for p in unlisted if p not in listed], root)
    verify_current_outputs(files + sorted(sidecars), out, fence_ns)
    value = {"status": reply["status"], "message": reply["message"], "textures": reply["textures"]}
    outputs: list[dict[str, Any]] = [
        {
            "output_id": f"export/s{export.step}",
            "kind": "api_readback",
            "call": CONFIG_EXPORT,
            "args": {"step": export.step, "config": export.config_id},
            "value": value,
        }
    ]
    for entry in reply["textures"]:
        texture_set = entry["texture_set"] + (f"/{entry['stack']}" if entry["stack"] else "")
        for file_name in entry["files"]:
            path = Path(file_name)
            measured = measure_storage_format(path)
            encoding, found = (
                (measured.encoding, "file")
                if measured.encoding is not None
                else (UNDETERMINED, basis)
            )
            outputs.append(
                {
                    "output_id": f"{prefix}/{output_safe(path.stem)}",
                    "kind": "exported_map",
                    "texture_set": texture_set,
                    "map": path.stem,
                    "blob": {
                        "sha256": sha256_file(path),
                        "size_bytes": path.stat().st_size,
                        "media_type": MEDIA_TYPES[measured.container],
                    },
                    "storage_format": measured.as_schema(encoding),
                    "export_settings": {
                        "step": export.step,
                        "config": export.config_id,
                        "encoding_basis": found,
                    },
                }
            )
    for path, media_type in sorted(sidecars.items()):
        name = path.relative_to(root).as_posix()
        outputs.append(
            {
                "output_id": "/".join([prefix, *(output_safe(part) for part in name.split("/"))]),
                "kind": "exported_sidecar",
                "file": name,
                "blob": {
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                    "media_type": media_type,
                },
                "export_settings": {"step": export.step, "config": export.config_id},
            }
        )
    return outputs, files + sorted(sidecars)


def run_exports(
    session: PainterSession, job: ScriptJob, directory: Path, recording: str
) -> tuple[list[dict[str, Any]], list[Path]]:
    """The script's export, then the closing config export (if any) of the same document."""
    outputs, files = run_export(session, job, directory, recording)
    if job.config_export is not None:
        more, more_files = run_config_export(
            session, job.config_export, directory / recording / "config", "config_export", "config"
        )
        names = [
            (o["texture_set"], o["map"]) for o in outputs + more if o["kind"] == "exported_map"
        ]
        if len(set(names)) != len(names):
            raise RecorderError(f"{recording}: the two exports write maps of the same name")
        outputs, files = outputs + more, files + more_files
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


def run_native_create(
    session: PainterSession, job: NativeJob, staged: dict[str, Path], directory: Path
) -> tuple[dict[str, Any], Path]:
    """The recorder-native create: `project.create` from the staged mesh with exactly the step's
    settings and no template; then, on the one texture set the step names, the Normal imported as
    a TEXTURE project resource under its name and group and bound as the Normal mesh map, every
    slot read back: refused unless the Normal is the only bound slot. Saved in full in the work
    directory, so r2 reopens it. Returns the readback and the project."""
    step = job.create
    project = directory / "project" / "native-create.spp"
    project.parent.mkdir(parents=True)
    created = session.call(
        "apply_step",
        step=step.step,
        call=NATIVE_CREATE,
        args=step.settings,
        resolved={"mesh": str(staged[step.mesh.input_id])},
    )
    session.wait_ready()
    bound = session.call(
        "bind_mesh_map",
        texture_set=step.args["texture_set"],
        path=str(staged[step.normal.input_id]),
        name=step.args["normal_name"],
        group=step.args["normal_group"],
        usage=NORMAL_USAGE,
    )
    normal = only_normal(bound, step)
    if normal != bound.get("resource"):
        raise RecorderError(f"the Normal slot holds {normal}, not the imported {bound['resource']}")
    session.wait_ready()
    saved = save_project(session, project)
    value = {
        # What the recorder asked for; Painter's API reads no project setting back (the template
        # capture reads the resolution and channels), and no resource group.
        "requested_settings": step.settings,
        "requested_normal": {"name": step.args["normal_name"], "group": step.args["normal_group"]},
        **created,
        **bound,
        "saved": saved,
    }
    return value, project


def only_normal(reply: dict[str, Any], step: NativeCreate) -> dict[str, Any]:
    """The Normal's resource from a mesh-map readback, refused unless it holds exactly the one
    named texture set and all ten slots, each empty or a resource readback, and the Normal is the
    only bound slot, under the requested name."""
    if reply.get("texture_sets") != [step.args["texture_set"]]:
        raise RecorderError(
            f"the created project's texture sets are {reply.get('texture_sets')}, not exactly "
            f"{step.args['texture_set']}"
        )
    maps = reply.get("mesh_maps")
    if not isinstance(maps, dict) or set(maps) != MESH_MAP_SLOTS:
        found = sorted(maps) if isinstance(maps, dict) else maps
        raise RecorderError(f"the mesh-map readback holds {found}, not the ten slots")
    for slot, value in maps.items():
        if value is not None and not is_resource(value):
            raise RecorderError(f"the {slot} slot reads back {value!r}, not a resource or None")
    bound = sorted(slot for slot, value in maps.items() if value is not None)
    if bound != [NORMAL_USAGE]:
        raise RecorderError(
            f"the mesh maps bound are {bound}, not only the Normal {step.args['normal_name']}"
        )
    normal: dict[str, Any] = maps[NORMAL_USAGE]
    # A named import keeps its name literally; `.image` ends only the version (decision 107).
    expected = step.args["normal_name"]
    if normal["name"] != expected:
        raise RecorderError(f"the Normal is {normal['name']!r}, not {expected!r}")
    return normal


def is_resource(value: Any) -> bool:
    """A resource readback: exactly `url`, `context` and `name` as strings, and `version` as a
    string or None."""
    return (
        isinstance(value, dict)
        and set(value) == RESOURCE_FIELDS
        and all(isinstance(value[key], str) for key in ("url", "context", "name"))
        and (value["version"] is None or isinstance(value["version"], str))
    )


def resource_identity(value: dict[str, Any]) -> dict[str, Any]:
    """A resource readback as a reopen must keep it: a project context `projectN`, and only that,
    is replaced by `projectN` in the context and the URL (a reopen renumbers it); any other
    context, a shelf's included, stays as read. Name and version are kept literally."""
    url, context = value["url"], value["context"]
    prefix = f"resource://{context}/"
    if PROJECT_CONTEXT.fullmatch(context) and url.startswith(prefix):
        context, url = "projectN", "resource://projectN/" + url[len(prefix) :]
    return {"url": url, "context": context, "name": value["name"], "version": value["version"]}


def mesh_map_output(
    session: PainterSession, job: NativeJob, staged: dict[str, Path], recording: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The slots read again (after the sync in r1, after the reopen in r2), checked like the
    create's, as a readback with the Normal's version beside the SHA-1 of its pinned bytes
    (evidence only: never normalised, never compared, and no rule makes a version a SHA-1).
    Returns the output and the Normal's identity."""
    step = job.create
    reply = session.call("mesh_maps", texture_set=step.args["texture_set"])
    normal = only_normal(reply, step)
    pinned = hashlib.sha1(staged[step.normal.input_id].read_bytes()).hexdigest()
    output = {
        "output_id": f"create/mesh-maps-{recording}",
        "kind": "api_readback",
        "call": GET_MESH_MAP,
        "args": {"texture_set": step.args["texture_set"]},
        "value": {**reply, "normal_pinned_bytes_sha1": pinned},
    }
    return output, resource_identity(normal)


# The native state readback (`painter_side.migration_readback`, recorded as `create/state`): each
# readback's fields, the key sets of the synced group's nodes, and what a renumbering may change.
STATE_ID = "create/state"
STATE_FIELDS = frozenset({"file_path", "last_imported_mesh_path", "texture_sets"})
LAYER_FIELDS = frozenset(
    {"name", "type", "uid", "visible", "blending", "mask", "content_effects", "mask_effects"}
)
GROUP_FIELDS = LAYER_FIELDS | {"sub_layers"}
FILL_FIELDS = LAYER_FIELDS | {"active_channels", "sources"}
MASK_FILL_FIELDS = frozenset({"name", "type", "uid", "visible", "blending", "sources"})
BITMAP_FIELDS = frozenset({"resource_url", "color_space", "available_color_spaces"})
MASKED = {"has_mask": True, "enabled": True, "background": "Black"}  # the sync's add_mask
UNMASKED = {"has_mask": False}
SYNC_REPLY = frozenset({"root_uid", "layers", "hidden", "resources", "group_height_blend"})
PROJECT_URL = re.compile(r"\Aresource://(project[0-9]+)/")


def renumbered_url(url: str) -> str:
    return PROJECT_URL.sub("resource://projectN/", url, count=1)


def project_renumbered(value: Any) -> Any:
    """`value` with only a project resource context renumbered: a `context` that is `projectN`,
    and that prefix of a `url` or `resource_url`. Every other value, names, versions and shelf
    contexts included, is kept literally."""
    if isinstance(value, list):
        return [project_renumbered(item) for item in value]
    if not isinstance(value, dict):
        return value
    out: dict[str, Any] = {}
    for key, item in value.items():
        if key == "context" and isinstance(item, str) and PROJECT_CONTEXT.fullmatch(item):
            out[key] = "projectN"
        elif key in ("url", "resource_url") and isinstance(item, str):
            out[key] = renumbered_url(item)
        else:
            out[key] = project_renumbered(item)
    return out


def project_contexts(value: Any) -> set[str]:
    """Every project context a readback names (in a `context`, `url` or `resource_url`)."""
    found: set[str] = set()
    if isinstance(value, list):
        for item in value:
            found |= project_contexts(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key == "context" and isinstance(item, str) and PROJECT_CONTEXT.fullmatch(item):
                found.add(item)
            elif key in ("url", "resource_url") and isinstance(item, str):
                match = PROJECT_URL.match(item)
                found |= {match.group(1)} if match else set()
            else:
                found |= project_contexts(item)
    return found


def count_bitmaps(value: Any) -> int:
    if isinstance(value, list):
        return sum(count_bitmaps(item) for item in value)
    if isinstance(value, dict):
        return int("bitmap" in value) + sum(count_bitmaps(item) for item in value.values())
    return 0


def first_difference(a: Any, b: Any, path: str = "") -> str:
    """The path of the first value where `a` and `b` differ (`a != b`)."""
    if isinstance(a, dict) and isinstance(b, dict) and set(a) == set(b):
        for key in a:
            if a[key] != b[key]:
                return first_difference(a[key], b[key], f"{path}/{key}")
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for index, (x, y) in enumerate(zip(a, b, strict=True)):
            if x != y:
                return first_difference(x, y, f"{path}[{index}]")
    return path or "/"


def sync_built(stack: dict[str, Any], synced: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The stack's layers in the order the sync builds them (group by group), and the uid the
    sync's own reply gives each; refused unless that reply names exactly those layers, one
    resource per bitmap, no resource for two bitmaps, and every group and layer path once."""
    if not isinstance(synced, dict) or not set(synced) >= SYNC_REPLY:
        found = sorted(synced) if isinstance(synced, dict) else synced
        raise RecorderError(f"the sync replied {found}, not its {sorted(SYNC_REPLY)}")
    groups = [g["name"] for g in stack["groups"]]
    built = [x for g in stack["groups"] for x in stack["layers"] if x["group"] == g["key"]]
    paths = [
        (next(g["name"] for g in stack["groups"] if g["key"] == x["group"]), x["name"])
        for x in built
    ]
    if len(built) != len(stack["layers"]) or len(set(groups)) != len(groups):
        raise RecorderError("the stack has a layer in no group, or two groups of one name")
    if len(set(paths)) != len(paths):
        raise RecorderError("the stack names one group/layer path twice")
    report = synced["layers"]
    if not isinstance(report, list) or [
        (r.get("id"), r.get("name")) if isinstance(r, dict) else r for r in report
    ] != [(x["id"], x["name"]) for x in built]:
        raise RecorderError("the sync's reply does not list the stack's layers as it builds them")
    if any(type(r["uid"]) is not int for r in report) or type(synced["root_uid"]) is not int:
        raise RecorderError("the sync's reply gives a layer or its group no uid")
    resources = synced["resources"]
    if (
        not isinstance(resources, dict)
        or set(resources) != stack_bitmaps(stack)
        or not all(isinstance(url, str) for url in resources.values())
    ):
        named = sorted(resources) if isinstance(resources, dict) else resources
        raise RecorderError(
            f"the sync's resources name {named}, not the stack's bitmaps "
            f"{sorted(stack_bitmaps(stack))}"
        )
    shared = sorted(n for n in resources if list(resources.values()).count(resources[n]) > 1)
    if shared:
        raise RecorderError(f"the sync bound the bitmaps {shared} to one resource")
    return built, {r["id"]: r["uid"] for r in report}


def check_native_state(
    texture_set: str,
    stack: dict[str, Any],
    synced: dict[str, Any],
    urls: dict[str, str],
    value: Any,
    project: Path,
    mesh: Path,
    recording: str,
) -> None:
    """The state readback holds the synced stack as the pinned stack and the sync's reply give
    it, refused otherwise (decision 300 item 7; contract "Resources" and "Root"):

    - the project file, the staged mesh as the last imported, one texture set with one stack;
    - the root layers: the stack's titled group first, visible, the sync's group; after it
      exactly one layer, Painter's default, the one the sync reports hiding, hidden;
    - in the group, the stack's groups and in each its layers, top first (Painter lists the
      stack the sync built bottom first from the top), each visible, by name, a layer by the uid
      the sync reported; nothing else and no content effect. A field this check needs (a
      structure, a name, a uid, a visibility, a mask, a binding or a Height blend) that is
      missing or raised is refused; any other getter's value, raised included, is only kept
      for the r1/r2 comparison;
    - each mask the stack gives (a layer's or a group's): a Black mask, enabled, holding exactly
      one visible fill effect named for its bitmap and bound to that bitmap's resource `urls`
      in the Data colour space; no mask elsewhere; a `base_tex` bound in BaseColor as sRGB;
    - Height blending Normal on a group with `replace_height`, LinearDodge on the others and on
      the titled group, as the sync reported;
    - as many bitmap sources in the whole stack as the stack binds, so none is added anywhere."""

    def refused(where: str, problem: str) -> RecorderError:
        return RecorderError(f"{recording}: the state readback at {where} {problem}")

    if not isinstance(value, dict) or set(value) != STATE_FIELDS:
        raise refused("/", f"holds {sorted(value) if isinstance(value, dict) else value!r}")
    file_path = value["file_path"]
    if not isinstance(file_path, str) or Path(file_path).resolve() != project.resolve():
        raise refused("/file_path", f"is {file_path!r}, not {project}")
    imported = value["last_imported_mesh_path"]
    if not isinstance(imported, str) or Path(imported).resolve() != mesh.resolve():
        raise refused("/last_imported_mesh_path", f"is {imported!r}, not the staged mesh {mesh}")
    sets = value["texture_sets"]
    if not isinstance(sets, dict) or list(sets) != [texture_set]:
        raise refused("/texture_sets", f"is not exactly {texture_set}")
    stacks = sets[texture_set].get("stacks")
    if not isinstance(stacks, dict) or len(stacks) != 1:
        raise refused(f"/{texture_set}", "holds no single stack")
    roots = next(iter(stacks.values())).get("layers")
    if not isinstance(roots, list) or not roots:
        raise refused(f"/{texture_set}", "holds no root layer")
    built, uids = sync_built(stack, synced)

    def node(item: Any, fields: frozenset[str], kind: str, name: str, where: str) -> Any:
        if not isinstance(item, dict) or set(item) != fields:
            raise refused(where, f"is no {kind} readback")
        if item["type"] != kind or item["name"] != name:
            raise refused(where, f"is the {item['type']} {item['name']!r}, not the {kind} {name!r}")
        if item["visible"] is not True or type(item["uid"]) is not int:
            raise refused(where, "is hidden, or has no uid")
        if "content_effects" in fields and item["content_effects"] != []:
            raise refused(where, "holds a content effect")
        return item

    def bitmap(sources: Any, channel: str, bitmap_name: str, space: str, where: str) -> None:
        source = sources.get(channel) if isinstance(sources, dict) else None
        inner = source.get("source") if isinstance(source, dict) else None
        found = inner.get("bitmap") if isinstance(inner, dict) else None
        if not isinstance(found, dict) or set(found) != BITMAP_FIELDS:
            raise refused(where, f"binds no bitmap in {channel}")
        if found["resource_url"] != urls[bitmap_name]:
            raise refused(
                where,
                f"binds {found['resource_url']!r}, not the sync's {bitmap_name} "
                f"{urls[bitmap_name]!r}",
            )
        available = found["available_color_spaces"]
        if (
            found["color_space"] != space
            or not isinstance(available, list)
            or space not in available
        ):
            raise refused(where, f"reads {bitmap_name} in {found['color_space']!r}, not {space}")

    def mask(item: dict[str, Any], bitmap_name: str | None, where: str) -> None:
        if bitmap_name is None:
            if item["mask"] != UNMASKED or item["mask_effects"] != []:
                raise refused(where, "has a mask the stack does not give it")
            return
        effects = item["mask_effects"]
        if item["mask"] != MASKED or not isinstance(effects, list) or len(effects) != 1:
            raise refused(where, f"has no Black mask holding exactly one fill for {bitmap_name}")
        effect = node(effects[0], MASK_FILL_FIELDS, "FillEffect", bitmap_name, f"{where}/mask")
        if set(effect["sources"]) != {"mask"}:
            raise refused(f"{where}/mask", "holds a source other than its mask")
        bitmap(effect["sources"], "mask", bitmap_name, "Data", f"{where}/mask")

    def height(item: dict[str, Any], expected: str, where: str) -> str:
        found = item["blending"].get("Height") if isinstance(item["blending"], dict) else None
        mode = found.get("blending_mode") if isinstance(found, dict) else None
        if mode != expected:
            raise refused(where, f"blends Height as {mode!r}, not {expected}")
        return expected

    title = stack["title"]
    root = node(roots[0], GROUP_FIELDS, "GroupLayer", title, f"/{title}")
    if root["uid"] != synced["root_uid"]:
        raise refused(
            f"/{title}", f"has the uid {root['uid']}, not the sync's {synced['root_uid']}"
        )
    mask(root, None, f"/{title}")
    height(root, "LinearDodge", f"/{title}")
    others, hidden = roots[1:], synced["hidden"]
    if (
        not isinstance(hidden, list)
        or len(hidden) != 1
        or len(others) != 1
        or not isinstance(others[0], dict)
        or others[0].get("name") != hidden[0]
        or others[0].get("visible") is not False
    ):
        raise refused(
            "/", f"holds not exactly one other root layer, the default the sync hid ({hidden})"
        )
    groups = root["sub_layers"]
    if not isinstance(groups, list) or len(groups) != len(stack["groups"]):
        raise refused(f"/{title}", f"does not hold the stack's {len(stack['groups'])} groups")
    blends: dict[str, str] = {}
    for item, group in zip(groups, reversed(stack["groups"]), strict=True):
        where = f"/{title}/{group['name']}"
        found = node(item, GROUP_FIELDS, "GroupLayer", group["name"], where)
        mask(found, group.get("mask"), where)
        expected = "Normal" if group.get("replace_height") else "LinearDodge"
        blends[group["name"]] = height(found, expected, where)
        layers = [x for x in built if x["group"] == group["key"]]
        children = found["sub_layers"]
        if not isinstance(children, list) or len(children) != len(layers):
            raise refused(where, f"does not hold the stack's {len(layers)} layers")
        for child, layer in zip(children, reversed(layers), strict=True):
            path = f"{where}/{layer['name']}"
            fill = node(child, FILL_FIELDS, "FillLayer", layer["name"], path)
            if fill["uid"] != uids[layer["id"]]:
                raise refused(path, f"has the uid {fill['uid']}, not the sync's {layer['id']}")
            if layer.get("base_tex"):
                bitmap(fill["sources"], "BaseColor", layer["base_tex"], "sRGB", path)
            mask(fill, layer.get("mask"), path)
    if blends != synced["group_height_blend"]:
        raise refused(f"/{title}", f"blends Height {blends}, not as the sync reported")
    bindings = sum(bool(x.get("mask")) + bool(x.get("base_tex")) for x in stack["layers"])
    bindings += sum(bool(g.get("mask")) for g in stack["groups"])
    if count_bitmaps(roots) != bindings:
        raise refused("/", f"binds {count_bitmaps(roots)} bitmaps, not the stack's {bindings}")


def native_state(
    session: PainterSession,
    job: NativeJob,
    staged: dict[str, Path],
    synced: Any,
    project: Path,
    recording: str,
) -> tuple[dict[str, Any], Any]:
    """The project's state read back (`migration.state_readback`, as `create/state`) and checked
    against the pinned stack and the sync's reply (`check_native_state`): literally in r1, after
    renumbering only a project context in r2. Returns the output and what r1 and r2 must hold
    alike: the readback with that renumbering and without its project path (checked here)."""
    from tools.parity.recorder.migration import state_readback  # migration imports this module

    output = {**state_readback(session), "output_id": STATE_ID}
    value = output["value"]
    stack = json.loads(staged[job.sync.args["stack"]].read_bytes().decode("utf-8"))
    resources = synced.get("resources") if isinstance(synced, dict) else None
    urls = dict(resources) if isinstance(resources, dict) else {}
    contexts = project_contexts(value)  # before any renumbering, which would merge them
    if len(contexts) > 1:
        raise RecorderError(
            f"{recording}: the state readback names several project contexts {sorted(contexts)}"
        )
    observed = value
    if recording != R1:
        observed = project_renumbered(value)
        urls = {
            name: renumbered_url(url) if isinstance(url, str) else url for name, url in urls.items()
        }
    texture_set = job.create.args["texture_set"]
    mesh = staged[job.create.mesh.input_id]
    check_native_state(texture_set, stack, synced, urls, observed, project, mesh, recording)
    renumbered = project_renumbered(value)
    return output, {key: item for key, item in renumbered.items() if key != "file_path"}


def save_project(session: PainterSession, project: Path) -> str:
    """`save_as` Full to `project`, refused unless Painter reports that file."""
    session.call("save_as", path=str(project))
    saved = session.wait_ready()
    if saved.file_path is None or Path(saved.file_path).resolve() != project.resolve():
        raise RecorderError(
            f"the project was not saved to {project} (Painter reports {saved.file_path})"
        )
    return str(saved.file_path)


def native_readback(step: NativeCreate, value: Any) -> dict[str, Any]:
    return {
        "output_id": f"create/s{step.step}",
        "kind": "api_readback",
        "call": NATIVE_CREATE,
        "args": {"step": step.step},
        "value": value,
    }


def record_script_golden(
    session: PainterSession,
    job: ScriptJob | NativeJob,
    work: Path,
    inbox: Path,
    now: Now = utc_now,
    *,
    record_prefix: str = "",
) -> Path:
    """Run the pinned scripts, record r1, r1-repeat and r2, and write the run to the inbox. A
    native job creates the project itself, saves it after the sync (no script saves it), and
    exports only its configuration."""
    identity = session.connect()
    require_colour_management(Job(job.manifest, {}, (), ()), identity)
    directory = ensure_outside_repository(work) / job.golden_id.replace("/", "__")
    directory = directory / run_name(identity.session_id, now())
    staged = stage_inputs(job, directory / "inputs")

    def exports(recording: str) -> tuple[list[dict[str, Any]], list[Path]]:
        if isinstance(job, NativeJob):
            return run_config_export(
                session, job.config_export, directory / recording / "config", "config_export"
            )
        return run_exports(session, job, directory, recording)

    try:
        baseline: dict[str, Any] | None = None  # the imported Normal, as the create bound it
        compared_r1: Any = None  # the native state r2 must hold alike
        if isinstance(job, NativeJob):
            native, project = run_native_create(session, job, staged, directory)
            created = native_readback(job.create, native)
            baseline = resource_identity(native["resource"])
        else:
            script_created, project = run_create(session, job, staged, directory)
            created = readback(job.create, script_created)
        after_create = session.call("hello")["colour_management"]
        synced = run_sync(session, job, staged, directory)
        first = [created, readback(job.sync, synced)]
        if isinstance(job, NativeJob):
            save_project(session, project)
            slots_r1, identity_r1 = mesh_map_output(session, job, staged, R1)
            if identity_r1 != baseline:
                raise RecorderError(
                    f"after the sync the Normal is {identity_r1}, not the imported {baseline}"
                )
            first.append(slots_r1)
            state_r1, compared_r1 = native_state(session, job, staged, synced, project, R1)
            first.append(state_r1)
        first.append(template_output(session))
        exported, first_blobs = exports(R1)
        repeat, repeat_blobs = exports(R1_REPEAT)
        session.call("close_project")
        session.wait_closed()
        session.call("open_project", path=project.as_posix())
        session.wait_ready()
        second = [template_output(session)]
        if isinstance(job, NativeJob):
            slots_r2, identity_r2 = mesh_map_output(session, job, staged, R2)
            if identity_r2 != baseline:
                raise RecorderError(
                    f"after the reopen the Normal is {identity_r2}, not the imported {baseline}"
                )
            second.append(slots_r2)
            state_r2, compared_r2 = native_state(session, job, staged, synced, project, R2)
            if compared_r2 != compared_r1:
                raise RecorderError(
                    "after the reopen the state differs from r1's at "
                    f"{first_difference(compared_r1, compared_r2)}"
                )
            second.append(state_r2)
        reopened, second_blobs = exports(R2)
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
    ("route-check-py", "pipeline_script", "Pipeline/qa/route_check.py"),
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
    "contract, so the Painter-side code the script builds is its own. Its route guard (Assets3D "
    "9a718b9; decision 144) sends its own probe through that function before the sync and "
    "imports locate from Pipeline/qa/route_check.py, pinned here and loaded from its pinned "
    "bytes; the project lies in the private work directory, outside a production character's "
    "folder, so the guard passes with no attempt token, and any other verdict is refused. "
    "Recordings: r1 (same "
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


def script_manifest(
    golden_id: str,
    description: str,
    inputs: list[dict[str, Any]],
    masks: list[dict[str, Any]],
    create: dict[str, str],
    stack: str,
    imports: list[str],
    assets_root: Path,
) -> dict[str, Any]:
    """A pipeline-script manifest (create, sync, export) over hashed inputs; validated against the
    schema and loaded as a job over `assets_root` before it is returned."""
    manifest: dict[str, Any] = {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": golden_id,
        "tier": "1",
        "domain": "tier1/pilot/" + golden_id.rsplit("/", 1)[-1],
        "description": description,
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
                        "stack": stack,
                        "masks": [m["input_id"] for m in masks],
                        "mask_files": [PurePosixPath(m["assets3d_path"]).name for m in masks],
                        "imports": imports,
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
        raise RecorderError(f"the {golden_id} manifest is invalid: {problems}")
    script_job_from_manifest(manifest, assets_root)
    return manifest


def mask_inputs(folder: str, bitmaps: Sequence[str], assets_root: Path) -> list[dict[str, Any]]:
    """One input per bitmap the stack names: `M_*` a mask, anything else (`T_*`) a colour image."""
    return [
        assets3d_input(
            f"mask-{name.lower()}",
            "mask" if name.startswith("M_") else "image",
            f"{folder}/{name}.png",
            assets_root,
        )
        for name in bitmaps
    ]


def wand_manifest(assets_root: Path) -> dict[str, Any]:
    """The R9 manifest, hashing the current Assets3D files (`--assets-root`)."""
    stack = json.loads((assets_root / WAND_STACK).read_bytes().decode("utf-8"))
    bitmaps = sorted(stack_bitmaps(stack))
    inputs = [assets3d_input(i, k, p, assets_root) for i, k, p in WAND_INPUTS]
    create = {
        "script": "painter-create-py",
        "args_file": "painter-create-args",
        "mesh": "wand-mesh",
        "mesh_material_library": "wand-mesh-mtl",
        "normal": "wand-normal",
        "ao": "wand-ao",
    }
    return script_manifest(
        "phase1/tier1/wand-v1",
        WAND_DESCRIPTION,
        inputs,
        mask_inputs(WAND_MASKS, bitmaps, assets_root),
        create,
        "wand-stack",
        ["route-check-py"],
        assets_root,
    )


# --- The Wand float request (phase1/tier1/wand-v1-float; decision 283) ---------------------------

WAND_FLOAT_CONFIG = "parity/fixtures/tier1/wand-v1-float/export-config.json"
WAND_FLOAT_DESCRIPTION = (
    "Float recording of the Tier 1 Wand v1 golden (phase1/tier1/wand-v1; decisions 099 and 283), "
    "so that its infinite padding can be scored on the document's own values: the Wand's Height "
    "is L16F, and each PNG 16 code of the golden has several L16F preimages (decisions 277 and "
    "281). Steps 1 to 3 and every input are the Wand v1 golden's, byte for byte (the three "
    "UzmiGames pipeline scripts and their arguments, the stack, the masks, the mesh and the mesh "
    "maps, all pinned by SHA-256), run with the same two recorder adaptations. Step 4 is the "
    "recorder's own export of the same document after every script export: the authored "
    "configuration export-config.json exports BaseColor, Roughness, Metallic and Height from the "
    "same document maps and channels as painter_export.py, as OpenEXR 32f with the script's "
    "parameters otherwise (sizeLog2 11, infinite padding, no dithering), each file name the "
    "script's with the suffix _f32, into a fresh directory of its own. The run's PNG 16 maps "
    "must equal the Wand v1 golden's byte for byte, which proves it is the same document. "
    "Recordings: r1 (same session: create, sync, export, float export), r1-repeat (same session, "
    "both exports again) and r2 (after save, close and reopen, both exports again). Recorded "
    "on Painter 12.1.5."
)


def wand_float_manifest(assets_root: Path) -> dict[str, Any]:
    """The Wand float request: the R9 manifest's inputs and steps, then a config export."""
    manifest = wand_manifest(assets_root)
    config = {
        "input_id": "wand-float-export-config",
        "kind": "recipe_json",
        "path": WAND_FLOAT_CONFIG,
        "sha256": sha256_file(REPO_ROOT / WAND_FLOAT_CONFIG),
        "provenance": {
            "origin": "uzmigames_authored",
            "licence": "Apache-2.0",
            "note": "The OpenEXR 32f export of the Wand float recording (decision 283).",
        },
    }
    steps = manifest["instruction_sequence"]["steps"]
    steps.append(
        {
            "step": len(steps) + 1,
            "call": CONFIG_EXPORT,
            "args": {"config": "wand-float-export-config"},
        }
    )
    manifest.update(
        golden_id="phase1/tier1/wand-v1-float",
        domain="tier1/pilot/wand-v1-float",
        description=WAND_FLOAT_DESCRIPTION,
        inputs=[*manifest["inputs"], config],
        applied_settings=[
            *manifest["applied_settings"],
            {"name": "export.exr.bit_depth", "value": "32f", "applied_by": "recorder_api"},
        ],
    )
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"the wand-v1-float manifest is invalid: {problems}")
    script_job_from_manifest(manifest, assets_root)
    return manifest


WAND_NORMAL_FLOAT_CONFIG = "parity/fixtures/tier1/wand-v1-normal-float/export-config.json"
WAND_NORMAL_FLOAT_DESCRIPTION = (
    "Wand v1 immutable pipeline replay, followed by EXR32f Normal_OpenGL, Normal channel and "
    "normal_base mesh map exports. Same 2048 resolution, infinite padding, no dithering, OCIO "
    "and original PNG16 exports as decision 283. PNG16 outputs must equal the existing Wand "
    "reference before admission. Three float maps must repeat bit exactly across r1, r1-repeat "
    "and r2. This separate exploratory request leaves decision 283 unchanged."
)


def wand_normal_float_manifest(assets_root: Path) -> dict[str, Any]:
    """The admitted Normal diagnostic, preserving its original float-pilot domain and pins."""
    manifest = wand_float_manifest(assets_root)
    manifest["golden_id"] = "phase1/tier1/wand-v1-normal-float"
    manifest["description"] = WAND_NORMAL_FLOAT_DESCRIPTION
    config = manifest["inputs"][-1]
    config["path"] = WAND_NORMAL_FLOAT_CONFIG
    config["sha256"] = sha256_file(REPO_ROOT / WAND_NORMAL_FLOAT_CONFIG)
    config["provenance"]["note"] = (
        "Authored normal-only diagnostic export configuration; documented export map sources "
        "already used by tier0 normal probes."
    )
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"the wand-v1-normal-float manifest is invalid: {problems}")
    script_job_from_manifest(manifest, assets_root)
    return manifest


# --- The Belt v5 request (phase2/tier1/belt-v5; phase2.9, decision 192) -------------------------

# The round folder of `Pipeline/retopology/waist-v5/` (its README: the folder is copied to
# `_tmp/claude/cintura-v5/`, the path the two Painter-side scripts hard-code) and the committed
# files the round runs. Assets3D's committed pipeline at c6b74c2: the layer-stack route guard
# imports `locate` from `Pipeline/production/run.py`.
BELT = "_tmp/claude/cintura-v5"
BELT_SCRIPTS = "Pipeline/retopology/waist-v5"
BELT_INPUTS: tuple[tuple[str, str, str], ...] = (
    ("painter-create-py", "pipeline_script", f"{BELT_SCRIPTS}/painter_create.py"),
    ("painter-layer-stack-py", "pipeline_script", "Pipeline/painting/painter_layer_stack.py"),
    ("production-run-py", "pipeline_script", "Pipeline/production/run.py"),
    ("painter-export-py", "pipeline_script", f"{BELT_SCRIPTS}/painter_export.py"),
    ("painter-create-args", "recipe_json", f"{BELT}/painter_create_args.json"),
    ("painter-export-args", "recipe_json", f"{BELT}/painter_export_args.json"),
    ("belt-stack", "recipe_json", f"{BELT_SCRIPTS}/stack-belt.json"),
)
BELT_MASKS = f"{BELT}/paint/masks-belt"  # round.sh: waist_masks.py belt --out paint/masks-belt
BELT_STACK = f"{BELT_SCRIPTS}/stack-belt.json"

BELT_DESCRIPTION = (
    "Tier 1 pilot golden of the UzmiGames belt 23-Cinto v5 of the Skeletal Mage (phase2.9 items "
    "2.1, 2.2, 3.1; decisions 099, 144 and 192). The waist-v5 round of the UzmiGames pipeline runs "
    "byte-unchanged in Painter, each script pinned by SHA-256, through Painter's documented remote "
    "control (never the community MCP bridge): painter_create.py (a new project from the low-poly "
    "OBJ under OCIO with Painter's substance config, OpenGL normals, 2048 px, no cameras; imports "
    "the Normal and AO mesh maps; save_as Full), painter_layer_stack.py sync (stack-belt.json: the "
    "leather and brass groups, 19 fills, the bitmap masks and the base_tex colour bitmap T_belt "
    "filled in final-UV space) and painter_export.py (BaseColor, Roughness, Metallic, Height and "
    "Normal_OpenGL as 16-bit PNG, sizeLog2 11, infinite padding, no dithering). The two "
    "adaptations of the wand golden (decision 099) apply unchanged: the arguments files are "
    "repointed at staged copies, and the sync command's remote-execution function is the "
    "recorder's remote control. Its route guard (Assets3D c6b74c2) imports locate from "
    "Pipeline/production/run.py, pinned here and loaded from its pinned bytes; the project lies in "
    "the private work directory, outside a production character's folder, so the guard passes "
    "with no attempt token. The mesh, normal and AO are the files the round's arguments file "
    "names. Recordings: r1 (same session: create, sync, export), r1-repeat (same session, export "
    "again) and r2 (after save, close and reopen, export again). Recorded on Painter 12.1.5."
)


class MissingInputs(RecorderError):
    """Inputs a manifest must pin that are not under the asset repository: `missing` lists their
    Assets3D paths, so a restore can be checked file by file."""

    def __init__(self, golden_id: str, missing: Sequence[str]) -> None:
        self.missing = sorted(set(missing))
        # The message as the exception's `args` (what `str` shows), with no dunder access: the
        # recorder's provenance rule refuses any underscore-prefixed attribute.
        self.args = (f"{golden_id}: {len(self.missing)} input(s) missing: {self.missing}",)


def assets3d_relative(value: str, assets_root: Path) -> str | None:
    """The Assets3D-relative path of an absolute path an arguments file names, or None outside."""
    written = PureWindowsPath(value)
    root = PureWindowsPath(str(assets_root))
    head = [part.lower() for part in written.parts[: len(root.parts)]]
    if not written.is_absolute() or head != [part.lower() for part in root.parts]:
        return None
    return "/".join(written.parts[len(root.parts) :])


def material_library(obj: Path) -> str | None:
    """The file name the OBJ's `mtllib` statement names (next to the OBJ), or None."""
    for line in obj.read_bytes().decode("utf-8", "replace").splitlines():
        words = line.split(maxsplit=1)
        if len(words) == 2 and words[0] == "mtllib":
            return PureWindowsPath(words[1].strip()).name
    return None


SASH_STACK = f"{BELT_SCRIPTS}/stack-sash.json"
SASH_MASKS = f"{BELT}/paint/masks-sash"  # round.sh: waist_masks.py sash --out paint/masks-sash

SASH_DESCRIPTION = (
    "Tier 1 pilot golden of the UzmiGames sash 25-Faixa-Cintura v5 of the Skeletal Mage, the piece "
    "that replaces Belt v5 as the phase2.9 pilot (owner, 2026-10-18; decisions 099, 144, 192 and "
    "260). The sash was painted in the same waist-v5 round as the belt: the UzmiGames pipeline runs"
    " byte-unchanged in Painter, each script pinned by SHA-256, through Painter's documented remote"
    " control (never the community MCP bridge): painter_create.py (a new project from the low-poly "
    "OBJ under OCIO with Painter's substance config, OpenGL normals, 2048 px, no cameras; imports "
    "the Normal and AO mesh maps; save_as Full), painter_layer_stack.py sync (stack-sash.json: the "
    "cloth and hem-leather groups, 20 fills, 19 bitmap masks and the base_tex colour bitmap T_sash "
    "filled in final-UV space) and painter_export.py (BaseColor, Roughness, Metallic, Height and "
    "Normal_OpenGL as 16-bit PNG, sizeLog2 11, infinite padding, no dithering). The two adaptations"
    " of the wand golden (decision 099) apply unchanged: the arguments files are repointed at "
    "staged copies, and the sync command's remote-execution function is the recorder's remote "
    "control. Its route guard (Assets3D c6b74c2) imports locate from Pipeline/production/run.py, "
    "pinned here and loaded from its pinned bytes; the project lies in the private work directory, "
    "outside a production character's folder, so the guard passes with no attempt token. The mesh, "
    "normal and AO are the files the round's arguments file names, which must name the sash. "
    "Recordings: r1 (same session: create, sync, export), r1-repeat (same session, export again) "
    "and r2 (after save, close and reopen, export again). Recorded on Painter 12.1.5."
)


@dataclass(frozen=True)
class WaistPiece:
    """One piece of the waist-v5 round (`Pipeline/retopology/waist-v5`, round folder `BELT`): the
    belt and the sash share the scripts and the round folder, not the stack or the masks."""

    golden_id: str
    prefix: str  # input-id prefix: belt-mesh, sash-mesh, ...
    name: str  # the texture set and the arguments files' `name` / export prefix
    stack: str
    masks: str
    description: str


BELT_PIECE = WaistPiece(
    "phase2/tier1/belt-v5", "belt", "23-Cinto", BELT_STACK, BELT_MASKS, BELT_DESCRIPTION
)
SASH_PIECE = WaistPiece(
    "phase2/tier1/sash-v5", "sash", "25-Faixa-Cintura", SASH_STACK, SASH_MASKS, SASH_DESCRIPTION
)


def piece_arguments(piece: WaistPiece, assets_root: Path) -> None:
    """Refused when the round folder's arguments files name another piece: the round folder holds
    one pair, rewritten for each piece the round creates or exports."""
    for args_path, key in (
        ("painter_create_args.json", "name"),
        ("painter_export_args.json", "prefix"),
    ):
        file = assets_root / BELT / args_path
        if not file.is_file():
            continue  # listed missing with the other fixed inputs
        value = str(json.loads(file.read_bytes().decode("utf-8")).get(key, ""))
        if not value.startswith(piece.name):
            raise RecorderError(
                f"{BELT}/{args_path}: `{key}` is {value!r}, not the {piece.name} piece's: the "
                f"round folder holds another piece's arguments"
            )


def belt_create_inputs(
    assets_root: Path, missing: list[str], prefix: str = "belt"
) -> list[tuple[str, str, str]]:
    """The mesh, its material library, the normal and the AO the round's arguments file names;
    every file not there is added to `missing`."""
    args_path = f"{BELT}/painter_create_args.json"
    file = assets_root / args_path
    if not file.is_file():
        return []  # listed missing with the other fixed inputs
    arguments = json.loads(file.read_bytes().decode("utf-8"))
    found: list[tuple[str, str, str]] = []
    for key, input_id, kind in (
        ("mesh", f"{prefix}-mesh", "mesh"),
        ("normal", f"{prefix}-normal", "image"),
        ("ao", f"{prefix}-ao", "image"),
    ):
        relative = assets3d_relative(str(arguments.get(key, "")), assets_root)
        if relative is None:
            raise RecorderError(
                f"{args_path}: `{key}` ({arguments.get(key)!r}) is not a path under the asset "
                "repository"
            )
        found.append((input_id, kind, relative))
        if not (assets_root / relative).is_file():
            missing.append(relative)
        elif key == "mesh":
            library = material_library(assets_root / relative)
            if library is None:
                raise RecorderError(f"{relative} names no material library (`mtllib`)")
            mtl = str(PurePosixPath(relative).with_name(library))
            found.append((f"{prefix}-mesh-mtl", "mesh", mtl))
            if not (assets_root / mtl).is_file():
                missing.append(mtl)
    return found


def waist_manifest(assets_root: Path, piece: WaistPiece) -> dict[str, Any]:
    """The request of one waist-v5 piece, hashing the current Assets3D files (`--assets-root`);
    refused with `MissingInputs` naming every file it needs that is not there."""
    fixed = tuple(
        (f"{piece.prefix}-stack", kind, piece.stack)
        if input_id == "belt-stack"
        else (input_id, kind, path)
        for input_id, kind, path in BELT_INPUTS
    )
    missing = [path for _, _, path in fixed if not (assets_root / path).is_file()]
    piece_arguments(piece, assets_root)
    created = belt_create_inputs(assets_root, missing, piece.prefix)
    bitmaps: list[str] = []
    if (assets_root / piece.stack).is_file():
        stack = json.loads((assets_root / piece.stack).read_bytes().decode("utf-8"))
        bitmaps = sorted(stack_bitmaps(stack))
        missing += [
            f"{piece.masks}/{name}.png"
            for name in bitmaps
            if not (assets_root / piece.masks / f"{name}.png").is_file()
        ]
    if missing:
        raise MissingInputs(piece.golden_id, missing)
    inputs = [assets3d_input(i, k, p, assets_root) for i, k, p in fixed + tuple(created)]
    create = {
        "script": "painter-create-py",
        "args_file": "painter-create-args",
        "mesh": f"{piece.prefix}-mesh",
        "mesh_material_library": f"{piece.prefix}-mesh-mtl",
        "normal": f"{piece.prefix}-normal",
        "ao": f"{piece.prefix}-ao",
    }
    return script_manifest(
        piece.golden_id,
        piece.description,
        inputs,
        mask_inputs(piece.masks, bitmaps, assets_root),
        create,
        f"{piece.prefix}-stack",
        ["production-run-py"],
        assets_root,
    )


def belt_manifest(assets_root: Path) -> dict[str, Any]:
    """The Belt v5 request (decision 192; replaced as the pilot by the sash, decision 260)."""
    return waist_manifest(assets_root, BELT_PIECE)


def sash_manifest(assets_root: Path) -> dict[str, Any]:
    """The Sash v5 request, the phase2.9 pilot since decision 260."""
    return waist_manifest(assets_root, SASH_PIECE)


PILOTS = {
    "wand": wand_manifest,
    "wand-float": wand_float_manifest,
    "wand-normal-float": wand_normal_float_manifest,
    "belt": belt_manifest,
    "sash": sash_manifest,
}


def store_inputs(manifest: dict[str, Any], assets_root: Path, store: OracleStore) -> int:
    """Every pinned Assets3D input into the private store (decision 144), each re-resolved by its
    hash afterwards; the number stored. Refused when a file no longer holds its pinned bytes. A
    repository file or a bitmap already resolved from the store (decision 194) is not Assets3D's."""
    pinned = [item for item in manifest["inputs"] if "assets3d_path" in item]
    for item in pinned:
        file = assets_root / item["assets3d_path"]
        if sha256_file(file) != item["sha256"]:
            raise RecorderError(f"input {item['input_id']}: {file} changed since it was hashed")
        store.add_input(file, item["sha256"], item["assets3d_path"])
        stored = store.resolve(item["input_id"], item["sha256"])
        if stored.status is not Status.AVAILABLE:
            raise RecorderError(f"input {item['input_id']}: not stored ({stored.reason})")
    return len(pinned)


def main(argv: Sequence[str] | None = None) -> int:
    from tools.parity.recorder.gltf_pilots import PILOTS as GLTF_PILOTS  # imports this module
    from tools.parity.recorder.tunic import PILOTS as TUNIC_PILOTS  # imports this module

    pilots: dict[str, Callable[[Path], dict[str, Any]]] = {
        **PILOTS,
        **TUNIC_PILOTS,
        **GLTF_PILOTS,
    }
    parser = argparse.ArgumentParser(prog="python -m tools.parity.recorder.script_run")
    commands = parser.add_subparsers(dest="command", required=True)
    write = commands.add_parser("manifest", help="write a pilot's manifest (hashes Assets3D)")
    write.add_argument("--assets-root", type=Path, required=True)
    write.add_argument("--out", type=Path, required=True)
    write.add_argument("--pilot", choices=sorted(pilots), default="wand")
    write.add_argument(
        "--store", action="store_true", help="also store every pinned input in the private store"
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    root = args.assets_root.resolve()
    try:
        manifest = pilots[args.pilot](root)
        if args.store:
            store = locate()
            if store is None:
                raise RecorderError("--store: there is no private store on this machine")
            print(f"stored {store_inputs(manifest, root, store)} inputs")
    except MissingInputs as error:
        print(f"refused: {error}", file=sys.stderr)
        print(json.dumps({"missing": error.missing}, indent=2), file=sys.stderr)
        return 2
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
