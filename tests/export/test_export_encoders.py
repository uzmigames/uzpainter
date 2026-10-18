"""Tests of phase1.16_export-processing-encoders (P1-EXPORT, `docs/architecture/08-export.md` §3,
§5; `src/export/encode.h`, `padding.h`, `png_writer.h`, `exr_writer.h`, `write.h`; decisions 089
and 090).

The CPU cases run `uzp-export-tests.exe` (`roundtrip`, `export`) on every lane: encoder round
trips and byte determinism across processes, the dry run against the files `WriteExport` writes,
and the refusals of every processing no recording covers (recording R-090). The Tier 0 cases read
the private oracle store and skip, saying so, on a machine without it (hosted CI, decision 028);
the local run on the owner's machine (`parity/reports/phase1/export-processing-encoders.md`) is
their evidence:

- every PNG and OpenEXR file Painter exported in the current envelope, decoded and encoded again
  by UzPainter's writers, is byte-identical;
- the goldens of `encoders_tier0.EXPORT_GOLDENS`, rebuilt and written by `WriteExport` in two
  processes, give the dry run's files, identical across the processes and byte-identical to
  Painter's files of each export step (r1, and r2 wherever r2 equals r1, decision 032);
- `parity/semantics/export-processing.json` is what those comparisons derive.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.export.conftest import REPO_ROOT

GRID = REPO_ROOT / "parity" / "fixtures" / "tier0-semantics" / "meshes" / "grid2x2.obj"
SPHERE = REPO_ROOT / "parity" / "fixtures" / "tier0-semantics" / "meshes" / "sphere.obj"
TEMPLATES = REPO_ROOT / "assets" / "templates"

PNG16 = {"fileFormat": "png", "bitDepth": "16", "dithering": False, "paddingAlgorithm": "infinite"}


def run(exe: Path, *args: str) -> list[dict[str, Any]]:
    proc = subprocess.run(
        [str(exe), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1800,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


# ── Round trips and determinism of the encoders ─────────────────────────────


def synthetic_png(width: int, height: int, channels: int) -> np.ndarray:
    """The samples `SyntheticPng` of export_test.cpp encodes."""
    per_row = width * channels
    out = np.empty(per_row * height, np.int64)
    state = 12345
    for i in range(per_row * height):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        kind = (i // per_row) % 3
        out[i] = i % 65536 if kind == 0 else 32768 if kind == 1 else state >> 16
    return out.reshape(height, width, channels)


def synthetic_exr_bits(width: int, height: int, channels: int) -> np.ndarray:
    """The float32 bit patterns `SyntheticExr` of export_test.cpp encodes."""
    specials = np.array(
        [
            0.0,
            -0.0,
            1.0,
            -1.0,
            1.4e-45,
            3.4028234663852886e38,
            -np.inf,
            np.inf,
            0.0,
            0.0,
            0.333333343,
            65504.0,
            1e-30,
        ],
        np.float32,
    ).view(np.uint32)
    specials[4] = 0x00000001  # denorm_min
    specials[5] = 0x7F7FFFFF  # max
    specials[8] = 0x7FC00001  # quiet NaN with a payload
    specials[9] = 0xFFA00000  # signalling-pattern NaN, sign set
    n = width * height * channels
    i = np.arange(n)
    ramp = (i.astype(np.float32) / np.float32(4093.0) - np.float32(7.5)).astype(np.float32)
    bits = ramp.view(np.uint32).copy()
    k = i % 97
    bits[k < len(specials)] = specials[k[k < len(specials)]]
    return bits.reshape(height, width, channels)


def test_encoders_round_trip_and_repeat_across_processes(
    export_tests: Path, tmp_path: Path
) -> None:
    """3.5, 3.6: PNG 16 and 8 and OpenEXR 32f images (grey, RGB, RGBA) of ramps, runs, noise and
    special floats (signed zero, subnormal, maximum, infinities, NaN payloads), at 1x1 and odd
    sizes: decoded back they equal the encoded values bit for bit (spng and tinyexr in the
    process; independently the repository's own PNG decoder, and OpenEXR's when installed),
    encoding twice gives the same bytes, and two processes write identical files."""
    from tools.parity.feasibility import png

    first = run(export_tests, "roundtrip", str(tmp_path / "a"))
    second = run(export_tests, "roundtrip", str(tmp_path / "b"))
    assert len(first) == 15
    assert [r["sha256"] for r in first] == [r["sha256"] for r in second]
    try:
        import OpenEXR
    except ImportError:
        OpenEXR = None
    for result in first:
        assert result["decoded_equal"] and result["repeat_equal"], result
        data = (tmp_path / "a" / result["name"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == result["sha256"]
        assert data == (tmp_path / "b" / result["name"]).read_bytes()
        w, h, c = (int(x) for x in result["name"].split("-")[1].split(".")[0].split("x"))
        if result["format"] == "png":
            decoded = png.decode(data).reshape(h, w, c).astype(np.int64)
            expected = synthetic_png(w, h, c)
            if result["name"].endswith("-8.png"):
                assert png.chunks(data)[0][1][8] == 8
                expected = expected & 0xFF
            assert np.array_equal(decoded, expected)
        elif OpenEXR is not None:
            with OpenEXR.File(str(tmp_path / "a" / result["name"]), separate_channels=True) as exr:
                planes = exr.channels()
                names = ["Y"] if c == 1 else ["R", "G", "B", "A"][:c]
                assert sorted(planes) == sorted(names)
                got = np.stack([np.asarray(planes[n].pixels) for n in names], axis=-1)
            assert got.dtype == np.float32
            assert np.array_equal(got.view(np.uint32), synthetic_exr_bits(w, h, c))


# ── WriteExport on CPU projects ─────────────────────────────────────────────


def ramp_codes() -> np.ndarray:
    """Every 16-bit code once: 256 x + y at column x, row y."""
    y, x = np.mgrid[0:256, 0:256]
    codes: np.ndarray = x * 256 + y
    return codes


def ramp_png(path: Path) -> str:
    """A 256x256 grey 16-bit bitmap holding `ramp_codes` (the fill source of `spec`); returns its
    SHA-256. A grey bitmap feeds every channel of a colour channel, and the one-channel channels
    read it without the colour-on-mono texture, which is recorded only for 8-bit images
    (decision 218)."""
    from tools.parity.feasibility import png

    data = png.encode(ramp_codes().astype(np.int64), 16)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def spec(tmp: Path, mesh: Path | None = GRID, name: str = "s0", height: bool = True) -> Path:
    """A texture set `name` (the mesh material it covers) of the grid mesh: User0 sRGB8, BaseColor
    sRGB8, Height L16F (empty when not `height`) and SpecularRoughness L16 filled from a ramp
    bitmap, and an empty Normal RGB16F."""
    tmp.mkdir(parents=True, exist_ok=True)
    sha = ramp_png(tmp / "ramp.png")
    bitmap = {"bitmap": sha, "color_space": "Raw"}
    sources = {"User0": bitmap, "BaseColor": bitmap, "Height": bitmap, "SpecularRoughness": bitmap}
    if not height:
        del sources["Height"]
    document: dict[str, Any] = {
        "name": name,
        "resolution": [256, 256],
        "channels": [
            {"type": "User0", "format": "sRGB8"},
            {"type": "BaseColor", "format": "sRGB8"},
            {"type": "Height", "format": "L16F"},
            {"type": "SpecularRoughness", "format": "L16"},
            {"type": "Normal", "format": "RGB16F"},
        ],
        "resources": [{"sha256": sha, "png": "ramp.png"}],
        "layers": [{"kind": "fill", "sources": sources}],
    }
    if mesh is not None:
        document["mesh"] = str(mesh)
    (tmp / "spec.json").write_text(json.dumps(document), encoding="utf-8")
    return tmp / "spec.json"


def chan(dest: str, kind: str, name: str) -> dict[str, str]:
    return {"destChannel": dest, "srcChannel": dest, "srcMapType": kind, "srcMapName": name}


def normal_map(name: str = "Normal_OpenGL") -> list[dict[str, Any]]:
    """One RGB file `$textureSet_n` of the virtual normal `name`."""
    return [{"fileName": "$textureSet_n", "channels": [chan(c, "virtualMap", name) for c in "RGB"]}]


def config(
    out: Path, rules: list[dict[str, Any]] | None = None, root: str = "s0", **params: Any
) -> dict[str, Any]:
    """User0 (RGB, an sRGB8 channel), Roughness (L) and Height (L) of `root`; Height as OpenEXR 32f
    by a rule."""
    return {
        "exportShaderParams": False,
        "exportPath": out.as_posix(),
        "defaultExportPreset": "p",
        "exportPresets": [
            {
                "name": "p",
                "maps": [
                    {
                        "fileName": "$textureSet_User0",
                        "channels": [chan(c, "documentMap", "user0") for c in "RGB"],
                    },
                    {
                        "fileName": "maps/$textureSet_Roughness",
                        "channels": [chan("L", "documentMap", "roughness")],
                    },
                    {
                        "fileName": "$textureSet_Height",
                        "channels": [chan("L", "documentMap", "height")],
                    },
                ],
            }
        ],
        "exportList": [{"rootPath": root}],
        "exportParameters": [
            {"parameters": PNG16 | params},
            {
                "filter": {"outputMaps": ["$textureSet_Height"]},
                "parameters": {"fileFormat": "exr", "bitDepth": "32f"},
            },
            *(rules or []),
        ],
    }


def export(
    exe: Path, spec_path: Path, cfg: dict[str, Any], tmp: Path, templates: Path = TEMPLATES
) -> dict[str, Any]:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    [result] = run(exe, "export", str(templates), str(spec_path), str(tmp / "config.json"))
    return result


def inferred_templates(root: Path) -> Path:
    """A copy of the shipped templates in which Blender's BaseColor base is `inferred`. Since
    decision 169 no shipped template has an inferred base; the guard stays for any that would."""
    shutil.copytree(TEMPLATES, root)
    path = root / "blender.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    for channel in document["channels"]:
        if channel["type"] == "BaseColor":
            channel["base_provenance"]["kind"] = "inferred"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return root


def files_under(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_written_files_equal_the_dry_run_in_two_processes(
    export_tests: Path, tmp_path: Path
) -> None:
    """3.5: `WriteExport` writes exactly the files of the dry run (`list_project_textures`), in
    sub-folders as named, with the sizes and SHA-256 it reports; two processes write identical
    bytes (PNG16 RGB and L, OpenEXR 32f L)."""
    spec_path = spec(tmp_path / "spec")
    results = []
    for run_id in ("a", "b"):
        out = tmp_path / f"out-{run_id}"
        result = export(export_tests, spec_path, config(out), tmp_path / f"run-{run_id}")
        assert "error" not in result, result
        listed = sorted(
            Path(f).relative_to(out).as_posix() for _, _, fs in result["list"] for f in fs
        )
        written = {f["relativePath"]: f for f in result["written"]}
        on_disk = files_under(out)
        assert (
            listed
            == sorted(written)
            == sorted(on_disk)
            == [
                "maps/s0_Roughness.png",
                "s0_Height.exr",
                "s0_User0.png",
            ]
        )
        for rel, data in on_disk.items():
            assert written[rel]["size"] == len(data)
            assert written[rel]["sha256"] == hashlib.sha256(data).hexdigest()
        results.append(on_disk)
    assert results[0] == results[1]


def test_written_values_follow_the_write_rules(export_tests: Path, tmp_path: Path) -> None:
    """2.5: the PNG16 file of an L16 channel holds its stored codes (the UNORM write rule of their
    operands gives every one of the 65536 codes back), and the OpenEXR file of the L16F Height
    channel is a FLOAT `Y` image."""
    from tools.parity.feasibility import png

    out = tmp_path / "out"
    result = export(export_tests, spec(tmp_path / "spec"), config(out), tmp_path / "run")
    assert "error" not in result, result
    rough = png.decode((out / "maps" / "s0_Roughness.png").read_bytes()).astype(np.int64)
    assert np.array_equal(rough.reshape(256, 256), ramp_codes())
    exr = (out / "s0_Height.exr").read_bytes()
    assert exr.startswith(b"\x76\x2f\x31\x01")
    assert b"channels\x00chlist" in exr and b"Y\x00\x02\x00\x00\x00" in exr


@pytest.mark.parametrize(
    ("params", "rules", "expected"),
    [
        ({"bitDepth": "8", "dithering": True}, None, "dithering at PNG 8 bits"),
        (
            {},
            [{"parameters": {"fileFormat": "exr", "bitDepth": "16f", "dithering": True}}],
            "dithering in OpenEXR",
        ),
        ({"sizeLog2": 7}, None, "resizing 256x256 to 128x128"),
        ({"sizeLog2": [8, 7]}, None, "resizing 256x256 to 256x128"),
        ({"paddingAlgorithm": "color", "dilationDistance": 4}, None, 'the padding "color"'),
        (
            {"paddingAlgorithm": "transparent", "dilationDistance": 4},
            None,
            'the padding "transparent"',
        ),
        ({"paddingAlgorithm": "diffusion", "dilationDistance": 4}, None, 'the padding "diffusion"'),
    ],
)
def test_unrecorded_processing_is_refused_before_writing(
    export_tests: Path,
    tmp_path: Path,
    params: dict[str, Any],
    rules: list[dict[str, Any]] | None,
    expected: str,
) -> None:
    """6.1 (decisions 090 and 103): processing recording R-090 shows but no fit reproduces raises
    NotYetSupported naming it, and nothing exists under exportPath afterwards."""
    out = tmp_path / "out"
    result = export(
        export_tests, spec(tmp_path / "spec"), config(out, rules, **params), tmp_path / "run"
    )
    assert result.get("error") == "NotYetSupported", result
    assert expected in result["message"] and "R-090" in result["message"], result["message"]
    assert files_under(out) == {}


def write_unorm(values: np.ndarray, bits: int) -> np.ndarray:
    """arith::WriteUnorm: clamp, truncate to bits + 4 fractional bits, nearest code, ties down."""
    c = np.clip(np.nan_to_num(values.astype(np.float32), nan=0.0), 0, 1).astype(np.float32)
    j = (c * np.float32(1 << (bits + 4))).astype(np.uint64)
    top, bias = np.uint64((1 << bits) - 1), np.uint64((1 << (bits + 3)) - 1)
    codes: np.ndarray = ((j * top + bias) >> np.uint64(bits + 4)).astype(np.int64)
    return codes


def test_recorded_depths_layouts_and_dithering_are_written(
    export_tests: Path, tmp_path: Path
) -> None:
    """6.1 (decision 103): PNG 8 writes the 8-bit UNORM rule of each value; PNG 16 with
    dithering writes the bytes PNG 16 without it writes; an RGB+A map whose alpha is 1 everywhere
    is written RGB, byte for byte the RGB map; an L+A map with a varying alpha is a grey and alpha
    PNG; an sRGB8 User channel is written to OpenEXR."""
    from tools.parity.feasibility import png

    spec_path = spec(tmp_path / "spec")
    plain = tmp_path / "plain"
    result = export(export_tests, spec_path, config(plain), tmp_path / "run-plain")
    assert "error" not in result, result

    out8 = tmp_path / "png8"
    result = export(export_tests, spec_path, config(out8, bitDepth="8"), tmp_path / "run-8")
    assert "error" not in result, result
    rough = png.decode((out8 / "maps" / "s0_Roughness.png").read_bytes()).astype(np.int64)
    operands = (ramp_codes() / 65535.0).astype(np.float32)
    assert np.array_equal(rough.reshape(256, 256), write_unorm(operands, 8))

    dithered = tmp_path / "dithered"
    cfg = config(dithered, dithering=True)
    cfg["exportParameters"][1]["parameters"]["dithering"] = False  # the OpenEXR Height map
    result = export(export_tests, spec_path, cfg, tmp_path / "run-d")
    assert "error" not in result, result
    assert files_under(dithered) == files_under(plain)

    alpha = tmp_path / "alpha"
    cfg = config(alpha)
    maps = cfg["exportPresets"][0]["maps"]
    maps[0]["channels"].append(chan("A", "defaultMap", "white"))
    maps.append(
        {
            "fileName": "$textureSet_la",
            "channels": [
                chan("L", "documentMap", "height"),
                chan("A", "documentMap", "roughness") | {"srcChannel": "L"},
            ],
        }
    )
    result = export(export_tests, spec_path, cfg, tmp_path / "run-alpha")
    assert "error" not in result, result
    written = files_under(alpha)
    assert written["s0_User0.png"] == files_under(plain)["s0_User0.png"]
    assert written["s0_la.png"][25] == 4  # IHDR colour type: grey and alpha

    exr = tmp_path / "exr"
    cfg = config(exr)
    cfg["exportParameters"][0]["parameters"] |= {"fileFormat": "exr", "bitDepth": "16f"}
    result = export(export_tests, spec_path, cfg, tmp_path / "run-exr")
    assert "error" not in result, result
    assert sorted(files_under(exr)) == ["maps/s0_Roughness.exr", "s0_Height.exr", "s0_User0.exr"]


def test_height_is_written_signed_to_png(export_tests: Path, tmp_path: Path) -> None:
    """6.1 (decision 103): a Height channel is written to PNG as v * 0.5 + 0.5 (its OpenEXR 32f
    value v), at 16 and at 8 bits; OpenEXR 16f holds v rounded toward zero to a half."""
    from tools.parity.feasibility import png
    from tools.parity.fit.decode import decode

    pytest.importorskip("OpenEXR")
    spec_path = spec(tmp_path / "spec")
    out = tmp_path / "f32"
    result = export(export_tests, spec_path, config(out), tmp_path / "run")
    assert "error" not in result, result
    height = decode((out / "s0_Height.exr").read_bytes()).values.astype(np.float32)[..., 0]
    for depth in ("16", "8"):
        target = tmp_path / f"png{depth}"
        cfg = config(target, bitDepth=depth)
        cfg["exportParameters"] = cfg["exportParameters"][:1]
        result = export(export_tests, spec_path, cfg, tmp_path / f"run-{depth}")
        assert "error" not in result, result
        codes = png.decode((target / "s0_Height.png").read_bytes()).astype(np.int64)
        expected = write_unorm(height * np.float32(0.5) + np.float32(0.5), int(depth))
        assert np.array_equal(codes.reshape(256, 256), expected)
    half = tmp_path / "f16"
    cfg = config(half)
    cfg["exportParameters"][1]["parameters"]["bitDepth"] = "16f"
    result = export(export_tests, spec_path, cfg, tmp_path / "run-16f")
    assert "error" not in result, result
    stored = decode((half / "s0_Height.exr").read_bytes()).values.astype(np.float32)[..., 0]
    nearest = height.astype(np.float16).astype(np.float32)
    toward_zero = np.where(
        np.abs(nearest) > np.abs(height),
        np.nextafter(nearest.astype(np.float16), np.float16(0)).astype(np.float32),
        nearest,
    )
    assert np.array_equal(stored, toward_zero)


def test_srgb8_material_channels_are_written_encoded(export_tests: Path, tmp_path: Path) -> None:
    """2.6 (decision 126): an sRGB8 BaseColor is written to PNG 16 as the sRGB encode of its linear
    value (Painter 12.1.5's encode, `tier0.srgb16`) and to OpenEXR 32f linear, equal to the sRGB8
    User0 read-out of the same bitmap; an sRGB8 material channel no recording shows (Diffuse) is
    refused before writing; a template whose BaseColor base is inferred from its PNG export only
    fails its evaluation (`unsupported_source`) before writing."""
    from tests.export.tier0 import srgb16

    pytest.importorskip("OpenEXR", reason="decodes the OpenEXR 32f BaseColor; owner's machine only")
    out = tmp_path / "out"
    cfg = config(out)
    cfg["exportPresets"][0]["maps"] = [
        {"fileName": f"$textureSet_{name}", "channels": [chan(c, "documentMap", m) for c in "RGB"]}
        for name, m in (("base", "basecolor"), ("base32", "basecolor"), ("user", "user0"))
    ]
    cfg["exportParameters"][1]["filter"]["outputMaps"] = ["$textureSet_base32"]
    result = export(export_tests, spec(tmp_path / "spec"), cfg, tmp_path / "run")
    assert "error" not in result, result
    from tests.export.tier0 import write16
    from tools.parity.fit.decode import decode

    base16 = decode((out / "s0_base.png").read_bytes()).values
    base32 = decode((out / "s0_base32.exr").read_bytes()).values.astype(np.float32)
    user16 = decode((out / "s0_user.png").read_bytes()).values
    assert np.array_equal(base16, srgb16(base32))
    assert np.array_equal(user16, write16(base32))
    assert not np.array_equal(base16, user16)

    document = json.loads((tmp_path / "spec" / "spec.json").read_text(encoding="utf-8"))
    document["channels"].append({"type": "Diffuse", "format": "sRGB8"})
    document["layers"][0]["sources"]["Diffuse"] = document["layers"][0]["sources"]["BaseColor"]
    (tmp_path / "spec" / "diffuse.json").write_text(json.dumps(document), encoding="utf-8")
    out = tmp_path / "diffuse"
    cfg = config(out)
    for c in cfg["exportPresets"][0]["maps"][0]["channels"]:
        c["srcMapName"] = "diffuse"
    result = export(export_tests, tmp_path / "spec" / "diffuse.json", cfg, tmp_path / "run-diffuse")
    assert result.get("error") == "NotYetSupported", result
    assert "the export encoding of the sRGB8 channel Diffuse" in result["message"], result
    assert "decision 126" in result["message"], result
    assert files_under(out) == {}

    document = json.loads((tmp_path / "spec" / "spec.json").read_text(encoding="utf-8"))
    document["template"] = "blender"
    (tmp_path / "spec" / "blender.json").write_text(json.dumps(document), encoding="utf-8")
    out = tmp_path / "inferred"
    cfg = config(out)
    for c in cfg["exportPresets"][0]["maps"][0]["channels"]:
        c["srcMapName"] = "basecolor"
    result = export(
        export_tests,
        tmp_path / "spec" / "blender.json",
        cfg,
        tmp_path / "run-inferred",
        inferred_templates(tmp_path / "templates"),
    )
    # An evaluator refusal (`unsupported_source`, NotYetSupported in the Python API, decision 082)
    # before anything is written.
    assert result.get("error") == "Failure", result
    assert result["message"].startswith("evaluator:unsupported_source"), result
    assert "inferred from its 16-bit PNG export only" in result["message"], result
    assert files_under(out) == {}


def test_l8_material_channels_are_written_encoded(export_tests: Path, tmp_path: Path) -> None:
    """Decision 204: an empty L8 BaseColor (float32(0.8)) and Specular (float32(10/255), its
    channel default) are written to PNG with the sRGB encode of the linear value in R, B and L and
    the linear write in G, as Painter's export-l8-material files hold them (s3, r1 and r2). Under
    OCIO, or in any other file than the RGB or L file of the one channel each letter reading its
    own, the PNG is refused before writing; their OpenEXR files hold the linear value."""
    document = {
        "name": "s0",
        "resolution": [256, 256],
        "mesh": str(GRID),
        "channels": [{"type": "BaseColor", "format": "L8"}, {"type": "Specular", "format": "L8"}],
        "resources": [],
        "layers": [],
    }
    (tmp_path / "spec").mkdir()
    spec_path = tmp_path / "spec" / "l8.json"
    spec_path.write_text(json.dumps(document), encoding="utf-8")

    def preset(out: Path, maps: dict[str, list[dict[str, str]]], **params: Any) -> dict[str, Any]:
        cfg = config(out, **params)
        cfg["exportPresets"][0]["maps"] = [
            {"fileName": f"$textureSet_{name}", "channels": channels}
            for name, channels in maps.items()
        ]
        cfg["exportParameters"] = cfg["exportParameters"][:1]
        return cfg

    from tools.parity.fit.decode import decode

    written = {
        "base": [chan(c, "documentMap", "basecolor") for c in "RGB"],
        "spec": [chan(c, "documentMap", "specular") for c in "RGB"],
        "specL": [chan("L", "documentMap", "specular")],
    }
    expected = {
        ("16", "base"): [59397, 52428, 59397],
        ("16", "spec"): [14330, 2570, 14330],
        ("16", "specL"): [14330],
        ("8", "base"): [231, 204, 231],
        ("8", "spec"): [56, 10, 56],
        ("8", "specL"): [56],
    }
    for depth in ("8", "16"):
        out = tmp_path / f"png{depth}"
        cfg = preset(out, written, bitDepth=depth)
        result = export(export_tests, spec_path, cfg, tmp_path / f"run{depth}")
        assert "error" not in result, result
        for name in written:
            values = decode((out / f"s0_{name}.png").read_bytes()).values
            unique = np.unique(values.reshape(-1, values.shape[-1]), axis=0).tolist()
            assert unique == [expected[(depth, name)]], (depth, name, unique)

    out = tmp_path / "exr"
    cfg = preset(out, {"spec": written["spec"]}, fileFormat="exr", bitDepth="32f")
    result = export(export_tests, spec_path, cfg, tmp_path / "run-exr")
    assert "error" not in result, result
    if importlib.util.find_spec("OpenEXR") is not None:
        values = decode((out / "s0_spec.exr").read_bytes()).values.astype(np.float32)
        assert np.all(values == np.float32(10 / 255)), np.unique(values)

    swapped = [
        {**chan("R", "documentMap", "specular"), "srcChannel": "G"},
        chan("G", "documentMap", "specular"),
        chan("B", "documentMap", "specular"),
    ]
    mixed = [chan("R", "documentMap", "specular"), *written["base"][1:]]
    refusals = [
        ("swapped", spec_path, {"spec": swapped}, "other than the channel's own"),
        ("mixed", spec_path, {"spec": mixed}, "other than the channel's own"),
    ]
    from tests.export.encoders_tier0 import OCIO_CONFIG_SHA256

    ocio = dict(document, color_management="ocio", config_hash=OCIO_CONFIG_SHA256)
    ocio_path = tmp_path / "spec" / "ocio.json"
    ocio_path.write_text(json.dumps(ocio), encoding="utf-8")
    refusals.append(("ocio", ocio_path, {"spec": written["spec"]}, "under OCIO is not recorded"))
    for label, path, maps, phrase in refusals:
        out = tmp_path / label
        result = export(export_tests, path, preset(out, maps), tmp_path / f"run-{label}")
        assert result.get("error") == "NotYetSupported", (label, result)
        assert "the PNG encoding of the L8 channel Specular" in result["message"], result
        assert phrase in result["message"] and "decision 204" in result["message"], result
        assert files_under(out) == {}, label


def test_no_export_reads_an_inferred_template_base(export_tests: Path, tmp_path: Path) -> None:
    """2.6 (decision 126): on a template whose BaseColor base is inferred (Blender, in a copy of
    the templates: since decision 169 no shipped template has an inferred base), every
    export source that reads BaseColor fails its evaluation (`unsupported_source`) before anything
    is written: the documentMap on sRGB8 and on RGB16, and the diagnosticMap sources isolated,
    contribution, regionStats, materialView and materialLeaks of BaseColor (leaks compare the
    channel's full and solo read-outs). On the default template, whose base is observed, the same
    diagnostic sources are written. Specular and Emissive added in a format other than sRGB8 and L8
    fail with `missing_base_value`: their channel defaults are recorded on those formats only."""

    def variant(name: str, template: str | None, basecolor: str = "sRGB8") -> Path:
        document = json.loads(spec(tmp_path / "spec").read_text(encoding="utf-8"))
        if template is not None:
            document["template"] = template
        for c in document["channels"]:
            if c["type"] == "BaseColor":
                c["format"] = basecolor
        document["layers"][0]["uid"] = 501
        path = tmp_path / "spec" / f"{name}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def single(out: Path, kind: str, source: str, layout: str = "RGB") -> dict[str, Any]:
        cfg = config(out)
        letters = "L" if layout == "L" else "RGB"
        cfg["exportPresets"][0]["maps"] = [
            {"fileName": "$textureSet_x", "channels": [chan(c, kind, source) for c in letters]}
        ]
        cfg["exportParameters"] = cfg["exportParameters"][:1]
        return cfg

    sources = [
        ("documentMap", "basecolor", "RGB"),
        ("diagnosticMap", "isolated/BaseColor/501", "RGB"),
        ("diagnosticMap", "contribution/BaseColor/501", "RGB"),
        ("diagnosticMap", "regionStats/BaseColor/501", "L"),
        ("diagnosticMap", "materialView/BaseColor/501", "RGB"),
        ("diagnosticMap", "materialLeaks/BaseColor/501", "L"),
    ]
    templates = inferred_templates(tmp_path / "templates")
    cases = [(variant("blender", "blender"), *src) for src in sources]
    cases.append((variant("blender-rgb16", "blender", "RGB16"), *sources[0]))
    for i, (spec_path, kind, source, layout) in enumerate(cases):
        out = tmp_path / f"inferred{i}"
        result = export(
            export_tests,
            spec_path,
            single(out, kind, source, layout),
            tmp_path / f"r{i}",
            templates,
        )
        assert result.get("error") == "Failure", (source, result)
        assert result["message"].startswith("evaluator:unsupported_source"), (source, result)
        assert "BaseColor in template 'blender' is inferred" in result["message"], result
        assert files_under(out) == {}, source
    default = variant("default", None)
    for i, (kind, source, layout) in enumerate(sources[1:]):
        out = tmp_path / f"observed{i}"
        result = export(
            export_tests, default, single(out, kind, source, layout), tmp_path / f"o{i}"
        )
        assert "error" not in result, (source, result)
        assert files_under(out), source

    # Specular and Emissive added in a format other than sRGB8 and L8: their channel defaults are
    # recorded on those formats only, so the evaluation fails (`missing_base_value`) before
    # anything is written.
    for channel, fmt in (("Specular", "RGB16"), ("Emissive", "RGB16"), ("Specular", "L16")):
        document = json.loads((tmp_path / "spec" / "default.json").read_text(encoding="utf-8"))
        document["channels"].append({"type": channel, "format": fmt})
        path = tmp_path / "spec" / f"{channel}-{fmt}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        out = tmp_path / f"added-{channel}-{fmt}"
        layout = "L" if fmt.startswith("L") else "RGB"
        cfg = single(out, "documentMap", channel.lower(), layout)
        result = export(export_tests, path, cfg, tmp_path / f"a-{channel}-{fmt}")
        assert result.get("error") == "Failure", (channel, fmt, result)
        assert result["message"].startswith("evaluator:missing_base_value"), (channel, result)
        assert "recorded as sRGB8 and L8 only" in result["message"], (channel, result)
        assert files_under(out) == {}, (channel, fmt)


def reference_padding(values: np.ndarray, covered: np.ndarray) -> np.ndarray:
    """Decision 223's `infinite` padding (src/export/padding.h; measured only, decision 259),
    written again independently: the ring from the covered 8-neighbours (x wraps), then the jump
    flood over covered and ring."""
    height, width, _ = values.shape
    out = values.astype(np.float32).copy()
    f = 0.4142245
    diagonal = f / (1.0 - f)
    shift = 24.875 * 2.0**-15
    weaken = (diagonal - shift * (1.0 + diagonal)) / (diagonal * (1.0 + shift))
    seed = covered.copy()
    for y, x in zip(*np.nonzero(~covered), strict=True):
        near = [
            (dy, dx, y + dy, (x + dx) % width)
            for dy, dx in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))
            if 0 <= y + dy < height and covered[y + dy, (x + dx) % width]
        ]
        if not near:
            continue
        seed[y, x] = True
        taps = [values[yy, xx] for _, _, yy, xx in near]
        if all(np.array_equal(taps[0], tap) for tap in taps):
            out[y, x] = taps[0]
            continue
        rows, cols = {n[0] for n in near}, {n[1] for n in near}
        flat = len(near) == 3 and len(rows) == 1 and 0 not in rows and cols == {-1, 0, 1}
        upright = len(near) == 3 and len(cols) == 1 and 0 not in cols and rows == {-1, 0, 1}
        total, weights = np.zeros(values.shape[2]), 0.0
        for dy, dx, yy, xx in near:
            w = 1.0 if dy == 0 or dx == 0 else diagonal
            w *= weaken if (flat and dx == -1) or (upright and dy == 1) else 1.0
            total = total + w * values[yy, xx].astype(np.float64)
            weights += w
        mean = (total / weights).astype(np.float32)
        out[y, x] = np.float32(1.0) - (np.float32(1.0) - mean)
    ys, xs = np.mgrid[0:height, 0:width]
    sy, sx = np.where(seed, ys, -1), np.where(seed, xs, -1)
    big = np.iinfo(np.int64).max
    k = max(width, height) // 2
    while k >= 1:
        by, bx = sy.copy(), sx.copy()
        best = np.where(by >= 0, (by - ys) ** 2 + (bx - xs) ** 2, big)
        for dy, dx in ((0, 1), (0, -1), (-1, 0), (1, 0), (-1, 1), (1, -1), (-1, -1), (1, 1)):
            cy, cx = np.full_like(sy, -1), np.full_like(sx, -1)
            y0, y1 = max(0, -dy * k), min(height, height - dy * k)
            x0, x1 = max(0, -dx * k), min(width, width - dx * k)
            cy[y0:y1, x0:x1] = sy[y0 + dy * k : y1 + dy * k, x0 + dx * k : x1 + dx * k]
            cx[y0:y1, x0:x1] = sx[y0 + dy * k : y1 + dy * k, x0 + dx * k : x1 + dx * k]
            d = np.where(cy >= 0, (cy - ys) ** 2 + (cx - xs) ** 2, big)
            better = d < best
            by, bx = np.where(better, cy, by), np.where(better, cx, bx)
            best = np.where(better, d, best)
        sy, sx = by, bx
        k //= 2
    gutter = ~seed & (sy >= 0)
    out[gutter] = out[sy[gutter], sx[gutter]]
    return out


def test_padding_on_islands(export_tests: Path, tmp_path: Path) -> None:
    """2.2 (decision 090) and decision 259: on the sphere, whose UV islands leave texels uncovered:
    - `passthrough` writes every texel's evaluated value (the L16 roughness holds the ramp's codes
      inside and outside the islands);
    - `infinite` is refused before anything is written, naming R-090, the owner and decision 259:
      its padding texels are not Painter's, and the owner withdrew exception EXC-007;
    - decision 223's rule stays behind that refusal, applied only when measured (`process` over
      the sphere's coverage): the covered texels keep their values, and the OpenEXR 32f Height
      equals the padding of padding.h written independently (`reference_padding`) over the
      coverage of `tools.parity.coverage`, value for value;
    - without a texturing mesh the export fails before writing."""
    from tools.parity.coverage import coverage, obj_triangles
    from tools.parity.feasibility import png
    from tools.parity.fit.decode import decode

    covered = coverage(obj_triangles(SPHERE, "uzp_sphere"), 256, 256)
    assert 0 < covered.sum() < covered.size
    sphere = spec(tmp_path / "sphere", SPHERE, "uzp_sphere")
    passthrough = tmp_path / "passthrough"
    cfg = config(passthrough, root="uzp_sphere", paddingAlgorithm="passthrough")
    result = export(export_tests, sphere, cfg, tmp_path / "run-passthrough")
    assert "error" not in result, result
    roughness = passthrough / "maps" / "uzp_sphere_Roughness.png"
    rough = png.decode(roughness.read_bytes()).astype(np.int64)
    assert np.array_equal(rough.reshape(256, 256), ramp_codes())
    height_file = passthrough / "uzp_sphere_Height.exr"
    evaluated = decode(height_file.read_bytes()).values

    out = tmp_path / "infinite"
    result = export(export_tests, sphere, config(out, root="uzp_sphere"), tmp_path / "run-infinite")
    assert result.get("error") == "NotYetSupported", result
    message = result["message"]
    assert (
        'the padding "infinite" on a texture set whose UV islands do not cover the whole tile '
        "is not exact" in message
    ), message
    assert "recording R-090" in message and "decision 259" in message, message
    assert "phase1.25_pilot-wand item 2.7" in message, message
    assert files_under(out) == {}

    cases: list[dict[str, Any]] = [
        {"source": str(roughness), "format": "png", "bit_depth": "16", "height": False},
        {"source": str(height_file), "format": "exr", "bit_depth": "32f", "height": True},
    ]
    for index, case in enumerate(cases):
        case["target"] = case["source"]
        case["mesh"], case["material"] = str(SPHERE), "uzp_sphere"
        case["out"] = str(tmp_path / f"measured-{index}.{case['format']}")
    listing = tmp_path / "measured.json"
    listing.write_text(json.dumps(cases), encoding="utf-8")
    lines = run(export_tests, "process", str(listing))
    assert [line["covered_texels"] for line in lines] == [int(covered.sum())] * 2, lines
    padded = png.decode(Path(cases[0]["out"]).read_bytes()).astype(np.int64).reshape(256, 256)
    assert np.array_equal(padded[covered], ramp_codes()[covered])
    assert not np.array_equal(padded[~covered], ramp_codes()[~covered])
    height = decode(Path(cases[1]["out"]).read_bytes()).values
    height, evaluated = height.reshape(256, 256, -1), evaluated.reshape(256, 256, -1)
    expected = reference_padding(evaluated.astype(np.float32), covered)
    assert np.array_equal(height.astype(np.float32).view(np.uint32), expected.view(np.uint32))

    out = tmp_path / "no-mesh"
    result = export(export_tests, spec(tmp_path / "bare", None), config(out), tmp_path / "run-bare")
    assert result.get("error") == "Failure" and "no texturing mesh" in result["message"], result
    assert files_under(out) == {}


def test_virtual_normal_on_islands(export_tests: Path, tmp_path: Path) -> None:
    """B18 (decision 245): on the sphere, whose UV islands leave texels uncovered, a combined
    virtual normal reads the Height outside the islands at its island-edge texels, where Painter's
    Height is not reproduced:
    - Normal_OpenGL and Normal_DirectX are refused before anything is written under `infinite` and
      `passthrough`, naming the cause, the evidence and the owner, with a layer writing the Height
      and with none (no recording shows Painter's empty Height outside the islands), and so is the
      pipeline's five-map export that holds one, as a whole (under `infinite` its first map is
      refused first, decision 259);
    - so is every diagnosticMap that isolates, compares or summarises one (`regionStats` a
      statistics file);
    - on the grid, whose coverage is complete, the same sources are written."""

    def variant(name: str, mesh: Path, set_name: str, height: bool) -> Path:
        path = spec(tmp_path / name, mesh, set_name, height=height)
        document = json.loads(path.read_text(encoding="utf-8"))
        document["layers"][0]["uid"] = 501
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def single(out: Path, root: str, kind: str, source: str, padding: str) -> dict[str, Any]:
        cfg = config(out, root=root, paddingAlgorithm=padding)
        letters = "L" if source.startswith("regionStats/") else "RGB"
        cfg["exportPresets"][0]["maps"] = [
            {"fileName": "$textureSet_n", "channels": [chan(c, kind, source) for c in letters]}
        ]
        cfg["exportParameters"] = cfg["exportParameters"][:1]
        return cfg

    sources = [
        ("virtualMap", "Normal_OpenGL"),
        ("virtualMap", "Normal_DirectX"),
        ("diagnosticMap", "isolated/Normal_OpenGL/501"),
        ("diagnosticMap", "contribution/Normal_DirectX/501"),
        ("diagnosticMap", "regionStats/Normal_OpenGL/501"),
    ]
    relief = variant("sphere", SPHERE, "uzp_sphere", height=True)
    flat = variant("sphere-flat", SPHERE, "uzp_sphere", height=False)
    for label, project in (("relief", relief), ("flat", flat)):
        for kind, source in sources:
            for padding in ("infinite", "passthrough"):
                case = f"{label}-{source.replace('/', '-')}-{padding}"
                out = tmp_path / case
                cfg = single(out, "uzp_sphere", kind, source, padding)
                result = export(export_tests, project, cfg, tmp_path / f"run-{case}")
                assert result.get("error") == "NotYetSupported", (case, result)
                message = result["message"]
                assert "whose UV islands do not cover the whole tile" in message, message
                assert f'the {kind} "{source}" reads the combined virtual normal' in message
                assert "island-edge texels" in message and "recording R-090" in message, message
                assert "no recording shows it for a Height without layers" in message, message
                assert "phase1.25_pilot-wand item 2.7" in message and "decision 245" in message
                assert files_under(out) == {}, case

    # The five-map export, refused as a whole: its first map under `infinite` (decision 259), its
    # Normal under `passthrough`.
    for padding, refusal in (("infinite", "decision 259"), ("passthrough", "island-edge texels")):
        out = tmp_path / f"five-{padding}"
        cfg = config(out, root="uzp_sphere", paddingAlgorithm=padding)
        cfg["exportPresets"][0]["maps"] += normal_map()
        result = export(export_tests, relief, cfg, tmp_path / f"run-five-{padding}")
        assert result.get("error") == "NotYetSupported", (padding, result)
        assert refusal in result["message"], (padding, result["message"])
        assert files_under(out) == {}, padding

    grid = variant("grid", GRID, "s0", height=False)
    for kind, source in sources:
        case = f"grid-{source.replace('/', '-')}"
        out = tmp_path / case
        cfg = single(out, "s0", kind, source, "infinite")
        result = export(export_tests, grid, cfg, tmp_path / f"run-{case}")
        assert "error" not in result, (case, result)
        assert len(files_under(out)) == 1, case


# ── Tier 0 (owner's machine) ─────────────────────────────────────────────────


def test_island_edge_normals_differ_from_painter(export_tests: Path, tmp_path: Path) -> None:
    """Decision 245, the evidence of the refusal above: on the recorded height-normal sphere and
    bevelled cube, UzPainter's evaluated Normal_OpenGL equals Painter's on every interior texel and
    differs on island-edge texels, where Painter's r1 and r2 agree; and Painter's Normal_OpenGL
    covered texels are the same under every padding of export-padding (passthrough, infinite,
    color, transparent and diffusion at every dilation), so no padding rule can make them exact."""
    from tests.export import encoders_tier0

    report = encoders_tier0.island_edge_normals(export_tests, tmp_path)
    print(json.dumps(report, indent=1))
    goldens = report["goldens"]
    assert set(goldens) == set(encoders_tier0.ISLAND_NORMAL_GOLDENS)
    for counts in goldens.values():
        assert counts["interior_differing"] == 0, counts
        assert 0 < counts["edge_differing"] <= counts["edge"], counts
        assert counts["edge_r1_r2_differing"] == 0, counts
    paddings = report["every_padding"]
    assert len(paddings) == 46, sorted(paddings)
    assert set(paddings.values()) == {0}, paddings


@pytest.fixture(scope="module")
def tier0_reports(
    export_tests: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from tests.export import encoders_tier0
    from tests.export.tier0 import needs_store

    needs_store()
    work = tmp_path_factory.mktemp("encoders-tier0")
    reencoded = encoders_tier0.reencode_painter_files(export_tests, work / "reencode")
    exported = encoders_tier0.export_goldens(export_tests, work / "export", runs=2)
    processed = encoders_tier0.process_painter_files(export_tests, work / "process")
    return reencoded, exported, processed


def test_painter_files_reencode_byte_for_byte(
    tier0_reports: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    """2.6, 3.4: every distinct PNG16 and OpenEXR 32f file Painter exported in the current envelope,
    decoded at native depth and encoded again by EncodePng / EncodeExr, is byte-identical."""
    reencoded, _, _ = tier0_reports
    assert reencoded["files"]["png"] > 0 and reencoded["files"]["exr"] > 0
    assert reencoded["differing"] == [], reencoded["differing"][:10]
    assert reencoded["identical"] == reencoded["files"]


def test_written_goldens_equal_painter_files(
    tier0_reports: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    """3.1, 3.3, 3.4, 3.5: every export step of the goldens of EXPORT_GOLDENS, written by
    WriteExport in two processes: the dry run's files, identical across the processes, and
    byte-identical to Painter's files (PNG16 and OpenEXR 32f, infinite padding without
    dithering on complete coverage)."""
    _, exported, _ = tier0_reports
    assert exported["steps"] > 0 and exported["files"] > 0
    assert exported["problems"] == [], exported["problems"][:10]
    assert exported["identical_to_painter"] == exported["comparisons"]


def test_processing_reproduces_painter_files(
    tier0_reports: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    """6.1 (decision 103): Painter's own file of each map, as the raster, encoded with the
    processing of its other files gives those files byte for byte: PNG 8, PNG 16 and OpenEXR 16f of
    every channel, mesh map and Height of export-bit-depth (sRGB8 material channels sRGB-encoded in
    PNG, decision 126), PNG 16 with dithering of export-dither, and the L+A and RGB+A PNG 16 files
    of export-alpha-layouts (an all-opaque alpha dropped)."""
    _, _, processed = tier0_reports
    assert processed["cases"] and processed["differing"] == [], processed["differing"][:10]
    assert processed["identical"] == processed["cases"]
    assert processed["layouts"]["LA"] > 0 and processed["layouts"]["RGBA"] > 0
    assert sum(processed["srgb8_cases"].values()) == 2 * 8 * 3 * 3


def test_infinite_padding_on_islands_keeps_covered_texels_exact(
    export_tests: Path, tmp_path: Path
) -> None:
    """Decision 223's rule, measured (decision 259: the export refuses it): every r1 `infinite`
    file of the recorded padding goldens, padded by ApplyPadding from Painter's OpenEXR 32f file of
    the map over the golden's mesh, equals Painter's file exactly on every covered texel (PNG 8,
    PNG 16, OpenEXR); the export's coverage equals `tools.parity.coverage`'s, and on the
    position-encoded probes that coverage is exactly the texels holding their own centre
    (Painter's). The padding texels differ (the exact rule is open, item 2.7); their max |delta| is
    printed, never asserted."""
    from tests.export import encoders_tier0

    report = encoders_tier0.padding_goldens(export_tests, tmp_path / "padding")
    files = report["files"]
    assert len({f["golden"] for f in files}) == len(encoders_tier0.PADDING_GOLDENS)
    assert [f for f in files if not f["coverage_equal"] or not f["covered_equal"]] == []
    assert report["position_probe_mismatches"] == dict.fromkeys(encoders_tier0.POSITION_PROBES, 0)
    print(json.dumps(files, indent=1))


def test_srgb8_material_channels_equal_painter_files(export_tests: Path, tmp_path: Path) -> None:
    """2.6 (decision 126): export-bit-depth's BaseColor, Specular and Emissive (colour bitmaps,
    uniform colours stored as the facade stores them, empty channels over their linear template
    constants and channel defaults; every set: s4, s5 and s7 fill them from grey 16-bit bitmaps
    in the sRGB space, phase1.15_compositor-colour-fits item 2.2), rebuilt per texture set and
    written by WriteExport at PNG 8, PNG 16, OpenEXR 16f and OpenEXR 32f, are byte-identical to
    Painter's files (r1 and r2)."""
    from tests.export import encoders_tier0

    report = encoders_tier0.srgb8_material_written(export_tests, tmp_path)
    assert report["problems"] == [], report["problems"][:10]
    assert report["files"] == 8 * 4 * 3, report
    assert report["identical"] == report["comparisons"] == 2 * report["files"], report


