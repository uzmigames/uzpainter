"""Analytical geometry only; numerical bounds here are not Painter tolerances."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tools.parity.fit.plane_transforms import FOLD_GATE, Construction, Plane, rotate_between_planes


@pytest.mark.parametrize("construction", ["intersection", "householder"])
@pytest.mark.parametrize("degrees", [-140, -70, -30, -12, 12, 30, 70, 140])
@pytest.mark.parametrize("shift", [(0.0, 0.0, 0.0), (13.0, -7.0, 21.0)])
def test_rotation_matches_analytical_fold_and_preserves_rigid_chart(
    construction: Construction, degrees: int, shift: tuple[float, float, float]
) -> None:
    angle = math.radians(degrees)
    c, s = math.cos(angle), math.sin(angle)
    source = Plane((-s, 0.0, c), shift)
    target = Plane((0.0, 0.0, 1.0), shift)
    # Plane tangents and its normal define independently known rotated points.
    p = (shift[0] + 2 * c - 0.3 * s, shift[1] + 3, shift[2] + 2 * s + 0.3 * c)
    q = (shift[0] + 4 * c, shift[1] - 2, shift[2] + 4 * s)
    moved = rotate_between_planes(p, source, target, construction=construction, mode="all")
    other = rotate_between_planes(q, source, target, construction=construction, mode="all")
    np.testing.assert_allclose(moved, np.asarray(shift) + np.array([2, 3, 0.3]), rtol=0, atol=2e-13)
    np.testing.assert_allclose(other, np.asarray(shift) + np.array([4, -2, 0]), rtol=0, atol=2e-13)
    assert math.dist(moved, other) == pytest.approx(math.dist(p, q), rel=0, abs=2e-13)
    inverse = rotate_between_planes(moved, target, source, construction=construction, mode="all")
    np.testing.assert_allclose(inverse, p, rtol=0, atol=2e-13)


@pytest.mark.parametrize("construction", ["intersection", "householder"])
def test_nonintersecting_anchors_still_rotate_about_plane_intersection(
    construction: Construction,
) -> None:
    # Source x=2 and target z=5 intersect on (2, y, 5). Their supplied anchors
    # are deliberately different points; rotation maps +x to +z, not vice versa.
    source = Plane((7.0, 0.0, 0.0), (2.0, 11.0, -9.0))
    target = Plane((0.0, 0.0, 3.0), (-6.0, -8.0, 5.0))
    actual = rotate_between_planes((2.25, 4.0, 8.0), source, target, construction=construction)
    np.testing.assert_allclose(actual, (-1.0, 4.0, 5.25), rtol=0, atol=4e-15)


@pytest.mark.parametrize("construction", ["intersection", "householder"])
@pytest.mark.parametrize("normal", [(0.0, 0.0, 1.0), (0.0, 0.0, -1.0), (5e-11, 0.0, 1.0)])
def test_parallel_antiparallel_and_near_parallel_keep_original_point(
    construction: Construction, normal: tuple[float, float, float]
) -> None:
    point = (-0.0, 2.0, 3.0)
    source = Plane(normal, (0.0, 0.0, 100.0))
    target = Plane((0.0, 0.0, 1.0), (0.0, 0.0, -100.0))
    result = rotate_between_planes(point, source, target, construction=construction, mode="all")
    assert np.asarray(result).tobytes() == np.asarray(point).tobytes()


@pytest.mark.parametrize("construction", ["intersection", "householder"])
@pytest.mark.parametrize("delta", [-1e-6, 1e-6])
def test_existing_float32_fold_gate_and_disabled_mode(
    construction: Construction, delta: float
) -> None:
    cosine = FOLD_GATE + delta
    sine = math.sqrt(1 - cosine * cosine)
    source = Plane((-sine, 0.0, cosine), (0.0, 0.0, 0.0))
    target = Plane((0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
    point = (cosine, 0.0, sine)
    result = rotate_between_planes(point, source, target, construction=construction)
    if delta > 0:
        assert result == point
    else:
        np.testing.assert_allclose(result, (1, 0, 0), rtol=0, atol=1e-15)
    assert (
        rotate_between_planes(point, source, target, construction=construction, mode="none")
        == point
    )


@pytest.mark.parametrize("normal", [(0.0, 0.0, 0.0), (math.nan, 0.0, 1.0), (math.inf, 0.0, 1.0)])
def test_invalid_normals_refuse_instead_of_returning_nonfinite_geometry(
    normal: tuple[float, float, float],
) -> None:
    source = Plane(normal, (0.0, 0.0, 0.0))
    target = Plane((0.0, 0.0, 1.0), (0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="finite"):
        rotate_between_planes((1.0, 2.0, 3.0), source, target)
