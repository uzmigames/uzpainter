"""Tunic v10 Tier 1 on the production export (decisions 414, 417), opt-in.

The Wand's production Tier 1 (`wand_v1/test_wand_production.py`) over the Tunic current golden
`phase2/tier1/tunic-v10-current`, through the Wand's runner (its native route), as the measure
mode's `test_mcp_round.py::tunic_tier1` runs it: on the ReleaseFast build (`fast_painter`), under
the manifest's `OCIO` and with the Tunic's GPU deadline (`tunic_recipe.GPU_DEADLINE_MS`; its 4096 px
exports outlast the default). Two rebuilds whose every export is the production export, conformant
under EXC-013 and EXC-014, each map judged with the exceptions its receipt names. It runs only when
`UZP_TIER1_PRODUCTION=1`, on the owner's machine, with the same inputs and skips as the Tunic's
measure-mode Tier 1, and prints per-map counts (`TUNIC_PRODUCTION:`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from adapters.assets3d.client import GPU_DEADLINE_ENV
from tests.parity.tier1.test_mcp_round import (
    _NEEDS_THE_TUNIC,
    TUNIC_CURRENT,
    fast_painter,  # noqa: F401  (the fixture)
    painter_ocio,
)
from tests.parity.tier1.tunic_recipe import GPU_DEADLINE_MS
from tests.parity.tier1.wand_v1 import runner as wand_runner
from tests.parity.tier1.wand_v1.test_wand_production import (
    PRODUCTION_ENV,
    PRODUCTION_EXCEPTIONS,
    check_production,
    counts,
)

pytestmark = [
    *_NEEDS_THE_TUNIC,
    pytest.mark.skipif(
        os.environ.get(PRODUCTION_ENV) != "1",
        reason=f"opt-in GPU run: set {PRODUCTION_ENV}=1 (decision 417)",
    ),
]

# A native job's normal map is `<set>_Normal_Raw` (`wand_v1/runner.py`, `NORMAL_COLOUR_SPACE`).
NORMAL_SUFFIX = f"{wand_runner.NORMAL_SUFFIX}_{wand_runner.NORMAL_COLOUR_SPACE}"


def test_tunic_v10_production_export_equals_painter_under_exc013_and_exc014(
    fast_painter: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OCIO", str(painter_ocio()))
        patch.setenv(GPU_DEADLINE_ENV, str(GPU_DEADLINE_MS))
        report, runs = wand_runner.compared(fast_painter, tmp_path, TUNIC_CURRENT)
    found = counts(report) if not runs[0].refused else {}
    print("TUNIC_PRODUCTION: " + json.dumps(found, sort_keys=True))
    normals = frozenset(k[1] for k in runs[0].files if k[1].endswith(NORMAL_SUFFIX))
    relied = {e["exception_id"] for e in report["equality_to_painter"]["exceptions_relied_on"]}
    assert relied <= PRODUCTION_EXCEPTIONS | {"EXC-011"}, relied
    check_production(report, runs, normals)
