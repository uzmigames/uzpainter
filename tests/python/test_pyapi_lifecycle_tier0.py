"""Tier 0 event-order comparisons of the facade's asynchronous host (task
phase1.21_pyapi-dispatcher-lifecycle item 3.1; local run on the owner's machine, decision 028).

The recorder's own Painter-side code (`tools/parity/recorder/painter_side.py` and
`painter_probes.py`, documented `substance_painter` symbols only) runs inside UzPainter's embedded
interpreter against the facade and replays, exactly as the recorder drives Painter:

- `lifecycle-events`: two cycles of create -> save_as -> close (`same_session`) and open -> save
  -> close (`after_save_reopen`); each phase records the events its handlers logged, with the
  state each handler read, and the distinct states polled until the phase completed
  (`tools.parity.recorder.probes.lifecycle_phase`). Every output is compared exactly.
- the observed R10 probes `phase1-save-modes`, `phase1-reload-mesh`, `phase1-reload-resources` and
  `phase1-execute-when-not-busy` (s3-s8): every step through `probe_step`, then the events its
  handlers and callbacks logged once its asynchronous calls answered (`probe_state` pending), in
  both recordings (`probe_rebind` after save_as, close and open).

Two normalisations, outside the instruction sequence: resource contexts up to one constant
session offset (decision 107), and, for the steps of an asynchronous operation (`reload_mesh`,
`reload_modified_resources_async`), the `during_step` marker, which says whether a delivery
happened before the probe call returned: a timing that varies in Painter itself (the two
recordings of `phase1-execute-when-not-busy` s10 differ in it).

Outputs that cannot be equal are listed in `EXCLUDED` with their reason; the test requires them
to still differ. Where no private store exists the test skips, naming why.
"""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.python.capability_trace import SOURCE, check_trace, exercised
from tests.python.conftest import Run
from tests.python.test_pyapi_facade_tier0 import (
    API_PROBES,
    PAINTER_SIDE,
    golden_record,
    normalised,
)
from tools.parity.recorder.probes import INPUT_ARGS, PAINTER_PROBES

# Project-state readbacks of the observed probes, compared with the events (phase1-save-modes).
READBACK_CALLS = ("substance_painter.project.file_path", "substance_painter.project.needs_saving")
ASYNC_CALLS = (
    "substance_painter.project.reload_mesh",
    "substance_painter.resource.reload_modified_resources_async",
)
RELOAD_RESIDUAL = (
    "after save and reopen Painter reports a reload of bytes the project already holds (old and "
    "new version equal); UzPainter reloads a resource only when the file's bytes match none of "
    "its versions (decision 110)"
)
# Outputs that cannot equal Painter's: probe -> condition -> output id -> reason.
EXCLUDED: dict[str, dict[str, dict[str, str]]] = {
    "phase1-reload-resources": {
        "after_save_reopen": {"s9/events": RELOAD_RESIDUAL, "s12/events": RELOAD_RESIDUAL},
    },
}

LOADER = """
import base64, shutil, uzpainter
PAYLOAD = json.loads(base64.b64decode("__PAYLOAD__").decode("utf-8"))
TRACE = {"__name__": "uzp_capability_trace"}
exec(compile(PAYLOAD["trace"], "capability_trace.py", "exec"), TRACE)
TRACE["start"]()
recorder = {"__name__": "uzp_recorder"}
with open(PAYLOAD["painter_side"], encoding="utf-8") as source:
    exec(compile(source.read(), "painter_side.py", "exec"), recorder)
probes = dict(recorder)
with open(PAYLOAD["painter_probes"], encoding="utf-8") as source:
    exec(compile(source.read(), "painter_probes.py", "exec"), probes)
OPERATIONS = probes["OPERATIONS"]


def call(operation, **kwargs):
    try:
        return OPERATIONS[operation](kwargs)
    finally:
        # The host pumps events between remote calls, after the recorder clears CURRENT.
        uzpainter.event.flush()


def settle():
    deadline = time.monotonic() + 120
    while call("probe_state")["pending"]:
        if time.monotonic() > deadline:
            raise RuntimeError("asynchronous calls did not answer")
        time.sleep(0.01)
"""

