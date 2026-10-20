"""The compared replay of an observed Tier 0 API-probe golden (task phase1.24_python-api-facade
item 4.1; local run on the owner's machine, decision 028).

An observed probe golden connects events in its step 2, so the recorder records after every later
step the events dispatched since the previous step and the readiness states it polled
(`tools.parity.recorder.probes`, `observe`). `replay_observed` runs the golden's instruction
sequence inside UzPainter's embedded interpreter with the recorder's own Painter-side code
(`painter_side.py`, `painter_probes.py`, documented `substance_painter` symbols only), step for step
as `record_api_probe` drives Painter:

- the project, then the state steps once, each observed; `s<n>/files` after a save, `s<n>/rebind`
  after a `project.open`;
- recording `same_session`: the template, `start/events`, the inserted nodes' identities, the probe
  steps (an `export_project_textures` probe step through `probe_export`, with its directory's
  files), then the capture exports, one map at a time so a refused map hides no other;
- save, close and reopen, the nodes found again (`identity/reopen`), and recording
  `after_save_reopen` the same way.

The run directory has the recorder's layout (`inputs`, `r1`, `r2`, `project`) and is the probe's
root, so paths read back relative to it as in Painter's recording.

`compare_observed` compares every output with the golden, field by field, in both recordings, the
inserted nodes' effective defaults and the exported maps (decoded on every texel). An output in
`excluded` (key `<output id>` for both recordings, `<condition> <output id>` for one) must exist in
the golden and must still differ, so no exclusion outlives its reason. The golden is read from the
private store at run time (`golden_record`); no Painter value is in this repository.

Each replay is traced (`capability_trace.py`, decision 112). With `$UZP_OBSERVED_TRACE_DIR` set,
`check_observed_trace` and `save_trace` write the trace to that folder instead of checking
`tools/capabilities/tier0-trace.json`, which its one writer makes from those traces, so a symbol is
cited only by a replay that proved its outputs exact.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import os
from pathlib import Path
from typing import Any

from tests.python.capability_trace import SOURCE, check_trace, exercised
from tests.python.conftest import Run
from tests.python.test_pyapi_facade_tier0 import (
    CONDITIONS,
    PAINTER_SIDE,
    golden_outputs,
    golden_record,
    map_differences,
    normalised,
    stage,
    without_default_layer,
)
from tools.parity.recorder.job import EXPORT, Step, export_step
from tools.parity.recorder.probes import (
    CREATE_FOLDERS,
    DEFAULT_EXPORT_PATH,
    EXPORT_PATH_BLOCKED,
    INPUT_ARGS,
    MESH_MAPS,
    PAINTER_PROBES,
    PLUGIN_FOLDER,
    PLUGINS_PATH,
    RELOAD_RESOURCES,
    REWRITE_ARGS,
    SHELF_FOLDER,
    SHELF_INPUTS,
    WORK_FILE,
    ProbeJob,
    ProbeStep,
    plugin_root,
    probe_job_from_manifest,
)
from tools.parity.recorder.texture import export_roots

# Seconds between the readiness polls of a step (the recorder's session interval is the host's;
# only state changes are recorded, so the interval changes no output).
POLL_INTERVAL_S = 0.05
# Seconds a replay may run before its watchdog ends it (under the runner's own 600 s).
TIMEOUT_S = 480.0
# Where `save_trace` writes each replay's trace (unset: nowhere). The traces are the evidence a
# later `tier0-trace.json` entry is made from; this module never writes that file.
TRACE_DIR = "UZP_OBSERVED_TRACE_DIR"
TRACE_OUT = "UZP_OBSERVED_TRACE_OUT"  # an alias of TRACE_DIR

REPLAY = """
import base64, hashlib, shutil, threading, time
PAYLOAD = json.loads(base64.b64decode("__PAYLOAD__").decode("utf-8"))
TRACE = {"__name__": "uzp_capability_trace"}
exec(compile(PAYLOAD["trace"], "capability_trace.py", "exec"), TRACE)
TRACE["start"]()
MARK = ["setup"]


def mark(output_id):
    MARK[0] = output_id
    TRACE["mark"](output_id)


