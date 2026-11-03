"""The Tunic current round's state checks through typed MCP (`tests/parity/tier1/tunic_state.py`,
`mcp_round.drive_native(..., state=...)` and `mcp_round.run_tunic_current`): the bindings by the
pinned hashes through the mask-effect links, F03 and C07 distinct, the Height blends, the recipe's
settings and mesh, `double_sided` stored with parity false (decision 196), all after the sync and
again after the reopen, before the export. Nothing here starts UzPainter: the round runs against a
fake session over the native stand-in (C02 as the F03, C04 as the C07; 6 bindings onto 5
resources)."""

from __future__ import annotations

import contextlib
import copy
import json
from pathlib import Path, PurePosixPath
from typing import Any, cast

import pytest

from python.uzpainter_facade.bitmap_defaults import PAINTER_OCIO_CONFIG_SHA256
from tests.adapters.assets3d import wand as wand_module
from tests.parity.recorder.test_script_run import NATIVE_STACK, TUNIC_SET, make_assets
from tests.parity.recorder.test_script_run import native_manifest as make_native_manifest
from tests.parity.tier1 import mcp_round, tunic_state
from tests.parity.tier1.test_native_round_adapters import Session
from tests.parity.tier1.tunic_state import StateScenario
from tools.parity.recorder import script_run
from tools.parity.store.store import STORE_ENV

# The stand-in's scenario: C02 (the F03) overrides the M_iron_v9 that C04 (the C07) keeps.
STAND_IN = dict(
    bindings=6,
    resources=5,
    data_bindings=5,
    distinct=("C02", "C04"),
    height=(("Outer", "LinearDodge"), ("Lining", "Normal")),
)
DEFAULT_LAYER = "Layer 1"
STATE_READS = ["layer_list", "project_recipe", "shader_get", "display_get"]


@pytest.fixture(autouse=True)
def no_private_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "no-store"))


@pytest.fixture
def assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = make_assets(tmp_path / "assets3d")
    monkeypatch.setattr(wand_module, "ASSETS3D", root)
    return root


@pytest.fixture
def native(assets: Path, tmp_path: Path) -> dict[str, Any]:
    return make_native_manifest(assets, tmp_path / "repo")


def load_job(manifest: dict[str, Any], tmp_path: Path) -> script_run.NativeJob:
    job = script_run.pipeline_job_from_manifest(
        manifest, wand_module.ASSETS3D, repo_root=tmp_path / "repo"
    )
    assert isinstance(job, script_run.NativeJob)
    return job


def scenario_of(job: script_run.NativeJob, **changes: Any) -> StateScenario:
    return StateScenario(**{"golden_id": job.golden_id, **STAND_IN, **changes})


