"""The Unreal Engine 5.6 consumer fixture (`tools/consumers/unreal.py`;
phase3.2_unreal-ue56-packed-preset items 2.8, 3.2, 3.3 and 3.5).

The first cases run on every CPU lane without UE: the delivery adapter's selection and staging,
the project's create-once rule and the judgement of a UE result, a defect in each binding
included. The UE cases run only on the owner's machine with UE 5.6 and the fixture project
(`UZP_UE_FIXTURE=1`, decision 028); each starts `UnrealEditor-Cmd` once:

- the shipped preset's PNG 8 and TGA 8 files on the authored set in AO_Mixed's scope import with
  their bindings (BaseColor and Emissive sRGB, ORM linear, Normal as a DirectX normal map);
- its DDS files (BC7_SRGB, BC7, BC5) do not: UE 5.6's DDS importer supports none of those DXGI
  formats (observed, item 3.3);
- item 3.5: after each fixed-name copy is interrupted, before and after each file's rename, UE
  imports at once through the generation-pinning adapter and consumes the one complete selected
  generation; a damaged selected generation fails before UE starts.

The pilots' production exports are imported by `tests/parity/tier1/test_unreal_consumer_pilots.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.export.test_export_publication import KILLED, Fixture, call, one
from tests.export.test_unreal_preset import DDS, PACKED, published
from tools.consumers import unreal
from tools.consumers.gltf import Published

MANIFEST = unreal.REPO_ROOT / "parity/manifests/consumers/unreal/wand-v1.json"
UE_ENV = "UZP_UE_FIXTURE"
needs_ue = pytest.mark.skipif(
    os.environ.get(UE_ENV) != "1" or not unreal.editor_cmd().is_file(),
    reason=f"opt-in local UE 5.6 run: set {UE_ENV}=1 on the owner's machine (decision 028)",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def publication(names: dict[str, str], skipped: tuple[dict[str, Any], ...] = ()) -> Published:
    files = {name: name.encode() for name in names}
    entries = {
        name: {"path": name, "format": fmt, "sha256": sha(name.encode()), "size": [4, 4]}
        for name, fmt in names.items()
    }
    return Published("000003", "r" * 64, files, entries, skipped)


PILOT = {
    "m_s_BaseColor_sRGB.png": "png",
    "m_s_OcclusionRoughnessMetallic_Raw.png": "png",
    "m_s_Normal_Raw.png": "png",
    "m_s_BaseColor_sRGB.dds": "dds",
    "m_s_OcclusionRoughnessMetallic_Raw.dds": "dds",
    "m_s_Normal_Raw.dds": "dds",
    "m_s_SpecularWeight.png": "png",
}


# ── CPU: adapter, project, judgement ────────────────────────────────────────


def test_selected_takes_each_slot_of_its_variant() -> None:
    """PNG/TGA files for `png`, DDS files for `dds`; SpecularWeight is no slot; Emissive is
    optional, the three others are required; two files of one slot are refused."""
    pub = publication(PILOT)
    assert unreal.selected(pub, "png") == {
        "BaseColor": "m_s_BaseColor_sRGB.png",
        "OcclusionRoughnessMetallic": "m_s_OcclusionRoughnessMetallic_Raw.png",
        "Normal": "m_s_Normal_Raw.png",
    }
    assert set(unreal.selected(pub, "dds").values()) == {n for n, f in PILOT.items() if f == "dds"}
    without_normal = {k: v for k, v in PILOT.items() if "Normal" not in k}
    with pytest.raises(ValueError, match="Normal"):
        unreal.selected(publication(without_normal), "png")
    with pytest.raises(ValueError, match="two published BaseColor"):
        unreal.selected(publication(PILOT | {"m_s_BaseColor.tga": "tga"}), "png")


def test_project_is_created_once_and_never_overwritten(tmp_path: Path) -> None:
    first = unreal.ensure_project(tmp_path)
    assert sorted(first["created"]) == sorted(unreal.PROJECT_FILES)
    assert unreal.ensure_project(tmp_path)["created"] == []
    ini = tmp_path / "Config" / "DefaultEngine.ini"
    ini.write_text(ini.read_text(encoding="utf-8") + "[UE.Own]\nKey=1\n", encoding="utf-8")
    assert unreal.ensure_project(tmp_path)["created"] == []  # UE appends its own sections
    text = ini.read_text(encoding="utf-8").replace("AutoLaunch=false", "AutoLaunch=true")
    ini.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to change"):
        unreal.ensure_project(tmp_path)


def test_stage_writes_only_verified_bytes(tmp_path: Path) -> None:
    pub = publication(PILOT)
    names = unreal.selected(pub, "png")
    folder = unreal.stage(pub, names, tmp_path, "wand-v1", "png")
    assert folder == tmp_path / "Import" / "wand-v1" / "png" / "000003"
    assert sorted(p.name for p in folder.iterdir()) == sorted(names.values())
    broken = Published(
        pub.generation,
        pub.receipt_sha256,
        pub.files,
        {k: v | {"sha256": "0" * 64} for k, v in pub.entries.items()},
    )
    with pytest.raises(ValueError, match="differs from its receipt"):
        unreal.stage(broken, names, tmp_path, "wand-v1", "png")
    with pytest.raises(ValueError, match="invalid fixture name"):
        unreal.stage(pub, names, tmp_path, "../x", "png")


def ue_result(names: dict[str, str], variant: str, **changes: Any) -> dict[str, Any]:
    """A UE result that binds every slot as `BINDINGS` says; `changes`: slot -> as_bound keys."""
    textures, links = {}, []
    for slot in names:
        binding = unreal.BINDINGS[variant][slot]
        bound = {
            "class": "Texture2D",
            "srgb": binding["srgb"],
            "compression": binding["compression"],
            "flip_green_channel": False,
            "lod_group": "TEXTUREGROUP_WORLD",
            "size": [4, 4],
        } | changes.get(slot, {})
        path = f"/Game/UzFixture/x/{variant}/T_{slot}.T_{slot}"
        textures[slot] = {
            "imported_object_paths": [path],
            "as_imported": bound,
            "as_bound": bound,
            "source_export": None,
        }
        for output, prop in unreal.LINKS[slot]:
            links.append(
                {
                    "property": prop,
                    "texture": path,
                    "output": output,
                    "sampler": f"SAMPLERTYPE_{binding['sampler'].upper()}",
                }
            )
    return {"status": "imported", "textures": textures, "material": {"links": links}}


def test_judged_passes_the_binding_and_names_each_defect() -> None:
    """A DDS result bound as stated passes (its source is recorded, not judged); an ORM read as
    sRGB, a Normal not compressed as a normal map, a flipped green channel, a link to another
    texture or sampler, and a PNG whose exported source is missing each fail by name."""
    pub = publication(PILOT)
    dds = unreal.selected(pub, "dds")
    assert unreal.judged(ue_result(dds, "dds"), pub, dds, "dds")["failures"] == []
    defects = {
        "OcclusionRoughnessMetallic": {"srgb": True},
        "Normal": {"compression": "TC_DEFAULT", "flip_green_channel": True},
    }
    failures = unreal.judged(ue_result(dds, "dds", **defects), pub, dds, "dds")["failures"]
    assert failures == [
        "OcclusionRoughnessMetallic: srgb",
        "Normal: compression",
        "Normal: green_not_flipped",
    ]
    result = ue_result(dds, "dds")
    result["material"]["links"][1]["texture"] = "/Game/UzFixture/x/dds/T_Normal.T_Normal"
    result["material"]["links"][2]["sampler"] = "SAMPLERTYPE_COLOR"
    failures = unreal.judged(result, pub, dds, "dds")["failures"]
    assert failures == [
        "OcclusionRoughnessMetallic: material_ambient_occlusion",
        "OcclusionRoughnessMetallic: material_roughness",
    ]
    pngs = unreal.selected(pub, "png")
    failures = unreal.judged(ue_result(pngs, "png"), pub, pngs, "png")["failures"]
    assert failures == [f"{s}: source_equals_published" for s in pngs]
    assert unreal.judged({"status": "error", "error": "x"}, pub, pngs, "png")["failures"]
    refused = {
        "status": "refused",
        "refused": ["Normal"],
        "textures": {"Normal": {"file": "n.dds"}},
    }
    verdict = unreal.judged(refused, pub, dds, "dds")
    assert verdict["failures"] == ["Normal: UE 5.6 imported nothing from n.dds"]
    assert verdict["refused"] == [{"slot": "Normal", "file": "n.dds"}]


def test_round_trip_compares_decoded_values(tmp_path: Path) -> None:
    """Equal decoded values, UE's opaque alpha aside, are equal; one changed sample or a lower
    depth is not."""
    import numpy as np

    from tools.parity.feasibility import png

    values = np.arange(4 * 4 * 3, dtype=np.int64).reshape(4, 4, 3) * 1000
    ours = png.encode(values, 16)
    exported = tmp_path / "e.png"
    exported.write_bytes(png.encode(np.dstack([values, np.full((4, 4), 65535)]), 16))
    assert unreal.round_trip(ours, "png", exported)["equal"]
    changed = values.copy()
    changed[1, 2, 0] += 1
    exported.write_bytes(png.encode(changed, 16))
    assert unreal.round_trip(ours, "png", exported)["differing_samples"] == 1
    exported.write_bytes(png.encode(values // 257, 8))
    assert not unreal.round_trip(ours, "png", exported)["equal"]
    grey = np.repeat(values[:, :, :1], 3, axis=2)
    exported.write_bytes(png.encode(grey[:, :, 0], 16))
    trip = unreal.round_trip(png.encode(grey, 16), "png", exported)
    assert trip["equal"] and trip["ue_grey_source"]
    assert not unreal.round_trip(ours, "png", exported)["equal"]


def test_dds_top_mip_is_the_first_level_after_the_dx10_header() -> None:
    header = bytearray(148)
    header[:4], header[84:88] = b"DDS ", b"DX10"
    header[12:16], header[16:20] = (8).to_bytes(4, "little"), (4).to_bytes(4, "little")
    blocks = bytes(range(32))
    assert unreal.dds_top_mip(bytes(header) + blocks + b"mip1") == blocks
    with pytest.raises(ValueError, match="DX10"):
        unreal.dds_top_mip(b"DDS " + bytes(200))


def test_manifest_pins_this_engine_and_project() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == unreal.MANIFEST_SCHEMA
    assert Path(manifest["project_folder"]) == Path("W:/UE_Projects/UzPainterFixture")
    if unreal.editor_cmd().is_file():
        identity = unreal.engine_identity()
        for key in ("version", "changelist", "branch", "build_version_sha256"):
            assert manifest["consumer"][key] == identity[key], key


# ── UE 5.6 (owner's machine) ────────────────────────────────────────────────


def export_root(exe: Path, root: Path, reference: str, **parameters: Any) -> Path:
    """The shipped `reference` published on the authored set in AO_Mixed's scope."""
    code, lines, out = published(exe, root, reference, None, in_scope=True, **parameters)
    assert code == 0 and len(lines) == 1 and "error" not in lines[0], (code, lines)
    return out


