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


# --- a current round's sync: typed options, the import closure, the project probe ------------

CURRENT_LAYER_STACK = """'''Stand-in of painter_layer_stack.py at Assets3D 1c9a312a.
A project probe, then the route guard's probe for the texture set (from run.py's `locate` and
`owner_preview_paint`); the resource prefix, group and texture set options.'''
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'AGENTS.md').exists())
CLIENT = ROOT / 'Pipeline/mcp/painter_mcp_client.py'
sys.path.insert(0, str(ROOT / 'Pipeline/production'))
from run import MARK, locate, owner_preview_paint  # noqa: E402

PROJECT_PROBE_CODE = '''
import substance_painter.project as project
result = {'project': project.file_path() if project.is_open() else None}
'''

GUARD_CODE = '''
import substance_painter.project as project
name = __TS__
result = {'project': project.file_path(), 'texture_set': name}
'''

SYNC_CODE = '''
import base64, json
import substance_painter.project as project
D = json.loads(base64.b64decode('__DATA__').decode('utf-8'))
result = {'project': project.file_path(), 'imported': sorted(D['masks']),
          'options': D['options'], 'argv': D['argv'], 'run_mark': D['run_mark'],
          'resources': {k: 'resource://fake/' + k for k in D['masks']}}
'''


def execute(code, token=None):
    command = [sys.executable, str(CLIENT), 'execute_python', code]
    env = dict(os.environ, UZ_ROUTE_TOKEN=token or '')
    run = subprocess.run(command, capture_output=True, text=True, env=env)
    return json.loads(run.stdout)['data']


def route_guard(texture_set, mode):
    probe = execute(PROJECT_PROBE_CODE)
    if not probe.get('project'):
        raise SystemExit('ROUTE BLOCKED: save the Painter project inside the piece folder first')
    state, state_path = locate(probe['project'])
    if state == 'legacy' or owner_preview_paint(probe['project']):
        execute(GUARD_CODE.replace('__TS__', repr(texture_set)))
        return None
    if state != 'production':
        raise SystemExit('ROUTE BLOCKED: ' + probe['project'] + ' has no production state')
    execute(GUARD_CODE.replace('__TS__', repr(texture_set)), 'attempt-token')
    return 'attempt-token'


def sync(a):
    stack = json.loads(Path(a.stack).read_text(encoding='utf-8'))
    masks_dir = Path(a.masks).resolve()
    names = {x['mask'] for x in stack['layers'] + stack['groups'] if x.get('mask')}
    names = sorted(names | {x['base_tex'] for x in stack['layers'] if x.get('base_tex')})
    masks = {n: hashlib.sha1((masks_dir / (n + '.png')).read_bytes()).hexdigest() for n in names}
    options = {'prefix': a.resource_prefix, 'group': a.resource_group,
               'texture_set': a.texture_set}
    data = {'masks': masks, 'options': options, 'argv': sys.argv[1:], 'run_mark': MARK}
    encoded = base64.b64encode(json.dumps(data).encode('utf-8')).decode('ascii')
    token = route_guard(a.texture_set, 'sync')
    reply = execute(SYNC_CODE.replace('__DATA__', encoded), token)
    Path(a.state).write_text(json.dumps(reply['resources']), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('sync')
    s.add_argument('--stack', required=True)
    s.add_argument('--masks', required=True)
    s.add_argument('--state', required=True)
    s.add_argument('--resource-prefix', default='stack_')
    s.add_argument('--resource-group', default='layer_stack')
    s.add_argument('--texture-set')
    args = parser.parse_args()
    {'sync': sync}[args.command](args)


if __name__ == '__main__':
    main()
"""

RUN_PY = """'''Stand-in of run.py at Assets3D 1c9a312a: two local helpers imported at import time,
relative first, then absolute.'''
from __future__ import annotations

from pathlib import Path

try:
    from .decision_evidence import build
    from .stage_review_evidence import collect
except ImportError:
    from decision_evidence import build
    from stage_review_evidence import collect

MARK = build() + '+' + collect()


def locate(path):
    path = Path(path).resolve()
    for folder in [path, *path.parents]:
        if (folder / 'Concept').is_dir() and (folder / 'Project').is_dir():
            state = folder / 'Project' / 'production.json'
            return ('production', state) if state.exists() else ('missing', state)
    return ('legacy', None)


def owner_preview_paint(path):
    import colorsys  # noqa: F401  (inside a function: not an import-time import)

    return False
"""

DECISION_EVIDENCE = """'''Stand-in helper of run.py: the standard library only at import.'''
import hashlib


def build():
    return 'decision-evidence-pinned'
"""

STAGE_REVIEW_EVIDENCE = """'''Stand-in helper of run.py: the standard library only at import.'''
import json


def collect():
    return 'stage-review-pinned'
"""

