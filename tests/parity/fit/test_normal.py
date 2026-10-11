"""Height-to-normal model of `tools/parity/fit/normal.py` on synthetic heights (no store)."""

from __future__ import annotations

import numpy as np

from tools.parity.fit import hwmath
from tools.parity.fit.normal import (
    SHARP_Z,
    SOBEL_Z,
    half_toward_zero,
    height_layers,
    height_readout,
    height_vector,
    normal_maps,
    unorm,
    uv_domain,
)


def test_unorm16_truncates_then_rounds_ties_down() -> None:
    values = np.array([0.0, 0.2, 0.5, 0.8, 0.9, 1.0])
    # 0.2 * 65535 = 13107 and 0.8 * 65535 = 52428 exactly; 0.5 and 0.9 are ties that go down.
    assert unorm(values, 16).tolist() == [0, 13107, 32767, 52428, 58981, 65535]


def test_unorm8_keeps_four_extra_bits_before_rounding() -> None:
    # 128/255 is 0.502 of a code above 127.5: truncated to 12 bits it is 2056/4096, which still
    # rounds up; 0.5 is a tie at 127.5 and goes down.
    assert unorm(np.array([128 / 255, 0.5, 1.0]), 8).tolist() == [128, 127, 255]


def test_hardware_rsqrt_is_within_two_ulps_of_the_correct_one() -> None:
    y = np.linspace(1.0, 4.0, 4097, dtype=np.float32)
    correct = hwmath.rsqrt_correct(y)
    exact = (1.0 / np.sqrt(y.astype(np.float64))).astype(np.float32)
    assert np.all(np.abs(correct.view(np.int32) - exact.view(np.int32)) <= 1)
    moved = hwmath.rsqrt(y).view(np.int32) - correct.view(np.int32)
    assert set(np.unique(moved).tolist()) <= {-2, -1, 0, 1}


def test_flat_height_gives_the_flat_normal_in_both_formats_and_methods() -> None:
    for method in ("Sharp", "SmoothSobel"):
        maps = normal_maps(np.zeros((4, 4)), method)
        for name in ("Normal_OpenGL", "Normal_DirectX"):
            assert maps[name].shape == (4, 4, 3)
            assert (maps[name] == np.array([32767, 32767, 65535])).all()


def test_stencils_read_backward_differences_and_the_sobel_neighbourhood() -> None:
    h = np.arange(25, dtype=np.float32).reshape(5, 5) ** 2
    x, y, z = height_vector(h, "Sharp")
    assert x[2, 2] == h[2, 1] - h[2, 2] and y[2, 2] == h[2, 2] - h[1, 2] and z[2, 2] == SHARP_Z
    x, y, z = height_vector(h, "SmoothSobel")
    left = h[1, 1] + 2 * h[2, 1] + h[3, 1]
    right = h[1, 3] + 2 * h[2, 3] + h[3, 3]
    top = h[1, 1] + 2 * h[1, 2] + h[1, 3]
    bottom = h[3, 1] + 2 * h[3, 2] + h[3, 3]
    assert x[2, 2] == left - right and y[2, 2] == bottom - top and z[2, 2] == SOBEL_Z


def test_ramp_down_the_rows_flips_green_between_opengl_and_directx() -> None:
    # Height growing towards lower rows falls towards +v: OpenGL green up, DirectX green down.
    height = np.tile((np.arange(8) * 75 / 256)[:, None], (1, 8)).astype(np.float32)
    maps = normal_maps(height)
    gl, dx = maps["Normal_OpenGL"][3, 3], maps["Normal_DirectX"][3, 3]
    assert gl[0] == dx[0] == 32767 and gl[2] == dx[2]
    assert gl[1] > 32767 > dx[1]


def test_backward_difference_wraps_at_the_left_border() -> None:
    # Column 0 differences against the last column (-7 * slope): x tilts towards +x.
    height = np.tile(np.arange(8) * 75 / 256, (8, 1)).astype(np.float32)
    first = normal_maps(height)["Normal_OpenGL"][3, 0]
    assert first[0] > 32767 and first[1] == 32767


def test_readout_keeps_the_unquantised_product_and_stacks_quantise_per_layer() -> None:
    q = half_toward_zero(np.array([0.3, -0.7, 0.123], np.float32))
    single = height_readout(q, [("Normal", 0.75)])
    assert np.array_equal(single, (q * np.float32(0.75)).astype(np.float32))
    stacked = height_readout(q, [("Normal", 1.0), ("LinearDodge", 1.0), ("LinearDodge", 1.0)])
    assert np.array_equal(stacked, half_toward_zero(half_toward_zero(q + q) + q))


def test_height_layers_follow_the_recorded_order() -> None:
    steps = [
        {"step": 3, "call": "x.layerstack.insert_fill", "args": {"texture_set": "s0"}},
        {"step": 4, "call": "x.layerstack.insert_fill", "args": {"above_step": 3}},
        {
            "step": 5,
            "call": "x.Node.set_blending_mode",
            "args": {"node_step": 4, "blending_mode": "LinearDodge", "channel": "Height"},
        },
        {
            "step": 6,
            "call": "x.Node.set_opacity",
            "args": {"node_step": 3, "opacity": 0.5, "channel": "Height"},
        },
        {"step": 7, "call": "x.layerstack.insert_fill", "args": {"texture_set": "s1"}},
    ]
    manifest = {"instruction_sequence": {"steps": steps}}
    assert height_layers(manifest, "s0") == [("Normal", 0.5), ("LinearDodge", 1.0)]
    assert height_layers(manifest, "s1") == [("Normal", 1.0)]


def test_uv_domain_of_a_full_quad_is_the_image_minus_its_border() -> None:
    obj = b"v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nf 1/1 2/2 3/3 4/4\n"
    domain = uv_domain(obj)
    assert domain.shape == (256, 256)
    assert int(domain.sum()) == 254 * 254
    assert not domain[0].any() and domain[1, 1:255].all()
