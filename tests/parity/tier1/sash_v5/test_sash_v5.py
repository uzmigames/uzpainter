"""Sash v5 Tier 1 and its MCP-only round on the owner's machine (phase2.9 items 2.3-2.5, 3.1-3.3;
decisions 028, 192, 260, 399).

Rebuilds Sash v5 twice through the pipeline adapter on DX12 (`runner.py`), saves and reopens the
first rebuild's project and exports it again, and compares both rebuilds with the private golden
`phase2/tier1/sash-v5-current`, the re-run waist-v5 round (decision 399). Every export is the
diagnostic measure export (decision 286): production refuses the Sash's islanded Normal and
`infinite` padding (decisions 245, 259), and the owner's EXC-012 (decision 399, EXC-010's terms)
excepts exactly what that mode writes inexactly. A pass is a pass under EXC-012, never exact.

The MCP-only round runs the same request through typed MCP tools with Python disabled
(`../mcp_round.py`), twice. With the production `export` tool, which refuses the islanded set
before writing, the round test is an expected failure naming that refusal (the export,
`NotYetSupported`, and a reason naming the islands and decision 245's or 259's refusal; any other
refusal fails). In the measure mode, as decision 398 §4 closed the Tunic's, the round sends no
export and its saved project is exported by the diagnostic measure export in its own `run`
process; that round must complete with every map byte-identical to the Tier 1 run's (also the
measure export), and it writes the round's report.

The dump-and-rebuild (gate G2, `parity/reports/phase2/gate-g2.md` §3.6) runs the Wand's recipe
scenario (`tests/parity/recipe/wand_v1/runner.py`) on the Sash: built through the adapter, its
recipe dumped, a new project rebuilt from the dump and the bundle's resources alone, both projects
exported by the diagnostic measure export; the digests must be equal and every exported file
byte-identical. Not conformant: it proves the rebuild reproduces the same bytes.

The tests need the UzmiGames asset repository (`UZP_TEST_ASSETS3D`), `zig` for a fresh `zig build
painter -Doptimize=ReleaseFast`, the private store and the admitted golden; hosted CI has none of
them and skips with the reason.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.adapters.assets3d.wand import ASSETS3D, REPO_ROOT
from tests.parity.recipe.wand_v1 import runner as recipe
from tests.parity.tier1.mcp_round import REFUSAL, Round, round_report, run_round
from tests.parity.tier1.sash_v5.runner import GOLDEN_ID, REQUEST, Evidence, painter_ocio, run
from tools.parity.recipe_rebuild import write_report as write_recipe_report
from tools.parity.schemas import Schema, validation_errors
from tools.parity.store.store import locate
from tools.parity.tier1.compare import write_report
from tools.parity.tier1.mcp_round import report_problems
from tools.parity.tier1.mcp_round import write_report as write_round_report
from tools.parity.verdict import resolve_golden

REPORT_ENV = "UZP_TIER1_REPORT"  # repository-relative path of the report to write
ROUND_ENV = "UZP_MCP_ROUND_REPORT"  # the same for the MCP-only round's report
RECIPE_ENV = "UZP_RECIPE_REBUILD_REPORT"  # the same for the dump-and-rebuild's report
# The only exception the Sash's equality may rely on (decision 399).
EXC012 = {"exception_id": "EXC-012", "version": 1}
# The production refusals of an islanded export the round may meet (src/export/padding.cpp
# `IslandNormalRefusal`, src/export/guards.cpp `CheckPadding`): the only expected failure.
ISLAND_REFUSAL = {"tool": "export", "error_code": REFUSAL, "type": "NotYetSupported"}
ISLANDS = "on a texture set whose UV islands do not cover the whole tile"
ISLAND_DECISIONS = ("decision 245", "decision 259")


def island_refusal(log: Round) -> bool:
    """Whether the round ended on exactly the export's islanded refusal: the export, the release
    gap `NotYetSupported`, and a reason naming the islands and decision 245's or 259's refusal."""
    reason = log.refusal_reason
    return (
        log.outcome == "refused"
        and log.refusal == ISLAND_REFUSAL
        and ISLANDS in reason
        and any(decision in reason for decision in ISLAND_DECISIONS)
    )


GOLDEN = resolve_golden(GOLDEN_ID)
_NEEDS_THE_SASH = [
    pytest.mark.skipif(
        not (ASSETS3D / "AGENTS.md").is_file(),
        reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
    ),
    pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine"),
    pytest.mark.skipif(GOLDEN is None, reason=f"{GOLDEN_ID} is not admitted"),
]


def _needs_the_sash[T: Callable[..., None]](test: T) -> T:
    """`test` skipped, with the reason, where the Sash's inputs or its golden are absent; the
    host test of the round's expected refusal runs everywhere."""
    for mark in _NEEDS_THE_SASH:
        test = mark(test)
    return test


