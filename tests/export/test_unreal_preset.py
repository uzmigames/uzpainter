"""Tests of phase3.2_unreal-ue56-packed-preset (`docs/architecture/08-export.md` §4 Unreal Engine
(Packed); `assets/export-presets/unreal-engine-packed{,-dds}.json`, `src/export/{preset_aliases,
plan,receipt}`; decisions 023, 131 and 322).

Every case runs `uzp-export-tests.exe` on the CPU. No case runs Painter, Unreal Engine or the GPU.

What these cases establish, and what they do not:
- The two shipped presets' own content and provenance, and their refusal before anything is
  planned: no recording of Painter's `Unreal Engine (Packed)` confirms the layout yet (R-322,
  decision 322). So no case here exports a shipped preset, and none is wand v1, Painter-parity or
  UE 5.6 acceptance.
- A test-only copy of the presets (`variant_presets`) whose provenance says `confirmed` and whose
  ORM R reads `documentMap ambientOcclusion` instead of the refused `AO_Mixed` (decision 131):
  the dry run, the DDS companions, the receipts and the SpecularWeight gap. The copy exercises the
  shipped code paths; it is not the shipped preset, and its layout is not confirmed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from jsonschema import Draft202012Validator
from PIL import Image

from tests.export.conftest import REPO_ROOT
from tests.export.test_export_encoders import TEMPLATES
from tests.export.test_export_plan import FULL_CHANNELS, project, refused, texture_set
from tests.export.test_export_presets import resolve, run
from tests.export.test_export_publication import call, consumed
from tests.export.test_uze_preset import authored_spec

PRESETS = REPO_ROOT / "assets" / "export-presets"
PACKED = "unreal-engine-packed"
DDS = "unreal-engine-packed-dds"
PAINTER_NAME = "Unreal Engine (Packed)"
PAINTER_URL = f"resource://starter_assets/{PAINTER_NAME}"
PROVENANCE_SCHEMA = REPO_ROOT / "src" / "export" / "preset-provenance.schema.json"
RECEIPT_SCHEMA = REPO_ROOT / "src" / "export" / "schema" / "receipt.schema.json"
PARAMETERS = {"dithering": False, "paddingAlgorithm": "infinite"}
P = "$mesh_$textureSet"
# 08-export.md §4: map -> its sources (destChannel, srcMapType, srcMapName).
LAYOUT = {
    f"{P}_BaseColor": [
        ("R", "documentMap", "basecolor"),
        ("G", "documentMap", "basecolor"),
        ("B", "documentMap", "basecolor"),
        ("A", "documentMap", "opacity"),
    ],
    f"{P}_OcclusionRoughnessMetallic": [
        ("R", "virtualMap", "AO_Mixed"),
        ("G", "documentMap", "roughness"),
        ("B", "documentMap", "metallic"),
    ],
    f"{P}_Normal": [(c, "virtualMap", "Normal_DirectX") for c in "RGB"],
    f"{P}_Emissive": [(c, "documentMap", "emissive") for c in "RGB"],
    f"{P}_SpecularWeight": [("L", "documentMap", "specularweight")],
}
# Decision 023: map -> (DDS format, mip class); SpecularWeight has no DDS.
DDS_TARGETS = {
    f"{P}_BaseColor": ("BC7_SRGB", "colour"),
    f"{P}_OcclusionRoughnessMetallic": ("BC7", "linear"),
    f"{P}_Normal": ("BC5", "normal"),
    f"{P}_Emissive": ("BC7_SRGB", "colour"),
}
# DXGI_FORMAT of each DDS format (docs/DDS.md).
DXGI = {"BC5": 83, "BC7": 98, "BC7_SRGB": 99}
STEMS = ["BaseColor", "OcclusionRoughnessMetallic", "Normal", "Emissive", "SpecularWeight"]
SKELETON_CHANNELS = FULL_CHANNELS | {"Emissive": "sRGB8"}
SKELETON = project(texture_set("s0", SKELETON_CHANNELS)) | {"mesh": "grid2x2.obj"}


def config(reference: str, out: str = "C:/export", **parameters: Any) -> dict[str, Any]:
    return {
        "exportShaderParams": False,
        "exportPath": out,
        "defaultExportPreset": reference,
        "exportList": [{"rootPath": "s0"}],
        "exportParameters": [{"parameters": PARAMETERS | parameters}],
    }


def plan(
    exe: Path, cases: list[tuple[dict[str, Any], dict[str, Any]]], tmp: Path, presets: Path | None
) -> list[dict[str, Any]]:
    """`uzp-export-tests plan`, the shipped presets read from `presets` when given."""
    extra = {} if presets is None else {"presets": str(presets)}
    path = tmp / "cases.json"
    path.write_text(
        json.dumps([{"project": p, "config": c} | extra for p, c in cases]), encoding="utf-8"
    )
    return run(exe, "plan", str(path))


def variant_presets(root: Path, ao_mixed: bool = False) -> Path:
    """A test-only copy of both presets: provenance layout `confirmed` (so they plan) and, unless
    `ao_mixed`, the ORM's R reading documentMap ambientOcclusion instead of AO_Mixed."""
    root.mkdir(parents=True)
    for preset_id in (PACKED, DDS):
        preset = json.loads((PRESETS / f"{preset_id}.json").read_text(encoding="utf-8"))
        for m in preset["maps"]:
            for c in m["channels"]:
                if c["srcMapName"] == "AO_Mixed" and not ao_mixed:
                    c.update(srcMapType="documentMap", srcMapName="ambientOcclusion")
        (root / f"{preset_id}.json").write_text(json.dumps(preset), encoding="utf-8")
        record = json.loads((PRESETS / f"{preset_id}.provenance.json").read_text(encoding="utf-8"))
        record["parity"]["layout"] = "confirmed"
        (root / f"{preset_id}.provenance.json").write_text(json.dumps(record), encoding="utf-8")
    return root


