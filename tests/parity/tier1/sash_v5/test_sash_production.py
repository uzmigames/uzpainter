"""Sash v5 Tier 1 on the production export (decisions 414, 417), opt-in.

The Wand's production Tier 1 (`../wand_v1/test_wand_production.py`) over the Sash v5 golden
`phase2/tier1/sash-v5-current`, under the manifest's `OCIO` (`runner.production`): two rebuilds
whose every export is the production export, conformant under EXC-013 and EXC-014, each map judged
with the exceptions its receipt names. It runs only when `UZP_TIER1_PRODUCTION=1`, on the owner's
machine, with the same inputs and skips as `test_sash_v5.py`, and prints per-map counts
(`SASH_PRODUCTION:`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.parity.tier1.sash_v5.runner import production
from tests.parity.tier1.sash_v5.test_sash_v5 import (
    _NEEDS_THE_SASH,
    painter,  # noqa: F401  (the fixture)
)
from tests.parity.tier1.wand_v1.test_wand_production import (
    PRODUCTION_ENV,
    PRODUCTION_EXCEPTIONS,
    check_production,
    counts,
)

pytestmark = [
    *_NEEDS_THE_SASH,
    pytest.mark.skipif(
        os.environ.get(PRODUCTION_ENV) != "1",
        reason=f"opt-in GPU run: set {PRODUCTION_ENV}=1 (decision 417)",
    ),
]


def test_sash_v5_production_export_equals_painter_under_exc013_and_exc014(
    painter: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    report, runs = production(painter, tmp_path)
    found = counts(report) if not runs[0].refused else {}
    print("SASH_PRODUCTION: " + json.dumps(found, sort_keys=True))
    normals = frozenset(k[1] for k in runs[0].files if k[1].endswith("_Normal"))
    relied = {e["exception_id"] for e in report["equality_to_painter"]["exceptions_relied_on"]}
    assert relied <= PRODUCTION_EXCEPTIONS | {"EXC-012"}, relied
    check_production(report, runs, normals)
