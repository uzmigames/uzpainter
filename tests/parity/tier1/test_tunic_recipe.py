"""The Tunic current round's dump-and-rebuild (`tests/parity/tier1/tunic_recipe.py`): the state
round, the saved project reopened afresh, its bundle verified, the rebuild in a separate `run`
process, the rebuilt project reopened and compared. Nothing here starts UzPainter: the state round
runs against the state front's fake (`test_tunic_mcp_state.StateSession`) over the native
stand-in, the later sessions against a fake that serves the saved projects, and `export-bundle` and
`run` against a fake process whose rebuild reallocates every uid, as `RebuildManifest` does. The
replies have UzPainter's shapes (`src/supervisor/typed_tools.cpp`, `worker.cpp`)."""

from __future__ import annotations

import copy
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.adapters.assets3d import wand as wand_module
from tests.parity.recorder.test_script_run import NATIVE_STACK, TUNIC_SET, make_assets
from tests.parity.recorder.test_script_run import native_manifest as make_native_manifest
from tests.parity.tier1 import tunic_recipe, tunic_state
from tests.parity.tier1.test_tunic_mcp_state import StateSession, load_job, scenario_of
from tools.parity.recorder import script_run
from tools.parity.recorder.job import canonical_json, sha256_file
from tools.parity.store.store import STORE_ENV

READS = list(tunic_recipe.READS)
FRESH_TOOLS = ["project_open", "project_close", "project_save", "export", *READS]
REVISION = 9  # the rebuilt project's revision
SHIFT = 1000  # the rebuild's new uids: every one moved


@pytest.fixture(autouse=True)
def no_private_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "no-store"))


@pytest.fixture
def native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = make_assets(tmp_path / "assets3d")
    monkeypatch.setattr(wand_module, "ASSETS3D", root)
    return make_native_manifest(root, tmp_path / "repo")


class World:
    """The fake UzPainter's projects by path, its resource bytes by SHA-256 and the authored
    faults."""

    def __init__(self, job: script_run.NativeJob, blobs: dict[str, tuple[bytes, str]]) -> None:
        self.job = job
        self.blobs = blobs
        self.projects: dict[str, dict[str, Any]] = {}
        self.state: RecipeStateSession | None = None
        self.saved = ""
        self.processes: list[list[str]] = []
        self.sessions: list[Any] = []
        self.bundle: dict[str, Any] = {}  # `missing`, `corrupt`, `planes`
        self.rebuild_error = ""
        self.rebuilt_fault: Callable[[dict[str, Any]], None] | None = None
        self.reopen_fault: Callable[[dict[str, Any]], None] | None = None
        self.refuse: set[str] = set()  # the sides whose export refuses
        self.python: set[str] = set()  # the sessions whose tools/list names run_python

    def entry(self, path: str) -> dict[str, Any]:
        """A saved project's replies; the state round's project as its session last saw it."""
        if path not in self.projects:
            assert self.state is not None and path == self.saved, path
            self.projects[path] = {
                tool: self.state.call(tool, arguments(tool))["result"] for tool in READS
            }
        return self.projects[path]

    def resources(self) -> list[str]:
        create = self.job.create
        found = {create.mesh.sha256, create.normal.sha256, *(m.sha256 for m in self.job.sync.masks)}
        return sorted(found)


def arguments(tool: str) -> dict[str, Any]:
    return {"texture_set": TUNIC_SET} if tool == "layer_list" else {}


