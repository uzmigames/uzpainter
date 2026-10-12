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
import json
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
    """A 256x256 RGB16 bitmap holding `ramp_codes` in its three components (the fill source of
    `spec`); returns its SHA-256."""
    from tools.parity.feasibility import png

    samples = np.repeat(ramp_codes()[:, :, None], 3, axis=-1)
    data = png.encode(samples.astype(np.int64), 16)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def spec(tmp: Path, mesh: Path | None = GRID, name: str = "s0") -> Path:
    """A texture set `name` (the mesh material it covers) of the grid mesh: User0 sRGB8, BaseColor
    sRGB8, Height L16F and SpecularRoughness L16 filled from a ramp bitmap, and an empty Normal
    RGB16F."""
    tmp.mkdir(parents=True, exist_ok=True)
    sha = ramp_png(tmp / "ramp.png")
    bitmap = {"bitmap": sha, "color_space": "Raw"}
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
        "layers": [
            {
                "kind": "fill",
                "sources": {
                    "User0": bitmap,
                    "BaseColor": bitmap,
                    "Height": bitmap,
                    "SpecularRoughness": bitmap,
                },
            }
        ],
    }
    if mesh is not None:
        document["mesh"] = str(mesh)
    (tmp / "spec.json").write_text(json.dumps(document), encoding="utf-8")
    return tmp / "spec.json"


def chan(dest: str, kind: str, name: str) -> dict[str, str]:
    return {"destChannel": dest, "srcChannel": dest, "srcMapType": kind, "srcMapName": name}


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


def export(exe: Path, spec_path: Path, cfg: dict[str, Any], tmp: Path) -> dict[str, Any]:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    [result] = run(exe, "export", str(TEMPLATES), str(spec_path), str(tmp / "config.json"))
    return result


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
    document["template"] = "unreal-engine"
    (tmp_path / "spec" / "unreal.json").write_text(json.dumps(document), encoding="utf-8")
    out = tmp_path / "inferred"
    cfg = config(out)
    for c in cfg["exportPresets"][0]["maps"][0]["channels"]:
        c["srcMapName"] = "basecolor"
    result = export(export_tests, tmp_path / "spec" / "unreal.json", cfg, tmp_path / "run-inferred")
    # An evaluator refusal (`unsupported_source`, NotYetSupported in the Python API, decision 082)
    # before anything is written.
    assert result.get("error") == "Failure", result
    assert result["message"].startswith("evaluator:unsupported_source"), result
    assert "inferred from its 16-bit PNG export only" in result["message"], result
    assert files_under(out) == {}


def test_no_export_reads_an_inferred_template_base(export_tests: Path, tmp_path: Path) -> None:
    """2.6 (decision 126): on a template whose BaseColor base is inferred (Unreal Engine), every
    export source that reads BaseColor fails its evaluation (`unsupported_source`) before anything
    is written: the documentMap on sRGB8 and on RGB16, and the diagnosticMap sources isolated,
    contribution, regionStats, materialView and materialLeaks of BaseColor (leaks compare the
    channel's full and solo read-outs). On the default template, whose base is observed, the same
    diagnostic sources are written. Specular and Emissive added in a format other than sRGB8 fail
    with `missing_base_value`: their channel default is recorded on sRGB8 only."""

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
    cases = [(variant("unreal", "unreal-engine"), *src) for src in sources]
    cases.append((variant("unreal-rgb16", "unreal-engine", "RGB16"), *sources[0]))
    for i, (spec_path, kind, source, layout) in enumerate(cases):
        out = tmp_path / f"inferred{i}"
        result = export(
            export_tests, spec_path, single(out, kind, source, layout), tmp_path / f"r{i}"
        )
        assert result.get("error") == "Failure", (source, result)
        assert result["message"].startswith("evaluator:unsupported_source"), (source, result)
        assert "BaseColor in template 'unreal-engine' is inferred" in result["message"], result
        assert files_under(out) == {}, source
    default = variant("default", None)
    for i, (kind, source, layout) in enumerate(sources[1:]):
        out = tmp_path / f"observed{i}"
        result = export(
            export_tests, default, single(out, kind, source, layout), tmp_path / f"o{i}"
        )
        assert "error" not in result, (source, result)
        assert files_under(out), source

    # Specular and Emissive added in a format other than sRGB8: their channel default is recorded
    # on sRGB8 only, so the evaluation fails (`missing_base_value`) before anything is written.
    for channel, fmt in (("Specular", "RGB16"), ("Emissive", "RGB16"), ("Specular", "L8")):
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
        assert "recorded as sRGB8 only" in result["message"], (channel, result)
        assert files_under(out) == {}, (channel, fmt)