def test_observed_template_bases_equal_painter_files(export_tests: Path, tmp_path: Path) -> None:
    """2.6 (decisions 168, 169, 172, 204): the empty BaseColor or Specular of every shipped
    template, written by WriteExport at OpenEXR 32f and PNG 16 (the 24 `export-template-base-*`
    goldens, 25 maps) and at OpenEXR 32f (the empty set s7 of three float virtual-map twins), is
    byte-identical to Painter's files (r1 and r2). Dota 2's L8 Specular included: its PNG 16
    holds (14330, 2570, 14330), the sRGB encode of float32(10/255) in R and B and its linear
    write in G (decision 204)."""
    from tests.export import encoders_tier0

    report = encoders_tier0.template_bases_written(export_tests, tmp_path)
    assert report["problems"] == [], report["problems"][:10]
    assert report["refused"] == [], report["refused"]
    assert report["files"] == 25 * 4 + 3 * 2, report
    assert report["identical"] == report["comparisons"] == 2 * report["files"], report


def test_l8_material_channels_equal_painter_files(export_tests: Path, tmp_path: Path) -> None:
    """Decision 204: export-l8-material's L8 BaseColor, Specular and Emissive as RGB and as L.

    - Painter's OpenEXR 32f file of every map (all four sets, 183 distinct codes), as the raster of
      its PNG 8 and PNG 16 files, encodes to those files byte for byte (r1 and r2): the sRGB encode
      of the linear value in R, B and L, its linear write in G.
    - Rebuilt per texture set and written by WriteExport at every export step (PNG 8, PNG 16 and
      OpenEXR 32f), every set is byte-identical to Painter's files (r1 and r2): grey A (s0) and the
      8-bit grey ramp (s1) in sRGB at 1:1, read through the float32 shader decode, an 8-bit code's
      rounded toward zero to a binary16 (decision 208), the uniform colour (s2) and the empty
      stack's bases (s3)."""
    from tests.export import encoders_tier0

    processed = encoders_tier0.l8_material_processed(export_tests, tmp_path / "process")
    assert processed["differing"] == [], processed["differing"][:10]
    assert processed["identical"] == processed["cases"] == 2 * 4 * 3 * 4, processed
    assert processed["layouts"] == {"RGB": 48, "L": 48}, processed

    report = encoders_tier0.l8_material_written(export_tests, tmp_path / "written")
    assert report["problems"] == [], report["problems"][:10]
    assert report["refused"] == [], report["refused"]
    assert report["files"] == 4 * 12 * 3, report
    assert report["identical"] == report["comparisons"] == 2 * report["files"], report


