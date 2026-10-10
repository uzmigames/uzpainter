"""Height-to-normal model of `tools/parity/fit/normal.py` on synthetic heights (no store)."""

from __future__ import annotations

import numpy as np

from tools.parity.fit.normal import (
    SCALE,
    height_normal,
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


def test_flat_height_gives_the_flat_normal_in_both_formats() -> None:
    maps = normal_maps(np.zeros((4, 4)))
    for name in ("Normal_OpenGL", "Normal_DirectX"):
        assert maps[name].shape == (4, 4, 3)
        assert (maps[name] == np.array([32767, 32767, 65535])).all()


def test_ramp_along_x_tilts_x_by_the_fitted_scale() -> None:
    # Slope 75/256 per texel times k = 2.56 gives 0.75: normalize(-0.75, 0, 1) = (-0.6, 0, 0.8).
    assert SCALE == 2.56
    height = np.tile(np.arange(8) * 75 / 256, (8, 1))
    nx, ny, nz = height_normal(height)
    assert np.isclose(nx[3, 3], -0.6, atol=1e-6)
    assert ny[3, 3] == 0.0
    assert np.isclose(nz[3, 3], 0.8, atol=1e-6)
    maps = normal_maps(height)
    assert maps["Normal_OpenGL"][3, 3].tolist() == [13107, 32767, 58981]
    assert maps["Normal_DirectX"][3, 3].tolist() == [13107, 32767, 58981]


def test_ramp_down_the_rows_flips_green_between_opengl_and_directx() -> None:
    # Height growing towards lower rows falls towards +v: OpenGL green up, DirectX green down.
    height = np.tile((np.arange(8) * 75 / 256)[:, None], (1, 8))
    maps = normal_maps(height)
    assert maps["Normal_OpenGL"][3, 3].tolist() == [32767, 52428, 58981]
    assert maps["Normal_DirectX"][3, 3].tolist() == [32767, 13107, 58981]


def test_backward_difference_wraps_at_the_left_border() -> None:
    # Column 0 differences against the last column (-7 * slope): x tilts towards +x.
    height = np.tile(np.arange(8) * 75 / 256, (8, 1))
    first = normal_maps(height)["Normal_OpenGL"][3, 0]
    assert first[0] > 32767 and first[1] == 32767


def test_uv_domain_of_a_full_quad_is_the_image_minus_its_border() -> None:
    obj = b"v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nf 1/1 2/2 3/3 4/4\n"
    domain = uv_domain(obj)
    assert domain.shape == (256, 256)
    assert int(domain.sum()) == 254 * 254
    assert not domain[0].any() and domain[1, 1:255].all()
