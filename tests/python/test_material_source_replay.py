"""Compared replay of the material-source goldens over the decision-413 capture (item 3.1).

The project is the private derived artifact of decision 413: UzPainter's own plane project holding
the multi-output capture of the decision-412 starter material in five states (20 snapshots). It is
resolved from the private oracle store by hash and size, verified after the copy and opened in
place of the golden's `project.create`; without it the tests skip as `oracle_unavailable`. A
snapshot is project-private, so no freshly created project can serve the material.

The recorder's own Painter-side code (`painter_side.py`, `painter_probes.py`) then replays the
golden exactly as `tools.parity.recorder.probes` records it in Painter: the state steps once, the
probe steps and the exports in recording r1, and again after each save, close and open (r2, r3).
Every output is compared with the admitted golden, recording by recording, readbacks, raised
errors and exported maps on every texel. The only outputs not compared are listed in
`EXCLUDED`, each with its reason and owner; a listed output must exist in the golden. After every
compared output is equal, the traced symbols of those outputs are checked against
`tools/capabilities/tier0-trace.json` (decision 112). Messages name only the recording, the
output id and digests.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.python.capability_trace import SOURCE, check_trace, exercised
from tests.python.conftest import Run
from tests.python.current_golden import current_manifest
from tests.python.test_pyapi_facade_tier0 import (
    PAINTER_SIDE,
    golden_record,
    normalised,
    stage,
)
from tests.python.test_snapshot_capture_replay import digest, private_dir, typed
from tools.parity.fit.decode import decode
from tools.parity.recorder.probes import (
    IMPORT_RESOURCE,
    PAINTER_PROBES,
    input_arg_key,
    probe_job_from_manifest,
)
from tools.parity.recorder.texture import export_roots
from tools.parity.store.store import Status, locate, resolve_oracle

# The decision-413 capture (2026-11-08, Painter lock seq 2340/2341): the defaults, the first
# preset, and that preset with the first image input set to the authored colour, to grey-a and
# removed; both outputs in both channel views, verified after save and reopen.
PROJECT_BLOB: dict[str, Any] = {
    "record_id": "source-substance-presets-inputs-project",
    "sha256": "b34c843e68c1823aad086df139daa279ce23ce4d3a28859915ed2c4a2e7122ed",
    "size_bytes": 237568,
}

TEMPLATE = (
    "the replay opens the capture project, whose stack also holds the capture's User0 L32F and "
    "User1 RGB32F channels, in place of Painter's fresh project (snapshots are project-private)"
)
SPLIT = (
    "a split source of a Substance resource on a template or User RGB channel is not served: the "
    "split BaseColor store is not derivable from the captured views and split sources bind only "
    "through `assets bind-snapshot` (phase3.3_procedural-families item 2.7): this step, the reads "
    "of that source and what depends on the fill"
)
SPLIT_EXPORT = (
    "BaseColor holds the refused split BaseColor fill (phase3.3_procedural-families item 2.7)"
)
RESOLUTION = (
    "a material source's default resolution is not recorded in the capture's metadata; the "
    "facade refuses it (UnsupportedProcedural, phase3.3_procedural-families item 2.7)"
)
MASKED = (
    "a mask output other than the output mapped to Height: r1 is fitted exactly but r2 and r3 are "
    "one binary16 ulp lower after save/reopen (P413-C, decision 416); the facade refuses the edit "
    "before any change (phase3.3_procedural-families item 2.7): this step and the reads after it"
)
REOPENED_MASKED = (
    "recording r2 starts from r1's end state, masked by an output other than Height's, which the "
    "facade refuses (decision 416, phase3.3_procedural-families item 2.7)"
)


def excluded(reason: str, *names: str) -> dict[str, str]:
    return dict.fromkeys(names, reason)


def split_outputs(name: str, nodes: tuple[int, ...]) -> dict[str, str]:
    """Every output of the split fills `nodes` (their insertion and each step on them)."""
    manifest = current_manifest(f"tier0/api-probes/{name}")
    outputs: dict[str, str] = {}
    for step in manifest["instruction_sequence"]["steps"]:
        number, call = step["step"], str(step["call"]).rsplit(".", 1)[1]
        if number in nodes:
            outputs.update(excluded(SPLIT, f"s{number}/{call}", f"identity/s{number}"))
            outputs[f"defaults/s{number}"] = SPLIT
        elif step["args"].get("node_step") in nodes:
            outputs[f"s{number}/{call}"] = SPLIT
    return outputs


# The P413-A state goldens the facade reaches: no mask output (decision 416).
STATES = (
    "defaults",
    "preset",
    "preset-colour",
    "preset-bitmap",
    "preset-reset",
    "preset-removed",
    "mapping-swap",
    "mapping-basecolor",
)
PRESETS = "source-substance-presets-inputs"
ACCESS = "source-substance-mapping-access"
MATERIAL_ONLY = (
    "source-substance-channels-material-only",
    "source-substance-masked-by-height",
    "source-substance-masked-by-normal-swap",
)


def goldens() -> dict[str, dict[str, str]]:
    """Each compared golden and its excluded outputs."""
    result: dict[str, dict[str, str]] = {
        name: {"template/texture-sets": TEMPLATE} for name in MATERIAL_ONLY
    }
    for state in STATES:
        name = f"source-substance-channels-{state}"
        result[name] = {
            "template/texture-sets": TEMPLATE,
            **split_outputs(name, (5,)),
            "uzp_plane/basecolor": SPLIT_EXPORT,
        }
    result[PRESETS] = {
        "template/texture-sets": TEMPLATE,
        **split_outputs(PRESETS, (5,)),
        "s17/resolution": RESOLUTION,
        **excluded(
            MASKED,
            "s89/mask_output",
            "s90/get_parameters",
            "s91/output_mapping",
            "s92/mask_output",
            "s93/get_source",
        ),
    }
    result[ACCESS] = {
        "template/texture-sets": TEMPLATE,
        "s2/add_channel": TEMPLATE,
        "s3/add_channel": TEMPLATE,
        **split_outputs(ACCESS, (4, 7, 10)),
    }
    return result


GOLDENS = goldens()
# Recording r2 of the presets probe is wholly excluded; its r1 is compared.
WHOLLY_EXCLUDED = {PRESETS: {"r2": REOPENED_MASKED}}


def step_payload(step: Any, staged: dict[str, Path]) -> dict[str, Any]:
    """A step as the recorder hands it to Painter, its staged input resolved (`probes.run_step`:
    an import names its file `image`)."""
    resolved: dict[str, str] = {}
    key = input_arg_key(step.call, step.args)
    if key is not None and key in step.args:
        transport = "image" if step.call == IMPORT_RESOURCE else key
        resolved[transport] = staged[step.args[key]].as_posix()
    return {"step": step.step, "call": step.call, "args": step.args, "resolved": resolved}


@pytest.fixture
def captured_project(tmp_path: Path) -> Path:
    resolved = resolve_oracle(locate(), PROJECT_BLOB)
    if resolved.status != Status.AVAILABLE or resolved.path is None:
        pytest.skip(f"oracle_unavailable: {resolved.reason}")
    target = tmp_path / "captured.uzp"
    shutil.copyfile(resolved.path, target)
    size = target.stat().st_size
    sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    if (sha256, size) != (PROJECT_BLOB["sha256"], PROJECT_BLOB["size_bytes"]):
        pytest.fail(f"copied project differs: sha256 {sha256}, size {size}", pytrace=False)
    return target


REPLAY = """
import base64
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
    return OPERATIONS[operation](kwargs)