def test_srgb8_bitmap_equals_painter_files(export_tests: Path, tmp_path: Path) -> None:
    """phase1.15_compositor-colour-fits items 2.2 and 2.4: export-ocio-encode-legacy's BaseColor
    filled from the authored 8-bit sRGB ramp at 1:1 (UV, BilinearHQ, RepeatNone) in the sRGB space
    (s3: each 8-bit code is its own sRGB8 code, sources.h), in Raw (s4) and in the sRGB space
    inside a group masked by grey A (s5), rebuilt per texture set and written by WriteExport at
    PNG 16, PNG 8 and OpenEXR 32f, is byte-identical to Painter's files: r1 and r2 of s3 and s4,
    r1 of s5. Painter is unstable on s5 (decision 032): its r2 is judged through the exception
    register, where EXC-006 covers it (decision 152)."""
    from tests.export import encoders_tier0

    report = encoders_tier0.srgb8_bitmap_written(export_tests, tmp_path)
    assert report["problems"] == [], report["problems"][:10]
    assert report["files"] == 3 * 3, report
    assert report["identical"] == report["comparisons"] == 2 * report["files"] - 3, report
    assert [(where, outcomes, relied) for where, _, outcomes, relied in report["register"]] == [
        (f"s5 step {step}", ["pass", "pass"], [("EXC-006", 1)]) for step in (46, 47, 48)
    ], report["register"]


