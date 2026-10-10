"""Tests of phase1.2_core-readback: `TextureReadback` (`src/render/texture_readback.*`,
`docs/architecture/13-engine-integration.md` §2.3, §4.1) and the 16-bit unorm formats it reads
(UZP-MOD-009).

Every case runs `uzp-render-tests.exe` (`tests/render/render_core_test.cpp`). `readback-layout`
runs anywhere; the cases that read textures back from a DX12 device skip under `UZP_NO_GPU=1`
(hosted CI, decision 028) or when no adapter is present, and run on the owner's hardware adapter
otherwise.
"""

from __future__ import annotations

from pathlib import Path

from tests.render.test_core_device_kernels import run_case


def test_readback_layout_and_pitch_rule(render_tests: Path) -> None:
    """2.1, 2.4: the 256-byte row pitch and the texel layout of every readable format; the RHI
    sizes and maps the 16-bit unorm formats (UZP-MOD-009)."""
    passed, _ = run_case(render_tests, "readback-layout")
    assert {
        "row pitch is the row size rounded up to 256 bytes",
        "every readable format's layout matches the RHI's bytes per texel",
        "16-bit unorm formats read back as 2-byte channels",
        "UZP-MOD-009: the RHI sizes the 16-bit unorm formats",
        "UZP-MOD-009: the 16-bit unorm formats map to their DXGI formats",
        "block-compressed, depth and unknown formats are not read back",
    } <= passed


def test_drain_releases_every_request(render_tests: Path, tmp_path: Path) -> None:
    """3.1, 2.3: 64 concurrent readback requests drain in submission order with exact texels and
    no staging buffer remains allocated afterwards (also after a destructor drain and after
    bursts submitted from four threads)."""
    passed, _ = run_case(render_tests, "readback-drain", tmp_path)
    assert {
        "64 readback requests are outstanding, each with its own staging buffer",
        "the device holds one staging allocation per outstanding request",
        "the drain reports every request in submission order",
        "every drained request returns its texture's texels",
        "after the drain no staging buffer remains allocated on the device",
        "destroying a TextureReadback drains it and releases its staging buffers",
        "rejected requests allocate nothing",
        "readback bursts submitted from four threads all drain exactly",
        "after every request the device holds no more allocations than before the first",
    } <= passed


def test_unaligned_widths_keep_rows(render_tests: Path, tmp_path: Path) -> None:
    """3.2: widths of 1, 3, 1023 and 4097 texels, whose rows are not multiples of 256 bytes,
    read back with correct rows; the pitch equals D3D12's copy footprint."""
    passed, _ = run_case(render_tests, "readback-pitch", tmp_path)
    assert "the readback pitch equals D3D12's copy footprint for every width" in passed
    assert (
        "widths 1, 3, 1023 and 4097 read back with correct rows for every tested format" in passed
    )
    for label in ("L16 (R16Unorm)", "RGB16 (RGBA16Unorm, 3 channels)", "L32F (R32Float)"):
        for width in (1, 3, 1023, 4097):
            assert f"{label}, width {width}: every row reads back unshifted" in passed


def test_exact_native_formats(render_tests: Path, tmp_path: Path) -> None:
    """3.3, 2.4, UZP-MOD-009: values uploaded to every readable format (8-bit and 16-bit unorm,
    16- and 32-bit float, 32-bit uint; one to four channels) read back bit-identical, the RGB16
    scenario of the spec included."""
    passed, _ = run_case(render_tests, "readback-exact", tmp_path)
    assert "every supported format reads back bit-identical" in passed
    for name in ("R16Unorm", "RG16Unorm", "RGBA16Unorm", "R16Float", "RGBA32Float", "R8Unorm"):
        assert f"{name} reads back bit-identical" in passed
    assert "an RGB16 texture 1023 texels wide reads back every texel unchanged" in passed
    assert "mip level 2 (16x10) reads back bit-identical" in passed


def test_failure_never_returns_stale_data(render_tests: Path, tmp_path: Path) -> None:
    """3.4, 2.2: pending readbacks under an injected device removal fail with
    `device_removed {backend: dx12, reason}` and return no texels; a readback behind a stalled
    queue fails with `timeout` and its staging buffer is released only after its copy."""
    passed, output = run_case(render_tests, "readback-failure", tmp_path)
    assert {
        "the pending readback fails with device_removed {backend: dx12, reason}",
        "no texels are returned, neither previous nor new",
        "the drain fails the other pending readback with device_removed",
        "a readback requested after the removal fails with device_removed",
        "the failed readbacks hold no staging buffer",
        "a readback behind a stalled queue fails with timeout and no texels",
        "its staging buffer is held while the GPU may still write it",
        "once the copy has completed the drain releases the held staging buffer",
    } <= passed
    assert "device_removed {backend: dx12, reason: DXGI_ERROR_DEVICE_REMOVED" in output
