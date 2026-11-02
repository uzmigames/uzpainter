r"""A pilot's production round through typed MCP tools with Python disabled (phase2.9 item 2.5;
`docs/architecture/11-mcp-server.md` §6, §7; decision 192).

    round = run_round(painter, work, manifest)        # the golden's manifest (or its request)
    report = round_report(round, tier1, manifest, painter)

The round is the one the pipeline scripts run (`painter_create.py`, `painter_layer_stack.py
sync`, `painter_export.py`), sent as typed tool calls to `UzPainter.exe --mcp` started without
`--allow-python`, so `run_python` is not even listed:

1. `project_create` from the staged mesh with the manifest's applied project settings (OpenGL
   normals, the default resolution, no cameras), then `set_list`;
2. `set_mesh_maps`: the staged Normal and AO on the first texture set, as the create script binds
   them to `all_texture_sets()[0]`; a sync `texture_set` must name exactly that set, or the round
   fails before this first edit of a set (`mesh_maps_set`);
3. `project_save_as` (`full`), as the create script's `save_as(..., Full)`;
4. `sync_stack` with the staged stack JSON and its bitmaps' folder (the masks and the `base_tex`
   colour bitmaps), the command `painter_layer_stack.py sync` runs, and the sync's typed options
   (`resource_prefix`, `resource_group`, `texture_set`, decision 300 item 7) under the tool's
   arguments of the same names; a legacy sync gives none, so the tool's defaults apply as
   before. The sync's import closure has no counterpart: the round runs no Python;
5. `project_save` (`full`), as the export script saves before exporting;
6. `export` with the configuration the export script builds (`pipeline_export_config`).

The inputs are the manifest's pinned files, staged by hash like the Tier 1 runner's
(`stage_inputs`). Each call is logged with its receipt. The exported maps are compared byte for
byte with the Tier 1 run's (the same pilot rebuilt through the pipeline adapter). An export
UzPainter refuses before writing (a configuration it does not support yet) ends the round as
`refused`, naming the refusal; it is never a pass.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from tests.adapters.assets3d.wand import ASSETS3D
from tests.supervisor.conftest import Mcp
from tools.parity.recorder.job import canonical_json, sha256_bytes, sha256_file
from tools.parity.recorder.script_run import (
    SYNC_OPTIONS,
    ScriptJob,
    load_script_job,
    stage_inputs,
)
from tools.parity.schemas import load_json
from tools.parity.tier1.compare import CandidateRun
from tools.parity.tier1.mcp_round import SCHEMA_ID, equality

# The manifest's applied project settings and the `project_create` setting each one is.
PROJECT_SETTINGS = {
    "project.normal_map_format": "normal_map_format",
    "project.default_texture_resolution": "default_texture_resolution",
    "project.import_cameras": "import_cameras",
}
# The workers export on the CPU evaluator, as `UzPainter.exe run` does, so no device is needed: the
# round runs on Vulkan workers, which create none (the supervisor tests' convention).
BACKEND = "vulkan"
LONG = frozenset({"project_create", "project_save_as", "export"})  # waited for (`wait`)
# An export setting UzPainter refuses before writing (`NotYetSupported`) is `capability_gap`.
REFUSAL = "capability_gap"


def pipeline_export_config(prefix: str, out: Path, texture_sets: list[str]) -> dict[str, Any]:
    """The configuration the pipeline's `painter_export.py` builds (waist-v5 and wand11-v1 alike,
    their preset's name apart): BaseColor, Roughness, Metallic and Height document maps and the
    `Normal_OpenGL` virtual map as 16-bit PNG, sizeLog2 11, infinite padding, no dithering."""

    def document(name: str, source: str) -> dict[str, Any]:
        channels = "RGB" if name == "BaseColor" else "L"
        return {
            "fileName": f"{prefix}_{name}",
            "channels": [
                {
                    "destChannel": c,
                    "srcChannel": c,
                    "srcMapType": "documentMap",
                    "srcMapName": source,
                }
                for c in channels
            ],
        }

    normal = {
        "fileName": f"{prefix}_Normal",
        "channels": [
            {
                "destChannel": c,
                "srcChannel": c,
                "srcMapType": "virtualMap",
                "srcMapName": "Normal_OpenGL",
            }
            for c in "RGB"
        ],
    }
    maps = [
        document("BaseColor", "basecolor"),
        document("Roughness", "roughness"),
        document("Metallic", "metallic"),
        document("Height", "height"),
        normal,
    ]
    return {
        "exportShaderParams": False,
        "exportPath": str(out),
        "defaultExportPreset": "pipeline",
        "exportPresets": [{"name": "pipeline", "maps": maps}],
        "exportList": [{"rootPath": name} for name in texture_sets],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": "png",
                    "bitDepth": "16",
                    "sizeLog2": 11,
                    "paddingAlgorithm": "infinite",
                    "dithering": False,
                }
            }
        ],
    }


@dataclass
class Round:
    """What a round did: its call log, outcome, refusal and exported files."""

    tools_listed: int
    run_python_listed: bool
    calls: list[dict[str, Any]] = field(default_factory=list)
    outcome: str = "completed"
    refusal: dict[str, str] | None = None
    files: dict[tuple[str, str], Path] = field(default_factory=dict)


class RoundFailed(RuntimeError):
    """A call failed other than by the export's refusal."""


