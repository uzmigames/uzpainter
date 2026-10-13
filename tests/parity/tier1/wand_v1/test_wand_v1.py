"""Wand v1 Tier 1 on the owner's machine (phase1.25 items 2.4, 3.1, 3.2; decision 028).

Rebuilds Wand v1 twice through the pipeline adapter on DX12 (`runner.py`) and compares both
rebuilds with the private golden. It needs the UzmiGames asset repository (`UZP_TEST_ASSETS3D`,
default `E:\\UzmiGames\\Assets3D`), `zig` for a fresh `zig build painter`, the private store and the
admitted golden `phase1/tier1/wand-v1` (recording R9); hosted CI has none of them and skips it
with the reason. Synthetic host cases of the comparison are in `../test_tier1_compare.py`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.adapters.assets3d.wand import ASSETS3D, REPO_ROOT
from tests.parity.tier1.wand_v1.runner import GOLDEN_ID, run
from tools.parity.schemas import Schema, validation_errors
from tools.parity.store.store import locate
from tools.parity.tier1.compare import write_report
from tools.parity.verdict import resolve_golden

REPORT_ENV = "UZP_TIER1_REPORT"  # repository-relative path of the report to write

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


def test_wand_v1_maps_equal_painter_and_are_byte_stable(painter: Path, tmp_path: Path) -> None:
    """3.1 every exported map equals its golden; 3.2 the two rebuilds are byte-identical."""
    report = run(painter, tmp_path)
    assert validation_errors(report, Schema.COMPARISON_REPORT) == []
    if os.environ.get(REPORT_ENV):
        write_report(report, REPO_ROOT / os.environ[REPORT_ENV])
    equality = report["equality_to_painter"]
    assert equality["structural"] == []
    assert equality["outcome"] == "pass", equality
    assert report["uzpainter_repeatability"]["status"] == "repeatable"
