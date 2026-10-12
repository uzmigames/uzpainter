"""Recording jobs: a public manifest (`golden-public.json`) read as the instruction to record.

The job is the UzmiGames-authored manifest of a golden with its `private_records` still empty:
inputs with provenance, the instruction sequence over documented `substance_painter` calls, the
applied settings. The recorder replays the state-changing steps once, then performs the capture
steps for every recording (task items 2.2, 2.3, 2.6). Only the vocabulary below is replayed;
anything else is refused before Painter is touched.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors

EXPORT = "substance_painter.export.export_project_textures"

# Step arguments naming an input by input_id; the recorder passes the input's file path.
INPUT_ARGS = {ps.CREATE: "mesh", ps.SET_ENVIRONMENT: "environment", ps.IMPORT_RESOURCE: "input"}

# Optional step arguments naming an input by input_id; when given, the recorder passes the
# staged file's `file:///` URL (a file baking parameter, e.g. the high-poly mesh).
OPTIONAL_INPUT_ARGS = {ps.BAKING_SET: "input"}

# `set_environment_resource` of a file imported as a session resource (the `ref_match` preset
# of the fixed render pipeline, decision 038): the file is not a repository input; the step
# names it by SHA-256 and file name, and the recorder is given the file at record time.
SESSION_ENVIRONMENT = "session_environment"
SESSION_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.(exr|hdr)")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")

# Baking-configuration steps: they must come before the last `bake_async` of the job.
BAKING_SETTINGS = frozenset({ps.BAKING_SET, ps.BAKING_SET_ENABLED_BAKERS})

# Common baking parameter naming the high-poly mesh: only an `input` may set it, so that the
# file Painter bakes from is a hashed, staged input.
HIPOLY_MESH = "HipolyMesh"
BAKING_VALUE_ARGS = ("value", "enum_label", "input")

STATE_CALLS = frozenset(
    {
        ps.CREATE,
        ps.INSERT_FILL,
        ps.SET_SOURCE,
        ps.SET_ACTIVE_CHANNELS,
        ps.SET_BLENDING_MODE,
        ps.SET_OPACITY,
        ps.SET_RESOLUTIONS,
        ps.SET_ENVIRONMENT,
        ps.SET_TONE_MAPPING,
        *(ps.CAMERA + name for name in ps.CAMERA_PROPERTIES),
        ps.INSERT_GROUP,
        ps.INSERT_LEVELS,
        ps.INSERT_FILTER,
        ps.SET_EFFECT_SOURCE,
        ps.SET_EFFECT_CHANNELS,
        ps.SET_FILTER_CHANNELS,
        ps.SET_LEVELS_CHANNEL,
        ps.SET_LEVELS,
        ps.SET_PROJECTION,
        ps.ADD_CHANNEL,
        ps.EDIT_CHANNEL,
        ps.IMPORT_RESOURCE,
        ps.SET_MESH_MAP,
        ps.ADD_MASK,
        ps.INSERT_GENERATOR,
        ps.INSERT_SMART_MATERIAL,
        ps.SET_PARAMETERS,
        ps.BAKING_SET,
        ps.BAKING_SET_ENABLED_BAKERS,
        ps.BAKE,
    }
)

# Capture calls of a baking-defaults job (read after the state steps, never changing state).
BAKING_CAPTURES = frozenset(
    {
        ps.BAKING_COMMON,
        ps.BAKING_BAKER,
        ps.BAKING_CURVATURE_METHOD,
        ps.BAKING_ENABLED_BAKERS,
        ps.BAKING_TEXTURESET_ENABLED,
    }
)

# Getter recorded after each setter (readback of the documented property it changed).
READBACK_OF = {
    ps.SET_SOURCE: (ps.GET_SOURCE, ("node_step", "channel")),
    ps.SET_ACTIVE_CHANNELS: (ps.GET_ACTIVE_CHANNELS, ("node_step",)),
    ps.SET_BLENDING_MODE: (ps.GET_BLENDING_MODE, ("node_step", "channel")),
    ps.SET_OPACITY: (ps.GET_OPACITY, ("node_step", "channel")),
    ps.SET_EFFECT_SOURCE: (ps.GET_EFFECT_SOURCE, ("node_step", "channel")),
    ps.SET_LEVELS_CHANNEL: (ps.GET_LEVELS, ("node_step",)),
    ps.SET_LEVELS: (ps.GET_LEVELS, ("node_step",)),
    ps.SET_PROJECTION: (ps.GET_PROJECTION, ("node_step",)),
    ps.SET_MESH_MAP: (ps.GET_MESH_MAP, ("usage",)),
    ps.SET_PARAMETERS: (ps.GET_GENERATOR_SOURCE, ("node_step",)),
}

# Getter recorded for the node an insertion step creates (`node_step` is the step itself).
READBACK_OF_INSERTED = {
    ps.INSERT_GENERATOR: ps.GET_GENERATOR_SOURCE,
    ps.INSERT_SMART_MATERIAL: ps.GET_SUB_LAYERS,
}

EXPORT_PRESET = "uzp_recorder"
MAP_CHANNELS = {"RGB": "RGB", "RGBA": "RGBA", "L": "L"}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Step:
    step: int
    call: str
    args: dict[str, Any]


@dataclass(frozen=True)
class OutputMap:
    """One map of the recorder's export preset: `<map_type>/<name>:<channels>`."""

    map_type: str
    name: str
    channels: str

    @property
    def stem(self) -> str:
        """The map name as a file-name and output-id component: a `/` (Painter's `1/ior`) would
        make Painter write a sub-folder, so it reads `_over_` (`1_over_ior`)."""
        return self.name.replace("/", "_over_")

    @property
    def file_name(self) -> str:
        return f"$textureSet_{self.stem}"

    def preset_map(self) -> dict[str, Any]:
        return {
            "fileName": self.file_name,
            "channels": [
                {
                    "destChannel": channel,
                    "srcChannel": channel,
                    "srcMapType": self.map_type,
                    "srcMapName": self.name,
                }
                for channel in self.channels
            ],
        }


