"""Texture goldens (Tiers 0-2b): state replay, readbacks, exports, repeat recordings.

1. Replay the job's state steps once through the documented API, reading effective defaults as
   they appear (fresh fill layers, the channel set `project.create` produced).
   A golden whose settings sheet names values only Painter's UI can set has them applied by
   the operator here (`texture_sheet.py`, decision 029).
2. Recording `same_session`: template capture, the operator's entries and panel images (if
   any), readback of every property the sequence set, then each export step, export probe and
   capture (export presets, a bitmap's colour spaces) in step order. An export step waits for
   readiness (edition state entered, not busy), writes the fence, exports into a fresh
   directory and verifies the exported files are current (`capture.py`).
3. Save the project (Full), close it, reopen it, find the layers again at their recorded places.
4. Recording `after_save_reopen`: the same captures; the operator re-reads the UI-set values.
   Explicit `recorder.reopen_count` settings may request two or three reopen cycles instead
   of the default one; each cycle retains its own recording and operator readback.
5. Write the private record and the public manifest to the oracle inbox (`output.py`).

The throwaway project and the exports live in the private work directory; the project is closed
when the recorder finishes or fails, never saved anywhere else.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Any, Protocol

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.capture import (
    MEDIA_TYPES,
    StaleCaptureError,
    measure_storage_format,
    verify_current_outputs,
    write_fence,
)
from tools.parity.recorder.job import (
    API_CAPTURES,
    EXPORT,
    INPUT_ARGS,
    OPTIONAL_INPUT_ARGS,
    SESSION_ENVIRONMENT,
    ExportProbe,
    ExportStep,
    Job,
    OutputMap,
    Step,
    sha256_file,
)
from tools.parity.recorder.output import ensure_outside_repository, run_name, write_run
from tools.parity.recorder.session import (
    PainterCallError,
    PainterIdentity,
    PainterSession,
    RecorderError,
)
from tools.parity.recorder.sidecars import gltf_sidecars
from tools.parity.recorder.texture_sheet import Operator, operate, readback_specs, texture_sheet

Now = Callable[[], datetime]

# Export map names (lower case) whose document channel has another `ChannelType` name: the
# documented `ambientOcclusion` map is the AO channel; the documented virtual maps
# `Normal_OpenGL`/`Normal_DirectX` derive from the Normal channel and `AO_Mixed` from AO.
SOURCE_CHANNEL_OF_MAP = {
    "ambientocclusion": "ao",
    "normal_opengl": "normal",
    "normal_directx": "normal",
    "ao_mixed": "ao",
}

# Encoding of an exported file that states none and has no single document channel that gives
# one (a converted virtual map, a file of an export probe): the record makes no colour-space
# claim; the consumer determines it, e.g. against the OpenEXR twin (decision 087).
UNDETERMINED = "undetermined"

# A bake (every texture set it covers) must end within this time.
BAKE_TIMEOUT_S = 1800.0

# Path characters a `file:///` URL carries without percent-encoding (RFC 3986 unreserved, the
# path separator and the drive colon); any other character makes the URL ambiguous.
URL_SAFE_PATH = re.compile(r"[A-Za-z0-9._~/:-]+")

# A manifest setting naming the stem of r2's project file (`project_file_name`).
PROJECT_FILE_NAME = "project.file_name"
REOPEN_COUNT = "recorder.reopen_count"
PROJECT_STEM = re.compile(r"[a-z0-9][a-z0-9_-]*(\.[a-z0-9_-]+)*")


def utc_now() -> datetime:
    return datetime.now(UTC)


def output_safe(text: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")
    return value if value and value[0].isalnum() else f"x{value}"


def stage_inputs(job: Job, directory: Path) -> dict[str, Path]:
    """Copy the inputs next to the throwaway project so Painter never reads the repository."""
    directory.mkdir(parents=True)
    staged: dict[str, Path] = {}
    for input_id, source in job.inputs.items():
        target = directory / f"{input_id}{source.suffix}"
        shutil.copyfile(source, target)
        staged[input_id] = target
    return staged


def session_file_key(sha256: str) -> str:
    """The staged-input key of a session file named by its SHA-256 (never an input id)."""
    return f"session:{sha256}"


def stage_session_files(job: Job, files: list[Path], directory: Path) -> dict[str, Path]:
    """Stage the files the job's session-environment steps name by SHA-256, under the step's
    file name (the session resource takes its name from the file)."""
    by_hash = {sha256_file(path): path for path in files}
    staged: dict[str, Path] = {}
    for step in job.state_steps:
        if step.call != ps.SET_ENVIRONMENT or SESSION_ENVIRONMENT not in step.args:
            continue
        digest = step.args[SESSION_ENVIRONMENT]
        if digest not in by_hash:
            raise RecorderError(
                f"step {step.step}: no --session-file has SHA-256 {digest} "
                f"({step.args['file_name']})"
            )
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / step.args["file_name"]
        shutil.copyfile(by_hash[digest], target)
        staged[session_file_key(digest)] = target
    return staged


def file_url(path: PurePath) -> str:
    """The `file:///` URL of a staged file, as the documented baking example builds it
    (`QUrl.fromLocalFile(path).toString()`); refuses a path that would need percent-encoding."""
    posix = path.as_posix()
    if not path.is_absolute() or not URL_SAFE_PATH.fullmatch(posix):
        raise RecorderError(
            f"{posix}: a file URL of this path would need percent-encoding; use a work directory "
            "whose path holds only letters, digits and . _ ~ / : -"
        )
    return "file://" + posix if posix.startswith("/") else "file:///" + posix


def wait_baked(session: PainterSession, step: int, timeout_s: float = BAKE_TIMEOUT_S) -> Any:
    """Poll `baking_state` until the bake a step launched has ended; any status other than
    `Success` refuses the golden."""
    deadline = session.monotonic() + timeout_s
    while True:
        state = session.call("baking_state")
        if state["ended"]:
            break
        if session.monotonic() >= deadline:
            raise RecorderError(
                f"step {step}: timed out after {timeout_s:.0f} s waiting for BakingProcessEnded"
            )
        session.sleep(session.poll_interval_s)
    if state["status"] != ps.BAKE_SUCCESS:
        raise RecorderError(f"step {step}: the bake ended with status {state['status']}")
    return state


def replay(session: PainterSession, job: Job, staged: dict[str, Path]) -> dict[str, Any]:
    """Apply the state steps; returns the effective defaults read along the way."""
    defaults: dict[str, Any] = {"insert_fill": {}}
    for step in job.state_steps:
        resolved = {}
        key = INPUT_ARGS.get(step.call)
        if key is not None and key in step.args:
            resolved[key] = staged[step.args[key]].as_posix()
        if step.call == ps.SET_ENVIRONMENT and SESSION_ENVIRONMENT in step.args:
            name = session_file_key(step.args[SESSION_ENVIRONMENT])
            if name not in staged:
                raise RecorderError(
                    f"step {step.step}: the session environment "
                    f"{step.args[SESSION_ENVIRONMENT]} was not given (--session-file)"
                )
            resolved["environment"] = staged[name].as_posix()
        key = OPTIONAL_INPUT_ARGS.get(step.call)
        if key is not None and key in step.args:
            resolved[key] = file_url(staged[step.args[key]])
        result = session.call(
            "apply_step", step=step.step, call=step.call, args=step.args, resolved=resolved
        )
        if step.call == ps.BAKE:
            ended = wait_baked(session, step.step)
            session.wait_ready()
            defaults.setdefault("bakes", {})[str(step.step)] = {
                "status": ended["status"],
                "texture_sets": ended["baked"],
                "enabled_bakers": result["enabled_bakers"],
            }
        elif step.call == ps.CREATE:
            session.wait_ready()
            defaults["project.create"] = session.call("template_capture")
            defaults["colour_management"] = result["colour_management"]
        elif step.call == ps.INSERT_FILL:
            defaults["insert_fill"][str(step.step)] = result["defaults"]
        elif step.call in (ps.INSERT_GROUP, ps.INSERT_LEVELS, ps.INSERT_FILTER):
            inserted = {k: v for k, v in result.items() if k != "done_at"}
            defaults.setdefault("inserted_nodes", {})[str(step.step)] = inserted
        elif step.call == ps.SET_COLOR_SPACE:
            attempt = {k: v for k, v in result.items() if k != "done_at"}
            defaults.setdefault("set_color_space", {})[str(step.step)] = attempt
        elif "resource_url" in result:
            defaults.setdefault("resources", {})[str(step.step)] = result["resource_url"]
    session.wait_ready()
    return defaults


def bake_readback_specs(job: Job, defaults: dict[str, Any]) -> list[dict[str, Any]]:
    """`get_mesh_map_resource` of every usage enabled when each bake ran (known after replay)."""
    specs: list[dict[str, Any]] = []
    for step in job.state_steps:
        if step.call != ps.BAKE:
            continue
        enabled = defaults["bakes"][str(step.step)]["enabled_bakers"]
        scope = {"texture_set": step.args["texture_set"]} if "texture_set" in step.args else {}
        for usage in sorted({name for names in enabled.values() for name in names}):
            specs.append({"call": ps.GET_MESH_MAP, "args": {"usage": usage, **scope}})
    return specs


def readback_outputs(
    session: PainterSession,
    job: Job,
    template: dict[str, Any],
    extra_specs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    specs = job.readback_specs()
    specs += [spec for spec in extra_specs or [] if spec not in specs]
    if any(step.call == ps.SET_RESOLUTIONS for step in job.state_steps):
        specs += [
            {"call": ps.GET_RESOLUTION, "args": {"texture_set": name}}
            for name in sorted(template["texture_sets"])
        ]
    return [
        api_readback(
            session,
            "/".join(
                [
                    "readback",
                    spec["call"].rsplit(".", 1)[1],
                    *(output_safe(str(v)) for v in spec["args"].values()),
                ]
            ),
            spec["call"],
            spec["args"],
        )
        for spec in specs
    ]


def api_readback(
    session: PainterSession, output_id: str, call: str, args: dict[str, Any]
) -> dict[str, Any]:
    """One documented call read through `readback`; an exception Painter raises is recorded."""
    output: dict[str, Any] = {
        "output_id": output_id,
        "kind": "api_readback",
        "call": call,
        "args": args,
    }
    try:
        output["value"] = session.call("readback", call=call, args=args)
    except PainterCallError as error:
        output["value"] = None
        output["raised"] = {"type": error.kind, "message": error.message}
    return output


def capture_output(session: PainterSession, step: Step) -> dict[str, Any]:
    """A texture-job capture (export presets, a bitmap's colour spaces): `<prefix>/s<step>`."""
    prefix = API_CAPTURES[step.call][0]
    return api_readback(session, f"{prefix}/s{step.step}", step.call, dict(step.args))


def export_roots(template: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (texture_set, stack)
        for texture_set, info in sorted(template["texture_sets"].items())
        for stack in sorted(info["stacks"])
    ]


def channel_encoding(
    template: dict[str, Any],
    texture_set: str,
    stack: str,
    out: OutputMap,
    channel_names: dict[str, str] | None = None,
) -> str:
    """Encoding from the source channel's documented storage (`textureset.ChannelFormat`).

    Used only when the exported file does not state its encoding; the record names the basis.
    `channel_names` maps a lower-case `ChannelType` member to its `.name` as Painter reports it
    (a legacy alias such as `Roughness` reports the member it aliases).
    """
    channels = template["texture_sets"][texture_set]["stacks"][stack]
    if out.map_type in ("documentMap", "virtualMap"):
        wanted = SOURCE_CHANNEL_OF_MAP.get(out.name.lower(), out.name.lower())
        wanted = (channel_names or {}).get(wanted, wanted).lower()
        for name, channel in channels.items():
            if name.lower() == wanted:
                return "srgb" if str(channel["format"]).startswith("sRGB") else "linear"
    raise RecorderError(
        f"{texture_set}/{out.name}: the export states no encoding and no document channel gives one"
    )


def export_outputs(
    session: PainterSession,
    export: ExportStep,
    template: dict[str, Any],
    directory: Path,
    keyed_by_step: frozenset[str] = frozenset(),
) -> tuple[list[dict[str, Any]], list[Path]]:
    """Export one step; a map named in `keyed_by_step` gets the step in its output id."""
    roots = export_roots(template)
    export_dir = directory / f"export-step{export.step}"
    export_dir.mkdir(parents=True)
    session.wait_ready()
    fence_ns = write_fence(directory / f"fence-step{export.step}")
    config = export.config(export_dir, [ts if not st else f"{ts}/{st}" for ts, st in roots])
    result = session.call("export_textures", config=config)
    if result["status"] != "Success":
        raise RecorderError(f"export step {export.step}: {result['status']}: {result['message']}")
    files = [Path(f) for group in result["textures"] for f in group["files"]]
    verify_current_outputs(files, export_dir, fence_ns)
    outputs: list[dict[str, Any]] = []
    blobs: list[Path] = []
    channel_names: dict[str, str] | None = None
    for group in result["textures"]:
        texture_set, stack = group["texture_set"], group["stack"]
        for name in group["files"]:
            path = Path(name)
            stems = {m.file_name.replace("$textureSet", texture_set): m for m in export.maps}
            out = stems.get(path.stem)
            if out is None:
                raise RecorderError(f"export wrote {path.name}, which no requested map names")
            measured = measure_storage_format(path)
            if measured.encoding is not None:
                encoding, basis = measured.encoding, "file"
            elif out.map_type == "defaultMap":
                # The documented constant maps (`black`, `white`): 0 and 1 in any encoding.
                encoding, basis = "linear", "constant_default_map"
            elif out.map_type == "meshMap":
                # Baked mesh maps hold data (directions, occlusion, positions), not colour.
                encoding, basis = "linear", "baked_mesh_map"
            elif out.map_type == "virtualMap" and out.name.lower() not in SOURCE_CHANNEL_OF_MAP:
                # A converted virtual map (Diffuse, f0, 1/ior, ...) derives from several
                # channels: no single channel format gives its encoding.
                encoding, basis = UNDETERMINED, "converted_virtual_map"
            else:
                if channel_names is None:
                    reported = session.call("channel_names")
                    channel_names = {k.lower(): v for k, v in reported.items()}
                encoding = channel_encoding(template, texture_set, stack, out, channel_names)
                basis = "source_channel_format"
            parts = [output_safe(texture_set), *([output_safe(stack)] if stack else []), out.stem]
            if out.name in keyed_by_step:
                parts.append(f"step{export.step}")
            outputs.append(
                {
                    "output_id": "/".join(parts),
                    "kind": "exported_map",
                    "texture_set": texture_set if not stack else f"{texture_set}/{stack}",
                    "map": out.name,
                    "blob": {
                        "sha256": sha256_file(path),
                        "size_bytes": path.stat().st_size,
                        "media_type": MEDIA_TYPES[measured.container],
                    },
                    "storage_format": measured.as_schema(encoding),
                    "export_settings": {
                        **export.parameters,
                        "step": export.step,
                        "map_type": out.map_type,
                        "map_channels": out.channels,
                        "encoding_basis": basis,
                    },
                }
            )
            blobs.append(path)
    return outputs, blobs


def relative_files(groups: list[dict[str, Any]], root: Path) -> dict[str, list[str]]:
    """Painter's `(texture set, stack) -> files` as `"<set>[/<stack>]" -> paths relative to the
    probe's export directory`. A path outside it is recorded relative to it (`../...`), or by
    its file name on another drive, and is never read."""
    listed: dict[str, list[str]] = {}
    for group in groups:
        stack = group["stack"]
        key = group["texture_set"] if not stack else f"{group['texture_set']}/{stack}"
        names: list[str] = []
        for name in group["files"]:
            path = Path(os.path.normpath(name))
            try:
                names.append(Path(os.path.relpath(path, root)).as_posix())
            except ValueError:
                names.append(f"<other drive>/{path.name}")
        listed[key] = names
    return listed


def probe_readback(
    output_id: str, call: str, probe: ExportProbe, value: Any, error: PainterCallError | None
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "output_id": output_id,
        "kind": "api_readback",
        "call": call,
        "args": {"config": probe.config_id},
        "value": value,
    }
    if error is not None:
        output["raised"] = {"type": error.kind, "message": error.message}
    return output


def probe_outputs(
    session: PainterSession, probe: ExportProbe, directory: Path
) -> tuple[list[dict[str, Any]], list[Path]]:
    """Run one export probe (decision 087): the dry run of its configuration and, when the dry
    run succeeds, the export into a fresh directory. Painter's answer, a raised error included,
    is the observation, and so are the files the directory then holds and how they differ from
    the files Painter reports; a file written before the fence is still refused as stale."""
    root = (directory / f"probe-step{probe.step}").resolve()
    root.mkdir(parents=True)
    prefix = f"probe/s{probe.step}"
    config = probe.config_at(root)
    session.wait_ready()
    try:
        listed = session.call("list_textures", config=config)
    except PainterCallError as error:
        return [probe_readback(f"{prefix}/list", ps.LIST_TEXTURES, probe, None, error)], []
    files = relative_files(listed["textures"], root)
    outputs = [probe_readback(f"{prefix}/list", ps.LIST_TEXTURES, probe, files, None)]
    session.wait_ready()
    fence_ns = write_fence(directory / f"fence-probe-step{probe.step}")
    raised: PainterCallError | None = None
    reported: dict[str, list[str]] = {}
    value: dict[str, Any] | None = None
    try:
        result = session.call("export_textures", config=config)
        reported = relative_files(result["textures"], root)
        value = {"status": result["status"], "message": result["message"], "textures": reported}
    except PainterCallError as error:
        raised = error
    present = sorted(path for path in root.rglob("*") if path.is_file() or path.is_symlink())
    for path in present:
        if path.is_symlink():
            raise StaleCaptureError(f"{path.name}: a link in the probe's export directory")
        if path.stat().st_mtime_ns < fence_ns:
            raise StaleCaptureError(f"{path.name} was written before export probe {probe.step}")
    on_disk = [path.relative_to(root).as_posix() for path in present]
    named = {name for names in reported.values() for name in names}
    inventory = {"missing": sorted(named - set(on_disk)), "unlisted": sorted(set(on_disk) - named)}
    if value is not None:
        value["directory"] = inventory
    outputs.append(probe_readback(f"{prefix}/export", EXPORT, probe, value, raised))
    if raised is not None:
        outputs[-1]["value"] = {"directory": inventory}
    sidecars = gltf_sidecars(present, root)
    for path, name in zip(present, on_disk, strict=True):
        if path in sidecars:
            outputs.append(
                {
                    "output_id": "/".join(
                        [prefix, *(output_safe(part) for part in name.split("/"))]
                    ),
                    "kind": "exported_sidecar",
                    "file": name,
                    "blob": {
                        "sha256": sha256_file(path),
                        "size_bytes": path.stat().st_size,
                        "media_type": sidecars[path],
                    },
                    "export_settings": {"step": probe.step, "probe": True},
                }
            )
            continue
        groups = sorted(key for key, names in reported.items() if name in names)
        measured = measure_storage_format(path)
        encoding, basis = (
            (measured.encoding, "file")
            if measured.encoding is not None
            else (UNDETERMINED, "export_probe")
        )
        outputs.append(
            {
                "output_id": "/".join([prefix, *(output_safe(part) for part in name.split("/"))]),
                "kind": "exported_map",
                "texture_set": ", ".join(groups) or "unlisted",
                "map": name,
                "blob": {
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                    "media_type": MEDIA_TYPES[measured.container],
                },
                "storage_format": measured.as_schema(encoding),
                "export_settings": {"step": probe.step, "probe": True, "encoding_basis": basis},
            }
        )
    return outputs, present


def reopen_count(job: Job) -> int:
    """Default to one reopen; requests may explicitly select up to three."""
    settings = [s for s in job.manifest["applied_settings"] if s["name"] == REOPEN_COUNT]
    if not settings:
        return 1
    setting = settings[0]
    value = setting["value"]
    if (
        len(settings) != 1
        or setting["applied_by"] != "recorder_api"
        or type(value) is not int
        or value not in (1, 2, 3)
    ):
        raise RecorderError(
            f"{job.golden_id}: `{REOPEN_COUNT}` must be one recorder_api integer from 1 to 3"
        )
    return int(value)


def project_file_name(job: Job) -> str:
    """The file name r2's project is saved under: `golden.spp`, or the stem a manifest names in
    its `project.file_name` setting (applied by the recorder; decision 093, a project name
    holding dots for the `$project` export wildcard)."""
    names = [
        s["value"]
        for s in job.manifest["applied_settings"]
        if s["name"] == PROJECT_FILE_NAME and s["applied_by"] == "recorder_api"
    ]
    if not names:
        return "golden.spp"
    stem = names[0]
    if len(names) > 1 or not isinstance(stem, str) or not PROJECT_STEM.fullmatch(stem):
        raise RecorderError(
            f"{job.golden_id}: `{PROJECT_FILE_NAME}` must be one file stem "
            f"({PROJECT_STEM.pattern}), not {names!r}"
        )
    return f"{stem}.spp"


class Manifested(Protocol):
    """A recordable golden: a texture job or an API-probe job."""

    @property
    def manifest(self) -> dict[str, Any]: ...

    @property
    def golden_id(self) -> str: ...


def require_colour_management(job: Manifested, identity: PainterIdentity) -> None:
    """A manifest that names `OCIO` (applied by environment variable) is recorded only in a
    session started with that configuration: a Legacy session would record another project.
    Conversely, a manifest that names no `OCIO` is recorded only in a Legacy session (no `OCIO`,
    no `PAINTER_ACE_CONFIG`), so a Legacy golden is never recorded under another configuration."""
    named = [
        setting
        for setting in job.manifest["applied_settings"]
        if setting["applied_by"] == "environment_variable" and setting["name"] == "OCIO"
    ]
    if not named and identity.colour_management.get("mode") != "legacy":
        raise RecorderError(
            f"{job.golden_id}: records under Legacy colour management; restart Painter without "
            f"OCIO and PAINTER_ACE_CONFIG (found {identity.colour_management!r})"
        )
    for setting in named:
        found = str(identity.colour_management.get("OCIO") or "").replace("\\", "/")
        if identity.colour_management.get("mode") != "ocio" or not found.endswith(
            str(setting["value"])
        ):
            raise RecorderError(
                f"{job.golden_id}: start Painter with OCIO naming its {setting['value']} "
                f"(found {identity.colour_management!r})"
            )


def record_once(
    session: PainterSession,
    job: Job,
    identity: PainterIdentity,
    directory: Path,
    recording_id: str,
    condition: str,
    now: Now,
    extra_readbacks: list[dict[str, Any]] | None = None,
    operator_outputs: tuple[list[dict[str, Any]], list[Path]] = ([], []),
) -> tuple[dict[str, Any], list[Path]]:
    session.wait_ready()
    if job.export_probes or any(
        API_CAPTURES[step.call][0] == "presets" for step in job.api_captures
    ):
        session.wait_catalog_ready()
    template = session.call("template_capture")
    outputs: list[dict[str, Any]] = [
        {
            "output_id": "template/texture-sets",
            "kind": "template_capture",
            "subject": "texture sets, stacks and channel formats of the project",
            "values": template,
        }
    ]
    outputs += operator_outputs[0]
    outputs += readback_outputs(session, job, template, extra_readbacks)
    blobs: list[Path] = list(operator_outputs[1])
    captures: list[ExportStep | ExportProbe | Step] = [
        *job.exports,
        *job.export_probes,
        *job.api_captures,
    ]
    for capture in sorted(captures, key=lambda c: c.step):
        if isinstance(capture, Step):
            outputs.append(capture_output(session, capture))
            continue
        if isinstance(capture, ExportProbe):
            exported, files = probe_outputs(session, capture, directory)
        else:
            exported, files = export_outputs(
                session, capture, template, directory, job.maps_exported_twice
            )
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


def save_and_reopen(session: PainterSession, project_file: Path) -> None:
    locations = session.call("node_locations")
    project_file.parent.mkdir(parents=True, exist_ok=True)
    session.call("save_as", path=project_file.as_posix())
    saved = session.wait_ready()
    if saved.file_path is None or Path(saved.file_path).resolve() != project_file.resolve():
        raise RecorderError(
            f"project was not saved to {project_file} (Painter reports {saved.file_path})"
        )
    session.call("close_project")
    session.wait_closed()
    session.call("open_project", path=project_file.as_posix())
    session.wait_ready()
    session.call("rebind_nodes", locations=locations)


def close_quietly(session: PainterSession) -> None:
    """Discard the throwaway project; a failure here must not hide the original error."""
    try:
        session.call("close_project")
    except RecorderError:
        return


def record_texture_golden(
    session: PainterSession,
    job: Job,
    work: Path,
    inbox: Path,
    now: Now = utc_now,
    *,
    record_prefix: str = "",
    operator: Operator | None = None,
) -> Path:
    """Record one Tier 0-2b golden and its declared reopens; return the inbox run directory.

    A golden whose sheet names UI-set values needs `operator` (`texture_sheet.py`); without one
    it is refused, so a default can never be recorded in place of the sheet's value."""
    if job.tier == "3":
        raise RecorderError("Tier 3 goldens are Iray references: use the iray command")
    if not job.exports and not job.export_probes and not job.api_captures:
        raise RecorderError(
            "a texture golden needs at least one export_project_textures, export probe or "
            "capture step"
        )
    if job.captures:
        raise RecorderError("baking-defaults captures are recorded by the record-defaults command")
    sheet = texture_sheet(job)
    if sheet and operator is None:
        raise RecorderError(
            f"{job.golden_id}: its settings sheet names values only Painter's UI can set; "
            "record it with an operator (--operator ui or console)"
        )
    project_name = project_file_name(job)
    reopens = reopen_count(job)
    identity = session.connect()
    require_colour_management(job, identity)
    directory = ensure_outside_repository(work) / job.golden_id.replace("/", "__")
    directory = directory / run_name(identity.session_id, now())
    staged = stage_inputs(job, directory / "inputs")
    try:
        defaults = replay(session, job, staged)
        extra = bake_readback_specs(job, defaults) + readback_specs(sheet)
        applied = (
            operate(session, operator, sheet, directory / "r1-operator", apply=True)
            if sheet and operator is not None
            else ([], [])
        )
        first, first_blobs = record_once(
            session, job, identity, directory / "r1", "r1", "same_session", now, extra, applied
        )
        recordings, blobs = [first], list(first_blobs)
        for index in range(2, reopens + 2):
            recording_id = f"r{index}"
            save_and_reopen(session, directory / "project" / project_name)
            reread = (
                operate(
                    session, operator, sheet, directory / f"{recording_id}-operator", apply=False
                )
                if sheet and operator is not None
                else ([], [])
            )
            recording, captured = record_once(
                session,
                job,
                identity,
                directory / recording_id,
                recording_id,
                "after_save_reopen",
                now,
                extra,
                reread,
            )
            recordings.append(recording)
            blobs.extend(captured)
    finally:
        close_quietly(session)
    record = {
        "schema": "uzpainter/parity/golden-private/1",
        "record_class": "private_oracle_record",
        "golden_id": job.golden_id,
        "tier": job.tier,
        "key": {
            "inputs": job.input_hashes(),
            "instruction_sequence_sha256": job.instruction_sequence_sha256,
            "effective_defaults": defaults,
            "painter_build": identity.painter_build(),
            "project_settings": {
                "create": job.project_settings(),
                "colour_management": defaults["colour_management"],
            },
            "resource_hashes": [],
            "bake_backend": None,
            "render_state": None,
        },
        "recordings": recordings,
    }
    return write_run(
        inbox,
        record,
        blobs,
        job.manifest,
        identity.session_id,
        environment=identity.environment,
        record_prefix=record_prefix,
    )
