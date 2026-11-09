"""The MCP-only round on the Wand v1 inputs, the stand-in for Sash v5 (phase2.9 item 2.5;
decisions 192, 260).

The waist-v5 round folder of the pilot (Sash v5, which replaced Belt v5) is gone from Assets3D
until the owner restores it, so the round tool (`mcp_round.py`) is exercised on the admitted Wand
v1 golden's pinned inputs: the same three-step pipeline round, the same export configuration. This
is evidence for the tool only, never for the pilot: item 2.5 closes on the Sash's own report
(`sash_v5/test_sash_v5.py`). It needs the UzmiGames
asset repository, the private store (the Wand's inputs resolve there by hash, decision 144) and
`zig`; hosted CI skips it with the reason. The rule that derives `equal_to_tier1` from the maps is
tested on its own and runs everywhere.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from adapters.assets3d.client import GPU_DEADLINE_ENV
from python.uzpainter_facade.bitmap_defaults import PAINTER_OCIO_CONFIG_SHA256
from tests.adapters.assets3d.wand import ASSETS3D, PAINTER_OCIO, REPO_ROOT
from tests.parity.tier1.mcp_round import round_report, run_round, run_tunic_current
from tests.parity.tier1.tunic_recipe import (
    GPU_DEADLINE_MS,
    RecipeMismatch,
    RecipeRound,
    run_tunic_recipe,
)
from tests.parity.tier1.wand_v1 import runner as wand_runner
from tools.parity.recorder.launcher import default_painter_exe
from tools.parity.schemas import Schema, validation_errors
from tools.parity.store.store import locate
from tools.parity.tier1.compare import CandidateRun, write_report
from tools.parity.tier1.mcp_round import equality, report_problems
from tools.parity.verdict import resolve_golden

_NEEDS_THE_WAND = [
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


def _needs_the_wand[T: Callable[..., None]](test: T) -> T:
    """`test` skipped, with the reason, where the Wand's inputs or its golden are absent."""
    for mark in _NEEDS_THE_WAND:
        test = mark(test)
    return test


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


def built_painter(tmp_path_factory: pytest.TempPathFactory, *options: str) -> Path:
    """`UzPainter.exe` of a fresh `zig build painter` install with `options`."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; UzPainter.exe cannot be built")
    prefix = tmp_path_factory.mktemp("painter")
    build = subprocess.run(
        [zig, "build", "painter", *options, "--prefix", str(prefix)],
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
def painter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`UzPainter.exe` of a fresh `zig build painter` install."""
    return built_painter(tmp_path_factory)


@pytest.fixture(scope="module")
def fast_painter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`UzPainter.exe` of a fresh `zig build painter -Doptimize=ReleaseFast` install, for the
    Tunic's 4096-px measure exports: a Debug export of the Wand's 2048-px maps already outlasts the
    adapter's 600 s per call (decision 223), as `wand_v1/test_wand_v1.py` builds it."""
    return built_painter(tmp_path_factory, "-Doptimize=ReleaseFast")


A, B = "a" * 64, "b" * 64


def _map(name: str, ours: str | None, tier1: str | None) -> dict[str, str | None]:
    return {"texture_set": "w", "map": name, "sha256": ours, "tier1_sha256": tier1}


@pytest.mark.parametrize(
    ("maps", "expected"),
    [
        ([_map("w_BaseColor", A, A), _map("w_Normal", B, B)], "equal"),
        ([_map("w_BaseColor", A, B)], "different"),
        ([_map("w_BaseColor", A, A), _map("w_Normal", B, None)], "different"),
        ([_map("w_BaseColor", A, A), _map("w_Normal", None, B)], "different"),
    ],
    ids=["same-bytes", "other-bytes", "extra-in-round", "extra-in-tier1"],
)
def test_both_runs_wrote_maps_so_equality_is_observed(
    maps: list[dict[str, Any]], expected: str
) -> None:
    """Both runs wrote maps: unequal map sets or bytes are an observed divergence, `different`,
    never `not_measured` (decision 192)."""
    assert equality("completed", maps) == expected