@needs_ue
@pytest.mark.parametrize(
    ("reference", "variant", "parameters"),
    [
        (PACKED, "png", {}),
        (PACKED, "png", {"fileFormat": "tga", "bitDepth": "8", "maps": 4}),
    ],
    ids=["png8", "tga8"],
)
def test_ue_imports_the_shipped_preset_with_its_bindings(
    export_tests: Path, tmp_path: Path, reference: str, variant: str, parameters: dict[str, Any]
) -> None:
    """3.2 on the authored set: every map imports with its binding, its source unchanged; the
    SpecularWeight file has no slot and stays the receipt's gap. TGA 8 has no L layout, so its
    export is restricted to Painter's four maps (`maps`)."""
    parameters = dict(parameters)
    if parameters.pop("maps", None):
        out = tga_export(export_tests, tmp_path)
    else:
        out = export_root(export_tests, tmp_path / "export", reference, **parameters)
    fixture = f"authored-{variant}-{parameters.get('fileFormat', 'png')}"
    report = unreal.run_fixture(out, fixture, variant, MANIFEST)
    assert report["status"] == "pass", report["failures"]
    assert set(report["textures"]) == set(unreal.SLOTS)
    if "fileFormat" not in parameters:
        assert {g["channel"] for g in report["consumer_gaps"]} == {"SpecularWeight"}