def parse_output_map(spec: str) -> OutputMap:
    kind_name, _, channels = spec.partition(":")
    # The map type ends at the first `/`: a virtual map's name may hold one (`1/ior`).
    map_type, slash, name = kind_name.partition("/")
    if not slash:
        map_type, name = "", kind_name
    if not name or channels not in MAP_CHANNELS:
        raise RecorderError(f"export map {spec!r} is not `<mapType>/<name>:<RGB|RGBA|L>`")
    return OutputMap(map_type or "documentMap", name, channels)


@dataclass(frozen=True)
class ExportStep:
    step: int
    maps: tuple[OutputMap, ...]
    parameters: dict[str, Any]

    def config(self, export_path: Path, roots: list[str]) -> dict[str, Any]:
        """The documented `json_config` of `export_project_textures`."""
        return {
            "exportPath": export_path.as_posix(),
            "exportShaderParams": False,
            "defaultExportPreset": EXPORT_PRESET,
            "exportPresets": [{"name": EXPORT_PRESET, "maps": [m.preset_map() for m in self.maps]}],
            "exportList": [{"rootPath": root} for root in roots],
            "exportParameters": [{"parameters": dict(self.parameters)}],
        }


def export_step(step: Step) -> ExportStep:
    args = step.args
    maps = args.get("maps")
    if not isinstance(maps, list) or not maps:
        raise RecorderError(f"step {step.step}: export needs a non-empty `maps` list")
    parameters: dict[str, Any] = {
        "fileFormat": str(args.get("file_format", "png")),
        "bitDepth": str(args["bit_depth"]),
        "dithering": bool(args.get("dithering", False)),
        "paddingAlgorithm": str(args["padding"]),
    }
    if "dilation" in args:
        parameters["dilationDistance"] = int(args["dilation"])
    if "size_log2" in args:
        parameters["sizeLog2"] = int(args["size_log2"])
    return ExportStep(step.step, tuple(parse_output_map(str(m)) for m in maps), parameters)