LIFECYCLE = """
import time


def phase(name, action, done):
    call("events_take")
    action()
    states = []

    def note():
        s = call("state")
        entry = {"is_open": s["is_open"], "in_edition": s["in_edition"], "busy": s["busy"]}
        if not states or states[-1] != entry:
            states.append(entry)
        return s

    deadline = time.monotonic() + 120
    while not done(note()):
        if time.monotonic() > deadline:
            raise RuntimeError(name + " timed out")
        time.sleep(0.02)
    for _ in range(3):
        time.sleep(0.02)
        note()
    return {name + "/events": call("events_take")["events"], name + "/states": states}


def ready(s):
    return s["is_open"] and s["in_edition"] and not s["busy"]


def saved_to(path):
    def done(s):
        return ready(s) and s["file_path"] is not None and os.path.samefile(s["file_path"], path)
    return done


def closed(s):
    return not s["is_open"]


create = PAYLOAD["create"]
call("events_connect", events=PAYLOAD["events"])
recordings = []
for cycle in (1, 2):
    path = PAYLOAD["work"] + f"/cycle{cycle}/lifecycle.spp"
    os.makedirs(os.path.dirname(path))
    created = {}
    created.update(phase("create", lambda: call("apply_step", **create), ready))
    created.update(phase("save_as", lambda: call("save_as", path=path), saved_to(path)))
    created.update(phase("close", lambda: call("close_project"), closed))
    reopened = {}
    reopened.update(phase("open", lambda: call("open_project", path=path), ready))
    reopened.update(phase("save", lambda: call("project_save"), saved_to(path)))
    reopened.update(phase("close", lambda: call("close_project"), closed))
    recordings += [created, reopened]
call("events_disconnect")
result = recordings
"""

# Appended to every replay: its result with the capability trace (decision 112).
TRACED = """
result = {"result": result, "trace": TRACE["stop"]()}
"""

OBSERVED = """
import time


def run(step, work):
    for target, source in step.get("rewrite", {}).items():
        shutil.copyfile(source, target)
    resolved = dict(step["resolved"])
    if "work_file" in step["args"]:
        resolved["work_file"] = work + "/" + step["args"]["work_file"]
    TRACE["mark"](f"s{step['step']}/events")
    outcome = call("probe_step", step=step["step"], call=step["call"], args=step["args"],
                   resolved=resolved)
    settle()
    events = call("events_take")["events"]
    TRACE["mark"]("setup")
    return events, outcome


def record(steps, work):
    os.makedirs(work, exist_ok=True)
    out = {}
    for step in steps:
        events, outcome = run(step, work)
        out[f"s{step['step']}/events"] = events
        if step["call"] in PAYLOAD["readbacks"]:
            out[f"s{step['step']}/{step['call'].rsplit('.', 1)[1]}"] = outcome.get("value")
    return out


TRACE["mark"]("bookkeeping")
call("probe_reset")
TRACE["mark"]("setup")
create = PAYLOAD["create"]
call("apply_step", **create)
call("probe_step", step=2, call=PAYLOAD["connect"]["call"], args=PAYLOAD["connect"]["args"],
     resolved={})
call("events_take")
first = record(PAYLOAD["first"], PAYLOAD["work"] + "/r1")
TRACE["mark"]("bookkeeping")
locations = call("probe_locations")
call("events_take")
TRACE["mark"]("setup")
call("save_as", path=PAYLOAD["work"] + "/project/probe.spp")
call("close_project")
call("open_project", path=PAYLOAD["work"] + "/project/probe.spp")
call("probe_rebind", locations=locations)
call("events_take")
second = record(PAYLOAD["second"], PAYLOAD["work"] + "/r2")
TRACE["mark"]("bookkeeping")
call("probe_finish")
call("close_project")
result = {"same_session": first, "after_save_reopen": second}
"""


