"""Texture goldens (Tiers 0-2b): state replay, readbacks, exports, two recordings (2.2, 2.3, 2.6).

1. Replay the job's state steps once through the documented API, reading effective defaults as
   they appear (fresh fill layers, the channel set `project.create` produced).
2. Recording `same_session`: template capture, readback of every property the sequence set,
   then each export step: wait for readiness (edition state entered, not busy), write the
   fence, export into a fresh directory, verify the exported files are current (`capture.py`).
3. Save the project (Full), close it, reopen it, find the layers again at their recorded places.
4. Recording `after_save_reopen`: the same captures.
5. Write the private record and the public manifest to the oracle inbox (`output.py`).

The throwaway project and the exports live in the private work directory; the project is closed
when the recorder finishes or fails, never saved anywhere else.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.capture import (
    MEDIA_TYPES,
    measure_storage_format,
    verify_current_outputs,
    write_fence,
)
from tools.parity.recorder.job import INPUT_ARGS, ExportStep, Job, OutputMap, sha256_file
from tools.parity.recorder.output import ensure_outside_repository, run_name, write_run
from tools.parity.recorder.session import (
    PainterCallError,
    PainterIdentity,
    PainterSession,
    RecorderError,
)

Now = Callable[[], datetime]


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


def replay(session: PainterSession, job: Job, staged: dict[str, Path]) -> dict[str, Any]:
    """Apply the state steps; returns the effective defaults read along the way."""
    defaults: dict[str, Any] = {"insert_fill": {}}
    for step in job.state_steps:
        resolved = {}
        key = INPUT_ARGS.get(step.call)
        if key is not None:
            resolved[key] = staged[step.args[key]].as_posix()
        result = session.call(
            "apply_step", step=step.step, call=step.call, args=step.args, resolved=resolved
        )
        if step.call == ps.CREATE:
            session.wait_ready()
            defaults["project.create"] = session.call("template_capture")
            defaults["colour_management"] = result["colour_management"]
        elif step.call == ps.INSERT_FILL:
            defaults["insert_fill"][str(step.step)] = result["defaults"]
    session.wait_ready()
    return defaults


def readback_outputs(
    session: PainterSession, job: Job, template: dict[str, Any]
) -> list[dict[str, Any]]:
    specs = job.readback_specs()
    if any(step.call == ps.SET_RESOLUTIONS for step in job.state_steps):
        specs += [
            {"call": ps.GET_RESOLUTION, "args": {"texture_set": name}}
            for name in sorted(template["texture_sets"])
        ]
    outputs: list[dict[str, Any]] = []
    for spec in specs:
        output: dict[str, Any] = {
            "output_id": "/".join(
                [
                    "readback",
                    spec["call"].rsplit(".", 1)[1],
                    *(output_safe(str(v)) for v in spec["args"].values()),
                ]
            ),
            "kind": "api_readback",
            "call": spec["call"],
            "args": spec["args"],
        }
        try:
            output["value"] = session.call("readback", call=spec["call"], args=spec["args"])
        except PainterCallError as error:
            output["value"] = None
            output["raised"] = {"type": error.kind, "message": error.message}
        outputs.append(output)
    return outputs


def export_roots(template: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (texture_set, stack)
        for texture_set, info in sorted(template["texture_sets"].items())
        for stack in sorted(info["stacks"])
    ]


def channel_encoding(template: dict[str, Any], texture_set: str, stack: str, out: OutputMap) -> str:
    """Encoding from the source channel's documented storage (`textureset.ChannelFormat`).

    Used only when the exported file does not state its encoding; the record names the basis.
    """
    channels = template["texture_sets"][texture_set]["stacks"][stack]
    if out.map_type == "documentMap":
        for name, channel in channels.items():
            if name.lower() == out.name.lower():
                return "srgb" if str(channel["format"]).startswith("sRGB") else "linear"
    raise RecorderError(
        f"{texture_set}/{out.name}: the export states no encoding and no document channel gives one"
    )


def export_outputs(
    session: PainterSession,
    export: ExportStep,
    template: dict[str, Any],
    directory: Path,
) -> tuple[list[dict[str, Any]], list[Path]]:
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
            else:
                encoding = channel_encoding(template, texture_set, stack, out)
                basis = "source_channel_format"
            parts = [output_safe(texture_set), *([output_safe(stack)] if stack else []), out.name]
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


def record_once(
    session: PainterSession,
    job: Job,
    identity: PainterIdentity,
    directory: Path,
    recording_id: str,
    condition: str,
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
        }
    ]
    outputs += readback_outputs(session, job, template)
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


def save_and_reopen(session: PainterSession, project_file: Path) -> None:
    locations = session.call("node_locations")
    project_file.parent.mkdir(parents=True)
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
) -> Path:
    """Record one Tier 0-2b golden twice and write it to the inbox; returns the run directory."""
    if job.tier == "3":
        raise RecorderError("Tier 3 goldens are Iray references: use the iray command")
    if not job.exports:
        raise RecorderError("a texture golden needs at least one export_project_textures step")
    identity = session.connect()
    directory = ensure_outside_repository(work) / job.golden_id.replace("/", "__")
    directory = directory / run_name(identity.session_id, now())
    staged = stage_inputs(job, directory / "inputs")
    try:
        defaults = replay(session, job, staged)
        first, first_blobs = record_once(
            session, job, identity, directory / "r1", "r1", "same_session", now
        )
        save_and_reopen(session, directory / "project" / "golden.spp")
        second, second_blobs = record_once(
            session, job, identity, directory / "r2", "r2", "after_save_reopen", now
        )
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
        "recordings": [first, second],
    }
    return write_run(inbox, record, first_blobs + second_blobs, job.manifest, identity.session_id)