PRODUCTION = "Pipeline/production"
CLOSURE = (
    ("production-run-py", f"{PRODUCTION}/run.py", RUN_PY),
    ("decision-evidence-py", f"{PRODUCTION}/decision_evidence.py", DECISION_EVIDENCE),
    ("stage-review-evidence-py", f"{PRODUCTION}/stage_review_evidence.py", STAGE_REVIEW_EVIDENCE),
)
CURRENT_OPTIONS = {
    "resource_prefix": "v5f_",
    "resource_group": "faixa25_v5",
    "texture_set": "25-Faixa-Cintura",
}
LAYER_STACK_PATH = "Pipeline/painting/painter_layer_stack.py"


def current_manifest(assets: Path) -> dict[str, Any]:
    """The stand-in Wand manifest with the current-round sync: the 1c9a312a-shaped script, its
    import of `run` and run's two helpers, the typed options and the masks by folder."""
    manifest = wand_manifest(assets)
    write(assets / LAYER_STACK_PATH, CURRENT_LAYER_STACK)
    for _, path, text in CLOSURE:
        write(assets / path, text)
    manifest["inputs"] = [
        *(i for i in manifest["inputs"] if i["input_id"] != "route-check-py"),
        *(script_run.assets3d_input(i, "pipeline_script", p, assets) for i, p, _ in CLOSURE),
    ]
    args = manifest["instruction_sequence"]["steps"][1]["args"]
    del args["masks"], args["mask_files"]
    args.update(
        mask_folder=f"{WAND}/paint/masks",
        imports=["production-run-py"],
        import_closure=["decision-evidence-py", "stage-review-evidence-py"],
        **CURRENT_OPTIONS,
    )
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    return wand_manifest_unchecked(manifest, assets)


def test_a_legacy_sync_keeps_its_command_line_and_imports(
    manifest: dict[str, Any], assets: Path
) -> None:
    """No option, no closure: the legacy `--stack --masks --state` command line, the masks of the
    lists, and the imports loaded as named."""
    job = script_job_from_manifest(manifest, assets)
    assert job.sync.options == ()
    assert job.sync.load_order == job.sync.imports
    assert [m.input_id for m in job.sync.masks] == manifest["instruction_sequence"]["steps"][1][
        "args"
    ]["masks"]


def test_a_legacy_sync_script_without_the_flag_refuses_the_option(
    manifest: dict[str, Any], assets: Path
) -> None:
    changed = copy.deepcopy(manifest)
    changed["instruction_sequence"]["steps"][1]["args"]["resource_prefix"] = "v5f_"
    with pytest.raises(RecorderError, match="defines no --resource-prefix option"):
        script_job_from_manifest(changed, assets)