def watchdog():
    # A call that never returns (a job queue that cannot progress) ends the run with an error
    # report naming the output it was on, instead of blocking the test.
    time.sleep(PAYLOAD["timeout_s"])
    message = "replay timed out after " + str(PAYLOAD["timeout_s"]) + " s at " + MARK[0]
    report = {"status": "error",
              "error": {"type": "TimeoutError", "message": message, "traceback": message}}
    os.write(1, ("UZP_JSON:" + json.dumps(report) + chr(10)).encode("utf-8"))
    os._exit(1)


threading.Thread(target=watchdog, daemon=True).start()
recorder = {"__name__": "uzp_recorder"}
with open(PAYLOAD["painter_side"], encoding="utf-8") as source:
    exec(compile(source.read(), "painter_side.py", "exec"), recorder)
probes = dict(recorder)
with open(PAYLOAD["painter_probes"], encoding="utf-8") as source:
    exec(compile(source.read(), "painter_probes.py", "exec"), probes)
OPERATIONS = probes["OPERATIONS"]
POLL = PAYLOAD["poll_interval_s"]
SETTLE_POLLS = 3
ASYNC_TIMEOUT_S = 600.0
RUN = PAYLOAD["run"]


def call(operation, **kwargs):
    # One recorder remote call. Painter delivers the events its operations queued (a created or
    # opened project's ProjectEditionEntered) when its event loop runs between two remote calls,
    # once the call's step marker has cleared: the replay delivers them at the same boundary.
    value = OPERATIONS[operation](kwargs)
    uzpainter.event.flush()
    return value


def wait_for(condition, what):
    deadline = time.monotonic() + 600.0
    while True:
        state = call("state")
        if condition(state):
            return state
        if time.monotonic() >= deadline:
            raise RuntimeError("timed out waiting for " + what)
        time.sleep(POLL)


def ready(state):
    return state["is_open"] and state["in_edition"] and not state["busy"]


def wait_ready():
    return wait_for(ready, "the project to be ready")


def readback(outcome):
    out = {"value": outcome.get("value")}
    if "raised" in outcome:
        out["raised"] = outcome["raised"]
    return out


def work_files(directory):
    if not os.path.isdir(directory):
        return []
    found = []
    for folder, _, names in os.walk(directory):
        for name in names:
            relative = os.path.relpath(os.path.join(folder, name), directory)
            found.append(relative.replace(os.sep, "/"))
    return sorted(found)


def sha256(path):
    with open(path, "rb") as data:
        return hashlib.sha256(data.read()).hexdigest()


def observe(step):
    states = []

    def note():
        polled = dict(call("probe_state"))
        pending = polled.pop("pending")
        if not states or states[-1] != polled:
            states.append(polled)
        return pending

    n = step["step"]
    mark(f"s{n}/states")
    deadline = time.monotonic() + ASYNC_TIMEOUT_S
    pending = note()
    while pending and time.monotonic() < deadline:
        time.sleep(POLL)
        pending = note()
    for _ in range(SETTLE_POLLS):
        time.sleep(POLL)
        pending = note()
    mark(f"s{n}/events")
    events = call("events_take")["events"]
    out = {f"s{n}/events": {"value": events}, f"s{n}/states": {"value": states}}
    if pending:
        out[f"s{n}/pending"] = {"value": pending}
    return out


def run_step(step, work_dir):
    mark(step["output_id"])
    resolved = dict(step["resolved"])
    args = step["args"]
    if "work_file" in args:
        os.makedirs(work_dir, exist_ok=True)
        resolved["work_file"] = work_dir + "/" + args["work_file"]
    if step["call"] == PAYLOAD["shelves_add"]:
        folder = work_dir + "/" + args["folder"]
        os.makedirs(folder, exist_ok=True)
        for source in step["shelf_inputs"]:
            shutil.copyfile(source, folder + "/" + os.path.basename(source))
        resolved["shelf_path"] = folder
    if "rewrite_inputs" in step:
        target, source = step["rewrite_inputs"]
        shutil.copyfile(source, target)
    return call("probe_step", step=step["step"], call=step["call"], args=args, resolved=resolved)


def run_step_rebinding(step, work_dir, closed):
    if step["call"] == PAYLOAD["project_close"]:
        mark("bookkeeping")
        closed["locations"] = call("probe_locations")
    return run_step(step, work_dir)


