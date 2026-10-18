"""Sash v5 Tier 1 and its MCP-only round on the owner's machine (phase2.9 items 2.3-2.5, 3.1-3.3;
decisions 028, 192, 260).

Rebuilds Sash v5 twice through the pipeline adapter on DX12 (`runner.py`) and compares both
rebuilds with the private golden; runs the round through typed MCP tools with Python disabled
(`../mcp_round.py`) and compares its maps with a Tier 1 rebuild's. They need the UzmiGames asset
repository (`UZP_TEST_ASSETS3D`), `zig` for a fresh `zig build painter` and the private store; the
Tier 1 test needs the admitted golden `phase2/tier1/sash-v5`, the round its request. Hosted CI has
none of them and skips with the reason; until the owner restores the waist-v5 round folder
(decisions 192, 260) both skip naming that.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.adapters.assets3d.wand import ASSETS3D, REPO_ROOT
from tests.parity.tier1.mcp_round import round_report, run_round
from tests.parity.tier1.sash_v5.runner import GOLDEN_ID, REQUEST, run
from tests.parity.tier1.wand_v1.runner import rebuild
from tools.parity.schemas import Schema, validation_errors
from tools.parity.store.store import locate
from tools.parity.tier1.compare import write_report
from tools.parity.tier1.mcp_round import write_report as write_round_report
from tools.parity.verdict import resolve_golden

REPORT_ENV = "UZP_TIER1_REPORT"  # repository-relative path of the report to write
ROUND_ENV = "UZP_MCP_ROUND_REPORT"  # the same for the MCP-only round's report

pytestmark = [
    pytest.mark.skipif(
        not (ASSETS3D / "AGENTS.md").is_file(),
        reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
    ),
    pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine"),
]
GOLDEN = resolve_golden(GOLDEN_ID)
NO_REQUEST = "its request waits on the owner restoring the waist-v5 round folder (decision 260)"
admitted = pytest.mark.skipif(
    GOLDEN is None,
    reason=f"{GOLDEN_ID} is not admitted: "
    + ("its request is not recorded yet" if REQUEST.is_file() else NO_REQUEST),
)
requested = pytest.mark.skipif(
    GOLDEN is None and not REQUEST.is_file(), reason=f"{GOLDEN_ID}: {NO_REQUEST}"
)


@pytest.fixture(scope="module")
def painter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`UzPainter.exe` of a fresh `zig build painter` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; UzPainter.exe cannot be built")
    prefix = tmp_path_factory.mktemp("painter")
    build = subprocess.run(
        [zig, "build", "painter", "--prefix", str(prefix)],
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


@admitted
def test_sash_v5_maps_equal_painter_and_are_byte_stable(painter: Path, tmp_path: Path) -> None:
    """3.1 every exported map equals its golden; 3.2 the two rebuilds are byte-identical."""
    report = run(painter, tmp_path)
    assert validation_errors(report, Schema.COMPARISON_REPORT) == []
    if os.environ.get(REPORT_ENV):
        write_report(report, REPO_ROOT / os.environ[REPORT_ENV])
    equality = report["equality_to_painter"]
    assert equality["structural"] == []
    assert equality["outcome"] == "pass", equality
    assert report["uzpainter_repeatability"]["status"] == "repeatable"


@requested
def test_sash_v5_round_through_typed_mcp_tools_with_python_disabled(
    painter: Path, tmp_path: Path
) -> None:
    """2.5, 3.3: the round through typed tools against a supervisor without `--allow-python`;
    `run_python` is not listed, every call is typed, the round completes and its maps equal the
    Tier 1 run's byte for byte."""
    manifest = GOLDEN.manifest_path if GOLDEN is not None else REQUEST
    _, tier1 = rebuild(painter, tmp_path / "tier1", manifest)
    log = run_round(painter, tmp_path / "round", manifest)
    report = round_report(log, tier1, manifest, painter)
    if os.environ.get(ROUND_ENV):
        write_round_report(report, REPO_ROOT / os.environ[ROUND_ENV])
    assert report["python"] == {"allow_python": False, "run_python_listed": False}
    assert report["outcome"] == "completed", report.get("refusal", report["calls"][-1])
    assert report["equal_to_tier1"] == "equal", report["maps"]