@pytest.mark.parametrize(
    ("outcome", "maps"),
    [
        ("completed", []),
        ("completed", [_map("w_BaseColor", A, None)]),
        ("completed", [_map("w_BaseColor", None, A)]),
        ("refused", []),
        ("refused", [_map("w_BaseColor", None, A)]),
    ],
    ids=["neither-wrote", "tier1-wrote-nothing", "round-wrote-nothing", "refused", "refused-tier1"],
)
def test_a_run_that_wrote_nothing_is_not_measured(outcome: str, maps: list[dict[str, Any]]) -> None:
    """Absence compares nothing: a run with no maps, or a round that did not complete, is
    `not_measured` (a refused round is never a pass)."""
    assert equality(outcome, maps) == "not_measured"


def _measure_mode_report() -> dict[str, Any]:
    """The published Sash round's report as a completed measure-mode round would be: its calls
    up to the save, no export call, and both runs' maps the same bytes."""
    path = REPO_ROOT / "parity/reports/phase2/sash-v5-mcp-round.json"
    report: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    report["calls"] = [call for call in report["calls"] if call["tool"] != "export"]
    report.pop("refusal", None)
    report["maps"] = [{**m, "sha256": m["tier1_sha256"]} for m in report["maps"]]
    measured = {"outcome": "completed", "export_mode": "diagnostic_measure"}
    return {**report, **measured, "equal_to_tier1": "equal"}


def test_a_measure_mode_round_sends_no_export_and_is_never_refused() -> None:
    """`export_mode: diagnostic_measure` (decisions 398 §4, 399): the round's maps come from the
    measure export of its saved project, so its call log holds no `export` call and it is never
    refused by one; a report without the mode is a production round, as historical ones are."""
    report = _measure_mode_report()
    assert report_problems(report) == []
    assert equality(report["outcome"], report["maps"]) == "equal"
    historical = {k: v for k, v in report.items() if k != "export_mode"}
    assert report_problems(historical) == []
    export = {**report["calls"][-1], "step": len(report["calls"]) + 1, "tool": "export"}
    with_export = {**report, "calls": [*report["calls"], export]}
    assert "export_mode: a measure-mode round sends no export call" in report_problems(with_export)
    assert report_problems({**report, "export_mode": "measure"})


@_needs_the_wand
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


TUNIC_CURRENT = "phase2/tier1/tunic-v10-current"


@pytest.mark.skipif(
    not (ASSETS3D / "AGENTS.md").is_file(),
    reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
)
@pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine")
@pytest.mark.skipif(
    resolve_golden(TUNIC_CURRENT) is None, reason=f"{TUNIC_CURRENT} is not admitted"
)
def test_tunic_current_round_checks_its_state_before_the_export(
    painter: Path, tmp_path: Path, record_property: Callable[[str, object], None]
) -> None:
    """The real Tunic current round through typed tools, as a state-check test: every state check
    after the sync and after the reopen passes before the one export, and a failed check raises
    before the export is sent. The export either writes or is refused before writing as an
    explicit capability refusal; which refusal fired is not proved here. The round's aggregate
    (hashes, calls, outcome, refusal) is recorded as the `tunic_current_round` property."""
    manifest = resolve_golden(TUNIC_CURRENT)
    assert manifest is not None
    log = run_tunic_current(painter, tmp_path / "round", manifest.manifest_path)
    record_property(
        "tunic_current_round",
        json.dumps(
            {
                "manifest_sha256": hashlib.sha256(manifest.manifest_path.read_bytes()).hexdigest(),
                "exe_sha256": hashlib.sha256(painter.read_bytes()).hexdigest(),
                "tools_listed": log.tools_listed,
                "run_python_listed": log.run_python_listed,
                "calls": log.calls,
                "outcome": log.outcome,
                "refusal": log.refusal,
            },
            sort_keys=True,
        ),
    )
    assert not log.run_python_listed
    tools = [call["tool"] for call in log.calls]
    assert tools[-1] == "export", log.calls
    assert all(call["outcome"] != "error" for call in log.calls[:-1]), log.calls
    assert tools.count("layer_list") == 2 and "project_open" in tools, tools
    if log.outcome == "refused":
        assert log.refusal is not None and log.refusal["tool"] == "export", log.refusal
    else:
        assert log.outcome == "completed", log.calls