class StateSession(Session):
    """The native round's fake, plus the state reads: the sync builds the stack's nodes as
    UzPainter's `layer_list` lists them, bound to the pinned hashes. `tamper` changes one thing:
    before the first state read, or (`reopen-*`) when the project is opened again."""

    def __init__(self, job: script_run.NativeJob, tamper: str = "", **session: Any) -> None:
        super().__init__(**{"sets": [TUNIC_SET], "sha256": job.create.normal.sha256, **session})
        self.job = job
        self.tamper = tamper
        self.hashes = {PurePosixPath(m.name).stem: m.sha256 for m in job.sync.masks}
        self.revision = 4
        self.nodes: list[dict[str, Any]] = []
        self.double_sided = False
        self.uids: dict[str, int] = {}  # the stack's layer ids, and the groups' keys
        self.tampered = False

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert method == "tools/list"
        return {"tools": [{"name": "layer_list"}]}

    def close(self) -> None:
        pass

    # --- the stack the sync builds ----------------------------------------------------------

    def node(
        self, uid: int, kind: str, name: str, parent: int | None, slot: str, **params: Any
    ) -> dict[str, Any]:
        record = {
            "uid": uid,
            "node": "effect" if slot == "Mask" else "layer",
            "kind": kind,
            "name": name,
            "visible": True,
            "texture_set": 1,
            "stack": 1,
            "parent": parent,
            "slot": slot,
            "index": 0,
            "params": params,
        }
        self.nodes.append(record)
        return record

    def bitmap(self, name: str, space: str) -> dict[str, Any]:
        sha256 = self.hashes[name]
        return {
            "type": "bitmap",
            "resource": {"sha256": sha256, "alias": None},
            "color_space": space,
        }

    def masked(self, uid: int, name: str | None, next_uid: int) -> Any:
        if name is None:
            return None
        self.node(
            next_uid,
            "fill",
            name,
            uid,
            "Mask",
            blending={"mode": "Normal", "opacity": 1.0},
            fill={"source": self.bitmap(name, "Data")},
        )
        blending = {"mode": "Normal", "opacity": 1.0}
        return {"background": "Black", "enabled": True, "blending": blending, "effects": [next_uid]}

    def sync(self) -> dict[str, Any]:
        stack = NATIVE_STACK
        uid = iter(range(100, 1000))
        self.node(1, "fill", DEFAULT_LAYER, None, "Substack", mask=None, content_effects=[])
        self.nodes[0]["visible"] = False
        root = next(uid)
        groups, layers = [], []
        root_children: list[int] = []
        for group in stack["groups"]:
            gid = next(uid)
            root_children.insert(0, gid)
            groups.append({"key": group["key"], "name": group["name"], "uid": gid})
            self.uids[group["key"]] = gid
            mode = "Normal" if group.get("replace_height") else "LinearDodge"
            children: list[int] = []
            record = self.node(gid, "group", group["name"], root, "Substack", children=children)
            record["params"].update(
                blending={"Height": {"mode": mode, "opacity": 1.0}},
                content_effects=[],
                mask=self.masked(gid, group.get("mask"), next(uid)),
            )
            for layer in (x for x in stack["layers"] if x["group"] == group["key"]):
                lid = next(uid)
                children.insert(0, lid)
                layers.append({"group": group["key"], "name": layer["name"], "uid": lid})
                self.uids[layer["id"]] = lid
                base = (
                    self.bitmap(layer["base_tex"], "sRGB")
                    if layer.get("base_tex")
                    else {"type": "uniform_color", "rgb": [0.5] * 3, "color_space": "Working"}
                )
                self.node(
                    lid,
                    "fill",
                    layer["name"],
                    gid,
                    "Substack",
                    blending={"Height": {"mode": "LinearDodge", "opacity": 1.0}},
                    content_effects=[],
                    fill={"sources": {"BaseColor": base}},
                    mask=self.masked(lid, layer.get("mask"), next(uid)),
                )
        self.node(
            root,
            "group",
            stack["title"],
            None,
            "Substack",
            blending={"Height": {"mode": "LinearDodge", "opacity": 1.0}},
            content_effects=[],
            mask=None,
            children=root_children,
        )
        return {
            "root_uid": root,
            "groups": groups,
            "layers": layers,
            "hidden": [{"name": DEFAULT_LAYER, "uid": 2 if self.tamper == "hidden-uid" else 1}],
            "imported": sorted(self.hashes),
            "skipped": [],
            "deleted": [],
        }

    # --- the authored faults ----------------------------------------------------------------

    def effect_of(self, layer_id: str) -> dict[str, Any]:
        owner = next(n for n in self.nodes if n["uid"] == self.uids[layer_id])
        uid = owner["params"]["mask"]["effects"][0]
        effect: dict[str, Any] = next(n for n in self.nodes if n["uid"] == uid)
        return effect

    def group_named(self, name: str) -> dict[str, Any]:
        return next(n for n in self.nodes if n["name"] == name and n["kind"] == "group")

    def apply(self, fault: str) -> None:
        f03, c07 = (self.effect_of(x)["params"]["fill"]["source"] for x in ("C02", "C04"))
        if fault == "swapped":
            f03["resource"], c07["resource"] = c07["resource"], f03["resource"]
        elif fault == "shared":
            f03["resource"] = copy.deepcopy(c07["resource"])
        elif fault == "srgb":
            c07["color_space"] = "sRGB"
        elif fault == "blend":
            self.group_named("Lining")["params"]["blending"]["Height"]["mode"] = "LinearDodge"
        elif fault == "extra-binding":
            self.nodes[0]["params"]["fill"] = {
                "sources": {"BaseColor": self.bitmap("M_wood", "sRGB")}
            }
        elif fault == "hidden-effect":
            self.nodes[0]["node"] = "effect"
        elif fault == "group-order":
            children = next(n for n in self.nodes if n["name"] == NATIVE_STACK["title"])
            children["params"]["children"].reverse()
        elif fault == "layer-order":
            self.group_named("Outer")["params"]["children"][:2] = reversed(
                self.group_named("Outer")["params"]["children"][:2]
            )
        elif fault == "stack-lost":
            self.nodes = [n for n in self.nodes if n["uid"] == 1]
            self.nodes[0]["visible"] = True
        elif fault == "double-sided-lost":
            self.double_sided = False
        elif fault == "renumbered":
            for record in self.nodes:
                record["uid"] += 1000
                record["parent"] = None if record["parent"] is None else record["parent"] + 1000
                params = record["params"]
                if "children" in params:
                    params["children"] = [u + 1000 for u in params["children"]]
                if isinstance(params.get("mask"), dict):
                    params["mask"]["effects"] = [u + 1000 for u in params["mask"]["effects"]]
        elif fault != "":
            assert fault in ("parity-true", "setting", "mesh", "stale", "hidden-uid"), fault

    # --- the replies ------------------------------------------------------------------------

    def recipe(self) -> dict[str, Any]:
        settings = self.job.create.settings
        resolution = settings["default_texture_resolution"]
        tangent = "PerVertex" if self.fault("setting") else settings["tangent_space_mode"]
        mesh = "0" * 64 if self.fault("mesh") else self.job.create.mesh.sha256
        return {
            "revision": self.revision,
            "digest": "d" * 64,
            "recipe": {
                "settings": {
                    "normal_map_format": settings["normal_map_format"],
                    "tangent_space": tangent,
                    "workflow": settings["project_workflow"],
                    "color_management": {"mode": "ocio", "config_hash": PAINTER_OCIO_CONFIG_SHA256},
                },
                "mesh": {"resource": mesh, "import_report": {}},
            },
            "rebuild": {
                "/settings/default_resolution": {"width": resolution, "height": resolution},
                "/settings/import_cameras": settings["import_cameras"],
                "/settings/mesh_unit_scale": settings["mesh_unit_scale"],
                "/settings/auto_unwrap": False,
            },
        }

    def fault(self, name: str) -> bool:
        return self.tamper in (name, f"reopen-{name}") and self.tampered

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool not in ("sync_stack", "shader_set", "project_close", "project_open", *STATE_READS):
            return super().call(tool, arguments)
        self.calls.append((tool, arguments))
        if tool == "sync_stack":
            return {"result": {"status": "committed", "returned": {"sync": self.sync()}}}
        if tool == "shader_set":
            self.double_sided = arguments["parameters"]["double_sided"]
            self.revision += 1
            return {"result": {"status": "committed"}, "committed_revision": self.revision}
        if tool == "project_close":
            return {"result": {"closed": True}}
        if tool == "project_open":
            if self.tamper.startswith("reopen-"):
                self.tampered = True
                self.apply(self.tamper.removeprefix("reopen-"))
            return {"result": {"revision": self.revision}}
        if not self.tampered and not self.tamper.startswith("reopen-"):
            self.tampered = True
            self.apply(self.tamper)
        if tool == "layer_list":
            stale = self.revision + (1 if self.fault("stale") else 0)
            nodes = copy.deepcopy(self.nodes)
            return {"result": {"revision": stale, "texture_set": TUNIC_SET, "nodes": nodes}}
        if tool == "project_recipe":
            return {"result": self.recipe()}
        parameters = {"double_sided": self.double_sided, "specular_ior": 1.5}
        shader = {"shader": "open-pbr", "parameters": parameters}
        if tool == "shader_get":
            return {"result": shader}
        parity = self.fault("parity-true") or not self.double_sided
        return {"result": {"parity": parity, "shader": shader}}