class RecipeStateSession(StateSession):
    """The state front's fake, with each node's `index` its place in its owner's list and the
    full dump (versions, resources and the `/display` block), as UzPainter lists them."""

    def __init__(self, world: World) -> None:
        super().__init__(world.job)
        self.world = world

    def sync(self) -> dict[str, Any]:
        reply = super().sync()
        by_uid = {node["uid"]: node for node in self.nodes}
        for node in self.nodes:
            params = node["params"]
            mask = params.get("mask")
            for uids in (params.get("children") or [], mask["effects"] if mask else []):
                for index, uid in enumerate(uids):
                    by_uid[uid]["index"] = index
            if node["parent"] is None:  # the titled group above the default layer
                node["index"] = 0 if node["name"] == NATIVE_STACK["title"] else 1
        return reply

    def recipe(self) -> dict[str, Any]:
        dump = super().recipe()
        hashes = self.world.resources()
        dump["recipe"]["resources"] = {
            h: {"mime": "application/octet-stream", "size": len(self.world.blobs[h][0])}
            for h in hashes
        }
        dump["rebuild"]["/display"] = {
            "shader": {"id": "open-pbr", "parameters": {"double_sided": self.double_sided}}
        }
        return {
            "schema": "uzpainter/recipe/1",
            "evaluator_profile": "e1",
            "compat_profile": "c1",
            "app_version": "0.0.0",
            "resource_hashes": hashes,
            **dump,
        }

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        listed = super().request(method, params)
        if "state" in self.world.python:
            listed["tools"].append({"name": "run_python"})
        return listed

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool == "project_save_as":
            self.world.saved = arguments["path"]
        reply = super().call(tool, arguments)
        if tool == "set_list":  # UzPainter's set_list names its committed revision
            reply["result"] = {"revision": self.revision, **reply["result"]}
        return reply


class OpenSession:
    """A fresh session on a saved project: `project_open`, the reads, `project_save`,
    `project_close` and the export, which writes the bytes the project's content gives."""

    def __init__(self, world: World, name: str) -> None:
        self.world, self.name = world, name
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.project: dict[str, Any] | None = None
        self.opens = 0
        self.requests: list[str] = []

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert method == "tools/list" and not self.calls, (method, self.calls)
        self.requests.append(method)
        names = [*FRESH_TOOLS, *(["run_python"] if self.name in self.world.python else [])]
        return {"tools": [{"name": name} for name in names]}

    def close(self) -> None:
        pass

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, arguments))
        if tool == "project_open":
            self.opens += 1
            self.project = self.world.entry(arguments["path"])
            if self.opens == 2 and self.world.reopen_fault is not None:
                self.world.reopen_fault(self.project)
            revision = self.project["project_recipe"]["revision"]
            return {"result": {"path": arguments["path"], "revision": revision}}
        assert self.project is not None, tool
        if tool in READS:
            return {"result": copy.deepcopy(self.project[tool])}
        if tool == "project_save":
            return {"result": {"current": "rev-1", "named": None, "previous": None}}
        if tool == "project_close":
            self.project = None
            return {"result": {}}
        assert tool == "export", tool
        if self.name in self.world.refuse:
            return {"error": {"code": "capability_gap", "details": {"type": "NotYetSupported"}}}
        out = Path(arguments["config"]["exportPath"])
        out.mkdir(parents=True)
        path = out / f"{TUNIC_SET}_Height.exr"
        path.write_bytes(content(self.project))
        return {"result": {"files": [{"path": str(path), "root_path": TUNIC_SET}]}}


def content(project: dict[str, Any]) -> bytes:
    """What an export of `project` writes: its digest, display and bindings in node order."""
    nodes = project["layer_list"]["nodes"]
    bound = [tunic_state.field(b, "resource", "sha256") for b in tunic_state.bitmaps(nodes)]
    dump = project["project_recipe"]
    return canonical_json({"digest": dump["digest"], "display": dump["rebuild"], "bound": bound})


def renumbered(project: dict[str, Any]) -> dict[str, Any]:
    """`project` with every uid moved and new texture set and stack ids, as a rebuild gives."""
    moved = copy.deepcopy(project)
    for node in moved["layer_list"]["nodes"]:
        node["uid"] += SHIFT
        node["parent"] = None if node["parent"] is None else node["parent"] + SHIFT
        node["texture_set"], node["stack"] = 7, 8
        params = node["params"]
        if "children" in params:
            params["children"] = [uid + SHIFT for uid in params["children"]]
        if isinstance(params.get("mask"), dict):
            params["mask"]["effects"] = [uid + SHIFT for uid in params["mask"]["effects"]]
        if "content_effects" in params:
            params["content_effects"] = [uid + SHIFT for uid in params["content_effects"]]
    return moved


