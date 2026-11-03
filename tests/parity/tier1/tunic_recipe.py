r"""The Tunic current round's dump-and-rebuild (phase2.10_pilot-tunic-recovery item 2.4) through the
public recipe facade, as the Wand's (`tests/parity/recipe/wand_v1/runner.py`) is: an adapter
round, not an MCP-only one. There is no typed `project_rebuild` tool.

    round = run_tunic_recipe(painter, work, manifest)    # the golden's manifest

1. **The state round** (`state_round`): `mcp_round.drive` with `tunic_state.TUNIC_CURRENT`
   unchanged, typed MCP with Python disabled (its `tools/list` first, refused before any call if
   it names `run_python`), its replies recorded so the sync's reply, the saved
   project's path and the reopened reads are known. Only an export refusal may end it.
2. **The original** (`original_session`), in a fresh MCP session that first lists its tools
   (`listed`) and refuses before any project call if `run_python` is among them: `project_open`
   of the saved
   project at the round's revision; `set_list`, `layer_list`, `project_recipe` (the FULL dump),
   `shader_get` and `display_get`, checked through `tunic_state` with `fresh_uids=False` and equal
   to the round's reopened reads literally (the same project), the dump written to
   `original/recipe/dump.json`; then the export of the job's
   `config_export.config`, only its `exportPath` changed; then `project_close`.
3. **The bundle** (`bundle_resources`): `UzPainter.exe export-bundle` of the saved project. Its
   revision must be the dump's. Paint-plane content stays refused (the run ends `refused`, nothing
   is deleted). Before any file is read, every entry's `file` must be a plain relative path that
   stays inside the bundle once resolved, links followed (`bundle_file`): an absolute, rooted,
   drive-relative or `..` entry fails the run even when its file has the right hash. Every hash
   of the dump's `resource_hashes` must be a bundle entry whose file has
   that SHA-256 and the size both the entry and the recipe state, or the run fails: a missing
   resource is NEVER filled from the original inputs. Only then are they copied to
   `resources/<sha256>.<ext>`.
4. **The rebuild** (`rebuild`), in a separate `UzPainter.exe run` of `REBUILD`: the public
   `uzpainter.project.rebuild_from_recipe(dump, resources)`, then `save_as` (full) to a new file;
   it returns the saved file, its revision and its `dump_recipe()`. A `NotYetSupported` refusal
   ends the run `refused`; any other error fails it.
5. **The rebuilt project** (`rebuilt_session`), in a fresh MCP session listed and refused as
   the original's: `project_open` at the
   rebuild's revision, the same reads and checks, its dump equal to the rebuild's literally; then
   `project_save` (full), `project_close`, `project_open` and the reads again, equal to the first
   literally; then the same export, and `project_close`. No `run_python` is sent in any session,
   and each of the three sessions' own `tools/list` must not list it. The rebuild itself is the
   separate public-facade process of step 4, never an MCP tool.
6. **The comparison** (`compare_projects`), original against rebuilt:
   - the two dumps literally, key presence included (a missing key is never a null one),
     `revision` alone excepted: `digest`, `recipe`, the whole `rebuild`
     block (display, export defaults, metadata, catalog, mesh source, rebuild-only settings),
     `resource_hashes` and every version field. The rebuild block lies outside the digest, so an
     equal digest alone proves nothing about it;
   - `double_sided` true in both dumps' `/display` block (decision 196), named on its own;
   - `set_list` (the mesh bindings) literally but for its `revision`, which each snapshot checks
     against its own opened revision; `shader_get` and `display_get` (OCIO and display), which
     carry no revision, literally (`REVISIONED`);
   - `layer_list` after `canonical_listing`, the only normalisation;
   then the report of `tools.parity.recipe_rebuild` (digests and exported files by name):
   `pass` only for equal digests and identical files; both exports refused alike is
   `export_refused`, one refused is `fail`. A refusal is never counted as file equality.

**The normalisation** (`canonical_listing`), across projects only: a rebuild allocates new uids
(`src/uzp_core/manifest/recipe.cpp`, `RebuildManifest`). Each node gets a handle from the freshly
resolved hierarchy: a root is `Substack[<index>]`, and a child is `<parent's handle>/<slot>[<n>]`
for the n-th uid of its parent's `children` (Substack), `content_effects` (Content) or
`mask.effects` (Mask) list. The child must name that parent and slot, and its `index` must be `n`.
Every node must be reached exactly once. Only the fields `layer_list` proves to be uid references
(`src/uzp_core/document/layer_tree.cpp`, `SnapshotLayerTree` and `Params`) are rewritten: `uid`,
`parent`, those three lists, and the node's `texture_set` and `stack` ids, which must be one pair.
Every other field stays literal, bindings, settings, blending, names and versions included. A
reference source's `anchor` or an instance's `instance_source` (none in the Tunic) is not
normalised, so it would refuse the round. The listing's `revision` is checked inside each project,
not across them. Within one project, save and reopen stay literal: nothing is normalised.

Assumptions (accepted by the coordinator, 2026-11-02): the original is a fresh reopen of the
state round's saved project, and the state round's own export is not reused; `display_get` and
`set_list` hold no project-specific uid or path, and the dump no uid; the rebuilt project's
save/reopen check is both the rebuild process's dump against the MCP reopen and the MCP save,
close and open; `state_round` repeats `mcp_round.run_round`'s guard and call of `drive` rather
than adding a hook to `mcp_round`; the export and the rebuild run on the round's `BACKEND`. No
run of UzPainter backs the literal comparisons here. A field that legitimately differs refuses
the round, and only a proof for that specific field may relax its comparison.
"""