def state_round(
    native: dict[str, Any], tmp_path: Path, tamper: str = "", **changes: Any
) -> tuple[StateSession, mcp_round.Round]:
    job = load_job(native, tmp_path)
    staged = script_run.stage_inputs(job, tmp_path / "round" / "assets")
    fake = StateSession(job, tamper)
    log = mcp_round.Round(0, False)
    driver = mcp_round.Driver(cast(Any, fake), log)
    with contextlib.suppress(mcp_round.RoundFailed):  # `log.outcome` says `failed`
        mcp_round.drive(driver, job, staged, tmp_path / "round", scenario_of(job, **changes))
    return fake, log


SAVED = [
    "project_create",
    "set_list",
    "resource_import",
    "set_mesh_maps",
    "set_list",
    "project_save_as",
    "sync_stack",
    "shader_set",
    "project_save",
    "set_list",
]
REOPENED = [*SAVED, *STATE_READS, "project_close", "project_open", "set_list"]


def test_the_state_round_checks_the_saved_and_reopened_state_before_its_export(
    native: dict[str, Any], tmp_path: Path
) -> None:
    session, log = state_round(native, tmp_path)
    assert log.outcome == "completed" and log.refusal is None, log.calls
    tools = [tool for tool, _ in session.calls]
    assert tools == [*REOPENED, *STATE_READS, "export"]
    project = str(tmp_path / "round" / "project" / "native-create.uzp")
    assert ("shader_set", {"parameters": {"double_sided": True}}) in session.calls
    assert ("project_open", {"path": project, "wait": True}) in session.calls
    assert ("layer_list", {"texture_set": TUNIC_SET}) in session.calls
    assert list(log.files) == [(TUNIC_SET, f"{TUNIC_SET}_Height")]