def call_outcome(reply: dict[str, Any]) -> str:
    """A logged call's outcome: `committed` or `no_op` for a mutation, `returned` for a read."""
    if "error" in reply:
        return "error"
    status = (
        reply.get("result", {}).get("status") if isinstance(reply.get("result"), dict) else None
    )
    if status in ("committed", "no_op"):
        return str(status)
    return "returned"


class Driver:
    """Sends typed calls and logs each with its receipt."""

    def __init__(self, session: Mcp, log: Round) -> None:
        self.session = session
        self.log = log

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        reply = self.session.call(tool, {**arguments, **({"wait": True} if tool in LONG else {})})
        receipt = reply.get("receipt", {})
        entry: dict[str, Any] = {
            "step": len(self.log.calls) + 1,
            "tool": tool,
            "typed": True,
            "outcome": call_outcome(reply),
            "receipt_sha256": sha256_bytes(canonical_json(receipt)),
            "seconds": round(time.monotonic() - started, 3),
        }
        if isinstance(receipt.get("admission"), str):
            entry["admission"] = receipt["admission"]
        if "committed_revision" in reply:
            entry["committed_revision"] = reply["committed_revision"]
        if "error" in reply:
            entry["error_code"] = str(reply["error"].get("code"))
        self.log.calls.append(entry)
        return reply


def refusal_of(tool: str, reply: dict[str, Any]) -> dict[str, str] | None:
    """The export's refusal before writing, or None for any other failure."""
    error = reply["error"]
    kind = (error.get("details") or {}).get("type")
    if tool != "export" or error.get("code") != REFUSAL:
        return None
    refusal = {"tool": tool, "error_code": REFUSAL}
    if isinstance(kind, str):
        refusal["type"] = kind
    return refusal


def run_round(painter: Path, work: Path, manifest: Path, backend: str = BACKEND) -> Round:
    """The round over the manifest's inputs staged in `work` (a fresh directory)."""
    job: ScriptJob = load_script_job(manifest, ASSETS3D)
    staged = stage_inputs(job, work / "assets")
    session = Mcp(painter, work, "--gpu-backend", backend)
    try:
        tools = {tool["name"] for tool in session.request("tools/list", {})["tools"]}
        log = Round(len(tools), "run_python" in tools)
        driver = Driver(session, log)
        drive(driver, job, staged, work)
        return log
    finally:
        session.close()


def sync_stack_arguments(job: ScriptJob, staged: dict[str, Path]) -> dict[str, Any]:
    """`sync_stack`'s arguments: the staged stack JSON, its bitmaps' folder (the job's validated
    masks, from the `masks` list or the `mask_folder`) and each typed option the sync gives."""
    arguments: dict[str, Any] = {
        "stack_json": str(staged[job.sync.args["stack"]]),
        "masks_dir": str(staged[job.sync.masks[0].input_id].parent),
    }
    given = dict(job.sync.options)
    for key, (flag, _) in SYNC_OPTIONS.items():
        if flag in given:
            arguments[key] = given[flag]
    return arguments