def test_current_sync_passes_the_options_and_runs_the_pinned_closure(
    painter: tuple[Any, ScriptSession],
    assets: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact command line with the three options, the probe and the guard for that texture
    set, and run.py with its two helpers loaded from their pinned bytes before it: decoy modules
    and a live helper on `sys.path` are never used, and both are as before afterwards."""
    manifest = current_manifest(assets)
    job = script_job_from_manifest(manifest, assets)
    assert [m.input_id for m in job.sync.load_order] == [
        "decision-evidence-py",
        "stage-review-evidence-py",
        "production-run-py",
    ]
    assert job.sync.options == (
        ("--resource-prefix", "v5f_"),
        ("--resource-group", "faixa25_v5"),
        ("--texture-set", "25-Faixa-Cintura"),
    )
    live = tmp_path / "live"
    write(live / "decision_evidence.py", "def build():\n    return 'LIVE'\n")
    monkeypatch.syspath_prepend(str(live))
    decoys = {name: types.ModuleType(name) for name in ("run", "decision_evidence")}
    for name, module in decoys.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "stage_review_evidence", raising=False)
    path = list(sys.path)
    run = record(painter, manifest, assets, tmp_path)

    assert all(sys.modules[name] is module for name, module in decoys.items())
    assert "stage_review_evidence" not in sys.modules and sys.path == path
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    synced = next(
        o["value"]
        for r in data["recordings"]
        for o in r["outputs"]
        if o["output_id"] == "script/s2"
    )
    assert synced["run_mark"] == "decision-evidence-pinned+stage-review-pinned"
    assert synced["options"] == {
        "prefix": "v5f_",
        "group": "faixa25_v5",
        "texture_set": "25-Faixa-Cintura",
    }
    argv = synced["argv"]
    assert argv[0] == "sync" and argv[1::2][:3] == ["--stack", "--masks", "--state"]
    assert argv[7:] == [
        "--resource-prefix",
        "v5f_",
        "--resource-group",
        "faixa25_v5",
        "--texture-set",
        "25-Faixa-Cintura",
    ]
    assert synced["imported"] == ["M_iron", "M_wood", "T_base"]


def test_a_mask_folder_carries_more_bitmaps_than_a_schema_list_holds(assets: Path) -> None:
    """The public schema bounds a list at 16 items and the sash has 20 bitmaps: as parallel lists
    they fail the schema, by folder they pass it and all 20 load as the sync's masks."""
    names = [f"M_m{i:02d}" for i in range(19)] + ["T_base"]
    stack = {
        "title": "twenty bitmaps",
        "groups": [{"key": "g", "name": "G", "mask": None}],
        "layers": [
            *(
                {"id": f"L{i:02d}", "group": "g", "name": n, "mask": n}
                for i, n in enumerate(names[:-1])
            ),
            {"id": "B", "group": "g", "name": "Base", "mask": None, "base_tex": "T_base"},
        ],
    }
    manifest = current_manifest(assets)
    write(assets / WAND / "paint/stack-wand.json", json.dumps(stack))
    for name in names:
        write(assets / WAND / "paint/masks" / f"{name}.png", name.encode("ascii"))
    masks = script_run.mask_inputs(f"{WAND}/paint/masks", names, assets)
    manifest["inputs"] = [
        *(i for i in manifest["inputs"] if not i["input_id"].startswith("mask-")),
        *masks,
    ]
    manifest = wand_manifest_unchecked(manifest, assets)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    job = script_job_from_manifest(manifest, assets)
    assert [m.input_id for m in job.sync.masks] == sorted(m["input_id"] for m in masks)
    assert len(job.sync.masks) == 20
    lists = copy.deepcopy(manifest)
    args = lists["instruction_sequence"]["steps"][1]["args"]
    del args["mask_folder"]
    args["masks"] = [m["input_id"] for m in masks]
    args["mask_files"] = [f"{name}.png" for name in names]
    assert validation_errors(lists, Schema.GOLDEN_PUBLIC)


def repinned(manifest: dict[str, Any], assets: Path, path: str, text: str) -> dict[str, Any]:
    write(assets / path, text)
    return wand_manifest_unchecked(manifest, assets)


def with_sync_args(manifest: dict[str, Any], **args: Any) -> dict[str, Any]:
    changed = copy.deepcopy(manifest)
    changed["instruction_sequence"]["steps"][1]["args"].update(args)
    return changed


def with_input(
    manifest: dict[str, Any], assets: Path, input_id: str, kind: str, path: str, text: str
) -> dict[str, Any]:
    write(assets / path, text)
    changed = copy.deepcopy(manifest)
    changed["inputs"].append(script_run.assets3d_input(input_id, kind, path, assets))
    return changed


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        (lambda m, a: with_sync_args(m, texture_set="../x"), r"`texture_set` must match"),
        (lambda m, a: with_sync_args(m, resource_prefix=5), r"`resource_prefix` must match"),
        (
            lambda m, a: with_sync_args(m, import_closure=["decision-evidence-py"]),
            r"run\.py line \d+ imports stage_review_evidence when imported, which is neither .*"
            r"\(Pipeline/production/stage_review_evidence\.py\)",
        ),
        (
            lambda m, a: repinned(
                m, a, f"{PRODUCTION}/run.py", RUN_PY + "\nfrom .decision_evidence import build\n"
            ),
            r"run\.py line \d+ imports \.decision_evidence outside a `try` that catches",
        ),
        (
            lambda m, a: repinned(
                m,
                a,
                f"{PRODUCTION}/run.py",
                RUN_PY.replace("except ImportError:", "except ModuleNotFoundError:"),
            ),
            r"imports \.decision_evidence outside a `try` that catches ImportError",
        ),
        (
            lambda m, a: with_sync_args(
                m, import_closure=["decision-evidence-py", "decision-evidence-py"]
            ),
            "name a module twice",
        ),
        (
            lambda m, a: with_sync_args(
                with_input(
                    m,
                    a,
                    "unrelated-py",
                    "pipeline_script",
                    f"{PRODUCTION}/unrelated.py",
                    "import os\n",
                ),
                import_closure=["decision-evidence-py", "stage-review-evidence-py", "unrelated-py"],
            ),
            r"names \['unrelated-py'\], which no pinned import imports",
        ),
        (
            lambda m, a: repinned(
                m,
                a,
                f"{PRODUCTION}/stage_review_evidence.py",
                "import numpy\n\n\ndef collect():\n    return 'x'\n",
            ),
            r"stage_review_evidence\.py line 1 imports numpy when imported",
        ),
        (
            lambda m, a: repinned(
                m,
                a,
                f"{PRODUCTION}/stage_review_evidence.py",
                "from run import locate\n\n\ndef collect():\n    return 'x'\n",
            ),
            "form a cycle",
        ),
        (
            lambda m, a: with_sync_args(
                with_input(
                    m,
                    a,
                    "unrelated-py",
                    "pipeline_script",
                    "Pipeline/qa/stage_review_evidence.py",
                    "import os\n",
                ),
                import_closure=["decision-evidence-py", "unrelated-py"],
            ),
            r"imports stage_review_evidence when imported.*\(Pipeline/production/",
        ),
        (
            lambda m, a: with_input(
                m, a, "mask-notes", "recipe_json", f"{WAND}/paint/masks/notes.json", "{}"
            ),
            r"the mask folder .* also holds \['mask-notes'\]",
        ),
        (
            lambda m, a: {
                **m,
                "inputs": [i for i in m["inputs"] if i["input_id"] != "mask-t_base"],
            },
            "references the bitmaps",
        ),
    ],
)
def test_a_current_sync_refuses_a_wrong_option_closure_or_mask_folder(
    assets: Path, change: Any, refusal: str
) -> None:
    """Refused when the job loads, before Painter: an option of another shape, a missing,
    duplicate, unreachable, unpinned (import-time third-party), cyclic or misplaced module, a mask
    folder holding another input, or one missing a bitmap the stack references."""
    manifest = current_manifest(assets)
    assert script_job_from_manifest(manifest, assets).sync.options
    with pytest.raises(RecorderError, match=refusal):
        script_job_from_manifest(change(manifest, assets), assets)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # the probe is not sent: the guard probe twice instead
        (
            "probe = execute(PROJECT_PROBE_CODE)",
            "probe = execute(GUARD_CODE.replace('__TS__', 'None'))",
        ),
        # the guard is sent for another texture set than the command line's
        ("token = route_guard(a.texture_set, 'sync')", "token = route_guard(None, 'sync')"),
    ],
)
def test_a_current_sync_refuses_probes_other_than_its_own(
    painter: tuple[Any, ScriptSession], assets: Path, tmp_path: Path, old: str, new: str
) -> None:
    manifest = current_manifest(assets)
    assert old in CURRENT_LAYER_STACK
    changed = repinned(manifest, assets, LAYER_STACK_PATH, CURRENT_LAYER_STACK.replace(old, new))
    with pytest.raises(RecorderError, match=r"sync ran \d Painter calls, not its route guard's 2"):
        record(painter, changed, assets, tmp_path)
    assert not list((tmp_path / "work").rglob("sync-state.json"))