def process(world: World, args: list[str]) -> subprocess.CompletedProcess[str]:
    """`export-bundle` and `run` of the fake UzPainter."""
    world.processes.append(args)
    if args[1] == "export-bundle":
        project, bundle = world.entry(args[2]), Path(args[3])
        resources = []
        for sha256 in world.resources():
            if sha256 == world.bundle.get("missing"):
                continue
            data, suffix = world.blobs[sha256]
            file = f"res/{sha256}{suffix}"
            written = b"corrupt" + data if sha256 == world.bundle.get("corrupt") else data
            (bundle / "res").mkdir(parents=True, exist_ok=True)
            (bundle / file).write_bytes(written)
            if sha256 == world.bundle.get("external"):  # the right bytes, outside the bundle
                outside = bundle.parent / "outside" / f"{sha256}{suffix}"
                outside.parent.mkdir()
                outside.write_bytes(data)
                (bundle / file).unlink()
                file = (
                    str(outside)
                    if world.bundle["how"] == "absolute"
                    else f"../outside/{outside.name}"
                )
            resources.append({"sha256": sha256, "file": file, "mime": "x", "bytes": len(written)})
        index = {
            "revision": project["project_recipe"]["revision"],
            "resources": resources,
            "planes": world.bundle.get("planes", []),
        }
        (bundle / "bundle.json").write_text(json.dumps(index), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")
    assert args[1] == "run" and args[3:6] == ["--gpu-backend", "vulkan", "--"], args
    dump_file, folder, target = (Path(a) for a in args[6:])
    report: dict[str, Any]
    if world.rebuild_error:
        error = {"type": world.rebuild_error, "message": "refused", "traceback": ""}
        report = {"status": "failed", "result": None, "error": error}
        return subprocess.CompletedProcess(args, 1, f"UZP_JSON:{json.dumps(report)}\n", "")
    dump = json.loads(dump_file.read_text(encoding="utf-8"))
    for sha256 in dump["resource_hashes"]:  # the facade reads `<sha256>`, any extension
        (found,) = folder.glob(f"{sha256}.*")
        assert sha256_file(found) == sha256
    original = next(p for p in world.projects.values() if p["project_recipe"] == dump)
    rebuilt = renumbered(original)
    rebuilt["layer_list"]["revision"] = rebuilt["set_list"]["revision"] = REVISION
    rebuilt["project_recipe"] = {**dump, "revision": REVISION}
    if world.rebuilt_fault is not None:
        world.rebuilt_fault(rebuilt)
    world.projects[str(target)] = rebuilt
    result = {"file": str(target), "revision": REVISION, "dump": rebuilt["project_recipe"]}
    report = {"status": "ok", "result": result}
    return subprocess.CompletedProcess(args, 0, f"UZP_JSON:{json.dumps(report)}\n", "")


@pytest.fixture
def world(native: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """The fake UzPainter behind `tunic_recipe`: the state session first, then fresh ones."""
    job = load_job(native, tmp_path)
    staged = script_run.stage_inputs(job, tmp_path / "store")
    blobs = {sha256_file(p): (p.read_bytes(), p.suffix) for p in staged.values()}
    made = World(job, blobs)
    monkeypatch.setattr(tunic_state, "TUNIC_CURRENT", scenario_of(job))

    def loader(path: Path, assets_root: Path) -> Any:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        return script_run.pipeline_job_from_manifest(
            manifest, assets_root, repo_root=tmp_path / "repo"
        )

    def session(painter: Path, work: Path, backend: str) -> Any:
        assert backend == "vulkan"
        if made.state is None:
            made.state = RecipeStateSession(made)
            made.sessions.append(made.state)
        else:
            made.sessions.append(OpenSession(made, ["original", "rebuilt"][len(made.sessions) - 1]))
        return made.sessions[-1]

    monkeypatch.setattr(tunic_recipe, "load_pipeline_job", loader)
    monkeypatch.setattr(tunic_recipe, "session_of", session)
    monkeypatch.setattr(tunic_recipe, "run_process", lambda args: process(made, args))
    return made


def run(world: World, tmp_path: Path) -> tunic_recipe.RecipeRound:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(world.job.manifest), encoding="utf-8")
    painter = tmp_path / "UzPainter.exe"
    painter.write_bytes(b"fake")
    return tunic_recipe.run_tunic_recipe(painter, tmp_path / "work", manifest)


def tools(session: Any) -> list[str]:
    return [tool for tool, _ in session.calls]


EXPORT_THEN_CLOSE = ["export", "project_close"]


def test_the_rebuilt_tunic_equals_the_original_across_reallocated_uids(
    world: World, tmp_path: Path
) -> None:
    """A legitimate uid remap is accepted: every rebuilt uid and the set and stack ids are new,
    and the rebuild still passes: dumps, state, bindings and exported bytes equal."""
    outcome = run(world, tmp_path)
    assert outcome.outcome == "pass" and outcome.refusal is None, outcome.report
    assert outcome.report is not None
    assert outcome.report["equality"]["files"] == "identical"
    original, rebuilt = world.sessions[1:]
    assert tools(original) == ["project_open", *READS, *EXPORT_THEN_CLOSE]
    reopened = ["project_save", "project_close", "project_open", *READS]
    assert tools(rebuilt) == ["project_open", *READS, *reopened, *EXPORT_THEN_CLOSE]
    assert "run_python" not in tools(world.sessions[0]) + tools(original) + tools(rebuilt)
    assert original.requests == rebuilt.requests == ["tools/list"]  # before any project call
    logs = outcome.logs
    assert [logs[n].run_python_listed for n in ("state", "original", "rebuilt")] == [False] * 3
    assert logs["original"].tools_listed == logs["rebuilt"].tools_listed == len(FRESH_TOOLS)
    work = tmp_path / "work"
    target = work / "rebuild" / "tunic-rebuilt.uzp"
    assert [args[1] for args in world.processes] == ["export-bundle", "run"]
    assert world.processes[0][2:] == [world.saved, str(work / "bundle")]
    assert world.processes[1][6:] == [
        str(work / "original" / "recipe" / "dump.json"),
        str(work / "resources"),
        str(target),
    ]
    suffixes = {h: world.blobs[h][1] for h in world.resources()}
    assert sorted(p.name for p in (work / "resources").iterdir()) == sorted(
        f"{h}{s}" for h, s in suffixes.items()
    )
    # The rebuild's dump is the full one read through `project_recipe`, double_sided included.
    dump = json.loads((work / "original" / "recipe" / "dump.json").read_text(encoding="utf-8"))
    assert dump == world.entry(world.saved)["project_recipe"]
    assert dump["rebuild"]["/display"]["shader"]["parameters"]["double_sided"] is True
    revisions = [world.projects[p]["set_list"]["revision"] for p in (world.saved, str(target))]
    assert revisions[0] != revisions[1] == REVISION  # compared across projects without it
    uids = [
        {n["uid"] for n in world.projects[p]["layer_list"]["nodes"]}
        for p in (world.saved, str(target))
    ]
    assert uids[0].isdisjoint(uids[1])


def test_a_state_session_that_lists_run_python_is_refused_before_any_call(
    world: World, tmp_path: Path
) -> None:
    world.python = {"state"}
    with pytest.raises(tunic_recipe.RecipeFailed, match="the state session lists run_python"):
        run(world, tmp_path)
    assert world.state is not None and world.state.calls == []
    assert len(world.sessions) == 1 and world.processes == []


@pytest.mark.parametrize("name", ["original", "rebuilt"])
def test_a_fresh_session_that_lists_run_python_is_refused_before_any_project_call(
    world: World, tmp_path: Path, name: str
) -> None:
    world.python = {name}
    with pytest.raises(tunic_recipe.RecipeFailed, match=f"the {name} session lists run_python"):
        run(world, tmp_path)
    session = world.sessions[-1]
    assert session.name == name and session.requests == ["tools/list"] and session.calls == []
    expected = ["export-bundle", "run"] if name == "rebuilt" else []
    assert [args[1] for args in world.processes] == expected


def test_a_missing_bundle_resource_fails_and_is_never_filled_from_the_inputs(
    world: World, tmp_path: Path
) -> None:
    lost = world.job.sync.masks[0].sha256
    world.bundle["missing"] = lost
    with pytest.raises(tunic_recipe.RecipeFailed, match=f"missing the resource {lost}"):
        run(world, tmp_path)
    assert [args[1] for args in world.processes] == ["export-bundle"]  # no rebuild
    assert not (tmp_path / "work" / "resources").exists()


def test_a_corrupt_bundle_resource_fails_before_the_rebuild(world: World, tmp_path: Path) -> None:
    world.bundle["corrupt"] = world.job.create.mesh.sha256
    with pytest.raises(tunic_recipe.RecipeFailed, match="is corrupt"):
        run(world, tmp_path)
    assert [args[1] for args in world.processes] == ["export-bundle"]
    assert not (tmp_path / "work" / "resources").exists()


@pytest.mark.parametrize("how", ["absolute", "escaping"])
def test_a_bundle_entry_outside_the_bundle_fails_even_with_the_right_hash(
    world: World, tmp_path: Path, how: str
) -> None:
    """An absolute or `../` entry whose file has the expected bytes is refused before it is read:
    only the bundle's own files are resources, and the inputs never fill one."""
    world.bundle.update(external=world.job.create.mesh.sha256, how=how)
    with pytest.raises(tunic_recipe.RecipeFailed, match="is not a path inside the bundle"):
        run(world, tmp_path)
    assert [args[1] for args in world.processes] == ["export-bundle"]  # no rebuild
    assert not (tmp_path / "work" / "resources").exists()


@pytest.mark.parametrize(
    "name", ["C:res/a.png", "\\res\\a.png", "/res/a.png", "res/../../a.png", "", 7]
)
def test_a_rooted_drive_relative_or_escaping_entry_is_refused(tmp_path: Path, name: Any) -> None:
    with pytest.raises(tunic_recipe.RecipeFailed, match="is not a path inside the bundle"):
        tunic_recipe.bundle_file(tmp_path / "bundle", name)
    inside = tunic_recipe.bundle_file(tmp_path / "bundle", "res/a.png")
    assert inside == (tmp_path / "bundle" / "res" / "a.png").resolve()


@pytest.mark.parametrize(
    ("where", "expected"),
    [
        ((), "the dumps' extra is present on one side only"),
        (("rebuild",), "the dumps' rebuild block differs at ['extra']"),
    ],
)
def test_a_key_missing_on_one_side_is_not_a_null_on_the_other(
    world: World, tmp_path: Path, where: tuple[str, ...], expected: str
) -> None:
    run(world, tmp_path)
    first = world.projects[world.saved]
    second = copy.deepcopy(first)
    holder = second["project_recipe"]
    for key in where:
        holder = holder[key]
    holder["extra"] = None  # absent from the original's dump
    with pytest.raises(tunic_recipe.RecipeMismatch) as raised:
        tunic_recipe.compare_projects(first, second)
    assert str(raised.value) == expected
    with pytest.raises(tunic_recipe.RecipeMismatch):
        tunic_recipe.compare_projects(second, first)


def lose_double_sided(project: dict[str, Any]) -> None:
    project["project_recipe"]["rebuild"]["/display"]["shader"]["parameters"]["double_sided"] = False
    project["shader_get"]["parameters"]["double_sided"] = False
    project["display_get"] = {"parity": True, "shader": copy.deepcopy(project["shader_get"])}


def test_double_sided_lost_with_the_digest_unchanged_is_a_mismatch(
    world: World, tmp_path: Path
) -> None:
    world.rebuilt_fault = lose_double_sided
    with pytest.raises(tunic_recipe.RecipeMismatch, match="double_sided"):
        run(world, tmp_path)


def test_the_comparison_names_double_sided_lost_in_the_rebuild_block_alone(
    world: World, tmp_path: Path
) -> None:
    """The rebuild block lies outside the digest: an equal digest proves nothing about it."""
    run(world, tmp_path)
    first = world.projects[world.saved]
    second = copy.deepcopy(first)
    second["project_recipe"]["rebuild"]["/display"]["shader"]["parameters"]["double_sided"] = False
    assert second["project_recipe"]["digest"] == first["project_recipe"]["digest"]
    with pytest.raises(tunic_recipe.RecipeMismatch) as raised:
        tunic_recipe.compare_projects(first, second)
    assert "rebuild block differs at ['/display']" in str(raised.value)
    assert "rebuilt dump does not hold double_sided true" in str(raised.value)


def swap_two_bindings(project: dict[str, Any]) -> None:
    sources = [
        n["params"]["fill"]["source"] for n in project["layer_list"]["nodes"] if n["slot"] == "Mask"
    ]
    first, second = next((a, b) for a in sources for b in sources if a["resource"] != b["resource"])
    first["resource"], second["resource"] = second["resource"], first["resource"]


def test_a_swapped_binding_in_the_rebuilt_project_is_a_mismatch(
    world: World, tmp_path: Path
) -> None:
    world.rebuilt_fault = swap_two_bindings
    with pytest.raises(tunic_recipe.RecipeMismatch, match="revision 9"):
        run(world, tmp_path)


def test_the_comparison_refuses_a_swapped_binding_even_where_the_state_checks_pass(
    world: World, tmp_path: Path
) -> None:
    run(world, tmp_path)
    first = world.projects[world.saved]
    second = renumbered(first)
    swap_two_bindings(second)
    with pytest.raises(tunic_recipe.RecipeMismatch, match="layer_list differs"):
        tunic_recipe.compare_projects(first, second)
    tunic_recipe.compare_projects(first, renumbered(first))  # the remap alone is accepted


def test_a_remap_that_breaks_the_hierarchy_is_refused(world: World, tmp_path: Path) -> None:
    run(world, tmp_path)
    listing = world.projects[world.saved]["layer_list"]
    reordered = copy.deepcopy(listing)
    group = next(n for n in reordered["nodes"] if len(n["params"].get("children") or []) > 1)
    group["params"]["children"].reverse()  # the children's `index` no longer matches
    with pytest.raises(tunic_recipe.RecipeMismatch, match="is not the node at that place"):
        tunic_recipe.canonical_listing(reordered)
    orphan = copy.deepcopy(listing)
    child = next(n for n in orphan["nodes"] if n["parent"] is not None)
    child["parent"] = None
    with pytest.raises(tunic_recipe.RecipeMismatch):
        tunic_recipe.canonical_listing(orphan)
    stray = copy.deepcopy(listing)
    stray["nodes"][0]["params"]["anchor"] = stray["nodes"][1]["uid"]  # not a proven reference
    moved = renumbered({"layer_list": stray})["layer_list"]
    moved["nodes"][0]["params"]["anchor"] += SHIFT  # a rebuild moves it with its node
    assert tunic_recipe.canonical_listing(moved) != tunic_recipe.canonical_listing(stray)


def test_exports_refused_on_both_sides_are_never_counted_as_equal(
    world: World, tmp_path: Path
) -> None:
    world.refuse = {"original", "rebuilt"}
    outcome = run(world, tmp_path)
    assert outcome.outcome == "export_refused" and outcome.report is not None
    equality = outcome.report["equality"]
    assert equality["files"] == "not_exported" and equality["outcome"] != "pass"
    assert outcome.report["rebuilt"]["export"] == {
        "status": "refused",
        "refusal": "capability_gap:NotYetSupported",
    }


def test_an_export_refused_on_one_side_fails(world: World, tmp_path: Path) -> None:
    world.refuse = {"rebuilt"}
    outcome = run(world, tmp_path)
    assert outcome.outcome == "fail" and outcome.report is not None
    assert outcome.report["equality"]["files"] == "not_exported"


def test_paint_plane_content_stays_refused_and_nothing_is_deleted(
    world: World, tmp_path: Path
) -> None:
    world.bundle["planes"] = [{"plane_id": 1, "file": "planes/1.png"}]
    outcome = run(world, tmp_path)
    assert outcome.outcome == "refused" and outcome.report is None
    assert outcome.refusal == {"step": "export-bundle", "type": "paint_planes", "planes": 1}
    assert [args[1] for args in world.processes] == ["export-bundle"]
    assert (tmp_path / "work" / "bundle" / "bundle.json").is_file()
    assert (tmp_path / "work" / "original" / "out" / "export").is_dir()  # nothing is deleted


def test_a_rebuild_refusal_stays_explicit_and_another_error_fails(
    world: World, tmp_path: Path
) -> None:
    world.rebuild_error = "NotYetSupported"
    outcome = run(world, tmp_path)
    assert outcome.outcome == "refused" and outcome.report is None
    assert outcome.refusal is not None and outcome.refusal["step"] == "rebuild_from_recipe"
    assert len(world.sessions) == 2  # the rebuilt project is never opened


def test_a_rebuild_error_fails(world: World, tmp_path: Path) -> None:
    world.rebuild_error = "ProjectError"
    with pytest.raises(tunic_recipe.RecipeFailed, match="the rebuild failed"):
        run(world, tmp_path)


@pytest.mark.parametrize("tool", ["set_list", "layer_list"])
def test_a_stale_revision_in_a_rebuilt_snapshot_is_a_mismatch(
    world: World, tmp_path: Path, tool: str
) -> None:
    """Each read names its own snapshot's revision: one left at the original's is refused."""

    def stale(project: dict[str, Any]) -> None:
        project[tool]["revision"] = world.projects[world.saved][tool]["revision"]

    world.rebuilt_fault = stale
    with pytest.raises(tunic_recipe.RecipeMismatch, match=f"'{tool}': 5"):
        run(world, tmp_path)


def test_set_list_is_compared_across_projects_without_its_revision_only(
    world: World, tmp_path: Path
) -> None:
    run(world, tmp_path)
    first = world.projects[world.saved]
    second = renumbered(first)
    second["set_list"]["revision"] = REVISION
    tunic_recipe.compare_projects(first, second)  # the revision alone may differ
    second["set_list"]["texture_sets"][0]["original_name"] = "renamed"
    with pytest.raises(
        tunic_recipe.RecipeMismatch, match=r"set_list differs at \['texture_sets'\]"
    ):
        tunic_recipe.compare_projects(first, second)
    third = renumbered(first)
    third["shader_get"] = {**third["shader_get"], "revision": REVISION}  # never omitted there
    with pytest.raises(tunic_recipe.RecipeMismatch, match=r"shader_get differs at \['revision'\]"):
        tunic_recipe.compare_projects(first, third)


def test_a_rebuilt_project_that_changes_on_reopen_is_a_mismatch(
    world: World, tmp_path: Path
) -> None:
    def rename(project: dict[str, Any]) -> None:
        project["set_list"]["texture_sets"][0]["original_name"] = "renamed"

    world.reopen_fault = rename
    with pytest.raises(tunic_recipe.RecipeMismatch, match="after its save and reopen"):
        run(world, tmp_path)


def test_a_rebuilt_dump_other_than_the_one_saved_is_a_mismatch(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rebuild process's dump and the reopened project's are one project's: literal."""
    rebuild = tunic_recipe.rebuild

    def resaved(*args: Any, **kwargs: Any) -> dict[str, Any]:
        made = rebuild(*args, **kwargs)
        project = world.projects[str(made["file"])]
        project["project_recipe"] = {**project["project_recipe"], "app_version": "other"}
        return made

    monkeypatch.setattr(tunic_recipe, "rebuild", resaved)
    with pytest.raises(tunic_recipe.RecipeMismatch, match="not the one the rebuild saved"):
        run(world, tmp_path)