def test_ocio_encode_equals_painter_files(export_tests: Path, tmp_path: Path) -> None:
    """phase1.15_compositor-colour-fits item 2.3 (decision 190): export-ocio-encode (Session O,
    OCIO with Painter's substance config) rebuilt per texture set as an OCIO project and written by
    WriteExport, every map of steps 46-49 and the `$colorSpace` probes 50 and 51, is byte-identical
    to Painter's files: r1 everywhere, r2 wherever r2 equals r1 (s5's BaseColor, an sRGB bitmap
    in a group masked by grey A, is unstable in Painter: r1 is its exact target, decision 032).
    This covers the measured PNG 16 encode of the sRGB8 codes and the empty BaseColor (s0-s7), the
    8-bit Raw bitmap read through a binary16 rounded toward zero (s4), and the probes' names
    (`sRGB`, `Raw`)."""
    from tests.export import encoders_tier0

    report = encoders_tier0.ocio_encode_written(export_tests, tmp_path)
    assert report["problems"] == [], report["problems"][:10]
    assert report["files"] == 8 * (4 + 4 + 1 + 1 + 3 + 3), report
    assert report["names"] == 8 * 3 * 2, report
    assert report["unstable"] == [
        "s5 step 46: s5_basecolor.png",
        "s5 step 47: s5_basecolor.png",
        "s5 step 48: s5_basecolor.exr",
        "s5 probe 50: s5_basecolor_sRGB.png",
        "s5 probe 51: s5_basecolor_sRGB.png",
    ], report["unstable"]
    assert report["identical"] == report["comparisons"] == 2 * report["files"] - 5, report


