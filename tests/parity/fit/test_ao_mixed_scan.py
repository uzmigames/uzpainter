"""`tools/parity/fit/ao_mixed_scan.py` on synthetic operands (no store)."""

from __future__ import annotations

import numpy as np

from tools.parity.fit.ao_mixed_scan import (
    allowed_shifts,
    l16_opacity,
    normal_over_white,
    product,
    quantize,
    shift_ulps,
)

F32 = np.float32
BOUNDARY = F32(1551 / 4096)  # a 12-bit step whose 8-bit code changes: j = 1551 -> 97, 1550 -> 96


def test_quantizer_keeps_twelve_bits_and_rounds_ties_down() -> None:
    assert quantize([0.0, 1.0]).tolist() == [0, 255]
    # j = 2048: 2048 * 255 / 4096 = 127.5, a tie, written as 127.
    assert quantize([0.5]).tolist() == [127]
    assert quantize([BOUNDARY]).tolist() == [97]


def test_quantizer_rounds_to_the_2_pow_minus_23_grid_first() -> None:
    # In [0.25, 0.5) one ulp is 2^-25. Two ulps below the step is a tie on the 2^-23 grid and
    # goes to the even neighbour, the step itself; three ulps below rounds below the step.
    assert quantize([shift_ulps(BOUNDARY, -1)]).tolist() == [97]
    assert quantize([shift_ulps(BOUNDARY, -2)]).tolist() == [97]
    assert quantize([shift_ulps(BOUNDARY, -3)]).tolist() == [96]


def test_l16_opacity_rounds_the_code_ties_down() -> None:
    assert l16_opacity(0.5) == F32(32767 / 65535)
    assert l16_opacity(0.75) == F32(49151 / 65535)
    assert l16_opacity(1.0) == F32(1)


def test_normal_over_white_at_full_opacity_is_the_source() -> None:
    source = (np.arange(256) / 255).astype(F32)
    assert (normal_over_white(source, 1.0) == source).all()
    assert normal_over_white([0.0], 0.5).tolist() == [F32(1) - l16_opacity(0.5)]


def test_product_is_one_float32_rounding() -> None:
    a, c = F32(1 / 3), F32(3)
    assert product([a], [c])[0] == F32(np.float64(a) * np.float64(c))


def test_allowed_shifts_finds_the_moves_that_explain_a_code() -> None:
    a, c = np.array([F32(1)]), np.array([BOUNDARY])
    assert allowed_shifts(a, c, [96], "c", span=4) == {float(BOUNDARY): [-4, -3]}
    assert allowed_shifts(a, c, [97], "c", span=4) == {float(BOUNDARY): [-2, -1, 0, 1, 2, 3, 4]}
    # A row that matches under every shift is not reported.
    assert allowed_shifts(np.array([F32(0)]), c, [0], "c", span=2) == {}
