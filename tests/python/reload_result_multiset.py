"""Decision 338: exact reload-result multisets in explicitly measured event outputs."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.parity.recorder.output import ensure_outside_repository

SCOPES = {
    "p22b-host-resources": {("after_save_reopen", "s20/events")},
    **{
        f"p22b-reload-order-{order}-all-origins": {
            (condition, output)
            for condition in ("same_session", "after_save_reopen")
            for output in ("s8/events", "s11/events")
        }
        for order in ("zam", "mza")
    },
}


def comparison_contract(probe: str) -> dict[str, Any] | None:
    """Describe semantic equality without promoting unstable raw order to exact parity."""
    scopes = SCOPES.get(probe)
    if scopes is None:
        return None
    return {
        "decision": "338",
        "metric": "complete ReloadedResourceResult multiset; duplicates preserved",
        "scopes": [
            {"condition": condition, "output_id": output} for condition, output in sorted(scopes)
        ],
        "raw_reload_result_order": {
            "parity": "unclaimed",
            "oracle_stability": "fresh-process-unstable",
        },
        "outer_event_order_and_other_fields": "exact",
    }


def write_raw_replay(directory: Path, replayed: dict[str, Any]) -> Path:
    """Keep unnormalized candidate evidence outside the repository beside the replay work."""
    path = ensure_outside_repository(directory) / "replayed.json"
    path.write_text(json.dumps(replayed, indent=2) + "\n", encoding="utf-8")
    return path


def reload_events(probe: str, condition: str, output_id: str, value: Any) -> Any:
    """Sort only complete results; retain duplicates, outer event order and every other field."""
    result = copy.deepcopy(value)
    if (condition, output_id) not in SCOPES.get(probe, set()):
        return result
    if not isinstance(result, list):
        return result
    for event in result:
        if isinstance(event, dict) and event.get("event") == "ReloadResourcesEnded":
            values = event.get("reloaded_resources_argument")
            if isinstance(values, list):
                event["reloaded_resources_argument"] = sorted(
                    values, key=lambda item: json.dumps(item, sort_keys=True)
                )
    return result


def comparable_reload(
    probe: str, golden: dict[str, Any], replayed: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Copy raw evidence before applying the narrow semantic comparison contract."""
    expected, ours = copy.deepcopy(golden), copy.deepcopy(replayed)
    for recording in expected["recordings"]:
        condition = recording["condition"]
        for output in recording["outputs"]:
            if "value" in output:
                output["value"] = reload_events(
                    probe, condition, output["output_id"], output["value"]
                )
    for condition in ("same_session", "after_save_reopen"):
        for output_id, output in ours[condition]["outputs"].items():
            if "value" in output:
                output["value"] = reload_events(probe, condition, output_id, output["value"])
    return expected, ours


def compare_every_recording(
    golden: dict[str, Any], compare: Callable[[dict[str, Any]], list[str]]
) -> list[str]:
    """Call the existing two-condition comparator once per session, losing no repetitions."""
    sessions: dict[str, list[dict[str, Any]]] = {}
    for recording in golden["recordings"]:
        sessions.setdefault(recording["session_id"], []).append(recording)
    differences: list[str] = []
    for session, recordings in sessions.items():
        conditions = [recording["condition"] for recording in recordings]
        if sorted(conditions) != ["after_save_reopen", "same_session"]:
            raise ValueError(f"{session}: expected one recording of each condition: {conditions}")
        sample = {**golden, "recordings": recordings}
        differences.extend(f"session {session}: {difference}" for difference in compare(sample))
    return differences