@pytest.mark.skipif(
    not (ASSETS3D / "AGENTS.md").is_file(),
    reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
)
@pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine")
@pytest.mark.skipif(
    resolve_golden(TUNIC_CURRENT) is None, reason=f"{TUNIC_CURRENT} is not admitted"
)
def test_tunic_current_recipe_rebuilds_the_typed_round_from_its_dump(
    painter: Path, tmp_path: Path, record_property: Callable[[str, object], None]
) -> None:
    """The real Tunic dump-and-rebuild (`tunic_recipe.run_tunic_recipe`, phase2.10 item 2.4) on the
    admitted golden: the typed state round, its saved project reopened afresh, the bundle, the
    rebuild in a separate `run` process and the rebuilt project's checks, on this module's one
    build. It proves the flow, not recipe acceptance. The rebuild is the separate public-facade
    `run` process, never an MCP tool.

    Each of the three MCP sessions (the state round's, the original's and the rebuilt project's)
    lists its tools before any project call and is refused if `run_python` is among them; the
    test asserts all three lists left it out. Every state check passes or raises. The outcome
    must be `pass` (equal digests, identical files) or `export_refused` (equal digests, both
    exports refused alike before writing, with the same generic `capability_gap` refusal; which
    gap fired, decision 245 or 259 or another, is not claimed). `export_refused` counts only as
    success of the state and rebuild flow, never as parity acceptance; a refused step or a `fail`
    fails the test. The aggregate is recorded as the `tunic_current_recipe` property, even when a
    check raises: hashes, each session's `run_python_listed`, how far each side's state checks
    got, the dump digests, each export's status or refusal and the outcomes. When a check raises,
    no stage proof comes back, so each side's state is recorded as `unverified` (an earlier stage
    may have succeeded), and only the exception's class name is recorded, never its message. The
    raw error is kept privately in `tmp_path` and the test fails with the class name alone, with
    no traceback or exception context (`private_recipe`), so no private dump or API value reaches
    the pytest or JUnit output. An accepted outcome needs all three sessions' logs."""
    manifest = resolve_golden(TUNIC_CURRENT)
    assert manifest is not None
    aggregate: dict[str, Any] = {
        "manifest_sha256": hashlib.sha256(manifest.manifest_path.read_bytes()).hexdigest(),
        "exe_sha256": hashlib.sha256(painter.read_bytes()).hexdigest(),
    }
    result = private_recipe(
        lambda: run_tunic_recipe(painter, tmp_path / "recipe", manifest.manifest_path),
        tmp_path,
        aggregate,
        lambda value: record_property("tunic_current_recipe", json.dumps(value, sort_keys=True)),
    )
    # Every message below is the aggregate: hashes and outcomes, no private value.
    assert result.outcome in ("pass", "export_refused"), aggregate
    assert set(result.logs) == {"state", "original", "rebuilt"}, aggregate
    assert not any(log.run_python_listed for log in result.logs.values()), aggregate
    assert result.report is not None, aggregate
    equality = result.report["equality"]
    assert equality["digests_equal"], aggregate
    if result.outcome == "export_refused":  # the flow succeeded; never parity acceptance
        exports = [result.report[name]["export"] for name in ("original", "rebuilt")]
        assert equality["files"] == "not_exported", aggregate
        assert [e["status"] for e in exports] == ["refused", "refused"], aggregate
        assert exports[0]["refusal"] == exports[1]["refusal"], aggregate
        assert str(exports[0]["refusal"]).startswith("capability_gap:"), aggregate
    else:
        assert equality["files"] == "identical", aggregate


_NEEDS_THE_TUNIC = [
    pytest.mark.skipif(
        not (ASSETS3D / "AGENTS.md").is_file(),
        reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
    ),
    pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine"),
    pytest.mark.skipif(
        resolve_golden(TUNIC_CURRENT) is None, reason=f"{TUNIC_CURRENT} is not admitted"
    ),
]


def _needs_the_tunic[T: Callable[..., None]](test: T) -> T:
    """`test` skipped, with the reason, where the Tunic's inputs or its golden are absent."""
    for mark in _NEEDS_THE_TUNIC:
        test = mark(test)
    return test


# --- decision 398: the Tunic's Tier 1 under EXC-011, through the diagnostic measure export ------

REPORT_ENV = "UZP_TIER1_REPORT"  # repository-relative path of the report to write
# The only exception the Tunic's equality may rely on (decision 398; version 2, decision 401).
EXC011 = {"exception_id": "EXC-011", "version": 3}


def painter_ocio() -> Path:
    """Painter's substance configuration, which the manifest applies as `OCIO` and the native
    create checks by hash (`tests/adapters/assets3d/wand.py`): skipped where it is absent."""
    config = default_painter_exe().parent / PAINTER_OCIO
    if not config.is_file():
        pytest.skip(f"Painter's OCIO configuration is not at {config}")
    if hashlib.sha256(config.read_bytes()).hexdigest() != PAINTER_OCIO_CONFIG_SHA256:
        pytest.skip(f"{config} is not the pinned substance configuration")
    return config