def test_painter_ocio_png16_differs_from_legacy_on_74_values() -> None:
    """B17 of the practical end-to-end run (decision 190): Painter's own PNG 16 of an sRGB8
    BaseColor differs between its OCIO and Legacy twins (export-ocio-encode against
    export-ocio-encode-legacy) by one code, on exactly `OCIO_PNG16_DIFFERING_CODES` of the 256
    sRGB8 codes (s3) and on the empty BaseColor (s7), in both recordings; their PNG 8 and OpenEXR
    32f files are byte-identical. A Legacy and an OCIO export of one stack differing there is
    parity, not a bug."""
    from tests.export import encoders_tier0

    report = encoders_tier0.painter_ocio_against_legacy()
    assert report["problems"] == [], report["problems"]
    assert report["different"] == [], report["different"]
    assert len(report["same"]) == 2 * len(encoders_tier0.OCIO_TWIN_SETS) * 2, report["same"]
    for recording in ("r1", "r2"):
        ocio = report["tables"][("ocio", recording)]
        legacy = report["tables"][("legacy", recording)]
        assert sorted(ocio) == sorted(legacy) == list(range(256)), recording
        differing = [c for c in range(256) if ocio[c] != legacy[c]]
        assert differing == list(encoders_tier0.OCIO_PNG16_DIFFERING_CODES), (recording, differing)
        assert {c: ocio[c] - legacy[c] for c in differing if ocio[c] - legacy[c] != -1} == {6: 1}
        for mode, code in encoders_tier0.OCIO_EMPTY_BASECOLOR_PNG16.items():
            assert report["empty"][(mode, recording)] == [code], (mode, recording)