@pytest.mark.parametrize(
    ("helper", "live"),
    [
        # a dynamic import static resolution cannot see
        ("import importlib\n\nimportlib.import_module('uzp_live_helper')\n", "uzp_live_helper"),
        # a standard-library name a live file on `sys.path` shadows
        ("import colorsys\n", "colorsys"),
        # a live submodule added to a standard-library package's `__path__`
        (
            "import importlib\nimport xml\n\nxml.__path__.insert(0, __LIVE__)\n"
            "importlib.import_module('xml.uzp_live_sub')\n",
            "xml.uzp_live_sub",
        ),
    ],
)
def test_a_current_sync_never_loads_a_live_module(
    painter: tuple[Any, ScriptSession],
    assets: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    helper: str,
    live: str,
) -> None:
    """The closure passes, but at run time a helper imports a module that is neither pinned nor
    the standard library: refused before the sync code reaches Painter, the live file never
    runs, and `sys.meta_path` is as before."""
    import xml

    manifest = current_manifest(assets)
    folder = tmp_path / "live"
    text = helper.replace("__LIVE__", repr(str(folder)))
    text += "\n\ndef collect():\n    return 'stage-review-pinned'\n"
    changed = repinned(manifest, assets, f"{PRODUCTION}/stage_review_evidence.py", text)
    write(folder / f"{live.rpartition('.')[2]}.py", "raise AssertionError('the live module ran')\n")
    monkeypatch.syspath_prepend(str(folder))
    monkeypatch.setattr(xml, "__path__", list(xml.__path__))  # restored after the test
    monkeypatch.delitem(sys.modules, live, raising=False)
    finders = list(sys.meta_path)
    with pytest.raises(RecorderError, match=rf"the pinned sync imports \['{live}'\]"):
        record(painter, changed, assets, tmp_path)
    assert live not in sys.modules and sys.meta_path == finders
    assert not list((tmp_path / "work").rglob("sync-state.json"))


