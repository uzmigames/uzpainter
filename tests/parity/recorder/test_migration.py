"""Tier 1 migration goldens and the Tunic v10 inputs (phase2.10; decision 194): the request
generator, job parsing and the r1 / r1-repeat / r2 recordings of a project opened from a private
copy, against a fake Painter and a temporary stand-in asset repository; and the rebuild fixture
over a synthetic report, with the recovered bitmaps in a temporary private store. The owner's real
store and Assets3D are read only by the tests of the committed manifest."""

from __future__ import annotations

import hashlib
import json
import struct
import types
import zlib
from pathlib import Path
from typing import Any

import pytest

from tools.parity.feasibility import png as png_module
from tools.parity.recorder import script_run, tunic
from tools.parity.recorder import session as session_module
from tools.parity.recorder.migration import (
    check_after_open,
    check_declared,
    declared_maps,
    load_migration_job,
    migration_job_from_manifest,
    record_migration_golden,
)
from tools.parity.recorder.script_run import MissingInputs
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.recorder.tunic import (
    EXPORT_CONFIG,
    LOST_FOLDER,
    TUNIC_MESH,
    TUNIC_PIECE_MANIFEST,
    TUNIC_PROJECT,
    TUNIC_REPORT,
    tunic_manifest,
    tunic_rebuild,
)
from tools.parity.schemas import REPO_ROOT, Schema, load_json, record_problems, validation_errors
from tools.parity.store.store import STORE_ENV, OracleStore
from tools.parity.store.store import locate as locate_store

BUILD = "12.1.5+js-api.1.1.20"
OCIO = r"C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\ocio\substance\config.ocio"
REAL_ASSETS = Path(r"E:\UzmiGames\Assets3D")
COMMITTED = (
    REPO_ROOT
    / "parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/phase2/tier1"
    / "tunic-v10.json"
)
MESH = "E:/UzmiGames/Assets3D/_tmp/astra-tunica/tunic_low.obj"
# A configuration the fake Painter exports (it resolves no shipped preset): an inline preset,
# with RGB channels because the fake writes every map as RGB (the declared-map check counts them).
FAKE_CONFIG = {
    "exportShaderParams": False,
    "defaultExportPreset": "tunic",
    "exportPresets": [
        {
            "name": "tunic",
            "maps": [
                {
                    "fileName": f"$textureSet_{name}",
                    "channels": [
                        {
                            "destChannel": c,
                            "srcChannel": c,
                            "srcMapType": "documentMap",
                            "srcMapName": name.lower(),
                        }
                        for c in "RGB"
                    ],
                }
                for name in ("BaseColor", "Height")
            ],
        }
    ],
    "exportList": [{"rootPath": "uzp_plane"}],
    "exportParameters": [{"parameters": {"fileFormat": "png", "bitDepth": "16"}}],
}
LOST = ["M_lining", "M_pores"]


def write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha1(data: bytes) -> str:
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()


def fake_project(fake: types.ModuleType) -> bytes:
    """A project file of the fake Painter: two fill layers and the mesh it was created from."""
    world = fake.FakeWorld()
    world.mesh_path = MESH
    world.layers = [
        fake.Layer(
            uid,
            {fake.ChannelType.BaseColor, fake.ChannelType.Height},
            sources={fake.ChannelType.BaseColor: fake.Color(value, 0.1, 0.1)},
        )
        for uid, value in ((101, 0.37), (102, 0.62))
    ]
    return json.dumps(world.snapshot()).encode("utf-8")


def piece_manifest(project_sha256: str) -> str:
    entry = {"path": TUNIC_PROJECT, "sha256": {"value": project_sha256, "verification": "verified"}}
    return json.dumps({"files": {"painter-v10": entry}})


@pytest.fixture(autouse=True)
def no_private_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No private store unless a test makes one."""
    monkeypatch.setenv(STORE_ENV, str(tmp_path / "no-store"))


@pytest.fixture
def assets(tmp_path: Path, fake: types.ModuleType) -> Path:
    root = tmp_path / "assets3d"
    project = fake_project(fake)
    write(root / TUNIC_PROJECT, project)
    write(root / TUNIC_PIECE_MANIFEST, piece_manifest(sha256(project)))
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository root holding the fake-exportable configuration at the fixture's path."""
    root = tmp_path / "repo"
    write(root / EXPORT_CONFIG, json.dumps(FAKE_CONFIG, indent=2))
    return root


@pytest.fixture
def painter(fake: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, PainterSession]:
    """A fake Painter 12.1.5 started under Painter's substance OCIO configuration."""
    monkeypatch.setattr(session_module, "envelope_builds", lambda: frozenset({BUILD}))
    monkeypatch.setenv("OCIO", OCIO)
    monkeypatch.delenv("PAINTER_ACE_CONFIG", raising=False)
    world = fake.FakeWorld()
    world.version, world.version_info = "12.1.5", (12, 1, 5)
    return world, PainterSession(fake.LocalTransport(world), sleep=lambda seconds: None)


def tree_state(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): sha256(p.read_bytes())
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# --- the request -------------------------------------------------------------------------------


