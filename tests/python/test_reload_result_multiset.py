"""Decision 338 mutation tests use authored records, never Painter values."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.python.observed_replay import save_trace
from tests.python.reload_result_multiset import (
    SCOPES,
    comparable_reload,
    compare_every_recording,
    comparison_contract,
    reload_events,
)

PROBE = "p22b-reload-order-zam-all-origins"


def events() -> list[dict[str, Any]]:
    def resource(name: str, version: str) -> dict[str, Any]:
        return {"resource": {"context": "project0", "name": name, "version": version}}

    return [
        {"event": "ReloadResourcesStarted", "filter_argument": "ProjectFilter"},
        {
            "event": "ReloadResourcesEnded",
            "filter_argument": "ProjectFilter",
            "resource_errors_argument": [],
            "reloaded_resources_argument": [
                {"old": resource(name, "old.image"), "new": resource(name, "new.image")}
                for name in ("first", "second")
            ],
        },
    ]


def semantic(value: Any) -> Any:
    return reload_events(PROBE, "same_session", "s8/events", value)


def test_internal_permutation_only_passes_without_mutating_raw() -> None:
    original = events()
    changed = copy.deepcopy(original)
    changed[1]["reloaded_resources_argument"].reverse()
    saved = copy.deepcopy(changed)
    assert changed != original
    assert semantic(changed) == semantic(original)
    assert changed == saved


@pytest.mark.parametrize(
    ("probe", "condition", "output"),
    [
        (probe, condition, output)
        for probe, scopes in SCOPES.items()
        for condition, output in scopes
    ],
)
def test_every_declared_scope_accepts_only_internal_permutation(
    probe: str, condition: str, output: str
) -> None:
    original = events()
    changed = copy.deepcopy(original)
    changed[1]["reloaded_resources_argument"].reverse()
    assert reload_events(probe, condition, output, changed) == reload_events(
        probe, condition, output, original
    )


@pytest.mark.parametrize("side", ["old", "new"])
@pytest.mark.parametrize("field", ["name", "version", "context"])
def test_every_resource_field_remains_exact(side: str, field: str) -> None:
    original = events()
    changed = copy.deepcopy(original)
    changed[1]["reloaded_resources_argument"][0][side]["resource"][field] = "changed"
    assert semantic(changed) != semantic(original)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "swap-old-new",
        "errors",
        "filter",
        "outer-order",
        "extra-field",
        "missing-field",
        "wrong-event",
    ],
)
def test_structural_or_other_event_change_fails(mutation: str) -> None:
    original = events()
    changed = copy.deepcopy(original)
    result = changed[1]["reloaded_resources_argument"]
    if mutation == "missing":
        result.pop()
    elif mutation == "duplicate":
        result.append(copy.deepcopy(result[0]))
    elif mutation == "swap-old-new":
        result[0]["old"], result[0]["new"] = result[0]["new"], result[0]["old"]
    elif mutation == "errors":
        changed[1]["resource_errors_argument"] = [{"message": "failed"}]
    elif mutation == "filter":
        changed[1]["filter_argument"] = "SessionFilter"
    elif mutation == "outer-order":
        changed.reverse()
    elif mutation == "extra-field":
        result[0]["unexpected"] = True
    elif mutation == "missing-field":
        del result[0]["new"]
    else:
        changed[1]["event"] = "OtherEvent"
    assert semantic(changed) != semantic(original)


@pytest.mark.parametrize(
    ("probe", "condition", "output"),
    [
        (PROBE, "same_session", "s9/events"),
        ("other", "same_session", "s8/events"),
        ("p22b-host-resources", "same_session", "s20/events"),
    ],
)
def test_unmeasured_scopes_keep_order(probe: str, condition: str, output: str) -> None:
    original = events()
    changed = copy.deepcopy(original)
    changed[1]["reloaded_resources_argument"].reverse()
    assert reload_events(probe, condition, output, changed) != original


def test_all_six_recordings_are_compared_including_last_repeat_failure() -> None:
    recordings = [
        {"session_id": str(session), "condition": condition, "value": session}
        for session in range(3)
        for condition in ("same_session", "after_save_reopen")
    ]
    visited = []

    def compare(golden: dict[str, Any]) -> list[str]:
        visited.extend(golden["recordings"])
        return ["last repeat differs"] if golden["recordings"][0]["value"] == 2 else []

    assert compare_every_recording({"recordings": recordings}, compare) == [
        "session 2: last repeat differs"
    ]
    assert visited == recordings


def test_missing_condition_is_not_silently_skipped() -> None:
    with pytest.raises(ValueError, match="one recording of each condition"):
        compare_every_recording(
            {"recordings": [{"session_id": "one", "condition": "same_session"}]}, lambda _: []
        )


@pytest.mark.parametrize("differences", [[], ["changed old resource version"]])
def test_semantic_trace_never_claims_raw_exactness_and_preserves_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, differences: list[str]
) -> None:
    monkeypatch.setenv("UZP_OBSERVED_TRACE_DIR", str(tmp_path))
    raw = events()
    raw[1]["reloaded_resources_argument"].reverse()
    golden = {
        "golden_id": f"tier0/api-probes/{PROBE}",
        "recordings": [
            {
                "condition": condition,
                "outputs": [{"output_id": "s8/events", "kind": "api_readback", "value": raw}],
            }
            for condition in ("same_session", "after_save_reopen")
        ],
    }
    replayed = {
        condition: {"outputs": {"s8/events": {"value": raw}}}
        for condition in ("same_session", "after_save_reopen")
    }
    replayed["trace"] = {}
    before = copy.deepcopy((golden, replayed))
    expected, ours = comparable_reload(PROBE, golden, replayed)
    assert expected != golden and ours != replayed
    contract = comparison_contract(PROBE)
    save_trace("authored/reload", golden, replayed, {}, differences, comparison_contract=contract)
    trace = json.loads((tmp_path / "authored__reload.trace.json").read_text())
    assert trace["exact_apart_from_exclusions"] is False
    assert trace["comparison_passed"] is (not differences)
    assert trace["differences"] == differences
    assert trace["comparison_contract"] == contract
    assert trace["comparison_contract"]["raw_reload_result_order"] == {
        "parity": "unclaimed",
        "oracle_stability": "fresh-process-unstable",
    }
    assert (golden, replayed) == before


@pytest.mark.parametrize("differences", [[], ["different"]])
def test_ordinary_trace_keeps_existing_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, differences: list[str]
) -> None:
    monkeypatch.setenv("UZP_OBSERVED_TRACE_DIR", str(tmp_path))
    save_trace(
        "ordinary", {"golden_id": "authored", "recordings": []}, {"trace": {}}, {}, differences
    )
    trace = json.loads((tmp_path / "ordinary.trace.json").read_text())
    assert trace == {
        "replay": "ordinary",
        "golden": "authored",
        "exact_apart_from_exclusions": not differences,
        "differences": differences,
        "excluded": {},
        "symbols": [],
        "by_output": {},
    }
    assert comparison_contract("unrelated-probe") is None