@dataclass(frozen=True)
class ExportProbe:
    """An export probe (decision 087): a literal `json_config`, an authored input of the golden
    (`recipe_json`), listed with the documented `list_project_textures` and, when that
    succeeds, exported with `export_project_textures`. Its outcome, a refusal included, is the
    observation."""

    step: int
    config_id: str
    config: dict[str, Any]

    def config_at(self, export_path: Path) -> dict[str, Any]:
        return {**self.config, "exportPath": export_path.as_posix()}


def export_probe(step: Step, inputs: dict[str, Path]) -> ExportProbe:
    config_id = step.args.get("config")
    if set(step.args) != {"config"} or config_id not in inputs:
        raise RecorderError(
            f"step {step.step}: an export probe takes only `config`, an input with a path"
        )
    config = json.loads(inputs[str(config_id)].read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise RecorderError(f"step {step.step}: the export probe's config is not a JSON object")
    if "exportPath" in config:
        raise RecorderError(
            f"step {step.step}: the recorder sets `exportPath` (a fresh private directory)"
        )
    return ExportProbe(step.step, str(config_id), config)


def baking_readback(step: Step) -> dict[str, Any]:
    """Readback of a baking-configuration step, per texture set: the `Property.value()` of the
    parameter it set, or the enabled bakers."""
    scope = {"texture_set": step.args["texture_set"]} if "texture_set" in step.args else {}
    if step.call == ps.BAKING_SET_ENABLED_BAKERS:
        return {"call": ps.BAKING_ENABLED_BAKERS, "args": scope}
    args = {k: step.args[k] for k in ("parameter", "usage") if k in step.args}
    return {"call": ps.GET_PROPERTY_VALUE, "args": args | scope}


def check_session_environment(step: Step) -> None:
    if not SHA256_HEX.fullmatch(str(step.args[SESSION_ENVIRONMENT])):
        raise RecorderError(f"step {step.step}: `{SESSION_ENVIRONMENT}` must be a SHA-256")
    if not SESSION_FILE_NAME.fullmatch(str(step.args.get("file_name", ""))):
        raise RecorderError(
            f"step {step.step}: a session environment needs `file_name` (an .exr or .hdr name)"
        )


def check_baking_step(step: Step) -> None:
    """Refuse a malformed baking step before Painter is touched."""
    args = step.args
    where = f"step {step.step}"
    if step.call == ps.BAKE:
        if set(args) - {"texture_set"}:
            raise RecorderError(f"{where}: bake_async takes only an optional `texture_set`")
        return
    if step.call == ps.BAKING_SET_ENABLED_BAKERS:
        usages = args.get("usages")
        if not isinstance(usages, list) or set(args) - {"usages", "texture_set"}:
            raise RecorderError(f"{where}: set_enabled_bakers takes `usages` and `texture_set`")
        unknown = sorted(str(u) for u in usages if u not in ps.BAKER_USAGES)
        if unknown:
            raise RecorderError(f"{where}: {unknown} are not MeshMapUsage members")
        return
    unknown = sorted(set(args) - set(ps.BAKING_SET_ARGS))
    if unknown:
        raise RecorderError(f"{where}: BakingParameters.set does not take {unknown}")
    if not isinstance(args.get("parameter"), str) or not args["parameter"]:
        raise RecorderError(f"{where}: BakingParameters.set needs a `parameter` name")
    given = [k for k in BAKING_VALUE_ARGS if k in args]
    if len(given) != 1:
        raise RecorderError(f"{where}: give exactly one of `value`, `enum_label`, `input`")
    if "usage" in args and args["usage"] not in ps.BAKER_USAGES:
        raise RecorderError(f"{where}: usage {args['usage']!r} is not a MeshMapUsage member")
    if args.get("value", "") is None:
        raise RecorderError(f"{where}: a baking parameter value cannot be null")
    if "enum_label" in args and not isinstance(args["enum_label"], str):
        raise RecorderError(f"{where}: `enum_label` must be a label string")
    if args["parameter"] == HIPOLY_MESH and given != ["input"]:
        raise RecorderError(f"{where}: {HIPOLY_MESH} is set only from an `input` (an input id)")


@dataclass(frozen=True)
class Job:
    manifest: dict[str, Any]
    inputs: dict[str, Path]
    state_steps: tuple[Step, ...]
    exports: tuple[ExportStep, ...]
    captures: tuple[Step, ...] = ()
    export_probes: tuple[ExportProbe, ...] = ()

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

    @property
    def maps_exported_twice(self) -> frozenset[str]:
        """Maps more than one export step exports: their outputs are keyed by step (a second
        export in one session measures Painter's run-to-run noise, decision 087)."""
        steps = Counter(name for export in self.exports for name in {m.name for m in export.maps})
        return frozenset(name for name, count in steps.items() if count > 1)

    def readback_specs(self) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for step in self.state_steps:
            if step.call in READBACK_OF_INSERTED:
                spec = {"call": READBACK_OF_INSERTED[step.call], "args": {"node_step": step.step}}
                if spec not in specs:
                    specs.append(spec)
            if step.call in READBACK_OF:
                getter, keys = READBACK_OF[step.call]
                spec = {"call": getter, "args": {k: step.args[k] for k in keys}}
                if spec not in specs:
                    specs.append(spec)
            if step.call in BAKING_SETTINGS:
                spec = baking_readback(step)
                if spec not in specs:
                    specs.append(spec)
        return specs

    def project_settings(self) -> dict[str, Any]:
        """Settings the instruction sequence gives `project.create` (all other values: defaults)."""
        for step in self.state_steps:
            if step.call == ps.CREATE:
                return {k: v for k, v in step.args.items() if k != "mesh"}
        return {}


def load_job(path: Path, repo_root: Path = REPO_ROOT) -> Job:
    manifest = load_json(path)
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"{path}: not a valid public manifest: {problems}")
    return job_from_manifest(manifest, repo_root)


