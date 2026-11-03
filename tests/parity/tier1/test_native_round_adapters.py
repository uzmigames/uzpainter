"""The UzPainter-side rebuild of a native job (decision 300 item 7, the Tunic current round): the
direct route (`Wand`, and the Tier 1 runner's subject) and the MCP route
(`tests/parity/tier1/mcp_round.py`) reproduce the native create's colour profile, settings and
Normal binding, save after the unchanged sync, check the Normal again before the closing config
export, and refuse by name what they cannot do. Nothing here starts UzPainter or Painter: the
adapter's subprocess is captured, the Painter-side code runs in-process against stand-in modules,
and the MCP round runs against a fake session.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

from python.uzpainter_facade.bitmap_defaults import PAINTER_OCIO_CONFIG_SHA256
from tests.adapters.assets3d import wand as wand_module
from tests.adapters.assets3d.wand import (
    NATIVE_CREATE_CODE,
    NATIVE_EXPORT_CODE,
    NATIVE_SAVE_CODE,
    NativeColourRefused,
    NativeNotCreated,
    NotAScriptJob,
    Wand,
)
from tests.parity.recorder.test_script_run import (
    NATIVE_ARGS,
    TUNIC_SET,
    make_assets,
    native_manifest,
)
from tests.parity.tier1 import mcp_round
from tests.parity.tier1.test_current_round_adapters import CLOSURE_ORDER
from tests.parity.tier1.wand_v1 import runner
from tools.parity.recorder import script_run
from tools.parity.recorder.job import sha256_file
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import STORE_ENV

OPTIONS = [
    "--resource-prefix",
    "v10c_",
    "--resource-group",
    "tunica18_v10c",
    "--texture-set",
    TUNIC_SET,
]
SETTINGS = {key: NATIVE_ARGS[key] for key in script_run.NATIVE_SETTINGS}
SLOTS = sorted(script_run.MESH_MAP_SLOTS)
NORMAL = "Tunic_v6_HighNormal"


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
    return native_manifest(assets, tmp_path / "repo")


def manifest_file(tmp_path: Path, manifest: dict[str, Any], name: str = "native") -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def native_wand(tmp_path: Path, manifest: dict[str, Any]) -> Wand:
    path = manifest_file(tmp_path, manifest)
    return Wand(tmp_path / "UzPainter.exe", tmp_path / "work", path, tmp_path / "repo")


def without_ocio(manifest: dict[str, Any]) -> dict[str, Any]:
    changed = copy.deepcopy(manifest)
    changed["applied_settings"] = [s for s in changed["applied_settings"] if s["name"] != "OCIO"]
    return changed


# --- stand-ins of UzPainter's `substance_painter` and `uzpainter` modules ----------------------


class Identifier:
    """A resource identifier: context, name and version, and its URL."""

    def __init__(self, context: str, name: str, version: str | None = "v1") -> None:
        self.context, self.name, self.version = context, name, version

    def url(self) -> str:
        query = f"?version={self.version}" if self.version else ""
        return f"resource://{self.context}/{self.name}{query}"


class Painter:
    """What the Painter-side code did, and the state it reads: texture sets, bound slots, the
    project's colour management, and what a bind puts in the slot (`swap`, else the import)."""

    def __init__(self, sets: list[str], ocio: str) -> None:
        self.sets = sets
        self.bound: dict[str, Identifier] = {}
        self.colour: dict[str, Any] = {"mode": "ocio", "config_hash": ocio}
        self.swap: Identifier | None = None
        self.calls: list[tuple[Any, ...]] = []
        self.saved: str | None = None


