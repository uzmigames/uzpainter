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
    """3.5, 3.6: PNG16 (grey, RGB) and OpenEXR 32f (grey, RGB) images of ramps, runs, noise and
    special floats (signed zero, subnormal, maximum, infinities, NaN payloads), at 1x1 and odd
    sizes: decoded back they equal the encoded values bit for bit (spng and tinyexr in the
    process; independently the repository's own PNG decoder, and OpenEXR's when installed),
    encoding twice gives the same bytes, and two processes write identical files."""
    from tools.parity.feasibility import png

    first = run(export_tests, "roundtrip", str(tmp_path / "a"))
    second = run(export_tests, "roundtrip", str(tmp_path / "b"))
    assert len(first) == 8
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
            assert np.array_equal(decoded, synthetic_png(w, h, c))
        elif OpenEXR is not None:
            with OpenEXR.File(str(tmp_path / "a" / result["name"]), separate_channels=True) as exr:
                planes = exr.channels()
                names = ["Y"] if c == 1 else ["R", "G", "B"]
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
    """A texture set `name` (the mesh material it covers) of the grid mesh: BaseColor sRGB8,
    Height L16F and SpecularRoughness L16 filled from a ramp bitmap."""
    tmp.mkdir(parents=True, exist_ok=True)
    sha = ramp_png(tmp / "ramp.png")
    bitmap = {"bitmap": sha, "color_space": "Raw"}
    document: dict[str, Any] = {
        "name": name,
        "resolution": [256, 256],
        "channels": [
            {"type": "BaseColor", "format": "sRGB8"},
            {"type": "Height", "format": "L16F"},
            {"type": "SpecularRoughness", "format": "L16"},
        ],
        "resources": [{"sha256": sha, "png": "ramp.png"}],
        "layers": [
            {
                "kind": "fill",
                "sources": {"BaseColor": bitmap, "Height": bitmap, "SpecularRoughness": bitmap},
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
    """BaseColor (RGB), Roughness (L) and Height (L) of `root`; Height as OpenEXR 32f by a
    rule."""
    return {
        "exportShaderParams": False,
        "exportPath": out.as_posix(),
        "defaultExportPreset": "p",
        "exportPresets": [
            {
                "name": "p",
                "maps": [
                    {
                        "fileName": "$textureSet_BaseColor",
                        "channels": [chan(c, "documentMap", "basecolor") for c in "RGB"],
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
                "s0_BaseColor.png",
                "s0_Height.exr",
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
        ({"bitDepth": "8"}, None, "PNG at 8 bits"),
        ({}, [{"parameters": {"fileFormat": "exr", "bitDepth": "16f"}}], "OpenEXR at 16f"),
        ({"dithering": True}, None, "dithering"),
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
    """2.2-2.5 (decision 090): processing no Tier 0 recording covers raises NotYetSupported naming
    recording R-090, and nothing exists under exportPath afterwards."""
    out = tmp_path / "out"
    result = export(
        export_tests, spec(tmp_path / "spec"), config(out, rules, **params), tmp_path / "run"
    )
    assert result.get("error") == "NotYetSupported", result
    assert expected in result["message"] and "R-090" in result["message"], result["message"]
    assert files_under(out) == {}


def test_alpha_layouts_are_refused_before_writing(export_tests: Path, tmp_path: Path) -> None:
    """2.5 (decision 090): an RGB+A map (alpha from a defaultMap) is refused, naming R-090."""
    out = tmp_path / "out"
    cfg = config(out)
    cfg["exportPresets"][0]["maps"][0]["channels"].append(chan("A", "defaultMap", "white"))
    result = export(export_tests, spec(tmp_path / "spec"), cfg, tmp_path / "run")
    assert result.get("error") == "NotYetSupported", result
    assert "RGBA layout" in result["message"] and "R-090" in result["message"]
    assert files_under(out) == {}


def test_padding_needs_complete_coverage_or_a_mesh(export_tests: Path, tmp_path: Path) -> None:
    """2.2 (decision 090): on the sphere, whose UV islands leave texels uncovered, `infinite` and
    `passthrough` padding are refused naming R-090; without a texturing mesh the export fails
    before writing; nothing is written either way."""
    for padding in ("infinite", "passthrough"):
        out = tmp_path / padding
        cfg = config(out, root="uzp_sphere", paddingAlgorithm=padding)
        sphere = spec(tmp_path / "sphere", SPHERE, "uzp_sphere")
        result = export(export_tests, sphere, cfg, tmp_path / f"run-{padding}")
        assert result.get("error") == "NotYetSupported", result
        assert "do not cover the whole tile" in result["message"] and "R-090" in result["message"]
        assert files_under(out) == {}
    out = tmp_path / "no-mesh"
    result = export(export_tests, spec(tmp_path / "bare", None), config(out), tmp_path / "run-bare")
    assert result.get("error") == "Failure" and "no texturing mesh" in result["message"], result
    assert files_under(out) == {}


# ── Tier 0 (owner's machine) ─────────────────────────────────────────────────


@pytest.fixture(scope="module")
def tier0_reports(
    export_tests: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[dict[str, Any], dict[str, Any]]:
    from tests.export import encoders_tier0
    from tests.export.tier0 import needs_store

    needs_store()
    work = tmp_path_factory.mktemp("encoders-tier0")
    reencoded = encoders_tier0.reencode_painter_files(export_tests, work / "reencode")
    exported = encoders_tier0.export_goldens(export_tests, work / "export", runs=2)
    return reencoded, exported


def test_painter_files_reencode_byte_for_byte(
    tier0_reports: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    """2.6, 3.4: every distinct PNG16 and OpenEXR 32f file Painter exported in the current envelope,
    decoded at native depth and encoded again by EncodePng / EncodeExr, is byte-identical."""
    reencoded, _ = tier0_reports
    assert reencoded["files"]["png"] > 0 and reencoded["files"]["exr"] > 0
    assert reencoded["differing"] == [], reencoded["differing"][:10]
    assert reencoded["identical"] == reencoded["files"]


def test_written_goldens_equal_painter_files(
    tier0_reports: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    """3.1, 3.3, 3.4, 3.5: every export step of the goldens of EXPORT_GOLDENS, written by
    WriteExport in two processes: the dry run's files, identical across the processes, and
    byte-identical to Painter's files (PNG16 and OpenEXR 32f, infinite padding without
    dithering on complete coverage)."""
    _, exported = tier0_reports
    assert exported["steps"] > 0 and exported["files"] > 0
    assert exported["problems"] == [], exported["problems"][:10]
    assert exported["identical_to_painter"] == exported["comparisons"]


def test_published_export_processing_reproduces(
    tier0_reports: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    """2.7: `parity/semantics/export-processing.json` is valid, states `exact` only with zero
    residuals and equals what this machine's comparisons derive."""
    from tests.export import encoders_tier0
    from tools.parity.schemas import Schema, validation_errors

    reencoded, exported = tier0_reports
    published = json.loads(encoders_tier0.PUBLISHED.read_text(encoding="utf-8"))
    assert validation_errors(published, Schema.SEMANTICS) == []
    for item in published["entries"]:
        zero = all(r["difference"]["differing"] == 0 for r in item["residuals"])
        if item["status"] != "gap":
            assert (item["status"] == "exact") == zero, item["entry_id"]
    assert encoders_tier0.publish(reencoded, exported) == published