def readback(output_id, outcome):
    out = {"value": outcome.get("value")}
    if "raised" in outcome:
        out["raised"] = outcome["raised"]
    return output_id, out


def output_id(step):
    return f"s{step['step']}/{step['call'].rsplit('.', 1)[1]}"


PREFIX = ""


def mark(name):
    TRACE["mark"](PREFIX + name)


def run_step(step):
    mark(output_id(step))
    return call("probe_step", step=step["step"], call=step["call"], args=step["args"],
                resolved=step["resolved"])


def record(recording, first, uids):
    global PREFIX
    # An uncompared recording's symbols are no evidence (decision 112): its marks are apart.
    PREFIX = "uncompared:" if recording in PAYLOAD["uncompared"] else ""
    mark("template/texture-sets")
    outputs = {"template/texture-sets": {"value": call("template_capture")}}
    outputs.update(first)
    for step, uid in sorted(uids.items(), key=lambda item: int(item[0])):
        mark(f"identity/s{step}")
        value = call("probe_identity", node_step=int(step), recorded_uid=uid)
        outputs[f"identity/s{step}"] = {"value": value}
    for step in PAYLOAD["probes"]:
        key, out = readback(output_id(step), run_step(step))
        outputs[key] = out
    files = {}
    for name, config in PAYLOAD["exports"][recording].items():
        mark("export/" + name)
        try:
            result = sp.export.export_project_textures(config)
        except Exception as error:
            files[name] = {"raised": type(error).__name__ + ": " + str(error)}
            continue
        files[name] = sorted(f for fs in result.textures.values() for f in fs)
    PREFIX = ""
    return {"outputs": outputs, "files": files}


