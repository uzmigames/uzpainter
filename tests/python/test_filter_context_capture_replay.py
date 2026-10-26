"""Private V2 comparison after materialized native import; never promotes capabilities."""

from __future__ import annotations

import json
import traceback
from contextlib import suppress
from pathlib import Path

import pytest

from tests.python.capability_trace import SOURCE
from tests.python.conftest import FACADE_PRELUDE, runner
from tools.parity import filter_context_replay as replay
from tools.parity.recorder.output import ensure_outside_repository


def test_materialized_filter_context_replays_independent_recordings(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    configured = replay.configured_path()
    if configured is None:
        pytest.skip("oracle_unavailable: private materialized Filter context not configured")
    work: Path | None = None
    failed = False
    try:
        work = ensure_outside_repository(tmp_path)
        plan = replay.prepare(configured)
        executable: Path = request.getfixturevalue("pyapi_runner")
        execute = runner(executable, work, FACADE_PRELUDE, private_diagnostics=work)
        envelope = execute(replay.build_script(plan, SOURCE))
        (work / "filter-context-runner.json").write_text(json.dumps(envelope), encoding="utf-8")
        replay.require(
            envelope.get("status") == "ok"
            and envelope.get("result")
            == {
                "status": "captured",
                "outputs": 6,
                "old_handles_refused": 3,
            },
            "F_REPLAY_EXECUTION",
        )
        report = replay.compare(plan, work / "filter-context-actual.json")
        (work / "filter-context-comparison.json").write_text(json.dumps(report), encoding="utf-8")
    except (Exception, pytest.skip.Exception):
        failed = True
        if work is not None:
            with suppress(OSError):
                (work / "filter-context-private-error.txt").write_text(
                    traceback.format_exc(), encoding="utf-8"
                )
    if failed:
        pytest.fail("F_REPLAY_FAILED: inspect private diagnostics", pytrace=False)
    print("Filter context: F 6/6; independent old 6/6; traced 6/6; stale refusals 3/3; unchanged")