def test_request_pins_the_verified_project_and_the_export_configuration(
    assets: Path, repo: Path
) -> None:
    manifest = tunic_manifest(assets, repo)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["golden_id"] == "phase2/tier1/tunic-v10" and manifest["private_records"] == []
    project, config = manifest["inputs"]
    assert (project["kind"], project["assets3d_path"]) == ("painter_project", TUNIC_PROJECT)
    assert project["sha256"] == sha256((assets / TUNIC_PROJECT).read_bytes())
    assert (config["kind"], config["path"]) == ("recipe_json", EXPORT_CONFIG)
    sequence = manifest["instruction_sequence"]
    assert sequence["interface"] == "painter_project_migration"
    assert [(s["call"], s["args"]) for s in sequence["steps"]] == [
        ("substance_painter.project.open", {"project": project["input_id"]}),
        ("substance_painter.export.export_project_textures", {"config": config["input_id"]}),
    ]


def test_request_refuses_a_project_saved_again(assets: Path, repo: Path) -> None:
    write(assets / TUNIC_PIECE_MANIFEST, piece_manifest("0" * 64))
    with pytest.raises(RecorderError, match="the approved project was saved again"):
        tunic_manifest(assets, repo)


def test_request_lists_a_missing_project(assets: Path, repo: Path) -> None:
    (assets / TUNIC_PROJECT).unlink()
    with pytest.raises(MissingInputs) as refused:
        tunic_manifest(assets, repo)
    assert refused.value.missing == [TUNIC_PROJECT]


def mutated(manifest: dict[str, Any], how: str) -> dict[str, Any]:
    changed: dict[str, Any] = json.loads(json.dumps(manifest))
    steps = changed["instruction_sequence"]["steps"]
    if how == "interface":
        changed["instruction_sequence"]["interface"] = "uzmigames_pipeline_scripts"
    elif how == "order":
        steps.reverse()
    elif how == "extra input":
        changed["inputs"].append({**changed["inputs"][1], "input_id": "unused"})
    elif how == "project kind":
        changed["inputs"][0]["kind"] = "mesh"
    elif how == "argument":
        steps[1]["args"]["texture_set"] = "DefaultMaterial"
    return changed


@pytest.mark.parametrize(
    ("how", "refusal"),
    [
        ("interface", "the interface is not painter_project_migration"),
        ("order", "runs step 1 substance_painter.project.open"),
        ("extra input", "every input is the project or the export configuration"),
        ("project kind", "`project` must name a painter_project input"),
        ("argument", "takes only `config`"),
    ],
)
def test_job_refuses_steps_and_inputs_it_does_not_know(
    assets: Path, repo: Path, how: str, refusal: str
) -> None:
    manifest = tunic_manifest(assets, repo)
    with pytest.raises(RecorderError, match=refusal):
        migration_job_from_manifest(mutated(manifest, how), assets, repo_root=repo)


@pytest.mark.parametrize(
    ("config", "refusal"),
    [
        ({**FAKE_CONFIG, "exportPath": "C:/out"}, "the recorder sets `exportPath`"),
        ({**FAKE_CONFIG, "exportList": []}, "`exportList` and `exportParameters`"),
    ],
)
def test_job_refuses_an_export_configuration_it_must_not_record(
    assets: Path, repo: Path, config: dict[str, Any], refusal: str
) -> None:
    manifest = tunic_manifest(assets, repo)
    write(repo / EXPORT_CONFIG, json.dumps(config))
    manifest["inputs"][1]["sha256"] = sha256((repo / EXPORT_CONFIG).read_bytes())
    with pytest.raises(RecorderError, match=refusal):
        migration_job_from_manifest(manifest, assets, repo_root=repo)


def test_a_project_gone_from_assets3d_resolves_from_the_private_store(
    assets: Path, repo: Path, tmp_path: Path
) -> None:
    """Decision 144: `--store` keeps the git-ignored project; the job opens the stored bytes."""
    store = OracleStore.init(tmp_path / "store")
    manifest = tunic_manifest(assets, repo)
    assert script_run.store_inputs(manifest, assets, store) == 1  # the repository file is not
    pinned = (assets / TUNIC_PROJECT).read_bytes()
    (assets / TUNIC_PROJECT).unlink()
    job = migration_job_from_manifest(manifest, assets, store, repo_root=repo)
    assert job.project_file.is_relative_to(store.root)
    assert job.project_file.read_bytes() == pinned
    with pytest.raises(RecorderError, match="does not exist, and the private store holds no"):
        migration_job_from_manifest(
            manifest, assets, OracleStore.init(tmp_path / "empty"), repo_root=repo
        )


# --- the recording -----------------------------------------------------------------------------