@pytest.fixture(scope="module")
def painter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`UzPainter.exe` of a fresh `zig build painter -Doptimize=ReleaseFast` install: a Debug
    five-map export at 2048 px outlasts the adapter's 600 s per call (decision 223)."""
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


@pytest.fixture(scope="module")
def evidence(painter: Path, tmp_path_factory: pytest.TempPathFactory) -> Evidence:
    """The report, the two rebuilds and the save/reopen record, from one run for every test."""
    return run(painter, tmp_path_factory.mktemp("sash"))


@_needs_the_sash
def test_sash_v5_maps_equal_painter_and_are_byte_stable(evidence: Evidence) -> None:
    """3.1 every exported map equals its golden under EXC-012 (decision 399: covered interior
    texels exact on every map, covered texels exact on every map but the Normal, the padding and
    the Normal's island-edge texels published per band); 3.2 the two independent rebuilds, each in
    its own processes and work directory, are byte-identical."""
    report, runs, _ = evidence
    assert validation_errors(report, Schema.COMPARISON_REPORT) == []
    if os.environ.get(REPORT_ENV):
        write_report(report, REPO_ROOT / os.environ[REPORT_ENV])
    assert not any(r.refused for r in runs), [r.refusal for r in runs]
    equality = report["equality_to_painter"]
    assert isinstance(equality, dict)
    assert equality["structural"] == []
    assert len(equality["maps"]) == 5 and all("padding" in m for m in equality["maps"]), equality
    assert equality["outcome"] == "pass", equality
    assert equality["exceptions_relied_on"] in ([], [EXC012]), equality["exceptions_relied_on"]
    repeatability = report["uzpainter_repeatability"]
    assert isinstance(repeatability, dict) and repeatability["status"] == "repeatable"


@_needs_the_sash
def test_sash_v5_saved_and_reopened_project_exports_the_first_maps(evidence: Evidence) -> None:
    """3.1's save/reopen: the first rebuild's project keeps one file and UUID from its first
    export through the save to the reopen in a fresh process, and exports again every file of its
    first export, byte for byte, in the measure mode."""
    _, runs, reopen = evidence
    assert not any(r.refused for r in runs), [r.refusal for r in runs]
    assert reopen is not None
    assert reopen.first, "the first export wrote no file"
    assert reopen.same_project, reopen
    assert reopen.refusal == "", reopen.refusal
    assert reopen.differing == [], reopen.differing
    assert reopen.equal


@_needs_the_sash
def test_sash_v5_round_through_typed_mcp_tools_with_python_disabled(
    painter: Path, evidence: Evidence, tmp_path: Path
) -> None:
    """The production round through typed tools against a supervisor without `--allow-python`;
    `run_python` is not listed, every call is typed, the round completes and its maps equal the
    Tier 1 run's byte for byte. The production `export` tool refuses the islanded set before
    writing (decisions 245, 259); while it does, this is an expected failure naming the refusal.
    The round's report is the measure mode's (below)."""
    assert GOLDEN is not None
    _, (tier1, _), _ = evidence
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OCIO", str(painter_ocio()))
        log = run_round(painter, tmp_path / "round", GOLDEN.manifest_path)
    report = round_report(log, tier1, GOLDEN.manifest_path, painter)
    assert report["python"] == {"allow_python": False, "run_python_listed": False}
    assert all(call["typed"] for call in report["calls"])
    if island_refusal(log):
        pytest.xfail(f"the production export refuses the Sash's UV islands: {log.refusal_reason}")
    assert report["outcome"] == "completed", report.get("refusal", report["calls"][-1])
    assert report["equal_to_tier1"] == "equal", report["maps"]