def test_ocio_png16_differs_from_legacy_where_painter_does(
    export_tests: Path, tmp_path: Path
) -> None:
    """B17 of the practical end-to-end run (decision 190): a stack that stores the same values
    under Legacy and OCIO, exported from a Legacy and from an OCIO project, gives the same PNG 8
    and OpenEXR 32f files, and PNG 16 files that differ by one code exactly where Painter's do
    (`OCIO_PNG16_DIFFERING_CODES` and the empty BaseColor, pinned on Painter's files by
    `test_painter_ocio_png16_differs_from_legacy_on_74_values`): export-ocio-encode's s3 (every
    sRGB8 code of the authored ramp on BaseColor at 1:1) and s7 (the empty BaseColor), rebuilt
    from the repository's manifest. A value outside the recorded ones, the luma of the ramp, is
    written under Legacy and refused under OCIO before anything is written."""
    from tests.export import encoders_tier0
    from tools.parity.fit.decode import decode

    report = encoders_tier0.ocio_twin_written(export_tests, tmp_path)
    files = report["files"]
    expected = ["s3 luma", *(f"{s} step {n}" for s in ("s3", "s7") for n in (46, 47, 48))]
    assert sorted(files) == expected, dict(report["refused"])
    for where in ("s3 step 47", "s3 step 48", "s7 step 47", "s7 step 48"):
        assert files[where]["legacy"].read_bytes() == files[where]["ocio"].read_bytes(), where

    def values(where: str, mode: str) -> np.ndarray:
        result: np.ndarray = decode(files[where][mode].read_bytes()).values.reshape(-1)
        return result.astype(np.int64)

    codes = values("s3 step 47", "legacy")
    legacy, ocio = values("s3 step 46", "legacy"), values("s3 step 46", "ocio")
    assert sorted(set(codes.tolist())) == list(range(256))
    for png16 in (legacy, ocio):  # each a function of the stored code
        assert len(set(zip(codes.tolist(), png16.tolist(), strict=True))) == 256
    assert sorted(set(codes[legacy != ocio].tolist())) == list(
        encoders_tier0.OCIO_PNG16_DIFFERING_CODES
    )
    assert set((ocio - legacy).tolist()) == {-1, 0, 1}
    for mode, code in encoders_tier0.OCIO_EMPTY_BASECOLOR_PNG16.items():
        assert sorted(set(values("s7 step 46", mode).tolist())) == [code], mode

    assert set(files["s3 luma"]) == {"legacy"}, dict(report["refused"])
    error, message, written = report["refused"]["s3 luma"]["ocio"]
    assert error == "Failure" and message.startswith("evaluator:unsupported_source"), message
    assert "under OCIO, the PNG encode of the linear value" in message, message
    assert "decision 190" in message, message
    assert written == []