def job_from_manifest(manifest: dict[str, Any], repo_root: Path = REPO_ROOT) -> Job:
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
    steps = [
        Step(s["step"], s["call"], dict(s.get("args", {})))
        for s in manifest["instruction_sequence"]["steps"]
    ]
    if [s.step for s in steps] != list(range(1, len(steps) + 1)):
        raise RecorderError("instruction steps must be numbered 1..n in order")
    state: list[Step] = []
    exports: list[ExportStep] = []
    captures: list[Step] = []
    probes: list[ExportProbe] = []
    for step in steps:
        if step.call == EXPORT:
            exports.append(export_step(step))
            continue
        if step.call == ps.LIST_TEXTURES:
            probes.append(export_probe(step, inputs))
            continue
        if step.call in BAKING_CAPTURES:
            captures.append(step)
            continue
        if exports or captures or probes:
            raise RecorderError(f"step {step.step}: state steps must precede the captures")
        if step.call not in STATE_CALLS:
            raise RecorderError(f"step {step.step}: {step.call} is not in the recorder vocabulary")
        key = INPUT_ARGS.get(step.call)
        if step.call == ps.SET_ENVIRONMENT and "resource_url" in step.args:
            key = None  # a resource Painter ships or already has, named by its URL
        if step.call == ps.SET_ENVIRONMENT and SESSION_ENVIRONMENT in step.args:
            check_session_environment(step)
            key = None  # a file outside the repository, named by its SHA-256
        if key is not None and step.args.get(key) not in inputs:
            raise RecorderError(f"step {step.step}: `{key}` must name an input with a path")
        key = OPTIONAL_INPUT_ARGS.get(step.call)
        if key is not None and key in step.args and step.args[key] not in inputs:
            raise RecorderError(f"step {step.step}: `{key}` must name an input with a path")
        if step.call in BAKING_SETTINGS or step.call == ps.BAKE:
            check_baking_step(step)
        state.append(step)
    if not state or state[0].call != ps.CREATE:
        raise RecorderError("the instruction sequence must start with project.create")
    bakes = [s.step for s in state if s.call == ps.BAKE]
    for step in state:
        if step.call in BAKING_SETTINGS and bakes and step.step > bakes[-1]:
            raise RecorderError(
                f"step {step.step}: baking settings must precede the last bake_async step"
            )
    return Job(manifest, inputs, tuple(state), tuple(exports), tuple(captures), tuple(probes))
