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

A native job (decision 300 item 7, the Tunic current round: `NativeJob`) has no create or export
script. Its round sends the recorder's own steps as typed calls instead:

1. `project_create` from the staged mesh with exactly the create step's six settings, no
   template and the `ocio_config_hash` of Painter's substance configuration, which the manifest
   must name (`NativeColourRefused` otherwise, before any call: never Legacy), then `set_list`:
   the project must hold exactly the step's texture set, or the round fails before the import;
2. `resource_import` of the staged Normal as a TEXTURE resource under the step's name and group:
   the imported entry must be the pinned bytes (its SHA-256);
3. `set_mesh_maps`: that entry's URL as the set's Normal, then `set_list` again: the set's bound
   mesh maps must be exactly the Normal, that entry (its SHA-256 and name, valid);
4. `project_save_as` (`full`), `sync_stack` as above and `project_save` (`full`), as the recorder
   saves after the sync, then the same `set_list` check again;
5. `export` with the closing configuration, its `exportPath` the round's: the only export.

A settings value (`project_create`) or a configuration (`export`) that UzPainter refuses as a
release gap ends the round as `refused`, naming it; any other failed call fails the round.

With a state scenario (`state`, the Tunic current round's `tunic_state.TUNIC_CURRENT`), the native
round also checks the state before its export (`tunic_state`), every step a typed call. The
scenario is checked against the job before any call. After the sync it sets
`shader_set {double_sided: true}` (decision 196) before the save. After the save and the Normal
check it reads `layer_list`, `project_recipe`, `shader_get` and `display_get` and checks them, the
two snapshots at the revision `shader_set` committed. Then `project_close` and `project_open` of
the saved project, the Normal check again, and the same reads and checks at the revision the
open reports, which must be the saved one; each reopened read must equal the first literally.
Only then the export, unchanged. Without a scenario the round is exactly as above.

`run_tunic_current` is the Tunic current round's entrypoint: `run_round` with `TUNIC_CURRENT`,
refused before UzPainter starts unless the manifest is `phase2/tier1/tunic-v10-current`'s and its
pinned job fits the scenario. No other round turns the state check on.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from tests.adapters.assets3d.wand import ASSETS3D, native_ocio_sha256
from tests.parity.tier1 import tunic_state
from tests.parity.tier1.tunic_state import StateMismatch, StateScenario
from tests.supervisor.conftest import Mcp
from tools.parity.recorder.job import canonical_json, sha256_bytes, sha256_file
from tools.parity.recorder.script_run import (
    NORMAL_USAGE,
    SYNC_OPTIONS,
    NativeJob,
    ScriptJob,
    load_pipeline_job,
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
# The calls whose release-gap refusal is the round's refusal: the export, and a native job's create.
REFUSABLE = frozenset({"export"})
NATIVE_REFUSABLE = frozenset({"project_create", "export"})


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


def refusal_of(
    tool: str, reply: dict[str, Any], refusable: frozenset[str] = REFUSABLE
) -> dict[str, str] | None:
    """The refusal before writing of a `refusable` call (the export), or None for any other
    failure."""
    error = reply["error"]
    kind = (error.get("details") or {}).get("type")
    if tool not in refusable or error.get("code") != REFUSAL:
        return None
    refusal = {"tool": tool, "error_code": REFUSAL}
    if isinstance(kind, str):
        refusal["type"] = kind
    return refusal


def run_round(
    painter: Path,
    work: Path,
    manifest: Path,
    backend: str = BACKEND,
    state: StateScenario | None = None,
) -> Round:
    """The round over the manifest's inputs staged in `work` (a fresh directory); a native job's
    with the `state` scenario's checks, if one is given."""
    job = load_pipeline_job(manifest, ASSETS3D)
    staged = stage_inputs(job, work / "assets")
    if state is not None:  # refused before UzPainter starts
        if not isinstance(job, NativeJob):
            raise RoundFailed(f"a state scenario applies to a native job, not {job.golden_id}")
        expected_of(state, job, staged, native_ocio_sha256(job))
    session = Mcp(painter, work, "--gpu-backend", backend)
    try:
        tools = {tool["name"] for tool in session.request("tools/list", {})["tools"]}
        log = Round(len(tools), "run_python" in tools)
        driver = Driver(session, log)
        drive(driver, job, staged, work, state)
        return log
    finally:
        session.close()


def run_tunic_current(painter: Path, work: Path, manifest: Path, backend: str = BACKEND) -> Round:
    """The Tunic current round (`phase2/tier1/tunic-v10-current`) with its state checks before
    the export (`tunic_state.TUNIC_CURRENT`); refused before UzPainter starts unless the manifest
    is that golden's and its pinned job fits the scenario."""
    return run_round(painter, work, manifest, backend, tunic_state.TUNIC_CURRENT)


def expected_of(
    state: StateScenario, job: NativeJob, staged: dict[str, Path], ocio: str
) -> tunic_state.Expected:
    """What `state` expects of `job` over its staged, pinned stack; `RoundFailed` (a contract
    mismatch) unless the scenario fits the job."""
    stack = json.loads(staged[job.sync.args["stack"]].read_bytes().decode("utf-8"))
    try:
        return tunic_state.expected_state(state, job, stack, ocio)
    except StateMismatch as error:
        raise RoundFailed(f"contract mismatch: {error}") from error


def sync_stack_arguments(job: ScriptJob | NativeJob, staged: dict[str, Path]) -> dict[str, Any]:
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


def drive(
    driver: Driver,
    job: ScriptJob | NativeJob,
    staged: dict[str, Path],
    work: Path,
    state: StateScenario | None = None,
) -> None:
    if isinstance(job, NativeJob):
        drive_native(driver, job, staged, work, state)
        return
    if state is not None:
        raise RoundFailed(f"a state scenario applies to a native job, not {job.golden_id}")
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


def drive_native(
    driver: Driver,
    job: NativeJob,
    staged: dict[str, Path],
    work: Path,
    state: StateScenario | None = None,
) -> None:
    """A native job's round (the module's docstring): its create's settings and Normal binding
    through the typed tools, each checked, then the sync and the closing config export; with
    `state`, the scenario's state checks before the export."""
    ocio = native_ocio_sha256(job)  # refused before any call
    log = driver.log
    expected = None
    if state is not None:  # refused before any call
        try:
            expected = expected_of(state, job, staged, ocio)
        except RoundFailed:
            log.outcome = "failed"
            raise
    create = job.create
    texture_set = str(create.args["texture_set"])
    pinned = create.normal.sha256

    def fail(message: str) -> RoundFailed:
        log.outcome = "failed"
        return RoundFailed(message)

    def send(tool: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """The call's result; None when it refused (the round's refusal is logged)."""
        reply = driver.call(tool, arguments)
        if "error" not in reply:
            result: dict[str, Any] = reply["result"]
            return result
        log.refusal = refusal_of(tool, reply, NATIVE_REFUSABLE)
        if log.refusal is None:
            raise fail(f"{tool} failed: {reply['error']}")
        log.outcome = "refused"
        return None

    def mesh_maps() -> dict[str, Any]:
        """The created project's one texture set's mesh maps; refused unless it is exactly the
        create step's set."""
        listed = send("set_list", {})
        assert listed is not None
        sets = [entry["name"] for entry in listed["texture_sets"]]
        if sets != [texture_set]:
            raise fail(
                f"contract mismatch: the created project's texture sets are {sets}, not exactly "
                f"the native create's {texture_set!r}"
            )
        maps: dict[str, Any] = listed["texture_sets"][0]["mesh_maps"]
        return maps

    def check_normal(baseline: dict[str, Any]) -> None:
        """Refused unless the one set binds exactly the Normal, as `baseline` (the import)."""
        bound = mesh_maps()
        if bound != {NORMAL_USAGE: baseline}:
            raise fail(f"the mesh maps bound are {bound}, not only the imported Normal {baseline}")

    created = {
        "mesh": str(staged[create.mesh.input_id]),
        "settings": create.settings,
        "ocio_config_hash": ocio,  # never Legacy
    }
    if send("project_create", created) is None:
        return
    mesh_maps()  # the one texture set, before the import
    imported = send(
        "resource_import",
        {
            "path": str(staged[create.normal.input_id]),
            "usage": "TEXTURE",
            "name": create.args["normal_name"],
            "group": create.args["normal_group"],
        },
    )
    assert imported is not None
    resource = imported["resource"]
    if resource["sha256"] != pinned:
        raise fail(f"the imported Normal is {resource['sha256']}, not the pinned {pinned}")
    maps = {NORMAL_USAGE: {"resource": resource["url"]}}
    send("set_mesh_maps", {"texture_set": texture_set, "maps": maps})
    baseline = {"sha256": pinned, "name": resource["name"], "invalid": False}
    check_normal(baseline)
    project = work / "project" / "native-create.uzp"
    send("project_save_as", {"path": str(project), "mode": "full"})
    synced = send("sync_stack", sync_stack_arguments(job, staged))
    revision: Any = None
    if expected is not None:
        send("shader_set", {"parameters": {"double_sided": True}})
        if log.calls[-1]["outcome"] != "committed":
            raise fail(
                f"shader_set double_sided true was {log.calls[-1]['outcome']}, not committed"
            )
        revision = log.calls[-1].get("committed_revision")
    send("project_save", {"mode": "full"})
    check_normal(baseline)  # after the sync and its save, before the export
    if expected is not None:
        reply = synced.get("returned", {}).get("sync") if isinstance(synced, dict) else None
        if not isinstance(reply, dict):
            raise fail("sync_stack returned no sync report")

        def observe(at: Any, fresh_uids: bool) -> dict[str, Any]:
            """The scenario's reads, checked, both snapshots at the revision `at`."""
            assert expected is not None and isinstance(reply, dict)
            reads = {
                tool: send(tool, arguments)
                for tool, arguments in (
                    ("layer_list", {"texture_set": texture_set}),
                    ("project_recipe", {}),
                    ("shader_get", {}),
                    ("display_get", {}),
                )
            }
            listing, dump = reads["layer_list"] or {}, reads["project_recipe"] or {}
            if type(at) is not int or listing.get("revision") != at or dump.get("revision") != at:
                raise fail(
                    f"the state reads are at revisions {listing.get('revision')} and "
                    f"{dump.get('revision')}, not the committed {at}"
                )
            try:
                tunic_state.check_listing(expected, listing, reply, fresh_uids)
                tunic_state.check_recipe(expected, dump)
                tunic_state.check_shader(reads["shader_get"] or {}, reads["display_get"] or {})
            except StateMismatch as error:
                raise fail(f"revision {at}: {error}") from error
            return reads

        saved = observe(revision, fresh_uids=True)
        send("project_close", {})
        opened = send("project_open", {"path": str(project), "wait": True})
        check_normal(baseline)  # after the reopen
        reopened_at = opened.get("revision") if isinstance(opened, dict) else None
        if reopened_at != revision:
            raise fail(f"the reopened project is at revision {reopened_at}, not {revision}")
        reopened = observe(reopened_at, fresh_uids=False)
        changed = [tool for tool in saved if reopened[tool] != saved[tool]]
        if changed:
            raise fail(f"after the reopen {changed} differ from the saved project's")
    config = {**job.config_export.config, "exportPath": str(work / "out" / "export")}
    exported = send("export", {"config": config})
    if exported is None:
        return
    for written in exported["files"]:
        path = Path(written["path"])
        log.files[(str(written["root_path"]), PurePosixPath(path.as_posix()).stem)] = path


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