from __future__ import annotations

import copy
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from tests.adapters.assets3d import wand
from tests.parity.tier1 import mcp_round, tunic_state
from tests.parity.tier1.mcp_round import BACKEND, NATIVE_REFUSABLE, Driver, Round, refusal_of
from tests.parity.tier1.tunic_state import Expected, StateMismatch
from tests.supervisor.conftest import JSON_PREFIX, Mcp
from tools.parity.recipe_rebuild import Side, report, sha256_of
from tools.parity.recorder.job import sha256_bytes
from tools.parity.recorder.script_run import NativeJob, load_pipeline_job, stage_inputs

# The reads of each snapshot, in order; `layer_list` takes the texture set.
READS = ("set_list", "layer_list", "project_recipe", "shader_get", "display_get")
# The reads that carry the committed revision, each checked against its own snapshot's and left
# out of the comparison across projects alone: `set_list`, `layer_list` (`typed_tools.cpp`) and
# `project_recipe` (`DumpRecipe`). `shader_get` and `display_get` carry none (`display.cpp`,
# `Shader` and `State`), so they are compared whole.
REVISIONED = ("set_list", "layer_list", "project_recipe")
# The `layer_list` params that hold uids, and the slot their nodes sit in (`layer_tree.cpp`).
UID_LISTS = (
    (("children",), "Substack"),
    (("content_effects",), "Content"),
    (("mask", "effects"), "Mask"),
)
# The second process: the public facade only (`src/python/bind_project.cpp`).
REBUILD = """\
import sys
from uzpainter import project
dump, resources, target = sys.argv[1:4]
project.rebuild_from_recipe(dump, resources)
project.save_as(target, project.ProjectSaveMode.Full)
result = {
    "file": project.absolute_file_path(),
    "revision": project.revision(),
    "dump": project.dump_recipe(),
}
"""
TIMEOUT = 1800  # seconds, for `export-bundle` and the rebuild


class RecipeFailed(RuntimeError):
    """A step failed: a call, a process, the bundle or a resource."""


class RecipeMismatch(Exception):
    """A state differs from the one it must equal."""


class RecipeRefused(Exception):
    """A step UzPainter refuses explicitly (paint-plane content, a release gap)."""

    def __init__(self, refusal: dict[str, Any]) -> None:
        super().__init__(refusal)
        self.refusal = refusal