def stand_ins(painter: Painter, monkeypatch: pytest.MonkeyPatch) -> None:
    """`substance_painter.{project,resource,textureset,export}` and `uzpainter` over `painter`."""

    def members(kind: str, *names: str) -> types.SimpleNamespace:
        return types.SimpleNamespace(**{name: f"{kind}.{name}" for name in names})

    class Resource:
        def __init__(self, name: str) -> None:
            self.id = Identifier("project0", name)

        def identifier(self) -> Identifier:
            return self.id

    class Set:
        def __init__(self, name: str) -> None:
            self.set_name = name

        def name(self) -> str:
            return self.set_name

        def set_mesh_map_resource(self, usage: str, identifier: Identifier) -> None:
            painter.calls.append(("bind", self.set_name, usage, identifier.url()))
            painter.bound[usage.rsplit(".", 1)[1]] = painter.swap or identifier

        def get_mesh_map_resource(self, usage: str) -> Identifier | None:
            return painter.bound.get(usage.rsplit(".", 1)[1])

    def create(mesh_file_path: str, settings: types.SimpleNamespace) -> None:
        painter.calls.append(("create", mesh_file_path, vars(settings)))

    def save_as(path: str, mode: str) -> None:
        painter.calls.append(("save_as", path, mode))
        painter.saved = path

    def save(mode: str) -> None:
        painter.calls.append(("save", painter.saved, mode))

    def import_project_resource(path: str, usage: str, name: str, group: str) -> Resource:
        painter.calls.append(("import", path, usage, name, group))
        return Resource(name)

    def export_project_textures(config: dict[str, Any]) -> types.SimpleNamespace:
        painter.calls.append(("export", config))
        files = [f"{config['exportPath']}/{TUNIC_SET}_Height.exr"]
        return types.SimpleNamespace(
            status="ExportStatus.Success", message="", textures={(TUNIC_SET, ""): files}
        )

    project = types.ModuleType("substance_painter.project")
    project.__dict__.update(
        is_open=lambda: False,
        Settings=lambda **given: types.SimpleNamespace(**given),
        NormalMapFormat=members("NormalMapFormat", "OpenGL", "DirectX"),
        TangentSpace=members("TangentSpace", "PerVertex", "PerFragment"),
        ProjectWorkflow=members("ProjectWorkflow", "Default", "TextureSetPerUVTile", "UVTile"),
        ProjectSaveMode=members("ProjectSaveMode", "Full", "Incremental"),
        create=create,
        save_as=save_as,
        save=save,
        file_path=lambda: painter.saved,
    )
    resource = types.ModuleType("substance_painter.resource")
    resource.__dict__.update(
        Usage=members("Usage", "TEXTURE"), import_project_resource=import_project_resource
    )
    textureset = types.ModuleType("substance_painter.textureset")
    textureset.__dict__.update(
        all_texture_sets=lambda: [Set(name) for name in painter.sets],
        TextureSet=types.SimpleNamespace(from_name=Set),
        MeshMapUsage=members("MeshMapUsage", *SLOTS),
    )
    export = types.ModuleType("substance_painter.export")
    export.__dict__.update(export_project_textures=export_project_textures)
    package = types.ModuleType("substance_painter")
    modules = {"project": project, "resource": resource, "textureset": textureset, "export": export}
    for name, module in modules.items():
        setattr(package, name, module)
        monkeypatch.setitem(sys.modules, f"substance_painter.{name}", module)
    monkeypatch.setitem(sys.modules, "substance_painter", package)
    uzpainter = types.ModuleType("uzpainter")
    uzpainter.__dict__.update(
        colormanagement=types.SimpleNamespace(get_color_management=lambda: dict(painter.colour))
    )
    monkeypatch.setitem(sys.modules, "uzpainter", uzpainter)


@pytest.fixture
def painter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Painter:
    """The stand-ins with the one texture set, under an `OCIO` file of its own (the Wands below
    are pointed at its hash: Painter's configuration is not on a test machine)."""
    config = tmp_path / "config.ocio"
    config.write_text("ocio_profile_version: 2\n", encoding="utf-8")
    monkeypatch.setenv("OCIO", str(config))
    found = Painter([TUNIC_SET], sha256_file(config))
    stand_ins(found, monkeypatch)
    return found


def run_code(code: str) -> Any:
    namespace: dict[str, Any] = {"__name__": "painter_side"}
    exec(compile(code, "painter_side", "exec"), namespace)
    return namespace["result"]


def ocio_wand(tmp_path: Path, manifest: dict[str, Any], painter: Painter) -> Wand:
    wand = native_wand(tmp_path, manifest)
    assert wand.ocio_sha256 == PAINTER_OCIO_CONFIG_SHA256
    wand.ocio_sha256 = painter.colour["config_hash"]
    return wand


def created(wand: Wand, painter: Painter) -> Any:
    """The native create run in-process; its result."""
    result = run_code(wand.native_code(NATIVE_CREATE_CODE))
    painter.calls.clear()
    return result