TRACE["mark"]("bookkeeping")
call("probe_reset", root=PAYLOAD["run"])
TRACE["mark"]("setup")
# The golden's project.create: the capture project holds the plane and the snapshots.
call("open_project", path=PAYLOAD["project"])
defaults = {"inserted": {}}
first = {}
for step in PAYLOAD["state"]:
    outcome = run_step(step)
    if "defaults" in outcome:
        defaults["inserted"][str(step["step"])] = outcome["defaults"]
    key, out = readback(output_id(step), outcome)
    first[key] = out
TRACE["mark"]("bookkeeping")
uids = {step: int(where["uid"]) for step, where in call("probe_locations").items()}
recordings = {"r1": record("r1", first, uids)}
for recording in PAYLOAD["reopened"]:
    TRACE["mark"]("bookkeeping")
    locations = call("probe_locations")
    TRACE["mark"]("setup")
    sp.project.save()
    call("close_project")
    call("open_project", path=PAYLOAD["project"])
    PREFIX = "uncompared:" if recording in PAYLOAD["uncompared"] else ""
    mark("identity/reopen")
    PREFIX = ""
    found = call("probe_rebind", locations=locations)
    recordings[recording] = record(recording, {"identity/reopen": {"value": found}}, uids)
TRACE["mark"]("setup")
call("close_project")
result = {"defaults": defaults, "recordings": recordings, "trace": TRACE["stop"]()}
"""


def replay(
    facade: Run, name: str, project: Path, work: Path
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    manifest, golden = golden_record(name)
    job = probe_job_from_manifest(json.loads(json.dumps(manifest)))
    staged = stage(job, work / "inputs")
    template = next(
        o["values"] for o in golden["recordings"][0]["outputs"] if o["kind"] == "template_capture"
    )
    roots = [ts if not st else f"{ts}/{st}" for ts, st in export_roots(template)]
    recordings = [r["recording_id"] for r in golden["recordings"]]
    exports = {
        recording: {
            f"{export.step}/{out.name}": dataclasses.replace(export, maps=(out,)).config(
                work / recording / f"export-step{export.step}-{index}", roots
            )
            for export in job.exports
            for index, out in enumerate(export.maps)
        }
        for recording in recordings
    }
    payload = {
        "painter_side": PAINTER_SIDE.as_posix(),
        "painter_probes": PAINTER_PROBES.as_posix(),
        "run": work.as_posix(),
        "project": project.as_posix(),
        "state": [step_payload(s, staged) for s in job.state_steps],
        "probes": [step_payload(s, staged) for s in job.probe_steps],
        "exports": exports,
        "reopened": recordings[1:],
        "uncompared": sorted(WHOLLY_EXCLUDED.get(name, {})),
        "trace": SOURCE,
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    report = facade(REPLAY.replace("__PAYLOAD__", encoded))
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    return report["result"], golden, job


def golden_outputs(golden: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for recording in golden["recordings"]:
        outputs: dict[str, dict[str, Any]] = {}
        for o in recording["outputs"]:
            if o["kind"] == "exported_map":
                continue
            entry = {"value": o.get("value", o.get("values"))}
            if "raised" in o:
                entry["raised"] = o["raised"]
            outputs[o["output_id"]] = entry
        out[recording["recording_id"]] = normalised(outputs)
    return out


def map_differences(
    golden: dict[str, Any], replayed: dict[str, Any], job: Any, skip: dict[str, str]
) -> list[str]:
    store = locate()
    assert store is not None
    differences: list[str] = []
    maps = {(e.step, m.name): m for e in job.exports for m in e.maps}
    for recording in golden["recordings"]:
        rid = recording["recording_id"]
        if rid in skip:
            continue
        for o in recording["outputs"]:
            if o["kind"] != "exported_map":
                continue
            step = int(o["export_settings"]["step"])
            out = maps[(step, o["map"])]
            stem = out.file_name.replace("$textureSet", o["texture_set"])
            exported = replayed["recordings"][rid]["files"][f"{step}/{o['map']}"]
            if isinstance(exported, dict):
                differences.append(f"{rid} {o['output_id']}: raised")
                continue
            written = [Path(f) for f in exported if Path(f).stem == stem]
            if len(written) != 1:
                differences.append(f"{rid} {o['output_id']}: not exported")
                continue
            expected = store.load(o["blob"]["sha256"])
            assert expected is not None, f"golden blob {o['blob']['sha256']} is not in the store"
            ours, theirs = decode(written[0].read_bytes()), decode(expected)
            same = ours.values.shape == theirs.values.shape and bool(
                (ours.values == theirs.values).all()
            )
            if not same:
                differences.append(f"{rid} {o['output_id']}: differs from Painter's map")
    return differences


def compare(name: str, facade: Run, project: Path, work: Path) -> list[str]:
    replayed, golden, job = replay(facade, name, project, work)
    skip_output = GOLDENS[name]
    skip_recording = WHOLLY_EXCLUDED.get(name, {})
    expected = golden_outputs(golden)
    differences: list[str] = []
    details: dict[str, Any] = {}
    for rid, theirs in expected.items():
        if rid in skip_recording:
            continue
        ours = normalised(replayed["recordings"][rid]["outputs"])
        for output_id, value in ours.items():
            if output_id in skip_output:
                continue
            painter = theirs.get(output_id)
            if painter is None or typed(painter) != typed(value):
                details[f"{rid}/{output_id}"] = {"recorded": painter, "replayed": value}
                differences.append(
                    f"{rid} {output_id}: replayed {digest(value)} != recorded "
                    f"{digest(painter) if painter is not None else 'absent'}"
                )
        for output_id in theirs:
            if output_id not in ours and output_id not in skip_output:
                differences.append(f"{rid} {output_id}: not replayed")
    if details:
        # Values stay private: only digests reach the test output.
        text = json.dumps(details, indent=1)
        (private_dir() / f"material-replay-differences-{name}.json").write_text(text, "utf-8")
    inserted = golden["key"]["effective_defaults"]["inserted"]
    for step, value in replayed["defaults"]["inserted"].items():
        key = f"defaults/s{step}"
        if key not in skip_output and inserted.get(step) != value:
            differences.append(
                f"{key}: replayed {digest(value)} != recorded {digest(inserted.get(step))}"
            )
    differences += [
        d
        for d in map_differences(golden, replayed, job, skip_recording)
        if d.split()[1].rstrip(":") not in skip_output
    ]
    recorded = {o["output_id"] for r in golden["recordings"] for o in r["outputs"]}
    recorded |= {f"defaults/s{step}" for step in inserted}
    for output_id in skip_output:
        assert output_id in recorded, f"{name}: the excluded output {output_id} is not recorded"
    if not differences:
        excluded_exports = {
            f"export/{o['export_settings']['step']}/{o['map']}"
            for r in golden["recordings"]
            for o in r["outputs"]
            if o["kind"] == "exported_map" and o["output_id"] in skip_output
        }
        # A wholly excluded recording's outputs are no evidence either.
        skipped = {key for key in replayed["trace"] if key.startswith("uncompared:")}
        symbols = exercised(replayed["trace"], {*skip_output, *excluded_exports, *skipped})
        check_trace(f"facade/{name}", f"tier0/api-probes/{name}", symbols)
    return differences


@pytest.mark.parametrize("name", sorted(GOLDENS))
def test_material_golden_replays_exactly(
    private_facade: Run, captured_project: Path, tmp_path: Path, name: str
) -> None:
    differences = compare(name, private_facade, captured_project, tmp_path)
    print(f"full comparison: {'equal' if not differences else 'different'} ({len(differences)})")
    assert differences == [], "\n".join(differences)