@_needs_the_sash
def test_sash_v5_round_through_typed_mcp_tools_closes_on_the_measure_export(
    painter: Path, evidence: Evidence, tmp_path: Path
) -> None:
    """2.5, 3.3 (decisions 398 §4, 399): the round through typed tools against a supervisor
    without `--allow-python`, `run_python` not listed and every call typed, sends no export; its
    saved project is exported by the diagnostic measure export in its own `run` process, its
    receipt checked (`mcp_round.measured_round`). The round completes and its maps equal the Tier
    1 run's, also the measure export, byte for byte. Not conformant: a measure-mode round."""
    assert GOLDEN is not None
    _, (tier1, _), _ = evidence
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OCIO", str(painter_ocio()))
        log = run_round(painter, tmp_path / "round", GOLDEN.manifest_path, diagnostic=True)
    report = round_report(log, tier1, GOLDEN.manifest_path, painter)
    if os.environ.get(ROUND_ENV):
        write_round_report(report, REPO_ROOT / os.environ[ROUND_ENV])
    assert report_problems(report) == []
    assert report["python"] == {"allow_python": False, "run_python_listed": False}
    assert all(call["typed"] for call in report["calls"])
    assert "export" not in [call["tool"] for call in report["calls"]]
    assert report["export_mode"] == "diagnostic_measure"
    assert report["outcome"] == "completed", report["calls"][-1]
    assert report["equal_to_tier1"] == "equal", report["maps"]


@_needs_the_sash
def test_sash_v5_rebuilt_from_its_dump_exports_byte_identical_files(
    painter: Path, tmp_path: Path
) -> None:
    """Gate G2's dump-and-rebuild on the Sash (the Tunic's pass criterion): the project built
    through the adapter and the one rebuilt from its recipe dump and its bundle's resources dump the
    same body, rebuild block and digest, and their diagnostic measure exports (decision 286; each
    receipt `non_conformant`, bypassing only decided refusals) are byte-identical, all five maps.
    No export may be refused. The report goes to `UZP_RECIPE_REBUILD_REPORT` when that is set."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OCIO", str(painter_ocio()))
        scenario = recipe.run(
            painter, tmp_path / "rebuild", diagnostic=True, golden_id=GOLDEN_ID, request=REQUEST
        )
    report, original, rebuilt = scenario.report, scenario.original, scenario.rebuilt
    assert validation_errors(report, Schema.RECIPE_REBUILD_REPORT) == []
    if os.environ.get(RECIPE_ENV):
        write_recipe_report(report, REPO_ROOT / os.environ[RECIPE_ENV])
    assert scenario.refusals == ()
    assert rebuilt["digest"] == original["digest"]
    assert rebuilt["recipe"] == original["recipe"]
    assert rebuilt["rebuild"] == original["rebuild"]
    assert report["equality"]["digests_equal"] is True
    files = report["original"]["export"]["files"]
    assert len(files) == 5
    assert report["rebuilt"]["export"]["files"] == files
    assert report["equality"]["files"] == "identical", report["equality"]
    assert report["equality"]["outcome"] == "pass", report["equality"]


def test_only_the_islanded_export_refusal_is_expected() -> None:
    """The round's expected failure is exactly the export's islanded refusal: the export, the
    `NotYetSupported` gap and a reason naming the islands and decision 245's or 259's refusal. Any
    other refused call, gap type or reason, and a completed or failed round, is not."""
    normal = (
        'the layer "n" reads the combined virtual normal on a texture set whose UV islands do not '
        "cover the whole tile: (owner: the Height outside the UV islands; decision 245)"
    )
    padding = (
        'the padding "infinite" on a texture set whose UV islands do not cover the whole tile is '
        "not exact (owner, decision 259)"
    )

    def refused(reason: str, **refusal: str) -> Round:
        log = Round(67, False, outcome="refused", refusal={**ISLAND_REFUSAL, **refusal})
        log.refusal_reason = reason
        return log

    assert island_refusal(refused(normal)) and island_refusal(refused(padding))
    assert not island_refusal(refused("a 4096 height-to-normal scaling is not recorded"))
    assert not island_refusal(refused(normal.replace("decision 245", "decision 999")))
    assert not island_refusal(refused(normal, tool="project_create"))
    assert not island_refusal(refused(normal, type="UVOutsideTile"))
    assert not island_refusal(refused(normal, error_code="call_failed"))
    for outcome in ("completed", "failed"):
        log = refused(normal)
        log.outcome = outcome
        assert not island_refusal(log)
