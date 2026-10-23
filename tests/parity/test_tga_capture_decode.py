"""Authored TGA8 storage, orientation and packet checks for the recorder and fit reader."""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from PIL import Image

from tools.parity import tga
from tools.parity.fit.decode import decode
from tools.parity.recorder.capture import MEDIA_TYPES, measure_storage_format
from tools.parity.recorder.job import ExportStep, OutputMap
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.recorder.texture import export_outputs
from tools.parity.schemas import REPO_ROOT


def header(channels: int, rle: bool, origin: int, width: int = 3, height: int = 2) -> bytes:
    kind = 3 if channels <= 2 else 2
    return (
        struct.pack(
            "<BBBHHBHHHHBB",
            3,
            0,
            kind + (8 if rle else 0),
            0,
            0,
            0,
            0,
            0,
            width,
            height,
            channels * 8,
            origin | (8 if channels in (2, 4) else 0),
        )
        + b"id!"
    )


@pytest.mark.parametrize("channels", [1, 2, 3, 4])
@pytest.mark.parametrize("rle", [False, True])
@pytest.mark.parametrize("origin", [0, 16, 32, 48])
def test_measure_and_decode_preserve_orientation_channels_and_alpha(
    tmp_path: Path, channels: int, rle: bool, origin: int
) -> None:
    expected = (np.arange(6 * channels, dtype=np.uint8) * 7).reshape(2, 3, channels)
    if channels in (2, 4):
        expected[0, 0, -1], expected[1, 2, -1] = 0, 255
    order = expected.copy()
    if not origin & 32:
        order = order[::-1]
    if origin & 16:
        order = order[:, ::-1]
    if channels >= 3:
        order = order[..., [2, 1, 0, *range(3, channels)]]
    payload = (bytes([5]) if rle else b"") + order.tobytes()
    content = header(channels, rle, origin) + payload
    # TGA 2.0 footer and image identifier are not image pixels.
    content += struct.pack("<II", 0, 0) + b"TRUEVISION-XFILE.\0"
    path = tmp_path / "unrelated-name.TGA"
    path.write_bytes(content)
    measured = measure_storage_format(path)
    assert (measured.container, measured.sample_type, measured.bits_per_channel) == (
        "tga",
        "uint",
        8,
    )
    assert measured.channels == channels and measured.encoding is None
    assert MEDIA_TYPES[measured.container] == "image/x-tga"
    decoded = decode(content)
    assert decoded.integer and decoded.bits == 8
    np.testing.assert_array_equal(decoded.values, expected)
    with Image.open(io.BytesIO(content)) as independent:
        assert independent.tobytes() == expected.tobytes()


@pytest.mark.parametrize("channels", [1, 2, 3, 4])
def test_mixed_packets_may_cross_rows_and_retain_exact_sample_codes(channels: int) -> None:
    first = bytes(range(1, channels + 1))
    second = bytes(range(31, 31 + channels))
    repeated = bytes(range(71, 71 + channels))
    last = bytes(range(201, 201 + channels))
    content = (
        header(channels, True, 32) + b"\x01" + first + second + b"\x82" + repeated + b"\x00" + last
    )
    decoded = tga.decode(content)
    expected = np.frombuffer(first + second + repeated * 3 + last, dtype=np.uint8).reshape(
        2, 3, channels
    )
    if channels >= 3:
        expected = expected[..., [2, 1, 0, *range(3, channels)]]
    np.testing.assert_array_equal(decoded, expected)


def test_full_128_run_and_literal_packets() -> None:
    content = header(1, True, 32, 256, 1) + b"\xff\x19\x7f" + bytes(range(128))
    expected = np.array([25] * 128 + list(range(128)), dtype=np.uint8).reshape(1, 256, 1)
    np.testing.assert_array_equal(tga.decode(content), expected)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\0" * 18,
        header(3, False, 32)[:-1],
        header(3, False, 32) + b"short",
        header(3, True, 32),
        header(3, True, 32) + b"\x85ab",
        header(3, True, 32) + b"\x05" + b"x" * 17,
        header(3, True, 32) + b"\x86abc",
        header(3, False, 32) + b"short" + struct.pack("<II", 0, 0) + b"TRUEVISION-XFILE.\0",
        header(3, False, 32) + b"x" * 18 + struct.pack("<II", 1, 0) + b"TRUEVISION-XFILE.\0",
        header(1, False, 32, 0, 2),
        header(4, True, 32, 65535, 65535),
    ],
)
def test_truncated_or_overflowing_payload_is_refused_before_decode(
    tmp_path: Path, content: bytes
) -> None:
    path = tmp_path / "bad.tga"
    path.write_bytes(content)
    with pytest.raises(RecorderError, match="TGA not supported"):
        measure_storage_format(path)
    with pytest.raises(ValueError, match="TGA:"):
        decode(content)


