"""Capture checks: measured storage format, current-output verification, PNG decoding,
silhouette (task items 2.3, 2.4)."""

from __future__ import annotations

import os
import struct
import types
from pathlib import Path

import pytest

from tools.parity.recorder.capture import (
    StaleCaptureError,
    check_silhouette,
    decode_png,
    measure_storage_format,
    verify_current_outputs,
    write_fence,
)
from tools.parity.recorder.session import RecorderError


def exr_bytes(pixel_types: list[int]) -> bytes:
    chlist = (
        b"".join(
            name.encode() + b"\0" + struct.pack("<iB3xii", t, 0, 1, 1)
            for name, t in zip("BGRA", pixel_types, strict=False)
        )
        + b"\0"
    )
    header = b"channels\0chlist\0" + struct.pack("<i", len(chlist)) + chlist + b"\0"
    return struct.pack("<ii", 20000630, 2) + header


def test_png_storage_format_is_measured(fake: types.ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "a.png"
    fake.write_png(path, 2, 1, [(1, 2, 3), (4, 5, 6)], bit_depth=16)
    measured = measure_storage_format(path)
    assert (measured.container, measured.sample_type, measured.bits_per_channel) == (
        "png",
        "uint",
        16,
    )
    assert measured.channels == 3 and measured.encoding is None
    fake.write_png(path, 1, 1, [(9,)], bit_depth=8, srgb_chunk=True)
    measured = measure_storage_format(path)
    assert (measured.bits_per_channel, measured.channels, measured.encoding) == (8, 1, "srgb")


@pytest.mark.parametrize(
    ("types_", "expected"), [([1, 1, 1], ("half", 16, 3)), ([2] * 4, ("float", 32, 4))]
)
def test_exr_storage_format_is_measured(
    tmp_path: Path, types_: list[int], expected: tuple[str, int, int]
) -> None:
    path = tmp_path / "a.exr"
    path.write_bytes(exr_bytes(types_))
    measured = measure_storage_format(path)
    assert (measured.sample_type, measured.bits_per_channel, measured.channels) == expected
    assert measured.encoding == "linear"


def test_mixed_exr_sample_types_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "a.exr"
    path.write_bytes(exr_bytes([1, 2, 1]))
    with pytest.raises(RecorderError, match="mixed"):
        measure_storage_format(path)


def test_unknown_container_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "a.tga"
    path.write_bytes(b"\0" * 32)
    with pytest.raises(RecorderError, match="not supported"):
        measure_storage_format(path)


@pytest.mark.parametrize("bit_depth", [8, 16])
@pytest.mark.parametrize("channels", [1, 2, 3, 4])
def test_png_decoding_undoes_every_filter(
    fake: types.ModuleType, tmp_path: Path, bit_depth: int, channels: int
) -> None:
    width, height = 3, 5
    top = (1 << bit_depth) - 1
    pixels = [
        tuple((x * 37 + y * 91 + c * 53) % (top + 1) for c in range(channels))
        for y in range(height)
        for x in range(width)
    ]
    path = tmp_path / "filtered.png"
    fake.write_png(path, width, height, pixels, bit_depth=bit_depth, filters=[0, 1, 2, 3, 4])
    image = decode_png(path)
    assert (image.width, image.height, image.channels) == (width, height, channels)
    assert image.pixels == pixels


def test_current_outputs_are_accepted(tmp_path: Path) -> None:
    out = tmp_path / "export"
    out.mkdir()
    fence = write_fence(tmp_path / "fence")
    file = out / "a.png"
    file.write_bytes(b"x")
    verify_current_outputs([file], out, fence)


def test_output_older_than_the_last_instruction_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "export"
    out.mkdir()
    file = out / "a.png"
    file.write_bytes(b"x")
    fence = write_fence(tmp_path / "fence")
    old = fence - 10_000_000_000
    os.utime(file, ns=(old, old))
    with pytest.raises(StaleCaptureError, match="before the last applied instruction"):
        verify_current_outputs([file], out, fence)


def test_unlisted_or_missing_outputs_are_refused(tmp_path: Path) -> None:
    out = tmp_path / "export"
    out.mkdir()
    fence = write_fence(tmp_path / "fence")
    (out / "stale.png").write_bytes(b"x")
    listed = out / "a.png"
    listed.write_bytes(b"x")
    with pytest.raises(StaleCaptureError, match="unlisted"):
        verify_current_outputs([listed], out, fence)
    with pytest.raises(StaleCaptureError, match="outside"):
        verify_current_outputs([tmp_path / "fence"], out, fence)


def silhouette_images(
    fake: types.ModuleType, tmp_path: Path, hole: bool = False, noisy_background: bool = False
) -> tuple[Path, Path]:
    """4x4 render with a 2x2 object in the middle; the mask marks a don't-care pixel."""
    mask_px, render_px = [], []
    for y in range(4):
        for x in range(4):
            inside = 1 <= x <= 2 and 1 <= y <= 2
            mask_px.append((255,) if inside else (128,) if (x, y) == (0, 0) else (0,))
            if inside:
                render_px.append((10, 10, 10) if hole and (x, y) == (1, 1) else (200, 150, 90))
            else:
                render_px.append(
                    (11, 10, 10) if noisy_background and (x, y) == (3, 3) else (10, 10, 10)
                )
    render, mask = tmp_path / "render.png", tmp_path / "mask.png"
    fake.write_png(render, 4, 4, render_px, bit_depth=8)
    fake.write_png(mask, 4, 4, mask_px, bit_depth=8)
    return render, mask


def test_matching_silhouette_is_accepted(fake: types.ModuleType, tmp_path: Path) -> None:
    result = check_silhouette(*silhouette_images(fake, tmp_path))
    assert (result.foreground_checked, result.background_checked, result.dont_care) == (4, 11, 1)
    assert result.background_value == (10, 10, 10)


@pytest.mark.parametrize(("hole", "noisy"), [(True, False), (False, True)])
def test_wrong_silhouette_is_refused(
    fake: types.ModuleType, tmp_path: Path, hole: bool, noisy: bool
) -> None:
    with pytest.raises(StaleCaptureError):
        check_silhouette(*silhouette_images(fake, tmp_path, hole=hole, noisy_background=noisy))
