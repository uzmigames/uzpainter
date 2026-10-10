"""Comparison statistics, prototypes and fits of the procedural feasibility study (2.5-2.7)."""

from __future__ import annotations

import numpy as np
import pytest

from tools.parity.feasibility.compare import (
    Difference,
    comparison_domain,
    difference,
    erode,
    rasterise_uv,
)
from tools.parity.feasibility.fit import fit_leather, fit_step_curve, nelder_mead
from tools.parity.feasibility.fixtures import Mesh
from tools.parity.feasibility.prototypes import (
    FULL,
    MEW_FIT_NAMES,
    StepCurve,
    UnsupportedParameters,
    fbm,
    gaussian_blur,
    leather_damaged,
    metal_edge_wear,
    perlin_noise,
    position_generator,
)
from tools.parity.feasibility.study import CaseResult, MapResult


def test_difference_reports_max_mean_nearest_rank_p99_and_counts() -> None:
    a = np.zeros((10, 10, 1), np.int64)
    b = a.copy()
    b[0, 0, 0] = 7
    b[0, 1, 0] = 3
    domain = np.ones((10, 10), np.bool_)
    assert difference(a, b, domain) == Difference(7, 0.1, 3, 2, 100, 2, 100)
    domain[0, 0] = False
    assert difference(a, b, domain).max == 3


def test_difference_counts_texels_once_across_channels() -> None:
    a = np.zeros((2, 2, 3), np.int64)
    b = a.copy()
    b[1, 1] = (1, 2, 0)
    result = difference(a, b, np.ones((2, 2), np.bool_))
    assert (result.differing, result.total, result.affected_texels, result.texels) == (2, 12, 1, 4)


def test_uv_rasterisation_and_erosion() -> None:
    mesh = Mesh(
        "square",
        np.zeros((4, 3)),
        np.zeros((4, 3)),
        np.array([[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]),
        np.array([[0, 1, 2], [0, 2, 3]]),
        ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
        lambda p: np.zeros(p.shape[:-1]),
    )
    covered = rasterise_uv(mesh, 8)
    assert covered.sum() == 16 and covered[2:6, 2:6].all()
    assert erode(covered).sum() == 4


def test_comparison_domains_cover_the_islands() -> None:
    assert comparison_domain("sphere").mean() > 0.95
    cube = comparison_domain("rounded-cube")
    assert 0.5 < cube.mean() < 2 / 3
    assert not cube[:300].any()  # the top third of the atlas holds no island


def test_position_generator_semantics() -> None:
    position = np.stack([*np.meshgrid(np.arange(4), np.arange(4)), np.full((4, 4), 9)], -1)
    position = position.astype(np.int64) * 1000
    assert np.array_equal(position_generator(position, {}, {}), position[..., 1])
    inverted = position_generator(
        position,
        {
            "position_direction_topbottom_opacity": 0.0,
            "position_direction_rightleft_opacity": 1.0,
            "position_invert": 1,
        },
        {},
    )
    assert np.array_equal(inverted, FULL - position[..., 0])
    with pytest.raises(UnsupportedParameters):
        position_generator(position, {"position_contrast": 0.5}, {})
    with pytest.raises(UnsupportedParameters):
        position_generator(position, {"global_blur": 1.0}, {})
    stepped = position_generator(
        position,
        {"position_contrast": 1.0, "position_balance": 1.0},
        {(1.0, 1.0): StepCurve(1500.0, 1.0)},
    )
    assert set(np.unique(stepped).tolist()) <= {0, FULL}


def test_noise_is_deterministic_tileable_and_in_range() -> None:
    noise = perlin_noise((64, 64), 4, 1)
    assert np.array_equal(noise, perlin_noise((64, 64), 4, 1))
    assert not np.array_equal(noise, perlin_noise((64, 64), 4, 2))
    assert np.abs(noise).max() <= 1.0
    # Tileable: across the wrap the noise changes no more than between neighbouring texels.
    seam = np.abs(noise[:, 0] - noise[:, -1]).max()
    assert seam <= 1.5 * np.abs(np.diff(noise, axis=1)).max()
    octaves = fbm((32, 32), 2, 0)
    assert octaves.min() >= 0.0 and octaves.max() <= 1.0


def test_gaussian_blur_keeps_the_mean_and_smooths() -> None:
    image = np.zeros((32, 32))
    image[16, 16] = 1.0
    blurred = gaussian_blur(image, 2.0)
    assert blurred.sum() == pytest.approx(1.0)
    assert blurred.max() < 0.1
    assert np.array_equal(gaussian_blur(image, 0.0), image)


def test_metal_edge_wear_wears_convex_edges_first() -> None:
    curvature = np.full((32, 32, 1), 32768, np.int64)
    curvature[:, 16:] = 49151
    occlusion = np.full((32, 32, 1), FULL, np.int64)
    fitted = dict(zip(MEW_FIT_NAMES, (2.0, 0.0, 0.0, 0.0, 4.0), strict=True))
    out = metal_edge_wear(curvature, occlusion, {"Grunge_Amount": 0.0}, fitted)
    assert out[:, :16].max() < out[:, 16:].min()


def test_nelder_mead_finds_a_quadratic_minimum() -> None:
    best, value = nelder_mead(
        lambda v: float((v[0] - 1.0) ** 2 + (v[1] + 2.0) ** 2), (0.0, 0.0), (0.5, 0.5), 300
    )
    assert np.allclose(best, (1.0, -2.0), atol=1e-3) and value < 1e-6


def test_step_fit_reproduces_a_one_code_transition() -> None:
    x = np.arange(100, 110, dtype=np.int64)
    y = np.where(x < 104, 0, FULL)
    y[x == 104] = 34999
    curve = fit_step_curve([x], [y])
    rebuilt = np.floor(np.clip(0.5 + (x - curve.threshold) * curve.gain, 0, 1) * FULL + 0.5)
    assert np.array_equal(rebuilt.astype(np.int64), y)


def test_leather_fit_recovers_its_own_recipe() -> None:
    shape = (32, 32)
    curvature = np.full((*shape, 1), 32768, np.int64)
    curvature[:, :8] = 49151
    truth = {
        name: {"base": [0.3] * width, "grain": [0.2] * width, "edge": [0.1] * width}
        for name, width in (
            ("basecolor", 3),
            ("specularroughness", 1),
            ("basemetalness", 1),
            ("height", 1),
            ("normal", 3),
        )
    }
    oracle = leather_damaged(curvature, truth, shape)
    fitted = fit_leather([(curvature, oracle, np.ones(shape, np.bool_))], shape)
    assert fitted["height"]["base"][0] == pytest.approx(0.3, abs=1e-4)
    assert fitted["basecolor"]["edge"][2] == pytest.approx(0.1, abs=1e-3)


def test_non_zero_residual_is_never_equal() -> None:
    from tools.parity.feasibility.cases import cases

    case = cases()[0]
    zero = Difference(0, 0.0, 0, 0, 10, 0, 10)
    one = Difference(1, 0.1, 0, 1, 10, 1, 10)
    assert CaseResult(case, [MapResult("m", zero, {"r1": zero, "r2": zero})]).classification == (
        "equal"
    )
    for residuals in ({"r1": one, "r2": zero}, {"r1": zero, "r2": one}):
        result = CaseResult(case, [MapResult("m", zero, residuals)])
        assert result.classification == "candidate exception or gap"
    unstable = CaseResult(case, [MapResult("m", one, {"r1": zero, "r2": zero})])
    assert unstable.classification != "equal"
    assert CaseResult(case, [], unsupported="x").classification == "gap"
