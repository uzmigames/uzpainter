"""The facade's Tier 0 API-probe comparisons (task phase1.20_pyapi-facade items 3.1 and 3.7; local
run on the owner's machine, decision 028).

The recorder's own Painter-side code (`tools/parity/recorder/painter_side.py` and
`painter_probes.py`, documented `substance_painter` symbols only) runs inside UzPainter's embedded
interpreter against the facade, and replays each probe exactly as `tools.parity.recorder.probes`
records it in Painter: the state steps once, then the probe steps in the same session
(`same_session`) and again after `save_as`, `close` and `open` (`after_save_reopen`), with the
inserted nodes' effective defaults, their identities and the capture exports. Every output is then
compared exactly with the private golden of the current envelope, both recordings:

- readbacks and raised errors (class and message) by output id;
- the effective defaults of each inserted node (the golden's key);
- exported maps, decoded at native depth (`tools.parity.fit.decode`), on every texel.

Two normalisations, both Painter-internal and outside the instruction sequence (decision 107):
resource contexts are compared up to one constant session offset (`project<N>` counts the
projects a Painter session created or opened before the recording), and Painter's empty default
paint layer "Layer 1" is removed from the structure readbacks after asserting it is exactly that
layer (decision 105, phase4.1_nodes-paint-layers item 2.8).

Outputs that cannot be equal yet are listed in `EXCLUDED` with their reason and owner; a listed
output must exist in the golden, and nothing else may differ. Where no private store exists the
test skips, naming why.

A Session O golden (recorded with `OCIO` naming Painter's substance config) is replayed with the
project declaring that configuration (`OCIO_DECLARATION`): no creation path yields an OCIO project,
so the replay script makes `get_color_management` report it, and the facade applies its OCIO
profile (decision 202). The native project stays Legacy, so these replays compare readbacks only;
the OCIO evaluation and export are compared by `tests/export/test_export_encoders.py` (decision
190).
"""

from __future__ import annotations

import base64
import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.python.capability_trace import SOURCE, check_trace, exercised
from tests.python.conftest import REPO_ROOT, Run
from tools.parity.fit.decode import decode
from tools.parity.recorder.probes import INPUT_ARGS, PAINTER_PROBES, probe_job_from_manifest
from tools.parity.recorder.texture import export_roots
from tools.parity.store.store import locate

API_PROBES = (
    REPO_ROOT
    / "parity"
    / "envelopes"
    / "painter-12.1.5_js-api.1.1.20"
    / "manifests"
    / "tier0"
    / "api-probes"
)
PAINTER_SIDE = REPO_ROOT / "tools" / "parity" / "recorder" / "painter_side.py"
CONDITIONS = ("same_session", "after_save_reopen")
PAINTER_DEFAULT_LAYER = {
    "Content": [],
    "Mask": [],
    "has_mask": False,
    "name": "Layer 1",
    "node_type": "PaintLayer",
    "visible": True,
}

CONTENT_FILL = (
    "the native support check refuses a fill effect in a content stack before any change "
    "(release gap phase3.2_proc-filter-families, decision 081): this step and the steps on its node"
)
MASK_LEVELS = (
    "the native support check refuses a levels effect in a mask stack (release gap "
    "phase4.2_remaining-nodes, decision 081): this step and the steps on its node"
)
MASKED_EXPORT = (
    "the mask holds Painter's levels effect (s13, s14), which the native support check refuses "
    "(release gap phase4.2_remaining-nodes, decision 081), so the masked BaseColor differs"
)
COMPARE = (
    "the native support check refuses a compare-mask effect (release gap "
    "phase4.1_nodes-mask-effects, decision 081)"
)
UID_VALUE = (
    "a uid's value is Painter's own allocation, not part of the instruction sequence; the "
    "identity outputs compare what a uid resolves to"
)
REOPEN = "found_by lists the nodes of the refused steps"
OCIO_NATIVE = (
    "the replay's native project is Legacy (no creation path yields an OCIO project); the OCIO "
    "export is compared by tests/export/test_export_encoders.py (decision 190)"
)


def excluded(reason: str, *ids: str) -> dict[str, str]:
    return dict.fromkeys(ids, reason)


