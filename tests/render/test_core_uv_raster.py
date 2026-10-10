"""Tests of phase1.3_core-uv-raster: the UV-space raster pass (`src/render/uv_raster.*`,
`src/render/shaders/uv_raster.hlsl`, `docs/architecture/12-mesh-import.md` §5, §6) on synthetic
meshes.

Every case runs `uzp-render-tests.exe` (`tests/render/uv_raster_test.cpp`). `uv-raster-validate`
runs anywhere; the cases that rasterise on a DX12 device skip under `UZP_NO_GPU=1` (hosted CI,
decision 028) or when no adapter is present, and run on the owner's hardware adapter otherwise.
"""

from __future__ import annotations

from pathlib import Path

from tests.render.test_core_device_kernels import run_case

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


def test_corner_layout_validation(render_tests: Path, tmp_path: Path) -> None:
    """2.1: corner buffers carry explicit strides and offsets per attribute; strides below the
    attribute size (0 included), unaligned offsets, attributes past their buffer, unknown buffers,
    corner ids out of range and UV tiles other than 1001 are rejected."""
    passed, _ = run_case(render_tests, "uv-raster-validate", tmp_path)
    assert {
        "separate and interleaved layouts are accepted",
        "a stride smaller than the attribute is rejected",
        "a zero stride is rejected (no default stride)",
        "an unaligned offset is rejected",
        "an attribute past the end of its buffer is rejected",
        "an unknown buffer index is rejected",
        "a corner id out of range is rejected",
        "a size of 0 is rejected",
        "UV tiles other than 1001 are rejected in v1",
    } <= passed


def test_plane_matches_analytic_values(render_tests: Path, tmp_path: Path) -> None:
    """3.1, 2.1, 2.2, 2.4: a unit plane on the 0-1 square at 256 x 256 covers every texel at its
    centre with the analytic position and frame; interleaved (stride 64) and separate corner
    layouts give byte-identical buffers indexed by tile 1001."""
    passed, _ = run_case(render_tests, "uv-raster-plane", tmp_path)
    assert {
        "interleaved and separate corner layouts give byte-identical buffers",
        "the buffers are indexed by UV tile 1001",
        "position, normal and tangent frame are RGBA32F, ids R32Uint",
        "every texel of the 256 x 256 plane is covered at its centre",
        "the conservative mask covers the whole plane",
        "interpolated positions equal the analytic values at texel centres (|error| <= 1e-6)",
        "normal, tangent (with sign) and bitangent equal the analytic frame",
        "plane: texel-centre coverage equals the reference",
    } <= passed


def test_thin_triangle_conservative_mask(render_tests: Path, tmp_path: Path) -> None:
    """2.3, spec scenario "Thin triangle": a sliver narrower than a texel and a triangle inside one
    texel are in the conservative mask although their texel-centre coverage is (almost) empty."""
    passed, _ = run_case(render_tests, "uv-raster-thin", tmp_path)
    assert {
        "sliver: the conservative mask covers every texel a triangle touches",
        "sliver: the conservative mask marks no untouched texel",
        "sliver: the conservative mask contains the texel-centre coverage",
        "the conservative mask marks the sliver's texels although few or no centres are covered",
        "a triangle inside one texel marks it in the mask with an empty texel centre",
    } <= passed


def test_sphere_and_bevelled_cube_coverage(render_tests: Path, tmp_path: Path) -> None:
    """3.2: on the sphere and bevelled-cube fixtures (square and non-square sizes) the conservative
    mask covers every texel a triangle touches and contains the texel-centre coverage."""
    passed, _ = run_case(render_tests, "uv-raster-coverage", tmp_path)
    for fixture in ("sphere", "bevelled cube"):
        for size in ("512x512", "300x200"):
            label = f"{fixture} {size}"
            assert {
                f"{label}: the conservative mask covers every texel a triangle touches",
                f"{label}: the conservative mask marks no untouched texel",
                f"{label}: the conservative mask contains the texel-centre coverage",
                f"{label}: texel-centre coverage equals the reference",
            } <= passed


def test_material_and_island_ids(render_tests: Path, tmp_path: Path) -> None:
    """3.3: a two-material, two-island mesh has the right material and island id per texel; a
    texture-set filter rasterises only that set's triangles."""
    passed, _ = run_case(render_tests, "uv-raster-ids", tmp_path)
    assert {
        "both islands cover texels",
        "material and island ids are correct per texel",
        "a texture-set filter rasterises only its material's triangles, keeping their indices",
    } <= passed


def _hashes(output: str) -> dict[str, str]:
    return {
        parts[1]: parts[2]
        for parts in (line.split() for line in output.splitlines() if line.startswith("HASH "))
    }


def test_repeatable_across_processes(render_tests: Path, tmp_path: Path) -> None:
    """3.4: the bevelled cube rasterised twice in one process and in two separate processes gives
    byte-identical buffers."""
    first_passed, first = run_case(render_tests, "uv-raster-repeat", tmp_path / "first")
    second_passed, second = run_case(render_tests, "uv-raster-repeat", tmp_path / "second")
    check = "two runs in one process give byte-identical buffers"
    assert check in first_passed and check in second_passed
    first_hashes, second_hashes = _hashes(first), _hashes(second)
    assert set(first_hashes) == set(BUFFERS)
    assert first_hashes == second_hashes
