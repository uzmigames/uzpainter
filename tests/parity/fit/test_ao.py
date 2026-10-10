"""`AO_Mixed` operator of `tools/parity/fit/ao.py` on synthetic codes (no store)."""

from __future__ import annotations

import numpy as np

from tools.parity.fit.ao import ao_mixed, mesh_map_codes


def test_full_operands_give_white() -> None:
    assert ao_mixed(np.array([65535]), np.array([65535])).tolist() == [65535]


def test_product_is_written_at_8_bit_precision() -> None:
    # a = 128/255, c = 1: v = 128/255, exactly code 128 -> export 128 * 257.
    assert ao_mixed(np.array([128 * 257]), np.array([65535])).tolist() == [128 * 257]
    # a = 1, c = 0.5 (code 32767): 0.49999 * 255 = 127.497 -> 127.
    assert ao_mixed(np.array([65535]), np.array([32767])).tolist() == [127 * 257]


def test_truncation_rounds_just_above_half_down() -> None:
    # a = 1/255, c = 128/255: 255 * a * c = 0.502; plain rounding gives code 1, but v truncated to
    # 12 bits is 8/4096 and 8 * 255 / 4096 = 0.498 rounds to 0.
    assert ao_mixed(np.array([257]), np.array([128 * 257])).tolist() == [0]
    # a = 1, c = 32768/65535: v * 4096 = 2048.03 -> 2048; 2048 * 255 / 4096 = 127.5, tie down.
    assert ao_mixed(np.array([65535]), np.array([32768])).tolist() == [127 * 257]


def test_empty_channel_returns_the_mesh_map_on_the_8_bit_lattice() -> None:
    codes = np.arange(256, dtype=np.int64) * 257
    assert ao_mixed(codes, np.full_like(codes, 65535)).tolist() == codes.tolist()


def test_operator_is_symmetric() -> None:
    a = np.arange(256, dtype=np.int64)[None, :] * 257
    c = np.arange(256, dtype=np.int64)[:, None] * 257
    product = ao_mixed(np.broadcast_to(a, (256, 256)), np.broadcast_to(c, (256, 256)))
    assert (product == product.T).all()
    assert (product % 257 == 0).all()


def test_mesh_map_is_the_authored_ramp_along_x() -> None:
    codes = mesh_map_codes()
    assert codes.shape == (256, 256)
    assert (codes == np.arange(256)[None, :] * 257).all()
