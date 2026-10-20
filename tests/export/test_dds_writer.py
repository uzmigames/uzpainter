"""Independent DDS structure, real Pillow decoding and cook-boundary checks; CPU only."""

from __future__ import annotations

import io
import json
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BC5, BC7, BC7_SRGB = 5, 6, 7
LINEAR, COLOUR, NORMAL, MASKED_COLOUR = 0, 1, 2, 3


@pytest.fixture(scope="session")
def dds_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    zig = shutil.which("zig")
    assert zig is not None, "zig is required for DDS writer acceptance"
    prefix = tmp_path_factory.mktemp("dds-tests")
    result = subprocess.run(
        [zig, "build", "uzp-dds-tests", "--prefix", str(prefix)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return prefix / "bin" / "uzp-dds-tests.exe"


def invoke(exe: Path, tmp: Path, request: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    path = tmp / "dds-request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    run = subprocess.run(
        [str(exe), str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert run.returncode in (0, 1), (run.stdout, run.stderr)
    return run.returncode, json.loads(run.stdout)


def raw_request(width: int, height: int, sizes: list[int], fmt: int = BC7) -> dict[str, Any]:
    return {"operation": "raw", "format": fmt, "width": width, "height": height, "sizes": sizes}


def cook_request(
    width: int = 4,
    height: int = 4,
    *,
    fmt: int = BC7,
    map_class: int = LINEAR,
    pixel: tuple[int, int, int, int] = (12000, 34000, 56000, 65535),
) -> dict[str, Any]:
    return {
        "operation": "cook",
        "format": fmt,
        "width": width,
        "height": height,
        "mapClass": map_class,
        "rgba": list(pixel) * (width * height),
        "threads": 1,
    }


def check_header(result: dict[str, Any], width: int, height: int, fmt: int, count: int) -> bytes:
    data = bytes(result["bytes"])
    assert data[:4] == b"DDS " and len(data) >= 148
    h = struct.unpack_from("<31I", data, 4)
    assert h[0] == 124 and h[2:4] == (height, width)
    assert h[1] == 0x81007 | (0x20000 if count > 1 else 0)
    assert h[4] == ((width + 3) // 4) * ((height + 3) // 4) * 16
    assert h[5] == 0 and h[6] == count and h[7:18] == (0,) * 11
    assert h[18:22] == (32, 4, int.from_bytes(b"DX10", "little"), 0)
    assert h[22:26] == (0,) * 4
    assert h[26] == 0x1000 | (0x400008 if count > 1 else 0)
    assert h[27:31] == (0,) * 4
    assert struct.unpack_from("<5I", data, 128) == (
        {BC5: 83, BC7: 98, BC7_SRGB: 99}[fmt],
        3,
        0,
        1,
        0,
    )
    assert (result["width"], result["height"], result["format"], result["srgb"]) == (
        width,
        height,
        fmt,
        fmt == BC7_SRGB,
    )
    offset = 148
    for level, mip in enumerate(result["mips"]):
        w, hgt = max(1, width >> level), max(1, height >> level)
        size = ((w + 3) // 4) * ((hgt + 3) // 4) * 16
        assert mip == {"offset": offset, "size": size, "width": w, "height": hgt}
        offset += size
    assert len(result["mips"]) == count and len(data) == offset
    return data


@pytest.mark.parametrize("fmt", [BC5, BC7, BC7_SRGB])
@pytest.mark.parametrize(
    "width,height,count", [(1, 1, 1), (7, 5, 1), (7, 5, 2), (7, 5, 3), (1, 8, 4)]
)
def test_raw_header_and_contiguous_payload(
    dds_tests: Path,
    tmp_path: Path,
    fmt: int,
    width: int,
    height: int,
    count: int,
) -> None:
    sizes = [
        ((max(1, width >> n) + 3) // 4) * ((max(1, height >> n) + 3) // 4) * 16
        for n in range(count)
    ]
    code, result = invoke(dds_tests, tmp_path, raw_request(width, height, sizes, fmt))
    assert code == 0, result
    data = check_header(result, width, height, fmt, count)
    assert data[148:] == b"".join(bytes([17 + i]) * size for i, size in enumerate(sizes))


@pytest.mark.parametrize(
    "invalid_input",
    [
        raw_request(0, 4, [16]),
        raw_request(4, 0, [16]),
        raw_request(4, 4, []),
        raw_request(4, 4, [15]),
        raw_request(4, 4, [17]),
        raw_request(8, 8, [64, 15]),
        raw_request(1, 1, [16, 16]),
        raw_request(4, 4, [16] * 4),
        raw_request(0xFFFFFFFF, 0xFFFFFFFF, [16]),
        raw_request(0xFFFFFFFF, 1, [16]),
        *[raw_request(4, 4, [16], fmt) for fmt in [0, 1, 2, 3, 4, 255]],
    ],
)
def test_writer_refuses_invalid_inputs(
    dds_tests: Path, tmp_path: Path, invalid_input: dict[str, Any]
) -> None:
    code, result = invoke(dds_tests, tmp_path, invalid_input)
    assert code == 1 and result["error"]


def decode_mip(data: bytes, mip: dict[str, int]) -> Image.Image:
    # Repackage this level as a one-level DDS for a real independent loader.
    header = bytearray(data[:148])
    struct.pack_into("<5I", header, 8, 0x81007, mip["height"], mip["width"], mip["size"], 0)
    struct.pack_into("<I", header, 28, 1)
    struct.pack_into("<I", header, 108, 0x1000)
    payload = data[mip["offset"] : mip["offset"] + mip["size"]]
    image = Image.open(io.BytesIO(header + payload))
    image.load()
    return image


@pytest.mark.parametrize("fmt,map_class", [(BC5, LINEAR), (BC7, LINEAR), (BC7_SRGB, COLOUR)])
def test_real_decoder_all_mips_and_threads(
    dds_tests: Path,
    tmp_path: Path,
    fmt: int,
    map_class: int,
) -> None:
    pixel = (0, 65535, 0, 65535)
    request = cook_request(8, 4, fmt=fmt, map_class=map_class, pixel=pixel)
    code, result = invoke(dds_tests, tmp_path, request)
    assert code == 0, result
    data = check_header(result, 8, 4, fmt, 4)
    for call in result["calls"]:
        assert call["rgba"] == [0, 255, 0, 255] * (call["width"] * call["blockRows"] * 4)
    for mip in result["mips"]:
        decoded = decode_mip(data, mip)
        assert decoded.size == (mip["width"], mip["height"])
        assert decoded.mode == ("RGB" if fmt == BC5 else "RGBA")
        # Pinned bc7enc selects mode 6 with shared-per-endpoint pbits=0: both
        # endpoints are (0,254,0,254). This lossy result is distinct from cook's exact input.
        expected = (0, 255) if fmt == BC5 else (0, 254, 0, 254)
        for y in range(decoded.height):
            for x in range(decoded.width):
                p = decoded.getpixel((x, y))
                assert isinstance(p, tuple) and p[: len(expected)] == expected
        assert ("gamma" in decoded.info) == (fmt == BC7_SRGB)
    for threads in (4, 0):
        request["threads"] = threads
        code, threaded = invoke(dds_tests, tmp_path, request)
        assert code == 0 and threaded["bytes"] == result["bytes"]


def test_quantization_and_linear_mips_at_encoder_boundary(dds_tests: Path, tmp_path: Path) -> None:
    request = cook_request(2, 2)
    pixels = [
        (128, 129, 65535, 0),
        (385, 386, 257, 65535),
        (642, 643, 514, 32768),
        (899, 900, 771, 32767),
    ]
    request["rgba"] = [c for p in pixels for c in p]
    code, result = invoke(dds_tests, tmp_path, request)
    assert code == 0, result
    calls = result["calls"]
    assert len(calls) == 2

    def quantize(c: int) -> int:
        return (c + 128) // 257

    actual = calls[0]["rgba"]
    for y in range(4):
        for x in range(4):
            expected = [quantize(c) for c in pixels[min(y, 1) * 2 + min(x, 1)]]
            assert actual[4 * (y * 4 + x) : 4 * (y * 4 + x + 1)] == expected
    average = [(sum(p[c] for p in pixels) + 2) // 4 for c in range(4)]
    assert calls[1]["rgba"] == [quantize(c) for c in average] * 16


@pytest.mark.parametrize("fmt,map_class", [(BC5, LINEAR), (BC7, LINEAR), (BC7_SRGB, COLOUR)])
def test_decoder_channel_alpha_and_block_orientation(
    dds_tests: Path, tmp_path: Path, fmt: int, map_class: int
) -> None:
    quadrants = [
        (0, 0, 65535, 0),
        (65535, 0, 0, 65535),
        (0, 65535, 0, 65535),
        (65535, 65535, 65535, 0),
    ]
    request = cook_request(8, 8, fmt=fmt, map_class=map_class)
    request["rgba"] = [
        c for y in range(8) for x in range(8) for c in quadrants[(y // 4) * 2 + x // 4]
    ]
    code, result = invoke(dds_tests, tmp_path, request)
    assert code == 0, result
    decoded = decode_mip(check_header(result, 8, 8, fmt, 4), result["mips"][0])
    # Exact independently decoded output of the pinned encoder, including its mode-6
    # endpoint quantization on the opaque red/green blocks. No general error allowance.
    bc7_expected = [(0, 0, 255, 0), (254, 0, 0, 254), (0, 254, 0, 254), (255, 255, 255, 0)]
    for y in range(8):
        for x in range(8):
            expected = tuple(c // 257 for c in quadrants[(y // 4) * 2 + x // 4])
            if fmt != BC5:
                expected = bc7_expected[(y // 4) * 2 + x // 4]
            actual = decoded.getpixel((x, y))
            count = 2 if fmt == BC5 else 4
            assert isinstance(actual, tuple) and actual[:count] == expected[:count]


@pytest.mark.parametrize("map_class", [COLOUR, MASKED_COLOUR])
def test_srgb_mips_filter_in_linear_light(dds_tests: Path, tmp_path: Path, map_class: int) -> None:
    request = cook_request(2, 2, fmt=BC7_SRGB, map_class=map_class)
    request["rgba"] = [0, 0, 0, 65535, 65535, 65535, 65535, 65535] * 2
    code, result = invoke(dds_tests, tmp_path, request)
    assert code == 0, result
    # Half linear intensity maps to about sRGB 0.735, not encoded-code average 0.5.
    assert result["calls"][1]["rgba"] == [188, 188, 188, 255] * 16


def test_normal_dx_green_preserved_and_mips_renormalized(dds_tests: Path, tmp_path: Path) -> None:
    request = cook_request(2, 2, fmt=BC5, map_class=NORMAL)
    request["rgba"] = [52428, 19661, 56732, 65535] * 4
    code, result = invoke(dds_tests, tmp_path, request)
    assert code == 0, result
    for call in result["calls"]:
        r, g, b, a = call["rgba"][:4]
        assert r > 128 and g < 128 and b > 128 and a == 255
        assert abs(sum((v / 255 * 2 - 1) ** 2 for v in (r, g, b)) - 1) < 0.02
    data = check_header(result, 2, 2, BC5, 2)
    decoded = decode_mip(data, result["mips"][0])
    pixel = decoded.getpixel((0, 0))
    assert isinstance(pixel, tuple) and pixel[1] < 128


@pytest.mark.parametrize(
    "fmt,map_class",
    [
        (BC7_SRGB, NORMAL),
        (BC7_SRGB, LINEAR),
        (BC5, COLOUR),
        (BC7, COLOUR),
        (BC7, MASKED_COLOUR),
        (BC7, 255),
        (255, LINEAR),
    ],
)
def test_cook_refuses_semantic_mismatch_before_encoder(
    dds_tests: Path,
    tmp_path: Path,
    fmt: int,
    map_class: int,
) -> None:
    request = cook_request(fmt=fmt, map_class=map_class)
    request["failEncoder"] = True
    code, result = invoke(dds_tests, tmp_path, request)
    assert code == 1 and result["error"] != "encoder reached", result


def test_negative_z_rejected_before_encoder(dds_tests: Path, tmp_path: Path) -> None:
    request = cook_request(fmt=BC5, map_class=NORMAL, pixel=(32768, 32768, 65535, 65535))
    request["rgba"][-2] = 32767
    request["failEncoder"] = True
    code, result = invoke(dds_tests, tmp_path, request)
    assert code == 1 and "negative" in result["error"].lower() and "z" in result["error"].lower(), (
        result
    )


def test_bc7_preserves_negative_z(dds_tests: Path, tmp_path: Path) -> None:
    request = cook_request(fmt=BC7, map_class=NORMAL, pixel=(32768, 32768, 0, 65535))
    code, result = invoke(dds_tests, tmp_path, request)
    assert code == 0, result
    data = check_header(result, 4, 4, BC7, 3)
    for mip in result["mips"]:
        decoded = decode_mip(data, mip)
        pixel = decoded.getpixel((0, 0))
        assert isinstance(pixel, tuple) and pixel[2] < 128


@pytest.mark.parametrize(
    "mutation", ["npot", "empty", "short", "long", "threshold_negative", "threshold_one"]
)
def test_cook_invalid_inputs_before_encoder(dds_tests: Path, tmp_path: Path, mutation: str) -> None:
    request = cook_request(fmt=BC7_SRGB, map_class=MASKED_COLOUR)
    if mutation == "npot":
        request["width"] = 3
        request["rgba"] = request["rgba"][: 3 * 4 * 4]
    elif mutation == "empty":
        request["width"] = 0
        request["rgba"] = []
    elif mutation == "short":
        request["rgba"].pop()
    elif mutation == "long":
        request["rgba"].append(0)
    else:
        request["alphaThreshold"] = -0.1 if mutation == "threshold_negative" else 1.0
    request["failEncoder"] = True
    code, result = invoke(dds_tests, tmp_path, request)
    assert code == 1 and result["error"] != "encoder reached", result