def listed(result: dict[str, Any]) -> list[str]:
    assert "error" not in result, result
    [[_, _, paths]] = result["list"]
    return [p.removeprefix("C:/export/") for p in paths]


def gaps(entry: dict[str, Any]) -> set[str]:
    return {g["channel"] for g in entry["consumer_gaps"]}


# ── The presets and their provenance (2.2, 2.3, 2.4, 3.6) ────────────────────


def test_unreal_presets_load_unconfirmed(export_tests: Path, tmp_path: Path) -> None:
    """2.3, 2.4, 3.6: the Painter name and its URL resolve to `unreal-engine-packed`; both
    presets load with layout `unconfirmed`, pending R-322; their records validate against the
    provenance schema; an unrecorded `?version=` is refused naming R-322."""
    installed = export_tests.parent / "assets" / "export-presets"
    references = [PAINTER_NAME, PAINTER_URL, PACKED, DDS, f"{PAINTER_URL}?version=1"]
    r = resolve(export_tests, installed, references, tmp_path)
    assert [x.get("id") for x in r[:4]] == [PACKED, PACKED, PACKED, DDS]
    for x in r[:4]:
        assert x["name"] == x["id"] and x["layout"] == "unconfirmed" and x["pending"] == ["R-322"]
        assert x["maps"] == list(LAYOUT)
    assert r[4]["error"] == "NotYetSupported" and "R-322" in r[4]["message"], r[4]
    validator = Draft202012Validator(json.loads(PROVENANCE_SCHEMA.read_text(encoding="utf-8")))
    for preset_id, answers in ((PACKED, [PAINTER_NAME]), (DDS, [])):
        record = json.loads((PRESETS / f"{preset_id}.provenance.json").read_text(encoding="utf-8"))
        assert [e.message for e in validator.iter_errors(record)] == []
        assert record["answersTo"] == answers and record["privateRecords"] == []
        assert record["parity"]["status"] == "pending"
        assert all(p["status"] == "hypothesis" for p in record["packing"])


def test_unreal_preset_packs_the_documented_layout(export_tests: Path, tmp_path: Path) -> None:
    """2.2, 2.6: both presets hold 08-export.md §4's maps; the default one at PNG 8, the DDS
    variant at PNG 16 (each DDS's canonical file) with decision 023's BC targets."""
    for preset_id, depth in ((PACKED, "8"), (DDS, "16")):
        preset = json.loads((PRESETS / f"{preset_id}.json").read_text(encoding="utf-8"))
        assert preset["name"] == preset_id
        assert [m["fileName"] for m in preset["maps"]] == list(LAYOUT)
        for m in preset["maps"]:
            sources = [(c["destChannel"], c["srcMapType"], c["srcMapName"]) for c in m["channels"]]
            assert sources == LAYOUT[m["fileName"]], m["fileName"]
            assert m["parameters"] == {"fileFormat": "png", "bitDepth": depth}
        targets = {t["map"]: (t["format"], t["mips"]) for t in preset.get("dds", [])}
        assert targets == ({} if preset_id == PACKED else DDS_TARGETS)