# Outputs that cannot equal Painter's yet, by probe: output id -> reason and owner. Applies to
# both recordings where the output exists (decision 107). Every other output is exact.
EXCLUDED: dict[str, dict[str, str]] = {
    "set-source-none-multichannel": {
        **excluded(
            CONTENT_FILL,
            "s5/insert_fill",
            "s6/active_channels",
            "s7/set_source",
            "s9/set_source",
            "s11/get_source",
            "s13/source_mode",
            "s14/get_type",
            "s16/get_source",
            "identity/s5",
            "defaults/s5",
        ),
        "identity/reopen": REOPEN,
    },
    "mask-stack": {
        **excluded(
            MASK_LEVELS,
            "s13/insert_levels_effect",
            "s14/set_parameters",
            "s36/mask_effects",
            "s38/get_parameters",
            "s39/affected_channel",
            "s40/get_blending_mode",
            "s41/is_in_mask_stack",
            "identity/s13",
            "defaults/s13",
        ),
        "identity/reopen": REOPEN,
        "uzp_plane/basecolor": MASKED_EXPORT,
    },
    **{
        f"phase1-srgb-uniform-decode-ocio-part{part}": excluded(OCIO_NATIVE, "uzp_plane/basecolor")
        for part in range(1, 5)
    },
    # BaseColor, BaseMetalness, Height and SpecularRoughness are exact (decisions 218 and 224).
    "phase1-fill-channel-defaults": excluded(
        "the grey bitmap on Normal (RGB16F) is refused by the evaluator "
        "(evaluator:unsupported_source): P20-A sees it only through NormalMapDetail, whose decode "
        "hides its value and whether its filter result is written as a 16-bit code "
        "(phase1.15_compositor-colour-fits item 2.9, decision 249; the recording of 8-bit grey "
        "images on Normal that decision 249 lists settles it)",
        "uzp_plane/normal",
    ),
    "phase1-delete-node": excluded(UID_VALUE, "s17/uid"),
    "phase1-resource-update": excluded(UID_VALUE, "s14/uid", "s15/uid"),
    "insert-positions": {
        **excluded(
            CONTENT_FILL,
            "s5/insert_fill",
            "s9/insert_levels_effect",
            "s12/insert_fill",
            "s18/insert_group",
            "s21/insert_compare_mask_effect",
            "s23/insert_fill",
            "s25/content_effects",
            "s28/get_type",
            "identity/s5",
            "identity/s9",
            "identity/s12",
            "defaults/s5",
            "defaults/s9",
            "defaults/s12",
        ),
        **excluded(
            MASK_LEVELS,
            "s7/insert_levels_effect",
            "s26/mask_effects",
            "identity/s7",
            "defaults/s7",
        ),
        **excluded(
            COMPARE, "s8/insert_compare_mask_effect", "s29/get_type", "identity/s8", "defaults/s8"
        ),
        "s24/get_root_layer_nodes": "the root list holds the refused effects of s5, s7-s9, s12",
        "identity/reopen": REOPEN,
    },
}


# ── The replay script (runs inside uzp-pyapi-tests.exe) ─────────────────────────────────────────

REPLAY = """
import base64
PAYLOAD = json.loads(base64.b64decode("__PAYLOAD__").decode("utf-8"))
if PAYLOAD.get("ocio_config"):
    _declared = uzpainter.colormanagement.get_color_management
    uzpainter.colormanagement.get_color_management = lambda: dict(
        _declared(), mode="ocio", config_hash=PAYLOAD["ocio_config"])
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


def run_step(step):
    TRACE["mark"](output_id(step))
    return call("probe_step", step=step["step"], call=step["call"], args=step["args"],
                resolved=step["resolved"])


def record(condition, first, uids):
    TRACE["mark"]("template/texture-sets")
    outputs = {"template/texture-sets": {"value": call("template_capture")}}
    outputs.update(first)
    for step, uid in sorted(uids.items(), key=lambda item: int(item[0])):
        TRACE["mark"](f"identity/s{step}")
        value = call("probe_identity", node_step=int(step), recorded_uid=uid)
        outputs[f"identity/s{step}"] = {"value": value}
    for step in PAYLOAD["probes"]:
        key, out = readback(output_id(step), run_step(step))
        outputs[key] = out
    files = {}
    for export_step in PAYLOAD["exports"]:
        # Each map is exported on its own, so a map the export engine refuses (a release gap)
        # does not hide the others; Painter's configuration differs only by the map list.
        for name, config in export_step[condition].items():
            TRACE["mark"]("export/" + name)
            try:
                result = sp.export.export_project_textures(config)
            except Exception as error:
                files[name] = {"raised": type(error).__name__ + ": " + str(error)}
                continue
            files[name] = sorted(f for fs in result.textures.values() for f in fs)
    return {"outputs": outputs, "files": files}


TRACE["mark"]("bookkeeping")
call("probe_reset", root=PAYLOAD["run"])
TRACE["mark"]("setup")
create = PAYLOAD["create"]
call("apply_step", step=create["step"], call=create["call"], args=create["args"],
     resolved=create["resolved"])
defaults = {"project.create": call("template_capture"), "inserted": {}}
first = {}
for step in PAYLOAD["state"]:
    outcome = run_step(step)
    if "defaults" in outcome:
        defaults["inserted"][str(step["step"])] = outcome["defaults"]
    key, out = readback(output_id(step), outcome)
    first[key] = out
TRACE["mark"]("bookkeeping")
uids = {step: int(where["uid"]) for step, where in call("probe_locations").items()}
same_session = record("same_session", first, uids)
TRACE["mark"]("bookkeeping")
locations = call("probe_locations")
TRACE["mark"]("setup")
os.makedirs(os.path.dirname(PAYLOAD["save_to"]), exist_ok=True)
call("save_as", path=PAYLOAD["save_to"])
call("close_project")
call("open_project", path=PAYLOAD["save_to"])
TRACE["mark"]("identity/reopen")
found = call("probe_rebind", locations=locations)
after = record("after_save_reopen", {"identity/reopen": {"value": found}}, uids)
TRACE["mark"]("setup")
call("close_project")
result = {"defaults": defaults, "same_session": same_session, "after_save_reopen": after,
          "trace": TRACE["stop"]()}
"""