def mesh_maps_set(job: ScriptJob, sets: list[str]) -> str:
    """The texture set `set_mesh_maps` binds: the first, as the create script binds the maps to
    `all_texture_sets()[0]`. A sync `texture_set` must name that set, once: the create script's
    maps are never moved to another set."""
    if not sets:
        raise RoundFailed("the project has no texture set: refused before set_mesh_maps")
    named = dict(job.sync.options).get(SYNC_OPTIONS["texture_set"][0])
    if named is not None and (named != sets[0] or sets.count(named) != 1):
        raise RoundFailed(
            f"contract mismatch: the sync's texture_set {named!r} is not exactly the first of "
            f"the project's texture sets {sets}, to which the create script binds the mesh "
            "maps: refused before set_mesh_maps"
        )
    return sets[0]


def drive(driver: Driver, job: ScriptJob, staged: dict[str, Path], work: Path) -> None:
    log = driver.log
    assert job.create.arguments is not None and job.export.arguments is not None
    applied = {s["name"]: s["value"] for s in job.manifest["applied_settings"]}
    settings = {key: applied[name] for name, key in PROJECT_SETTINGS.items() if name in applied}
    out = work / "out" / "export"
    steps: list[tuple[str, Any]] = [
        ("project_create", {"mesh": str(staged[job.create.args["mesh"]]), "settings": settings}),
        ("set_list", {}),
        ("set_mesh_maps", None),  # on the first texture set set_list returns
        (
            "project_save_as",
            {"path": str(work / "project" / f"{job.create.arguments['name']}.uzp"), "mode": "full"},
        ),
        ("sync_stack", sync_stack_arguments(job, staged)),
        ("project_save", {"mode": "full"}),
        ("export", None),  # with the texture sets set_list returns
    ]
    sets: list[str] = []
    for tool, arguments in steps:
        if tool == "set_mesh_maps":
            maps = {
                usage: {"path": str(staged[job.create.args[key]])}
                for usage, key in (("Normal", "normal"), ("AO", "ao"))
            }
            try:
                texture_set = mesh_maps_set(job, sets)
            except RoundFailed:
                log.outcome = "failed"
                raise
            arguments = {"texture_set": texture_set, "maps": maps}
        elif tool == "export":
            prefix = str(job.export.arguments["prefix"])
            arguments = {"config": pipeline_export_config(prefix, out, sets)}
        reply = driver.call(tool, arguments)
        if "error" in reply:
            log.refusal = refusal_of(tool, reply)
            log.outcome = "refused" if log.refusal is not None else "failed"
            if log.refusal is None:
                raise RoundFailed(f"{tool} failed: {reply['error']}")
            return
        if tool == "set_list":
            sets = [entry["name"] for entry in reply["result"]["texture_sets"]]
        if tool == "export":
            for written in reply["result"]["files"]:
                path = Path(written["path"])
                root = str(written["root_path"])
                log.files[(root, PurePosixPath(path.as_posix()).stem)] = path


def round_report(
    log: Round, tier1: CandidateRun, manifest: Path, painter: Path, backend: str = BACKEND
) -> dict[str, Any]:
    """The report of `log` (`tools.parity.tier1.mcp_round`), its maps next to the Tier 1 run's."""
    keys = sorted(set(log.files) | set(tier1.files))
    maps = [
        {
            "texture_set": texture_set,
            "map": name,
            "sha256": sha256_file(log.files[(texture_set, name)])
            if (texture_set, name) in log.files
            else None,
            "tier1_sha256": sha256_file(tier1.files[(texture_set, name)])
            if (texture_set, name) in tier1.files
            else None,
        }
        for texture_set, name in keys
    ]
    report: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "golden_id": load_json(manifest)["golden_id"],
        "manifest_sha256": sha256_file(manifest),
        "run": {
            "date": datetime.now(UTC).date().isoformat(),
            "exe_sha256": hashlib.sha256(painter.read_bytes()).hexdigest(),
            "backend": backend,
            "tools_listed": log.tools_listed,
        },
        "python": {"allow_python": False, "run_python_listed": log.run_python_listed},
        "calls": log.calls,
        "outcome": log.outcome,
        "maps": maps,
        "equal_to_tier1": equality(log.outcome, maps),
    }
    if log.refusal is not None:
        report["refusal"] = log.refusal
    return report
