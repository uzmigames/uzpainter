"""Compared replays of the four P22-B host goldens (task phase1.24_python-api-facade item 4.1;
decision 297; local run on the owner's machine, decision 028).

`p22b-host-application`, `p22b-host-events`, `p22b-host-resources` and `p22b-host-plugins` run
through the facade with the recorder's own Painter-side code (`observed_replay.replay_observed`).
Every output of both recordings is compared field by field with the golden read from the private
store at run time (`compare_observed`). No Painter value is in this file.

`comparable` applies these named rules to copies of the golden and the replay, and checks that
each rule still has a reason to exist:

- `.painter_lock`: only the suffix of the project's lock is mapped to UzPainter's `.lock`
  (decision 319 §9a). The lock's presence, base name and phase stay compared.
- Texture states (decision 297 §3.3): each event list's `TextureStateEvent` dispatches are
  compared as the distinct (action, channel type) pairs of the step, in a sibling output
  `<output id>/texture_states`; the other events keep their order and states and stay
  compared exactly. UzPainter emits no `TextureStateEvent` yet, a release gap
  (`TEXTURE_STATES`): no `TextureStateEventAction` member gets credit from these outputs.
- Shelf crawls of shelves the run did not add are left out of the crawl events. Painter's
  installed and user shelves are Adobe content that UzPainter never ships (decision 006, as
  `phase1-shelves`).
- `list_project_resources`: only Painter's viewer defaults, its `open-pbr` shader and
  `panorama` environment (Adobe content, decision 006), are left out, both asserted present;
  every other entry stays compared, so an unused import listed by UzPainter would fail.
- Resource contexts inside an error message are renumbered from each side's first project, as
  `normalised` does for every `context` field (decision 107). A staged input's path inside an
  error message is compared relative to the run's root (the recorder's `inputs/` folder).

The outputs that cannot equal Painter's are in `EXCLUDED`, with their kind and owner; each must
be recorded in the golden and still differ.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest

from tests.python.conftest import Run
from tests.python.observed_replay import (
    check_observed_trace,
    compare_observed,
    observed_symbols,
    replay_observed,
    save_trace,
)
from tests.python.test_pyapi_facade_tier0 import CONDITIONS, contexts, golden_outputs, normalised

HOST_VERSION = (
    "host difference (decision 330): UzPainter reports its own version, never Painter's; no "
    "parity credit"
)
TEXTURE_STATES = (
    "release gap: UzPainter emits no TextureStateEvent (emission owner phase2.3_realtime-preview "
    "per decision 297; an open seam of phase1.24_python-api-facade item 4.1, decision 330); "
    "compared as distinct (action, channel type) pairs (decision 297 §3.3)"
)

# Outputs that cannot equal Painter's, by probe: output key (`<output id>` for both recordings,
# `<condition> <output id>` for one) -> kind, reason and owner.
EXCLUDED: dict[str, dict[str, str]] = {
    "p22b-host-application": dict.fromkeys(
        ("s3/version", "s4/version_info", "s20/evaluate"), HOST_VERSION
    ),
    "p22b-host-events": {
        **dict.fromkeys(("s20/events/texture_states", "s21/events/texture_states"), TEXTURE_STATES),
        "same_session s8/events/texture_states": TEXTURE_STATES,
        # Painter's UPDATE lands one step earlier in its second recording (decision 330).
        "after_save_reopen s7/events/texture_states": TEXTURE_STATES,
        "after_save_reopen start/events/texture_states": TEXTURE_STATES,
    },
    "p22b-host-plugins": {},
    "p22b-host-resources": {
        "s5/import_project_resource": (
            "refused: a COLOR_LUT import raises UnsupportedInUzPainter before any change, as the "
            "colour LUT is pinned to none by the fixed render pipeline (decision 038)"
        ),
        "s15/get_environment_resource": (
            "host content, permanent (decisions 006 and 038): Painter's default environment is "
            "its own Adobe panorama; a UzPainter project has none until a script sets one"
        ),
        "s23/reload_modified_resources_async": (
            "release gap: shelf resources (phase3.3_procedural-families). A ShelvesListFilter "
            "reload has no UzPainter resource to check, so it ends before the call returns "
            "(running_after_call); its events stay compared"
        ),
        "after_save_reopen s20/events": (
            "order unproven, owner phase1.24_python-api-facade item 4.1: the two reloads of one "
            "content (`checker`, `checker-reload`) equal Painter's as a set (`UNORDERED`), but "
            "the one recording that reloads two resources at once cannot settle their order"
        ),
    },
}
# Excluded event outputs whose events must still equal Painter's apart from the order of each
# `ReloadResourcesEnded`'s reloaded resources.
UNORDERED: dict[str, list[str]] = {"p22b-host-resources": ["after_save_reopen s20/events"]}


PAINTER_LOCK, LOCK = ".painter_lock", ".lock"
VIEWER_DEFAULTS = {("viewer", "open-pbr"), ("viewer", "panorama")}
TEXTURE_STATE = "TextureStateEvent"
SHELF_EVENTS = ("ShelfCrawlingStarted", "ShelfCrawlingEnded")
INCOMPATIBLE = re.compile(r"^Resource '(?P<root>.+)/inputs/(?P<file>[^/']+)' is incompatible")
RESOURCE_CONTEXT = re.compile(r"resource://project(\d+)/")


def outputs(golden: dict[str, Any], condition: str) -> list[dict[str, Any]]:
    recording = next(r for r in golden["recordings"] if r["condition"] == condition)
    found: list[dict[str, Any]] = recording["outputs"]
    return found


def base_context(values: Any) -> int:
    found: set[int] = set()
    contexts(values, found)
    return min(found) if found else 0


def renumbered(message: str, shift: int) -> str:
    """The resource contexts of a message, renumbered by `shift` (decision 107)."""

    def context(match: re.Match[str]) -> str:
        return f"resource://project{int(match.group(1)) + shift}/"

    return RESOURCE_CONTEXT.sub(context, message)


def map_lock(files: list[Any]) -> list[Any]:
    """Decision 319 §9a: the project lock's suffix only; its base must be a listed file."""
    mapped = []
    for name in files:
        if isinstance(name, str) and name.endswith(PAINTER_LOCK):
            base = name.removesuffix(PAINTER_LOCK)
            assert base in files, f"lock {name} names no project file"
            name = base + LOCK
        mapped.append(name)
    return mapped