def test_srgb_variants_equal_painter_files(export_tests: Path, tmp_path: Path) -> None:
    """phase1.15_compositor-colour-fits item 2.2 (decision 174): srgb-bitmap-variants-v2 rebuilt
    per texture set and written by WriteExport at PNG 16, PNG 8 and OpenEXR 32f, every map, is
    byte-identical to Painter's files: the 8-bit grey sRGB ramp at 1:1 (s0); field A and the 8-bit
    sRGB ramp magnified by BilinearHQ (s2) and under Nearest at scale 2 (s3); the user channels
    whose sRGB Painter refused, read as Data (s4); BaseColor under a mask whose grey source stays
    Data (s5, r1: Painter is unstable there, decision 032); Working, Legacy Linear and Legacy sRGB
    (s6-s8). s1 (BilinearHQ minification at 30 degrees) is refused for every bitmap."""
    from tests.export import encoders_tier0

    report = encoders_tier0.srgb_variants_written(export_tests, tmp_path)
    assert report["problems"] == [], report["problems"][:10]
    assert set(report["refused"]) == {"s1"}, report["refused"]
    assert report["files"] == 8 * 8 * 3, report
    assert report["unstable"] == [
        f"s5 step {step}: s5_basecolor.{ext}"
        for step, ext in ((78, "png"), (80, "png"), (82, "exr"))
    ], report["unstable"]
    assert report["identical"] == report["comparisons"] == 2 * report["files"] - 3, report