# Session O: the colour management a replay of an OCIO golden declares (OCIO with Painter's
# substance config, decision 202).
OCIO_DECLARATION = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"


def session_o(manifest: dict[str, Any]) -> bool:
    """Whether the golden was recorded under OCIO (its applied settings name the variable)."""
    return any(s["name"] == "OCIO" for s in manifest.get("applied_settings", []))


def stage(job: Any, directory: Path) -> dict[str, Path]:
    """The inputs copied as `<input_id><suffix>`, the names Painter imported them under."""
    directory.mkdir(parents=True, exist_ok=True)
    staged: dict[str, Path] = {}
    for input_id, source in job.inputs.items():
        target = directory / f"{input_id}{source.suffix}"
        target.write_bytes(source.read_bytes())
        staged[input_id] = target
    return staged


def step_payload(step: Any, staged: dict[str, Path]) -> dict[str, Any]:
    resolved: dict[str, str] = {}
    key = INPUT_ARGS.get(step.call)
    if key is not None and key in step.args:
        resolved[key] = staged[step.args[key]].as_posix()
    return {"step": step.step, "call": step.call, "args": step.args, "resolved": resolved}


def golden_record(probe: str) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads((API_PROBES / f"{probe}.json").read_text(encoding="utf-8"))
    store = locate()
    if store is None:
        pytest.skip("no private oracle store on this machine (decision 028)")
    record = next(r for r in manifest["private_records"] if r["record_id"] == "golden-record")
    data = store.load(record["sha256"])
    assert data is not None, f"{probe}: the golden record is not in the private store"
    return manifest, json.loads(data)