# UE 5.6's DDS importer (its log, as `run_fixture` reports it): no DX10 BC5 or BC7 file imports.
DDS_REFUSALS = {
    "Error: DDS DXGIFormat not supported : 83 : BC5_UNORM",
    "Error: DDS DXGIFormat not supported : 98 : BC7_UNORM",
    "Error: DDS DXGIFormat not supported : 99 : BC7_UNORM_SRGB",
}


@needs_ue
def test_ue_56_refuses_the_bc7_and_bc5_dds_files(export_tests: Path, tmp_path: Path) -> None:
    """3.3, observed: UE 5.6 imports none of the DDS variant's files. Its default importer
    (Interchange) imports nothing without a message; its legacy TextureFactory, asked only for
    the reason, refuses each DXGI format by name. Every DDS is a valid DX10 BC7_SRGB, BC7 or BC5
    file (Pillow decodes each here), so this is UE's importer, not the file."""
    out = export_root(export_tests, tmp_path / "export", DDS)
    report = unreal.run_fixture(out, "authored-dds", "dds", MANIFEST)
    assert report["status"] == "fail"
    assert {r["slot"] for r in report["refused"]} == set(unreal.SLOTS)
    assert set(report["ue_log_errors"]) >= DDS_REFUSALS, report["ue_log_errors"]
    from PIL import Image

    for dds in out.glob("generations/*/files/*.dds"):
        with Image.open(dds) as image:
            image.load()
            assert image.size == (256, 256), dds


