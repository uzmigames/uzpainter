"""Unreal Engine (Packed) on the pilots (phase3.2_unreal-ue56-packed-preset item 3.1).

Each pilot's Unreal golden (`phase3/tier1/<pilot>-unreal`, written by
`tools/parity/recorder/gltf_pilots.py` with `preset="unreal"`) is the pilot's admitted Tier 1
golden closed by Painter's own export of its starter-assets `Unreal Engine (Packed)` preset, by
the versioned URL R-322 observed (PNG 16, the pilot's size, `infinite` padding, no dithering).
UzPainter rebuilds it twice through the Wand's runner, every export the production export, as the
glTF pilots do (`test_gltf_pilots.py`), and resolves the URL to the authored
`unreal-engine-packed` preset (`src/export/preset_aliases.cpp`, decision 422). Every map, the
Unreal files and the script's five, is compared in decoded values with Painter's r1, each judged
with the exceptions its receipt names (EXC-013 for the padding, EXC-014 for the Normal's island
edge; decisions 414, 417). A pass is a pass under those, never exact.

It runs only when `UZP_TIER1_PRODUCTION=1` (six GPU rebuilds, never part of the suite), on the
owner's machine, and prints per-map counts (`UNREAL_<PILOT>:`). With `UZP_UNREAL_REPORTS=1` it
writes each comparison report to `parity/reports/phase3/tier1-<pilot>-unreal.json`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from adapters.assets3d.client import GPU_DEADLINE_ENV
from tests.adapters.assets3d.wand import ASSETS3D
from tests.parity.tier1.test_mcp_round import (
    fast_painter,  # noqa: F401  (the fixture)
    painter_ocio,
)
from tests.parity.tier1.tunic_recipe import GPU_DEADLINE_MS
from tests.parity.tier1.wand_v1 import runner as wand_runner
from tests.parity.tier1.wand_v1.test_wand_production import PRODUCTION_ENV, counts
from tools.parity.recorder.gltf_pilots import UNREAL_PILOT_GOLDENS
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.store.store import locate
from tools.parity.tier1.compare import CandidateRun, write_report
from tools.parity.verdict import resolve_golden

PRODUCTION_EXCEPTIONS = frozenset({"EXC-013", "EXC-014"})
# The preset's maps a pilot writes (no Opacity, Emissive or SpecularWeight channel on any pilot):
# each file's name ends `_<map>_<$colorSpace>` under OCIO.
UNREAL_MAPS = ("BaseColor", "OcclusionRoughnessMetallic", "Normal")

pytestmark = [
    pytest.mark.skipif(
        not (ASSETS3D / "AGENTS.md").is_file(),
        reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
    ),
    pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine"),
    pytest.mark.skipif(
        os.environ.get(PRODUCTION_ENV) != "1",
        reason=f"opt-in GPU run: set {PRODUCTION_ENV}=1 (decision 417)",
    ),
]


def golden_id(pilot: str) -> str:
    found = UNREAL_PILOT_GOLDENS[pilot][1]
    if resolve_golden(found) is None:
        pytest.skip(f"{found} is not admitted")
    return found


def unreal_map(name: str) -> str | None:
    """The Unreal map a file name holds (`<mesh>_<set>_<map>[_<colour space>]`), or None."""
    parts = name.split("_")
    for index in (-1, -2):
        if len(parts) >= -index and parts[index] in UNREAL_MAPS:
            return parts[index]
    return None


def compared(
    painter: Path, work: Path, pilot: str
) -> tuple[dict[str, Any], tuple[CandidateRun, CandidateRun]]:
    """The report and the two production rebuilds, under each pilot's own conditions (as
    `test_gltf_pilots.compared`)."""
    found = golden_id(pilot)
    with pytest.MonkeyPatch.context() as patch:
        if pilot != "wand-v1":
            patch.setenv("OCIO", str(painter_ocio()))
        if pilot == "tunic-v10":
            patch.setenv(GPU_DEADLINE_ENV, str(GPU_DEADLINE_MS))
        report, runs = wand_runner.compared(painter, work, found, Path("unused"))
    print(f"UNREAL_{pilot.upper()}: " + json.dumps(counts(report) if not runs[0].refused else {}))
    if os.environ.get("UZP_UNREAL_REPORTS") == "1":
        write_report(report, REPO_ROOT / f"parity/reports/phase3/tier1-{pilot}-unreal.json")
    return report, runs


def check(report: dict[str, Any], runs: tuple[CandidateRun, CandidateRun]) -> None:
    """Neither rebuild refused; the preset wrote exactly BaseColor, the ORM and Normal; every file
    relies on EXC-013 at most and only a Normal on EXC-014; equal to Painter under those;
    byte-identical rebuilds."""
    assert validation_errors(report, Schema.COMPARISON_REPORT) == []
    assert not any(r.refused for r in runs), [r.refusal for r in runs]
    unreal = sorted(m for key in runs[0].files if (m := unreal_map(key[1])) is not None)
    assert sorted(set(unreal)) == sorted(UNREAL_MAPS), runs[0].files.keys()
    for run in runs:
        for key, relied in run.exceptions.items():
            normal = unreal_map(key[1]) == "Normal" or key[1].lower().endswith("_normal")
            assert relied <= PRODUCTION_EXCEPTIONS and ("EXC-014" in relied) <= normal, (
                key,
                relied,
            )
    equality = report["equality_to_painter"]
    assert equality["structural"] == [], equality["structural"]
    assert equality["outcome"] == "pass", (equality["outcome"], counts(report))
    assert {e["exception_id"] for e in equality["exceptions_relied_on"]} <= PRODUCTION_EXCEPTIONS
    assert report["uzpainter_repeatability"]["status"] == "repeatable"


def test_wand_v1_unreal_export_equals_painter(
    fast_painter: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    check(*compared(fast_painter, tmp_path, "wand-v1"))


def test_sash_v5_unreal_export_equals_painter(
    fast_painter: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    check(*compared(fast_painter, tmp_path, "sash-v5"))


def test_tunic_v10_unreal_export_equals_painter(
    fast_painter: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    check(*compared(fast_painter, tmp_path, "tunic-v10"))
