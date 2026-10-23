"""Authored quantized TGA8 bytes; no Painter or Unreal parity claim."""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import pytest
from PIL import Image


def encode(
    executable: Path, directory: Path, width: int, height: int, channels: int, samples: bytes
) -> tuple[subprocess.CompletedProcess[str], Path]:
    raw = directory / "source.raw"
    target = directory / "result.tga"
    raw.write_bytes(samples)
    result = subprocess.run(
        [str(executable), "tga", str(width), str(height), str(channels), str(raw), str(target)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return result, target


def decode(data: bytes) -> tuple[int, int, int, bytes, list[int]]:
    """Independent TGA header/RLE decoder; return top-first RGB-order bytes."""
    identifier, cmap, kind, _, _, _, _, _, width, height, bits, descriptor = struct.unpack(
        "<BBBHHBHHHHBB", data[:18]
    )
    assert identifier == cmap == 0
    assert kind in (10, 11)
    channels = bits // 8
    assert kind == (11 if channels <= 2 else 10)
    assert descriptor == (8 if channels in (2, 4) else 0)
    cursor = 18
    pixels: list[bytes] = []
    packets: list[int] = []
    while len(pixels) < width * height:
        packet = data[cursor]
        packets.append(packet)
        cursor += 1
        count = (packet & 127) + 1
        if packet & 128:
            pixels.extend([data[cursor : cursor + channels]] * count)
            cursor += channels
        else:
            pixels.extend(
                data[cursor + i * channels : cursor + (i + 1) * channels] for i in range(count)
            )
            cursor += count * channels
    assert len(pixels) == width * height
    assert cursor == len(data)
    rows = []
    for y in reversed(range(height)):
        for pixel in pixels[y * width : (y + 1) * width]:
            assert len(pixel) == channels
            rows.append(pixel[2::-1] + pixel[3:] if channels >= 3 else pixel)
    return width, height, channels, b"".join(rows), packets


@pytest.mark.parametrize("channels", [1, 2, 3, 4])
def test_channels_orientation_alpha_and_rle(
    export_tests: Path, tmp_path: Path, channels: int
) -> None:
    width, height = 261, 3
    samples = bytearray()
    for y in range(height):
        for x in range(width):
            # Long repeated packets, then raw packets, distinct rows and alpha extremes.
            value = 33 + y if x < 132 else x + y * 37
            samples.extend((value + c * 71) % 256 for c in range(channels))
    result, target = encode(export_tests, tmp_path, width, height, channels, bytes(samples))
    assert result.returncode == 0, result.stderr
    w, h, c, decoded, packets = decode(target.read_bytes())
    assert (w, h, c, decoded) == (width, height, channels, bytes(samples))
    assert 255 in packets  # Full 128-pixel RLE packet.
    assert any(packet < 128 for packet in packets)
    with Image.open(target) as image:
        assert image.mode == {1: "L", 2: "LA", 3: "RGB", 4: "RGBA"}[channels]
        assert image.size == (width, height)
        assert image.tobytes() == samples


@pytest.mark.parametrize("channels", [2, 4])
@pytest.mark.parametrize("alpha", [0, 255])
def test_uniform_alpha_is_preserved(
    export_tests: Path, tmp_path: Path, channels: int, alpha: int
) -> None:
    samples = bytes([19] * (channels - 1) + [alpha])
    result, target = encode(export_tests, tmp_path, 1, 1, channels, samples)
    assert result.returncode == 0, result.stderr
    assert decode(target.read_bytes())[:4] == (1, 1, channels, samples)


@pytest.mark.parametrize("width,height", [(65535, 1), (1, 65535)])
def test_maximum_tga_dimension(export_tests: Path, tmp_path: Path, width: int, height: int) -> None:
    samples = bytes(range(256)) * 255 + bytes(range(255))
    result, target = encode(export_tests, tmp_path, width, height, 1, samples)
    assert result.returncode == 0, result.stderr
    assert decode(target.read_bytes())[:4] == (width, height, 1, samples)


@pytest.mark.parametrize(
    "width,height,channels,samples",
    [
        (0, 1, 1, b""),
        (1, 0, 1, b""),
        (65536, 1, 1, b""),
        (1, 65536, 1, b""),
        (1, 1, 0, b""),
        (1, 1, 5, b"12345"),
        (1, 1, 4, b"123"),
        (1, 1, 4, b"12345"),
        (65535, 65535, 4, b""),
    ],
)
def test_invalid_input_refused_without_file(
    export_tests: Path, tmp_path: Path, width: int, height: int, channels: int, samples: bytes
) -> None:
    result, target = encode(export_tests, tmp_path, width, height, channels, samples)
    assert result.returncode == 2
    assert "TGA8:" in result.stderr
    assert not target.exists()