def rebound(step, closed):
    if step["call"] != PAYLOAD["project_open"]:
        return {}
    mark("setup")
    wait_ready()
    mark(f"s{step['step']}/rebind")
    found = call("probe_rebind", locations=closed.get("locations", {}))
    return {f"s{step['step']}/rebind": {"value": found}}


def step_outputs(step, work_dir, outcome):
    out = {step["output_id"]: readback(outcome)}
    if step["call"] != PAYLOAD["event_connect"] and step["wait"]:
        out.update(observe(step))
    if step["call"] in PAYLOAD["save_calls"]:
        mark(f"s{step['step']}/files")
        out[f"s{step['step']}/files"] = {"value": work_files(work_dir)}
    return out


def located_files(outcome):
    files = []
    value = outcome.get("value") or {}
    for located in value.get("locations", {}).values():
        for where in located:
            parts = where.get("run_relative") if isinstance(where, dict) else None
            if parts is None:
                files.append({"location": where})
                continue
            path = os.path.join(RUN, *parts)
            files.append({"file_name": "/".join(parts),
                          "sha256": sha256(path) if os.path.isfile(path) else None})
    return files


def probe_export(step, condition):
    export = step["exports"][condition]
    export_dir = export["directory"]
    if step["args"].get("export_path_blocked") is True:
        os.makedirs(os.path.dirname(export_dir), exist_ok=True)
        with open(export_dir, "wb"):
            pass
    else:
        os.makedirs(export_dir)
    mark(step["output_id"])
    outcome = call("probe_export", step=step["step"], config=export["config"],
                   locations=export["default_path"])
    out = {step["output_id"]: readback(outcome)}
    if step["wait"]:
        out.update(observe(step))
    mark(f"s{step['step']}/files")
    files = [{"file_name": name, "sha256": sha256(export_dir + "/" + name)}
             for name in work_files(export_dir)]
    if export["default_path"]:
        files = located_files(outcome)
    out[f"s{step['step']}/files"] = {"value": files}
    return out


def record(condition, first, uids):
    mark("setup")
    wait_ready()
    mark("template/texture-sets")
    template = call("template_capture")
    outputs = {"template/texture-sets": {"value": template}}
    outputs.update(first)
    mark("start/events")
    outputs["start/events"] = {"value": call("events_take")["events"]}
    for step, uid in sorted(uids.items(), key=lambda item: int(item[0])):
        mark(f"identity/s{step}")
        value = call("probe_identity", node_step=int(step), recorded_uid=uid)
        outputs[f"identity/s{step}"] = {"value": value}
    directory = RUN + "/" + PAYLOAD["recordings"][condition]
    work_dir = directory + "/work-files"
    closed = {}
    for step in PAYLOAD["probes"]:
        if step["call"] == PAYLOAD["export"]:
            outputs.update(probe_export(step, condition))
            continue
        outcome = run_step_rebinding(step, work_dir, closed)
        outputs.update(step_outputs(step, work_dir, outcome))
        outputs.update(rebound(step, closed))
    files = {}
    for name, config in PAYLOAD["captures"][condition].items():
        mark("setup")
        wait_ready()
        mark("export/" + name)
        try:
            result = sp.export.export_project_textures(config)
        except Exception as error:
            files[name] = {"raised": type(error).__name__ + ": " + str(error)}
            continue
        files[name] = sorted(f for fs in result.textures.values() for f in fs)
    mark("setup")
    return {"outputs": outputs, "files": files}


mark("bookkeeping")
call("probe_reset", root=RUN)
mark("setup")
create = PAYLOAD["create"]
created = call("apply_step", step=create["step"], call=create["call"], args=create["args"],
               resolved=create["resolved"])
wait_ready()
defaults = {"project.create": call("template_capture"),
            "colour_management": created["colour_management"], "inserted": {}}
first = {}
closed = {}
state_dir = RUN + "/r1/work-files"
for step in PAYLOAD["state"]:
    outcome = run_step_rebinding(step, state_dir, closed)
    if "defaults" in outcome:
        defaults["inserted"][str(step["step"])] = outcome["defaults"]
    first.update(step_outputs(step, state_dir, outcome))
    first.update(rebound(step, closed))
