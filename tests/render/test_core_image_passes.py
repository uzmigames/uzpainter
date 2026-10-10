"""Tests of phase1.3_core-image-passes: jump-flood dilation, resampling and mip generation
(`src/render/dilation.*`, `resample.*`, `mips.*`, `image_pass.*`, `src/render/shaders/`;
`docs/architecture/13-engine-integration.md` §4.1), each equal to its CPU reference
(`tests/render/reference/`) bit for bit.

Every case runs `uzp-render-tests.exe` (`tests/render/image_passes_test.cpp`). `image-reference`
runs anywhere; the cases that run the passes on a DX12 device skip under `UZP_NO_GPU=1` (hosted
CI, decision 028) or when no adapter is present, and run on the owner's hardware adapter
otherwise.
"""

from __future__ import annotations

from pathlib import Path

from tests.render.test_core_device_kernels import run_case

FORMATS_DILATED = ("RGBA8Unorm", "RGBA16Unorm", "RGBA16Float", "R32Float")


def test_references_match_published_fits(render_tests: Path) -> None:
    """2.4: the CPU references: the write rule is the BilinearHQ storage formula of
    `parity/semantics/resampling.json` (truncate to n + 4 fractional bits, nearest, ties down),
    sRGB encode inverts decode, the jump-flood schedule, and jump flooding equals the exact
    nearest covered texel on the island masks."""
    passed, output = run_case(render_tests, "image-reference")
    assert {
        "the write rule equals the resampling.json BilinearHQ storage formula for every 16-bit "
        "weighted sum",
        "the write rule rounds a value halfway between codes down",
        "the float-to-UNORM write rule maps every code's value back to the code",
        "sRGB encode inverts decode for every 8-bit code; decode is increasing",
        "jump-flood steps for an 8-texel limit are 1, 8, 4, 2, 1",
        "a zero limit or a single texel needs no step",
        "mip extents are max(1, extent >> level)",
        "the alpha cutoff code is ceil(cutoff M), at least 1",
        "jump flooding equals the nearest covered texel on the two islands (limit 8)",
        "jump flooding equals the nearest covered texel on the two islands (limit unlimited)",
    } <= passed
    assert "INFO jump flooding vs exact nearest" in output


def test_dilation_two_islands(render_tests: Path, tmp_path: Path) -> None:
    """3.1, 2.1: two islands dilated by 8 texels equal the CPU nearest-covered-texel reference
    (ties to the smaller linear index) exactly; covered texels and texels beyond the limit stay
    unchanged; random masks equal the CPU jump-flood reference."""
    passed, _ = run_case(render_tests, "image-dilation", tmp_path)
    for name in FORMATS_DILATED:
        assert {
            f"{name}: two islands, distance 8, equal the CPU jump-flood reference",
            f"{name}: two islands, distance 8, equal the nearest covered texel",
            f"{name}: covered texels and texels beyond 8 texels stay unchanged",
        } <= passed
    assert {
        "dilation on synthetic islands equals the CPU nearest-covered-texel reference",
        "unlimited dilation fills every texel with its nearest island's colour",
        "dilation of random masks equals the CPU jump-flood reference exactly",
        "distance 0 copies the colour unchanged",
        "a coverage mask of another size is rejected with request_failed",
    } <= passed


def test_resampling(render_tests: Path, tmp_path: Path) -> None:
    """3.2, 2.2: identity size is bit-exact; up- and down-sampling with the Nearest, Bilinear
    (Painter's fixed-point bilinear, clamp and repeat) and Box filters equal the CPU reference in
    the linear, sRGB and normal colour modes."""
    passed, _ = run_case(render_tests, "image-resample", tmp_path)
    assert {
        "resampling at identity size is bit-exact for every format and filter",
        "up- and down-sampling equal the CPU reference for every format, filter and colour mode",
        "RGBA16Unorm linear Bilinear clamp: up- and down-sampling equal the CPU reference",
        "RGBA16Unorm linear Bilinear repeat: up- and down-sampling equal the CPU reference",
        "RGBA8Unorm sRGB Box clamp: up- and down-sampling equal the CPU reference",
        "RGBA16Float normal Box clamp: up- and down-sampling equal the CPU reference",
        "sRGB filtering of a float format is rejected with request_failed",
    } <= passed


def test_mip_generation(render_tests: Path, tmp_path: Path) -> None:
    """3.3, 2.3: sRGB-aware chains equal the CPU decode-filter-encode reference; normal chains
    are renormalised and unit length at storage precision; alpha coverage at the test cutoff is
    preserved on every level."""
    passed, _ = run_case(render_tests, "image-mips", tmp_path)
    assert {
        "sRGB8 64x40: every level of the 7-level chain equals the CPU decode-filter-encode "
        "reference",
        "sRGB8 45x27: every level of the 6-level chain equals the CPU decode-filter-encode "
        "reference",
        "RGBA16Unorm 45x27: the linear chain equals the CPU reference",
        "R16Float 45x27: the linear chain equals the CPU reference",
        "alpha coverage (linear): the chain equals the CPU coverage-preserving reference",
        "alpha coverage (sRGB): the chain equals the CPU coverage-preserving reference",
        "alpha coverage at the test cutoff is preserved on every level",
    } <= passed
    for name in ("RGBA16Unorm", "RGBA8Unorm", "RGBA16Float"):
        assert f"{name}: the normal chain equals the CPU renormalising reference" in passed
        assert f"{name}: normal mips are unit length at storage precision" in passed


def test_passes_repeat_byte_identical(render_tests: Path, tmp_path: Path) -> None:
    """3.4: dilation, resampling and mip generation run twice on the same input give
    byte-identical output."""
    passed, _ = run_case(render_tests, "image-repeat", tmp_path)
    assert "every image pass produces byte-identical output across two runs" in passed