def test_padding_on_islands(export_tests: Path, tmp_path: Path) -> None:
    """2.2 (decision 090): on the sphere, whose UV islands leave texels uncovered:
    - `infinite` padding is refused naming R-090, nothing written;
    - `passthrough` writes every texel's evaluated value (the L16 roughness holds the ramp's codes
      inside and outside the islands);
    - a virtualMap source with `passthrough` is refused (not recorded outside the islands);
    - without a texturing mesh the export fails before writing."""
    from tools.parity.feasibility import png

    sphere = spec(tmp_path / "sphere", SPHERE, "uzp_sphere")
    out = tmp_path / "infinite"
    result = export(export_tests, sphere, config(out, root="uzp_sphere"), tmp_path / "run-infinite")
    assert result.get("error") == "NotYetSupported", result
    assert "do not cover the whole tile" in result["message"] and "R-090" in result["message"]
    assert files_under(out) == {}

    out = tmp_path / "passthrough"
    cfg = config(out, root="uzp_sphere", paddingAlgorithm="passthrough")
    result = export(export_tests, sphere, cfg, tmp_path / "run-passthrough")
    assert "error" not in result, result
    rough = png.decode((out / "maps" / "uzp_sphere_Roughness.png").read_bytes()).astype(np.int64)
    assert np.array_equal(rough.reshape(256, 256), ramp_codes())

    out = tmp_path / "virtual"
    cfg = config(out, root="uzp_sphere", paddingAlgorithm="passthrough")
    cfg["exportPresets"][0]["maps"] = [
        {
            "fileName": "$textureSet_n",
            "channels": [chan(c, "virtualMap", "Normal_OpenGL") for c in "RGB"],
        }
    ]
    cfg["exportParameters"] = cfg["exportParameters"][:1]
    result = export(export_tests, sphere, cfg, tmp_path / "run-virtual")
    assert result.get("error") == "NotYetSupported", result
    assert "virtualMap source outside the UV islands" in result["message"]
    assert files_under(out) == {}

    out = tmp_path / "no-mesh"
    result = export(export_tests, spec(tmp_path / "bare", None), config(out), tmp_path / "run-bare")
    assert result.get("error") == "Failure" and "no texturing mesh" in result["message"], result
    assert files_under(out) == {}


# ── Tier 0 (owner's machine) ─────────────────────────────────────────────────


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


def test_srgb8_material_channels_equal_painter_files(export_tests: Path, tmp_path: Path) -> None:
    """2.6 (decision 126): export-bit-depth's BaseColor, Specular and Emissive (colour bitmaps,
    uniform colours stored as the facade stores them, empty channels over their linear template
    constants and channel defaults; sets s0-s3 and s6), rebuilt per texture set and written by
    WriteExport at PNG 8, PNG 16, OpenEXR 16f and OpenEXR 32f, are byte-identical to Painter's
    files (r1 and r2)."""
    from tests.export import encoders_tier0

    report = encoders_tier0.srgb8_material_written(export_tests, tmp_path)
    assert report["problems"] == [], report["problems"][:10]
    # s4, s5 and s7 fill these channels from grey 16-bit bitmaps (height-ramps, grey-a) in the sRGB
    # space, which the evaluator refuses before writing (phase1.14_compositor-core, sources.h).
    assert report["grey_bitmap_sets"] == {"s4", "s5", "s7"}, report
    assert report["files"] == 5 * 4 * 3, report
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