@pytest.mark.parametrize(
    ("tamper", "sent"),
    [
        ("swapped", [*SAVED, "layer_list"]),
        ("shared", [*SAVED, "layer_list"]),
        ("srgb", [*SAVED, "layer_list"]),
        ("blend", [*SAVED, "layer_list"]),
        ("extra-binding", [*SAVED, "layer_list"]),
        ("hidden-effect", [*SAVED, "layer_list"]),
        ("hidden-uid", [*SAVED, "layer_list"]),
        ("reopen-hidden-effect", [*REOPENED, "layer_list"]),
        ("group-order", [*SAVED, "layer_list"]),
        ("layer-order", [*SAVED, "layer_list"]),
        ("reopen-group-order", [*REOPENED, "layer_list"]),
        ("reopen-layer-order", [*REOPENED, "layer_list"]),
        ("stale", [*SAVED, "layer_list"]),
        ("setting", [*SAVED, *STATE_READS]),
        ("mesh", [*SAVED, *STATE_READS]),
        ("parity-true", [*SAVED, *STATE_READS]),
        ("reopen-stack-lost", [*REOPENED, "layer_list"]),
        ("reopen-double-sided-lost", [*REOPENED, *STATE_READS]),
        ("reopen-renumbered", [*REOPENED, "layer_list"]),
        ("reopen-swapped", [*REOPENED, "layer_list"]),
    ],
)
def test_a_wrong_state_fails_the_round_before_its_export(
    native: dict[str, Any], tmp_path: Path, tamper: str, sent: list[str]
) -> None:
    """F03 and C07 swapped or sharing a resource, a mask read as sRGB, a wrong Height blend, a
    binding beyond the stack's, the hidden root an effect or not the uid the sync hid, the two
    groups or two layers of a group in swapped order (every binding, name and Height kept), a
    read at another revision, a setting or mesh the recipe does not persist, parity reported with
    `double_sided` true, and the stack, its order, the hidden root, `double_sided` or the uids
    not kept by the reopen: the round fails at that read and never exports."""
    session, log = state_round(native, tmp_path, tamper)
    assert log.outcome == "failed" and log.refusal is None
    tools = [tool for tool, _ in session.calls]
    assert tools[: len(sent)] == sent and "export" not in tools
    if tamper.startswith("reopen-"):
        assert len(tools) > len(REOPENED)


