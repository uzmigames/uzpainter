"""The islanded-golden padding scorer's offline parts (`tools/parity/fit/padding_goldens.py`): the
document stores, the format detection and the classes; no oracle access."""

from __future__ import annotations

import types

import numpy as np
import pytest

from tools.parity.fit import padding_goldens as pg
from tools.parity.fit.padding_wand import source_table

F32 = np.float32
TABLE = {f.name: f for f in pg.formats()}


def test_the_half_store_rounds_toward_zero() -> None:
    above = F32(1.0 + 0.75 * 2.0**-10)  # nearest half is 1 + 2^-10, toward zero is 1
    assert pg.half_toward_zero(above) == F32(1.0)
    assert pg.half_toward_zero(-above) == F32(-1.0)
    assert pg.half_toward_zero(F32(0.25)) == F32(0.25)
    assert TABLE["half"].value(above) == F32(1.0)


def test_unorm_stores_keep_their_operands_and_requantise_the_rest() -> None:
    for bits, name in ((8, "UNORM8"), (16, "UNORM16")):
        fmt, m = TABLE[name], (1 << bits) - 1
        for k in (0, 1, m // 3, m - 1, m):
            operand = F32(k / m)
            assert fmt.holds(operand)
            assert fmt.value(operand) == operand
        assert not fmt.holds(F32(0.5 / m))
    # 1 - (1 - v) of a UNORM16 operand drifts off it; the store brings it back (seam goldens).
    v = F32(6553 / 65535)
    drifted = F32(1) - (F32(1) - v)
    assert drifted != v
    assert TABLE["UNORM16"].value(drifted) == v


def test_the_srgb8_store_keeps_its_decoded_operands() -> None:
    fmt = TABLE["sRGB8"]
    bits = source_table("src/evaluator/arith.cpp", "kSrgb8DecodeBits[256]")
    operands = list(np.array(bits, np.uint32).view(F32))
    assert len(set(operands)) == 256
    assert all(fmt.holds(v) and fmt.value(v) == v for v in operands)
    assert not fmt.holds(np.nextafter(operands[100], F32(1)))


def test_detect_takes_the_named_format_or_the_coarsest_that_holds() -> None:
    values = np.array([[[0.0], [1 / 255]], [[128 / 255], [1.0]]], F32)
    covered = np.ones((2, 2), bool)
    table = pg.formats()
    assert [f.name for f in pg.detect(values, covered, table)] == ["UNORM8"]
    assert [f.name for f in pg.detect(values, covered, table, "UNORM16")] == ["UNORM16"]
    values[0, 0, 0] = F32(0.1)
    assert [f.name for f in pg.detect(values, covered, table)] == ["float32"]
    with pytest.raises(ValueError, match="UNORM16"):
        pg.detect(values, covered, table, "UNORM16")
    # Uncovered texels do not count.
    covered[0, 0] = False
    assert [f.name for f in pg.detect(values, covered, table)] == ["UNORM8"]


def test_channel_formats_follow_the_added_channels_over_the_defaults() -> None:
    golden = types.SimpleNamespace(
        manifest={
            "instruction_sequence": {
                "steps": [
                    {"call": "substance_painter.project.create", "args": {}},
                    {
                        "call": "substance_painter.textureset.Stack.add_channel",
                        "args": {"channel": "User1", "format": "L32F"},
                    },
                    {
                        "call": "substance_painter.textureset.Stack.add_channel",
                        "args": {"channel": "Opacity", "format": "L8"},
                    },
                ]
            }
        }
    )
    named = pg.channel_formats(golden)  # type: ignore[arg-type]
    assert named["user1"] == "float32"
    assert named["opacity"] == "UNORM8"
    assert named["basecolor"] == "sRGB8"
    assert named["height"] == "half"


def test_ring_mask_and_differs() -> None:
    covered = np.zeros((3, 4), bool)
    covered[1, 0] = True
    ring = pg.ring_mask(covered)
    assert ring[1, 3] and ring[0, 1] and not ring[1, 0] and not ring[1, 2]
    a = np.zeros((2, 2, 1), F32)
    b = a.copy()
    b[1, 0, 0] = F32(-0.0)  # signed zero differs bit for bit
    assert pg.differs(a, b).tolist() == [[False, False], [True, False]]