def test_a_refused_current_sync_restores_the_modules_and_path(
    painter: tuple[Any, ScriptSession],
    assets: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inside a production character's layout the guard returns an attempt token: refused, and
    `sys.modules` and `sys.path` are as before."""
    manifest = current_manifest(assets)
    (tmp_path / "Concept").mkdir()
    (tmp_path / "Project").mkdir()
    (tmp_path / "Project" / "production.json").write_text("{}", encoding="utf-8")
    decoy = types.ModuleType("decision_evidence")
    monkeypatch.setitem(sys.modules, "decision_evidence", decoy)
    monkeypatch.delitem(sys.modules, "run", raising=False)
    path = list(sys.path)
    with pytest.raises(RecorderError, match="attempt token"):
        record(painter, manifest, assets, tmp_path)
    assert sys.modules["decision_evidence"] is decoy and "run" not in sys.modules
    assert sys.path == path


# --- a native job: the recorder's own create, the sync with an override, the config export ----

TUNIC_SET = "DefaultMaterial"
NATIVE_ARGS: dict[str, Any] = {
    "mesh": "wand-mesh",
    "mesh_material_library": "wand-mesh-mtl",
    "normal": "wand-normal",
    "texture_set": TUNIC_SET,
    "normal_name": "Tunic_v6_HighNormal",
    "normal_group": "tunica18_v10c_mesh_maps",
    "normal_map_format": "OpenGL",
    "tangent_space_mode": "PerFragment",
    "project_workflow": "Default",
    "default_texture_resolution": 4096,
    "import_cameras": False,
    "mesh_unit_scale": 1.0,
}
REPORT_PATH = "Creatures/stand-in/18-Tunica/report.json"
RECIPE_KEYS = ["painting_v10", "painter_stack_recipe"]
OVERRIDE = {"override_layer": "C02", "override_mask": "M_iron"}  # the stand-in's F03


def recipe_of(stack: dict[str, Any]) -> dict[str, Any]:
    """The recipe the override applies to: the stack with C02 binding its older mask."""
    recipe = copy.deepcopy(stack)
    next(x for x in recipe["layers"] if x["id"] == "C02")["mask"] = "M_iron_v9"
    return recipe


def native_manifest(assets: Path, repo: Path) -> dict[str, Any]:
    """A Tunic-shaped native job over the stand-in Wand: the native create, the current-round
    sync with the C02 override of the recipe, and the closing config export only."""
    current = current_manifest(assets)
    write(
        assets / REPORT_PATH,
        json.dumps({"painting_v10": {"painter_stack_recipe": recipe_of(STACK)}}),
    )
    dropped = {
        "painter-create-py",
        "painter-export-py",
        "painter-create-args",
        "painter-export-args",
        "wand-ao",
    }
    inputs = [i for i in current["inputs"] if i["input_id"] not in dropped]
    inputs.append(script_run.assets3d_input("tunic-report", "recipe_json", REPORT_PATH, assets))
    sync = {
        **current["instruction_sequence"]["steps"][1]["args"],
        "recipe": "tunic-report",
        "recipe_keys": RECIPE_KEYS,
        **OVERRIDE,
        # the Tunic's sync options: one texture set, the created project's
        "resource_prefix": "v10c_",
        "resource_group": "tunica18_v10c",
        "texture_set": TUNIC_SET,
    }
    with_config = with_config_export(current, repo, TUNIC_SET, "DefaultMaterial_Displacement_Raw")
    config = next(i for i in with_config["inputs"] if i["input_id"] == "float-config")
    manifest = copy.deepcopy(current)
    manifest["inputs"] = [*inputs, config]
    manifest["instruction_sequence"]["steps"] = [
        {"step": 1, "call": script_run.NATIVE_CREATE, "args": dict(NATIVE_ARGS)},
        {"step": 2, "call": RUN_SCRIPT, "args": sync},
        {"step": 3, "call": CONFIG_EXPORT, "args": {"config": "float-config"}},
    ]
    return manifest


@pytest.fixture
def native_assets(tmp_path: Path) -> Path:
    """A stand-in asset repository of its own: the native job rewrites its sync script."""
    return make_assets(tmp_path / "native-assets")


@pytest.fixture
def native(native_assets: Path, tmp_path: Path) -> dict[str, Any]:
    return native_manifest(native_assets, tmp_path / "repo")


def native_job(manifest: dict[str, Any], assets: Path, tmp_path: Path) -> script_run.NativeJob:
    job = script_run.pipeline_job_from_manifest(manifest, assets, repo_root=tmp_path / "repo")
    assert isinstance(job, script_run.NativeJob)
    return job


def test_a_native_manifest_is_valid_under_the_one_new_call(native: dict[str, Any]) -> None:
    """Depends on Codex root's approval of the schema change (one enum value,
    `substance_painter.project.create`, under `uzmigames_pipeline_scripts`): the Tunic-shaped
    native manifest validates; any other documented call there still does not."""
    assert validation_errors(native, Schema.GOLDEN_PUBLIC) == []
    other = copy.deepcopy(native)
    other["instruction_sequence"]["steps"][0]["call"] = "substance_painter.project.open"
    assert validation_errors(other, Schema.GOLDEN_PUBLIC)


def test_a_native_job_creates_binds_only_the_normal_syncs_and_exports_its_config(
    painter: tuple[Any, ScriptSession], native: dict[str, Any], native_assets: Path, tmp_path: Path
) -> None:
    """The exact settings and no template; the one texture set; the Normal imported under its
    name and group and bound alone; the project saved after the sync; r1, r1-repeat and r2 each
    export only the configuration."""
    world, session = painter
    world.texture_set = world.imported_texture_set = TUNIC_SET
    job = native_job(native, native_assets, tmp_path)
    assert job.create.settings == {k: NATIVE_ARGS[k] for k in script_run.NATIVE_SETTINGS}
    run = record_script_golden(session, job, tmp_path / "work", tmp_path / "inbox")

    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    recordings = {r["recording_id"]: r for r in data["recordings"]}
    assert set(recordings) == {"r1", "r1-repeat", "r2"}
    for recorded in recordings.values():
        maps = [o for o in recorded["outputs"] if o["kind"] == "exported_map"]
        assert [m["map"] for m in maps] == ["DefaultMaterial_Displacement_Raw"]
        assert all(m["export_settings"]["config"] == "float-config" for m in maps)
    created = next(o for o in recordings["r1"]["outputs"] if o["output_id"] == "create/s1")
    assert created["call"] == script_run.NATIVE_CREATE
    value = created["value"]
    assert value["requested_settings"] == job.create.settings
    assert value["requested_normal"] == {
        "name": "Tunic_v6_HighNormal",
        "group": "tunica18_v10c_mesh_maps",
    }
    assert value["texture_sets"] == [TUNIC_SET] and len(value["mesh_maps"]) == 10
    bound = {k: v for k, v in value["mesh_maps"].items() if v is not None}
    assert list(bound) == ["Normal"] and bound["Normal"] == value["resource"]
    assert value["resource"]["name"] == "Tunic_v6_HighNormal.image"
    assert [(n, g) for _, n, g in world.named_resources] == [
        ("Tunic_v6_HighNormal", "tunica18_v10c_mesh_maps")
    ]
    assert Path(value["saved"]).name == "native-create.spp"
    synced = next(o for o in recordings["r1"]["outputs"] if o["output_id"] == "script/s2")
    assert synced["value"]["options"] == {
        "prefix": "v10c_",
        "group": "tunica18_v10c",
        "texture_set": TUNIC_SET,
    }
    normal_bytes = (
        native_assets / WAND / "bake/11-Varinha-Madeira_Normal_OpenGL_v1.png"
    ).read_bytes()
    for rid in ("r1", "r2"):  # the slots read again after the sync, and after the reopen
        (slots,) = [
            o for o in recordings[rid]["outputs"] if o["output_id"] == f"create/mesh-maps-{rid}"
        ]
        assert slots["call"] == "substance_painter.textureset.TextureSet.get_mesh_map_resource"
        assert slots["value"]["mesh_maps"]["Normal"] == value["resource"]
        sha1 = hashlib.sha1(normal_bytes).hexdigest()
        assert slots["value"]["normal_pinned_bytes_sha1"] == sha1


def hooked(
    session: ScriptSession, monkeypatch: pytest.MonkeyPatch, operation: str, change: Any
) -> None:
    """`session.call(operation, ...)` returns `change(reply, nth call)` instead of the reply."""
    call = session.call
    seen: list[int] = []

    def wrapped(called: str, /, **args: Any) -> Any:
        reply = call(called, **args)
        if called != operation:
            return reply
        seen.append(1)
        return change(copy.deepcopy(reply), len(seen))

    monkeypatch.setattr(session, "call", wrapped)


def drop_slot(reply: dict[str, Any], nth: int) -> dict[str, Any]:
    del reply["mesh_maps"]["Opacity"]
    return reply


def extra_slot(reply: dict[str, Any], nth: int) -> dict[str, Any]:
    reply["mesh_maps"]["Displacement"] = None
    return reply


def new_version(reply: dict[str, Any], nth: int) -> dict[str, Any]:
    if nth == 2:  # the readback after the reopen
        reply["mesh_maps"]["Normal"]["version"] = "0" * 40 + ".image"
    return reply


def new_slot(reply: dict[str, Any], nth: int) -> dict[str, Any]:
    if nth == 2:
        reply["mesh_maps"]["AO"] = {**reply["mesh_maps"]["Normal"], "name": "baked_AO"}
    return reply


def new_context(reply: dict[str, Any], nth: int) -> dict[str, Any]:
    if nth == 2:  # a reopen may move the resource to another project context only
        normal = reply["mesh_maps"]["Normal"]
        normal["url"] = normal["url"].replace("project0", "project1")
        normal["context"] = "project1"
    return reply


def shelf_context(reply: dict[str, Any], nth: int) -> dict[str, Any]:
    if nth == 2:  # a context other than projectN is part of the identity
        normal = reply["mesh_maps"]["Normal"]
        normal["url"] = normal["url"].replace("project0", "starter_assets")
        normal["context"] = "starter_assets"
    return reply


def swapped(reply: dict[str, Any], nth: int) -> dict[str, Any]:
    """Another resource bound as the Normal after the sync, and still there after the reopen:
    stable from r1 to r2, but not the one the create imported."""
    reply["mesh_maps"]["Normal"] = {
        "url": "resource://project0/Tunic_v6_HighNormal.image?version=other",
        "context": "project0",
        "name": "Tunic_v6_HighNormal.image",
        "version": "other",
    }
    return reply


def renamed(reply: dict[str, Any], nth: int) -> dict[str, Any]:
    """A name sharing the requested name's prefix is another resource."""
    for value in (reply["resource"], reply["mesh_maps"]["Normal"]):
        value["name"] = "Tunic_v6_HighNormal_v2.image"
    return reply


