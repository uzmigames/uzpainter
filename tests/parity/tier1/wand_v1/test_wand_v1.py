"""Wand v1 Tier 1 on the owner's machine (phase1.25 items 2.4, 3.1, 3.2, 3.3; decision 028).

Rebuilds Wand v1 twice through the pipeline adapter on DX12 (`runner.py`) and compares both
rebuilds with the private golden; the first rebuild's project is also saved, reopened in a fresh
process and exported again (3.3). One module fixture runs all of it once; 3.1 with 3.2 and 3.3 are
checked by separate tests. It needs the UzmiGames asset repository (`UZP_TEST_ASSETS3D`,
default `E:\\UzmiGames\\Assets3D`), `zig` for a fresh `zig build painter`, the private store and the
admitted golden `phase1/tier1/wand-v1` (recording R9); hosted CI has none of them and skips it
with the reason. Synthetic host cases of the comparison are in `../test_tier1_compare.py`.

While phase1.25 item 2.7 is open, UzPainter refuses the pinned five-map export before writing:
the virtual Normal on the Wand's UV islands is not exact (decision 245), and neither is its
`infinite` padding there (decision 259; the owner withdrew exception EXC-007). The test then checks
that both rebuilds refused it with one of those refusals and that the report states it as the one
structural failure `candidate_export_refused`, and ends as an expected failure naming the refusal
(decision 255); the 3.3 test then has no evidence (a refused first export is never reopened) and
ends as an expected failure too. Any other refusal fails the tests with its message; once the
refusal is lifted, the equality, repeatability and save/reopen assertions run unchanged.
Diagnostic measure exports (`test_wand_measure.py`) are never reopened and never count as 3.3.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.adapters.assets3d.wand import ASSETS3D, REPO_ROOT
from tests.parity.tier1.wand_v1.runner import GOLDEN_ID, Reopen, reopened_compared
from tools.parity.schemas import Schema, validation_errors
from tools.parity.store.store import locate
from tools.parity.tier1.compare import CandidateRun, write_report
from tools.parity.verdict import resolve_golden

REPORT_ENV = "UZP_TIER1_REPORT"  # repository-relative path of the report to write
# The decided refusals of the five-map export (src/export/padding.cpp `IslandNormalRefusal` and
# `CheckPadding`), whichever of its files is checked first.
KNOWN_REFUSALS = (
    "the Height outside the UV islands; decision 245",
    "UV islands do not cover the whole tile is not exact",
)

pytestmark = [
    pytest.mark.skipif(
        not (ASSETS3D / "AGENTS.md").is_file(),
        reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
    ),
    pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine"),
    pytest.mark.skipif(
        resolve_golden(GOLDEN_ID) is None,
        reason=f"{GOLDEN_ID} is not admitted yet (recording R9, owner session O)",
    ),
]


@pytest.fixture(scope="module")
def painter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`UzPainter.exe` of a fresh `zig build painter -Doptimize=ReleaseFast` install: in a Debug
    build the five-map export takes longer than the adapter's 600 s per call (decision 223: 465 s
    to its first 2048 map)."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; UzPainter.exe cannot be built")
    prefix = tmp_path_factory.mktemp("painter")
    build = subprocess.run(
        [zig, "build", "painter", "-Doptimize=ReleaseFast", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "UzPainter.exe"


Evidence = tuple[dict[str, Any], tuple[CandidateRun, CandidateRun], Reopen | None]


@pytest.fixture(scope="module")
def evidence(painter: Path, tmp_path_factory: pytest.TempPathFactory) -> Evidence:
    """The report, the two rebuilds and the save/reopen record (`runner.reopened_compared`),
    from one run for both tests."""
    return reopened_compared(painter, tmp_path_factory.mktemp("wand"))


def refusals_of(runs: tuple[CandidateRun, CandidateRun]) -> list[str]:
    """Each rebuild's refusal message, asserted to be a decided refusal; empty when none refused."""
    if not any(r.refused for r in runs):
        return []
    refusals = [r.refusal for r in runs]
    assert all(any(k in message for k in KNOWN_REFUSALS) for message in refusals), refusals
    return refusals


def test_wand_v1_maps_equal_painter_and_are_byte_stable(evidence: Evidence) -> None:
    """3.1 every exported map equals its golden; 3.2 the two independent rebuilds, each in its own
    processes and work directory, are byte-identical."""
    report, runs, _ = evidence
    assert validation_errors(report, Schema.COMPARISON_REPORT) == []
    if os.environ.get(REPORT_ENV):
        write_report(report, REPO_ROOT / os.environ[REPORT_ENV])
    equality = report["equality_to_painter"]
    if refusals := refusals_of(runs):
        assert equality == {
            "outcome": "fail",
            "exceptions_relied_on": [],
            "maps": [],
            "structural": [{"output_id": "export", "reason": "candidate_export_refused"}],
        }
        assert report["uzpainter_repeatability"] == {"status": "not_measured", "maps": []}
        pytest.xfail(f"UzPainter refuses the five-map export (decisions 245, 259): {refusals[0]}")
    assert equality["structural"] == []
    assert equality["outcome"] == "pass", equality
    assert report["uzpainter_repeatability"]["status"] == "repeatable"


def test_wand_v1_saved_and_reopened_project_exports_the_first_maps(evidence: Evidence) -> None:
    """3.3 the first rebuild's project keeps one file and UUID from its first export (the receipt's
    project) through the save to the reopen in a fresh process, and exports again every file of its
    first export, byte for byte (the first export's hashes were taken before the save)."""
    _, runs, reopen = evidence
    if refusals := refusals_of(runs):
        assert reopen is None  # a refused first export is never reopened: no 3.3 evidence
        pytest.xfail(f"UzPainter refuses the five-map export (decisions 245, 259): {refusals[0]}")
    assert reopen is not None
    assert reopen.first, "the first export wrote no file"
    assert reopen.same_project, reopen
    assert reopen.refusal == "", reopen.refusal
    assert reopen.differing == [], reopen.differing
    assert reopen.equal
