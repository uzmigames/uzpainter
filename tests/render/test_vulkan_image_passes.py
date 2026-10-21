"""Tests of phase3.1_vulkan-compute-parity items 2.5 and 3.2: the UV raster, jump-flood dilation,
resampling and mip generation (`src/render/uv_raster.*`, `dilation.*`, `resample.*`, `mips.*`,
the same HLSL sources in `src/render/shaders/`) on the qualified Vulkan device, in the
fixed-slot model of decision 313, byte-equal to DX12 on the synthetic plane, sphere and bevelled
cube.

Both cases run `uzp-render-tests.exe` with a DX12 engine and an engine over the qualified Vulkan
device (the native-test seam `EngineOptions::createDevice`; product paths still refuse Vulkan,
decision 310): `vulkan-uv-raster` (`tests/render/uv_raster_test.cpp`) and `vulkan-image-passes`
(`tests/render/image_passes_test.cpp`). They skip under `UZP_NO_GPU=1` (decision 028) and when
the machine has no DX12 adapter or no Vulkan device (exit code 77). None of them is parity
evidence for a Painter-visible output.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.render.test_core_device_kernels import run_case

FIXTURES = ("plane", "sphere", "bevelled cube")
BUFFERS = (
    "position",
    "normal",
    "tangent",
    "bitangent",
    "island_id",
    "material_id",
    "triangle",
    "conservative",
)
DILATION_FORMATS = (
    "RGBA8Unorm",
    "RGBA16Unorm",
    "RGBA16Float",
    "R32Float",
    "RGBA32Float",
    "RG16Float",
)
RESAMPLES = (
    "RGBA8Unorm sRGB Nearest clamp",
    "RGBA8Unorm sRGB Bilinear clamp",
    "RGBA8Unorm sRGB Box clamp",
    "RGBA8Unorm normal Box clamp",
    "RGBA16Unorm linear Nearest clamp",
    "RGBA16Unorm linear Bilinear clamp",
    "RGBA16Unorm linear Bilinear repeat",
    "RGBA16Unorm linear Box clamp",
    "RGBA16Float normal Bilinear clamp",
    "RGBA16Float normal Box clamp",
    "R32Float linear Bilinear repeat",
    "R32Float linear Box clamp",
    "RGBA32Float linear Box clamp",
    "RG16Float linear Bilinear clamp",
)
MIPS = (
    "RGBA8Unorm sRGB 512x512",
    "RGBA8Unorm sRGB alpha coverage 512x512",
    "RGBA8Unorm sRGB alpha coverage 300x200",
    "RGBA16Unorm linear alpha coverage 512x512",
    "RGBA8Unorm normal 512x512",
    "RGBA16Float normal 512x512",
    "R16Float linear 512x512",
    "R32Float linear 300x200",
)


def _passed(exe: Path, case: str, work: Path) -> set[str]:
    if os.environ.get("UZP_NO_GPU") == "1":
        pytest.skip(f"UZP_NO_GPU=1: `{case}` needs a DX12 adapter and a Vulkan device (028)")
    passed, _ = run_case(exe, case, work)
    return passed


def test_uv_raster_vulkan_equals_dx12(render_tests: Path, tmp_path: Path) -> None:
    """2.5, 3.2: the plane, sphere and bevelled cube rasterised at 512 x 512 and 300 x 200 give
    the same bytes on Vulkan as on DX12 in all eight buffers (one dispatch per buffer on Vulkan),
    and the Vulkan coverage equals the double-precision reference."""
    passed = _passed(render_tests, "vulkan-uv-raster", tmp_path)
    assert "the Vulkan engine runs on the qualified device" in passed
    for fixture in FIXTURES:
        for size in ("512x512", "300x200"):
            label = f"{fixture} {size}"
            assert f"{label}: rasterises on DX12 and on Vulkan" in passed
            for buffer in BUFFERS:
                assert f"{label}: {buffer} on Vulkan equals DX12 byte for byte" in passed
            assert f"{label} (Vulkan): texel-centre coverage equals the reference" in passed


def test_image_passes_vulkan_equal_dx12(render_tests: Path, tmp_path: Path) -> None:
    """2.5, 3.2: dilation (six formats, distance 8 and unlimited), resampling (every filter and
    colour mode, down to 143 x 105 and up to 451 x 299) and mip chains (sRGB, linear, normal,
    alpha coverage; a 512 x 512 coverage chain spans two Vulkan submissions) on each fixture's
    raster: Vulkan equals DX12 byte for byte, and DX12 equals the CPU reference."""
    passed = _passed(render_tests, "vulkan-image-passes", tmp_path)
    assert "the Vulkan engine runs on the qualified device" in passed
    expected: list[str] = []
    for fixture in FIXTURES:
        for name in DILATION_FORMATS:
            for distance in ("8", "unlimited"):
                expected.append(f"{fixture}: dilation {name} distance {distance}")
        for resample in RESAMPLES:
            for size in ("143x105", "451x299"):
                expected.append(f"{fixture}: resample {resample} {size}")
    for label in expected:
        assert f"{label}: Vulkan equals DX12 byte for byte" in passed, label
        assert f"{label}: equals the CPU reference" in passed, label
    for fixture in FIXTURES:
        for mip in MIPS:
            label = f"{fixture}: mips {mip}"
            assert f"{label}: every level on Vulkan equals DX12 byte for byte" in passed, label
            assert f"{label}: every level equals the CPU reference" in passed, label