mark("setup")
wait_ready()
mark("bookkeeping")
uids = {step: int(where["uid"]) for step, where in call("probe_locations").items()}
same_session = record("same_session", first, uids)
wait_ready()
mark("bookkeeping")
locations = call("probe_locations")
mark("setup")
saved_to = RUN + "/project/probe.spp"
os.makedirs(os.path.dirname(saved_to))
call("save_as", path=saved_to)
saved = wait_ready()
if saved["file_path"] is None or not os.path.samefile(saved["file_path"], saved_to):
    raise RuntimeError("the project was not saved to " + saved_to)
call("close_project")
wait_for(lambda state: not state["is_open"], "the project to close")
call("open_project", path=saved_to)
wait_ready()
mark("identity/reopen")
found = call("probe_rebind", locations=locations)
after = record("after_save_reopen", {"identity/reopen": {"value": found}}, uids)
mark("bookkeeping")
cleanup = []
for operation in ("probe_finish", "close_project", "probe_cleanup"):
    try:
        cleanup += call(operation).get("cleanup_failures", [])
    except Exception as error:
        cleanup.append({"stage": operation, "raised": type(error).__name__ + ": " + str(error)})
result = {"defaults": defaults, "same_session": same_session, "after_save_reopen": after,
          "cleanup_failures": cleanup, "trace": TRACE["stop"]()}