@pytest.mark.parametrize(
    "changes",
    [
        {"bindings": 7},
        {"resources": 6},
        {"distinct": ("C04", "C02")},
        {"height": (("Outer", "LinearDodge"), ("Lining", "LinearDodge"))},
        {"golden_id": "phase2/tier1/tunic-v10-current"},
    ],
    ids=["bindings", "resources", "not-the-override", "height", "golden"],
)
def test_a_scenario_that_does_not_fit_the_job_is_refused_before_any_call(
    native: dict[str, Any], tmp_path: Path, changes: dict[str, Any]
) -> None:
    session, log = state_round(native, tmp_path, **changes)
    assert log.outcome == "failed" and session.calls == []


def test_the_tunic_scenario_is_the_supplementary_records_state() -> None:
    expected = StateScenario(
        golden_id="phase2/tier1/tunic-v10-current",
        bindings=21,
        resources=17,
        data_bindings=21,
        distinct=("F03", "C07"),
        height=(("Forro", "Normal"), ("Tecido externo", "LinearDodge")),
        root_height="LinearDodge",
    )
    assert expected == tunic_state.TUNIC_CURRENT


# --- the entrypoint ---------------------------------------------------------------------------


@pytest.fixture
def entry(
    native: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> list[StateSession]:
    """`run_tunic_current`'s UzPainter replaced by a fake; the sessions it starts are listed."""
    monkeypatch.setattr(mcp_round, "ASSETS3D", wand_module.ASSETS3D)

    def loader(path: Path, assets_root: Path) -> Any:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        return script_run.pipeline_job_from_manifest(
            manifest, assets_root, repo_root=tmp_path / "repo"
        )

    started: list[StateSession] = []

    def mcp(painter: Path, work: Path, *args: str) -> StateSession:
        started.append(StateSession(load_job(native, tmp_path)))
        return started[-1]

    monkeypatch.setattr(mcp_round, "load_pipeline_job", loader)
    monkeypatch.setattr(mcp_round, "Mcp", mcp)
    return started


def manifest_file(tmp_path: Path, manifest: dict[str, Any]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_the_entrypoint_refuses_another_golden_before_uzpainter_starts(
    native: dict[str, Any], tmp_path: Path, entry: list[StateSession]
) -> None:
    with pytest.raises(mcp_round.RoundFailed, match="contract mismatch: the scenario is"):
        mcp_round.run_tunic_current(
            tmp_path / "UzPainter.exe", tmp_path / "work", manifest_file(tmp_path, native)
        )
    assert entry == []


def test_the_entrypoint_refuses_a_job_off_the_tunic_contract_before_uzpainter_starts(
    native: dict[str, Any], tmp_path: Path, entry: list[StateSession]
) -> None:
    """The Tunic's golden id over a stack that is not the Tunic's (6 bindings, other groups)."""
    relabelled = {**native, "golden_id": tunic_state.TUNIC_CURRENT.golden_id}
    with pytest.raises(mcp_round.RoundFailed, match="contract mismatch"):
        mcp_round.run_tunic_current(
            tmp_path / "UzPainter.exe", tmp_path / "work", manifest_file(tmp_path, relabelled)
        )
    assert entry == []


def test_the_entrypoint_runs_the_state_round(
    native: dict[str, Any],
    tmp_path: Path,
    entry: list[StateSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the scenario fitting the job, `run_tunic_current` drives the state round."""
    job = load_job(native, tmp_path)
    monkeypatch.setattr(tunic_state, "TUNIC_CURRENT", scenario_of(job))
    log = mcp_round.run_tunic_current(
        tmp_path / "UzPainter.exe", tmp_path / "work", manifest_file(tmp_path, native)
    )
    assert log.outcome == "completed", log.calls
    [session] = entry
    assert [tool for tool, _ in session.calls] == [*REOPENED, *STATE_READS, "export"]


def test_an_unrelated_native_round_keeps_its_calls(native: dict[str, Any], tmp_path: Path) -> None:
    """No scenario, no state check: the native round sends exactly its own calls."""
    job = load_job(native, tmp_path)
    staged = script_run.stage_inputs(job, tmp_path / "round" / "assets")
    fake = StateSession(job)
    log = mcp_round.Round(0, False)
    mcp_round.drive(mcp_round.Driver(cast(Any, fake), log), job, staged, tmp_path / "round")
    tools = [tool for tool, _ in fake.calls]
    assert log.outcome == "completed"
    assert tools == [t for t in SAVED if t != "shader_set"] + ["export"]
