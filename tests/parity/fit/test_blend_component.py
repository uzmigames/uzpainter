"""Component and normal-map blend formulas of `tools/parity/fit/blend_component.py` (no store)."""

from __future__ import annotations

import math

import numpy as np

from tools.parity.fit.blend_component import (
    component_result,
    decode_normal,
    half_truncate,
    hsv_mode,
    hsv_to_rgb,
    normal_mode,
    normal_opengl,
    reoriented,
    rgb_to_hsv,
    store,
    toward_flat,
    unorm,
    whiteout,
)

FLAT = np.array([[0.0, 0.0, 1.0]], np.float32)


def unit(*v: float) -> np.ndarray:
    a = np.array([v], np.float64)
    return (a / np.linalg.norm(a)).astype(np.float32)


def test_unorm_truncates_then_rounds_ties_down() -> None:
    assert unorm(np.array([0.0, 1.0, -0.5, 1.5]), 16).tolist() == [0, 65535, 0, 65535]
    # 0.5 * 65535 = 32767.5 exactly: the tie goes down.
    assert unorm(np.array([0.5]), 16).tolist() == [32767]
    # (k + 0.53) / 65535 lies within 2^-20 of the next lower 20-bit step's code ... + 0.5:
    # truncated to 20 bits it rounds down, plain rounding would go up.
    x = (1000 + 0.53) / 65535
    assert round(x * 65535) == 1001
    assert unorm(np.array([x]), 16).tolist() == [1000]
    # 8-bit: 12 fractional bits. 128.5 / 255 truncated to 12 bits is below the tie.
    assert unorm(np.array([128.5 / 255]), 8).tolist() == [128]
    assert unorm(np.array([128.6 / 255]), 8).tolist() == [129]


def test_half_truncate_rounds_toward_zero() -> None:
    third = np.array([1.0 / 3.0, -1.0 / 3.0])
    out = half_truncate(third)
    assert abs(out[0]) <= 1.0 / 3.0 and abs(out[1]) <= 1.0 / 3.0
    assert out[0] == -out[1]
    assert float(np.float16(out[0])) == out[0]
    assert half_truncate(np.array([0.5])).tolist() == [0.5]


def test_store_by_format() -> None:
    x = np.array([0.25])
    assert store(x, "RGB16").tolist() == [16384]  # 16383.75 -> 16384
    assert store(x, "RGB8").tolist() == [64]  # 63.75 -> 64
    assert store(np.array([0.5]), "sRGB8").tolist() == [188]  # 255 * 0.7354 = 187.5 -> 188
    assert store(x, "RGB32F").tolist() == [0.25]


def test_hsv_round_trip_without_epsilon() -> None:
    c = np.array([[0.2, 0.6, 0.4], [0.9, 0.1, 0.5], [0.3, 0.3, 0.3]])
    h, s, v = rgb_to_hsv(c, eps=0.0)
    assert np.allclose(hsv_to_rgb(h, s, v), c)
    assert math.isclose(h[0], (2.0 + (0.4 - 0.2) / 0.4) / 6.0)
    assert s[2] == 0.0 and h[2] == 0.0


def test_saturation_epsilon() -> None:
    _, s, _ = rgb_to_hsv(np.array([[0.5, 0.25, 0.25]]), eps=2.0**-12)
    assert math.isclose(s[0], 0.25 / (0.5 + 2.0**-12))


def test_hsv_modes_double_the_value() -> None:
    grey = np.array([[0.2, 0.2, 0.2]])
    colour = np.array([[0.1, 0.8, 0.8]])
    # Tint of a grey keeps its zero saturation: 2 * value.
    assert np.allclose(hsv_mode("Tint", grey, colour), 0.4)
    # Value: hue and saturation of A (grey) with twice the value of B.
    assert np.allclose(hsv_mode("Value", grey, colour), 1.6)
    # Color: hue and saturation of B, twice the value of A.
    out = hsv_mode("Color", grey, colour)[0]
    assert math.isclose(out[1], 0.4) and math.isclose(out[2], 0.4)
    assert math.isclose(out[0], 0.4 * (1.0 - 0.7 / (0.8 + 2.0**-12)))


def test_grey_channel_modes() -> None:
    a, b = np.array([[0.25]]), np.array([[0.75]])
    assert component_result("Tint", a, b, "L16", 1.0).tolist() == [[16384]]
    assert component_result("Value", a, b, "L16", 1.0).tolist() == [[49151]]
    assert component_result("NormalMapDetail", a, b, "L16", 1.0).tolist() == [[49151]]


def test_hsv_result_is_clamped_on_integer_formats_only() -> None:
    a, b = np.array([[0.75, 0.75, 0.75]]), np.array([[0.1, 0.2, 0.3]])
    assert component_result("Tint", a, b, "RGB16", 1.0).tolist() == [[65535] * 3]
    assert np.allclose(component_result("Tint", a, b, "RGB32F", 1.0), 1.5)
    # Opacity 0.5: A + (clamp(f) - A) / 2.
    assert component_result("Tint", a, b, "RGB16", 0.5).tolist() == [[57343] * 3]


def test_decode_normal_clamps_z_then_normalises() -> None:
    n = decode_normal(np.array([[1.0, 1.0, 0.0]]))
    assert np.allclose(n, [[math.sqrt(0.5), math.sqrt(0.5), 0.0]], atol=1e-7)
    n = decode_normal(np.array([[0.5, 0.5, 1.0]]))
    assert np.allclose(n, FLAT)


def test_whiteout_and_reoriented_with_flat_operands() -> None:
    d = unit(0.3, -0.2, 0.9)
    assert np.allclose(whiteout(FLAT, d), d)
    assert np.allclose(reoriented(FLAT, d), d, atol=1e-7)
    assert np.allclose(reoriented(d, FLAT), d, atol=1e-7)


def test_reoriented_matches_the_published_example() -> None:
    # Base tilted along x by 45 degrees, detail flat-tilted by 45 degrees along x too:
    # RNM rotates the detail by the base rotation, giving a 90-degree tilt (1, 0, 0).
    b = unit(1.0, 0.0, 1.0)
    out = normal_mode("NormalMapDetail", b, b)
    assert np.allclose(out, [[1.0, 0.0, 0.0]], atol=1e-6)


def test_inverse_detail_swaps_base_and_detail() -> None:
    a, b = unit(0.4, 0.1, 0.9), unit(-0.2, 0.5, 0.8)
    assert np.array_equal(
        normal_mode("NormalMapInverseDetail", a, b), normal_mode("NormalMapDetail", b, a)
    )
    combine = normal_mode("NormalMapCombine", a, b)
    expected = np.array([[a[0, 0] + b[0, 0], a[0, 1] + b[0, 1], a[0, 2] * b[0, 2]]])
    assert np.allclose(combine, expected / np.linalg.norm(expected), atol=1e-6)


def test_toward_flat_is_spherical() -> None:
    n = unit(1.0, 0.0, 0.0)
    half = toward_flat(n, 0.5)
    assert np.allclose(half, unit(1.0, 0.0, 1.0), atol=1e-7)
    quarter = toward_flat(n, 0.25)
    angle = math.pi / 8.0
    assert np.allclose(quarter, [[math.sin(angle), 0.0, math.cos(angle)]], atol=1e-7)
    assert np.array_equal(toward_flat(n, 1.0), n)
    assert np.allclose(toward_flat(FLAT, 0.3), FLAT)


def test_normal_opengl_of_the_flat_normal() -> None:
    assert normal_opengl(np.array([[0.5, 0.5, 1.0]])).tolist() == [[32767, 32767, 65535]]