def manifest(probe: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((API_PROBES / f"{probe}.json").read_text(encoding="utf-8"))
    return data


def stage(probe: dict[str, Any], directory: Path) -> dict[str, Path]:
    """The inputs copied as `<input_id><suffix>`, the names Painter imported them under."""
    from tests.python.conftest import REPO_ROOT

    directory.mkdir(parents=True, exist_ok=True)
    staged: dict[str, Path] = {}
    for item in probe["inputs"]:
        source = REPO_ROOT / item["path"]
        target = directory / f"{item['input_id']}{source.suffix}"
        shutil.copyfile(source, target)
        staged[item["input_id"]] = target
    return staged


def step_payload(step: dict[str, Any], staged: dict[str, Path]) -> dict[str, Any]:
    args = dict(step.get("args", {}))
    resolved: dict[str, str] = {}
    key = INPUT_ARGS.get(step["call"])
    if key is not None and key in args:
        resolved[key] = staged[args[key]].as_posix()
    out: dict[str, Any] = {"step": step["step"], "call": step["call"], "args": args}
    out["resolved"] = resolved
    if "rewrite_input" in args:
        out["rewrite"] = {
            staged[args["rewrite_input"]].as_posix(): staged[args["with_input"]].as_posix()
        }
    return out


def run(facade: Run, body: str, payload: dict[str, Any]) -> tuple[Any, dict[str, list[str]]]:
    """The replay's result and its capability trace (decision 112)."""
    payload = {
        **payload,
        "painter_side": PAINTER_SIDE.as_posix(),
        "painter_probes": PAINTER_PROBES.as_posix(),
        "trace": SOURCE,
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    script = LOADER.replace("__PAYLOAD__", encoded) + body + TRACED
    report = facade(script)
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    return report["result"]["result"], report["result"]["trace"]


def test_lifecycle_events_equal_painter(facade: Run, tmp_path: Path) -> None:
    """Item 3.1: create, save_as, close, open, save and close, two cycles: every event, the state
    each handler read, its argument and the states polled after each call (`lifecycle-events`)."""
    probe = manifest("lifecycle-events")
    _, golden = golden_record("lifecycle-events")
    staged = stage(probe, tmp_path / "inputs")
    steps = probe["instruction_sequence"]["steps"]
    create = step_payload(steps[1], staged)
    payload = {
        "create": {**create, "resolved": {"mesh": staged["plane"].as_posix()}},
        "events": steps[0]["args"]["events"],
        "work": (tmp_path / "work").as_posix(),
    }
    ours, trace = run(facade, LIFECYCLE, payload)
    theirs = [
        {o["output_id"]: o["value"] for o in recording["outputs"]}
        for recording in golden["recordings"]
    ]
    assert len(theirs) == len(ours) == 4
    for index, (painter, facade_outputs) in enumerate(zip(theirs, ours, strict=True)):
        assert facade_outputs == painter, f"recording r{index + 1}"
    golden_id = "tier0/api-probes/lifecycle-events"
    check_trace("facade-events/lifecycle-events", golden_id, exercised(trace))


OBSERVED_PROBES = {
    # probe: the steps compared in the first recording (a prefix of the probe's steps)
    "phase1-create-settings": None,
    "phase1-delete-node": None,
    "phase1-resource-update": None,
    "phase1-save-modes": None,
    "phase1-reload-mesh": None,
    "phase1-reload-resources": None,
    # s9-s10 race in Painter itself (the reload starts before or after s10's call); s3-s8 only.
    "phase1-execute-when-not-busy": 8,
}


def without_marker(events: Any) -> Any:
    return [{k: v for k, v in e.items() if k != "during_step"} for e in events]


@pytest.mark.parametrize("probe", sorted(OBSERVED_PROBES))
def test_observed_probe_events_equal_painter(facade: Run, tmp_path: Path, probe: str) -> None:
    """Item 3.1 (save) and 2.5, 2.7, 2.8: the events and callbacks every step of an observed R10
    probe delivered, in both recordings."""
    data = manifest(probe)
    _, golden = golden_record(probe)
    staged = stage(data, tmp_path / "inputs")
    steps = [step_payload(s, staged) for s in data["instruction_sequence"]["steps"]]
    last = OBSERVED_PROBES[probe]
    replayed = [
        s
        for s in steps[2:]
        if s["call"] != "substance_painter.export.export_project_textures"
        and (last is None or s["step"] <= last)
    ]
    expected: dict[str, dict[str, Any]] = {}
    for recording in golden["recordings"]:
        outputs = {
            o["output_id"]: {"value": o["value"]}
            for o in recording["outputs"]
            if (o["output_id"].endswith("/events") and o["output_id"] != "start/events")
            or o["output_id"].endswith(tuple("/" + c.rsplit(".", 1)[1] for c in READBACK_CALLS))
        }
        expected[recording["condition"]] = normalised(outputs)
    second_steps = {int(key[1:].split("/")[0]) for key in expected["after_save_reopen"]}
    payload = {
        "create": {**steps[0], "resolved": {"mesh": staged[steps[0]["args"]["mesh"]].as_posix()}},
        "connect": steps[1],
        "first": replayed,
        "second": [s for s in replayed if s["step"] in second_steps],
        "work": (tmp_path / "work").as_posix(),
        "readbacks": READBACK_CALLS,
    }
    ours, trace = run(facade, OBSERVED, payload)
    asynchronous = {f"s{s['step']}/events" for s in steps if s["call"] in ASYNC_CALLS}
    differences: list[str] = []
    for condition in ("same_session", "after_save_reopen"):
        excluded = EXCLUDED.get(probe, {}).get(condition, {})
        mine = normalised({key: {"value": value} for key, value in ours[condition].items()})
        for output_id, painter in expected[condition].items():
            if last is not None and int(output_id[1:].split("/")[0]) > last:
                continue
            value = mine.get(output_id)
            if output_id in asynchronous and value is not None:
                value = {"value": without_marker(value["value"])}
                painter = {"value": without_marker(painter["value"])}
            if output_id in excluded:
                assert value != painter, f"{condition} {output_id} is equal now: drop its exclusion"
                continue
            if value != painter:
                differences.append(f"{condition} {output_id}: facade {value!r} != {painter!r}")
    assert differences == [], "\n".join(differences)
    skipped = {o.split("/")[0] + "/events" for c in EXCLUDED.get(probe, {}).values() for o in c}
    check_trace(f"facade-events/{probe}", f"tier0/api-probes/{probe}", exercised(trace, skipped))
