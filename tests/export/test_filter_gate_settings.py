"""Native settings gate on authored records; no Painter or private oracle reads."""

from __future__ import annotations

import json
import struct
import subprocess
import zlib
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from tests.parity.test_filter_context_settings_validation import authored as authored


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(
    width: int, height: int, *, depth: int = 8, color: int = 6, interlaced: bool = False
) -> bytes:
    # Stream authored zero rows, including empty Adam7 passes, without a full source raster.
    compressor = zlib.compressobj()
    bits = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color] * depth
    passes = (
        (
            (0, 0, 8, 8),
            (4, 0, 8, 8),
            (0, 4, 4, 8),
            (2, 0, 4, 4),
            (0, 2, 2, 4),
            (1, 0, 2, 2),
            (0, 1, 1, 2),
        )
        if interlaced
        else ((0, 0, 1, 1),)
    )
    parts: list[bytes] = []
    for x, y, dx, dy in passes:
        if width <= x or height <= y:
            continue
        columns, rows = (width - x + dx - 1) // dx, (height - y + dy - 1) // dy
        row = bytes(1 + (columns * bits + 7) // 8)
        parts.extend(compressor.compress(row) for _ in range(rows))
    parts.append(compressor.flush())
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, int(interlaced))
        )
        + (chunk(b"PLTE", b"\0\0\0\xff\xff\xff") if color == 3 else b"")
        + chunk(b"IDAT", b"".join(parts))
        + chunk(b"IEND", b"")
    )


def pillow_accepts(data: bytes) -> bool:
    try:
        Image.open(BytesIO(data)).verify()
        Image.open(BytesIO(data)).load()
    except (OSError, ValueError, SyntaxError):
        return False
    return True


def test_native_filter_settings(
    export_tests: Path,
    tmp_path: Path,
    authored: tuple[dict[str, Any], dict[str, Any]],  # noqa: F811
) -> None:
    _, record = authored
    (tmp_path / "settings-record.json").write_text(json.dumps(record), encoding="utf-8")
    valid = png(2, 3)
    iend = valid[-12:]
    idat_size = struct.unpack(">I", valid[33:37])[0]
    idat_data = valid[41 : 41 + idat_size]
    ancillary = chunk(b"vpAg", b"authored ancillary")
    bad_crc = ancillary[:-1] + bytes([ancillary[-1] ^ 1])
    images = {
        "valid": valid,
        "truncated": valid[:-4],
        "ancillary-crc": valid[:-12] + bad_crc + iend,
        "trailing": valid + b"trailing",
        "missing-adler": valid[:33] + chunk(b"IDAT", idat_data[:-4]) + iend,
        "idat-trailing": valid[:33] + chunk(b"IDAT", idat_data + b"abc") + iend,
        "extra-scanline": valid[:33] + chunk(b"IDAT", zlib.compress(bytes(36))) + iend,
        "empty-idat": valid[:33] + chunk(b"IDAT", b"") + valid[33:],
        "split-idat": valid[:33] + b"".join(chunk(b"IDAT", bytes([b])) for b in idat_data) + iend,
        "invalid-filter": valid[:33] + chunk(b"IDAT", zlib.compress(b"\5" + bytes(26))) + iend,
        "missing-scanline": valid[:33] + chunk(b"IDAT", zlib.compress(bytes(18))) + iend,
        "over-width": png(8193, 1),
        "over-height": png(1, 8193),
        "width-edge": png(8192, 1),
        "height-edge": png(1, 8192),
        "decoded-edge": png(8192, 8192),
        "adam7-one": png(1, 1, interlaced=True),
        "adam7-small": png(2, 3, interlaced=True),
        "adam7-palette": png(9, 9, color=3, depth=1, interlaced=True),
        "adam7-gray": png(9, 9, color=0, depth=1, interlaced=True),
        "gray-four": png(3, 5, color=0, depth=4),
        "rgba-sixteen": png(3, 5, depth=16),
        "rgb-eight": png(3, 5, color=2),
        "gray-alpha": png(3, 5, color=4, depth=16),
        "adam7-sixteen": png(9, 9, depth=16, interlaced=True),
    }
    for name in (
        "ancillary-crc",
        "missing-adler",
        "invalid-filter",
    ):
        assert not pillow_accepts(images[name]), name
    for name in (
        "valid",
        "truncated",
        "missing-scanline",
        "trailing",
        "over-width",
        "over-height",
        "idat-trailing",
        "extra-scanline",
    ):
        assert pillow_accepts(images[name]), name
    for name in (
        "adam7-one",
        "adam7-small",
        "adam7-palette",
        "adam7-gray",
        "gray-four",
        "rgba-sixteen",
        "rgb-eight",
        "gray-alpha",
        "adam7-sixteen",
        "split-idat",
    ):
        assert pillow_accepts(images[name]), name
    for name, data in images.items():
        (tmp_path / f"settings-{name}.png").write_bytes(data)
    # Limit fixtures are written one at a time to keep peak memory bounded.
    limit = 64 * 1024 * 1024
    for name, lengths in (
        ("chunk-edge", (limit,)),
        ("chunk-limit", (limit + 1,)),
        ("ancillary-limit", (limit // 2, limit // 2 + 1)),
    ):
        with (tmp_path / f"settings-{name}.png").open("wb") as output:
            output.write(valid[:-12])
            for length in lengths:
                output.write(chunk(b"vpAg", bytes(length)))
            output.write(iend)
    proc = subprocess.run(
        [str(export_tests), "filter-gate-settings", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.startswith("FILTER_GATE_SETTINGS: ")]
    assert len(lines) == 1, proc.stdout
    assert json.loads(lines[0].split(": ", 1)[1]) == {"checks": 60}
