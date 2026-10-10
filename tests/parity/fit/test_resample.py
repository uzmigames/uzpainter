"""UV-projection resampling of `tools/parity/fit/resample.py` on synthetic arrays (no store)."""

from __future__ import annotations

import numpy as np

from tools.parity.fit.resample import (
    bilinear,
    bilinear_weights,
    nearest,
    resample,
    texel_coordinates,
    unorm16,
)


def test_identity_transform_puts_output_texels_on_bitmap_texel_centres() -> None:
    x, y, inside = texel_coordinates(4, [1.0, 1.0], 0.0, [0.0, 0.0], 4, 4)
    assert np.allclose(x, np.arange(4)[None, :])
    assert np.allclose(y, np.arange(4)[:, None])  # row 0 on top in both
    assert inside.all()


def test_positive_offset_moves_the_image_towards_plus_u_and_plus_v() -> None:
    # offset one texel in u and v: output texel (i, j) reads texel (i - 1, j + 1) (v up).
    x, y, _ = texel_coordinates(4, [1.0, 1.0], 0.0, [0.25, 0.25], 4, 4)
    assert np.allclose(x, np.arange(4)[None, :] - 1)
    assert np.allclose(y, np.arange(4)[:, None] + 1)


def test_scale_is_about_the_uv_centre_and_tiles() -> None:
    # scale 2 on a 4-texel map: u = (i + 0.5)/4 -> u' = 2 (u - 0.5) + 0.5.
    x, _, inside = texel_coordinates(4, [2.0, 2.0], 0.0, [0.0, 0.0], 4, 4)
    assert np.allclose(x[0], [-1.5, 0.5, 2.5, 4.5])
    assert inside[1:3, 1:3].all() and not inside[0, 0]


def test_rotation_turns_the_sample_point_clockwise_in_uv() -> None:
    # r = 90: u' = b + 0.5, v' = -a + 0.5 with (a, b) = (u - 0.5, v - 0.5).
    x, y, _ = texel_coordinates(2, [1.0, 1.0], 90.0, [0.0, 0.0], 2, 2)
    # output texel (0, 0): u = 0.25, v = 0.75 -> u' = 0.75, v' = 0.75 -> x = 1, y = 0.
    assert np.allclose([x[0, 0], y[0, 0]], [1.0, 0.0])
    # output texel (1, 0): u = 0.75, v = 0.75 -> u' = 0.75, v' = 0.25 -> x = 1, y = 1.
    assert np.allclose([x[0, 1], y[0, 1]], [1.0, 1.0])


def test_bilinear_weights_round_the_corner_product_and_sum_to_256() -> None:
    fx, fy = np.array([193, 1, 128, 2, 0]), np.array([207, 15, 128, 64, 0])
    w00, w10, w01, w11 = bilinear_weights(fx, fy)
    assert list(zip(w00, w10, w01, w11, strict=True)) == [
        (12, 37, 51, 156),  # 193 * 207 / 256 = 156.06
        (240, 1, 15, 0),
        (64, 64, 64, 64),
        (190, 2, 64, 0),  # 2 * 64 / 256 = 0.5: tie rounds down
        (256, 0, 0, 0),
    ]
    assert ((w00 + w10 + w01 + w11) == 256).all()


def test_unorm16_is_exact_on_a_single_tap() -> None:
    codes = np.arange(65536, dtype=np.int64)
    assert (unorm16(codes * 256) == codes).all()


def test_unorm16_truncates_to_20_bits_then_rounds_ties_down() -> None:
    # Midpoint of 32767 and 32768 is v = 0.5 exactly: a tie, rounded down.
    assert unorm16(np.array([128 * 32767 + 128 * 32768])).tolist() == [32767]
    # S / 256 = 0.546875 rounds to 1, but v truncated to 20 bits is 8 / 2^20 -> 0.49999 -> 0.
    assert unorm16(np.array([140])).tolist() == [0]
    # S / 256 = 0.5625: truncation keeps it above one half -> 1.
    assert unorm16(np.array([144])).tolist() == [1]


def test_bilinear_interpolates_with_eight_bit_sub_texel_positions() -> None:
    image = np.array([[0, 65535]], np.int64)
    x = np.array([[0.0, 0.25, 0.5, 1.0]])
    y = np.zeros_like(x)
    # 0.25 -> weights (192, 64): 64 * 65535 / 256 = 16383.75 -> 16384; 0.5 -> 32767.5 tie down.
    assert bilinear(image, x, y, "RepeatNone").tolist() == [[0, 16384, 32767, 65535]]
    # x = 1/1024 is below half a 1/256 step: the sample snaps to the texel centre.
    assert bilinear(image, np.array([[1 / 1024]]), np.zeros((1, 1)), "Repeat").tolist() == [[0]]


def test_repeat_wraps_and_repeat_none_clamps_the_taps() -> None:
    image = np.array([[1000, 3000]], np.int64)
    x, y = np.array([[1.5]]), np.zeros((1, 1))
    assert bilinear(image, x, y, "Repeat").tolist() == [[2000]]  # texels 1 and 0
    assert bilinear(image, x, y, "RepeatNone").tolist() == [[3000]]  # texel 1 twice
    assert nearest(image, np.array([[2.0, -1.0]]), np.zeros((1, 2)), "Repeat").tolist() == [
        [1000, 3000]
    ]


def test_resample_at_scale_one_copies_the_bitmap() -> None:
    rng = np.random.default_rng(1)
    image = rng.integers(0, 65536, (8, 8, 3), dtype=np.int64)
    for filtering in ("BilinearHQ", "Nearest"):
        out = resample(image, [1.0, 1.0], 0.0, [0.0, 0.0], filtering, "Repeat", size=8)
        assert (out == image).all()


def test_repeat_none_keeps_the_value_below_outside_the_uv_domain() -> None:
    image = np.full((4, 4), 100, np.int64)
    out = resample(image, [2.0, 2.0], 0.0, [0.0, 0.0], "BilinearHQ", "RepeatNone", size=4)
    expected = np.full((4, 4), 65535)
    expected[1:3, 1:3] = 100
    assert (out == expected).all()
