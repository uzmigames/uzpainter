"""CPU publication checks for UzEngine normal derivatives (writer items 2.7 and 3.5).

Inputs are authored here; no Painter recording or oracle is needed for the UzEngine extension.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.export.test_export_encoders import GRID, TEMPLATES, chan
from tests.export.test_export_publication import consumed, one
from tools.parity.feasibility import png

SIZE = 128
NEGATIVE_X = 5
NEGATIVE_Y = 3


def normal_spec(root: Path, *, negative: bool) -> Path:
    """Full UV coverage and one authored negative-Z texel, without height reconstruction."""
    root.mkdir(parents=True)
    pixels = np.full((SIZE, SIZE, 3), 32768, dtype=np.int64)
    pixels[:, :, 2] = 65535
    if negative:
        pixels[NEGATIVE_Y, NEGATIVE_X, 2] = 0
    data = png.encode(pixels, 16)
    (root / "normal.png").write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    document = {
        "name": "s0",
        "resolution": [SIZE, SIZE],
        "mesh": str(GRID),
        "channels": [{"type": "Normal", "format": "RGB16F"}],
        "resources": [{"sha256": sha, "png": "normal.png"}],
        "layers": [
            {
                "kind": "fill",
                "sources": {"Normal": {"bitmap": sha, "color_space": "Raw"}},
                "blending": {"Normal": {"mode": "Normal", "opacity": 1.0}},
            }
        ],
    }
    path = root / "spec.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def canonical_config(out: Path) -> dict[str, Any]:
    return {
        "exportShaderParams": False,
        "exportPath": str(out),
        "defaultExportPreset": "authored-normal",
        "exportPresets": [
            {
                "name": "authored-normal",
                "maps": [
                    {
                        "fileName": "$textureSet_Normal",
                        "channels": [chan(c, "documentMap", "normal") for c in "RGB"],
                    }
                ],
            }
        ],
        "exportList": [{"rootPath": "s0"}],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": "png",
                    "bitDepth": "16",
                    "paddingAlgorithm": "passthrough",
                    "dithering": False,
                }
            }
        ],
    }


def publish(
    exe: Path,
    spec: Path,
    config: dict[str, Any],
    config_path: Path,
    derivative: str | None = None,
) -> dict[str, Any]:
    config_path.write_text(json.dumps(config), encoding="utf-8")
    extra = ("--uztexture", derivative) if derivative is not None else ()
    return one(exe, "publish", str(TEMPLATES), str(spec), str(config_path), *extra)


def selected_files(exe: Path, out: Path) -> tuple[Path, dict[str, Any]]:
    selected = consumed(exe, out)
    assert "error" not in selected, selected
    generation = out / "generations" / selected["generation"]
    receipt = json.loads((generation / "receipt.json").read_text(encoding="utf-8"))
    for entry in receipt["files"]:
        data = (generation / "files" / entry["path"]).read_bytes()
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert selected["files"][entry["path"]] == entry["sha256"]
    return generation, receipt


def test_authored_normal_canonical_preserves_negative_z(export_tests: Path, tmp_path: Path) -> None:
    spec = normal_spec(tmp_path / "input", negative=True)
    out = tmp_path / "canonical"
    result = publish(export_tests, spec, canonical_config(out), tmp_path / "config.json")
    assert "error" not in result, result
    generation, _ = selected_files(export_tests, out)
    data = (generation / "files" / "s0_Normal.png").read_bytes()
    assert png.chunks(data)[0][1][8] == 16
    pixels = png.decode(data).reshape(SIZE, SIZE, 3)
    negative = pixels[:, :, 2] <= 32767
    assert np.count_nonzero(negative) == 1
    assert negative[NEGATIVE_Y, NEGATIVE_X]


def derivative_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    assert [entry["path"] for entry in receipt["files"]] == [
        "s0_Normal.png",
        "s0_Normal.uztexture",
    ]
    entry: dict[str, Any] = receipt["files"][1]
    assert (entry["format"], entry["bit_depth"], entry["colour_space"]) == (
        "uztexture",
        "8",
        "linear",
    )
    metadata = entry["uztexture"]
    assert metadata["source"] == "s0_Normal.png"
    assert metadata["binding"] == "normal" and metadata["srgb"] is False
    assert metadata["encoder"] == "etcpak 2.1"
    return entry


@pytest.mark.parametrize("suffix", ["", ":fail"])
def test_negative_normal_fail_preserves_published_generation(
    export_tests: Path, tmp_path: Path, suffix: str
) -> None:
    positive = normal_spec(tmp_path / "positive", negative=False)
    negative = normal_spec(tmp_path / "negative", negative=True)
    out = tmp_path / "out"
    config = canonical_config(out)
    result = publish(
        export_tests, positive, config, tmp_path / "positive.json", "s0_Normal.png" + suffix
    )
    assert "error" not in result, result
    generation, receipt = selected_files(export_tests, out)
    metadata = derivative_receipt(receipt)["uztexture"]
    assert metadata["format"] == "BC5"
    assert metadata["negative_z"] == {
        "policy": "fail",
        "texels": 0,
        "first": None,
        "routed": False,
    }
    pointer = (out / "current.json").read_bytes()
    previous = {
        p.relative_to(generation): p.read_bytes() for p in generation.rglob("*") if p.is_file()
    }
    consumer = consumed(export_tests, out)
    result = publish(
        export_tests, negative, config, tmp_path / "negative.json", "s0_Normal.png" + suffix
    )
    assert result["error"] == "Failure", result
    assert "1 texel(s) with negative Z" in result["message"], result
    assert f"first at {NEGATIVE_X}, {NEGATIVE_Y}" in result["message"], result
    assert "negative-Z policy is fail" in result["message"], result
    assert (out / "current.json").read_bytes() == pointer
    assert [p.name for p in (out / "generations").iterdir()] == [generation.name]
    assert {
        p.relative_to(generation): p.read_bytes() for p in generation.rglob("*") if p.is_file()
    } == previous
    assert consumed(export_tests, out) == consumer


def test_negative_normal_rgb_publishes_canonical_and_guard_receipt(
    export_tests: Path, tmp_path: Path
) -> None:
    spec = normal_spec(tmp_path / "input", negative=True)
    reference = tmp_path / "reference"
    assert "error" not in publish(
        export_tests, spec, canonical_config(reference), tmp_path / "reference.json"
    )
    reference_generation, _ = selected_files(export_tests, reference)
    out = tmp_path / "out"
    result = publish(
        export_tests, spec, canonical_config(out), tmp_path / "rgb.json", "s0_Normal.png:rgb"
    )
    assert "error" not in result, result
    generation, receipt = selected_files(export_tests, out)
    entry = derivative_receipt(receipt)
    metadata = entry["uztexture"]
    assert metadata["format"] == "RGBA8"
    assert metadata["negative_z"] == {
        "policy": "rgb",
        "texels": 1,
        "first": [NEGATIVE_X, NEGATIVE_Y],
        "routed": True,
    }
    assert any(gap["channel"] == "Normal" for gap in entry["consumer_gaps"])
    canonical = (generation / "files" / "s0_Normal.png").read_bytes()
    assert canonical == (reference_generation / "files" / "s0_Normal.png").read_bytes()
    cooked = (generation / "files" / "s0_Normal.uztexture").read_bytes()
    header = struct.unpack_from("<16I", cooked)
    assert header[:7] == (0x5A585455, 1, SIZE, SIZE, SIZE.bit_length(), 0, 0)
    assert header[7:] == (0,) * 9
    assert metadata["mips"] == header[4]
    expected_offset = 64 + header[4] * 24
    for level in range(header[4]):
        offset, size, width, height = struct.unpack_from("<QQII", cooked, 64 + 24 * level)
        assert width == height == max(1, SIZE >> level)
        assert offset == expected_offset and size == width * height * 4
        expected_offset += size
        if level == 0:
            pixels = np.frombuffer(cooked, dtype=np.uint8, count=size, offset=offset).reshape(
                SIZE, SIZE, 4
            )
            assert pixels[NEGATIVE_Y, NEGATIVE_X, 2] < 128
            assert np.count_nonzero(pixels[:, :, 2] < 128) == 1
            assert np.all(pixels[:, :, 3] == 255)
    assert expected_offset == len(cooked)
    plan = json.loads((generation / "plan.json").read_text(encoding="utf-8"))
    assert plan["files"][0]["uztexture"]["negativeZ"] == "rgb"