def texture_states(events: list[Any]) -> tuple[list[Any], list[list[Any]]]:
    """The events without their `TextureStateEvent` dispatches, and the distinct (action, channel
    type) pairs of those dispatches (decision 297 §3.3)."""
    kept = [e for e in events if e.get("event") != TEXTURE_STATE]
    pairs = {
        (e.get("action_argument"), e.get("channel_type_argument"))
        for e in events
        if e.get("event") == TEXTURE_STATE
    }
    return kept, [list(pair) for pair in sorted(pairs, key=repr)]


def without_viewer_defaults(listed: list[Any]) -> list[Any]:
    """A `list_project_resources` readback without Painter's two viewer defaults, which must both
    be in it (decision 006)."""
    found = {
        (e["resource"]["context"], e["resource"]["name"])
        for e in listed
        if isinstance(e, dict) and isinstance(e.get("resource"), dict)
    }
    assert found >= VIEWER_DEFAULTS, f"Painter's viewer defaults are not both listed: {found}"
    return [
        e
        for e in listed
        if (e["resource"]["context"], e["resource"]["name"]) not in VIEWER_DEFAULTS
    ]


def comparable(
    probe: str, golden: dict[str, Any], replayed: dict[str, Any], run: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Copies of the golden and the replay with the rules of the module applied, each checked to
    still have a reason to exist."""
    golden, replayed = copy.deepcopy(golden), copy.deepcopy(replayed)
    split = stripped_shelves = viewer_lists = 0
    for condition in CONDITIONS:
        ours = replayed[condition]["outputs"]
        theirs = outputs(golden, condition)
        added = {
            o["value"]["shelf"]
            for o in theirs
            if o["output_id"].endswith("/add") and isinstance(o.get("value"), dict)
        }
        shift = base_context(ours) - base_context({o["output_id"]: o.get("value") for o in theirs})
        for output in list(theirs):
            output_id, value = output["output_id"], output.get("value")
            if output_id.endswith("/files") and isinstance(value, list):
                output["value"] = map_lock(value)
            if output_id.endswith("/list_project_resources") and isinstance(value, list):
                output["value"] = without_viewer_defaults(value)
                viewer_lists += 1
            if output_id.endswith("/events") and isinstance(value, list):
                kept, pairs = texture_states(value)
                mine_kept, mine_pairs = texture_states(ours.get(output_id, {}).get("value") or [])
                if pairs or mine_pairs:
                    split += 1
                    sibling = f"{output_id}/texture_states"
                    theirs.append({"kind": "api_readback", "output_id": sibling, "value": pairs})
                    ours[sibling] = {"value": mine_pairs}
                    ours[output_id] = {**ours[output_id], "value": mine_kept}
                if added:
                    foreign = [
                        e
                        for e in kept
                        if e.get("event") in SHELF_EVENTS
                        and e.get("shelf_name_argument") not in added
                    ]
                    stripped_shelves += len(foreign)
                    kept = [e for e in kept if all(e is not f for f in foreign)]
                output["value"] = kept
            raised = output.get("raised")
            if isinstance(raised, dict) and isinstance(raised.get("message"), str):
                message = renumbered(raised["message"], shift)
                incompatible = INCOMPATIBLE.match(message)
                if incompatible is not None:
                    start, end = incompatible.span("root")
                    message = message[:start] + run.as_posix() + message[end:]
                raised["message"] = message
    if probe == "p22b-host-events":
        assert split > 0, "no step dispatched a TextureStateEvent: drop the rule"
    if probe == "p22b-host-resources":
        assert stripped_shelves > 0, "Painter crawled no shelf of its own: drop the rule"
        assert viewer_lists > 0, "Painter listed no project resources: drop the rule"
    return golden, replayed


def without_reload_order(events: list[Any]) -> list[Any]:
    """The events with each `ReloadResourcesEnded`'s reloaded resources sorted."""
    return [
        {**e, "reloaded_resources_argument": sorted(e["reloaded_resources_argument"], key=repr)}
        if "reloaded_resources_argument" in e
        else e
        for e in events
    ]


def unordered_differences(probe: str, ours: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """`UNORDERED` outputs that differ in more than the order of their reloaded resources."""
    differences = []
    for key in UNORDERED.get(probe, []):
        condition, output_id = key.split(" ")
        mine = normalised(ours[condition]["outputs"])[output_id]["value"]
        painter = golden_outputs(expected)[condition][output_id]["value"]
        if without_reload_order(mine) != without_reload_order(painter):
            differences.append(f"{key} differs beyond the reload order: {mine!r} != {painter!r}")
    return differences


@pytest.mark.parametrize("probe", sorted(EXCLUDED))
def test_host_probe_equals_painter(facade: Run, tmp_path: Path, probe: str) -> None:
    """Item 4.1: the P22-B host golden is exact apart from the named exclusions and the
    blocked outputs, both recordings."""
    replayed, golden, job = replay_observed(facade, probe, tmp_path)
    excluded = EXCLUDED[probe]
    expected, ours = comparable(probe, golden, replayed, tmp_path / "run")
    differences = compare_observed(ours, expected, job, tmp_path, excluded)
    differences += unordered_differences(probe, ours, expected)
    save_trace(f"facade-observed/{probe}", golden, replayed, excluded, differences)
    assert replayed["cleanup_failures"] == [], replayed["cleanup_failures"]
    assert differences == [], "\n".join(differences)
    symbols = observed_symbols(replayed, golden, excluded)
    check_observed_trace(f"facade-observed/{probe}", golden["golden_id"], symbols)