@dataclass(frozen=True)
class StateRound:
    """What the state round leaves: its job and expectations, the sync's reply, the saved project,
    its reopened reads and revision, and the round's log."""

    job: NativeJob
    expected: Expected
    synced: dict[str, Any]
    project: Path
    reads: dict[str, Any]
    revision: int
    log: Round


@dataclass(frozen=True)
class Export:
    """An export's files by name, or its refusal."""

    files: dict[str, Path] | None
    refusal: dict[str, str] | None


@dataclass(frozen=True)
class RecipeRound:
    """The outcome (`pass`, `fail`, `export_refused` or `refused`), the report (None when a step
    refused before it), the step's refusal and each session's call log."""

    outcome: str
    report: dict[str, Any] | None
    refusal: dict[str, Any] | None
    logs: dict[str, Round]


class Recorder(Driver):
    """A driver that also keeps each call's arguments and reply."""

    def __init__(self, session: Mcp, log: Round) -> None:
        super().__init__(session, log)
        self.replies: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        reply = super().call(tool, arguments)
        self.replies.append((tool, arguments, reply))
        return reply

    def last(self, tool: str) -> tuple[dict[str, Any], dict[str, Any]]:
        for sent, arguments, reply in reversed(self.replies):
            if sent == tool and "error" not in reply:
                return arguments, reply
        raise RecipeFailed(f"the state round has no successful {tool}")


def session_of(painter: Path, work: Path, backend: str) -> Mcp:
    """A typed MCP session without `--allow-python`."""
    work.mkdir(parents=True, exist_ok=True)
    return Mcp(painter, work, "--gpu-backend", backend)


def run_process(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT,
        check=False,
    )


