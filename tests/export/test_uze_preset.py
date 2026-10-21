"""Tests of phase3.2_uze-uzmat-preset (`docs/architecture/08-export.md` §4 UzEngine preset, §5;
`assets/export-presets/uzengine.json`, `src/export/{preset_aliases,plan,write,publish,receipt}`;
EXP-06, EXP-10, INT-21, decision 200).

Every case runs `uzp-export-tests.exe` on the CPU. No case runs Painter, UzEngine or the GPU.

What these cases establish, and what they do not:
- The shipped preset's own content, its targets and its provenance record (CPU lane, decision 200).
- The full shipped preset is refused before anything is planned: its `<set>_orm` reads `AO_Mixed`,
  which is not fitted (decision 131). So no case here exports the full shipped preset, and none of
  them is wand v1 acceptance.
- The shipped preset with its ORM maps filtered out, on an authored texture set: canonical maps,
  derivatives, receipts and gaps.
- A test-only variant of the preset, whose ORM R reads `documentMap ambientOcclusion`: the
  `.uzmat` and the interruption of every `.uztexture` and `.uzmat` write. The variant exercises the
  same code; it is not the shipped preset.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
from pathlib import Path
from typing import Any

import jsonschema
import numpy as np
import pytest
from jsonschema import Draft202012Validator

from tests.export.conftest import REPO_ROOT
from tests.export.test_export_encoders import GRID, TEMPLATES, ramp_png, run
from tests.export.test_export_plan import FULL_CHANNELS, plan_many, project, refused, texture_set
from tests.export.test_export_presets import resolve
from tests.export.test_export_publication import KILLED, call, consumed, one
from tools.parity.feasibility import png

PRESETS = REPO_ROOT / "assets" / "export-presets"
PRESET = PRESETS / "uzengine.json"
RECORD = PRESETS / "uzengine.provenance.json"
PROVENANCE_SCHEMA = REPO_ROOT / "src" / "export" / "preset-provenance.schema.json"
RECEIPT_SCHEMA = REPO_ROOT / "src" / "export" / "schema" / "receipt.schema.json"
SIZE = 256
UZTEXTURE_MAGIC = 0x5A585455
# uztexture_format.h TextureFormat values and the sRGB flag.
FORMAT_CODES = {"BC5": 3, "BC7": 4, "BC4": 5, "RGBA8": 0}
SRGB_FLAG = 1
PARAMETERS = {"dithering": False, "paddingAlgorithm": "infinite"}
# Every output except the ORM maps, whose R reads the refused AO_Mixed (decision 131).
WITHOUT_ORM = [
    "$textureSet_albedo",
    "canonical/$textureSet_albedo",
    "$textureSet_normal",
    "$textureSet_emissive",
    "canonical/$textureSet_emissive",
    "$textureSet_height",
    "$textureSet_specularweight",
    "$textureSet",
]
# The table of 08-export.md §4: delivered map ->
# (PNG bit depth, canonical map, format, sRGB, binding).
TABLE = {
    "$textureSet_albedo": ("8", "canonical/$textureSet_albedo", "BC7", True, "albedo"),
    "$textureSet_normal": ("16", "$textureSet_normal", "BC5", False, "normal"),
    "$textureSet_orm": ("8", "canonical/$textureSet_orm", "BC7", False, "orm"),
    "$textureSet_emissive": ("8", "canonical/$textureSet_emissive", "BC7", True, "emissive"),
    "$textureSet_height": ("16", "$textureSet_height", "BC4", False, "heightmap"),
    "$textureSet_specularweight": ("16", "$textureSet_specularweight", "BC4", False, None),
}
SKELETON = project(texture_set("s0", FULL_CHANNELS | {"Emissive": "sRGB8"}))


def shipped_config(out: str, output_maps: list[str] | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"rootPath": "s0"}
    if output_maps is not None:
        entry["filter"] = {"outputMaps": output_maps}
    return {
        "exportShaderParams": False,
        "exportPath": out,
        "defaultExportPreset": "uzengine",
        "exportList": [entry],
        "exportParameters": [{"parameters": PARAMETERS}],
    }


# ── The preset and its provenance (2.2, 2.8, 3.6) ────────────────────────────


def test_shipped_preset_loads_with_its_targets(export_tests: Path, tmp_path: Path) -> None:
    """2.2: the shipped preset holds the table's six maps with its engine targets, three PNG 16
    canonical companions of its PNG 8 maps, and the `.uzmat`; it loads with layout `consumer`."""
    [loaded] = resolve(export_tests, PRESETS, ["uzengine"], tmp_path)
    assert "error" not in loaded, loaded
    assert loaded["id"] == "uzengine" and loaded["layout"] == "consumer"
    preset = json.loads(PRESET.read_text(encoding="utf-8"))
    maps = {m["fileName"]: m for m in preset["maps"]}
    assert loaded["maps"] == [m["fileName"] for m in preset["maps"]]
    textures = {t["map"]: t for t in preset["uzengine"]["textures"]}
    assert sorted(textures) == sorted(TABLE)
    for name, (depth, canonical, fmt, srgb, binding) in TABLE.items():
        t = textures[name]
        assert (t["canonical"], t["format"], t["srgb"], t["binding"]) == (
            canonical,
            fmt,
            srgb,
            binding,
        )
        assert maps[name]["parameters"] == {"fileFormat": "png", "bitDepth": depth}
        assert maps[canonical]["parameters"] == {"fileFormat": "png", "bitDepth": "16"}
        assert maps[canonical]["channels"] == maps[name]["channels"]
    assert textures["$textureSet_normal"]["negativeZ"] == "fail"
    assert textures["$textureSet_albedo"]["mips"] == "masked_colour"

    def sources(name: str) -> list[tuple[str, str, str]]:
        return [
            (c["destChannel"], c["srcMapType"], c["srcMapName"]) for c in maps[name]["channels"]
        ]

    assert sources("$textureSet_albedo") == [
        ("R", "documentMap", "basecolor"),
        ("G", "documentMap", "basecolor"),
        ("B", "documentMap", "basecolor"),
        ("A", "documentMap", "opacity"),
    ]
    # phase0.9: UzEngine reads green as -v (parity/reports/phase0/normal-convention.md §8).
    assert sources("$textureSet_normal") == [(c, "virtualMap", "Normal_DirectX") for c in "RGB"]
    assert sources("$textureSet_orm") == [
        ("R", "virtualMap", "AO_Mixed"),
        ("G", "documentMap", "roughness"),
        ("B", "documentMap", "metallic"),
    ]
    assert sources("$textureSet_emissive") == [(c, "documentMap", "emissive") for c in "RGB"]
    assert sources("$textureSet_height") == [("L", "documentMap", "height")]
    assert sources("$textureSet_specularweight") == [("L", "documentMap", "specularweight")]
    assert preset["uzengine"]["material"] == {
        "fileName": "$textureSet",
        "albedo": "$textureSet_albedo",
        "normal": "$textureSet_normal",
        "orm": "$textureSet_orm",
        "emissive": "$textureSet_emissive",
        "height": "$textureSet_height",
    }


def test_provenance_validates_and_names_the_preset(export_tests: Path, tmp_path: Path) -> None:
    """3.6 (decision 200, CPU lane): the record validates against its schema and pends on AO_Mixed;
    without it the preset fails naming `uzengine`; an inline preset cannot carry the targets."""
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    validator = Draft202012Validator(json.loads(PROVENANCE_SCHEMA.read_text(encoding="utf-8")))
    assert [e.message for e in validator.iter_errors(record)] == []
    assert record["preset"] == "uzengine" and record["parity"]["layout"] == "consumer"
    assert [p["recording"] for p in record["parity"]["pending"]] == ["R-131"]
    copy = tmp_path / "presets"
    shutil.copytree(PRESETS, copy)
    (copy / "uzengine.provenance.json").unlink()
    [missing] = resolve(export_tests, copy, ["uzengine"], tmp_path)
    assert missing["error"] == "ManifestError", missing
    assert "uzengine" in missing["message"] and "provenance record" in missing["message"]
    preset = json.loads(PRESET.read_text(encoding="utf-8"))
    preset["name"] = "inline"
    config = shipped_config("C:/export")
    config["defaultExportPreset"] = "inline"
    config["exportPresets"] = [preset]
    [inline] = plan_many(export_tests, [(SKELETON, config)], tmp_path)
    refused(inline, "NotYetSupported", '"uzengine"', "not documented")


# ── Plan and dry run (2.9, 3.1 partial) ──────────────────────────────────────


def test_full_preset_is_refused_naming_ao_mixed(export_tests: Path, tmp_path: Path) -> None:
    """The full shipped preset is refused before anything is planned: `<set>_orm` reads AO_Mixed,
    whose owner is phase3.2_unreal-ue56-packed-preset item 2.10 (decision 131)."""
    [result] = plan_many(export_tests, [(SKELETON, shipped_config("C:/export"))], tmp_path)
    refused(result, "NotYetSupported", '"AO_Mixed"', "phase3.2_unreal-ue56-packed-preset item 2.10")


def test_dry_run_lists_outputs_with_formats(export_tests: Path, tmp_path: Path) -> None:
    """With the ORM maps filtered out, the dry run lists every other output, each derivative after
    its file, and the plan states each one's format, colour space, binding and canonical map; the
    `.uzmat` is not written and is listed as skipped, naming the ORM."""
    [result] = plan_many(
        export_tests, [(SKELETON, shipped_config("C:/export", WITHOUT_ORM))], tmp_path
    )
    assert "error" not in result, result
    [[_, _, listed]] = result["list"]
    assert [p.removeprefix("C:/export/") for p in listed] == [
        "s0_albedo.png",
        "s0_albedo.uztexture",
        "canonical/s0_albedo.png",
        "s0_normal.png",
        "s0_normal.uztexture",
        "s0_emissive.png",
        "s0_emissive.uztexture",
        "canonical/s0_emissive.png",
        "s0_height.png",
        "s0_height.uztexture",
        "s0_specularweight.png",
        "s0_specularweight.uztexture",
    ]
    plan = result["plan"]
    files = {f["fileName"]: f for f in plan["files"]}
    for name, (depth, canonical, fmt, srgb, binding) in TABLE.items():
        if name == "$textureSet_orm":
            continue
        f = files[name]
        assert (f["parameters"]["fileFormat"], f["parameters"]["bitDepth"]) == ("png", depth)
        derivative = f["uztexture"]
        assert derivative["format"] == fmt and derivative["srgb"] is srgb
        assert derivative["binding"] == binding
        assert derivative["canonical"] == files[canonical]["relativePath"]
        assert ("negativeZ" in derivative) == (fmt == "BC5")
    assert "materials" not in plan
    [skipped] = [s for s in plan["skipped"] if s["fileName"] == "$textureSet"]
    assert skipped["kind"] == "absent" and "$textureSet_orm" in skipped["reason"]


def test_canonical_map_filtered_out_is_invalid(export_tests: Path, tmp_path: Path) -> None:
    """A derivative is always written beside its canonical map (EXP-10): a filter that keeps a
    delivered map and drops its canonical map is invalid."""
    maps = [m for m in WITHOUT_ORM if m != "canonical/$textureSet_albedo"]
    [result] = plan_many(export_tests, [(SKELETON, shipped_config("C:/export", maps))], tmp_path)
    refused(result, "ValueError", "canonical/$textureSet_albedo", "EXP-10")


def test_linear_basecolor_is_refused_for_an_srgb_texture(
    export_tests: Path, tmp_path: Path
) -> None:
    """The derivative's declared colour space must be what the canonical file stores: a BaseColor
    stored linear (RGB16F) is not converted to the declared BC7 sRGB; the plan refuses it."""
    channels = FULL_CHANNELS | {"Emissive": "sRGB8", "BaseColor": "RGB16F"}
    [result] = plan_many(
        export_tests,
        [(project(texture_set("s0", channels)), shipped_config("C:/export", WITHOUT_ORM))],
        tmp_path,
    )
    refused(
        result, "NotYetSupported", "written linear", "declared sRGB", "phase3.4_uzengine-preset"
    )


# ── Publication on an authored texture set ──────────────────────────────────


def authored_spec(root: Path) -> Path:
    """Every channel the preset reads but SpecularWeight, filled from the 16-bit ramp (opacity
    varies, so the albedo keeps its alpha), on the grid mesh (full UV coverage)."""
    root.mkdir(parents=True, exist_ok=True)
    sha = ramp_png(root / "ramp.png")
    bitmap = {"bitmap": sha, "color_space": "Raw"}
    channels = {
        "BaseColor": "sRGB8",
        "Opacity": "L8",
        "SpecularRoughness": "L16",
        "BaseMetalness": "L8",
        "AO": "L16",
        "Emissive": "sRGB8",
        "Height": "L16F",
        "Normal": "RGB16F",
    }
    document = {
        "name": "s0",
        # A template with an Opacity base (no shipped template or channel default has a
        # SpecularWeight base, so the authored set has no SpecularWeight channel).
        "template": "pbr-metallic-roughness-alpha-test",
        "resolution": [SIZE, SIZE],
        "mesh": str(GRID),
        "channels": [{"type": t, "format": f} for t, f in channels.items()],
        "resources": [{"sha256": sha, "png": "ramp.png"}],
        "layers": [{"kind": "fill", "sources": {t: bitmap for t in channels if t != "Normal"}}],
    }
    path = root / "spec.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def variant_presets(root: Path) -> Path:
    """A test-only copy of the shipped preset whose ORM R reads documentMap ambientOcclusion
    instead of the refused AO_Mixed (decision 131); nothing else differs."""
    root.mkdir(parents=True)
    preset = json.loads(PRESET.read_text(encoding="utf-8"))
    for m in preset["maps"]:
        for c in m["channels"]:
            if c["srcMapName"] == "AO_Mixed":
                c.update(srcMapType="documentMap", srcMapName="ambientOcclusion")
    (root / "uzengine.json").write_text(json.dumps(preset, indent=2), encoding="utf-8")
    shutil.copy(RECORD, root / "uzengine.provenance.json")
    return root


def publish(
    exe: Path,
    spec_path: Path,
    config: dict[str, Any],
    tmp: Path,
    presets: Path | None = None,
    fault: str | None = None,
) -> tuple[int, list[dict[str, Any]], str]:
    path = tmp / f"config-{hashlib.sha256(json.dumps(config).encode()).hexdigest()[:8]}.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    args = ["--fault", fault] if fault else []
    extra = ["--presets", str(presets)] if presets else []
    return call(exe, *args, "publish", str(TEMPLATES), str(spec_path), str(path), *extra)


def published(exe: Path, out: Path) -> tuple[Path, dict[str, Any]]:
    """The selected generation and its receipt, every file checked against it."""
    selected = consumed(exe, out)
    assert "error" not in selected, selected
    generation = out / "generations" / selected["generation"]
    receipt: dict[str, Any] = json.loads((generation / "receipt.json").read_text(encoding="utf-8"))
    jsonschema.validate(receipt, json.loads(RECEIPT_SCHEMA.read_text(encoding="utf-8")))
    for entry in receipt["files"]:
        data = (generation / "files" / entry["path"]).read_bytes()
        assert len(data) == entry["bytes"]
        assert (
            hashlib.sha256(data).hexdigest() == entry["sha256"] == selected["files"][entry["path"]]
        )
    return generation, receipt


def header(data: bytes) -> tuple[int, ...]:
    return struct.unpack_from("<16I", data)


def gaps(entry: dict[str, Any]) -> set[str]:
    return {g["channel"] for g in entry["consumer_gaps"]}


@pytest.fixture(scope="module")
def filtered(export_tests: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    tmp = tmp_path_factory.mktemp("uze-filtered")
    spec_path = authored_spec(tmp / "spec")
    out = tmp / "out"
    code, lines, err = publish(
        export_tests, spec_path, shipped_config(out.as_posix(), WITHOUT_ORM), tmp
    )
    assert code == 0 and len(lines) == 1 and "error" not in lines[0], (code, lines, err)
    return out, published(export_tests, out)


def test_receipt_lists_formats_bindings_and_gaps(filtered: tuple[Path, Any]) -> None:
    """With the shipped preset (ORM filtered out), every file of the receipt has its hash, size,
    format, colour space and bit depth; every derivative has its engine format, binding and
    canonical map, and its header agrees; SM5 opacity and height are consumer gaps."""
    _, (generation, receipt) = filtered
    files = {f["path"]: f for f in receipt["files"]}
    assert list(files) == [
        "s0_albedo.png",
        "s0_albedo.uztexture",
        "canonical/s0_albedo.png",
        "s0_normal.png",
        "s0_normal.uztexture",
        "s0_emissive.png",
        "s0_emissive.uztexture",
        "canonical/s0_emissive.png",
        "s0_height.png",
        "s0_height.uztexture",
    ]
    expected = {
        "s0_albedo": ("canonical/s0_albedo.png", "BC7", True, "albedo", "RGBA"),
        "s0_normal": ("s0_normal.png", "BC5", False, "normal", "RGB"),
        "s0_emissive": ("canonical/s0_emissive.png", "BC7", True, "emissive", "RGB"),
        "s0_height": ("s0_height.png", "BC4", False, "heightmap", "L"),
    }
    for stem, (canonical, fmt, srgb, binding, layout) in expected.items():
        entry = files[f"{stem}.uztexture"]
        meta = entry["uztexture"]
        assert (
            meta["source"],
            meta["delivery"],
            meta["format"],
            meta["srgb"],
            meta["binding"],
        ) == (
            canonical,
            f"{stem}.png",
            fmt,
            srgb,
            binding,
        )
        assert entry["colour_space"] == ("sRGB" if srgb else "linear") and entry["layout"] == layout
        assert files[canonical]["bit_depth"] == "16" and files[canonical]["layout"] == layout
        data = (generation / "files" / f"{stem}.uztexture").read_bytes()
        h = header(data)
        assert h[0] == UZTEXTURE_MAGIC and h[2:4] == (SIZE, SIZE) and h[4] == meta["mips"] == 9
        assert h[5] == FORMAT_CODES[fmt] and h[6] == (SRGB_FLAG if srgb else 0)
        assert (meta["negative_z"] is None) == (fmt != "BC5")
    assert files["s0_normal.uztexture"]["uztexture"]["negative_z"] == {
        "policy": "fail",
        "texels": 0,
        "first": None,
        "routed": False,
    }
    assert files["s0_normal.png"]["normal"]["role"] == "combined"
    assert files["s0_normal.uztexture"]["normal"]["role"] == "combined"
    for name in ("s0_albedo.png", "s0_emissive.png"):
        assert files[name]["bit_depth"] == "8"
    # 2.5: opacity rides in the albedo alpha (RGBA canonical and derivative above), and the SM5
    # route is reported unsupported for it on the albedo derivative and in the manifest block.
    assert gaps(files["s0_albedo.uztexture"]) == {"Opacity"}
    [opacity] = files["s0_albedo.uztexture"]["consumer_gaps"]
    assert "albedo alpha" in opacity["gap"] and "SM5" in opacity["gap"]
    assert "unsupported" in opacity["gap"]
    assert gaps(files["s0_height.uztexture"]) == {"Height"}
    # The authored set has no SpecularWeight channel (no template gives its base): the map is
    # absent, and its gap is checked by test_specularweight_is_a_consumer_gap.
    assert {s["file_name"] for s in receipt["skipped"]} >= {"$textureSet_specularweight"}
    open_items = receipt["manifest_export"]["open_items"]
    assert any("SM5" in item for item in open_items)
    assert any(item.startswith("s0 $textureSet: not written") for item in open_items)


def test_colour_space_states_each_channel(filtered: tuple[Path, Any]) -> None:
    """EXP-10: the receipt's colour space is what each file stores: the sRGB8 BaseColor and
    Emissive PNGs sRGB-encoded with a linear alpha, the normal and height linear."""
    _, (_, receipt) = filtered
    files = {f["path"]: f for f in receipt["files"]}
    for name in ("s0_albedo.png", "canonical/s0_albedo.png"):
        assert files[name]["colour_space"] == "sRGB"
        assert [c["transfer"] for c in files[name]["channels"]] == [
            "sRGB",
            "sRGB",
            "sRGB",
            "linear",
        ]
    for name in ("s0_normal.png", "s0_height.png"):
        assert files[name]["colour_space"] == "linear"
        assert {c["transfer"] for c in files[name]["channels"]} == {"linear"}
    maps = receipt["manifest_export"]["maps"]
    assert maps[files["s0_albedo.png"]["key"]]["color_space"] == "sRGB"


def test_derivatives_are_cooked_from_the_canonical_samples(filtered: tuple[Path, Any]) -> None:
    """The canonical PNG 16 is written beside the PNG 8 file, holding the same channels at 16
    bits (the PNG 8 code is the canonical code rounded to 8 bits for the linear alpha and within
    one code for the sRGB colour), and the RGBA8-free BC4 height derivative decodes to the
    canonical map's 8-bit quantisation within BC4's error."""
    _, (generation, _) = filtered
    canonical = png.decode((generation / "files" / "canonical/s0_albedo.png").read_bytes())
    delivered = png.decode((generation / "files" / "s0_albedo.png").read_bytes())
    assert canonical.shape == delivered.shape == (SIZE, SIZE, 4)
    alpha16 = canonical[..., 3].astype(np.int64)
    assert np.array_equal(np.round(alpha16 / 257), delivered[..., 3].astype(np.int64))
    colour = np.abs(np.round(canonical[..., :3].astype(np.int64) / 257) - delivered[..., :3])
    assert int(colour.max()) <= 1
    height = png.decode((generation / "files" / "s0_height.png").read_bytes()).reshape(SIZE, SIZE)
    data = (generation / "files" / "s0_height.uztexture").read_bytes()
    offset, size, width, rows = struct.unpack_from("<QQII", data, 64)
    assert (width, rows, size) == (SIZE, SIZE, (SIZE // 4) * (SIZE // 4) * 8)
    blocks = np.frombuffer(data, dtype=np.uint8, count=size, offset=offset).reshape(-1, 8)
    # BC4 block endpoints bound the block's codes: each 4x4 block's 8-bit quantised canonical codes
    # lie within [min(e0, e1), max(e0, e1)].
    quantised = np.round(height.astype(np.int64) / 257)
    for index, block in enumerate(blocks[:: max(1, len(blocks) // 64)]):
        bi = index * max(1, len(blocks) // 64)
        by, bx = divmod(bi, SIZE // 4)
        tile = quantised[by * 4 : by * 4 + 4, bx * 4 : bx * 4 + 4]
        low, high = sorted((int(block[0]), int(block[1])))
        assert low <= int(tile.min()) and int(tile.max()) <= high, (bi, low, high, tile)


def test_canonical_maps_equal_the_png_route(
    export_tests: Path, tmp_path: Path, filtered: tuple[Path, Any]
) -> None:
    """Authored evidence for item 3.3 (not wand v1): each canonical map's bytes equal the same
    channels exported at PNG 16 through an inline preset of the proven PNG route."""
    _, (generation, _) = filtered
    preset = json.loads(PRESET.read_text(encoding="utf-8"))
    wanted = [
        "canonical/$textureSet_albedo",
        "canonical/$textureSet_emissive",
        "$textureSet_normal",
        "$textureSet_height",
        "$textureSet_specularweight",
    ]
    maps = [
        {"fileName": "png/" + m["fileName"].replace("canonical/", ""), "channels": m["channels"]}
        for m in preset["maps"]
        if m["fileName"] in wanted
    ]
    out = tmp_path / "png-route"
    config = {
        "exportShaderParams": False,
        "exportPath": out.as_posix(),
        "defaultExportPreset": "png16",
        "exportPresets": [{"name": "png16", "maps": maps}],
        "exportList": [{"rootPath": "s0"}],
        "exportParameters": [{"parameters": PARAMETERS | {"fileFormat": "png", "bitDepth": "16"}}],
    }
    spec_path = authored_spec(tmp_path / "spec")
    code, lines, err = publish(export_tests, spec_path, config, tmp_path)
    assert code == 0 and "error" not in lines[0], (code, lines, err)
    reference, _ = published(export_tests, out)
    pairs = {
        "canonical/s0_albedo.png": "png/s0_albedo.png",
        "canonical/s0_emissive.png": "png/s0_emissive.png",
        "s0_normal.png": "png/s0_normal.png",
        "s0_height.png": "png/s0_height.png",
    }
    for canonical, route in pairs.items():
        a = (generation / "files" / canonical).read_bytes()
        b = (reference / "files" / route).read_bytes()
        assert np.array_equal(png.decode(a), png.decode(b)), canonical
        assert a == b, canonical


def test_normal_is_directx_with_its_relief_round(
    export_tests: Path, tmp_path: Path, filtered: tuple[Path, Any]
) -> None:
    """2.4: the shipped preset's normal is in the convention phase0.9 settled for UzEngine (green
    = -v, `parity/reports/phase0/normal-convention.md` §8): against the same set's Normal_OpenGL
    through the PNG route, red and blue are equal and green is mirrored (the two codes sum to
    65535 within one code of rounding, over a green that varies). Both the PNG and its derivative
    are tagged `combined` with the relief round they read."""
    _, (generation, receipt) = filtered
    gl = [
        {
            "destChannel": c,
            "srcChannel": c,
            "srcMapType": "virtualMap",
            "srcMapName": "Normal_OpenGL",
        }
        for c in "RGB"
    ]
    out = tmp_path / "opengl"
    config = {
        "exportShaderParams": False,
        "exportPath": out.as_posix(),
        "defaultExportPreset": "gl",
        "exportPresets": [{"name": "gl", "maps": [{"fileName": "$textureSet_gl", "channels": gl}]}],
        "exportList": [{"rootPath": "s0"}],
        "exportParameters": [{"parameters": PARAMETERS | {"fileFormat": "png", "bitDepth": "16"}}],
    }
    code, lines, err = publish(export_tests, authored_spec(tmp_path / "spec"), config, tmp_path)
    assert code == 0 and "error" not in lines[0], (code, lines, err)
    reference, _ = published(export_tests, out)
    directx = png.decode((generation / "files" / "s0_normal.png").read_bytes()).astype(np.int64)
    opengl = png.decode((reference / "files" / "s0_gl.png").read_bytes()).astype(np.int64)
    assert directx.shape == opengl.shape == (SIZE, SIZE, 3)
    assert np.array_equal(directx[..., 0], opengl[..., 0])
    assert np.array_equal(directx[..., 2], opengl[..., 2])
    assert opengl[..., 1].min() < opengl[..., 1].max()
    mirrored = directx[..., 1] + opengl[..., 1] - 65535
    assert int(mirrored.min()) >= -1 and int(mirrored.max()) <= 0
    files = {f["path"]: f for f in receipt["files"]}
    tags = [files[name]["normal"] for name in ("s0_normal.png", "s0_normal.uztexture")]
    assert tags[0] == tags[1]
    assert tags[0]["role"] == "combined"
    relief = tags[0]["relief"]
    assert relief["revision"] >= 1 and len(relief["height_hash"]) == 64 and relief["method"]


# ── The .uzmat and interruption (variant preset) ─────────────────────────────


@pytest.fixture(scope="module")
def variant(export_tests: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("uze-variant")
    presets = variant_presets(tmp / "presets")
    spec_path = authored_spec(tmp / "spec")
    out = tmp / "out"
    config = shipped_config(out.as_posix())
    code, lines, err = publish(export_tests, spec_path, config, tmp, presets)
    assert code == 0 and len(lines) == 1 and "error" not in lines[0], (code, lines, err)
    generation, receipt = published(export_tests, out)
    return {
        "tmp": tmp,
        "presets": presets,
        "spec": spec_path,
        "out": out,
        "config": config,
        "generation": generation,
        "receipt": receipt,
    }


def test_uzmat_binds_the_generation_derivatives(variant: dict[str, Any]) -> None:
    """The `.uzmat` sits at the delivery root after its stack's files, binds the albedo, ORM,
    normal and emissive derivatives of the same generation, blends Masked (opacity in albedo
    alpha), and the receipt carries its inline block and the SM5 opacity and height gaps."""
    receipt, generation = variant["receipt"], variant["generation"]
    paths = [f["path"] for f in receipt["files"]]
    assert paths[-1] == "s0.uzmat"
    [entry] = [f for f in receipt["files"] if f["format"] == "uzmat"]
    meta = entry["uzmat"]
    assert meta["albedo"] == "s0_albedo.uztexture" and meta["orm"] == "s0_orm.uztexture"
    assert meta["normal"] == "s0_normal.uztexture" and meta["emissive"] == "s0_emissive.uztexture"
    assert meta["height"] == "s0_height.uztexture" and meta["blend"] == "Masked"
    for texture in (meta["albedo"], meta["orm"], meta["normal"], meta["emissive"]):
        assert texture in paths
    # The blend rule is authored (an alpha does not tell cutout from translucent): a gap too.
    assert gaps(entry) == {"opacity", "height", "blend"}
    graph = json.loads((generation / "files" / "s0.uzmat").read_text(encoding="utf-8"))
    textures = {
        e["name"]: e["stringParams"]["texturePath"]
        for e in graph["expressions"]
        if e["type"] == "TextureSample"
    }
    assert textures == {
        "Albedo": meta["albedo"],
        "Normal": meta["normal"],
        "ORM": meta["orm"],
        "Emissive": meta["emissive"],
    }
    assert graph["blendMode"] == "Masked"
    inline = meta["inline_material"]
    assert inline["material_graph"] == "s0.uzmat" and inline["orm"] == meta["orm"]
    orm = {f["path"]: f for f in receipt["files"]}["s0_orm.uztexture"]["uztexture"]
    assert (orm["format"], orm["srgb"], orm["binding"], orm["source"]) == (
        "BC7",
        False,
        "orm",
        "canonical/s0_orm.png",
    )


def test_interrupting_each_uztexture_and_uzmat_write_keeps_the_previous_generation(
    export_tests: Path, variant: dict[str, Any]
) -> None:
    """3.5 (EXP-06): killing the export after each `.uztexture` write and after the `.uzmat` write
    leaves the previous generation selected, and a consumer reads it whole."""
    out = variant["out"]
    plan = json.loads((variant["generation"] / "plan.json").read_text(encoding="utf-8"))
    derivatives = [i for i, f in enumerate(plan["files"]) if "uztexture" in f]
    # albedo, normal, ORM, emissive, height (the authored set has no SpecularWeight channel).
    assert len(derivatives) == 5
    points = [f"kill_after_uztexture:{i}" for i in derivatives] + ["kill_after_uzmat:0"]
    pointer = (out / "current.json").read_bytes()
    before = consumed(export_tests, out)
    for point in points:
        code, lines, err = publish(
            export_tests,
            variant["spec"],
            variant["config"],
            variant["tmp"],
            variant["presets"],
            point,
        )
        assert code == KILLED, (point, code, lines, err)
        assert (out / "current.json").read_bytes() == pointer, point
        assert consumed(export_tests, out) == before, point
    recovered = one(export_tests, "recover", "--recover", str(out))
    assert recovered.get("published") is None, recovered
    assert consumed(export_tests, out) == before


# ── Receipt colour space: what changed for every receipt (regression) ───────


def receipt_of(
    exe: Path, skeleton: dict[str, Any], config: dict[str, Any], tmp: Path
) -> dict[str, Any]:
    (tmp / "skeleton.json").write_text(json.dumps(skeleton), encoding="utf-8")
    (tmp / "config.json").write_text(json.dumps(config), encoding="utf-8")
    result: dict[str, Any] = one(
        exe, "receipt", str(tmp / "skeleton.json"), str(tmp / "config.json")
    )
    jsonschema.validate(result, json.loads(RECEIPT_SCHEMA.read_text(encoding="utf-8")))
    return result


def test_receipt_colour_space_follows_the_written_encoding(
    export_tests: Path, tmp_path: Path
) -> None:
    """Every receipt's `colour_space` changed from a constant `linear` to what the file stores,
    and each image channel gained its `transfer`. Exactly these files change: a PNG whose channel is
    written sRGB-encoded (decision 126: an sRGB8 BaseColor, Specular or Emissive, its luma included;
    decision 204: an L8 one through R, B or L) reads `sRGB`, or `mixed` when only some colour
    channels are (an L8 BaseColor's RGB file holds sRGB, linear, sRGB). An sRGB8 User channel, every
    data channel and normal and every OpenEXR file stay `linear`; the alpha is always linear."""

    def lum(name: str, src: str = "L") -> dict[str, Any]:
        return {
            "destChannel": "L",
            "srcChannel": src,
            "srcMapType": "documentMap",
            "srcMapName": name,
        }

    def rgb(name: str) -> list[dict[str, str]]:
        return [
            {"destChannel": c, "srcChannel": c, "srcMapType": "documentMap", "srcMapName": name}
            for c in "RGB"
        ]

    maps = [
        {"fileName": "$textureSet_rgb", "channels": rgb("basecolor")},
        {"fileName": "$textureSet_luma", "channels": [lum("basecolor")]},
        {"fileName": "$textureSet_user", "channels": rgb("user0")},
        {"fileName": "$textureSet_rough", "channels": [lum("roughness")]},
        {
            "fileName": "$textureSet_exr",
            "channels": rgb("basecolor"),
            "parameters": {"fileFormat": "exr", "bitDepth": "32f"},
        },
        {
            "fileName": "$textureSet_alpha",
            "channels": [
                *rgb("basecolor"),
                {
                    "destChannel": "A",
                    "srcChannel": "L",
                    "srcMapType": "documentMap",
                    "srcMapName": "opacity",
                },
            ],
        },
    ]
    config = {
        "exportPath": "C:/export",
        "defaultExportPreset": "p",
        "exportPresets": [{"name": "p", "maps": maps}],
        "exportList": [{"rootPath": "s0"}, {"rootPath": "s1"}],
        "exportParameters": [
            {"parameters": {"fileFormat": "png", "bitDepth": "8"} | PARAMETERS},
            {
                "filter": {"outputMaps": ["$textureSet_exr"]},
                "parameters": {"fileFormat": "exr", "bitDepth": "32f"},
            },
        ],
    }
    channels = {"BaseColor": "sRGB8", "User0": "sRGB8", "SpecularRoughness": "L8", "Opacity": "L8"}
    skeleton = project(
        texture_set("s0", channels), texture_set("s1", channels | {"BaseColor": "L8"})
    )
    receipt = receipt_of(export_tests, skeleton, config, tmp_path)
    files = {f["path"]: f for f in receipt["files"]}

    def state(path: str) -> tuple[str, list[str]]:
        return files[path]["colour_space"], [c["transfer"] for c in files[path]["channels"]]

    assert state("s0_rgb.png") == ("sRGB", ["sRGB"] * 3)
    assert state("s0_luma.png") == ("sRGB", ["sRGB"])
    assert state("s0_user.png") == ("linear", ["linear"] * 3)
    assert state("s0_rough.png") == ("linear", ["linear"])
    assert state("s0_exr.exr") == ("linear", ["linear"] * 3)
    assert state("s0_alpha.png") == ("sRGB", ["sRGB", "sRGB", "sRGB", "linear"])
    assert state("s1_rgb.png") == ("mixed", ["sRGB", "linear", "sRGB"])
    assert state("s1_luma.png") == ("sRGB", ["sRGB"])
    maps_block = receipt["manifest_export"]["maps"]
    assert maps_block[files["s1_rgb.png"]["key"]]["color_space"] == "mixed"


def test_derivative_colour_check_reads_the_luma_encoding(
    export_tests: Path, tmp_path: Path
) -> None:
    """The derivatives' colour check reads the same flags as the encoder: a linear BC4 of the luma
    of an sRGB8 BaseColor (written sRGB-encoded) is refused, naming the encoding."""
    presets = variant_presets(tmp_path / "presets")
    preset = json.loads((presets / "uzengine.json").read_text(encoding="utf-8"))
    for m in preset["maps"]:
        if m["fileName"] == "$textureSet_specularweight":
            m["channels"] = [
                {
                    "destChannel": "L",
                    "srcChannel": "L",
                    "srcMapType": "documentMap",
                    "srcMapName": "basecolor",
                }
            ]
    (presets / "uzengine.json").write_text(json.dumps(preset), encoding="utf-8")
    spec_path = authored_spec(tmp_path / "spec")
    code, lines, err = publish(
        export_tests, spec_path, shipped_config((tmp_path / "out").as_posix()), tmp_path, presets
    )
    assert code == 0 and len(lines) == 1, (code, lines, err)
    refused(
        lines[0],
        "NotYetSupported",
        "$textureSet_specularweight",
        "written sRGB-encoded",
        "declared linear",
    )
    assert not (tmp_path / "out").exists()


def test_engine_outputs_collide_as_windows_names_across_stacks(
    export_tests: Path, tmp_path: Path
) -> None:
    """Every UzEngine output is compared with every output of every stack as Windows compares file
    names (ordinal, ignoring case over Unicode): the derivatives of texture sets "É" and "é" are one
    file, which is invalid."""
    channels = FULL_CHANNELS | {"Emissive": "sRGB8"}
    skeleton = project(texture_set("É", channels), texture_set("é", channels))
    config = shipped_config("C:/export", WITHOUT_ORM)
    config["exportList"] = [
        {"rootPath": name, "filter": {"outputMaps": WITHOUT_ORM}} for name in ("É", "é")
    ]
    [result] = plan_many(export_tests, [(skeleton, config)], tmp_path)
    refused(result, "ValueError", "é_albedo.uztexture", "É_albedo.uztexture", "ignoring case")


def test_specularweight_is_a_consumer_gap(export_tests: Path, tmp_path: Path) -> None:
    """2.7: on a set with a SpecularWeight channel the shipped preset (ORM filtered out) writes
    `<set>_specularweight` (PNG 16, its own canonical map) with a BC4 derivative that has no engine
    binding, and the receipt lists the file as a SpecularWeight consumer gap (`receipt` builds it
    without evaluation: no template gives SpecularWeight a base)."""
    receipt = receipt_of(export_tests, SKELETON, shipped_config("C:/export", WITHOUT_ORM), tmp_path)
    files = {f["path"]: f for f in receipt["files"]}
    entry = files["s0_specularweight.png"]
    assert entry["bit_depth"] == "16" and entry["colour_space"] == "linear"
    assert gaps(entry) == {"SpecularWeight"}
    plan = one(
        export_tests, "receipt", str(tmp_path / "skeleton.json"), str(tmp_path / "config.json")
    )
    assert plan["files"] == receipt["files"]
    [planned] = plan_many(
        export_tests, [(SKELETON, shipped_config("C:/export", WITHOUT_ORM))], tmp_path
    )
    [weight] = [
        f for f in planned["plan"]["files"] if f["fileName"] == "$textureSet_specularweight"
    ]
    assert weight["uztexture"]["binding"] is None and weight["uztexture"]["format"] == "BC4"


def test_requested_derivatives_collide_as_windows_names(export_tests: Path, tmp_path: Path) -> None:
    """A derivative requested after compilation (`RequestUzTextureNormal`) passes the same
    Windows-name check: the normal files of sets "É" and "é" compile (Painter's own rule for its
    files is unchanged), one derivative is accepted, and the second, `é_n.uztexture`, is the first's
    file on Windows and is refused."""
    normal = [
        {"destChannel": c, "srcChannel": c, "srcMapType": "documentMap", "srcMapName": "normal"}
        for c in "RGB"
    ]
    skeleton = project(
        texture_set("É", {"Normal": "RGB16F"}), texture_set("é", {"Normal": "RGB16F"})
    )
    config = {
        "exportPath": "C:/export",
        "defaultExportPreset": "n",
        "exportPresets": [
            {"name": "n", "maps": [{"fileName": "$textureSet_n", "channels": normal}]}
        ],
        "exportList": [{"rootPath": "É"}, {"rootPath": "é"}],
        "exportParameters": [{"parameters": {"fileFormat": "png", "bitDepth": "16"} | PARAMETERS}],
    }
    cases = [
        {"project": skeleton, "config": config, "uztexture": ["É_n.png"]},
        {"project": skeleton, "config": config, "uztexture": ["É_n.png", "é_n.png"]},
    ]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    one_request, two_requests = run(export_tests, "plan", str(path))
    assert "error" not in one_request, one_request
    [first] = [f for f in one_request["plan"]["files"] if "uztexture" in f]
    assert first["uztexture"]["relativePath"] == "É_n.uztexture"
    refused(two_requests, "ValueError", "é_n.uztexture", "É_n.uztexture", "ignoring case")
