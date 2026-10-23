"""Independently authored AO operand; no Painter samples enter its generator."""

from __future__ import annotations

import hashlib
import struct

import numpy as np

from tools.parity.fit.decode import decode
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics.request_fixtures import ao_precomposed_half

SOURCE_SHA256 = "d5cdfd94bf239cfdb4630c78cf0bb72f5582ebea8bcc7a7a8f7edb4e474c3d84"


def f32(value: float) -> float:
    return float(struct.unpack("<f", struct.pack("<f", value))[0])


def test_authored_source_identity_and_all_256_operand_rows() -> None:
    authored = (
        REPO_ROOT / "parity/fixtures/tier0-semantics/bitmaps/ao-precomposed-half.exr"
    ).read_bytes()
    assert authored == ao_precomposed_half()
    assert hashlib.sha256(authored).hexdigest() == SOURCE_SHA256
    decoded = decode(authored)
    assert not decoded.integer and decoded.bits == 32
    assert decoded.values.shape == (256, 256, 3)
    rows = []
    for code in range(256):
        source = f32(code / 255)
        delta = f32(source - 1)
        # With scale 0.5, this double expression is exact before f32 rounding.
        composed = f32(delta * 0.5 + 1)
        identity = f32(f32(composed - 1) * 1 + 1)
        assert identity == composed
        rows.append(composed)
    expected = np.broadcast_to(np.asarray(rows)[:, None, None], (256, 256, 3))
    np.testing.assert_array_equal(decoded.values, expected)
    assert len(set(rows)) == 256 and rows[0] == 0.5 and rows[-1] == 1