def result_of(driver: Driver, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """A call's result; any error fails the run."""
    reply = driver.call(tool, arguments)
    if "error" in reply or not isinstance(reply.get("result"), dict):
        raise RecipeFailed(f"{tool} failed: {reply.get('error')}")
    result: dict[str, Any] = reply["result"]
    return result


def state_round(painter: Path, work: Path, manifest: Path, backend: str = BACKEND) -> StateRound:
    """The Tunic current round with its state checks (`mcp_round.drive`, `TUNIC_CURRENT`), refused
    before UzPainter starts unless the job fits the scenario, as `mcp_round.run_round`."""
    scenario = tunic_state.TUNIC_CURRENT
    job = load_pipeline_job(manifest, wand.ASSETS3D)
    if not isinstance(job, NativeJob):
        raise RecipeFailed(f"the Tunic rebuild takes a native job, not {job.golden_id}")
    staged = stage_inputs(job, work / "assets")
    expected = mcp_round.expected_of(scenario, job, staged, wand.native_ocio_sha256(job))
    session = session_of(painter, work, backend)
    try:
        log = listed(session, "state")  # before the round's first call
        driver = Recorder(session, log)
        mcp_round.drive(driver, job, staged, work, scenario)
    finally:
        session.close()
    if log.outcome != "completed" and (log.outcome, (log.refusal or {}).get("tool")) != (
        "refused",
        "export",
    ):
        raise RecipeFailed(f"the state round ended {log.outcome}: {log.refusal}")
    saved, _ = driver.last("project_save_as")
    _, synced = driver.last("sync_stack")
    _, opened = driver.last("project_open")
    sync = synced["result"].get("returned", {}).get("sync")
    revision = opened["result"].get("revision")
    if not isinstance(sync, dict) or type(revision) is not int:
        raise RecipeFailed("the state round has no sync report or reopened revision")
    reads = {tool: driver.last(tool)[1]["result"] for tool in READS}
    return StateRound(job, expected, sync, Path(saved["path"]), reads, revision, log)


def observe(driver: Driver, st: StateRound, at: Any) -> dict[str, Any]:
    """The snapshot's reads at revision `at`, checked through `tunic_state` (handles found afresh,
    no earlier uid used) and the one set's mesh bindings as the state round's."""
    texture_set = str(st.job.create.args["texture_set"])
    reads = {
        tool: result_of(driver, tool, {"texture_set": texture_set} if tool == "layer_list" else {})
        for tool in READS
    }
    listing, dump = reads["layer_list"], reads["project_recipe"]
    found = {tool: reads[tool].get("revision") for tool in REVISIONED}
    if type(at) is not int or any(revision != at for revision in found.values()):
        raise RecipeMismatch(f"the reads are at revisions {found}, not the opened {at}")
    sets = reads["set_list"].get("texture_sets")
    wanted = st.reads["set_list"]["texture_sets"][0]["mesh_maps"]
    if (
        not isinstance(sets, list)
        or [entry.get("name") for entry in sets] != [texture_set]
        or sets[0].get("mesh_maps") != wanted
    ):
        raise RecipeMismatch(f"the texture sets {sets} do not bind exactly {wanted}")
    try:
        tunic_state.check_listing(st.expected, listing, st.synced, fresh_uids=False)
        tunic_state.check_recipe(st.expected, dump)
        tunic_state.check_shader(reads["shader_get"], reads["display_get"])
    except StateMismatch as error:
        raise RecipeMismatch(f"revision {at}: {error}") from error
    return reads


def opened_at(driver: Driver, project: Path) -> Any:
    return result_of(driver, "project_open", {"path": str(project), "wait": True}).get("revision")


def literal(first: dict[str, Any], second: dict[str, Any], what: str) -> None:
    changed = [tool for tool in first if first[tool] != second.get(tool)]
    if changed:
        raise RecipeMismatch(f"{what}: {changed} differ")


def export_once(driver: Driver, job: NativeJob, out: Path) -> Export:
    """The job's closing configuration, only its `exportPath` changed; its refusal kept."""
    config = {**job.config_export.config, "exportPath": str(out)}
    reply = driver.call("export", {"config": config})
    if "error" in reply:
        refusal = refusal_of("export", reply, NATIVE_REFUSABLE)
        if refusal is None:
            raise RecipeFailed(f"export failed: {reply['error']}")
        return Export(None, refusal)
    files: dict[str, Path] = {}
    for written in reply["result"]["files"]:
        path = Path(written["path"])
        if path.name in files:
            raise RecipeFailed(f"the export wrote {path.name} twice")
        files[path.name] = path
    return Export(files, None)


def listed(session: Mcp, where: str) -> Round:
    """A session's log from its real `tools/list`; refused before any project call when
    `run_python` is listed."""
    tools = {tool["name"] for tool in session.request("tools/list", {})["tools"]}
    log = Round(len(tools), "run_python" in tools)
    if log.run_python_listed:
        raise RecipeFailed(f"the {where} session lists run_python: refused before any project call")
    return log


def original_session(
    painter: Path, work: Path, st: StateRound, backend: str = BACKEND
) -> tuple[dict[str, Any], Export, Round]:
    """The saved project reopened in a fresh session: its reads, its export and the call log."""
    where = "original"
    session = session_of(painter, work, backend)
    try:
        log = listed(session, where)
        driver = Driver(session, log)
        at = opened_at(driver, st.project)
        if at != st.revision:
            raise RecipeMismatch(f"the saved project opens at revision {at}, not {st.revision}")
        reads = observe(driver, st, at)
        literal(st.reads, reads, "the saved project reopened afresh")
        exported = export_once(driver, st.job, work / "out" / "export")
        result_of(driver, "project_close", {})
    finally:
        session.close()
    return reads, exported, log


def bundle_file(bundle: Path, name: Any) -> Path:
    """The bundle's file `name`, refused before anything is read unless it is a plain relative
    path that stays inside `bundle` once resolved (links followed): never absolute, rooted,
    drive-relative or `..`, and never a file outside the bundle, whatever its hash."""
    windows, posix = PureWindowsPath(str(name)), PurePosixPath(str(name))
    if (
        not isinstance(name, str)
        or not name
        or windows.drive
        or windows.root
        or posix.is_absolute()
        or ".." in windows.parts
        or ".." in posix.parts
    ):
        raise RecipeFailed(f"the bundle's entry {name!r} is not a path inside the bundle")
    root = bundle.resolve()
    path = (bundle / name).resolve()
    if path == root or not path.is_relative_to(root):
        raise RecipeFailed(f"the bundle's entry {name!r} leaves the bundle: {path}")
    return path


def bundle_resources(painter: Path, project: Path, dump: dict[str, Any], work: Path) -> Path:
    """The dump's resources from the project's bundle alone, verified, as `<sha256>.<ext>`."""
    bundle = work / "bundle"
    done = run_process([str(painter), "export-bundle", str(project), str(bundle)])
    if done.returncode != 0:
        raise RecipeFailed(f"export-bundle failed ({done.returncode}): {done.stdout}{done.stderr}")
    index = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    if index.get("revision") != dump["revision"]:
        raise RecipeFailed(
            f"the bundle is revision {index.get('revision')}, not {dump['revision']}"
        )
    if index.get("planes"):
        raise RecipeRefused(
            {"step": "export-bundle", "type": "paint_planes", "planes": len(index["planes"])}
        )
    entries: dict[str, tuple[dict[str, Any], Path]] = {}
    for entry in index["resources"]:  # every file named, checked before any is read
        if entry["sha256"] in entries:
            raise RecipeFailed(f"the bundle lists {entry['sha256']} twice")
        entries[entry["sha256"]] = (entry, bundle_file(bundle, entry.get("file")))
    sizes = dump["recipe"]["resources"]
    verified: list[tuple[str, Path, bytes]] = []
    for sha256 in dump["resource_hashes"]:
        if sha256 not in entries or not entries[sha256][1].is_file():
            raise RecipeFailed(
                f"the bundle is missing the resource {sha256}: never filled from the inputs"
            )
        entry, source = entries[sha256]
        data = source.read_bytes()
        if sha256_bytes(data) != sha256 or not len(data) == entry["bytes"] == sizes[sha256]["size"]:
            raise RecipeFailed(f"the bundle's resource {entry['file']} is corrupt: not {sha256}")
        verified.append((sha256, source, data))
    folder = work / "resources"
    folder.mkdir(parents=True)
    for sha256, source, data in verified:
        (folder / f"{sha256}{source.suffix}").write_bytes(data)
    return folder


def rebuild(
    painter: Path, dump: Path, resources: Path, target: Path, backend: str = BACKEND
) -> dict[str, Any]:
    """`rebuild_from_recipe(dump, resources)` and `save_as(target)` in a separate `run` process:
    the saved file, its revision and its dump."""
    target.parent.mkdir(parents=True, exist_ok=True)
    script = target.parent / "rebuild.py"
    script.write_text(REBUILD, encoding="utf-8")
    arguments = [str(dump), str(resources), str(target)]
    done = run_process(
        [str(painter), "run", str(script), "--gpu-backend", backend, "--", *arguments]
    )
    lines = [line for line in done.stdout.splitlines() if line.startswith(JSON_PREFIX)]
    if not lines:
        raise RecipeFailed(f"the rebuild printed no report ({done.returncode}): {done.stderr}")
    printed = json.loads(lines[-1][len(JSON_PREFIX) :])
    error = printed.get("error") or {}
    if printed.get("status") != "ok":
        if error.get("type") == "NotYetSupported":
            message = str(error.get("message"))
            raise RecipeRefused(
                {"step": "rebuild_from_recipe", "type": "NotYetSupported", "message": message}
            )
        raise RecipeFailed(f"the rebuild failed: {error}")
    made = printed.get("result")
    if (
        done.returncode != 0
        or not isinstance(made, dict)
        or not isinstance(made.get("dump"), dict)
        or Path(str(made.get("file"))).resolve() != target.resolve()
    ):
        raise RecipeFailed(f"the rebuild did not save {target}: {printed}")
    return made


def rebuilt_session(
    painter: Path,
    work: Path,
    target: Path,
    st: StateRound,
    made: dict[str, Any],
    backend: str = BACKEND,
) -> tuple[dict[str, Any], Export, Round]:
    """The rebuilt project in a fresh session, checked, saved, closed, reopened and checked
    again literally, then exported: its reads, its export and the call log."""
    where = "rebuilt"
    session = session_of(painter, work, backend)
    try:
        log = listed(session, where)
        driver = Driver(session, log)
        at = opened_at(driver, target)
        if at != made["revision"]:
            raise RecipeMismatch(f"the rebuilt project opens at {at}, not {made['revision']}")
        first = observe(driver, st, at)
        if first["project_recipe"] != made["dump"]:
            raise RecipeMismatch("the rebuilt project's dump is not the one the rebuild saved")
        result_of(driver, "project_save", {"mode": "full"})
        result_of(driver, "project_close", {})
        again = opened_at(driver, target)
        if again != at:
            raise RecipeMismatch(f"the rebuilt project reopens at {again}, not {at}")
        literal(first, observe(driver, st, again), "the rebuilt project after its save and reopen")
        exported = export_once(driver, st.job, work / "out" / "export")
        result_of(driver, "project_close", {})
    finally:
        session.close()
    return first, exported, log


def canonical_listing(listing: dict[str, Any]) -> dict[str, Any]:
    """`listing` with each proven uid reference replaced by its node's handle in the freshly
    resolved hierarchy (the module's docstring); every other field literal."""
    nodes = listing.get("nodes")
    if not isinstance(nodes, list) or not all(isinstance(n, dict) for n in nodes):
        raise RecipeMismatch("layer_list returned no node list")
    by_uid: dict[int, dict[str, Any]] = {}
    for node in nodes:
        if type(node.get("uid")) is not int or node["uid"] in by_uid:
            raise RecipeMismatch(f"layer_list holds a node without a single uid: {node.get('uid')}")
        by_uid[node["uid"]] = node
    if len({(n.get("texture_set"), n.get("stack")) for n in nodes}) != 1:
        raise RecipeMismatch("layer_list holds no single texture set and stack")
    handles: dict[int, str] = {}

    def assign(node: dict[str, Any], handle: str) -> None:
        if node["uid"] in handles:
            raise RecipeMismatch(f"{handle}: node {node['uid']} is reached twice")
        handles[node["uid"]] = handle
        for keys, slot in UID_LISTS:
            uids = tunic_state.field(node.get("params"), *keys)
            if uids is None:
                continue
            if not isinstance(uids, list):
                raise RecipeMismatch(f"{handle}: {'.'.join(keys)} is not a uid list")
            for position, uid in enumerate(uids):
                child = by_uid.get(uid) if type(uid) is int else None
                where = f"{handle}/{slot}[{position}]"
                if child is None or (
                    child.get("parent"),
                    child.get("slot"),
                    child.get("index"),
                ) != (
                    node["uid"],
                    slot,
                    position,
                ):
                    raise RecipeMismatch(f"{where}: {uid} is not the node at that place")
                assign(child, where)

    roots = sorted(
        (n for n in nodes if n.get("parent") is None),
        key=lambda n: n["index"] if type(n.get("index")) is int else -1,
    )
    if [(r.get("slot"), r.get("index")) for r in roots] != [
        ("Substack", i) for i in range(len(roots))
    ]:
        raise RecipeMismatch("the roots are not the stack's Substack list in order")
    for root in roots:
        assign(root, f"Substack[{root['index']}]")
    if len(handles) != len(nodes):
        raise RecipeMismatch(f"{len(nodes) - len(handles)} nodes are not reached from the roots")

    def rewrite(node: dict[str, Any]) -> dict[str, Any]:
        out = copy.deepcopy(node)
        out["uid"] = handles[node["uid"]]
        out["parent"] = None if node["parent"] is None else handles[node["parent"]]
        out["texture_set"], out["stack"] = "<texture_set>", "<stack>"
        for keys, _ in UID_LISTS:
            holder = tunic_state.field(out.get("params"), *keys[:-1])
            if isinstance(holder, dict) and isinstance(holder.get(keys[-1]), list):
                holder[keys[-1]] = [handles[uid] for uid in holder[keys[-1]]]
        return out

    kept = {key: value for key, value in listing.items() if key not in ("revision", "nodes")}
    return {**kept, "nodes": [rewrite(node) for node in nodes]}


def differing(first: dict[str, Any], second: dict[str, Any]) -> list[str]:
    """The keys present on one side only, or whose values differ: a missing key is never a
    null one."""
    keys = first.keys() | second.keys()
    return sorted(k for k in keys if k not in first or k not in second or first[k] != second[k])


def compare_projects(original: dict[str, Any], rebuilt: dict[str, Any]) -> None:
    """The rebuilt project's reads are the original's (the module's docstring); `RecipeMismatch`
    names every point that differs."""
    problems: list[str] = []
    for tool in ("set_list", "shader_get", "display_get"):
        first, second = (
            {key: value for key, value in reads[tool].items() if key != "revision"}
            if tool in REVISIONED
            else reads[tool]
            for reads in (original, rebuilt)
        )
        if differing(first, second):
            problems.append(f"{tool} differs at {differing(first, second)}")
    first, second = (
        {key: value for key, value in reads["project_recipe"].items() if key != "revision"}
        for reads in (original, rebuilt)
    )
    for key in differing(first, second):
        a, b = first.get(key), second.get(key)
        if (key in first) != (key in second):
            problems.append(f"the dumps' {key} is present on one side only")
        elif key == "rebuild" and isinstance(a, dict) and isinstance(b, dict):
            problems.append(f"the dumps' rebuild block differs at {differing(a, b)}")
        else:
            problems.append(f"the dumps' {key} differs")
    for name, reads in (("original", original), ("rebuilt", rebuilt)):
        dump = reads["project_recipe"]
        if (
            tunic_state.field(dump, "rebuild", "/display", "shader", "parameters", "double_sided")
            is not True
        ):
            problems.append(f"the {name} dump does not hold double_sided true in /display")
    if canonical_listing(original["layer_list"]) != canonical_listing(rebuilt["layer_list"]):
        problems.append("layer_list differs with its uids normalised through the hierarchy")
    if problems:
        raise RecipeMismatch("; ".join(problems))


def side(dump: dict[str, Any], exported: Export) -> Side:
    if exported.files is None:
        refusal = exported.refusal or {}
        return Side(dump, None, f"{refusal.get('error_code')}:{refusal.get('type', '')}")
    return Side(dump, exported.files)


def run_tunic_recipe(
    painter: Path, work: Path, manifest: Path, backend: str = BACKEND
) -> RecipeRound:
    """The dump-and-rebuild of the Tunic current round (the module's docstring) in `work`, a
    fresh directory; nothing is written elsewhere."""
    st = state_round(painter, work / "state", manifest, backend)
    logs = {"state": st.log}
    original, first, logs["original"] = original_session(painter, work / "original", st, backend)
    dump = work / "original" / "recipe" / "dump.json"
    dump.parent.mkdir(parents=True)  # never left to a session or an export to create
    dump.write_text(json.dumps(original["project_recipe"]), encoding="utf-8")
    target = work / "rebuild" / "tunic-rebuilt.uzp"
    try:
        resources = bundle_resources(painter, st.project, original["project_recipe"], work)
        made = rebuild(painter, dump, resources, target, backend)
    except RecipeRefused as refused:
        return RecipeRound("refused", None, refused.refusal, logs)
    rebuilt, second, logs["rebuilt"] = rebuilt_session(
        painter, work / "rebuilt", target, st, made, backend
    )
    compare_projects(original, rebuilt)
    document = report(
        st.job.golden_id,
        sha256_of(manifest),
        sha256_of(painter),
        side(original["project_recipe"], first),
        side(rebuilt["project_recipe"], second),
    )
    return RecipeRound(document["equality"]["outcome"], document, None, logs)