def untyped(reply: dict[str, Any], nth: int) -> dict[str, Any]:
    reply["mesh_maps"]["Normal"]["version"] = 5
    return reply


@pytest.mark.parametrize(
    ("operation", "change", "refusal"),
    [
        ("bind_mesh_map", drop_slot, "not the ten slots"),
        ("bind_mesh_map", extra_slot, "not the ten slots"),
        ("bind_mesh_map", renamed, r"not 'Tunic_v6_HighNormal\.image'"),
        ("bind_mesh_map", untyped, "reads back .*, not a resource or None"),
        ("mesh_maps", drop_slot, "not the ten slots"),
        ("mesh_maps", swapped, "after the sync the Normal is .*, not the imported"),
        ("mesh_maps", new_version, "after the reopen the Normal is .*, not the imported"),
        ("mesh_maps", shelf_context, "after the reopen the Normal is"),
        ("mesh_maps", new_slot, r"mesh maps bound are \['AO', 'Normal'\]"),
        ("mesh_maps", new_context, None),
    ],
)
def test_a_native_job_refuses_slot_readbacks_that_omit_add_or_change(
    painter: tuple[Any, ScriptSession],
    native: dict[str, Any],
    native_assets: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    change: Any,
    refusal: str | None,
) -> None:
    """Every slot readback (the create's, after the sync, after the reopen) must hold exactly the
    ten slots with only the Normal bound; after the reopen the Normal must be the same resource,
    its project context aside."""
    world, session = painter
    world.texture_set = world.imported_texture_set = TUNIC_SET
    job = native_job(native, native_assets, tmp_path)
    hooked(session, monkeypatch, operation, change)
    if refusal is None:
        assert record_script_golden(session, job, tmp_path / "work", tmp_path / "inbox")
        return
    with pytest.raises(RecorderError, match=refusal):
        record_script_golden(session, job, tmp_path / "work", tmp_path / "inbox")


