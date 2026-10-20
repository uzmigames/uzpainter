"""Pipeline-script Tier 1 goldens (decision 099; recording R9): job parsing, the `open` redirect,
the sync transport swap and the r1 / r1-repeat / r2 recordings, against a fake Painter and a
temporary stand-in asset repository whose small scripts mirror the shape of the real ones. The
private store is a temporary one (or none): the owner's real store is read only by the test of the
committed manifest."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder import script_run
from tools.parity.recorder import session as session_module
from tools.parity.recorder.script_run import (
    ASSETS3D_LICENCE,
    CONFIG_EXPORT,
    PAINTER_SCRIPTS,
    RUN_SCRIPT,
    ScriptSession,
    load_script_job,
    record_script_golden,
    script_job_from_manifest,
    wand_float_manifest,
    wand_manifest,
    wand_normal_float_manifest,
)
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, Schema, load_json, record_problems, validation_errors
from tools.parity.store.store import STORE_ENV, OracleStore
from tools.parity.store.store import locate as locate_store

BUILD = "12.1.5+js-api.1.1.20"
OCIO = r"C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\ocio\substance\config.ocio"
WAND = "_tmp/claude/varinha11-v1"
REAL_ASSETS = Path(r"E:\UzmiGames\Assets3D")
COMMITTED = (
    REPO_ROOT / "parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/phase1/tier1/wand-v1.json"
)
PINNED_MARK = "pinned-stand-in-7f3a"

CREATE = '''"""Stand-in of painter_create.py: a new project from the args' mesh, saved to dst."""
import json
import substance_painter.project as project, substance_painter.textureset as ts
A = json.loads(open(r"__ARGS__", encoding="utf-8").read())
st = project.Settings(normal_map_format=project.NormalMapFormat.OpenGL,
                      default_texture_resolution=256, import_cameras=False)
project.create(mesh_file_path=A["mesh"], settings=st)
maps = {usage: len(open(path, "rb").read())
        for usage, path in (("Normal", A["normal"]), ("AO", A["ao"]))}
project.save_as(A["dst"], project.ProjectSaveMode.Full)
result = {"file": project.file_path(), "sets": [x.name() for x in ts.all_texture_sets()],
          "maps": maps, "name": A["name"]}
'''

LAYER_STACK = '''"""Stand-in of painter_layer_stack.py: sync builds Painter code and executes it,
behind the route guard of Assets3D 9a718b9 (a probe of the open project, then `locate`)."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'AGENTS.md').exists())
CLIENT = ROOT / "Pipeline/mcp/painter_mcp_client.py"
MCP_PYTHON = ROOT / "Tools/SubstancePainterMCP/.venv/Scripts/python.exe"
sys.path.insert(0, str(ROOT / "Pipeline/qa"))
from route_check import locate  # noqa: E402

GUARD_CODE = r\'\'\'
import substance_painter.project as project
name = __TS__
result = {"project": project.file_path(), "texture_set": name}
\'\'\'

SYNC_CODE = r\'\'\'
import json
import substance_painter.project as project
S = json.loads(r"""__STACK__""")
MASKS = json.loads(r"""__MASKS__""")
sizes = {name: len(open(m["path"], "rb").read()) for name, m in MASKS.items()}
result = {"project": project.file_path(), "layers": [L["id"] for L in S["layers"]],
          "imported": sorted(MASKS), "hidden": [], "group_height_blend": {},
          "resources": {k: "resource://fake/" + k for k in MASKS}, "sizes": sizes,
          "mark": "__MARK__"}
\'\'\'


def execute(code, token=None):
    command = [str(MCP_PYTHON), str(CLIENT), "execute_python", code]
    env = dict(os.environ, UZ_ROUTE_TOKEN=token or "")
    run = subprocess.run(command, capture_output=True, text=True, env=env)
    return json.loads(run.stdout)["data"]


def route_guard(texture_set, mode):
    info = execute(GUARD_CODE.replace("__TS__", repr(texture_set)))
    if not info.get("project"):
        raise SystemExit("ROUTE BLOCKED: save the Painter project inside the piece folder first")
    state, state_path = locate(info["project"])
    if state == "legacy":
        return None
    if state != "production":
        raise SystemExit(f"ROUTE BLOCKED: {info['project']} has no production state")
    return "attempt-token"


def sync(a):
    stack = json.loads(Path(a.stack).read_text(encoding="utf-8"))
    masks_dir = Path(a.masks).resolve()
    state_path = Path(a.state)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    names = sorted({x["mask"] for x in stack["layers"] + stack["groups"] if x.get("mask")})
    names = sorted(set(names) | {x["base_tex"] for x in stack["layers"] if x.get("base_tex")})
    masks = {}
    for name in names:
        path = masks_dir / (name + ".png")
        sha = hashlib.sha1(path.read_bytes()).hexdigest()
        masks[name] = {"sha": sha, "path": path.as_posix(), "url": None}
    code = SYNC_CODE.replace("__STACK__", json.dumps(stack)).replace("__MASKS__", json.dumps(masks))
    token = route_guard(a.texture_set, "sync")
    data = execute(code, token)
    for name, url in data["resources"].items():
        state[name] = {"sha": masks[name]["sha"], "url": url}
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    print("SYNC_DONE", json.dumps({"project": data["project"], "layers": len(data["layers"])}))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--stack", required=True)
    s.add_argument("--masks", required=True)
    s.add_argument("--state", required=True)
    s.add_argument("--texture-set")
    args = parser.parse_args()
    {"sync": sync}[args.command](args)


if __name__ == "__main__":
    main()
'''.replace("__MARK__", PINNED_MARK)

EXPORT = '''"""Stand-in of painter_export.py: save the open project, export its maps (PNG16)."""
import json, os
import substance_painter.project as project, substance_painter.export as ex
import substance_painter.textureset as ts
A = json.loads(open(r"__ARGS__", encoding="utf-8").read())
project.save_as(project.file_path(), project.ProjectSaveMode.Full)
os.makedirs(A["out"], exist_ok=True)
P = A["prefix"]
doc = lambda name, src: {"fileName": f"{P}_{name}", "channels": [
    {"destChannel": c, "srcChannel": c, "srcMapType": "documentMap", "srcMapName": src}
    for c in ("RGB" if name == "BaseColor" else "L")]}
cfg = {"exportShaderParams": False, "exportPath": A["out"], "defaultExportPreset": "v6",
       "exportPresets": [{"name": "v6", "maps": [doc("BaseColor", "basecolor"),
                                                 doc("Height", "height")]}],
       "exportList": [{"rootPath": s.name()} for s in ts.all_texture_sets()],
       "exportParameters": [{"parameters": {"fileFormat": "png", "bitDepth": "16", "sizeLog2": 11,
                                            "paddingAlgorithm": "infinite", "dithering": False}}]}
r = ex.export_project_textures(cfg)
result = {"status": str(r.status), "message": r.message,
          "files": {str(k): v for k, v in r.textures.items()}, "saved": project.file_path()}
'''

ROUTE_CHECK = '''"""Stand-in of route_check.py: `locate` finds a character's production state."""
from pathlib import Path


