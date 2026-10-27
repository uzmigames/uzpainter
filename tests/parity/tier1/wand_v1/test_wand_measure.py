"""Wand v1 diagnostic measure (decision 286), opt-in: how far the measured padding is from Painter.

Runs `runner.measured`: two rebuilds exported with `--diagnostic-measure-export`, past refusals
245 and 259, whose maps are `non_conformant` and never a verdict. Prints, per map and texel class
(interior, edge, ring, gutter), the texels of the first rebuild that differ from Painter's r1. It
runs only when `UZP_WAND_MEASURE=1` (a GPU run of about ten minutes, never part of the suite), on
the owner's machine, with the same inputs as `test_wand_v1.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.parity.tier1.wand_v1.runner import measured
from tests.parity.tier1.wand_v1.test_wand_v1 import painter  # noqa: F401  (the fixture)
from tests.parity.tier1.wand_v1.test_wand_v1 import pytestmark as wand_marks

pytestmark = [
    *wand_marks,
    pytest.mark.skipif(
        os.environ.get("UZP_WAND_MEASURE") != "1",
        reason="opt-in diagnostic GPU run: set UZP_WAND_MEASURE=1 (decision 286)",
    ),
]


def test_wand_v1_measured_padding_texels_against_painter(
    painter: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    report, split = measured(painter, tmp_path)
    print("WAND_MEASURE: " + json.dumps(split, sort_keys=True))
    assert split, report
    for name, classes in split.items():
        assert set(classes) == {"interior", "edge", "ring", "gutter"}, name
