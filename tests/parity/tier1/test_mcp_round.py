"""The MCP-only round on the Wand v1 inputs, the stand-in for Belt v5 (phase2.9 item 2.5;
decision 192).

The Belt v5 round folder is gone from Assets3D until the owner restores it, so the round tool
(`mcp_round.py`) is exercised on the admitted Wand v1 golden's pinned inputs: the same three-step
pipeline round, the same export configuration. This is evidence for the tool only, never for the
Belt: item 2.5 closes on the Belt's own report (`belt_v5/test_belt_v5.py`). It needs the UzmiGames
asset repository, the private store (the Wand's inputs resolve there by hash, decision 144) and
`zig`; hosted CI skips it with the reason.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.adapters.assets3d.wand import ASSETS3D, REPO_ROOT
from tests.parity.tier1.mcp_round import round_report, run_round
from tests.parity.tier1.wand_v1 import runner as wand_runner
from tools.parity.store.store import locate
from tools.parity.tier1.mcp_round import report_problems
from tools.parity.verdict import resolve_golden

pytestmark = [
    pytest.mark.skipif(
        not (ASSETS3D / "AGENTS.md").is_file(),
        reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
    ),
    pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine"),
    pytest.mark.skipif(
        resolve_golden(wand_runner.GOLDEN_ID) is None,
        reason=f"{wand_runner.GOLDEN_ID} is not admitted",
    ),
]

# The round's calls before the export, in order; each succeeds, and these commit a revision.
BEFORE_EXPORT = [
    "project_create",
    "set_list",
    "set_mesh_maps",
    "project_save_as",
    "sync_stack",
    "project_save",
]
COMMITTING = {"project_create", "set_mesh_maps", "sync_stack"}


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


def test_wand_round_runs_through_typed_tools_with_python_disabled(
    painter: Path, tmp_path: Path
) -> None:
    """`run_python` is not listed; every call is a typed tool; the round's maps equal the Tier 1
    run's byte for byte, or both refuse the same export before writing."""
    manifest = resolve_golden(wand_runner.GOLDEN_ID)
    assert manifest is not None
    _, tier1 = wand_runner.rebuild(painter, tmp_path / "tier1", manifest.manifest_path)
    log = run_round(painter, tmp_path / "round", manifest.manifest_path)
    report = round_report(log, tier1, manifest.manifest_path, painter)
    assert report_problems(report) == []
    assert report["python"] == {"allow_python": False, "run_python_listed": False}
    calls = report["calls"]
    assert [call["tool"] for call in calls] == [*BEFORE_EXPORT, "export"], calls
    assert all(call["outcome"] != "error" for call in calls[:-1]), calls
    assert {c["tool"] for c in calls if c["outcome"] == "committed"} >= COMMITTING, calls
    if report["outcome"] == "refused":
        assert tier1.refused, "the round refused an export the Tier 1 run wrote"
        assert report["equal_to_tier1"] == "not_measured"
    else:
        assert report["outcome"] == "completed" and report["equal_to_tier1"] == "equal", report
