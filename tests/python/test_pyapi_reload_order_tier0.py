"""Decision 338: compare complete reload results against every admitted repetition."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.python.conftest import Run
from tests.python.observed_replay import compare_observed, replay_observed, save_trace
from tests.python.reload_result_multiset import (
    comparable_reload,
    compare_every_recording,
    comparison_contract,
    write_raw_replay,
)


@pytest.mark.parametrize("order", ["zam", "mza"])
def test_reload_results_equal_every_painter_recording(
    facade: Run, tmp_path: Path, order: str
) -> None:
    probe = f"p22b-reload-order-{order}-all-origins"
    replayed, golden, job = replay_observed(facade, probe, tmp_path)
    write_raw_replay(tmp_path, replayed)
    assert len(golden["recordings"]) == 6
    assert len({r["session_id"] for r in golden["recordings"]}) == 3
    expected, ours = comparable_reload(probe, golden, replayed)
    differences = compare_every_recording(
        expected, lambda sample: compare_observed(ours, sample, job, tmp_path, {})
    )
    save_trace(
        f"facade-observed/{probe}",
        golden,
        replayed,
        {},
        differences,
        comparison_contract=comparison_contract(probe),
    )
    assert replayed["cleanup_failures"] == []
    assert differences == [], "\n".join(differences)


@pytest.mark.parametrize("order", ["zam", "mza"])
def test_independent_alias_origin_equals_every_painter_recording(
    facade: Run, tmp_path: Path, order: str
) -> None:
    probe = f"p22b-reload-order-{order}"
    replayed, golden, job = replay_observed(facade, probe, tmp_path)
    write_raw_replay(tmp_path, replayed)
    assert len(golden["recordings"]) == 6
    assert len({r["session_id"] for r in golden["recordings"]}) == 3
    differences = compare_every_recording(
        golden, lambda sample: compare_observed(replayed, sample, job, tmp_path, {})
    )
    save_trace(f"facade-observed/{probe}", golden, replayed, {}, differences)
    assert replayed["cleanup_failures"] == []
    assert differences == [], "\n".join(differences)
