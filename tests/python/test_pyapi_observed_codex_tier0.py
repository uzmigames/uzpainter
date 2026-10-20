"""Recorded create/open timing and loss of unsaved edits (P21-F and P21-G)."""

from __future__ import annotations

import copy
from pathlib import Path

from tests.python.capability_trace import exercised
from tests.python.conftest import Run
from tests.python.observed_replay import (
    check_observed_trace,
    compare_observed,
    observed_symbols,
    replay_observed,
    save_trace,
)
from tests.python.test_pyapi_facade_tier0 import golden_record
from tests.python.test_pyapi_lifecycle_tier0 import run, stage, step_payload

TIMED_LIFECYCLE = """
import time


def phase(name, action, done):
    TRACE["mark"]("bookkeeping")
    call("events_take")
    TRACE["mark"](name + "/events")
    action()
    states = []

    def note():
        state = call("state")
        entry = {key: state[key] for key in ("is_open", "in_edition", "busy")}
        if not states or states[-1] != entry:
            states.append(entry)
        return state

    deadline = time.monotonic() + 120
    while not done(note()):
        if time.monotonic() > deadline:
            raise RuntimeError(name + " timed out")
        time.sleep(0.02)
    for _ in range(3):
        time.sleep(0.02)
        note()
    return {name + "/events": call("events_take")["events"], name + "/states": states}


def ready(state):
    return state["is_open"] and state["in_edition"] and not state["busy"]


def saved_to(path):
    def done(state):
        return (ready(state) and state["file_path"] is not None
                and os.path.samefile(state["file_path"], path))
    return done


def closed(state):
    return not state["is_open"]


def timing(name):
    TRACE["mark"](name + "/thread_polls")
    return {name + "/thread_polls": call("timing_take")}


TRACE["mark"]("setup")
call("events_connect", events=PAYLOAD["events"])
recordings = []
for cycle in (1, 2):
    path = PAYLOAD["work"] + f"/cycle{cycle}/lifecycle.spp"
    os.makedirs(os.path.dirname(path))
    created = {}
    created.update(phase("create", lambda: call(
        "timed_call", phase="create", args=PAYLOAD["create"]["args"],
        resolved=PAYLOAD["create"]["resolved"]), ready))
    created.update(timing("create"))
    created.update(phase("save_as", lambda: call("save_as", path=path), saved_to(path)))
    created.update(phase("close", lambda: call("close_project"), closed))
    reopened = {}
    reopened.update(phase("open", lambda: call("timed_call", phase="open", path=path), ready))
    reopened.update(timing("open"))
    reopened.update(phase("save", lambda: call("project_save"), saved_to(path)))
    reopened.update(phase("close", lambda: call("close_project"), closed))
    recordings += [created, reopened]
TRACE["mark"]("bookkeeping")
call("events_disconnect")
result = recordings
"""


def test_create_open_timing_matches_recorded_lifecycle(facade: Run, tmp_path: Path) -> None:
    """Compare all four recordings, preserving events' before-return markers."""
    probe = "phase1-create-open-timing"
    manifest, golden = golden_record(probe)
    staged = stage(manifest, tmp_path / "inputs")
    steps = manifest["instruction_sequence"]["steps"]
    create = step_payload(steps[1], staged)
    payload = {
        "create": {**create, "resolved": {"mesh": staged["plane"].as_posix()}},
        "events": steps[0]["args"]["events"],
        "work": (tmp_path / "work").as_posix(),
    }
    ours, trace = run(facade, TIMED_LIFECYCLE, payload)
    recordings = golden["recordings"]
    assert len(recordings) == len(ours) == 4
    excluded = {"create/thread_polls", "open/thread_polls"}
    for recorded, replayed in zip(recordings, ours, strict=True):
        expected = {output["output_id"]: output["value"] for output in recorded["outputs"]}
        assert set(replayed) == set(expected), recorded["recording_id"]
        for output_id, value in expected.items():
            actual = replayed[output_id]
            if output_id in excluded:
                # Decision 198: wall-clock samples differ between Painter's own repetitions.
                assert actual != value, f"{output_id} became exact: remove timing exclusion"
                assert actual["edition_entered_ms"] is not None
                assert actual["edition_entered_ms"] >= 0
                assert actual["poll_count"] >= len(actual["polls"]) > 0
                continue
            assert actual == value, f"{recorded['recording_id']} {output_id}"
    check_observed_trace(
        f"facade-events/{probe}", f"tier0/api-probes/{probe}", exercised(trace, excluded)
    )


def test_close_without_saving_restores_recorded_project(facade: Run, tmp_path: Path) -> None:
    """Replay dirty close/open, including node rebinding and the named saved file."""
    probe = "phase1-close-without-saving"
    replayed, golden, job = replay_observed(facade, probe, tmp_path)
    comparable = copy.deepcopy(golden)
    for recording in comparable["recordings"]:
        for output in recording["outputs"]:
            if output["output_id"] != "s5/files":
                continue
            files = output["value"]
            assert isinstance(files, list) and all(isinstance(name, str) for name in files)
            locks = [name for name in files if name.endswith(".painter_lock")]
            assert len(locks) <= 1, "unexpected Painter project-lock layout"
            for lock in locks:
                project_file = lock.removesuffix(".painter_lock")
                assert project_file in files, "lock sidecar has no matching project file"
                # Container-specific suffix only; full paths, presence and other files stay exact.
                files[files.index(lock)] = project_file + ".lock"
    exclusions: dict[str, str] = {}
    differences = compare_observed(replayed, comparable, job, tmp_path, exclusions)
    save_trace(f"facade-observed/{probe}", golden, replayed, exclusions, differences)
    assert replayed["cleanup_failures"] == []
    assert differences == [], "\n".join(differences)
    check_observed_trace(
        f"facade-observed/{probe}",
        golden["golden_id"],
        observed_symbols(replayed, golden, exclusions),
    )
