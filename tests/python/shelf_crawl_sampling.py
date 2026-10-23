"""Decision 359: compare the completed crawl, retaining its complete event evidence."""

from __future__ import annotations

import copy
from typing import Any

PROBE = "p22b-host-resources"
SHELF = "uzp_probe_host_shelf"
STEPS = (16, 17)


def comparison_contract(probe: str) -> dict[str, Any] | None:
    if probe != PROBE:
        return None
    return {
        "decision": "359",
        "metric": "one completed shelf crawl with exact events and non-crawl state",
        "scopes": [f"s{step}/states" for step in STEPS],
        "shelf": SHELF,
        "conditions": ["same_session", "after_save_reopen"],
        "allowed_sampling_paths": [[False], [True, False]],
        "raw_polling_trajectory": {
            "parity": "unclaimed",
            "reason": "completion can precede first poll",
        },
        "events_and_other_fields": "exact",
    }


def completed_states(states: Any, events: Any, step: int) -> Any:
    """Reject every trajectory outside the measured episode before collapsing its first poll."""
    assert isinstance(events, list), "crawl events must be a list"
    own = [event for event in events if event.get("shelf_name_argument") == SHELF]
    assert [event.get("event") for event in own] == [
        "ShelfCrawlingStarted",
        "ShelfCrawlingEnded",
    ], "one ordered Started/Ended pair is required"
    assert own[0].get("during_step") == step, "crawl must start during its call"
    assert "during_step" not in own[1], "crawl must end after its call"
    assert isinstance(states, list) and states, "crawl states must be nonempty"
    path = []
    other = []
    for state in states:
        assert isinstance(state, dict), "each crawl state must be an object"
        crawls = state.get("shelves_crawling")
        assert isinstance(crawls, dict) and set(crawls) == {SHELF}, "unexpected shelf state"
        value = crawls[SHELF]
        assert type(value) is bool, "crawl state must be boolean"
        path.append(value)
        other.append({key: value for key, value in state.items() if key != "shelves_crawling"})
    assert path in ([False], [True, False]), "unsupported crawl sampling trajectory"
    assert all(value == other[0] for value in other), "non-crawl state changed during sampling"
    return [copy.deepcopy(states[-1])]


def comparable_shelf(
    probe: str, golden: dict[str, Any], replayed: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected, ours = copy.deepcopy(golden), copy.deepcopy(replayed)
    if probe != PROBE:
        return expected, ours
    for recording in expected["recordings"]:
        condition = recording["condition"]
        outputs = {output["output_id"]: output for output in recording["outputs"]}
        for step in STEPS:
            states_key, events_key = f"s{step}/states", f"s{step}/events"
            for side in (outputs, ours[condition]["outputs"]):
                side[states_key]["value"] = completed_states(
                    side[states_key]["value"], side[events_key]["value"], step
                )
    return expected, ours