def test_unreal_presets_are_refused_naming_r322(export_tests: Path, tmp_path: Path) -> None:
    """Decisions 095 and 322: by its Painter name, its URL or its id, named by
    `defaultExportPreset` or an `exportList` entry, each preset is refused before anything is
    planned until R-322 confirms the layout."""
    cases = []
    for reference in (PAINTER_NAME, PAINTER_URL, PACKED, DDS):
        cases.append((SKELETON, config(reference)))
        entry = config("assets3d-inline-five-map")
        entry["exportList"] = [{"rootPath": "s0", "exportPreset": reference}]
        cases.append((SKELETON, entry))
    for result in plan(export_tests, cases, tmp_path, None):
        refused(
            result,
            "NotYetSupported",
            "no recording of Painter's output confirms its layout",
            "R-322",
            "decision 095",
        )


# ── The plan on the test-only copy (2.2, 2.6, 2.7, 2.10) ─────────────────────


def test_variant_dry_run_lists_the_png8_maps(export_tests: Path, tmp_path: Path) -> None:
    """The dry run of the default preset's copy lists its five PNG 8 maps named
    `$mesh_$textureSet_<map>`, with the colour each one stores; no DDS."""
    presets = variant_presets(tmp_path / "presets")
    [result] = plan(export_tests, [(SKELETON, config(PACKED))], tmp_path, presets)
    assert listed(result) == [f"grid2x2_s0_{stem}.png" for stem in STEMS]
    for f in result["plan"]["files"]:
        assert (f["parameters"]["fileFormat"], f["parameters"]["bitDepth"]) == ("png", "8")
        assert "dds" not in f


def test_dds_variant_lists_each_dds_after_its_png16(export_tests: Path, tmp_path: Path) -> None:
    """2.6: the DDS variant's dry run lists each DDS right after its PNG 16 canonical file, and
    the plan states its format, colour transfer, mip class and canonical file; SpecularWeight has
    no DDS."""
    presets = variant_presets(tmp_path / "presets")
    [result] = plan(export_tests, [(SKELETON, config(DDS))], tmp_path, presets)
    expected = []
    for stem in STEMS:
        expected.append(f"grid2x2_s0_{stem}.png")
        if stem != "SpecularWeight":
            expected.append(f"grid2x2_s0_{stem}.dds")
    assert listed(result) == expected
    for f in result["plan"]["files"]:
        assert f["parameters"]["bitDepth"] == "16"
        if f["fileName"] not in DDS_TARGETS:
            assert "dds" not in f
            continue
        fmt, mips = DDS_TARGETS[f["fileName"]]
        assert f["dds"] == {
            "relativePath": f["relativePath"].removesuffix(".png") + ".dds",
            "path": f["path"].removesuffix(".png") + ".dds",
            "canonical": f["relativePath"],
            "format": fmt,
            "srgb": fmt == "BC7_SRGB",
            "mips": mips,
        }


def test_ao_mixed_stays_refused_in_the_variant(export_tests: Path, tmp_path: Path) -> None:
    """2.10, decision 131: with the layout check lifted (test-only copy) but the ORM still reading
    AO_Mixed, both presets are refused before anything is written, naming item 2.10."""
    presets = variant_presets(tmp_path / "presets", ao_mixed=True)
    out = tmp_path / "out"
    cases = [(SKELETON, config(p, out.as_posix())) for p in (PACKED, DDS)]
    for result in plan(export_tests, cases, tmp_path, presets):
        refused(
            result, "NotYetSupported", '"AO_Mixed"', "phase3.2_unreal-ue56-packed-preset item 2.10"
        )
    assert not out.exists()