def native_with(native: dict[str, Any], step: int, **args: Any) -> dict[str, Any]:
    changed = copy.deepcopy(native)
    changed["instruction_sequence"]["steps"][step - 1]["args"].update(args)
    return changed


def native_without(native: dict[str, Any], step: int, key: str) -> dict[str, Any]:
    changed = copy.deepcopy(native)
    del changed["instruction_sequence"]["steps"][step - 1]["args"][key]
    return changed


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        (lambda m: native_without(m, 1, "mesh_unit_scale"), r"missing \['mesh_unit_scale'\]"),
        (lambda m: native_with(m, 1, template="pbr"), r"unknown \['template'\]"),
        (
            lambda m: native_with(m, 1, default_texture_resolution=3000),
            "`default_texture_resolution`",
        ),
        (
            lambda m: native_with(m, 1, default_texture_resolution=True),
            "`default_texture_resolution`",
        ),
        (lambda m: native_with(m, 1, import_cameras=None), "`import_cameras`"),
        (lambda m: native_with(m, 1, normal_map_format="Vulkan"), "`normal_map_format`"),
        (lambda m: native_with(m, 1, mesh_unit_scale=0), "`mesh_unit_scale`"),
        (lambda m: native_with(m, 1, normal_group="../x"), "`normal_group` must match"),
        (lambda m: native_with(m, 1, normal="wand-mesh"), "`normal` must be a image input"),
        (lambda m: native_with(m, 1, mesh_material_library="wand-normal"), "must be a mesh input"),
        (lambda m: native_with(m, 2, override_layer="C09"), r"has 0 layers 'C09'"),
        (lambda m: native_with(m, 2, override_mask="M_iron_v9"), "already binds M_iron_v9"),
        (lambda m: native_with(m, 2, override_layer="C01"), "not the recipe with C01 alone"),
        (lambda m: native_without(m, 2, "override_mask"), "an override names all of"),
        (lambda m: native_with(m, 2, recipe_keys=["painting_v9"]), "holds no painting_v9"),
        (lambda m: native_with(m, 2, recipe="wand-normal"), "`recipe` must be a recipe_json"),
        (
            lambda m: native_with(m, 2, texture_set="25-Faixa-Cintura"),
            r"the sync's texture set '25-Faixa-Cintura' is not the created project's",
        ),
        (lambda m: native_without(m, 2, "texture_set"), "the sync's texture set None"),
    ],
)
def test_a_native_job_refuses_a_wrong_create_or_override(
    native: dict[str, Any], native_assets: Path, tmp_path: Path, change: Any, refusal: str
) -> None:
    """Refused when the job loads, before Painter: a setting missing, extra or of another type,
    a name of another shape, an input of another kind; an override naming no layer, changing
    nothing, or leaving the stack other than the recipe with that one layer changed."""
    native_job(native, native_assets, tmp_path)
    with pytest.raises(RecorderError, match=refusal):
        script_run.pipeline_job_from_manifest(
            change(native), native_assets, repo_root=tmp_path / "repo"
        )


def test_a_stack_that_differs_from_the_overridden_recipe_elsewhere_is_refused(
    native: dict[str, Any], native_assets: Path, tmp_path: Path
) -> None:
    recipe = recipe_of(STACK)
    recipe["layers"][1]["base"] = [0.1, 0.1, 0.1]  # C02's colour differs too
    write(
        native_assets / REPORT_PATH, json.dumps({"painting_v10": {"painter_stack_recipe": recipe}})
    )
    changed = copy.deepcopy(native)
    report = next(i for i in changed["inputs"] if i["input_id"] == "tunic-report")
    report["sha256"] = hashlib.sha256((native_assets / REPORT_PATH).read_bytes()).hexdigest()
    with pytest.raises(RecorderError, match="not the recipe with C02 alone binding M_iron"):
        script_run.pipeline_job_from_manifest(changed, native_assets, repo_root=tmp_path / "repo")


