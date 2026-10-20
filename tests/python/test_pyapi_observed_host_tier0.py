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
- Texture states (decision 332, amending 297 §3.3), in `test_host_texture_states_equal_painter`:
  ADD and REMOVE dispatches stay in their step's event list and are compared exactly, in order
  with the other events; the UPDATE dispatches of the causative window (`UPDATE_WINDOWS`, s7-s8)
  are compared, both recordings, as the distinct (action, channel type) pairs of the whole
  window in the output `s7-s8/texture_updates`, since Painter attributes them asynchronously
  (s8 in r1, s7 in r2); an UPDATE outside the window stays in its list. Cache keys and texture
  ids are not claimed (`TEXTURE_IDS`). UzPainter emits no texture event until its observer lands:
  that test is an expected failure (`TEXTURE_GAP`), and passes unchanged once the events arrive.
  `test_host_probe_equals_painter` compares every other event of those lists exactly, without
  the `TextureStateEvent` dispatches, which only the texture test compares.
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
TEXTURE_GAP = (
    "release gap, decision 332, owner phase1.24_python-api-facade item 4.1: UzPainter emits no "
    "TextureStateEvent until its texture observer lands"
)

# Outputs that cannot equal Painter's, by probe: output key (`<output id>` for both recordings,
# `<condition> <output id>` for one) -> kind, reason and owner.
EXCLUDED: dict[str, dict[str, str]] = {
    "p22b-host-application": dict.fromkeys(
        ("s3/version", "s4/version_info", "s20/evaluate"), HOST_VERSION
    ),
    "p22b-host-events": {},
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
UPDATE = "UPDATE"
# Decision 332: the event outputs of each probe's causative window of an UPDATE.
UPDATE_WINDOWS: dict[str, tuple[str, ...]] = {"p22b-host-events": ("s7/events", "s8/events")}
# Fields of a texture event whose parity is not claimed (decisions 297 and 332).
TEXTURE_IDS = ("cache_key_argument", "stack_id_argument")
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


def window_output(probe: str) -> str:
    """The output id of a probe's UPDATE window: `s7-s8/texture_updates`."""
    steps = [output_id.split("/")[0] for output_id in UPDATE_WINDOWS[probe]]
    return f"{steps[0]}-{steps[-1]}/texture_updates"


def texture_events(
    events: list[Any], textures: bool, in_window: bool, window: set[tuple[Any, Any]]
) -> list[Any]:
    """One event list as the comparison reads it. Without `textures`, no texture dispatch.
    With it, every texture dispatch without its unclaimed ids, except the UPDATEs of an output in
    the window, whose (action, channel type) pairs go to `window`."""
    kept = []
    for e in events:
        if e.get("event") != TEXTURE_STATE:
            kept.append(e)
        elif not textures:
            continue
        elif in_window and e.get("action_argument") == UPDATE:
            window.add((e.get("action_argument"), e.get("channel_type_argument")))
        else:
            kept.append({k: v for k, v in e.items() if k not in TEXTURE_IDS})
    return kept


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
    probe: str, golden: dict[str, Any], replayed: dict[str, Any], run: Path, textures: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Copies of the golden and the replay with the rules of the module applied, each checked to
    still have a reason to exist; `textures` selects decision 332's texture comparison."""
    golden, replayed = copy.deepcopy(golden), copy.deepcopy(replayed)
    dispatched = stripped_shelves = viewer_lists = 0
    window_ids = UPDATE_WINDOWS.get(probe, ())
    for condition in CONDITIONS:
        ours = replayed[condition]["outputs"]
        theirs = outputs(golden, condition)
        painter_window: set[tuple[Any, Any]] = set()
        our_window: set[tuple[Any, Any]] = set()
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
                dispatched += sum(e.get("event") == TEXTURE_STATE for e in value)
                in_window = output_id in window_ids
                kept = texture_events(value, textures, in_window, painter_window)
                if output_id in ours:
                    mine = ours[output_id].get("value") or []
                    ours[output_id] = {
                        **ours[output_id],
                        "value": texture_events(mine, textures, in_window, our_window),
                    }
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
        if textures and window_ids:
            assert painter_window, f"{condition}: Painter dispatched no UPDATE in the window"
            output_id = window_output(probe)
            pairs = [list(pair) for pair in sorted(painter_window, key=repr)]
            theirs.append({"kind": "api_readback", "output_id": output_id, "value": pairs})
            ours[output_id] = {"value": [list(pair) for pair in sorted(our_window, key=repr)]}
    if probe == "p22b-host-events":
        assert dispatched > 0, "Painter dispatched no TextureStateEvent: drop the rule"
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
    """Item 4.1: the P22-B host golden is exact apart from the named exclusions, both
    recordings (texture events: `test_host_texture_states_equal_painter`)."""
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


@pytest.mark.xfail(reason=TEXTURE_GAP, strict=False)
def test_host_texture_states_equal_painter(facade: Run, tmp_path: Path) -> None:
    """Decision 332: the texture events of `p22b-host-events` equal Painter's, ADD and REMOVE
    in their step and the UPDATE pairs within their window, both recordings, with every other
    output exact as well."""
    probe = "p22b-host-events"
    replayed, golden, job = replay_observed(facade, probe, tmp_path)
    excluded = EXCLUDED[probe]
    expected, ours = comparable(probe, golden, replayed, tmp_path / "run", textures=True)
    differences = compare_observed(ours, expected, job, tmp_path, excluded)
    save_trace(f"facade-observed-textures/{probe}", golden, replayed, excluded, differences)
    assert replayed["cleanup_failures"] == [], replayed["cleanup_failures"]
    assert differences == [], "\n".join(differences)