@pytest.mark.parametrize(
    "offset,value", [(1, 1), (2, 1), (3, 1), (5, 1), (7, 24), (16, 16), (17, 64), (17, 8)]
)
def test_palette_packed_interleaved_and_ambiguous_alpha_are_refused(
    offset: int, value: int
) -> None:
    content = bytearray(header(3, False, 32) + b"x" * 18)
    content[offset] = value
    with pytest.raises(ValueError, match="TGA:"):
        tga.inspect(bytes(content))


def test_alpha_storage_without_attribute_bits_is_not_assumed_rgba() -> None:
    content = bytearray(header(4, False, 32) + b"x" * 24)
    content[17] = 32
    with pytest.raises(ValueError, match="alpha"):
        tga.inspect(bytes(content))


@pytest.mark.parametrize("area", ["developer", "extension"])
@pytest.mark.parametrize("has_pixels", [False, True])
def test_optional_metadata_areas_cannot_supply_missing_pixels(
    tmp_path: Path, area: str, has_pixels: bool
) -> None:
    content = header(1, False, 32)
    if has_pixels:
        content += bytes(range(6))
    metadata_offset = len(content)
    content += b"ABCDEF"
    area_offset = len(content)
    if area == "developer":
        # One developer tag references bytes preceding its directory.
        content += struct.pack("<HHII", 1, 7, metadata_offset, 6)
        offsets = (0, area_offset)
    else:
        # TGA 2.0's 495-byte extension has an indirect scan-line table offset.
        extension = bytearray(495)
        struct.pack_into("<H", extension, 0, 495)
        struct.pack_into("<I", extension, 490, metadata_offset)
        content += extension
        offsets = (area_offset, 0)
    content += struct.pack("<II", *offsets) + b"TRUEVISION-XFILE.\0"
    path = tmp_path / "metadata.tga"
    path.write_bytes(content)
    with pytest.raises(RecorderError, match="extension/developer areas are not supported"):
        measure_storage_format(path)
    with pytest.raises(ValueError, match="extension/developer areas are not supported"):
        decode(content)


def test_export_capture_records_tga_blob_format_and_explicit_encoding_basis(tmp_path: Path) -> None:
    content = header(3, False, 32) + b"\xff" * 18

    def call(name: str, **kwargs: Any) -> dict[str, Any]:
        assert name == "export_textures"
        config = kwargs["config"]
        assert config["exportParameters"][0]["parameters"]["fileFormat"] == "tga"
        path = Path(config["exportPath"]) / "s_white.tga"
        path.write_bytes(content)
        return {
            "status": "Success",
            "message": "",
            "textures": [{"texture_set": "s", "stack": "", "files": [str(path)]}],
        }

    session = Mock(spec=PainterSession)
    session.call.side_effect = call
    step = ExportStep(
        1,
        (OutputMap("defaultMap", "white", "RGB"),),
        {
            "fileFormat": "tga",
            "bitDepth": "8",
            "paddingAlgorithm": "passthrough",
            "dithering": False,
        },
    )
    outputs, blobs = export_outputs(
        session, step, {"texture_sets": {"s": {"stacks": {"": {}}}}}, tmp_path
    )
    assert len(outputs) == len(blobs) == 1 and blobs[0].read_bytes() == content
    output = outputs[0]
    assert output["storage_format"] == {
        "container": "tga",
        "sample_type": "uint",
        "bits_per_channel": 8,
        "channels": 3,
        "encoding": "linear",
    }
    assert output["blob"]["media_type"] == "image/x-tga"
    assert output["export_settings"]["encoding_basis"] == "constant_default_map"
    schema = json.loads((REPO_ROOT / "parity/schema/golden-private.json").read_text())
    Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/output"}).validate(output)


def test_recorder_fingerprint_tracks_shared_tga_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.parity.recorder import environment

    directory = tmp_path / "recorder"
    directory.mkdir()
    (directory / "documented_symbols.json").write_bytes(b"{}")
    reader = tmp_path / "tga.py"
    reader.write_bytes(b"version = 1\n")
    monkeypatch.setattr(environment, "RECORDER_DIR", directory)
    environment.recorder_version.cache_clear()
    try:
        before = environment.recorder_version()
        reader.write_bytes(b"version = 2\n")
        environment.recorder_version.cache_clear()
        after = environment.recorder_version()
        assert before != after
        reader.write_bytes(b"version = 2\r\n")
        environment.recorder_version.cache_clear()
        assert environment.recorder_version() == after
    finally:
        environment.recorder_version.cache_clear()