def test_records_r1_repeat_and_r2_from_a_private_copy(
    painter: tuple[Any, PainterSession], assets: Path, repo: Path, tmp_path: Path
) -> None:
    before = tree_state(assets)
    job = migration_job_from_manifest(tunic_manifest(assets, repo), assets, repo_root=repo)
    run = record_migration_golden(painter[1], job, tmp_path / "work", tmp_path / "inbox")

    assert tree_state(assets) == before  # the original project is never opened or saved
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    recordings = {r["recording_id"]: r for r in data["recordings"]}
    assert {k: r["condition"] for k, r in recordings.items()} == {
        "r1": "same_session",
        "r1-repeat": "same_session",
        "r2": "after_save_reopen",
    }
    outputs = {rid: {o["output_id"]: o for o in r["outputs"]} for rid, r in recordings.items()}
    assert set(outputs["r1-repeat"]) == {"export/s2", "export/uzp_plane_BaseColor",
                                         "export/uzp_plane_Height"}  # fmt: skip
    for rid in ("r1", "r2"):
        state = outputs[rid]["migration/state"]
        assert state["call"] == "substance_painter.layerstack.get_root_layer_nodes"
        value = state["value"]
        assert value["last_imported_mesh_path"] == MESH
        assert Path(value["file_path"]).is_relative_to(tmp_path / "work")  # the private copy
        stack = value["texture_sets"]["uzp_plane"]["stacks"][""]
        layers = stack["layers"]
        assert [layer["type"] for layer in layers] == ["FillLayer", "FillLayer"]
        assert layers[0]["sources"]["BaseColor"]["source"] == {
            "uniform_color_working": [0.62, 0.1, 0.1]
        }
        assert layers[0]["blending"]["Height"] == {"blending_mode": "Normal", "opacity": 1.0}
        assert layers[0]["mask"] == {"has_mask": False}
        assert value["texture_sets"]["uzp_plane"]["mesh_maps"]["Normal"] is None
    maps = {
        rid: sorted(o["map"] for o in out.values() if o["kind"] == "exported_map")
        for rid, out in outputs.items()
    }
    assert (
        maps["r1"] == maps["r1-repeat"] == maps["r2"] == ["uzp_plane_BaseColor", "uzp_plane_Height"]
    )
    folders = {
        Path(f).parent
        for out in outputs.values()
        for entry in out["export/s2"]["value"]["textures"]
        for f in entry["files"]
    }
    assert len(folders) == 3 and all(f.is_relative_to(tmp_path / "work") for f in folders)
    assert data["key"]["effective_defaults"]["colour_management_after_open"]["mode"] == "ocio"
    published = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert validation_errors(published, Schema.GOLDEN_PUBLIC) == []


def test_command_records_a_migration_golden(
    painter: tuple[Any, PainterSession],
    assets: Path,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.parity.recorder import __main__ as cli

    request = tmp_path / "request.json"
    write(request, json.dumps(tunic_manifest(assets, repo)))
    monkeypatch.setattr(cli, "ScriptSession", lambda *args, **kwargs: painter[1])
    monkeypatch.setattr(
        cli,
        "load_migration_job",
        lambda path, root: migration_job_from_manifest(load_json(path), root, repo_root=repo),
    )
    monkeypatch.setenv("UZP_ORACLE_WORK", str(tmp_path / "work"))
    monkeypatch.setenv("UZP_ORACLE_INBOX", str(tmp_path / "inbox"))
    command = ["record-migration", str(request), "--assets-root", str(assets)]
    assert cli.main(command) == 0
    assert len(list((tmp_path / "inbox").rglob("READY"))) == 1
    (assets / TUNIC_PROJECT).write_bytes(b"saved again")
    assert cli.main(command) == 2


# --- the rebuild fixture -----------------------------------------------------------------------


def synthetic_report(bitmaps: dict[str, bytes], normal: bytes) -> dict[str, Any]:
    """The report's fields the fixture reads, in the real report's shape."""

    def url(name: str, data: bytes) -> str:
        return f"resource://project0/{name}?version={sha1(data)}.image"

    layers = [
        {"id": "C01", "group": "outer", "mask": None, "base": [0.37, 0.1, 0.1]},
        {"id": "C02", "group": "outer", "mask": "M_pores", "base": [0.05, 0.02, 0.02]},
        {"id": "C07", "group": "outer", "mask": "M_piping", "base": [0.62, 0.54, 0.39]},
        {"id": "F02", "group": "lining", "mask": "M_pores", "base": [0.04, 0.03, 0.02]},
        {"id": "F03", "group": "lining", "mask": "M_piping", "base": [0.3, 0.25, 0.19]},
    ]
    groups = [
        {"key": "outer", "name": "Tecido externo", "mask": None},
        {"key": "lining", "name": "Forro", "mask": "M_lining", "replace_height": True},
    ]
    resource = (
        "ResourceID(context='project0', name='Tunic_v6_HighNormal', "
        f"version='{sha1(normal)}.image')"
    )
    return {
        "painting": {
            "effects_opacity_blending_state": {
                "doubleSided": {"identifier": "doubleSided", "value": True},
                "mesh_maps": {"MeshMapUsage.Normal": resource},
            }
        },
        "painting_v10": {
            "painter_stack_recipe": {"title": "Tunica v10", "groups": groups, "layers": layers},
            "mask_resources": [
                {
                    "mask": "M_piping",
                    "sha256": sha256(bitmaps["M_piping"]),
                    "resource": url("v10_M_piping", bitmaps["M_piping"]),
                }
            ],
            "short_panel_recipe": {
                "input_mask_sha256": {"M_piping": sha256(bitmaps["M_piping_lining_v9"])}
            },
            "source_recovery": {
                "layer_specific_masks": {
                    "bindings": [
                        {"layer_id": "C07", "packed_image": "Source_v10_M_piping"},
                        {
                            "layer_id": "F03",
                            "packed_image": "Source_v9_M_piping",
                            "recorded_original_resource": url(
                                "v9_M_piping", bitmaps["M_piping_lining_v9"]
                            ),
                        },
                    ],
                    "recipe_override_before_sync": {
                        "layer_id": "F03",
                        "mask": "M_piping_lining_v9",
                    },
                }
            },
        },
    }


@pytest.fixture
def rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, OracleStore, dict[str, bytes]]:
    """A stand-in asset repository with the report and the mesh, and a private store holding the
    recovered bitmaps (both piping masks and the Normal map), pinned like the real ones."""
    bitmaps = {
        "M_piping": b"v10 piping",
        "M_piping_lining_v9": b"v9 piping",
        "M_pores": b"pores",
        "M_lining": b"lining",
    }
    normal = b"high normal"
    root = tmp_path / "rebuild-assets"
    write(root / TUNIC_REPORT, json.dumps(synthetic_report(bitmaps, normal)))
    write(root / TUNIC_MESH, b"fbx")
    store = OracleStore.init(tmp_path / "rebuild-store")
    recovered = {}
    for name, packed in (
        ("M_piping", "Source_v10_M_piping"),
        ("M_piping_lining_v9", "Source_v9_M_piping"),
    ):
        recovered[name] = (packed, sha256(bitmaps[name]))
    for data in (bitmaps["M_piping"], bitmaps["M_piping_lining_v9"], normal):
        source = tmp_path / "blob"
        source.write_bytes(data)
        store.add_input(source, sha256(data), "18-Tunica-v10.blend#packed")
    monkeypatch.setattr(tunic, "RECOVERED", recovered)
    monkeypatch.setattr(tunic, "NORMAL", ("Source_v6_HighNormal", sha256(normal)))
    return root, store, bitmaps