@pytest.mark.parametrize(
    ("steps", "refusal"),
    [
        # no config export: a native job's only export is its configuration
        (lambda s: s[:2], "only the configuration of a closing"),
        # a script export besides the config export
        (lambda s: [s[0], s[1], {**s[1], "step": 3}, {**s[2], "step": 4}], "a native job runs"),
        # the native create not first
        (
            lambda s: [{**s[1], "step": 1}, {**s[0], "step": 2}, s[2]],
            r"is not uzmigames\.pipeline\.run_script",
        ),
    ],
)
def test_a_native_job_runs_create_sync_and_config_export_only(
    native: dict[str, Any], native_assets: Path, tmp_path: Path, steps: Any, refusal: str
) -> None:
    changed = copy.deepcopy(native)
    changed["instruction_sequence"]["steps"] = steps(changed["instruction_sequence"]["steps"])
    with pytest.raises(RecorderError, match=refusal):
        script_run.pipeline_job_from_manifest(changed, native_assets, repo_root=tmp_path / "repo")


def test_script_job_loading_refuses_a_native_manifest_by_name(
    native: dict[str, Any], native_assets: Path, tmp_path: Path
) -> None:
    with pytest.raises(RecorderError, match=r"is a native job \(pipeline_job_from_manifest\)"):
        script_job_from_manifest(native, native_assets, repo_root=tmp_path / "repo")


@pytest.mark.parametrize(
    ("prepare", "refusal"),
    [
        (lambda w: setattr(w, "other_texture_sets", ["Extra"]), r"not exactly DefaultMaterial"),
        (
            lambda w: setattr(w, "texture_set", "uzp_plane"),
            r"texture sets are \['uzp_plane'\], not exactly DefaultMaterial",
        ),
    ],
)
def test_a_native_create_refuses_other_texture_sets(
    painter: tuple[Any, ScriptSession],
    native: dict[str, Any],
    native_assets: Path,
    tmp_path: Path,
    prepare: Any,
    refusal: str,
) -> None:
    """The created project must hold exactly the named texture set: nothing is imported or bound
    otherwise, and no sync runs."""
    world, session = painter
    world.texture_set = world.imported_texture_set = TUNIC_SET
    world.other_resolutions = {"Extra": (4096, 4096)}
    prepare(world)
    job = native_job(native, native_assets, tmp_path)
    with pytest.raises(RecorderError, match=refusal):
        record_script_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    assert world.named_resources == []
    assert not list((tmp_path / "work").rglob("sync-state.json"))


def test_a_native_create_refuses_a_second_bound_mesh_map(
    painter: tuple[Any, ScriptSession],
    native: dict[str, Any],
    native_assets: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slot other than the Normal bound after the create (here an AO map left by a bake) is
    refused, before the sync."""
    world, session = painter
    world.texture_set = world.imported_texture_set = TUNIC_SET
    job = native_job(native, native_assets, tmp_path)
    call = session.call

    def with_ao(operation: str, **args: Any) -> Any:
        if operation == "bind_mesh_map":
            world.baked_maps[next(u for u in world.enabled_bakers if u.name == "AO")] = (
                "resource://project0/baked_AO"
            )
        return call(operation, **args)

    monkeypatch.setattr(session, "call", with_ao)
    with pytest.raises(RecorderError, match=r"mesh maps bound are \['AO', 'Normal'\]"):
        record_script_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    assert not list((tmp_path / "work").rglob("sync-state.json"))


def test_record_script_command_records_script_and_native_manifests(
    painter: tuple[Any, ScriptSession],
    manifest: dict[str, Any],
    assets: Path,
    native: dict[str, Any],
    native_assets: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`record-script` loads either job: a script manifest exactly as before (the Wand), and a
    native one."""
    from tools.parity.recorder import __main__ as cli

    world, session = painter
    monkeypatch.setenv("UZP_ORACLE_WORK", str(tmp_path / "work"))
    monkeypatch.setenv("UZP_ORACLE_INBOX", str(tmp_path / "inbox"))
    monkeypatch.setattr(cli, "ScriptSession", lambda *args, **kwargs: session)
    loaded: list[Any] = []
    load = script_run.load_pipeline_job

    def loader(path: Path, assets_root: Path, store: Any = None) -> Any:
        loaded.append(
            script_run.pipeline_job_from_manifest(
                load_json(path), assets_root, store, tmp_path / "repo"
            )
        )
        return loaded[-1]

    script = tmp_path / "wand-v1.json"
    script.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(cli, "load_pipeline_job", load)
    assert cli.main(["record-script", str(script), "--assets-root", str(assets)]) == 0
    monkeypatch.setattr(cli, "load_pipeline_job", loader)
    world.texture_set = world.imported_texture_set = TUNIC_SET
    path = tmp_path / "tunic-current.json"
    path.write_text(json.dumps(native), encoding="utf-8")
    assert cli.main(["record-script", str(path), "--assets-root", str(native_assets)]) == 0
    assert isinstance(loaded[0], script_run.NativeJob)
    assert len(list((tmp_path / "inbox").rglob("READY"))) == 2


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
