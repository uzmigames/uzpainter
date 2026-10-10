"""Separable blend formulas of `tools/parity/fit/blend.py` on synthetic values (no store)."""

from __future__ import annotations

import numpy as np

from tools.parity.fit.blend import (
    MODES,
    blend,
    fma,
    half_truncate,
    operand,
    stack,
    store,
    uniform_operand,
    unorm,
)
from tools.parity.tier0_semantics.corpus import BLEND_FAMILIES

F32 = np.float32


def arr(*v: float) -> np.ndarray:
    return np.array(v, F32)


def kernel(mode: str, a: float, b: float) -> float:
    return float(MODES[mode].kernel(arr(a), arr(b))[0])


def test_every_separable_mode_has_a_kernel() -> None:
    for family in ("basic", "additive", "contrast"):
        for mode in BLEND_FAMILIES[family]:
            assert mode in MODES


def test_unorm_truncates_to_guard_bits_then_rounds_ties_down() -> None:
    # Exact codes survive; the tie 0.5 code above 32767 rounds down.
    assert unorm(np.array([0.0, 1.0, 12345 / 65535]), 16).tolist() == [0, 65535, 12345]
    assert unorm(np.array([32767.5 / 65535]), 16).tolist() == [32767]
    # Just above a tie on 8 bits: truncation to 12 fractional bits drops it to the tie (down).
    assert unorm(np.array([1.502 / 255]), 8).tolist() == [1]
    assert unorm(np.array([1.6 / 255]), 8).tolist() == [2]
    # Out of range and NaN clamp.
    assert unorm(np.array([-0.2, 1.7, np.nan]), 8).tolist() == [0, 255, 0]


def test_half_truncate_rounds_toward_zero() -> None:
    v = arr(1.0 + 2.0**-11 * 1.9, -(1.0 + 2.0**-11 * 1.9))
    assert half_truncate(v).tolist() == [1.0, -1.0]


def test_rgb32f_store_composites_over_white() -> None:
    # Below 0.5 the value lands on a 2^-24 step, below 0 on a 2^-23 step.
    out = store(arr(2.0**-26, 3 * 2.0**-26, -3 * 2.0**-25, 0.75, 1.5), "RGB32F")
    assert out.tolist() == [0.0, 2.0**-24, -(2.0**-23), 0.75, 1.5]


def test_operand_decodes_storage_units() -> None:
    assert operand(np.array([65535]), "RGB16")[0] == F32(1.0)
    assert operand(np.array([51]), "RGB8")[0] == F32(0.2)
    assert operand(np.array([0, 255]), "sRGB8").tolist() == [0.0, 1.0]


def test_separable_kernels() -> None:
    assert kernel("Multiply", 0.5, 0.5) == 0.25
    assert kernel("Screen", 0.5, 0.5) == 0.75
    assert kernel("Exclusion", 0.25, 0.5) == 0.5
    assert kernel("Divide", 0.25, 0.5) == 0.5
    assert kernel("Divide", 0.0, 0.0) == 1.0  # 0 * inf is NaN; min(NaN, 1) gives 1
    assert kernel("InverseDivide", 0.5, 0.25) == 0.5
    assert kernel("Subtract", 0.25, 0.5) == -0.25
    assert kernel("InverseSubtract", 0.25, 0.5) == 0.25
    assert kernel("SignedAddition", 0.25, 0.75) == 0.75
    assert kernel("LinearBurn", 0.25, 0.5) == -0.25
    assert kernel("HardLight", 0.5, 0.25) == 0.25
    assert kernel("HardLight", 0.5, 0.75) == 0.75
    assert kernel("Overlay", 0.25, 0.5) == 0.25
    assert kernel("ColorBurn", 0.5, 0.5) == 0.0
    assert kernel("ColorBurn", 0.75, 0.5) == 0.5
    assert kernel("ColorDodge", 0.25, 0.5) == 0.5
    assert kernel("ColorDodge", 0.75, 0.5) == 1.0
    assert kernel("SoftLight", 0.25, 0.25) == 0.15625  # 2ab + a^2 (1 - 2b)
    assert kernel("SoftLight", 0.25, 0.75) == 0.375  # 2a(1 - b) + sqrt(a)(2b - 1)
    assert kernel("VividLight", 0.75, 0.25) == 0.5  # ColorBurn(a, 2b)
    assert kernel("LinearLight", 0.5, 0.25) == 0.0
    assert kernel("LinearLight", 0.75, 0.75) == 1.0  # clamped
    assert kernel("PinLight", 0.5, 0.125) == 0.25
    assert kernel("PinLight", 0.5, 0.875) == 0.75


def test_fma_rounds_once() -> None:
    x = arr(1.0 + 2.0**-12)
    # x*x - (1 + 2^-11) = 2^-24 exactly with one rounding; two roundings give 0.
    assert fma(x, x, arr(-(1.0 + 2.0**-11)))[0] == F32(2.0**-24)


def test_opacity_mix_and_clamp_by_format() -> None:
    a, b = arr(0.75), arr(0.75)
    dodge = MODES["LinearDodge"]
    # UNORM: r = 1.5 is clamped before the mix: 0.75*0.5 + 1*0.5.
    assert blend(dodge, a, b, "RGB16", 0.5).tolist() == [unorm(np.array([0.875]), 16)[0]]
    # Float formats keep r unclamped: 0.75*0.5 + 1.5*0.5.
    assert blend(dodge, a, b, "RGB16F", 0.5).tolist() == [1.125]
    # Replace uses a + (r - a) * alpha, Disable leaves the channel.
    assert blend(MODES["Replace"], arr(0.25), arr(0.75), "RGB32F", 0.5).tolist() == [0.5]
    assert blend(MODES["Disable"], arr(0.25), arr(0.75), "RGB16", 0.5).tolist() == [16384]


def test_stack_is_evaluated_bottom_up_over_white() -> None:
    a, b = arr(0.5), arr(0.25)
    c = uniform_operand((0.5,), "RGB16")
    # A Normal 1.0 -> 0.5; B Subtract 0.8 -> 0.5*0.2 + 0.25*0.8 = 0.3; C Divide 0.6.
    abc = stack("ABC", a, b, c, "RGB16")
    after_b = unorm(np.array([0.3]), 16) / 65535.0
    divided = min(1.0, after_b[0] / float(c[0]))
    expected = unorm(np.array([after_b[0] * 0.4 + divided * 0.6]), 16)
    assert abs(int(abc[0]) - int(expected[0])) <= 1
    # Over the white base, Divide gives 1 and A Normal then replaces it: CBA = A.
    assert stack("CBA", a, b, c, "RGB16").tolist() == [32767]  # 32767.5, tie rounds down