def replay(facade: Run, probe: str, work: Path) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """The facade's outputs of `probe`, the golden record and the probe job."""
    manifest, golden = golden_record(probe)
    job = probe_job_from_manifest(json.loads(json.dumps(manifest)))
    staged = stage(job, work / "inputs")
    template = next(
        o["values"] for o in golden["recordings"][0]["outputs"] if o["kind"] == "template_capture"
    )
    roots = [ts if not st else f"{ts}/{st}" for ts, st in export_roots(template)]
    exports = [
        {
            condition: {
                f"{export.step}/{out.name}": dataclasses.replace(export, maps=(out,)).config(
                    work / condition / f"export-step{export.step}-{index}", roots
                )
                for index, out in enumerate(export.maps)
            }
            for condition in CONDITIONS
        }
        for export in job.exports
    ]
    payload = {
        "painter_side": PAINTER_SIDE.as_posix(),
        "painter_probes": PAINTER_PROBES.as_posix(),
        "run": work.as_posix(),
        "create": {
            **step_payload(job.create, staged),
            "resolved": {"mesh": staged[job.create.args["mesh"]].as_posix()},
        },
        "state": [step_payload(s, staged) for s in job.state_steps],
        "probes": [step_payload(s, staged) for s in job.probe_steps],
        "exports": exports,
        "save_to": (work / "project" / "probe.spp").as_posix(),
        "trace": SOURCE,
        "ocio_config": OCIO_DECLARATION if session_o(manifest) else None,
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    report = facade(REPLAY.replace("__PAYLOAD__", encoded))
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    return report["result"], golden, job


# ── Normalisation and comparison ────────────────────────────────────────────────────────────────

CONTEXT = re.compile(r"^project(\d+)$")


def contexts(value: Any, found: set[int]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "context" and isinstance(item, str) and CONTEXT.match(item):
                found.add(int(item[len("project") :]))
            else:
                contexts(item, found)
    elif isinstance(value, list):
        for item in value:
            contexts(item, found)


def shift_contexts(value: Any, base: int) -> Any:
    """Resource contexts renumbered from the session's first project (decision 107)."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "context" and isinstance(item, str) and CONTEXT.match(item):
                out[key] = f"project{int(item[len('project') :]) - base}"
            else:
                out[key] = shift_contexts(item, base)
        return out
    if isinstance(value, list):
        return [shift_contexts(item, base) for item in value]
    return value


def normalised(outputs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    found: set[int] = set()
    contexts(outputs, found)
    return shift_contexts(outputs, min(found)) if found else outputs


def without_default_layer(value: Any) -> Any:
    """A structure readback without Painter's empty default paint layer (asserted to be it)."""
    if isinstance(value, list) and value and value[-1] == PAINTER_DEFAULT_LAYER:
        return value[:-1]
    return value


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
            if o["output_id"].endswith("/get_root_layer_nodes"):
                entry["value"] = without_default_layer(entry["value"])
            outputs[o["output_id"]] = entry
        out[recording["condition"]] = normalised(outputs)
    return out


def map_differences(
    golden: dict[str, Any], replayed: dict[str, Any], job: Any, work: Path
) -> list[str]:
    """Exported maps that differ from Painter's on any texel (both recordings)."""
    store = locate()
    assert store is not None
    differences: list[str] = []
    maps = {(e.step, m.name): m for e in job.exports for m in e.maps}
    for recording in golden["recordings"]:
        condition = recording["condition"]
        for o in recording["outputs"]:
            if o["kind"] != "exported_map":
                continue
            step = int(o["export_settings"]["step"])
            out = maps[(step, o["map"])]
            stem = out.file_name.replace("$textureSet", o["texture_set"])
            exported = replayed[condition]["files"][f"{step}/{o['map']}"]
            if isinstance(exported, dict):
                differences.append(f"{condition} {o['output_id']}: {exported['raised']}")
                continue
            written = [Path(f) for f in exported if Path(f).stem == stem]
            if len(written) != 1:
                differences.append(f"{condition} {o['output_id']}: not exported ({written})")
                continue
            expected = store.load(o["blob"]["sha256"])
            assert expected is not None, f"golden blob {o['blob']['sha256']} is not in the store"
            ours, theirs = decode(written[0].read_bytes()), decode(expected)
            same = ours.values.shape == theirs.values.shape and bool(
                np.array_equal(ours.values, theirs.values)
            )
            if not same:
                differences.append(f"{condition} {o['output_id']}: differs from Painter's map")
    return differences


def compare(probe: str, facade: Run, work: Path) -> list[str]:
    replayed, golden, job = replay(facade, probe, work)
    excluded = EXCLUDED.get(probe, {})
    expected = golden_outputs(golden)
    differences: list[str] = []
    for condition in CONDITIONS:
        ours = normalised(replayed[condition]["outputs"])
        theirs = {
            k: v
            for k, v in expected[condition].items()
            if probe not in (*R10_PROBES, *DECODE_PROBES, DEFAULTS_PROBE)
            or not k.endswith(("/events", "/states"))
        }
        for output_id, value in ours.items():
            if output_id.endswith("/get_root_layer_nodes"):
                value = {**value, "value": without_default_layer(value["value"])}
            if output_id in excluded:
                continue
            painter = theirs.get(output_id)
            if painter != value:
                differences.append(
                    f"{condition} {output_id}: facade {value!r} != Painter {painter!r}"
                )
        for output_id in theirs:
            if output_id not in ours and output_id not in excluded:
                differences.append(f"{condition} {output_id}: not replayed")
    inserted = golden["key"]["effective_defaults"]["inserted"]
    for step, value in replayed["defaults"]["inserted"].items():
        key = f"defaults/s{step}"
        if key not in excluded and inserted.get(step) != value:
            differences.append(f"{key}: facade {value!r} != Painter {inserted.get(step)!r}")
    differences += [
        d
        for d in map_differences(golden, replayed, job, work)
        if d.split()[1].rstrip(":") not in excluded
    ]
    recorded = {o["output_id"] for r in golden["recordings"] for o in r["outputs"]}
    recorded |= {f"defaults/s{step}" for step in inserted}
    for output_id in excluded:
        assert output_id in recorded, f"{probe}: the excluded output {output_id} is not recorded"
    # An excluded exported map's export call is not compared either: its symbols are no evidence.
    excluded_exports = {
        f"export/{o['export_settings']['step']}/{o['map']}"
        for r in golden["recordings"]
        for o in r["outputs"]
        if o["kind"] == "exported_map" and o["output_id"] in excluded
    }
    if not differences:
        golden_id = f"tier0/api-probes/{probe}"
        symbols = exercised(replayed["trace"], {*excluded, *excluded_exports})
        check_trace(f"facade/{probe}", golden_id, symbols)
    return differences


QUIRK_PROBES = (
    "active-channel-reset",
    "active-channel-reset-superset",
    "active-channel-order-control",
    "set-source-none-multichannel",
    "mask-stack",
    "insert-positions",
)
READBACK_PROBES = ("fill-layer-readback", "textureset-project-readback")
# The R10 probes of the project, layer and resource operations (decision 100): their readbacks,
# events aside (test_pyapi_lifecycle_tier0.py compares the observed ones), and exported maps.
R10_PROBES = ("phase1-create-settings", "phase1-delete-node", "phase1-resource-update")
# P20-B's OCIO twin (decisions 198 and 202): the 256 greys c / 255 and 64 random colours set in sRGB
# on BaseColor and read back in the working space, events aside, under OCIO.
OCIO_DECODE_PROBES = tuple(f"phase1-srgb-uniform-decode-ocio-part{part}" for part in range(1, 5))
# P20-B in Legacy (decisions 205 and 214): the same colours, Legacy colour management.
LEGACY_DECODE_PROBES = tuple(f"phase1-srgb-uniform-decode-part{part}" for part in range(1, 5))
DECODE_PROBES = (*OCIO_DECODE_PROBES, *LEGACY_DECODE_PROBES)
# P20-A (decisions 198 and 214): a fresh fill's default source on the default template's five
# channels, and the default and available colour spaces of a colour and a grey bitmap on each and
# in a mask, with every channel exported; events aside.
DEFAULTS_PROBE = "phase1-fill-channel-defaults"


@pytest.mark.parametrize("probe", QUIRK_PROBES)
def test_facade_quirk_probe_equals_painter(facade: Run, tmp_path: Path, probe: str) -> None:
    """Item 3.1: the active-channel reset, the mask-stack None rules, the insertion rules and
    `EditionContextException` on `set_source(None, ...)`."""
    differences = compare(probe, facade, tmp_path)
    assert differences == [], "\n".join(differences)


@pytest.mark.parametrize("probe", READBACK_PROBES)
def test_facade_shaped_readbacks_equal_painter(facade: Run, tmp_path: Path, probe: str) -> None:
    """Item 3.7: working-space colours, the available colour spaces, Painter's resource ids and the
    `.spp` file name (decision 106)."""
    differences = compare(probe, facade, tmp_path)
    assert differences == [], "\n".join(differences)


@pytest.mark.parametrize("probe", R10_PROBES)
def test_facade_r10_probe_equals_painter(facade: Run, tmp_path: Path, probe: str) -> None:
    """phase1.22 item 2.5: create settings, delete_node and update_layer_stack_resource, compared
    like the readback probes so their entries cite Tier 0 evidence (decision 112)."""
    differences = compare(probe, facade, tmp_path)
    assert differences == [], "\n".join(differences)


@pytest.mark.parametrize("probe", OCIO_DECODE_PROBES)
def test_facade_ocio_uniform_decode_equals_painter(facade: Run, tmp_path: Path, probe: str) -> None:
    """phase1.15 item 2.6 (decision 202): under OCIO with Painter's substance config every sRGB
    uniform colour reads back Painter's working value, both recordings."""
    differences = compare(probe, facade, tmp_path)
    assert differences == [], "\n".join(differences)


@pytest.mark.parametrize("probe", LEGACY_DECODE_PROBES)
def test_facade_legacy_uniform_decode_equals_painter(
    facade: Run, tmp_path: Path, probe: str
) -> None:
    """phase1.15 item 2.1 (decision 214): in Legacy every sRGB uniform colour reads back Painter's
    float32 decode and exports Painter's BaseColor, both recordings."""
    differences = compare(probe, facade, tmp_path)
    assert differences == [], "\n".join(differences)


def test_facade_fill_channel_defaults_equal_painter(facade: Run, tmp_path: Path) -> None:
    """phase1.15 items 2.1, 2.7 and 2.9 (decisions 214, 218, 224 and 249): a fill's default sources
    after the active-channel reset, the bitmaps' default and available colour spaces, and four
    maps, both recordings: BaseColor (the 8-bit sRGB checker magnified 16 times through the sRGB8
    texture filter), BaseMetalness, Height and SpecularRoughness (the colour checker on L8 and L16F
    and as a mask source). Normal is `EXCLUDED`: its grey bitmap is refused (decision 249)."""
    differences = compare(DEFAULTS_PROBE, facade, tmp_path)
    assert differences == [], "\n".join(differences)


# ── Colour rules: the readbacks of R5 and its Legacy twin (items 3.6, 3.7) ─────────────────────

SEMANTICS = API_PROBES.parent / "semantics"
# Every readback of both is exact: decision 107's 70/255 residual is Painter's Legacy decode, fitted
# from P20-B (decision 214).
COLOUR_GOLDENS: dict[str, dict[str, str]] = {
    "export-ocio-encode-legacy": {},
    "export-ocio-encode": {},
}

TEXTURE_REPLAY = """
import base64
PAYLOAD = json.loads(base64.b64decode("__PAYLOAD__").decode("utf-8"))
if PAYLOAD.get("ocio_config"):
    _declared = uzpainter.colormanagement.get_color_management
    uzpainter.colormanagement.get_color_management = lambda: dict(
        _declared(), mode="ocio", config_hash=PAYLOAD["ocio_config"])
TRACE = {"__name__": "uzp_capability_trace"}
exec(compile(PAYLOAD["trace"], "capability_trace.py", "exec"), TRACE)
TRACE["start"]()
recorder = {"__name__": "uzp_recorder"}
with open(PAYLOAD["painter_side"], encoding="utf-8") as source:
    exec(compile(source.read(), "painter_side.py", "exec"), recorder)
OPERATIONS = recorder["OPERATIONS"]


def call(operation, **kwargs):
    return OPERATIONS[operation](kwargs)


def outcome(spec):
    try:
        return {"value": call("readback", call=spec["call"], args=spec["args"])}
    except Exception as error:
        return {"value": None, "raised": {"type": repr(error).split("(", 1)[0],
                                          "message": str(error)}}


def record(condition):
    TRACE["mark"]("template/texture-sets")
    outputs = {"template/texture-sets": {"value": call("template_capture")}}
    for spec in PAYLOAD["readbacks"]:
        TRACE["mark"](spec["output_id"])
        outputs[spec["output_id"]] = outcome(spec)
    files = {}
    for name, config in PAYLOAD["exports"].get(condition, {}).items():
        TRACE["mark"]("export/" + name)
        try:
            exported = sp.export.export_project_textures(config)
        except Exception as error:
            files[name] = {"raised": type(error).__name__ + ": " + str(error)}
            continue
        files[name] = sorted(f for fs in exported.textures.values() for f in fs)
    TRACE["mark"]("setup")
    return {"outputs": outputs, "files": files}


for step in PAYLOAD["state"]:
    call("apply_step", step=step["step"], call=step["call"], args=step["args"],
         resolved=step["resolved"])
same_session = record("same_session")
TRACE["mark"]("bookkeeping")
locations = call("node_locations")
TRACE["mark"]("setup")
os.makedirs(os.path.dirname(PAYLOAD["save_to"]), exist_ok=True)
call("save_as", path=PAYLOAD["save_to"])
call("close_project")
call("open_project", path=PAYLOAD["save_to"])
call("rebind_nodes", locations=locations)
after = record("after_save_reopen")
call("close_project")
result = {"same_session": same_session, "after_save_reopen": after, "trace": TRACE["stop"]()}
"""


def texture_replay(
    facade: Run, name: str, work: Path, exports: bool
) -> tuple[dict[str, Any], dict[str, Any], Any, list[dict[str, Any]]]:
    """The facade's replay of the semantics golden `name` with the recorder's own Painter-side
    code: its readbacks and, with `exports`, its exported maps (each export step as Painter ran it),
    both recordings. Returns the replay, the golden record, the job and the readback specs."""
    from tools.parity.recorder.job import API_CAPTURES, job_from_manifest
    from tools.parity.recorder.job import INPUT_ARGS as JOB_INPUTS
    from tools.parity.recorder.texture import output_safe

    manifest = json.loads((SEMANTICS / f"{name}.json").read_text(encoding="utf-8"))
    store = locate()
    if store is None:
        pytest.skip("no private oracle store on this machine (decision 028)")
    record = next(r for r in manifest["private_records"] if r["record_id"] == "golden-record")
    data = store.load(record["sha256"])
    assert data is not None, f"{name}: the golden record is not in the private store"
    golden = json.loads(data)
    job = job_from_manifest(manifest)
    staged = stage(job, work / "inputs")

    def resolved(step: Any) -> dict[str, str]:
        key = JOB_INPUTS.get(step.call)
        return {key: staged[step.args[key]].as_posix()} if key and key in step.args else {}

    def readback_id(spec: dict[str, Any]) -> str:
        parts = [output_safe(str(v)) for v in spec["args"].values()]
        return "/".join(["readback", spec["call"].rsplit(".", 1)[1], *parts])

    readbacks = [{**spec, "output_id": readback_id(spec)} for spec in job.readback_specs()]
    readbacks += [
        {
            "call": capture.call,
            "args": dict(capture.args),
            "output_id": f"{API_CAPTURES[capture.call][0]}/s{capture.step}",
        }
        for capture in job.api_captures
    ]
    configs: dict[str, dict[str, Any]] = {}
    if exports:
        template = next(
            o["values"]
            for o in golden["recordings"][0]["outputs"]
            if o["kind"] == "template_capture"
        )
        roots = [ts if not st else f"{ts}/{st}" for ts, st in export_roots(template)]
        configs = {
            condition: {
                str(export.step): export.config(
                    work / condition / f"export-step{export.step}", roots
                )
                for export in job.exports
            }
            for condition in CONDITIONS
        }
    payload = {
        "painter_side": PAINTER_SIDE.as_posix(),
        "state": [
            {"step": s.step, "call": s.call, "args": s.args, "resolved": resolved(s)}
            for s in job.state_steps
        ],
        "readbacks": readbacks,
        "exports": configs,
        "save_to": (work / "project" / "probe.spp").as_posix(),
        "trace": SOURCE,
        "ocio_config": OCIO_DECLARATION if session_o(manifest) else None,
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    report = facade(TEXTURE_REPLAY.replace("__PAYLOAD__", encoded))
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    replayed: dict[str, Any] = report["result"]
    for condition in CONDITIONS:  # each export step wrote all its maps: index them by map
        files = replayed[condition]["files"]
        replayed[condition]["files"] = {
            f"{export.step}/{out.name}": files[str(export.step)]
            for export in job.exports
            for out in export.maps
            if str(export.step) in files
        }
    return replayed, golden, job, readbacks


@pytest.mark.parametrize("colour_golden", COLOUR_GOLDENS)
def test_colour_rule_readbacks_equal_painter(
    facade: Run, tmp_path: Path, colour_golden: str
) -> None:
    """Items 3.6 and 3.7: a uniform colour as sRGB, without a space (sRGB on BaseColor, Raw on the
    data channels) and as Raw, read back in the working space; bitmap colour spaces and the lists
    Painter offers on BaseColor and in a mask (`export-ocio-encode-legacy` readbacks and colour-
    space captures, both recordings; under OCIO `export-ocio-encode`, phase1.15 item 2.6, decision
    202). Their exported maps are compositor and export fits outside this test (decisions 107 and
    190)."""
    excluded = COLOUR_GOLDENS[colour_golden]
    replayed, golden, _, readbacks = texture_replay(facade, colour_golden, tmp_path, False)
    expected = golden_outputs(golden)
    differences = []
    compared = 0
    for condition in CONDITIONS:
        ours = normalised(replayed[condition]["outputs"])
        for output_id, painter in expected[condition].items():
            if output_id not in ours:
                continue  # the export probes and exported maps: compositor and export fits
            if output_id in excluded:
                assert ours[output_id] != painter, f"{output_id} is equal now: drop its exclusion"
                continue
            compared += 1
            if ours[output_id] != painter:
                differences.append(f"{condition} {output_id}: {ours[output_id]} != {painter}")
    assert differences == [], "\n".join(differences)
    assert compared == 2 * (len(readbacks) + 1 - len(excluded))
    symbols = exercised(replayed["trace"], excluded)
    check_trace(f"facade/{colour_golden}", f"tier0/semantics/{colour_golden}", symbols)


# ── Uniform colours composite as given (decision 115) ─────────────────────────────────────────

RAMPS = ("colour-ramps-srgb", "colour-ramps-working", "colour-ramps-raw")


@pytest.mark.parametrize("golden_name", RAMPS)
def test_uniform_colour_ramps_export_as_painter(
    facade: Run, tmp_path: Path, golden_name: str
) -> None:
    """Decision 115: the colour ramps of the documented spaces sRGB, Working and Raw (288 values
    on RGB16 and sRGB8 user channels over 24 texture sets) replayed through the facade with the
    recorder's own code: every exported map equals Painter's on every texel, both recordings,
    because the facade stores a colour as given and Painter composites it as given; every
    `get_source` readback (the working value) equals Painter's."""
    replayed, golden, job, readbacks = texture_replay(facade, golden_name, tmp_path, True)
    expected = golden_outputs(golden)
    differences = []
    for condition in CONDITIONS:
        ours = normalised(replayed[condition]["outputs"])
        for output_id, painter in expected[condition].items():
            if output_id in ours and ours[output_id] != painter:
                differences.append(f"{condition} {output_id}: {ours[output_id]} != {painter}")
    differences += map_differences(golden, replayed, job, tmp_path)
    assert differences == [], "\n".join(differences[:40])
    maps = sum(1 for r in golden["recordings"] for o in r["outputs"] if o["kind"] == "exported_map")
    assert maps == 2 * 24 * 8 and len(readbacks) == 216
    check_trace(
        f"facade/{golden_name}", f"tier0/semantics/{golden_name}", exercised(replayed["trace"])
    )


# ── Project templates (decision 116) ────────────────────────────────────────────────────────────

TEMPLATES = API_PROBES.parent / "defaults-templates" / "project-templates.json"
# The channels whose label Painter's template sets: the labels are Painter's own text, which
# UzPainter does not ship (clean room, decision 116); they read back "" and change no texture.
LABELS = {("templates/Dota 2.spt", f"User{i}") for i in range(4)}

TEMPLATE_REPLAY = """
import base64
PAYLOAD = json.loads(base64.b64decode("__PAYLOAD__").decode("utf-8"))
if PAYLOAD.get("ocio_config"):
    _declared = uzpainter.colormanagement.get_color_management
    uzpainter.colormanagement.get_color_management = lambda: dict(
        _declared(), mode="ocio", config_hash=PAYLOAD["ocio_config"])
TRACE = {"__name__": "uzp_capability_trace"}
exec(compile(PAYLOAD["trace"], "capability_trace.py", "exec"), TRACE)
TRACE["start"]()
recorder = {"__name__": "uzp_recorder"}
with open(PAYLOAD["painter_side"], encoding="utf-8") as source:
    exec(compile(source.read(), "painter_side.py", "exec"), recorder)
# The shelf the recorder finds the shipped templates in: a folder of empty files with the shipped
# names (UzPainter never reads a template file; Painter's shelf is a recording P21-D gap).
recorder["application_shelf_root"] = lambda: PAYLOAD["shelf"]
OPERATIONS = recorder["OPERATIONS"]


def call(operation, **kwargs):
    return OPERATIONS[operation](kwargs)


out = {"same_session": {}, "after_save_reopen": {}}
for step in PAYLOAD["steps"]:
    output_id = PAYLOAD["output_ids"][str(step["step"])]
    TRACE["mark"](output_id)
    call("apply_step", step=step["step"], call=step["call"], args=step["args"],
         resolved={"mesh": PAYLOAD["mesh"]})
    out["same_session"][output_id] = {"template": step["args"]["template"], "accepted": True,
                                      **call("template_capture")}
    TRACE["mark"]("setup")
    path = PAYLOAD["work"] + "/template-" + str(step["step"]) + ".spp"
    call("save_as", path=path)
    call("close_project")
    call("open_project", path=path)
    TRACE["mark"](output_id)
    out["after_save_reopen"][output_id] = {"template": step["args"]["template"], "accepted": True,
                                           **call("template_capture")}
    TRACE["mark"]("setup")
    call("close_project")
result = {**out, "trace": TRACE["stop"]()}
"""


def test_project_templates_equal_painter(facade: Run, tmp_path: Path) -> None:
    """Decision 116: every project template shipped with Painter 12.1, created through the facade
    by the recorder's own `project.create(template_file_path=...)` code, gives Painter's texture
    sets, stacks, channels and formats, as created and after save and reopen
    (`defaults-templates/project-templates`, both recordings)."""
    from tools.parity.recorder.defaults import template_output_id
    from tools.parity.recorder.job import job_from_manifest

    manifest = json.loads(TEMPLATES.read_text(encoding="utf-8"))
    store = locate()
    if store is None:
        pytest.skip("no private oracle store on this machine (decision 028)")
    record = next(r for r in manifest["private_records"] if r["record_id"] == "golden-record")
    data = store.load(record["sha256"])
    assert data is not None, "project-templates: the golden record is not in the private store"
    golden = json.loads(data)
    job = job_from_manifest(manifest)
    staged = stage(job, tmp_path / "inputs")
    shelf = tmp_path / "shelf"
    steps = list(job.state_steps)  # one project.create per shipped template
    for step in steps:
        empty = shelf.joinpath(*str(step.args["template"]).split("/"))
        empty.parent.mkdir(parents=True, exist_ok=True)
        empty.write_bytes(b"")
    payload: dict[str, Any] = {
        "painter_side": PAINTER_SIDE.as_posix(),
        "steps": [{"step": s.step, "call": s.call, "args": s.args} for s in steps],
        "output_ids": {str(s.step): template_output_id(str(s.args["template"])) for s in steps},
        "mesh": staged["plane"].as_posix(),
        "shelf": shelf.as_posix(),
        "work": tmp_path.as_posix(),
        "trace": SOURCE,
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    report = facade(TEMPLATE_REPLAY.replace("__PAYLOAD__", encoded))
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    replayed = report["result"]
    differences = []
    labelled = set()
    compared = 0
    for recording in golden["recordings"]:
        ours = replayed[recording["condition"]]
        for o in recording["outputs"]:
            if o["output_id"] not in payload["output_ids"].values():
                continue  # the shelf enumeration: Painter's shelf is a named gap (P21-D)
            compared += 1
            painter = json.loads(json.dumps(o["values"]))
            for stacks in painter["texture_sets"].values():
                for channels in stacks["stacks"].values():
                    for name, channel in channels.items():
                        if channel["label"]:  # Painter's own text, not shipped (LABELS)
                            labelled.add((o["values"]["template"], name))
                            channel["label"] = ""
            if ours.get(o["output_id"]) != painter:
                differences.append(f"{recording['condition']} {o['output_id']} differs")
    assert differences == [], "\n".join(differences)
    assert compared == 2 * 26
    assert labelled == LABELS
    check_trace(
        "facade/project-templates",
        "tier0/defaults-templates/project-templates",
        exercised(replayed["trace"]),
    )