def restore_lost(root: Path, bitmaps: dict[str, bytes]) -> None:
    for name in LOST:
        write(root / LOST_FOLDER / f"{name}.png", bitmaps[name])


def test_rebuild_lists_every_lost_mask_at_its_original_path(
    rebuild: tuple[Path, OracleStore, dict[str, bytes]],
) -> None:
    root, store, _ = rebuild
    with pytest.raises(MissingInputs) as refused:
        tunic_rebuild(root, store)
    assert refused.value.missing == [f"{LOST_FOLDER}/{name}.png" for name in LOST]


def test_rebuild_lists_a_recovered_bitmap_the_store_lacks(
    rebuild: tuple[Path, OracleStore, dict[str, bytes]], tmp_path: Path
) -> None:
    root, _, bitmaps = rebuild
    restore_lost(root, bitmaps)
    with pytest.raises(MissingInputs) as refused:
        tunic_rebuild(root, OracleStore.init(tmp_path / "empty"))
    assert len(refused.value.missing) == 3
    assert all(m.startswith("private store: ") for m in refused.value.missing)


def test_rebuild_binds_c07_and_f03_to_different_resources_by_hash(
    rebuild: tuple[Path, OracleStore, dict[str, bytes]],
) -> None:
    """3.2 at the fixture: F03 alone takes the override; C07 keeps the v10 piping; a mask two
    layers share (M_pores) is one input; the group mask is bound; every binding names its bytes'
    SHA-256 and Painter resource version."""
    root, store, bitmaps = rebuild
    restore_lost(root, bitmaps)
    fixture = tunic_rebuild(root, store)
    bindings = {b["node"]: b for b in fixture["bindings"]}
    assert set(bindings) == {"lining", "C02", "C07", "F02", "F03"}
    assert bindings["C07"]["sha256"] == sha256(bitmaps["M_piping"])
    assert bindings["F03"]["sha256"] == sha256(bitmaps["M_piping_lining_v9"])
    assert bindings["C07"]["sha256"] != bindings["F03"]["sha256"]
    assert bindings["F03"]["mask"] == "M_piping_lining_v9" and bindings["C07"]["mask"] == "M_piping"
    assert bindings["C02"]["input"] == bindings["F02"]["input"] == "mask-m_pores"
    assert bindings["lining"] == {
        "node": "lining",
        "kind": "group",
        "mask": "M_lining",
        "input": "mask-m_lining",
        "sha256": sha256(bitmaps["M_lining"]),
        "painter_version": sha1(bitmaps["M_lining"]),
    }
    assert all(b["painter_version"] == sha1(bitmaps[b["mask"]]) for b in bindings.values())
    assert fixture["stack"]["override"] == {"layer_id": "F03", "mask": "M_piping_lining_v9"}
    assert fixture["double_sided"]["value"] is True
    inputs = {item["input_id"]: item for item in fixture["inputs"]}
    assert inputs["tunic-mesh"]["assets3d_path"] == TUNIC_MESH
    assert inputs["mask-m_piping"]["recovered_from"]["packed_image"] == "Source_v10_M_piping"
    assert "assets3d_path" not in inputs["tunic-normal"]  # resolved from the private store


def test_rebuild_refuses_a_recovered_bitmap_the_report_contradicts(
    rebuild: tuple[Path, OracleStore, dict[str, bytes]],
) -> None:
    root, store, bitmaps = rebuild
    restore_lost(root, bitmaps)
    report = json.loads((root / TUNIC_REPORT).read_text(encoding="utf-8"))
    report["painting_v10"]["mask_resources"][0]["resource"] = (
        "resource://project0/v10_M_piping?version=" + "0" * 40
    )
    write(root / TUNIC_REPORT, json.dumps(report))
    with pytest.raises(RecorderError, match="disagree with the report"):
        tunic_rebuild(root, store)