def tga_export(exe: Path, tmp: Path) -> Path:
    from tests.export.test_export_encoders import TEMPLATES
    from tests.export.test_unreal_preset import config
    from tests.export.test_uze_preset import authored_spec

    tmp.mkdir(parents=True, exist_ok=True)
    spec_path = authored_spec(tmp / "spec", in_scope=True)
    out = tmp / "out"
    cfg = config(PACKED, out.as_posix(), fileFormat="tga", bitDepth="8")
    maps = [f"$mesh_$textureSet_{m}(_$colorSpace)(.$udim)" for m in unreal.SLOTS]
    cfg["exportList"] = [{"rootPath": "s0", "filter": {"outputMaps": maps}}]
    path = tmp / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    code, lines, err = call(exe, "publish", str(TEMPLATES), str(spec_path), str(path))
    assert code == 0 and len(lines) == 1 and "error" not in lines[0], (code, lines, err)
    return out


@needs_ue
@pytest.mark.parametrize("point", ["kill_before_fixed_rename", "kill_after_fixed_rename"])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_interrupted_fixed_name_copy_then_ue_import(
    export_tests: Path, tmp_path: Path, point: str, index: int
) -> None:
    """3.5 (EXP-06): A published and copied under fixed names, B published, then B's fixed-name
    copy killed before or after the rename of file `index`; UE imports at once through the
    pinning adapter: it stages and imports exactly B's verified files (the selected complete
    generation), never the half-copied fixed-name directory."""
    fx = Fixture(export_tests, tmp_path)
    assert fx.publish("a")[0] == 0
    fixed = tmp_path / "fixed"
    one(export_tests, "fixed-copy", str(fx.out), str(fixed))
    assert fx.publish("b")[0] == 0
    code, lines, err = call(
        export_tests, "--fault", f"{point}:{index}", "fixed-copy", str(fx.out), str(fixed)
    )
    assert code == KILLED and lines == [], (code, lines, err)
    journal = json.loads((fixed / "fixed-names.journal.json").read_text(encoding="utf-8"))
    assert journal["generation"] == "000002" and len(journal["copied"]) == index
    report = unreal.consume_generation(fx.out, f"interrupted-{point[5:11]}-{index}", MANIFEST)
    assert report["status"] == "imported", report
    assert report["generation"] == "000002"
    assert report["files"] == fx.expected["b"]


@needs_ue
def test_a_damaged_generation_fails_before_ue_starts(export_tests: Path, tmp_path: Path) -> None:
    """3.5: when a file of the selected generation no longer verifies, the adapter refuses before
    anything is staged or UE runs."""
    fx = Fixture(export_tests, tmp_path)
    assert fx.publish("a")[0] == 0
    (fx.out / "generations" / "000001" / "files" / "s0_User0.png").write_bytes(b"damaged")
    staging = unreal.PROJECT_DIR / "Import" / "damaged" / "any" / "000001"
    with pytest.raises(ValueError, match="mismatch"):
        unreal.consume_generation(fx.out, "damaged", MANIFEST)
    assert not staging.exists()
