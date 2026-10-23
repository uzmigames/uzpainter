"""Sampling equality must not erase an invalid or incomplete crawl episode."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from tests.python.shelf_crawl_sampling import (
    PROBE,
    SHELF,
    comparable_shelf,
    comparison_contract,
    completed_states,
)


def states(path: list[bool]) -> list[dict[str, Any]]:
    return [{"busy": False, "is_open": True, "shelves_crawling": {SHELF: value}} for value in path]


def events(step: int) -> list[dict[str, Any]]:
    return [
        {
            "event": "ShelfCrawlingStarted",
            "shelf_name_argument": SHELF,
            "during_step": step,
            "busy": False,
        },
        {"event": "ShelfCrawlingEnded", "shelf_name_argument": SHELF, "busy": False},
    ]


def evidence(path: list[bool]) -> dict[str, Any]:
    return {
        key: {"value": value}
        for step in (16, 17)
        for key, value in (
            (f"s{step}/states", states(path)),
            (f"s{step}/events", events(step)),
        )
    }


@pytest.mark.parametrize("expected,actual", [([False], [True, False]), ([True, False], [False])])
def test_accepts_both_directions_without_changing_raw_evidence(
    expected: list[bool], actual: list[bool]
) -> None:
    golden = {
        "recordings": [
            {
                "condition": "same_session",
                "outputs": [
                    {"output_id": key, **value} for key, value in evidence(expected).items()
                ],
            }
        ]
    }
    replay = {"same_session": {"outputs": evidence(actual)}}
    original = copy.deepcopy((golden, replay))
    left, right = comparable_shelf(PROBE, golden, replay)
    assert {o["output_id"]: o["value"] for o in left["recordings"][0]["outputs"]} == {
        key: value["value"] for key, value in right["same_session"]["outputs"].items()
    }
    assert (golden, replay) == original


@pytest.mark.parametrize(
    "path", [[], [True], [False, True], [True, False, True, False], [False, False]]
)
def test_rejects_other_paths(path: list[bool]) -> None:
    with pytest.raises(AssertionError):
        completed_states(states(path), events(16), 16)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_start",
        "missing_end",
        "reverse",
        "duplicate",
        "wrong_shelf",
        "wrong_step",
        "end_during_call",
    ],
)
def test_rejects_invalid_events(mutation: str) -> None:
    value = events(16)
    if mutation == "missing_start":
        value.pop(0)
    elif mutation == "missing_end":
        value.pop()
    elif mutation == "reverse":
        value.reverse()
    elif mutation == "duplicate":
        value.extend(copy.deepcopy(value))
    elif mutation == "wrong_shelf":
        value[0]["shelf_name_argument"] = "other"
    elif mutation == "wrong_step":
        value[0]["during_step"] = 17
    else:
        value[1]["during_step"] = 16
    with pytest.raises(AssertionError):
        completed_states(states([False]), value, 16)


@pytest.mark.parametrize("mutation", ["busy", "wrong_shelf", "extra_shelf", "non_boolean"])
def test_rejects_invalid_states(mutation: str) -> None:
    value = states([True, False])
    if mutation == "busy":
        value[0]["busy"] = True
    elif mutation == "wrong_shelf":
        value[0]["shelves_crawling"] = {"other": True}
    elif mutation == "extra_shelf":
        value[0]["shelves_crawling"]["other"] = False
    else:
        value[0]["shelves_crawling"][SHELF] = 1
    with pytest.raises(AssertionError):
        completed_states(value, events(16), 16)


def test_unrelated_probe_is_unchanged_and_contract_is_not_raw_exactness() -> None:
    golden, replay = {"unchanged": True}, {"other": False}
    assert comparable_shelf("other", golden, replay) == (golden, replay)
    assert comparison_contract("other") is None
    contract = comparison_contract(PROBE)
    assert contract is not None
    assert contract["raw_polling_trajectory"]["parity"] == "unclaimed"


def test_event_payloads_and_other_outputs_remain_exact() -> None:
    original = evidence([True, False])
    golden = {
        "recordings": [
            {
                "condition": "same_session",
                "outputs": [
                    {"output_id": key, **copy.deepcopy(value)} for key, value in original.items()
                ],
            }
        ]
    }
    replay = {"same_session": {"outputs": copy.deepcopy(original)}}
    replay["same_session"]["outputs"]["s16/events"]["value"][0]["busy"] = True
    left, right = comparable_shelf(PROBE, golden, replay)
    preserved = next(o for o in left["recordings"][0]["outputs"] if o["output_id"] == "s16/events")
    assert preserved["value"] != right["same_session"]["outputs"]["s16/events"]["value"]