def test_specularweight_is_a_separate_map_and_a_consumer_gap(
    export_tests: Path, tmp_path: Path
) -> None:
    """2.7: `_SpecularWeight` is written when the stack has the channel and is absent otherwise;
    the receipt lists it as a SpecularWeight consumer gap whose mapping the export does not apply
    (`receipt` builds it without evaluation: no template gives SpecularWeight a base)."""
    presets = variant_presets(tmp_path / "presets")
    without = project(
        texture_set("s0", {k: v for k, v in SKELETON_CHANNELS.items() if k != "SpecularWeight"})
    ) | {"mesh": "grid2x2.obj"}
    _, absent = plan(
        export_tests, [(SKELETON, config(PACKED)), (without, config(PACKED))], tmp_path, presets
    )
    assert listed(absent) == [f"grid2x2_s0_{stem}.png" for stem in STEMS[:-1]]
    [skipped] = [s for s in absent["plan"]["skipped"] if s["fileName"] == f"{P}_SpecularWeight"]
    assert skipped["kind"] == "absent"
    (tmp_path / "skeleton.json").write_text(json.dumps(SKELETON), encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps(config(PACKED)), encoding="utf-8")
    [receipt] = run(
        export_tests,
        "receipt",
        str(tmp_path / "skeleton.json"),
        str(tmp_path / "config.json"),
        str(presets),
    )
    jsonschema.validate(receipt, json.loads(RECEIPT_SCHEMA.read_text(encoding="utf-8")))
    files = {f["path"]: f for f in receipt["files"]}
    entry = files["grid2x2_s0_SpecularWeight.png"]
    assert entry["bit_depth"] == "8" and entry["colour_space"] == "linear"
    assert gaps(entry) == {"SpecularWeight"}
    [gap] = entry["consumer_gaps"]
    assert "0.5 x SpecularWeight" in gap["gap"] and "not applied by the export" in gap["gap"]
    assert (
        f"grid2x2_s0_SpecularWeight.png: {gap['gap']}" in receipt["manifest_export"]["open_items"]
    )
    for stem in STEMS[:-1]:
        assert gaps(files[f"grid2x2_s0_{stem}.png"]) == set(), stem


def test_tga_is_refused_naming_r322(export_tests: Path, tmp_path: Path) -> None:
    """2.5: TGA stays refused before writing, naming item 2.5 and R-322.
    Painter-compatible TGA processing and files have not been recorded or admitted.
    The native quantized-byte writer does not establish that compatibility."""
    presets = variant_presets(tmp_path / "presets")
    out = tmp_path / "out"
    [result] = plan(
        export_tests,
        [(SKELETON, config(PACKED, out.as_posix(), fileFormat="tga"))],
        tmp_path,
        presets,
    )
    refused(result, "NotYetSupported", '"tga"', "item 2.5", "R-322")
    assert not out.exists()


def test_dds_targets_are_checked(export_tests: Path, tmp_path: Path) -> None:
    """2.6: an inline preset cannot carry `dds`; a shipped preset's targets must name its maps and
    pair BC5 with normal mips and BC7_SRGB with colour mips; a colour target whose canonical file
    stores linear values is refused, not converted."""
    inline = config("p")
    inline["exportPresets"] = [
        {"name": "p", "maps": [], "dds": [{"map": "x", "format": "BC7", "mips": "linear"}]}
    ]
    linear = project(texture_set("s0", FULL_CHANNELS | {"BaseColor": "RGB16F"})) | {
        "mesh": "grid2x2.obj"
    }
    presets = variant_presets(tmp_path / "presets")
    a, b = plan(export_tests, [(SKELETON, inline), (linear, config(DDS))], tmp_path, presets)
    refused(a, "NotYetSupported", 'the key "dds" is not documented')
    refused(b, "NotYetSupported", "implicit colour conversion", "item 2.6")
    preset = json.loads((presets / f"{DDS}.json").read_text(encoding="utf-8"))
    broken = [
        ({"map": f"{P}_Normal", "format": "BC5", "mips": "linear"}, "BC5 goes with normal mips"),
        ({"map": f"{P}_BaseColor", "format": "BC7_SRGB", "mips": "linear"}, "BC7_SRGB goes with"),
        ({"map": f"{P}_Emissive", "format": "BC7", "mips": "colour"}, "BC7_SRGB goes with"),
        ({"map": "$textureSet_x", "format": "BC7", "mips": "linear"}, 'no map "$textureSet_x"'),
        ({"map": f"{P}_Emissive", "format": "BC3", "mips": "linear"}, "is not BC5, BC7"),
    ]
    for n, (target, fragment) in enumerate(broken):
        directory = tmp_path / f"broken{n}"
        shutil.copytree(presets, directory)
        (directory / f"{DDS}.json").write_text(
            json.dumps(preset | {"dds": [target]}), encoding="utf-8"
        )
        [loaded] = resolve(export_tests, directory, [DDS], tmp_path)
        assert loaded["error"] == "ManifestError" and fragment in loaded["message"], loaded


