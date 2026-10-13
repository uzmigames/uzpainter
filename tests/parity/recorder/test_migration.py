"""Tier 1 migration goldens and the Tunic v10 inputs (phase2.10; decision 194): the request
generator, job parsing and the r1 / r1-repeat / r2 recordings of a project opened from a private
copy, against a fake Painter and a temporary stand-in asset repository; and the rebuild fixture
over a synthetic report, with the recovered bitmaps in a temporary private store. The owner's real
store and Assets3D are read only by the tests of the committed request."""

from __future__ import annotations

import hashlib
import json
import types
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder import script_run, tunic
from tools.parity.recorder import session as session_module
from tools.parity.recorder.migration import (
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
    REPO_ROOT / "parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase2/tier1/tunic-v10.json"
)
MESH = "E:/UzmiGames/Assets3D/_tmp/astra-tunica/tunic_low.obj"
# A configuration the fake Painter exports (it resolves no shipped preset): an inline preset.
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
                            "destChannel": "L",
                            "srcChannel": "L",
                            "srcMapType": "documentMap",
                            "srcMapName": name.lower(),
                        }
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


# --- the committed request against the real asset repository --------------------------------


def test_committed_request_matches_the_real_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    """The committed request is what the generator writes over the real project, and its pin
    resolves in Assets3D or in the owner's private store."""
    monkeypatch.undo()  # the owner's store, read only
    if not (REAL_ASSETS / "AGENTS.md").is_file():
        pytest.skip(f"the UzmiGames asset repository is not at {REAL_ASSETS}")
    committed = load_json(COMMITTED)
    assert committed == tunic_manifest(REAL_ASSETS)
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
