"""Wand v1 Tier 1 on the production export (decisions 414, 417), opt-in.

Rebuilds Wand v1 twice through the pipeline adapter exactly as `test_wand_v1.py` does, but every
export is the production export, not the diagnostic measure export: production writes the
islanded five-map export under the owner's EXC-013 (the `infinite` padding outside the UV
coverage) and EXC-014 (the combined virtual Normal's covered island-edge texels), a conformant
generation. Each rebuild's receipt names, per file, the exceptions it relies on, and the
comparison judges each map with those (`runner.relied_exceptions`, `CandidateRun.exceptions`): a
production-export entry covers only the files its receipt names. A pass is a pass under those
exceptions, never exact.

It runs only when `UZP_TIER1_PRODUCTION=1` (two GPU rebuilds, never part of the suite), on the
owner's machine, with the same inputs and skips as `test_wand_v1.py`. It prints, per map, the
covered, island-edge and uncovered texel statistics (`WAND_PRODUCTION:`), counts only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.parity.tier1.wand_v1.runner import compared
from tests.parity.tier1.wand_v1.test_wand_v1 import painter  # noqa: F401  (the fixture)
from tests.parity.tier1.wand_v1.test_wand_v1 import pytestmark as wand_marks
from tools.parity.schemas import Schema, validation_errors
from tools.parity.tier1.compare import CandidateRun

PRODUCTION_ENV = "UZP_TIER1_PRODUCTION"
EXC013 = frozenset({"EXC-013"})
EXC014 = frozenset({"EXC-013", "EXC-014"})
# What a production pilot's equality may rely on: the production exceptions, and the pilot's own
# golden-scoped entry where its bounds also hold.
PRODUCTION_EXCEPTIONS = frozenset({"EXC-013", "EXC-014"})

pytestmark = [
    *wand_marks,
    pytest.mark.skipif(
        os.environ.get(PRODUCTION_ENV) != "1",
        reason=f"opt-in GPU run: set {PRODUCTION_ENV}=1 (decision 417)",
    ),
]


def counts(report: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Per map, the covered, island-edge and uncovered texel counts and how many values of each
    differ."""

    def differing(block: dict[str, Any] | None) -> int:
        return int(block["differing"]["count"]) if block else 0

    found: dict[str, dict[str, int]] = {}
    for entry in report["equality_to_painter"]["maps"]:
        padding = entry["padding"]
        found[entry["output_id"]] = {
            "covered": padding["covered_texels"],
            "covered_differing": differing(padding["covered"]),
            "edge": padding["edge_texels"],
            "edge_differing": differing(padding["edge"]),
            "uncovered": padding["uncovered_texels"],
            "uncovered_differing": differing(padding["uncovered"]),
        }
    return found


def check_production(
    report: dict[str, Any], runs: tuple[CandidateRun, CandidateRun], normals: frozenset[str]
) -> dict[str, dict[str, int]]:
    """The checks every pilot's production Tier 1 shares (`counts` returned): neither rebuild
    refused, every receipt naming EXC-013 for every map and EXC-014 for the Normal only, five
    maps each with its padding split, a pass relying on both production exceptions (and on
    nothing outside them but the pilot's own golden-scoped entry), and byte-identical rebuilds."""
    assert validation_errors(report, Schema.COMPARISON_REPORT) == []
    assert not any(r.refused for r in runs), [r.refusal for r in runs]
    for run in runs:
        assert set(run.exceptions) == set(run.files), run.exceptions
        for key, relied in run.exceptions.items():
            assert relied == (EXC014 if key[1] in normals else EXC013), (key, relied)
    equality = report["equality_to_painter"]
    assert equality["structural"] == []
    assert len(equality["maps"]) == 5 and all("padding" in m for m in equality["maps"]), equality
    found = counts(report)
    assert equality["outcome"] == "pass", (equality["outcome"], found)
    named = {e["exception_id"] for e in equality["exceptions_relied_on"]}
    assert named >= PRODUCTION_EXCEPTIONS, equality["exceptions_relied_on"]
    assert report["uzpainter_repeatability"]["status"] == "repeatable"
    return found


def test_wand_v1_production_export_equals_painter_under_exc013_and_exc014(
    painter: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    report, runs = compared(painter, tmp_path)
    found = counts(report) if not runs[0].refused else {}
    print("WAND_PRODUCTION: " + json.dumps(found, sort_keys=True))
    normals = frozenset(k[1] for k in runs[0].files if k[1].endswith("_Normal"))
    relied = {e["exception_id"] for e in report["equality_to_painter"]["exceptions_relied_on"]}
    assert relied <= PRODUCTION_EXCEPTIONS | {"EXC-010"}, relied
    check_production(report, runs, normals)