def test_srgb_minification_equals_painter_files(export_tests: Path, tmp_path: Path) -> None:
    """phase1.15_compositor-colour-fits items 2.5 and 2.7 (decisions 203, 219):
    srgb-bitmap-minification rebuilt per texture set and written by WriteExport at PNG 16, PNG 8
    and OpenEXR 32f is byte-identical to Painter's files, r1 and r2, for field A (16-bit, s4-s7)
    on BaseColor minified by BilinearHQ and BilinearSharp at scales 2 and 4 (each texel decoded to
    float32 before the texture unit samples its float32 mip chain) and for the 8-bit sRGB ramp at
    scale 2 (s0, s2: the sRGB8 texture's filter on level 0). The ramp at scale 4 (s1, s3) reads
    the sRGB8 mip levels, which are not measured, and is refused."""
    from tests.export import encoders_tier0

    report = encoders_tier0.srgb_minification_written(export_tests, tmp_path)
    assert report["problems"] == [], report["problems"][:10]
    assert set(report["refused"]) == {"s1", "s3"}, report["refused"]
    for message in report["refused"].values():
        assert "8-bit sRGB bitmap" in message and "decision 219" in message, message
    assert report["files"] == 6 * 3, report
    assert report["identical"] == report["comparisons"] == 2 * report["files"], report


def test_published_export_processing_reproduces(
    tier0_reports: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
) -> None:
    """2.7: `parity/semantics/export-processing.json` is valid, states `exact` only with zero
    residuals and equals what this machine's comparisons derive."""
    from tests.export import encoders_tier0
    from tools.parity.schemas import Schema, validation_errors

    reencoded, exported, processed = tier0_reports
    published = json.loads(encoders_tier0.PUBLISHED.read_text(encoding="utf-8"))
    assert validation_errors(published, Schema.SEMANTICS) == []
    for item in published["entries"]:
        zero = all(r["difference"]["differing"] == 0 for r in item["residuals"])
        if item["status"] != "gap":
            assert (item["status"] == "exact") == zero, item["entry_id"]
    assert encoders_tier0.publish(reencoded, exported, processed) == published
