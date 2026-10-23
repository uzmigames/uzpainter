"""`substance_painter.baking.BakingParameters` and `properties.Property` over the native bake
parameter model (phase3.1_baker-request-model items 3.1 and 5.2; decision 323).

The first tests run in every lane: the facade's keys, values and metadata equal the authored table
`assets/defaults/baking.json` (UzmiGames data), `set()` is one transaction kept through save and
reopen, and every refusal decision 323 lists raises before any change.

`test_baking_defaults_equal_painter` is item 3.1 on the owner's machine (decision 028). The
recorder's own Painter-side code (`tools/parity/recorder/painter_side.py`, documented
`substance_painter` symbols only) runs inside the embedded interpreter against the facade and
replays the Tier 0 golden `tier0/defaults-templates/baking-defaults` as `record-defaults` records
it: r1 on a fresh project, r2 after save and reopen, r3 on a second fresh project. Every captured
field of every key (`keys`, `value`, `name`, `short_name`, `label`, `widget_type`, `enum_values`,
`enum_value`) and the texture set's baking state are compared exactly with the private record,
read from the store, read only. Fields UzPainter refuses are listed in `REFUSED` with the reason;
each must be refused with `NotYetSupported`, and no other field may differ. Messages name the
output, the key and the field, never a recorded value.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from tests.python.capability_trace import SOURCE, check_trace, exercised
from tests.python.conftest import REPO_ROOT, Run
from tools.bake import bake_defaults as bd
from tools.parity.recorder.defaults import baking_output_id
from tools.parity.recorder.job import job_from_manifest
from tools.parity.store.store import locate

MANIFEST = (
    REPO_ROOT
    / "parity"
    / "envelopes"
    / "painter-12.1.5_js-api.1.1.20"
    / "manifests"
    / "tier0"
    / "defaults-templates"
    / "baking-defaults.json"
)
PAINTER_SIDE = REPO_ROOT / "tools" / "parity" / "recorder" / "painter_side.py"
RECORDINGS = {"r1": "same_session", "r2": "after_save_reopen", "r3": "same_session"}

UNESTABLISHED = (
    "Painter states no default (defaultValue unset) and the fresh project's value is not "
    "established as one: value() raises NotYetSupported until a value is set (decision 323)"
)
META = (
    "the meta properties carry Painter's descriptive text, which the clean room does not "
    "reproduce: properties() raises NotYetSupported (decision 323)"
)
# (output id, key, field) -> reason; `*` stands for every key of every output.
REFUSED: dict[tuple[str, str, str], str] = {
    ("baking/common", "OutputSize", "value"): UNESTABLISHED,
    ("baking/baker/Curvature", "TonemappingBounds", "value"): UNESTABLISHED,
    ("*", "*", "properties"): META,
}


def ok(report: dict[str, Any]) -> Any:
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    return report["result"]


def strict(a: Any, b: Any) -> bool:
    """JSON equality that keeps every type apart (`True != 1`, `1 != 1.0`)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(strict(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(strict(x, y) for x, y in zip(a, b, strict=True))
    return bool(a == b)


def as_json(value: Any) -> Any:
    """A table value as the capture writes `value()`: pairs as lists."""
    return list(value) if isinstance(value, tuple) else value


# ── Every lane: the facade against the authored table ──────────────────────────────────────────

READBACK = """
from substance_painter import baking, properties
import substance_painter.project as sproject
create()
t = ts.all_texture_sets()[0]
b = baking.BakingParameters.from_texture_set(t)
usages = ["Normal", "WorldSpaceNormal", "ID", "AO", "Curvature", "Position", "Thickness",
          "Height", "BentNormals", "Opacity"]

def describe(group):
    out = []
    for key, p in group.items():
        try:
            value = p.value()
        except uzpainter.NotYetSupported:
            value = None
        out.append({"short_name": p.short_name(), "key": key, "name": p.name(), "label": p.label(),
                    "widget_type": p.widget_type(), "enum_values": p.enum_values(), "value": value,
                    "pair": type(value).__name__ if isinstance(value, (tuple, list)) else None,
                    "is_property": isinstance(p, properties.Property)})
    return out

before = uzpainter.project.revision()
result = {
    "common": describe(b.common()),
    "bakers": {u: describe(b.baker(getattr(ts.MeshMapUsage, u))) for u in usages},
    "state": [b.get_curvature_method().name, sorted(u.name for u in b.get_enabled_bakers()),
              b.is_textureset_enabled()],
    "same": [b == baking.BakingParameters.from_texture_set_name(t.name()),
             b == baking.BakingParameters(uzpainter.textureset.all_texture_sets()[0].uid()),
             b.texture_set() == t],
    "revision": [before, uzpainter.project.revision()],
}
common, ao = b.common(), b.baker(ts.MeshMapUsage.AO)
cage = common["CageMode"]
baking.BakingParameters.set({common["DilationWidth"]: 4, cage: cage.enum_value("Custom file"),
                             common["MaxHeight"]: 1, ao["NbSecondary"]: 32})
result["set"] = [common["DilationWidth"].value(), cage.value(), common["MaxHeight"].value(),
                 ao["NbSecondary"].value(), uzpainter.project.revision() - before,
                 sproject.needs_saving()]
path = WORK + "/baking.spp"
sproject.save_as(path)
sproject.close()
sproject.open(path)
again = baking.BakingParameters.from_texture_set_name(t.name())
result["reopened"] = [again.common()["DilationWidth"].value(), again.common()["CageMode"].value(),
                      again.common()["MaxHeight"].value(),
                      again.baker(ts.MeshMapUsage.AO)["NbSecondary"].value()]
"""


def test_baking_parameters_equal_the_table_and_set_values_survive_reopen(facade: Run) -> None:
    result = ok(facade(READBACK))
    table = bd.load_table()
    for output_id, entries in bd.groups(table):
        name = output_id.rsplit("/", 1)[1]
        got = result["common"] if output_id == "baking/common" else result["bakers"][name]
        assert [g["key"] for g in got] == [e["short_name"] for e in entries], output_id
        for entry, g in zip(entries, got, strict=True):
            where = f"{output_id} {entry['short_name']}"
            assert g["short_name"] == g["key"] and g["is_property"], where
            for field in ("name", "label", "widget_type"):
                assert g[field] == entry[field], (where, field)
            assert g["enum_values"] == entry.get("enum_values", {}), where
            default = entry["default"]  # an Enum's default is its integer, as value() gives it
            assert strict(as_json(g["value"]), as_json(default)), where
            if entry["type"] in ("IntPair", "FloatPair") and default is not None:
                assert g["pair"] == "tuple", where  # Painter documents value() -> Tuple
    state = table["texture_set_state"]
    assert result["state"] == [
        state["curvature_method"]["default"],
        state["enabled_bakers"]["default"],
        state["textureset_enabled"]["default"],
    ]
    assert result["same"] == [True, True, True]
    assert result["revision"][0] == result["revision"][1]  # reading changes nothing
    # One set() is one revision; the integer of an enum label is stored by its label.
    assert result["set"] == [4, 2, 1.0, 32, 1, True]
    assert result["reopened"] == [4, 2, 1.0, 32]


REFUSALS = """
from substance_painter import baking
create()
t = ts.all_texture_sets()[0]
b = baking.BakingParameters.from_texture_set(t)
common, ao = b.common(), b.baker(ts.MeshMapUsage.AO)
curvature = b.baker(ts.MeshMapUsage.Curvature)
dilation, cage = common["DilationWidth"], common["CageMode"]
before = [uzpainter.project.revision(), sp.project.needs_saving()]
set_ = baking.BakingParameters.set
result = {
    "wrong_type": raises(set_, {dilation: 1.5}),
    "bool_for_int": raises(set_, {dilation: True}),
    "enum_label": raises(set_, {cage: "Custom file"}),
    "unknown_enum": raises(set_, {cage: 7}),
    "pair_size": raises(set_, {common["OutputSize"]: (10, 10, 10)}),
    "not_a_property": raises(set_, {"DilationWidth": 4}),
    "out_of_range": raises(set_, {dilation: 100000}),
    # One refused value refuses the whole batch: the valid value is not stored either.
    "batch": raises(set_, {ao["NbSecondary"]: 32, dilation: -1}),
    "other_baker": raises(set_, {next(iter(curvature.values())): 0}),
    "unestablished": [raises(common["OutputSize"].value),
                      raises(curvature["TonemappingBounds"].value)],
    "properties": raises(cage.properties),
    "unknown_label": raises(cage.enum_value, "No such label"),
    "state": [raises(b.set_textureset_enabled, False),
              raises(b.set_enabled_bakers, [ts.MeshMapUsage.AO]),
              raises(b.is_baker_enabled, ts.MeshMapUsage.AO),
              raises(b.set_baker_enabled, ts.MeshMapUsage.AO, False),
              raises(b.set_curvature_method, baking.CurvatureMethod.FromNormalMap),
              raises(b.get_enabled_uv_tiles),
              raises(b.set_enabled_uv_tiles, []),
              raises(b.is_uv_tile_enabled, None),
              raises(b.set_uv_tile_enabled, None, True)],
    "after": [ao["NbSecondary"].value(), dilation.value(), uzpainter.project.revision() - before[0],
              sp.project.needs_saving() == before[1]],
}
"""


def test_baking_refusals_raise_before_any_change(facade: Run) -> None:
    result = ok(facade(REFUSALS))
    assert result["wrong_type"] == "ValueError: DilationWidth takes a Int value"
    assert result["bool_for_int"] == "ValueError: DilationWidth takes a Int value"
    assert result["enum_label"] == "ValueError: CageMode takes a Enum value"
    assert result["unknown_enum"] == "ValueError: CageMode has no enum value 7"
    assert result["pair_size"] == "ValueError: OutputSize takes a pair of two values"
    assert result["not_a_property"] == "TypeError: set() takes a dict keyed by Property"
    assert result["out_of_range"].startswith("NotYetSupported: DilationWidth = 100000 lies outside")
    assert result["batch"].startswith("NotYetSupported: DilationWidth = -1 lies outside")
    assert result["other_baker"] == (
        "NotYetSupported: storing the bake parameters of Curvature "
        "(owned by phase3.4_baker-curvature)"
    )
    keys = ("OutputSize", "TonemappingBounds")
    for refused, key in zip(result["unestablished"], keys, strict=True):
        assert refused.startswith(f"NotYetSupported: the default of {key} is not established")
    assert result["properties"].startswith("NotYetSupported: the meta properties of CageMode")
    assert result["unknown_label"] == "ValueError: CageMode has no enum value 'No such label'"
    for refused in result["state"]:
        assert refused.startswith("NotYetSupported: uzpainter.baking.BakingParameters."), refused
        assert refused.endswith("is a release gap (phase3.5_embree-bakers; decision 323)")
    assert result["after"] == [64, 32, 0, True]


# ── The bake job through the facade (phase3.3_baker-evidence-publication items 2.6, 3.4) ──────

BAKE_EVENTS = """
import threading
from substance_painter import baking, event
from uzpainter_facade import baking as fb
create()
t = ts.all_texture_sets()[0]
b = baking.BakingParameters.from_texture_set(t)
common, ao = b.common(), b.baker(ts.MeshMapUsage.AO)
log, stops = [], []

def on(e):
    log.append({"event": type(e).__name__, "thread": threading.get_ident(),
                "busy": sp.project.is_busy(), "progress": getattr(e, "progress", None),
                "status": getattr(getattr(e, "status", None), "name", None),
                "busy_arg": getattr(e, "busy", None)})
    if isinstance(e, event.BakingProcessAboutToStart):
        stops.append(e.stop_source)

for cls in (event.BakingProcessAboutToStart, event.BakingProcessProgress,
            event.BakingProcessEnded, event.BusyStatusChanged):
    event.DISPATCHER.connect_strong(cls, on)
# Painter's default configuration enables bakers no binding holds yet: refused before any event.
result = {"default": raises(baking.bake_async, t), "default_events": len(log),
          "type": raises(baking.bake_async, "not a texture set")}
baking.BakingParameters.set({common["OutputSize"]: (8, 8), common["LowAsHigh"]: True,
                             common["RelativeScale"]: False, ao["Attenuation"]: 0,
                             ao["MaxDistanceRelativeScale"]: False})
revision = uzpainter.project.revision()

stop = fb.start(t, [ts.MeshMapUsage.AO])
result["busy_after_call"] = sp.project.is_busy()
uzpainter.event.drain()
result["run"] = log[:]
result["same_stop"] = len(stops) == 1 and stops[0] == stop
result["late_stop"] = stop.request_stop()
result["busy_after"] = sp.project.is_busy()
result["dispatcher"] = uzpainter.event.dispatcher_thread_id()

# A stop request cancels a running bake at once; another bake meanwhile is refused (busy).
del log[:]
baking.BakingParameters.set({common["OutputSize"]: (12, 12)})
big = fb.start(t, [ts.MeshMapUsage.AO])
result["busy_refusal"] = raises(fb.start, t, [ts.MeshMapUsage.AO])
result["stop"] = big.request_stop()
uzpainter.event.drain()
result["cancelled"] = log[:]
result["late_cancel"] = big.request_stop()

# The native job: kind bake, stopped before its commit point by the parity refusal.
baking.BakingParameters.set({common["OutputSize"]: (8, 8)})
before = uzpainter.project.revision()
job = uzpainter.baking.bake_async(t.name(), [ts.MeshMapUsage.AO])
result["native"] = [job.kind, raises(job.wait), job.receipt()["stopped"],
                    job.receipt()["committed"]]
result["revision"] = [revision, before, uzpainter.project.revision()]
"""


def test_bake_async_events_busy_and_cancel(facade: Run) -> None:
    """2.6, 3.4 (decision 355): a refused configuration raises before any event; a bake delivers
    BakingProcessAboutToStart (its StopSource), BusyStatusChanged(1), progress events in [0, 1],
    BakingProcessEnded and BusyStatusChanged(0), all on the dispatcher thread, is_busy() true only
    in between. Every usage is pending-evidence, so the bake ends Fail with nothing bound (decision
    001). A stop request cancels a running bake (Ended(Cancel)) and fails once it ended."""
    result = ok(facade(BAKE_EVENTS))
    assert result["default"].startswith("NotYetSupported: publishing Curvature"), result["default"]
    assert result["default_events"] == 0
    assert result["type"] == "TypeError: bake_async takes a TextureSet"
    run = result["run"]
    names = [entry["event"] for entry in run]
    assert names[0] == "BakingProcessAboutToStart" and names[1] == "BusyStatusChanged"
    assert names[-2:] == ["BakingProcessEnded", "BusyStatusChanged"]
    progress = [entry["progress"] for entry in run if entry["event"] == "BakingProcessProgress"]
    assert progress and progress == sorted(progress) and all(0.0 <= p <= 1.0 for p in progress)
    assert set(names[2:-2]) == {"BakingProcessProgress"}
    assert [run[1]["busy_arg"], run[-1]["busy_arg"]] == [True, False]
    assert run[0]["busy"] is False and all(entry["busy"] for entry in run[1:-1])
    assert run[-2]["status"] == "Fail"
    assert {entry["thread"] for entry in run} == {result["dispatcher"]}
    assert result["busy_after_call"] is True and result["busy_after"] is False
    assert result["same_stop"] is True and result["late_stop"] is False
    assert result["busy_refusal"].startswith("BusyError"), result["busy_refusal"]
    assert result["stop"] is True and result["late_cancel"] is False
    cancelled = [entry for entry in result["cancelled"] if entry["event"] == "BakingProcessEnded"]
    assert [entry["status"] for entry in cancelled] == ["Cancel"]
    kind, error, stopped, committed = result["native"]
    assert kind == "bake" and stopped == "before_commit" and committed is None
    assert error.startswith("NotYetSupported: publishing AO of texture set"), error
    assert "pending-evidence (decision 001)" in error
    revision, before, after = result["revision"]
    assert after == before == revision + 2  # the two set() calls; no bake committed


# ── Item 3.1 on the owner's machine: the Tier 0 golden ─────────────────────────────────────────

REPLAY = """
import base64
PAYLOAD = json.loads(base64.b64decode("__PAYLOAD__").decode("utf-8"))
TRACE = {"__name__": "uzp_capability_trace"}
exec(compile(PAYLOAD["trace"], "capability_trace.py", "exec"), TRACE)
TRACE["start"]()
recorder = {"__name__": "uzp_recorder"}
with open(PAYLOAD["painter_side"], encoding="utf-8") as source:
    exec(compile(source.read(), "painter_side.py", "exec"), recorder)
OPERATIONS = recorder["OPERATIONS"]


def call(operation, **kwargs):
    return OPERATIONS[operation](kwargs)


def create():
    TRACE["mark"]("setup")
    step = PAYLOAD["create"]
    call("apply_step", step=step["step"], call=step["call"], args=step["args"],
         resolved=step["resolved"])


def recording():
    outputs = {}
    for capture in PAYLOAD["captures"]:
        TRACE["mark"](capture["output_id"])
        outputs[capture["output_id"]] = call("baking_capture", call=capture["call"],
                                             args=capture["args"])
    return outputs


create()
r1 = recording()
TRACE["mark"]("setup")
os.makedirs(os.path.dirname(PAYLOAD["save_to"]), exist_ok=True)
call("save_as", path=PAYLOAD["save_to"])
call("close_project")
call("open_project", path=PAYLOAD["save_to"])
r2 = recording()
TRACE["mark"]("setup")
call("close_project")
create()
r3 = recording()
TRACE["mark"]("setup")
call("close_project")
result = {"r1": r1, "r2": r2, "r3": r3, "trace": TRACE["stop"]()}
"""


def golden() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    store = locate()
    ref = next(r for r in manifest["private_records"] if r["record_id"] == "golden-record")
    data = None if store is None else store.load(ref["sha256"], ref["size_bytes"])
    if data is None:
        # Decision 028: the oracle comparison runs only where the private store holds the record.
        reason = f"record {ref['sha256'][:12]} is not in this machine's store"
        pytest.skip(f"oracle_unavailable: {reason}")
    return manifest, json.loads(data.decode("utf-8"))


def refused_reason(output_id: str, key: str, field: str) -> str | None:
    return REFUSED.get((output_id, key, field)) or REFUSED.get(("*", "*", field))


def compare_parameters(
    where: str, output_id: str, ours: dict[str, Any], theirs: dict[str, Any]
) -> tuple[list[str], set[tuple[str, str, str]]]:
    """Differences (names only) and the refused fields of one parameter capture."""
    differences: list[str] = []
    refused: set[tuple[str, str, str]] = set()
    if not strict(ours.get("keys"), theirs["keys"]):
        differences.append(f"{where}: keys differ")
        return differences, refused
    for key in theirs["keys"]:
        o, t = ours["properties"][key], theirs["properties"][key]
        raised = o.get("raised", {})
        for field in sorted((set(o) | set(t)) - {"raised"}):
            if field in o and field in t:
                if not strict(o[field], t[field]):
                    differences.append(f"{where} {key}: {field} differs")
            elif field in t and refused_reason(output_id, key, field) is not None:
                if raised.get(field, {}).get("type") != "NotYetSupported":
                    differences.append(f"{where} {key}: {field} not refused with NotYetSupported")
                refused.add((output_id, key, field))
            else:
                differences.append(f"{where} {key}: {field} differs")
        for field in set(raised) - {f for (_, k, f) in refused if k == key}:
            differences.append(f"{where} {key}: {field} raised")
    return differences, refused


def test_baking_defaults_equal_painter(facade: Run, tmp_path: Path) -> None:
    manifest, record = golden()
    job = job_from_manifest(json.loads(json.dumps(manifest)))
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    staged = {}
    for input_id, source in job.inputs.items():
        staged[input_id] = inputs / f"{input_id}{source.suffix}"
        staged[input_id].write_bytes(source.read_bytes())
    [create] = job.state_steps
    payload = {
        "painter_side": PAINTER_SIDE.as_posix(),
        "create": {
            "step": create.step,
            "call": create.call,
            "args": create.args,
            "resolved": {"mesh": staged[create.args["mesh"]].as_posix()},
        },
        "captures": [
            {"call": s.call, "args": s.args, "output_id": baking_output_id(s)} for s in job.captures
        ],
        "save_to": (tmp_path / "project" / "defaults.spp").as_posix(),
        "trace": SOURCE,
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    replayed = ok(facade(REPLAY.replace("__PAYLOAD__", encoded)))

    differences: list[str] = []
    refused: set[tuple[str, str, str]] = set()
    assert [r["recording_id"] for r in record["recordings"]] == list(RECORDINGS)
    for recording in record["recordings"]:
        rid = recording["recording_id"]
        assert recording["condition"] == RECORDINGS[rid]
        ours_outputs = replayed[rid]
        assert sorted(ours_outputs) == sorted(o["output_id"] for o in recording["outputs"]), rid
        for output in recording["outputs"]:
            output_id = output["output_id"]
            theirs = output["values"]["texture_sets"]
            ours = ours_outputs[output_id]["texture_sets"]
            if sorted(ours) != sorted(theirs):
                differences.append(f"{rid} {output_id}: texture sets differ")
                continue
            for name, value in theirs.items():
                where = f"{rid} {output_id} {name}"
                if isinstance(value, dict) and "keys" in value:
                    found, refusals = compare_parameters(where, output_id, ours[name], value)
                    differences += found
                    refused |= refusals
                elif not strict(ours[name], value):
                    differences.append(f"{where}: differs")
    assert differences == [], "\n".join(differences)
    every_key = {
        (o["output_id"], key, "properties")
        for o in record["recordings"][0]["outputs"]
        if isinstance(next(iter(o["values"]["texture_sets"].values())), dict)
        for key in next(iter(o["values"]["texture_sets"].values()))["keys"]
    }
    named = {k for k in REFUSED if k[0] != "*"}
    assert refused == named | every_key, sorted(refused ^ (named | every_key))
    # The refused fields raise NotYetSupported inside compared outputs: a refusal is no evidence of
    # its class, which no compared value shows.
    symbols = [s for s in exercised(replayed["trace"]) if not s.endswith(".NotYetSupported")]
    check_trace("facade/baking-defaults", manifest["golden_id"], symbols)