# ── Publication on an authored texture set (2.6, 2.7) ────────────────────────


@pytest.fixture(scope="module")
def published_dds(export_tests: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("ue-dds")
    presets = variant_presets(tmp / "presets")
    spec_path = authored_spec(tmp / "spec")
    out = tmp / "out"
    path = tmp / "config.json"
    path.write_text(json.dumps(config(DDS, out.as_posix())), encoding="utf-8")
    code, lines, err = call(
        export_tests,
        "publish",
        str(TEMPLATES),
        str(spec_path),
        str(path),
        "--presets",
        str(presets),
    )
    assert code == 0 and len(lines) == 1 and "error" not in lines[0], (code, lines, err)
    selected = consumed(export_tests, out)
    assert "error" not in selected, selected
    generation = out / "generations" / selected["generation"]
    receipt = json.loads((generation / "receipt.json").read_text(encoding="utf-8"))
    jsonschema.validate(receipt, json.loads(RECEIPT_SCHEMA.read_text(encoding="utf-8")))
    return {"generation": generation, "receipt": receipt, "selected": selected}


def test_dds_variant_publishes_receipts_with_the_cook_gap(published_dds: dict[str, Any]) -> None:
    """2.6: on an authored set (every channel but SpecularWeight, full UV coverage) the DDS
    variant's copy publishes each PNG 16 and its DDS; every file's hash is the receipt's and the
    pinned consumer's. Each DDS states its BC format, transfer, mip chain and canonical source,
    is stored as its DXGI format with a full chain an independent decoder opens, and carries the
    cook gap: UE 5.6 BC pass-through through cooking is undocumented (item 3.3)."""
    generation, receipt = published_dds["generation"], published_dds["receipt"]
    files = {f["path"]: f for f in receipt["files"]}
    for entry in receipt["files"]:
        data = (generation / "files" / entry["path"]).read_bytes()
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert entry["sha256"] == published_dds["selected"]["files"][entry["path"]]
    names = [f["path"] for f in receipt["files"]]
    expected = []
    for stem in STEMS[:-1]:
        expected += [f"grid2x2_s0_{stem}.png", f"grid2x2_s0_{stem}.dds"]
    assert names == expected
    colour = {
        "BaseColor": "sRGB",
        "OcclusionRoughnessMetallic": "linear",
        "Normal": "linear",
        "Emissive": "sRGB",
    }
    for stem, space in colour.items():
        png_entry = files[f"grid2x2_s0_{stem}.png"]
        assert png_entry["bit_depth"] == "16" and png_entry["colour_space"] == space, stem
        dds_entry = files[f"grid2x2_s0_{stem}.dds"]
        fmt, _ = DDS_TARGETS[f"{P}_{stem}"]
        dds = dds_entry["dds"]
        assert dds["source"] == png_entry["path"] and dds["format"] == fmt
        assert dds["srgb"] is (fmt == "BC7_SRGB") and dds["lossy"] is True
        assert dds["mips"] == 9  # 256 x 256 down to 1 x 1
        assert dds["stored_channels"] == (["R", "G"] if fmt == "BC5" else ["R", "G", "B", "A"])
        assert dds_entry["colour_space"] == space and gaps(dds_entry) == {"cook"}, stem
        assert "item 3.3" in dds_entry["consumer_gaps"][0]["gap"]
        data = (generation / "files" / dds_entry["path"]).read_bytes()
        assert data[:4] == b"DDS " and struct.unpack_from("<I", data, 128)[0] == DXGI[fmt]
        with Image.open(generation / "files" / dds_entry["path"]) as image:
            assert image.size == (256, 256)
            image.load()
    assert files["grid2x2_s0_BaseColor.png"]["layout"] == "RGBA"