"""

RECORDINGS = {"same_session": "r1", "after_save_reopen": "r2"}


def step_payload(step: ProbeStep, staged: dict[str, Path], run: Path) -> dict[str, Any]:
    """A state or probe step as the script runs it: the staged input paths resolved, and for
    `Shelves.add` the staged inputs it copies into its folder."""
    resolved: dict[str, str] = {}
    key = INPUT_ARGS.get(step.call)
    if key is not None and key in step.args:
        resolved[key] = staged[step.args[key]].as_posix()
    if step.call == PLUGINS_PATH and PLUGIN_FOLDER in step.args:
        resolved["plugin_root"] = plugin_root(step, run / "r1" / "work-files").as_posix()
    out: dict[str, Any] = {
        "step": step.step,
        "call": step.call,
        "args": step.args,
        "resolved": resolved,
        "wait": step.wait,
        "output_id": step.output_id,
    }
    if SHELF_FOLDER in step.args and SHELF_INPUTS in step.args:
        out["shelf_inputs"] = [staged[i].as_posix() for i in step.args[SHELF_INPUTS]]
    if step.call == RELOAD_RESOURCES and REWRITE_ARGS[0] in step.args:
        out["rewrite_inputs"] = [staged[step.args[name]].as_posix() for name in REWRITE_ARGS]
    return out


def probe_export_payload(step: ProbeStep, run: Path, roots: list[str]) -> dict[str, Any]:
    """An export probe step's configuration in each recording's directory (`probe_export`)."""
    export = export_step(Step(step.step, EXPORT, step.args))
    default_path = step.args.get(DEFAULT_EXPORT_PATH) is True
    exports: dict[str, Any] = {}
    for condition, recording in RECORDINGS.items():
        directory = run / recording / f"probe-export-step{step.step}"
        config = export.config(directory, roots)
        if default_path:
            del config["exportPath"]
        exports[condition] = {
            "directory": directory.as_posix(),
            "config": config,
            "default_path": default_path,
        }
    return exports


def create_resolved(job: ProbeJob, staged: dict[str, Path], run: Path) -> dict[str, Any]:
    """The staged mesh, the mesh-map files and the default folders (`probes.create_resolved`)."""
    args = job.create.args
    resolved: dict[str, Any] = {"mesh": staged[args["mesh"]].as_posix()}
    if MESH_MAPS in args:
        resolved[MESH_MAPS] = [staged[m].as_posix() for m in args[MESH_MAPS]]
    for name in CREATE_FOLDERS:
        if name in args:
            folder = run / "r1" / "work-files" / args[name]
            folder.mkdir(parents=True, exist_ok=True)
            resolved[name] = folder.as_posix()
    return resolved


def replay_observed(
    facade: Run, probe: str, work: Path, timeout_s: float = TIMEOUT_S
) -> tuple[dict[str, Any], dict[str, Any], ProbeJob]:
    """The facade's replay of the observed probe golden `probe`, the golden record and the job.
    A replay still running after `timeout_s` seconds ends with an error naming the output it was
    on (a call that cannot return, such as a job queue that cannot progress, fails the test).

    The replay's outputs are `{condition: {"outputs": {output id: {"value", "raised"?}}, "files":
    {"<step>/<map>": [written files] | {"raised": ...}}}}`, with `defaults` (the golden key's
    effective defaults), `cleanup_failures` (the recorder's restoring stages that failed) and
    `trace` (the symbols each output exercised, `capability_trace.py`)."""
    from tools.parity.recorder.probes import (
        EVENT_CONNECT,
        PROJECT_CLOSE,
        PROJECT_OPEN,
        SAVE_CALLS,
        SHELVES_ADD,
    )

    manifest, golden = golden_record(probe)
    job = probe_job_from_manifest(json.loads(json.dumps(manifest)))
    assert not job.lifecycle, f"{probe} is a lifecycle golden, not an observed probe"
    assert job.observed, f"{probe} connects no events in step 2"
    assert all(WORK_FILE not in s.args or s.call in SAVE_CALLS for s in job.probe_steps), (
        f"{probe}: a work file on a call the replay does not resolve"
    )
    run = work / "run"
    staged = stage(job, run / "inputs")
    template = next(
        o["values"] for o in golden["recordings"][0]["outputs"] if o["kind"] == "template_capture"
    )
    roots = [ts if not st else f"{ts}/{st}" for ts, st in export_roots(template)]
    probes: list[dict[str, Any]] = []
    for step in job.probe_steps:
        payload = step_payload(step, staged, run)
        if step.call == EXPORT:
            payload["exports"] = probe_export_payload(step, run, roots)
        probes.append(payload)
    captures = {
        condition: {
            f"{export.step}/{out.name}": dataclasses.replace(export, maps=(out,)).config(
                run / recording / f"export-step{export.step}-{index}", roots
            )
            for export in job.exports
            for index, out in enumerate(export.maps)
        }
        for condition, recording in RECORDINGS.items()
    }
    assert not any(EXPORT_PATH_BLOCKED in s.args for s in job.state_steps)
    payload = {
        "painter_side": PAINTER_SIDE.as_posix(),
        "painter_probes": PAINTER_PROBES.as_posix(),
        "poll_interval_s": POLL_INTERVAL_S,
        "timeout_s": timeout_s,
        "trace": SOURCE,
        "run": run.as_posix(),
        "recordings": RECORDINGS,
        "create": {
            "step": job.create.step,
            "call": job.create.call,
            "args": job.create.args,
            "resolved": create_resolved(job, staged, run),
        },
        "state": [step_payload(s, staged, run) for s in job.state_steps],
        "probes": probes,
        "captures": captures,
        "export": EXPORT,
        "event_connect": EVENT_CONNECT,
        "project_close": PROJECT_CLOSE,
        "project_open": PROJECT_OPEN,
        "shelves_add": SHELVES_ADD,
        "save_calls": sorted(SAVE_CALLS),
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    report = facade(REPLAY.replace("__PAYLOAD__", encoded))
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    return report["result"], golden, job


def exclusion(excluded: dict[str, str], condition: str, output_id: str) -> str | None:
    """The reason `output_id` of `condition` is excluded, if it is."""
    return excluded.get(f"{condition} {output_id}", excluded.get(output_id))


def compare_observed(
    replayed: dict[str, Any],
    golden: dict[str, Any],
    job: ProbeJob,
    work: Path,
    excluded: dict[str, str],
) -> list[str]:
    """Every difference between the facade's replay and Painter's golden, both recordings: each
    readback, event list, state list and file list, each inserted node's defaults and each
    exported map. Excluded outputs must exist in the golden and still differ."""
    expected = golden_outputs(golden)
    recorded = {
        (r["condition"], o["output_id"]) for r in golden["recordings"] for o in r["outputs"]
    }
    inserted = golden["key"]["effective_defaults"]["inserted"]
    differences: list[str] = []
    for key in excluded:
        condition, _, output_id = key.rpartition(" ")
        if output_id.startswith("defaults/s"):
            present = output_id[len("defaults/s") :] in inserted
        else:
            conditions = [condition] if condition else list(CONDITIONS)
            present = any((c, output_id) in recorded for c in conditions)
        if not present:
            differences.append(f"excluded {key!r} is not recorded in the golden")
    for condition in CONDITIONS:
        ours = normalised(replayed[condition]["outputs"])
        theirs = expected[condition]
        for output_id in sorted(set(ours) | set(theirs)):
            mine, painter = ours.get(output_id), theirs.get(output_id)
            if mine is not None and output_id.endswith("/get_root_layer_nodes"):
                mine = {**mine, "value": without_default_layer(mine["value"])}
            reason = exclusion(excluded, condition, output_id)
            if reason is not None:
                if mine == painter:
                    differences.append(f"{condition} {output_id} is equal now: drop its exclusion")
                continue
            if mine != painter:
                differences.append(
                    f"{condition} {output_id}: facade {mine!r} != Painter {painter!r}"
                )
    for step in sorted(set(inserted) | set(replayed["defaults"]["inserted"]), key=int):
        key = f"defaults/s{step}"
        mine, painter = replayed["defaults"]["inserted"].get(step), inserted.get(step)
        if key in excluded:
            if mine == painter:
                differences.append(f"{key} is equal now: drop its exclusion")
        elif mine != painter:
            differences.append(f"{key}: facade {mine!r} != Painter {painter!r}")
    maps = map_differences(golden, replayed, job, work)
    for condition in CONDITIONS:
        for o in next(r for r in golden["recordings"] if r["condition"] == condition)["outputs"]:
            if o["kind"] != "exported_map":
                continue
            found = [d for d in maps if d.startswith(f"{condition} {o['output_id']}:")]
            if exclusion(excluded, condition, o["output_id"]) is not None:
                if not found:
                    differences.append(
                        f"{condition} {o['output_id']} is equal now: drop its exclusion"
                    )
            else:
                differences += found
    return differences


def trace_folder() -> str | None:
    """The folder standalone traces go to: `$UZP_OBSERVED_TRACE_DIR` (or its alias
    `$UZP_OBSERVED_TRACE_OUT`), or None."""
    return os.environ.get(TRACE_DIR) or os.environ.get(TRACE_OUT) or None


def observed_symbols(
    replayed: dict[str, Any], golden: dict[str, Any], excluded: dict[str, str]
) -> list[str]:
    """The symbols the replay's compared outputs exercised: excluded outputs (in either
    recording), the export calls of excluded exported maps and bookkeeping left out
    (`capability_trace.exercised`)."""
    skipped = {key.rpartition(" ")[2] for key in excluded}
    # An excluded exported map's export call is not compared either: its symbols are no evidence.
    skipped |= {
        f"export/{o['export_settings']['step']}/{o['map']}"
        for r in golden["recordings"]
        for o in r["outputs"]
        if o["kind"] == "exported_map" and o["output_id"] in skipped
    }
    return exercised(replayed["trace"], skipped)


def write_trace(replay_id: str, kind: str, entry: dict[str, Any]) -> None:
    """Writes `<replay id>.<kind>.json` in the trace folder: `trace` (`save_trace`) and `symbols`
    (`check_observed_trace`) are separate files, so neither overwrites the other."""
    folder = trace_folder()
    assert folder is not None
    target = Path(folder) / f"{replay_id.replace('/', '__')}.{kind}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(entry, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def save_trace(
    replay_id: str,
    golden: dict[str, Any],
    replayed: dict[str, Any],
    excluded: dict[str, str],
    differences: list[str],
) -> None:
    """With a trace folder set (`trace_folder`), writes `<replay id>.trace.json` there: the
    symbols of the compared outputs (`observed_symbols`), the per-output trace, the exclusions
    and the differences. Without one it does nothing."""
    if trace_folder() is None:
        return
    write_trace(
        replay_id,
        "trace",
        {
            "replay": replay_id,
            "golden": golden["golden_id"],
            "exact_apart_from_exclusions": not differences,
            "differences": differences,
            "excluded": dict(sorted(excluded.items())),
            "symbols": observed_symbols(replayed, golden, excluded),
            "by_output": replayed["trace"],
        },
    )


def check_observed_trace(replay: str, golden: str, symbols: list[str]) -> None:
    """`capability_trace.check_trace(replay, golden, symbols)`; with a trace folder set
    (`trace_folder`), writes `{replay, golden, symbols}` to `<replay>.symbols.json` there
    instead, so `tools/capabilities/tier0-trace.json` keeps one writer."""
    if trace_folder() is None:
        check_trace(replay, golden, symbols)
        return
    write_trace(replay, "symbols", {"replay": replay, "golden": golden, "symbols": symbols})