# --- the direct route: the Wand's command lines ------------------------------------------------


def replying(monkeypatch: pytest.MonkeyPatch, baseline: Any) -> list[list[str]]:
    """Every command line the Wand starts, none of them run; the client replies with `baseline`
    as the native create's Normal."""
    calls: list[list[str]] = []

    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        reply = {"success": True, "data": {"normal": baseline}}
        stdout = json.dumps(reply) if command[1] == str(wand_module.CLIENT) else ""
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_a_native_wand_creates_syncs_saves_checks_and_exports_only_its_config(
    native: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client runs the create; the sync keeps the current round's command line and is then
    saved through `run`; the export runs through `run` too, into the Wand's own directory."""
    wand = native_wand(tmp_path, native)
    baseline = {"url": "u", "context": "projectN", "name": NORMAL, "version": "v1"}
    calls = replying(monkeypatch, baseline)
    wand.create()
    wand.sync()
    wand.export()
    job = wand.pipeline
    assert isinstance(job, script_run.NativeJob)
    assert wand.baseline == baseline
    imports = [
        part
        for input_id in CLOSURE_ORDER
        for part in ("--import", f"{wand.staged[input_id]}={job.inputs[input_id].sha256}")
    ]
    head = [sys.executable, str(wand_module.ENTRY), "--diagnostic-import", *wand.pins(), *imports]
    script = str(wand.script("painter-layer-stack-py"))
    work = tmp_path / "work"
    client = [sys.executable, str(wand_module.CLIENT), "execute_python"]
    assert calls == [
        [*client, str(work / "native-create.json")],
        [
            *head,
            script,
            "sync",
            "--stack",
            str(wand.stack),
            "--masks",
            str(wand.masks),
            "--state",
            str(wand.state),
            *OPTIONS,
        ],
        [*head, script, "run", str(work / "native-save.py")],
        [*head, script, "run", str(work / "native-export.py")],
    ]
    assert wand.redirects == {}
    assert wand.argument("create", "dst") == work / "project" / "native-create.spp"
    assert wand.argument("export", "out") == work / "export"
    assert (work / "export").is_dir()
    for name in ("native-save.py", "native-export.py"):
        text = (work / name).read_text(encoding="utf-8")
        assert json.dumps(baseline) in text and PAINTER_OCIO_CONFIG_SHA256 in text


def test_a_failed_native_create_leaves_no_baseline(
    native: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A create the client fails gives no Normal: the sync and the export are refused before
    anything is started."""
    wand = native_wand(tmp_path, native)
    calls: list[list[str]] = []

    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 1, '{"success": false}', "")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(NativeNotCreated):
        wand.sync()
    assert wand.create().status == 1 and wand.baseline is None
    with pytest.raises(NativeNotCreated):
        wand.sync()
    with pytest.raises(NativeNotCreated):
        wand.export()
    assert len(calls) == 1


def test_a_legacy_wand_keeps_its_create_command_line(
    assets: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pinned `painter_create.py` bytes through the client, as before, with no save after
    the sync."""
    path = manifest_file(tmp_path, script_run.wand_manifest(assets), "legacy")
    wand = Wand(tmp_path / "UzPainter.exe", tmp_path / "work", path)
    calls = replying(monkeypatch, None)
    wand.create()
    wand.sync()
    arguments = tmp_path / "work" / "painter-create.json"
    assert calls[0] == [sys.executable, str(wand_module.CLIENT), "execute_python", str(arguments)]
    script = wand.job.inputs["painter-create-py"].data
    assert script is not None
    assert json.loads(arguments.read_text(encoding="utf-8")) == {"code": script.decode("utf-8")}
    assert len(calls) == 2 and calls[1][-7] == "sync"
    assert wand.ocio_sha256 is None and wand.baseline is None


# --- the direct route: the Painter-side code ---------------------------------------------------


def test_the_native_create_binds_the_normal_and_saves_under_the_pinned_profile(
    native: dict[str, Any], tmp_path: Path, painter: Painter
) -> None:
    wand = ocio_wand(tmp_path, native, painter)
    result = run_code(wand.native_code(NATIVE_CREATE_CODE))
    mesh, normal = (str(wand.staged[i]) for i in ("wand-mesh", "wand-normal"))
    project = str(tmp_path / "work" / "project" / "native-create.spp")
    expected_settings = {
        "normal_map_format": "NormalMapFormat.OpenGL",
        "tangent_space_mode": "TangentSpace.PerFragment",
        "project_workflow": "ProjectWorkflow.Default",
        "default_texture_resolution": 4096,
        "import_cameras": False,
        "mesh_unit_scale": 1.0,
    }
    assert painter.calls == [
        ("create", mesh, expected_settings),
        ("import", normal, "Usage.TEXTURE", NORMAL, "tunica18_v10c_mesh_maps"),
        ("bind", TUNIC_SET, "MeshMapUsage.Normal", f"resource://project0/{NORMAL}?version=v1"),
        ("save_as", project, "ProjectSaveMode.Full"),
    ]
    assert result == {
        "texture_sets": [TUNIC_SET],
        "normal": {
            "url": f"resource://projectN/{NORMAL}?version=v1",
            "context": "projectN",
            "name": NORMAL,
            "version": "v1",
        },
        "project": project,
    }
    assert isinstance(wand.pipeline, script_run.NativeJob)
    assert sha256_file(Path(normal)) == wand.pipeline.create.normal.sha256


def no_ocio(painter: Painter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OCIO")


def other_ocio(painter: Painter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    other = tmp_path / "other.ocio"
    other.write_text("another configuration\n", encoding="utf-8")
    monkeypatch.setenv("OCIO", str(other))


def legacy_project(painter: Painter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    painter.colour = {"mode": "legacy"}


def two_sets(painter: Painter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    painter.sets = ["Other", TUNIC_SET]


def no_set(painter: Painter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    painter.sets = []


def bound_ao(painter: Painter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    painter.bound["AO"] = Identifier("project0", "baked_ao")


def swapped(painter: Painter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    painter.swap = Identifier("project0", "another_normal")


def other_project(painter: Painter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    painter.swap = Identifier("project7", NORMAL)


@pytest.mark.parametrize(
    ("change", "refusal", "done"),
    [
        (no_ocio, "OCIO gives None", []),
        (other_ocio, "OCIO gives [0-9a-f]{64}, not", []),
        (legacy_project, r"colour management is \('legacy', None\)", ["create"]),
        (no_set, "not exactly", ["create"]),
        (two_sets, "not exactly", ["create"]),
        (bound_ao, r"bound are \['AO', 'Normal'\]", ["create", "import", "bind"]),
        (swapped, "not the imported", ["create", "import", "bind"]),
        (other_project, "not the imported", ["create", "import", "bind"]),
    ],
    ids=[
        "ocio-unset",
        "other-ocio",
        "legacy-project",
        "no-set",
        "two-sets",
        "another-slot-bound",
        "swapped-normal",
        "another-project-context",
    ],
)
def test_the_native_create_refuses_before_it_saves(
    native: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    painter: Painter,
    change: Any,
    refusal: str,
    done: list[str],
) -> None:
    """No OCIO or another configuration (before the create), a project read back in another
    profile, not exactly the one set (before the import), another bound slot or another Normal
    in the slot (before the save): refused, as the recorder refuses."""
    wand = ocio_wand(tmp_path, native, painter)
    change(painter, monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match=refusal):
        run_code(wand.native_code(NATIVE_CREATE_CODE))
    assert [call[0] for call in painter.calls] == done
    assert painter.saved is None


def renumbered(painter: Painter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    painter.bound["Normal"] = Identifier("project7", NORMAL)


def shelf_context(painter: Painter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    painter.bound["Normal"] = Identifier("shelf", NORMAL)


def other_version(painter: Painter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    painter.bound["Normal"] = Identifier("project0", NORMAL, "v2")


def renamed(painter: Painter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    painter.bound["Normal"] = Identifier("project0", NORMAL + "_copy")


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        (renumbered, None),
        (bound_ao, r"bound are \['AO', 'Normal'\]"),
        (renamed, "not the imported"),
        (other_version, "not the imported"),
        (shelf_context, "not the imported"),
        (legacy_project, "colour management"),
        (two_sets, "not exactly"),
    ],
    ids=[
        "reopen-renumbers-project",
        "extra-ao",
        "swapped-normal",
        "other-version",
        "shelf-context",
        "legacy-project",
        "two-sets",
    ],
)
def test_the_save_after_the_sync_and_the_export_check_the_imported_normal(
    native: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    painter: Painter,
    change: Any,
    refusal: str | None,
) -> None:
    """After the sync (and again before the export, in another process), the slots, the Normal's
    literal identity and the profile are those of the create; only a `projectN` renumbering is
    accepted. A refused export never starts."""
    wand = ocio_wand(tmp_path, native, painter)
    baseline = created(wand, painter)["normal"]
    change(painter, monkeypatch, tmp_path)
    save = wand.native_code(NATIVE_SAVE_CODE, baseline=baseline)
    export = wand.native_code(NATIVE_EXPORT_CODE, baseline=baseline, config={"exportPath": "o"})
    if refusal is None:
        assert run_code(save)["normal"] == baseline
        assert run_code(export)["status"] == "ExportStatus.Success"
        # The open project is the create's file: a Full `save`, never `save_as` onto it.
        project = str(tmp_path / "work" / "project" / "native-create.spp")
        assert [call[0] for call in painter.calls] == ["save", "export"]
        assert painter.calls[0][1] == project
        return
    with pytest.raises(RuntimeError, match=refusal):
        run_code(save)
    with pytest.raises(RuntimeError, match=refusal):
        run_code(export)
    assert [call[0] for call in painter.calls] == ["save"]


def test_a_native_wand_refuses_its_script_only_parts_by_name(
    native: dict[str, Any], tmp_path: Path
) -> None:
    wand = native_wand(tmp_path, native)
    with pytest.raises(NotAScriptJob, match="is a native job"):
        _ = wand.job
    with pytest.raises(NotAScriptJob, match="no export argument 'prefix'"):
        wand.argument("export", "prefix")


@pytest.mark.parametrize(
    ("change", "error", "refusal"),
    [
        (
            lambda m: script_run_native_with(m, mesh_unit_scale=0),
            RecorderError,
            "`mesh_unit_scale`",
        ),
        (without_ocio, NativeColourRefused, r"never Legacy; the manifest names \[\]"),
    ],
    ids=["invalid-setting", "no-ocio"],
)
def test_an_invalid_native_manifest_is_refused_before_anything_is_staged(
    native: dict[str, Any], tmp_path: Path, change: Any, error: type[Exception], refusal: str
) -> None:
    with pytest.raises(error, match=refusal):
        native_wand(tmp_path, change(native))
    assert not (tmp_path / "work").exists()


def script_run_native_with(manifest: dict[str, Any], **args: Any) -> dict[str, Any]:
    changed = copy.deepcopy(manifest)
    changed["instruction_sequence"]["steps"][0]["args"].update(args)
    return changed


# --- the direct route: the Tier 1 runner's subject ---------------------------------------------


def config(preset: str, maps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "defaultExportPreset": preset,
        "exportPresets": [{"name": "inline", "maps": maps}],
        "exportList": [{"rootPath": TUNIC_SET}],
        "exportParameters": [{"parameters": {"fileFormat": "png"}}],
    }


def channels(kind: str, name: str) -> list[dict[str, str]]:
    return [
        {"destChannel": c, "srcChannel": c, "srcMapType": kind, "srcMapName": name} for c in "RGB"
    ]


def test_the_runner_takes_a_native_jobs_normal_maps_from_its_configuration() -> None:
    maps = [
        {"fileName": "$textureSet_Normal", "channels": channels("virtualMap", "Normal_OpenGL")},
        {"fileName": "$textureSet_Height", "channels": channels("documentMap", "height")},
    ]
    assert runner.normal_maps_of(config("inline", maps)) == {f"{TUNIC_SET}_Normal"}
    assert runner.normal_maps_of(config("inline", maps[1:])) == frozenset()
    token = [{"fileName": "$mesh_Normal", "channels": channels("virtualMap", "Normal_DirectX")}]
    with pytest.raises(runner.NativeSubjectRefused, match=r"another token \$mesh"):
        runner.normal_maps_of(config("inline", token))
    # `$udim` is empty in a native job (the Default workflow): its group is dropped.
    udim = [{**maps[0], "fileName": "$textureSet_Normal(_$colorSpace)(.$udim)"}]
    assert runner.normal_maps_of(config("inline", udim)) == {f"{TUNIC_SET}_Normal_Raw"}
    mixed = [{**maps[0], "fileName": "$textureSet_Normal(_$colorSpace.$udim)"}]
    with pytest.raises(runner.NativeSubjectRefused, match=r"mixes \$udim"):
        runner.normal_maps_of(config("inline", mixed))
    blender = "resource://starter_assets/Blender (Principled BSDF)"
    shadow = [{"fileName": "Own_Normal", "channels": channels("virtualMap", "Normal_OpenGL")}]
    inline_first = config(blender, shadow)
    inline_first["exportPresets"][0]["name"] = blender
    assert runner.normal_maps_of(inline_first) == {"Own_Normal"}  # an inline preset comes first


TUNIC_CONFIG = REPO_ROOT / "parity/fixtures/tier1/tunic-v10/export-config.json"


def test_the_runner_names_the_tunics_normal_through_the_blender_catalogue_preset() -> None:
    """The real Tunic configuration (7167a93e, unchanged) names the shipped Blender preset: its
    normal map, through the authored catalogue preset under OCIO, is exactly
    `DefaultMaterial_Normal_Raw`, the name its provenance cites."""
    assert sha256_file(TUNIC_CONFIG).startswith("7167a93e")
    tunic = json.loads(TUNIC_CONFIG.read_text(encoding="utf-8"))
    assert runner.normal_maps_of(tunic) == {"DefaultMaterial_Normal_Raw"}
    recorded = {**tunic, "defaultExportPreset": tunic["defaultExportPreset"] + "?version="}
    recorded["defaultExportPreset"] += "13120355637414252359"
    assert runner.normal_maps_of(recorded) == {"DefaultMaterial_Normal_Raw"}


@pytest.mark.parametrize(
    ("preset", "refusal"),
    [
        ("resource://starter_assets/PBR Metallic Roughness", "neither inline nor"),
        ("resource://starter_assets/Blender (Principled BSDF)?version=1", "is not recorded"),
        ("resource://starter_assets/Blender (Principled BSDF)?other=1", "is not recorded"),
        ("resource://shelf/Blender (Principled BSDF)", "neither inline nor"),
    ],
    ids=["another-shipped-preset", "unrecorded-version", "another-query", "another-shelf"],
)
def test_the_runner_refuses_a_preset_it_does_not_resolve(preset: str, refusal: str) -> None:
    tunic = json.loads(TUNIC_CONFIG.read_text(encoding="utf-8"))
    with pytest.raises(runner.NativeSubjectRefused, match=refusal):
        runner.normal_maps_of({**tunic, "defaultExportPreset": preset})


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda m: m, runner.NativeSubjectRefused),
        (without_ocio, NativeColourRefused),
    ],
    ids=["unresolved-preset", "no-ocio"],
)
def test_the_runner_refuses_a_native_subject_before_any_rebuild(
    native: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: Any,
    error: type[Exception],
) -> None:
    """A preset the runner does not resolve, or a manifest without OCIO: refused before either
    rebuild runs."""
    shipped = {
        "exportShaderParams": False,
        "defaultExportPreset": "resource://starter_assets/PBR Metallic Roughness",
        "exportList": [{"rootPath": TUNIC_SET}],
        "exportParameters": [{"parameters": {"fileFormat": "png", "bitDepth": "16"}}],
    }
    path = tmp_path / "repo" / "shipped-config.json"
    path.write_text(json.dumps(shipped), encoding="utf-8")
    manifest = copy.deepcopy(native)
    item = next(i for i in manifest["inputs"] if i["input_id"] == "float-config")
    item.update(path="shipped-config.json", sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    load = script_run.pipeline_job_from_manifest

    def loader(document: dict[str, Any], assets_root: Path) -> Any:
        return load(document, assets_root, repo_root=tmp_path / "repo")

    def ran(*_: Any, **__: Any) -> Any:
        raise AssertionError("a rebuild ran")

    monkeypatch.setattr(runner, "pipeline_job_from_manifest", loader)
    monkeypatch.setattr(runner, "built", ran)
    monkeypatch.setattr(runner, "rebuild", ran)
    request = manifest_file(tmp_path, change(manifest), "shipped")
    with pytest.raises(error):
        runner._evidence(
            tmp_path / "UzPainter.exe", tmp_path, "phase9/tier1/none", request, False, True
        )


# --- the MCP route -----------------------------------------------------------------------------


class Session:
    """Replies to the native round's typed calls; `refuse` makes a tool refuse as a release
    gap, `sha256` is what the import reports, `bound` what the Normal then binds (the import's
    by default), `extra` the mesh maps `set_list` adds and `after_sync` the maps the sync
    leaves."""

    def __init__(
        self,
        sets: list[str],
        sha256: str,
        refuse: str = "",
        bound: str = "",
        extra: dict[str, Any] | None = None,
        after_sync: dict[str, Any] | None = None,
    ) -> None:
        self.sets = sets
        self.sha256 = sha256
        self.refuse = refuse
        self.bound = bound or sha256
        self.extra = extra or {}
        self.after_sync = after_sync
        self.maps: dict[str, Any] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, arguments))
        if tool == self.refuse:
            return {"error": {"code": "capability_gap", "details": {"type": "NotYetSupported"}}}
        if tool == "set_list":
            entry = {"mesh_maps": {**self.maps, **self.extra}}
            return {"result": {"texture_sets": [{"name": n, **entry} for n in self.sets]}}
        if tool == "resource_import":
            name = arguments["name"]
            url = f"resource://project/{name}?version={self.sha256}"
            resource = {"name": name, "sha256": self.sha256, "url": url, "usage": "TEXTURE"}
            return {"result": {"status": "committed", "returned": {"resource": resource}}}
        if tool == "set_mesh_maps":
            self.maps = {"Normal": {"sha256": self.bound, "name": NORMAL, "invalid": False}}
        if tool == "sync_stack" and self.after_sync is not None:
            self.maps = self.after_sync
        if tool == "export":
            path = f"{arguments['config']['exportPath']}/{TUNIC_SET}_Height.exr"
            return {"result": {"files": [{"path": path, "root_path": TUNIC_SET}]}}
        return {"result": {"status": "committed"}}


def native_round(
    native: dict[str, Any], tmp_path: Path, **session: Any
) -> tuple[Session, mcp_round.Round, script_run.NativeJob, dict[str, Path]]:
    job = script_run.pipeline_job_from_manifest(
        native, wand_module.ASSETS3D, repo_root=tmp_path / "repo"
    )
    assert isinstance(job, script_run.NativeJob)
    staged = script_run.stage_inputs(job, tmp_path / "round" / "assets")
    fake = Session(**{"sets": [TUNIC_SET], "sha256": job.create.normal.sha256, **session})
    log = mcp_round.Round(0, False)
    driver = mcp_round.Driver(cast(Any, fake), log)
    with contextlib.suppress(mcp_round.RoundFailed):  # `log.outcome` says `failed`
        mcp_round.drive(driver, job, staged, tmp_path / "round")
    return fake, log, job, staged


def test_a_native_mcp_round_sends_the_create_the_binding_the_sync_and_the_config(
    native: dict[str, Any], tmp_path: Path
) -> None:
    session, log, job, staged = native_round(native, tmp_path)
    assert log.outcome == "completed" and log.refusal is None
    work = tmp_path / "round"
    sha256 = job.create.normal.sha256
    url = f"resource://project/{NORMAL}?version={sha256}"
    config = {**job.config_export.config, "exportPath": str(work / "out" / "export")}
    project = str(work / "project" / "native-create.uzp")
    created = {
        "mesh": str(staged["wand-mesh"]),
        "settings": SETTINGS,
        "ocio_config_hash": PAINTER_OCIO_CONFIG_SHA256,
    }
    assert session.calls == [  # the long jobs are waited for (`mcp_round.LONG`)
        ("project_create", {**created, "wait": True}),
        ("set_list", {}),
        (
            "resource_import",
            {
                "path": str(staged["wand-normal"]),
                "usage": "TEXTURE",
                "name": NORMAL,
                "group": "tunica18_v10c_mesh_maps",
            },
        ),
        ("set_mesh_maps", {"texture_set": TUNIC_SET, "maps": {"Normal": {"resource": url}}}),
        ("set_list", {}),
        ("project_save_as", {"path": project, "mode": "full", "wait": True}),
        ("sync_stack", mcp_round.sync_stack_arguments(job, staged)),
        ("project_save", {"mode": "full"}),
        ("set_list", {}),
        ("export", {"config": config, "wait": True}),
    ]
    assert mcp_round.sync_stack_arguments(job, staged)["texture_set"] == TUNIC_SET
    assert list(log.files) == [(TUNIC_SET, f"{TUNIC_SET}_Height")]


BOUND = ["project_create", "set_list", "resource_import", "set_mesh_maps", "set_list"]
SYNCED = [*BOUND, "project_save_as", "sync_stack", "project_save", "set_list"]
AO = {"sha256": "1" * 64, "name": "ao", "invalid": False}


@pytest.mark.parametrize(
    ("session", "sent"),
    [
        ({"sets": ["Other"]}, ["project_create", "set_list"]),
        ({"sets": [TUNIC_SET, TUNIC_SET]}, ["project_create", "set_list"]),
        ({"sets": []}, ["project_create", "set_list"]),
        ({"sha256": "0" * 64}, ["project_create", "set_list", "resource_import"]),
        ({"bound": "2" * 64}, BOUND),
        ({"extra": {"AO": AO}}, BOUND),
        (
            {"after_sync": {"Normal": {"sha256": "2" * 64, "name": NORMAL, "invalid": False}}},
            SYNCED,
        ),
        ({"after_sync": {"Normal": {"sha256": "x", "name": "other", "invalid": False}}}, SYNCED),
        ({"after_sync": "keep+ao"}, SYNCED),
        ({"after_sync": {}}, SYNCED),
    ],
    ids=[
        "another-set",
        "ambiguous-set",
        "no-set",
        "other-bytes",
        "other-binding",
        "another-map",
        "swapped-normal-after-sync",
        "renamed-normal-after-sync",
        "extra-ao-after-sync",
        "unbound-after-sync",
    ],
)
def test_a_native_mcp_round_fails_before_the_next_edit(
    native: dict[str, Any], tmp_path: Path, session: dict[str, Any], sent: list[str]
) -> None:
    """Not exactly the create's set, an import of other bytes, or a Normal that is not the
    import or not alone, after the binding or after the sync and its save: the round fails
    before its next call and never exports."""
    if session.get("after_sync") == "keep+ao":
        job = script_run.pipeline_job_from_manifest(
            native, wand_module.ASSETS3D, repo_root=tmp_path / "repo"
        )
        assert isinstance(job, script_run.NativeJob)
        normal = {"sha256": job.create.normal.sha256, "name": NORMAL, "invalid": False}
        session = {"after_sync": {"Normal": normal, "AO": AO}}
    fake, log, _, _ = native_round(native, tmp_path, **session)
    assert log.outcome == "failed" and log.refusal is None
    assert [tool for tool, _ in fake.calls] == sent


@pytest.mark.parametrize("tool", ["project_create", "export"])
def test_a_release_gap_of_the_native_create_or_export_is_the_rounds_refusal(
    native: dict[str, Any], tmp_path: Path, tool: str
) -> None:
    """UzPainter refusing a setting (`project_create`) or the configuration (`export`) as a
    release gap ends the round `refused`, naming the call; nothing runs after it."""
    fake, log, _, _ = native_round(native, tmp_path, refuse=tool)
    assert log.outcome == "refused"
    assert log.refusal == {"tool": tool, "error_code": "capability_gap", "type": "NotYetSupported"}
    assert [t for t, _ in fake.calls][-1] == tool
    assert log.files == {}


def test_a_native_mcp_round_without_ocio_is_refused_before_any_call(
    native: dict[str, Any], tmp_path: Path
) -> None:
    with pytest.raises(NativeColourRefused):
        native_round(without_ocio(native), tmp_path)


def test_a_legacy_rounds_create_refusal_still_fails_it() -> None:
    """Only the export's release gap is a legacy round's refusal, as before."""
    reply = {"error": {"code": "capability_gap", "details": {"type": "NotYetSupported"}}}
    assert mcp_round.refusal_of("project_create", reply) is None
    assert mcp_round.refusal_of("export", reply) == {
        "tool": "export",
        "error_code": "capability_gap",
        "type": "NotYetSupported",
    }