def locate(path):
    path = Path(path).resolve()
    for folder in [path, *path.parents]:
        if (folder / "Concept").is_dir() and (folder / "Project").is_dir():
            state = folder / "Project" / "production.json"
            return ("production", state) if state.exists() else ("missing", state)
    return ("legacy", None)
'''

MESH = "mtllib 11-Varinha-Madeira-v1_low.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nf 1 2 3\n"
STACK = {
    "title": "stand-in stack",
    "groups": [{"key": "outer", "name": "Outer", "mask": None}],
    "layers": [
        {"id": "C01", "group": "outer", "name": "Wood", "mask": "M_wood", "base_tex": "T_base"},
        {"id": "C02", "group": "outer", "name": "Iron", "mask": "M_iron", "base": [0.5, 0.5, 0.5]},
    ],
}


def write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)


def make_assets(root: Path) -> Path:
    """A stand-in Assets3D at the real layout (the manifest generator's paths)."""
    write(root / "AGENTS.md", "stand-in asset repository\n")
    win = str(root)
    create_args = str(root / WAND / "painter_create_args.json")
    export_args = str(root / WAND / "painter_export_args.json")
    scripts = root / "Pipeline/retopology/wand11-v1"
    write(scripts / "painter_create.py", CREATE.replace("__ARGS__", create_args))
    write(scripts / "painter_export.py", EXPORT.replace("__ARGS__", export_args))
    write(root / "Pipeline/painting/painter_layer_stack.py", LAYER_STACK)
    write(root / "Pipeline/qa/route_check.py", ROUTE_CHECK)
    paint = root / WAND / "paint"
    write(paint / "11-Varinha-Madeira-v1_low.obj", MESH)
    write(paint / "11-Varinha-Madeira-v1_low.mtl", "newmtl 11-Varinha-Madeira\n")
    write(root / WAND / "bake/11-Varinha-Madeira_Normal_OpenGL_v1.png", b"normal")
    write(paint / "11-Varinha-Madeira_AO_v1.png", b"ao")
    for name in ("M_wood", "M_iron", "T_base"):
        write(paint / "masks" / f"{name}.png", name.encode("ascii"))
    write(paint / "stack-wand.json", json.dumps(STACK))
    windows = win.replace("/", "\\")
    write(
        Path(create_args),
        json.dumps(
            {
                "mesh": windows + r"\_tmp\claude\varinha11-v1\paint\11-Varinha-Madeira-v1_low.obj",
                "normal": windows
                + r"\_tmp\claude\varinha11-v1\bake\11-Varinha-Madeira_Normal_OpenGL_v1.png",
                "ao": windows + r"\_tmp\claude\varinha11-v1\paint\11-Varinha-Madeira_AO_v1.png",
                "dst": windows + r"\Models3D\11-Varinha-Madeira\11-Varinha-Madeira-v1.spp",
                "name": "11-Varinha-Madeira",
            }
        ),
    )
    write(
        Path(export_args),
        json.dumps({"out": windows + r"\_tmp\claude\varinha11-v1\paint\tex-r2", "prefix": "W_v1"}),
    )
    return root


def tree_state(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(autouse=True)
def no_private_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No private store unless a test makes one: the stand-in pins resolve under `assets`."""
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "no-store"))


@pytest.fixture
def assets(tmp_path: Path) -> Path:
    return make_assets(tmp_path / "assets3d")


@pytest.fixture
def manifest(assets: Path) -> dict[str, Any]:
    return wand_manifest(assets)


@pytest.fixture
def painter(fake: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ScriptSession]:
    """A fake Painter 12.1.5 started under Painter's substance OCIO configuration."""
    monkeypatch.setattr(session_module, "envelope_builds", lambda: frozenset({BUILD}))
    monkeypatch.setenv("OCIO", OCIO)
    monkeypatch.delenv("PAINTER_ACE_CONFIG", raising=False)
    world = fake.FakeWorld()
    world.version, world.version_info = "12.1.5", (12, 1, 5)
    return world, ScriptSession(fake.LocalTransport(world), sleep=lambda seconds: None)


def record(
    painter: tuple[Any, ScriptSession], manifest: dict[str, Any], assets: Path, tmp_path: Path
) -> Path:
    job = script_job_from_manifest(manifest, assets)
    return record_script_golden(painter[1], job, tmp_path / "work", tmp_path / "inbox")


# --- job parsing -----------------------------------------------------------------------------


def test_manifest_names_every_input_by_hash_and_assets3d_path(manifest: dict[str, Any]) -> None:
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["instruction_sequence"]["interface"] == "uzmigames_pipeline_scripts"
    assert {s["call"] for s in manifest["instruction_sequence"]["steps"]} == {RUN_SCRIPT}
    for item in manifest["inputs"]:
        assert "path" not in item and item["assets3d_path"]
        assert item["provenance"] == {"origin": "uzmigames_authored", "licence": ASSETS3D_LICENCE}
    sync = manifest["instruction_sequence"]["steps"][1]["args"]
    assert sync["mask_files"] == ["M_iron.png", "M_wood.png", "T_base.png"]
    assert sync["imports"] == ["route-check-py"]


def test_job_refuses_a_hash_mismatch(assets: Path, manifest: dict[str, Any]) -> None:
    (assets / WAND / "paint/masks/M_wood.png").write_bytes(b"changed")
    with pytest.raises(RecorderError, match=r"mask-m_wood: .* has sha256 .*no private store"):
        script_job_from_manifest(manifest, assets)


def test_job_refuses_a_script_whose_bytes_differ_from_the_pin(
    assets: Path, manifest: dict[str, Any]
) -> None:
    path = assets / "Pipeline/painting/painter_layer_stack.py"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(RecorderError, match=r"painter-layer-stack-py: .* has sha256"):
        script_job_from_manifest(manifest, assets)


def test_job_refuses_a_changed_import(assets: Path, manifest: dict[str, Any]) -> None:
    path = assets / "Pipeline/qa/route_check.py"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(RecorderError, match=r"route-check-py: .* has sha256"):
        script_job_from_manifest(manifest, assets)


def test_job_refuses_an_import_the_sync_script_does_not_make(
    assets: Path, manifest: dict[str, Any]
) -> None:
    changed = copy.deepcopy(manifest)
    changed["instruction_sequence"]["steps"][1]["args"]["imports"] = ["painter-export-py"]
    with pytest.raises(RecorderError, match=r"imports no module \['painter_export'\]"):
        script_job_from_manifest(changed, assets)


def test_job_refuses_a_missing_input(assets: Path, manifest: dict[str, Any]) -> None:
    (assets / WAND / "paint/11-Varinha-Madeira-v1_low.mtl").unlink()
    with pytest.raises(RecorderError, match="does not exist, and the private store holds no"):
        script_job_from_manifest(manifest, assets)


def test_an_input_gone_from_assets3d_resolves_from_the_private_store(
    assets: Path, manifest: dict[str, Any], tmp_path: Path
) -> None:
    """Decision 144: a missing or changed file at the pinned path falls back to the store's blob
    of the pinned hash; the job stages and runs those bytes. A store without it refuses."""
    store = OracleStore.init(tmp_path / "store")
    mask = assets / WAND / "paint/masks/M_wood.png"
    script = assets / "Pipeline/qa/route_check.py"
    for path in (mask, script):
        relative = path.relative_to(assets).as_posix()
        assert main_store(store, "input", path, "--path", relative) == 0
    pinned = {path: path.read_bytes() for path in (mask, script)}
    mask.unlink()
    script.write_bytes(b"locate = None\n")
    job = script_job_from_manifest(manifest, assets, store)
    for input_id, path in (("mask-m_wood", mask), ("route-check-py", script)):
        item = job.inputs[input_id]
        assert item.file.is_relative_to(store.root) and item.file.read_bytes() == pinned[path]
    assert job.sync.imports[0].data == pinned[script]
    staged = script_run.stage_inputs(job, tmp_path / "staged")
    assert staged["mask-m_wood"].read_bytes() == pinned[mask]
    assert staged["mask-m_wood"] == tmp_path / "staged" / WAND / "paint/masks/M_wood.png"
    with pytest.raises(
        RecorderError, match=r"route-check-py: .* not the pinned one, .*blob missing"
    ):
        script_job_from_manifest(manifest, assets, OracleStore.init(tmp_path / "empty"))


def main_store(store: OracleStore, *args: str | Path) -> int:
    from tools.parity.store.cli import main as store_main

    return store_main(["--store", str(store.root), *(str(a) for a in args)])


def test_job_refuses_an_unknown_call(assets: Path, manifest: dict[str, Any]) -> None:
    changed = copy.deepcopy(manifest)
    changed["instruction_sequence"]["steps"][2]["call"] = "uzmigames.pipeline.other"
    assert validation_errors(changed, Schema.GOLDEN_PUBLIC)
    with pytest.raises(RecorderError, match=r"is not uzmigames\.pipeline\.run_script"):
        script_job_from_manifest(changed, assets)


def test_job_refuses_unknown_step_arguments(assets: Path, manifest: dict[str, Any]) -> None:
    changed = copy.deepcopy(manifest)
    changed["instruction_sequence"]["steps"][2]["args"]["extra"] = 1
    with pytest.raises(RecorderError, match="no create, sync or export"):
        script_job_from_manifest(changed, assets)


def test_job_refuses_masks_the_stack_does_not_reference(
    assets: Path, manifest: dict[str, Any]
) -> None:
    changed = copy.deepcopy(manifest)
    args = changed["instruction_sequence"]["steps"][1]["args"]
    args["masks"], args["mask_files"] = args["masks"][:2], args["mask_files"][:2]
    with pytest.raises(RecorderError, match="references the bitmaps"):
        script_job_from_manifest(changed, assets)


def test_job_refuses_an_args_file_naming_another_mesh(
    assets: Path, manifest: dict[str, Any]
) -> None:
    args_file = assets / WAND / "painter_create_args.json"
    arguments = json.loads(args_file.read_text(encoding="utf-8"))
    arguments["mesh"] = r"E:\elsewhere\other.obj"
    args_file.write_text(json.dumps(arguments), encoding="utf-8")
    changed = wand_manifest_unchecked(manifest, assets)
    with pytest.raises(RecorderError, match="`mesh` names"):
        script_job_from_manifest(changed, assets)


def wand_manifest_unchecked(manifest: dict[str, Any], assets: Path) -> dict[str, Any]:
    """The manifest with every hash re-pinned to the files now under `assets`."""
    changed = copy.deepcopy(manifest)
    for item in changed["inputs"]:
        item["sha256"] = hashlib.sha256((assets / item["assets3d_path"]).read_bytes()).hexdigest()
    return changed


# --- Painter side: the open redirect ---------------------------------------------------------


def painter_scripts_namespace() -> dict[str, Any]:
    namespace: dict[str, Any] = {"OPERATIONS": {}}
    exec(compile(PAINTER_SCRIPTS.read_bytes(), str(PAINTER_SCRIPTS), "exec"), namespace)
    return namespace


def test_open_redirect_maps_only_the_one_hard_coded_path(tmp_path: Path) -> None:
    hard = tmp_path / "assets" / "painter_create_args.json"
    other = tmp_path / "assets" / "other_args.json"
    repointed = tmp_path / "work" / "painter_create_args.json"
    for path, text in ((hard, "original"), (other, "other"), (repointed, "repointed")):
        write(path, text)
    namespace = painter_scripts_namespace()
    assert set(namespace["OPERATIONS"]) == {"run_script"}
    open_file = namespace["redirected_open"](str(hard), str(repointed))
    with open_file(str(hard), encoding="utf-8") as stream:
        assert stream.read() == "repointed"
    with open_file(str(hard).upper().replace("\\", "/"), encoding="utf-8") as stream:
        assert stream.read() == ("repointed" if sys.platform == "win32" else "original")
    with open_file(hard.with_name("painter_create_args.json.bak"), "w") as stream:
        stream.write("x")
    with open_file(str(other), encoding="utf-8") as stream:
        assert stream.read() == "other"
    assert hard.read_text(encoding="utf-8") == "original"


def test_run_script_refuses_bytes_that_differ_from_their_hash(tmp_path: Path) -> None:
    namespace = painter_scripts_namespace()
    source = b"result = {'ok': True}\n"
    args = {
        "source": base64.b64encode(source).decode("ascii"),
        "sha256": hashlib.sha256(source).hexdigest(),
        "file_name": "s.py",
        "args_path": None,
        "args_copy": None,
    }
    assert namespace["run_script"](args) == {"result": {"ok": True}}
    with pytest.raises(ValueError, match="pinned SHA-256"):
        namespace["run_script"]({**args, "sha256": "0" * 64})
    nothing = base64.b64encode(b"x = 1\n").decode("ascii")
    with pytest.raises(RuntimeError, match="no `result`"):
        namespace["run_script"](
            {**args, "source": nothing, "sha256": hashlib.sha256(b"x = 1\n").hexdigest()}
        )


# --- recordings --------------------------------------------------------------------------------


def test_records_r1_repeat_and_r2_without_writing_under_the_assets_root(
    painter: tuple[Any, ScriptSession],
    manifest: dict[str, Any],
    assets: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = tree_state(assets)

    def no_subprocess(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the sync command must not start the MCP client")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    decoy = types.ModuleType("painter_layer_stack")
    monkeypatch.setitem(sys.modules, "painter_layer_stack", decoy)
    route_decoy = types.ModuleType("route_check")
    route_decoy.locate = no_subprocess  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "route_check", route_decoy)
    path = list(sys.path)
    # Modules imported before the run (pytest imports every collected test module, such as
    # tests.supervisor.test_supervisor_mcp) are not the sync command's imports.
    loaded = set(sys.modules)
    run = record(painter, manifest, assets, tmp_path)

    assert tree_state(assets) == before
    assert sys.modules["route_check"] is route_decoy and sys.path == path  # restored
    assert not [name for name in set(sys.modules) - loaded if "mcp" in name.lower()]
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    recordings = {r["recording_id"]: r for r in data["recordings"]}
    assert {k: r["condition"] for k, r in recordings.items()} == {
        "r1": "same_session",
        "r1-repeat": "same_session",
        "r2": "after_save_reopen",
    }
    for recording in recordings.values():
        maps = sorted(o["map"] for o in recording["outputs"] if o["kind"] == "exported_map")
        assert maps == ["W_v1_BaseColor", "W_v1_Height"]
    readbacks = {
        (rid, o["output_id"]): o["value"]
        for rid, r in recordings.items()
        for o in r["outputs"]
        if o["kind"] == "api_readback"
    }
    assert {o for o in readbacks} == {
        ("r1", "script/s1"),
        ("r1", "script/s2"),
        ("r1", "script/s3"),
        ("r1-repeat", "script/s3"),
        ("r2", "script/s3"),
    }
    work = tmp_path / "work"
    created = readbacks[("r1", "script/s1")]
    assert Path(created["file"]).is_relative_to(work)  # dst repointed into the work directory
    assert created["name"] == "11-Varinha-Madeira"  # other keys unchanged
    synced = readbacks[("r1", "script/s2")]
    assert synced["mark"] == PINNED_MARK  # the pinned bytes ran, not the decoy module
    assert synced["imported"] == ["M_iron", "M_wood", "T_base"]
    exports = {rid: readbacks[(rid, "script/s3")] for rid in ("r1", "r1-repeat", "r2")}
    outs = {
        rid: {Path(f).parent for files in v["files"].values() for f in files}
        for rid, v in exports.items()
    }
    assert len({p for paths in outs.values() for p in paths}) == 3  # a fresh directory each
    assert all(p.is_relative_to(work) for paths in outs.values() for p in paths)
    state = next(work.rglob("sync-state.json"))
    assert sorted(json.loads(state.read_text(encoding="utf-8"))) == ["M_iron", "M_wood", "T_base"]
    published = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert validation_errors(published, Schema.GOLDEN_PUBLIC) == []
    assert data["key"]["project_settings"]["colour_management"]["mode"] == "ocio"


@pytest.mark.parametrize(
    ("production_state", "refusal"),
    [(False, "ROUTE BLOCKED: .* has no production state"), (True, "attempt token")],
)
def test_refuses_a_route_guard_verdict_inside_the_production_layout(
    painter: tuple[Any, ScriptSession],
    manifest: dict[str, Any],
    assets: Path,
    tmp_path: Path,
    production_state: bool,
    refusal: str,
) -> None:
    """The work directory inside a new-layout character: the guard blocks (no production state)
    or returns an attempt token; either way the sync code never reaches Painter."""
    (tmp_path / "Concept").mkdir()
    (tmp_path / "Project").mkdir()
    if production_state:
        (tmp_path / "Project" / "production.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RecorderError, match=refusal):
        record(painter, manifest, assets, tmp_path)
    assert not list((tmp_path / "work").rglob("sync-state.json"))
    assert not painter[0].project_open


def test_refuses_without_the_ocio_configuration(
    painter: tuple[Any, ScriptSession],
    manifest: dict[str, Any],
    assets: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OCIO")
    with pytest.raises(RecorderError, match="start Painter with OCIO"):
        record(painter, manifest, assets, tmp_path)
    assert not painter[0].project_open and not (tmp_path / "work").exists()


def test_refuses_when_a_project_is_already_open(
    painter: tuple[Any, ScriptSession], manifest: dict[str, Any], assets: Path, tmp_path: Path
) -> None:
    painter[0].project_open = True
    with pytest.raises(RecorderError, match="already open"):
        record(painter, manifest, assets, tmp_path)


def test_command_records_from_a_manifest_file(
    painter: tuple[Any, ScriptSession],
    manifest: dict[str, Any],
    assets: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.parity.recorder import __main__ as cli

    path = tmp_path / "wand-v1.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("UZP_ORACLE_WORK", str(tmp_path / "work"))
    monkeypatch.setenv("UZP_ORACLE_INBOX", str(tmp_path / "inbox"))
    monkeypatch.setattr(cli, "ScriptSession", lambda *args, **kwargs: painter[1])
    assert cli.main(["record-script", str(path), "--assets-root", str(assets)]) == 0
    assert len(list((tmp_path / "inbox").rglob("READY"))) == 1
    (assets / WAND / "paint/masks/T_base.png").write_bytes(b"changed")
    assert cli.main(["record-script", str(path), "--assets-root", str(assets)]) == 2


def test_manifest_command_writes_the_generated_manifest(assets: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / "wand-v1.json"
    assert script_run.main(["manifest", "--assets-root", str(assets), "--out", str(out)]) == 0
    assert load_script_job(out, assets).golden_id == "phase1/tier1/wand-v1"


# --- the Belt v5 request (phase2.9 item 2.1; decision 192) -----------------------------------

BELT = "_tmp/claude/cintura-v5"
BELT_MESH = "_tmp/claude/cintura-v5/lows/23-Cinto-v5-low.obj"
BELT_STACK = {
    "title": "stand-in belt",
    "groups": [
        {"key": "leather", "name": "Couro", "mask": None},
        {"key": "brass", "name": "Latao", "mask": "M_metal"},
    ],
    "layers": [
        {"id": "L01", "group": "leather", "name": "Base", "mask": None, "base_tex": "T_belt"},
        {"id": "L02", "group": "leather", "name": "Grain", "mask": "M_grain", "base": [60, 45, 36]},
        {"id": "B01", "group": "brass", "name": "Base", "mask": None, "base_tex": "T_belt"},
    ],
}


def make_belt_assets(root: Path) -> Path:
    """A stand-in Assets3D at the waist-v5 round's layout: the committed scripts and stack, and the
    round folder whose arguments file names the mesh, normal and AO; the layer-stack script's route
    guard imports `locate` from `Pipeline/production/run.py` (Assets3D c6b74c2)."""
    write(root / "AGENTS.md", "stand-in asset repository\n")
    windows = str(root).replace("/", "\\")
    scripts = root / "Pipeline/retopology/waist-v5"
    write(
        scripts / "painter_create.py",
        CREATE.replace("__ARGS__", str(root / BELT / "painter_create_args.json")),
    )
    write(
        scripts / "painter_export.py",
        EXPORT.replace("__ARGS__", str(root / BELT / "painter_export_args.json")),
    )
    write(scripts / "stack-belt.json", json.dumps(BELT_STACK))
    stack_script = LAYER_STACK.replace('"Pipeline/qa"', '"Pipeline/production"').replace(
        "from route_check import locate", "from run import locate"
    )
    write(root / "Pipeline/painting/painter_layer_stack.py", stack_script)
    write(root / "Pipeline/production/run.py", ROUTE_CHECK)
    write(root / BELT_MESH, "mtllib 23-Cinto-v5-low.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    write(root / BELT / "lows/23-Cinto-v5-low.mtl", "newmtl 23-Cinto\n")
    write(root / BELT / "bake/23-Cinto_Normal_OpenGL_v5.png", b"normal")
    write(root / BELT / "bake/23-Cinto_AO_v5.png", b"ao")
    for name in ("M_metal", "M_grain", "T_belt"):
        write(root / BELT / "paint/masks-belt" / f"{name}.png", name.encode("ascii"))
    tmp = windows + r"\_tmp\claude\cintura-v5"
    arguments = {
        "mesh": tmp + r"\lows\23-Cinto-v5-low.obj",
        "normal": tmp + r"\bake\23-Cinto_Normal_OpenGL_v5.png",
        "ao": tmp + r"\bake\23-Cinto_AO_v5.png",
        "dst": windows + r"\Creatures\Undead\Skeletal Mage\Models3D\23-Cinto\23-Cinto-v5.spp",
        "name": "23-Cinto",
    }
    write(root / BELT / "painter_create_args.json", json.dumps(arguments))
    export = {"out": tmp + r"\paint\tex-belt-r10", "prefix": "23-Cinto_v5r10"}
    write(root / BELT / "painter_export_args.json", json.dumps(export))
    return root


def test_belt_manifest_pins_the_files_the_round_names(tmp_path: Path) -> None:
    """The mesh, its material library (the OBJ's `mtllib`), the normal and the AO are the files
    the round's arguments file names; the stack is the committed one, its bitmaps (masks and the
    base_tex colour bitmap) come from the round's masks folder, and the sync imports `run`."""
    assets = make_belt_assets(tmp_path / "assets3d")
    manifest = script_run.belt_manifest(assets)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["golden_id"] == "phase2/tier1/belt-v5"
    assert manifest["domain"] == "tier1/pilot/belt-v5"
    paths = {item["input_id"]: item["assets3d_path"] for item in manifest["inputs"]}
    assert paths["belt-mesh"] == BELT_MESH
    assert paths["belt-mesh-mtl"] == f"{BELT}/lows/23-Cinto-v5-low.mtl"
    assert paths["belt-ao"] == f"{BELT}/bake/23-Cinto_AO_v5.png"
    assert paths["belt-stack"] == "Pipeline/retopology/waist-v5/stack-belt.json"
    assert paths["production-run-py"] == "Pipeline/production/run.py"
    sync = manifest["instruction_sequence"]["steps"][1]["args"]
    assert sync["mask_files"] == ["M_grain.png", "M_metal.png", "T_belt.png"]
    assert sync["imports"] == ["production-run-py"]
    kinds = {item["input_id"]: item["kind"] for item in manifest["inputs"]}
    assert kinds["mask-t_belt"] == "image" and kinds["mask-m_metal"] == "mask"
    job = script_job_from_manifest(manifest, assets)
    assert job.sync.imports[0].module == "run"


def test_belt_manifest_lists_every_missing_input(tmp_path: Path, capsys: Any) -> None:
    """Refused, writing nothing, with every missing path listed as JSON (a restore is checked
    file by file); without the arguments file its mesh, normal and AO cannot be named."""
    assets = make_belt_assets(tmp_path / "assets3d")
    (assets / BELT / "paint/masks-belt/T_belt.png").unlink()
    (assets / BELT / "bake/23-Cinto_AO_v5.png").unlink()
    with pytest.raises(script_run.MissingInputs) as refused:
        script_run.belt_manifest(assets)
    assert refused.value.missing == [
        f"{BELT}/bake/23-Cinto_AO_v5.png",
        f"{BELT}/paint/masks-belt/T_belt.png",
    ]
    (assets / BELT / "painter_create_args.json").unlink()
    out = tmp_path / "out" / "belt-v5.json"
    command = ["manifest", "--pilot", "belt", "--assets-root", str(assets), "--out", str(out)]
    assert script_run.main(command) == 2
    assert not out.exists()
    printed = capsys.readouterr().err
    listed = json.loads(printed[printed.index("{") :])["missing"]
    assert listed == [f"{BELT}/paint/masks-belt/T_belt.png", f"{BELT}/painter_create_args.json"]


# --- the Sash v5 request (phase2.9 item 2.1; decision 260) -----------------------------------

SASH_MESH = f"{BELT}/lows/25-Faixa-Cintura-v5-low.obj"
SASH_STACK = {
    "title": "stand-in sash",
    "groups": [
        {"key": "cloth", "name": "Pano", "mask": None},
        {"key": "hem", "name": "Couro das abas", "mask": "M_hem"},
    ],
    "layers": [
        {"id": "S01", "group": "cloth", "name": "Base", "mask": None, "base_tex": "T_sash"},
        {"id": "S02", "group": "cloth", "name": "Weave", "mask": "M_weave", "base": [40, 31, 26]},
        {"id": "H01", "group": "hem", "name": "Base", "mask": None, "base_tex": "T_sash"},
    ],
}


def make_sash_assets(root: Path) -> Path:
    """The waist-v5 stand-in with the round folder's arguments rewritten for the sash: the same
    scripts and round folder, the sash's stack, masks, low and mesh maps."""
    make_belt_assets(root)
    windows = str(root).replace("/", "\\")
    write(root / "Pipeline/retopology/waist-v5/stack-sash.json", json.dumps(SASH_STACK))
    write(root / SASH_MESH, "mtllib 25-Faixa-Cintura-v5-low.mtl\nv 0 0 0\nv 1 0 0\nf 1 2 2\n")
    write(root / BELT / "lows/25-Faixa-Cintura-v5-low.mtl", "newmtl 25-Faixa-Cintura\n")
    write(root / BELT / "bake/25-Faixa-Cintura_Normal_OpenGL_v5.png", b"sash normal")
    write(root / BELT / "bake/25-Faixa-Cintura_AO_v5.png", b"sash ao")
    for name in ("M_hem", "M_weave", "T_sash"):
        write(root / BELT / "paint/masks-sash" / f"{name}.png", name.encode("ascii"))
    tmp = windows + r"\_tmp\claude\cintura-v5"
    arguments = {
        "mesh": tmp + r"\lows\25-Faixa-Cintura-v5-low.obj",
        "normal": tmp + r"\bake\25-Faixa-Cintura_Normal_OpenGL_v5.png",
        "ao": tmp + r"\bake\25-Faixa-Cintura_AO_v5.png",
        "dst": windows + r"\Creatures\Undead\Skeletal Mage\Models3D\25-Faixa-Cintura\x.spp",
        "name": "25-Faixa-Cintura",
    }
    write(root / BELT / "painter_create_args.json", json.dumps(arguments))
    export = {"out": tmp + r"\paint\tex-sash-r8", "prefix": "25-Faixa-Cintura_v5r8"}
    write(root / BELT / "painter_export_args.json", json.dumps(export))
    return root


def test_sash_manifest_pins_the_files_the_round_names(tmp_path: Path) -> None:
    """The sash's request pins the shared waist-v5 scripts and round arguments with the sash's
    stack, masks, low and mesh maps (decision 260)."""
    assets = make_sash_assets(tmp_path / "assets3d")
    manifest = script_run.sash_manifest(assets)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["golden_id"] == "phase2/tier1/sash-v5"
    assert manifest["domain"] == "tier1/pilot/sash-v5"
    paths = {item["input_id"]: item["assets3d_path"] for item in manifest["inputs"]}
    assert paths["sash-mesh"] == SASH_MESH
    assert paths["sash-mesh-mtl"] == f"{BELT}/lows/25-Faixa-Cintura-v5-low.mtl"
    assert paths["sash-ao"] == f"{BELT}/bake/25-Faixa-Cintura_AO_v5.png"
    assert paths["sash-stack"] == "Pipeline/retopology/waist-v5/stack-sash.json"
    assert paths["painter-create-py"] == "Pipeline/retopology/waist-v5/painter_create.py"
    assert "belt-stack" not in paths
    sync = manifest["instruction_sequence"]["steps"][1]["args"]
    assert sync["stack"] == "sash-stack"
    assert sync["mask_files"] == ["M_hem.png", "M_weave.png", "T_sash.png"]
    job = script_job_from_manifest(manifest, assets)
    assert job.sync.imports[0].module == "run"


def test_a_round_folder_holding_another_pieces_arguments_is_refused(tmp_path: Path) -> None:
    """The round folder holds one pair of arguments files, rewritten per piece: the belt's
    request is refused over the sash's arguments, and the sash's over the belt's."""
    assets = make_sash_assets(tmp_path / "assets3d")
    with pytest.raises(RecorderError, match="another piece's arguments"):
        script_run.belt_manifest(assets)
    belt = make_belt_assets(tmp_path / "belt")
    write(belt / "Pipeline/retopology/waist-v5/stack-sash.json", json.dumps(SASH_STACK))
    with pytest.raises(RecorderError, match="`name` is '23-Cinto'"):
        script_run.sash_manifest(belt)


def test_sash_manifest_lists_every_missing_input(tmp_path: Path, capsys: Any) -> None:
    """Today's Assets3D: the round folder is gone, so the command lists both arguments files and
    every bitmap of the sash's stack, and writes nothing."""
    assets = make_sash_assets(tmp_path / "assets3d")
    for path in sorted((assets / BELT).rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    out = tmp_path / "out" / "sash-v5.json"
    command = ["manifest", "--pilot", "sash", "--assets-root", str(assets), "--out", str(out)]
    assert script_run.main(command) == 2
    assert not out.exists()
    printed = capsys.readouterr().err
    assert json.loads(printed[printed.index("{") :])["missing"] == [
        f"{BELT}/paint/masks-sash/M_hem.png",
        f"{BELT}/paint/masks-sash/M_weave.png",
        f"{BELT}/paint/masks-sash/T_sash.png",
        f"{BELT}/painter_create_args.json",
        f"{BELT}/painter_export_args.json",
    ]


def test_manifest_command_stores_every_pinned_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--store` puts every pinned input in the private store (decision 144) and re-resolves it,
    so the request outlives Assets3D `_tmp`: the job then loads with the round folder gone."""
    assets = make_belt_assets(tmp_path / "assets3d")
    store = OracleStore.init(tmp_path / "store")
    monkeypatch.setenv(STORE_ENV, str(store.root))
    out = tmp_path / "out" / "belt-v5.json"
    command = ["manifest", "--pilot", "belt", "--assets-root", str(assets), "--out", str(out)]
    assert script_run.main([*command, "--store"]) == 0
    manifest = load_json(out)
    for item in manifest["inputs"]:
        assert store.resolve(item["input_id"], item["sha256"]).path is not None
    for path in sorted((assets / BELT).rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    job = load_script_job(out, assets, store)
    assert job.inputs["mask-t_belt"].file.is_relative_to(store.root)


# --- the committed manifest against the real asset repository --------------------------------


def test_committed_manifest_matches_the_real_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every pin of the committed R9 manifest resolves, in Assets3D or in the owner's private
    store (decision 144), and the generator writes the same manifest over the pinned files."""
    monkeypatch.undo()  # the owner's store, read only
    if not (REAL_ASSETS / "AGENTS.md").is_file():
        pytest.skip(f"the UzmiGames asset repository is not at {REAL_ASSETS}")
    committed = load_json(COMMITTED)
    assert validation_errors(committed, Schema.GOLDEN_PUBLIC) == []
    job = load_script_job(COMMITTED, REAL_ASSETS, locate_store())
    assert job.sync.args["command"] == "sync"
    pinned = tmp_path / "pinned"
    script_run.stage_inputs(job, pinned)
    assert {**committed, "private_records": []} == wand_manifest(pinned)


# --- a closing config export: the Wand float request (decision 283) --------------------------

ENVELOPE = REPO_ROOT / "parity/envelopes/painter-12.1.5_js-api.1.1.20"
FLOAT_GOLDEN = "phase1/tier1/wand-v1-float.json"


def with_config_export(
    manifest: dict[str, Any], repo: Path, texture_set: str, name: str = "W_v1_Height_f32"
) -> dict[str, Any]:
    """The stand-in manifest closed by a config export of its Height as OpenEXR 32f."""
    config = {
        "exportShaderParams": False,
        "defaultExportPreset": "f32",
        "exportPresets": [
            {
                "name": "f32",
                "maps": [
                    {
                        "fileName": name,
                        "channels": [
                            {
                                "destChannel": "L",
                                "srcChannel": "L",
                                "srcMapType": "documentMap",
                                "srcMapName": "height",
                            }
                        ],
                    }
                ],
            }
        ],
        "exportList": [{"rootPath": texture_set}],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": "exr",
                    "bitDepth": "32f",
                    "sizeLog2": 11,
                    "paddingAlgorithm": "infinite",
                    "dithering": False,
                }
            }
        ],
    }
    write(repo / "fixtures/config.json", json.dumps(config))
    changed = copy.deepcopy(manifest)
    changed["inputs"].append(
        {
            "input_id": "float-config",
            "kind": "recipe_json",
            "path": "fixtures/config.json",
            "sha256": hashlib.sha256((repo / "fixtures/config.json").read_bytes()).hexdigest(),
            "provenance": {"origin": "uzmigames_authored", "licence": "Apache-2.0"},
        }
    )
    changed["instruction_sequence"]["steps"].append(
        {"step": 4, "call": CONFIG_EXPORT, "args": {"config": "float-config"}}
    )
    assert validation_errors(changed, Schema.GOLDEN_PUBLIC) == []
    return changed


def test_a_closing_config_export_follows_every_script_export(
    painter: tuple[Any, ScriptSession], manifest: dict[str, Any], assets: Path, tmp_path: Path
) -> None:
    world, session = painter
    changed = with_config_export(manifest, tmp_path / "repo", world.texture_set)
    job = script_job_from_manifest(changed, assets, repo_root=tmp_path / "repo")
    assert job.config_export is not None and job.config_export.step == 4
    run = record_script_golden(session, job, tmp_path / "work", tmp_path / "inbox")

    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    for recording in data["recordings"]:
        maps = {o["map"]: o for o in recording["outputs"] if o["kind"] == "exported_map"}
        assert sorted(maps) == ["W_v1_BaseColor", "W_v1_Height", "W_v1_Height_f32"]
        assert maps["W_v1_Height_f32"]["export_settings"]["step"] == 4
        assert maps["W_v1_Height"]["export_settings"]["step"] == 3
        readbacks = [o for o in recording["outputs"] if o["output_id"] == "export/s4"]
        assert len(readbacks) == 1 and readbacks[0]["call"] == CONFIG_EXPORT
        files = [f for t in readbacks[0]["value"]["textures"] for f in t["files"]]
        # A fresh directory of its own, next to the script's export of the same recording.
        assert [Path(f).parent.parent.name for f in files] == ["config"]
        assert Path(files[0]).parent.parent.parent.name == recording["recording_id"]


def test_two_exports_writing_maps_of_one_name_are_refused(
    painter: tuple[Any, ScriptSession], manifest: dict[str, Any], assets: Path, tmp_path: Path
) -> None:
    world, session = painter
    changed = with_config_export(manifest, tmp_path / "repo", world.texture_set, "W_v1_Height")
    job = script_job_from_manifest(changed, assets, repo_root=tmp_path / "repo")
    with pytest.raises(RecorderError, match="maps of the same name"):
        record_script_golden(session, job, tmp_path / "work", tmp_path / "inbox")


def test_job_refuses_a_repository_input_no_config_export_names(
    assets: Path, manifest: dict[str, Any], tmp_path: Path
) -> None:
    changed = with_config_export(manifest, tmp_path / "repo", "uzp_plane")
    del changed["instruction_sequence"]["steps"][3]
    with pytest.raises(RecorderError, match="only the configuration of a closing"):
        script_job_from_manifest(changed, assets, repo_root=tmp_path / "repo")


def test_job_refuses_a_config_export_before_the_script_export(
    assets: Path, manifest: dict[str, Any], tmp_path: Path
) -> None:
    changed = with_config_export(manifest, tmp_path / "repo", "uzp_plane")
    steps = changed["instruction_sequence"]["steps"]
    steps[2]["call"], steps[3]["call"] = steps[3]["call"], steps[2]["call"]
    steps[2]["args"], steps[3]["args"] = steps[3]["args"], steps[2]["args"]
    with pytest.raises(RecorderError, match="only the configuration of a closing"):
        script_job_from_manifest(changed, assets, repo_root=tmp_path / "repo")


def test_job_refuses_a_config_whose_bytes_differ_from_the_pin(
    assets: Path, manifest: dict[str, Any], tmp_path: Path
) -> None:
    changed = with_config_export(manifest, tmp_path / "repo", "uzp_plane")
    (tmp_path / "repo/fixtures/config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RecorderError, match="not the pinned bytes"):
        script_job_from_manifest(changed, assets, repo_root=tmp_path / "repo")


def test_committed_float_golden_replays_the_wand_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The float golden (its request until admitted) holds the Wand v1 golden's inputs, steps and
    settings unchanged, then the config export; the generator writes it over the pinned files."""
    monkeypatch.undo()  # the owner's store, read only
    if not (REAL_ASSETS / "AGENTS.md").is_file():
        pytest.skip(f"the UzmiGames asset repository is not at {REAL_ASSETS}")
    admitted = ENVELOPE / "manifests" / FLOAT_GOLDEN
    path = admitted if admitted.is_file() else ENVELOPE / "requests" / FLOAT_GOLDEN
    committed, wand = load_json(path), load_json(COMMITTED)
    assert committed["inputs"][:-1] == wand["inputs"]
    assert committed["instruction_sequence"]["steps"][:3] == wand["instruction_sequence"]["steps"]
    assert committed["applied_settings"][:-1] == wand["applied_settings"]
    job = load_script_job(path, REAL_ASSETS, locate_store())
    assert job.config_export is not None
    parameters = job.config_export.config["exportParameters"][0]["parameters"]
    assert parameters == {
        "fileFormat": "exr",
        "bitDepth": "32f",
        "sizeLog2": 11,
        "paddingAlgorithm": "infinite",
        "dithering": False,
    }
    pinned = tmp_path / "pinned"
    script_run.stage_inputs(job, pinned)
    assert {**committed, "private_records": []} == wand_float_manifest(pinned)


def test_committed_normal_float_golden_preserves_authorship_and_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regenerate the admitted request from pinned authored inputs, never oracle pixels."""
    monkeypatch.undo()  # the owner's store, read only
    if not (REAL_ASSETS / "AGENTS.md").is_file():
        pytest.skip(f"the UzmiGames asset repository is not at {REAL_ASSETS}")
    path = ENVELOPE / "manifests/phase1/tier1/wand-v1-normal-float.json"
    committed, wand = load_json(path), load_json(COMMITTED)
    assert committed["inputs"][:-1] == wand["inputs"]
    assert committed["instruction_sequence"]["steps"][:3] == wand["instruction_sequence"]["steps"]
    assert committed["applied_settings"][:-1] == wand["applied_settings"]
    job = load_script_job(path, REAL_ASSETS, locate_store())
    assert job.config_export is not None
    config = job.config_export.config
    assert config["exportParameters"][0]["parameters"] == {
        "fileFormat": "exr",
        "bitDepth": "32f",
        "sizeLog2": 11,
        "paddingAlgorithm": "infinite",
        "dithering": False,
    }
    maps = config["exportPresets"][0]["maps"]
    assert [m["fileName"] for m in maps] == [
        "11-Varinha-Madeira_v1r2_Normal_f32",
        "11-Varinha-Madeira_v1r2_NormalChannel_f32",
        "11-Varinha-Madeira_v1r2_NormalMesh_f32",
    ]
    assert [
        [
            (c["destChannel"], c["srcChannel"], c["srcMapType"], c["srcMapName"])
            for c in m["channels"]
        ]
        for m in maps
    ] == [
        [(c, c, kind, name) for c in "RGB"]
        for kind, name in (
            ("virtualMap", "Normal_OpenGL"),
            ("documentMap", "normal"),
            ("meshMap", "normal_base"),
        )
    ]
    pinned = tmp_path / "pinned"
    script_run.stage_inputs(job, pinned)
    assert {**committed, "private_records": []} == wand_normal_float_manifest(pinned)
    assert script_run.PILOTS["wand-normal-float"] is wand_normal_float_manifest