def test_rebuild_command_lists_the_missing_inputs_as_json(
    rebuild: tuple[Path, OracleStore, dict[str, bytes]],
    tmp_path: Path,
    capsys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, store, _ = rebuild
    monkeypatch.setenv(STORE_ENV, str(store.root))
    out = tmp_path / "out" / "rebuild-fixture.json"
    command = [
        "manifest",
        "--pilot",
        "tunic-rebuild",
        "--assets-root",
        str(root),
        "--out",
        str(out),
    ]
    assert script_run.main(command) == 2
    assert not out.exists()
    printed = capsys.readouterr().err
    assert json.loads(printed[printed.index("{") :])["missing"] == [
        f"{LOST_FOLDER}/{name}.png" for name in LOST
    ]


# --- the committed manifest against the real asset repository -------------------------------


def test_committed_manifest_matches_the_real_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    """The admitted manifest (decision 215) is what the generator writes over the real project,
    and its pin resolves in Assets3D or in the owner's private store."""
    monkeypatch.undo()  # the owner's store, read only
    if not (REAL_ASSETS / "AGENTS.md").is_file():
        pytest.skip(f"the UzmiGames asset repository is not at {REAL_ASSETS}")
    committed = load_json(COMMITTED)
    assert validation_errors(committed, Schema.GOLDEN_PUBLIC) == []
    assert {**committed, "private_records": []} == tunic_manifest(REAL_ASSETS)
    job = load_migration_job(COMMITTED, REAL_ASSETS, locate_store())
    assert (
        job.config["defaultExportPreset"] == "resource://starter_assets/Blender (Principled BSDF)"
    )


def test_real_rebuild_waits_on_exactly_the_nine_lost_masks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every recovered bitmap resolves from the owner's store and agrees with the report; the
    refusal names the nine masks only the Painter project holds (decision 194)."""
    monkeypatch.undo()
    store = locate_store()
    if not (REAL_ASSETS / "AGENTS.md").is_file() or store is None:
        pytest.skip("needs the UzmiGames asset repository and the owner's private store")
    lost = ["M_cav", "M_dyeinv", "M_fiber", "M_fray", "M_hem", "M_lining", "M_pores"]
    lost += ["M_ridgewear", "M_stains"]
    present = [n for n in lost if (REAL_ASSETS / LOST_FOLDER / f"{n}.png").is_file()]
    if present:
        pytest.skip(f"the owner has restored {present}: the fixture is written, not refused")
    with pytest.raises(MissingInputs) as refused:
        tunic_rebuild(REAL_ASSETS, store)
    assert refused.value.missing == [f"{LOST_FOLDER}/{name}.png" for name in lost]


# --- the Sash v5 migration request (decision 300 item 7) -----------------------------------------

CURRENT_BUILD = "12.2.0+js-api.1.1.20"
SASH_REQUEST = (
    REPO_ROOT
    / "parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/requests/phase2/tier1"
    / "sash-v5-migration.json"
)
SASH_PROJECT = "Creatures/Undead/Skeletal Mage/Models3D/25-Faixa-Cintura/25-Faixa-Cintura-v5.spp"
SASH_PIN = "0691cc12071436cb4e97bb612a73cea4fb9b2d3c08231b517fe573dd0e310b8a"
SASH_CONFIG = "parity/fixtures/tier1/sash-v5/export-config.json"


def rgb(file_name: str, source_type: str, source: str) -> dict[str, Any]:
    return {
        "fileName": file_name,
        "channels": [
            {"destChannel": c, "srcChannel": c, "srcMapType": source_type, "srcMapName": source}
            for c in "RGB"
        ],
    }


# The Sash configuration's shape over the fake's texture set (the fake writes RGB maps only).
SASH_FAKE_CONFIG = {
    "exportShaderParams": False,
    "defaultExportPreset": "sash-fake",
    "exportPresets": [
        {
            "name": "sash-fake",
            "maps": [
                rgb("uzp_plane_BaseColor", "documentMap", "basecolor"),
                rgb("uzp_plane_Normal", "virtualMap", "Normal_OpenGL"),
            ],
        }
    ],
    "exportList": [{"rootPath": "uzp_plane"}],
    "exportParameters": [
        {
            "parameters": {
                "fileFormat": "png",
                "bitDepth": "16",
                "paddingAlgorithm": "infinite",
                "dithering": False,
            }
        }
    ],
}


def sash_request() -> dict[str, Any]:
    request: dict[str, Any] = load_json(SASH_REQUEST)
    return request


@pytest.fixture
def sash_assets(tmp_path: Path, fake: types.ModuleType) -> tuple[Path, dict[str, Any]]:
    """A stand-in asset repository holding a fake project at the sash's path, and the committed
    request re-pinned to it. Nothing else of the sash (no mask, no low OBJ) is present."""
    root = tmp_path / "sash-assets"
    project = fake_project(fake)
    write(root / SASH_PROJECT, project)
    request = sash_request()
    request["inputs"][0]["sha256"] = sha256(project)
    return root, request


def test_sash_request_is_a_two_input_two_step_migration_of_the_current_envelope() -> None:
    from tools.parity.envelope.registry import current_envelope

    request = sash_request()
    assert validation_errors(request, Schema.GOLDEN_PUBLIC) == []
    assert request["golden_id"] == "phase2/tier1/sash-v5-migration"  # never the script sash-v5
    assert request["private_records"] == []
    assert request["software"]["painter"]["build_id"] == current_envelope()["painter_build"]
    assert len(request["inputs"]) == 2
    project, config = request["inputs"]
    assert (project["kind"], project["assets3d_path"], project["sha256"]) == (
        "painter_project",
        SASH_PROJECT,
        SASH_PIN,
    )
    assert (config["kind"], config["path"]) == ("recipe_json", SASH_CONFIG)
    assert config["sha256"] == sha256((REPO_ROOT / SASH_CONFIG).read_bytes())
    sequence = request["instruction_sequence"]
    assert sequence["interface"] == "painter_project_migration"
    assert [(s["step"], s["call"], s["args"]) for s in sequence["steps"]] == [
        (1, "substance_painter.project.open", {"project": project["input_id"]}),
        (2, "substance_painter.export.export_project_textures", {"config": config["input_id"]}),
    ]


def test_sash_export_configuration_states_every_field() -> None:
    config = load_json(REPO_ROOT / SASH_CONFIG)
    assert "exportPath" not in config  # the recorder owns the private destination
    assert config["exportShaderParams"] is False
    assert config["exportList"] == [{"rootPath": "25-Faixa-Cintura"}]
    (preset,) = config["exportPresets"]
    assert config["defaultExportPreset"] == preset["name"]
    names = [m["fileName"] for m in preset["maps"]]
    assert names == [
        f"25-Faixa-Cintura_{m}" for m in ("BaseColor", "Roughness", "Metallic", "Height", "Normal")
    ]
    sources = [{(c["srcMapType"], c["srcMapName"]) for c in m["channels"]} for m in preset["maps"]]
    assert sources[-1] == {("virtualMap", "Normal_OpenGL")}
    assert config["exportParameters"] == [
        {
            "parameters": {
                "fileFormat": "png",
                "bitDepth": "16",
                "sizeLog2": 11,
                "paddingAlgorithm": "infinite",
                "dithering": False,
            }
        }
    ]


def test_sash_request_resolves_without_the_lost_masks_or_the_low_obj(
    sash_assets: tuple[Path, dict[str, Any]],
) -> None:
    root, request = sash_assets
    job = migration_job_from_manifest(request, root)
    assert job.project_file == root / SASH_PROJECT
    assert job.config == load_json(REPO_ROOT / SASH_CONFIG)


def sash_refusal(how: str, request: dict[str, Any], root: Path) -> dict[str, Any]:
    changed: dict[str, Any] = json.loads(json.dumps(request))
    if how == "bad pin":
        changed["inputs"][0]["sha256"] = "0" * 64
    elif how == "missing project":
        (root / SASH_PROJECT).unlink()
    elif how == "config hash":
        changed["inputs"][1]["sha256"] = "1" * 64
    elif how == "extra input":
        changed["inputs"].append({**changed["inputs"][1], "input_id": "sash-v5-lost-mask"})
    elif how == "extra step":
        steps = changed["instruction_sequence"]["steps"]
        steps.append({**steps[1], "step": 3})
    return changed


@pytest.mark.parametrize(
    ("how", "refusal"),
    [
        ("bad pin", "not the pinned one, and the private store holds no blob"),
        ("missing project", "does not exist, and the private store holds no blob"),
        ("config hash", "is missing or not the pinned bytes"),
        ("extra input", "every input is the project or the export configuration"),
        ("extra step", "runs step 1 substance_painter.project.open, step 2"),
    ],
)
def test_sash_request_refuses_before_painter(
    sash_assets: tuple[Path, dict[str, Any]], tmp_path: Path, how: str, refusal: str
) -> None:
    root, request = sash_assets
    changed = sash_refusal(how, request, root)
    empty = OracleStore.init(tmp_path / "empty-store")  # the project is in no store either
    with pytest.raises(RecorderError, match=refusal):
        migration_job_from_manifest(changed, root, empty)


def test_sash_request_refuses_an_export_path(
    sash_assets: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    root, request = sash_assets
    repo_root = tmp_path / "sash-repo"
    config = {**load_json(REPO_ROOT / SASH_CONFIG), "exportPath": "C:/out"}
    write(repo_root / SASH_CONFIG, json.dumps(config))
    request["inputs"][1]["sha256"] = sha256((repo_root / SASH_CONFIG).read_bytes())
    with pytest.raises(RecorderError, match="the recorder sets `exportPath`"):
        migration_job_from_manifest(request, root, repo_root=repo_root)


@pytest.fixture
def painter_current(
    fake: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, PainterSession]:
    """A fake Painter of the current envelope (12.2.0) under the substance OCIO configuration."""
    monkeypatch.setattr(session_module, "envelope_builds", lambda: frozenset({CURRENT_BUILD}))
    monkeypatch.setenv("OCIO", OCIO)
    monkeypatch.delenv("PAINTER_ACE_CONFIG", raising=False)
    world = fake.FakeWorld()
    world.version, world.version_info = "12.2.0", (12, 2, 0)
    return world, PainterSession(fake.LocalTransport(world), sleep=lambda seconds: None)


def test_sash_request_records_three_exports_from_a_private_copy(
    painter_current: tuple[Any, PainterSession],
    sash_assets: tuple[Path, dict[str, Any]],
    tmp_path: Path,
) -> None:
    """The fake Painter knows only its own texture set and writes RGB maps, so the export
    configuration is the Sash's shape (inline preset, literal names, PNG 16) over that set, at
    the Sash fixture's path: the declared-map check runs on every export. The request is
    otherwise the committed one."""
    root, request = sash_assets
    repo_root = tmp_path / "sash-repo"
    write(repo_root / SASH_CONFIG, json.dumps(SASH_FAKE_CONFIG, indent=2))
    request["inputs"][1]["sha256"] = sha256((repo_root / SASH_CONFIG).read_bytes())
    before = tree_state(root)
    job = migration_job_from_manifest(request, root, repo_root=repo_root)
    run = record_migration_golden(painter_current[1], job, tmp_path / "work", tmp_path / "inbox")
    assert tree_state(root) == before  # the original project is never opened or saved
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    assert data["golden_id"] == "phase2/tier1/sash-v5-migration"
    assert data["key"]["painter_build"]["build_id"] == CURRENT_BUILD
    recordings = {r["recording_id"]: r for r in data["recordings"]}
    assert {k: r["condition"] for k, r in recordings.items()} == {
        "r1": "same_session",
        "r1-repeat": "same_session",
        "r2": "after_save_reopen",
    }
    for rid, recording in recordings.items():
        outputs = {o["output_id"]: o for o in recording["outputs"]}
        assert sorted(o["map"] for o in outputs.values() if o["kind"] == "exported_map") == [
            "uzp_plane_BaseColor",
            "uzp_plane_Normal",
        ]
        if rid != "r1-repeat":
            state = outputs["migration/state"]["value"]
            assert Path(state["file_path"]).is_relative_to(tmp_path / "work")  # the copy
    published = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert validation_errors(published, Schema.GOLDEN_PUBLIC) == []
    assert published["inputs"] == request["inputs"]


def test_committed_sash_request_resolves_in_the_real_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pin resolves to the preserved project (Assets3D or the owner's store), read only."""
    monkeypatch.undo()
    if not (REAL_ASSETS / "AGENTS.md").is_file():
        pytest.skip(f"the UzmiGames asset repository is not at {REAL_ASSETS}")
    job = load_migration_job(SASH_REQUEST, REAL_ASSETS, locate_store())
    assert job.project_sha256 == SASH_PIN
    assert job.config == load_json(REPO_ROOT / SASH_CONFIG)


# --- the opened-project and declared-map checks (any migration golden) ---------------------------


def test_the_committed_sash_configuration_is_refused_before_any_export_on_another_project(
    painter_current: tuple[Any, PainterSession],
    sash_assets: tuple[Path, dict[str, Any]],
    tmp_path: Path,
) -> None:
    """The fake project holds the texture set uzp_plane, not 25-Faixa-Cintura: the run stops
    after the open and its readback, before an export, and nothing reaches the inbox."""
    root, request = sash_assets
    job = migration_job_from_manifest(request, root)
    with pytest.raises(RecorderError, match=r"has no texture set \['25-Faixa-Cintura'\]"):
        record_migration_golden(painter_current[1], job, tmp_path / "work", tmp_path / "inbox")
    assert not list((tmp_path / "work").rglob("fence"))  # no export was started
    assert not (tmp_path / "inbox").exists()


def opened_job(sash_assets: tuple[Path, dict[str, Any]]) -> Any:
    root, request = sash_assets
    return migration_job_from_manifest(request, root)


SESSION_COLOUR = {"mode": "ocio", "OCIO": OCIO, "PAINTER_ACE_CONFIG": None}


@pytest.mark.parametrize(
    ("after_open", "sets", "refusal"),
    [
        ({**SESSION_COLOUR, "mode": "legacy", "OCIO": None}, ["25-Faixa-Cintura"], "mode changed"),
        ({**SESSION_COLOUR, "OCIO": "other.ocio"}, ["25-Faixa-Cintura"], "OCIO changed"),
        ({**SESSION_COLOUR, "PAINTER_ACE_CONFIG": "ace.ocio"}, ["25-Faixa-Cintura"], "ACE_CONFIG"),
        (SESSION_COLOUR, ["DefaultMaterial"], "has no texture set"),
    ],
    ids=["mode", "ocio", "ace", "texture-set"],
)
def test_the_colour_environment_is_stable_across_the_open_and_the_exported_sets_exist(
    sash_assets: tuple[Path, dict[str, Any]],
    after_open: dict[str, Any],
    sets: list[str],
    refusal: str,
) -> None:
    """The colour check compares `hello`'s environment variables before and after the open, so it
    proves environment stability only, never the opened project's own saved colour mode."""
    job = opened_job(sash_assets)
    with pytest.raises(RecorderError, match=refusal):
        check_after_open(job, SESSION_COLOUR, after_open, {name: {} for name in sets})
    check_after_open(job, SESSION_COLOUR, dict(SESSION_COLOUR), {"25-Faixa-Cintura": {}})


def png_header(width: int, height: int, bits: int, channels: int) -> bytes:
    """The PNG signature and IHDR of a map: all the size check reads (no 2048 px encode)."""
    colour_type = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    body = struct.pack(">IIBBBBB", width, height, bits, colour_type, 0, 0, 0)
    crc = zlib.crc32(b"IHDR" + body) & 0xFFFFFFFF
    return (
        png_module.SIGNATURE
        + struct.pack(">I", len(body))
        + b"IHDR"
        + body
        + struct.pack(">I", crc)
    )


def declared_exports(
    directory: Path, maps: dict[str, tuple[int, int, int]], repeat: str | None = None
) -> list[dict[str, Any]]:
    """The outputs of one config export as the recorder reports them, its readback included:
    name -> (channels, bits, size); `repeat` lists one file twice in the readback."""
    files: list[str] = []
    outputs: list[dict[str, Any]] = []
    for name, (channels, bits, size) in maps.items():
        path = directory / f"{name}.png"
        write(path, png_header(size, size, bits, channels))
        files.append(path.as_posix())
        outputs.append(
            {
                "kind": "exported_map",
                "texture_set": "25-Faixa-Cintura",
                "map": name,
                "storage_format": {
                    "container": "png",
                    "sample_type": "uint",
                    "bits_per_channel": bits,
                    "channels": channels,
                    "encoding": "undetermined",
                },
            }
        )
    if repeat is not None:
        files.append((directory / f"{repeat}.png").as_posix())
    readback = {
        "output_id": "export/s2",
        "kind": "api_readback",
        "call": "substance_painter.export.export_project_textures",
        "value": {"textures": [{"texture_set": "25-Faixa-Cintura", "stack": "", "files": files}]},
    }
    return [readback, *outputs]


SASH_MAPS = {
    "25-Faixa-Cintura_BaseColor": (3, 16, 2048),
    "25-Faixa-Cintura_Roughness": (1, 16, 2048),
    "25-Faixa-Cintura_Metallic": (1, 16, 2048),
    "25-Faixa-Cintura_Height": (1, 16, 2048),
    "25-Faixa-Cintura_Normal": (3, 16, 2048),
}


@pytest.mark.parametrize(
    ("change", "repeat", "refusal"),
    [
        ({}, None, None),
        ({"25-Faixa-Cintura_Normal": None}, None, "not the declared"),
        ({"25-Faixa-Cintura_Extra": (1, 16, 2048)}, None, "not the declared"),
        ({}, "25-Faixa-Cintura_Height", "once each"),
        ({"25-Faixa-Cintura_Height": (1, 8, 2048)}, None, "is .*'bits_per_channel': 8"),
        ({"25-Faixa-Cintura_Roughness": (3, 16, 2048)}, None, "is .*'channels': 3"),
        ({"25-Faixa-Cintura_Metallic": (1, 16, 1024)}, None, "is 1024x1024, not the declared 2048"),
    ],
    ids=["exact", "missing", "extra", "listed-twice", "depth", "channels", "size"],
)
def test_an_export_must_write_exactly_the_declared_maps(
    sash_assets: tuple[Path, dict[str, Any]],
    tmp_path: Path,
    change: dict[str, tuple[int, int, int] | None],
    repeat: str | None,
    refusal: str | None,
) -> None:
    job = opened_job(sash_assets)
    maps = {**SASH_MAPS, **change}
    present = {name: spec for name, spec in maps.items() if spec is not None}
    outputs = declared_exports(tmp_path / "export", present, repeat)
    if refusal is None:
        check_declared(job, outputs)
        return
    with pytest.raises(RecorderError, match=refusal):
        check_declared(job, outputs)


def test_declared_maps_of_the_committed_and_fake_configurations() -> None:
    shipped = load_json(REPO_ROOT / EXPORT_CONFIG)  # the Tunic's shipped Blender preset
    assert declared_maps(shipped) is None  # Painter names a shipped preset's maps
    fake = declared_maps(FAKE_CONFIG)
    assert fake is not None
    assert fake[0] == {("uzp_plane", f"uzp_plane_{m}"): 3 for m in ("BaseColor", "Height")}
    sash = declared_maps(load_json(REPO_ROOT / SASH_CONFIG))
    assert sash is not None
    assert sash[0] == {("25-Faixa-Cintura", name): spec[0] for name, spec in SASH_MAPS.items()}
    assert sash[1]["sizeLog2"] == 11


def reshaped(how: str) -> dict[str, Any]:
    config: dict[str, Any] = json.loads(json.dumps(SASH_FAKE_CONFIG))
    preset = config["exportPresets"][0]
    rule = config["exportParameters"][0]
    if how == "entry preset":
        config["exportList"][0]["exportPreset"] = "resource://starter_assets/PBR Metallic Roughness"
    elif how == "two rules":
        config["exportParameters"].append({"parameters": {"bitDepth": "8"}})
    elif how == "filtered rule":
        rule["filter"] = {"outputMaps": ["uzp_plane_Normal"]}
    elif how == "map parameters":
        preset["maps"][0]["parameters"] = {"bitDepth": "8"}
    elif how == "other token":
        preset["maps"][0]["fileName"] = "$mesh_BaseColor"
    elif how in ("exr 16f", "exr 32f"):
        rule["parameters"].update(fileFormat="exr", bitDepth=how.split()[1])
    elif how == "no depth":
        del rule["parameters"]["bitDepth"]
    elif how == "size text":
        rule["parameters"]["sizeLog2"] = "11"
    elif how == "repeated name":
        preset["maps"][1]["fileName"] = preset["maps"][0]["fileName"]
    return config


@pytest.mark.parametrize(
    "how",
    [
        "entry preset",
        "two rules",
        "filtered rule",
        "map parameters",
        "other token",
        "exr 16f",
        "exr 32f",
        "no depth",
        "size text",
    ],
)
def test_a_configuration_outside_the_checked_scope_keeps_the_generic_behaviour(
    sash_assets: tuple[Path, dict[str, Any]], tmp_path: Path, how: str
) -> None:
    """Only one unfiltered PNG 8/16 inline preset is checked against its declared maps; any other
    valid configuration (OpenEXR 16f or 32f among them) loads and is exported as before."""
    root, request = sash_assets
    config = reshaped(how)
    assert declared_maps(config) is None
    repo_root = tmp_path / "sash-repo"
    write(repo_root / SASH_CONFIG, json.dumps(config))
    request["inputs"][1]["sha256"] = sha256((repo_root / SASH_CONFIG).read_bytes())
    job = migration_job_from_manifest(request, root, repo_root=repo_root)
    check_declared(job, [])  # nothing is checked: Painter's own export check stands


def test_a_checked_preset_that_declares_a_map_twice_is_refused_before_painter(
    sash_assets: tuple[Path, dict[str, Any]], tmp_path: Path
) -> None:
    root, request = sash_assets
    repo_root = tmp_path / "sash-repo"
    write(repo_root / SASH_CONFIG, json.dumps(reshaped("repeated name")))
    request["inputs"][1]["sha256"] = sha256((repo_root / SASH_CONFIG).read_bytes())
    with pytest.raises(RecorderError, match="is declared twice"):
        migration_job_from_manifest(request, root, repo_root=repo_root)