TunicEvidence = tuple[
    dict[str, Any],
    tuple[CandidateRun, CandidateRun],
    wand_runner.Reopen | None,
]


@pytest.fixture(scope="module")
def tunic_tier1(fast_painter: Path, tmp_path_factory: pytest.TempPathFactory) -> TunicEvidence:
    """The Tunic current round's Tier 1 evidence through the Wand's runner (its native route):
    two rebuilds and the first one's save/reopen export, every export the diagnostic measure
    export (decisions 286, 398), from one run for both Tier 1 tests, under the manifest's `OCIO`,
    each `run` with the Tunic's GPU deadline (`tunic_recipe.GPU_DEADLINE_MS`)."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OCIO", str(painter_ocio()))
        patch.setenv(GPU_DEADLINE_ENV, str(GPU_DEADLINE_MS))
        return wand_runner.reopened_compared(
            fast_painter, tmp_path_factory.mktemp("tunic-tier1"), TUNIC_CURRENT, diagnostic=True
        )


@_needs_the_tunic
def test_tunic_current_tier1_maps_equal_painter_under_exc011(tunic_tier1: TunicEvidence) -> None:
    """Items 2.5 and 3.1: every exported map of the Tunic current round equals its golden under
    EXC-011 version 3 (decision 410, narrowing decision 401's version 2 back to decision 398's
    EXC-010 terms: covered texels exact on every map but the Normal, covered interior texels
    exact on the Normal too, the padding and the Normal's island-edge texels published per band);
    the two rebuilds, each in its own processes and work directory, are byte-identical.
    The report is written to `UZP_TIER1_REPORT` when that is set."""
    report, runs, _ = tunic_tier1
    assert validation_errors(report, Schema.COMPARISON_REPORT) == []
    if os.environ.get(REPORT_ENV):
        write_report(report, REPO_ROOT / os.environ[REPORT_ENV])
    assert not any(r.refused for r in runs), [r.refusal for r in runs]
    equality = report["equality_to_painter"]
    assert equality["structural"] == []
    assert len(equality["maps"]) == 5 and all("padding" in m for m in equality["maps"]), equality
    assert equality["outcome"] == "pass", equality
    assert equality["exceptions_relied_on"] in ([], [EXC011]), equality["exceptions_relied_on"]
    assert report["uzpainter_repeatability"]["status"] == "repeatable"


@_needs_the_tunic
def test_tunic_current_saved_and_reopened_project_exports_the_first_maps(
    tunic_tier1: TunicEvidence,
) -> None:
    """Item 3.1's save/reopen: the first rebuild's project keeps one file and UUID from its first
    export through the save to the reopen in a fresh process, and exports again every file of its
    first export, byte for byte, in the measure mode."""
    _, runs, reopen = tunic_tier1
    assert not any(r.refused for r in runs), [r.refusal for r in runs]
    assert reopen is not None
    assert reopen.first, "the first export wrote no file"
    assert reopen.same_project, reopen
    assert reopen.refusal == "", reopen.refusal
    assert reopen.differing == [], reopen.differing
    assert reopen.equal


@_needs_the_tunic
def test_tunic_current_recipe_rebuild_exports_identical_bytes_in_the_measure_mode(
    fast_painter: Path, tmp_path: Path, record_property: Callable[[str, object], None]
) -> None:
    """Items 2.4 and 3.4 (decision 398): the real Tunic dump-and-rebuild of
    `test_tunic_current_recipe_rebuilds_the_typed_round_from_its_dump`, its two projects exported
    by the diagnostic measure export (`tunic_recipe.measured_export`) instead of their sessions.
    Every state check of the three typed sessions passes (bindings, Height blends and
    `double_sided` read through freshly resolved handles, after the reopen and after the rebuilt
    project's save and reopen); the outcome must be `pass`: equal recipe digests and
    byte-identical exports. The aggregate is recorded as `tunic_current_recipe_measure`, with no
    private value, as the production test's."""
    manifest = resolve_golden(TUNIC_CURRENT)
    assert manifest is not None
    aggregate: dict[str, Any] = {
        "manifest_sha256": hashlib.sha256(manifest.manifest_path.read_bytes()).hexdigest(),
        "exe_sha256": hashlib.sha256(fast_painter.read_bytes()).hexdigest(),
    }
    result = private_recipe(
        lambda: run_tunic_recipe(
            fast_painter, tmp_path / "recipe", manifest.manifest_path, diagnostic=True
        ),
        tmp_path,
        aggregate,
        lambda value: record_property(
            "tunic_current_recipe_measure", json.dumps(value, sort_keys=True)
        ),
    )
    assert set(result.logs) == {"state", "original", "rebuilt"}, aggregate
    assert not any(log.run_python_listed for log in result.logs.values()), aggregate
    assert result.report is not None, aggregate
    assert result.report["equality"]["digests_equal"], aggregate
    assert result.outcome == "pass", aggregate
    assert result.report["equality"]["files"] == "identical", aggregate


PRIVATE_DIAGNOSTICS = "private-recipe-diagnostics.txt"


def private_recipe(
    run: Callable[[], RecipeRound],
    directory: Path,
    aggregate: dict[str, Any],
    record: Callable[[dict[str, Any]], None],
) -> RecipeRound:
    """`run()`'s result, its aggregate added to `aggregate` and recorded. A raised error is kept
    privately in `directory` (the test's `tmp_path`) and fails the test with its class name only,
    raised outside the except block with no traceback or exception context (the
    `tests/python/conftest.py` `_private_report` pattern): no stage proof comes back, so each
    side's state is `unverified`."""
    result: RecipeRound | None = None
    failure, diagnostic = "", ""
    try:
        result = run()
    except Exception as error:
        failure = type(error).__name__
        diagnostic = "".join(traceback.format_exception(error))
    if result is not None:
        aggregate.update(recipe_aggregate(result))
        record(aggregate)
        return result
    aggregate.update(
        outcome="raised",
        error=failure,
        state={"original": "unverified", "rebuilt": "unverified"},
    )
    record(aggregate)
    saved = True
    try:
        (directory / PRIVATE_DIAGNOSTICS).write_text(diagnostic, encoding="utf-8")
    except OSError:
        saved = False
    suffix = "details kept privately" if saved else "private diagnostic write failed"
    pytest.fail(f"the Tunic recipe raised {failure} ({suffix})", pytrace=False)


def test_a_raised_recipe_error_fails_with_its_class_only(tmp_path: Path) -> None:
    """A check that raises with a private value: the value is kept in the private file, and
    neither the failure, which has no traceback or context, nor the record carries it."""
    sentinel = "SENTINEL-private-dump-value-0123"

    def leaking() -> RecipeRound:
        raise RecipeMismatch(f"the dump holds {sentinel}")

    recorded: list[str] = []
    with pytest.raises(pytest.fail.Exception) as raised:
        private_recipe(leaking, tmp_path, {}, lambda value: recorded.append(json.dumps(value)))
    failure = raised.value
    assert str(failure) == "the Tunic recipe raised RecipeMismatch (details kept privately)"
    assert failure.pytrace is False
    assert failure.__context__ is None and failure.__cause__ is None
    assert sentinel not in str(failure) and sentinel not in "".join(recorded)
    assert json.loads(recorded[0])["state"] == {"original": "unverified", "rebuilt": "unverified"}
    assert sentinel in (tmp_path / PRIVATE_DIAGNOSTICS).read_text(encoding="utf-8")


def recipe_aggregate(result: RecipeRound) -> dict[str, Any]:
    """What the recipe test records of `result`: no dump content, file name or file hash."""
    document = result.report or {}
    sides = {name: document.get(name) or {} for name in ("original", "rebuilt")}
    return {
        "run_python_listed": {name: log.run_python_listed for name, log in result.logs.items()},
        "tools_listed": {name: log.tools_listed for name, log in result.logs.items()},
        # A returned result proves each stage it logged; a side without a log refused before it.
        "state": {
            "original": "checked" if "original" in result.logs else "not_reached",
            "rebuilt": "checked" if "rebuilt" in result.logs else "not_reached",
        },
        "digests": {name: side.get("recipe_digest") for name, side in sides.items()},
        "digests_equal": (document.get("equality") or {}).get("digests_equal"),
        "exports": {
            name: {
                "status": (side.get("export") or {}).get("status"),
                "refusal": (side.get("export") or {}).get("refusal"),
            }
            for name, side in sides.items()
        },
        "outcome": result.outcome,
        "report_outcome": (document.get("equality") or {}).get("outcome"),
        "refusal": (result.refusal or {}).get("type"),
    }
