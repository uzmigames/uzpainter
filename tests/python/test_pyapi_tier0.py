"""Tier 0 API-probe readbacks owned by the native API, compared exactly with Painter's goldens
(task phase1.19_pyapi-native-module item 3.2; local run on the owner's machine, decision 028).

The native API replays the state steps of the `fill-layer-readback` and
`textureset-project-readback` probes (`parity/envelopes/<current>/manifests/tier0/api-probes/`) and
reads back, in the golden's value shapes, every output that needs no facade rule: the template's
channels, names, visibility, node types, active channels, source mode, blending modes and
opacities, bitmap colour space, projection mode and UV parameters, the stack structure, uid
identity, resolutions, mesh-map bindings and the project state. Both recordings are compared:
`same_session` before saving and `after_save_reopen` after `save_as`, `close` and `open`.

Outputs that need a facade rule are compared by phase1.20_pyapi-facade: uniform colours (Painter
reads them back converted to the working space), the available colour spaces, and Painter's own
resource ids (context and version are Painter's internal identifiers; the native readback is
compared by resource name). The project file's extension is `.uzp`, not `.spp` (only the stem is
compared). Painter's new stack holds an empty paint layer, "Layer 1", which the native project does
not create (decision 105); the structure readback is compared without it. Where no private oracle
store exists the test skips, naming why.

The `fill-layer-readback` replay reaches Painter's outputs through UzPainter's own operations
(phase1.24, decision 115): its state steps are one native `Transaction` whose result's created ids
address the identity readbacks, the other readbacks find their nodes by name (LAY-06), the stack is
found again by its uid after reopening, and its Height map is exported through the dry-run plan, a
queued export job and its wait, then compared with Painter's on every texel.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.python.capability_trace import check_trace, exercised, traced
from tests.python.conftest import REPO_ROOT, Run
from tools.parity.fit.decode import decode
from tools.parity.recorder.probes import probe_job_from_manifest
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

# Common readback helpers of both replays (values in the golden's shapes).
HELPERS = """
def node_tree(node):
    out = {
        "Content": [node_tree(e) for e in node.content_effects()]
        if isinstance(node, ls.LayerNode)
        else [],
        "Mask": [node_tree(e) for e in node.mask_effects()]
        if isinstance(node, ls.LayerNode)
        else [],
        "has_mask": node.has_mask() if isinstance(node, ls.LayerNode) else False,
        "name": node.get_name(),
        "node_type": node.get_type().name,
        "visible": node.is_visible(),
    }
    if isinstance(node, ls.GroupLayerNode):
        out["Substack"] = [node_tree(x) for x in node.sub_layers()]
    return out


def template():
    sets = {}
    for t in ts.all_texture_sets():
        stacks = {}
        for s in t.all_stacks():
            stacks[s.name()] = {
                c.name: {
                    "bit_depth": ch.bit_depth(),
                    "format": ch.format().name,
                    "is_color": ch.is_color(),
                    "is_floating": ch.is_floating(),
                    "label": ch.label(),
                }
                for c, ch in s.all_channels().items()
            }
        r = t.get_resolution()
        sets[t.name()] = {"resolution": [r.width, r.height], "stacks": stacks}
    return {"texture_sets": sets}
"""

FILL_LAYER_READBACK = (
    HELPERS
    + """
stack = create()
stack_uid = stack.uid()
outputs = {"same_session": {}, "after_save_reopen": {}}
# The probe's state steps as one native Transaction (decision 115): the revision's created ids
# address the nodes the identity outputs read back.
transaction = uzpainter.Transaction("fill-layer-readback")
transaction.__enter__()
fill = ls.insert_fill(top(stack))
fill.set_name("uzp fill A")
fill.active_channels = {CT.BaseColor, CT.SpecularRoughness, CT.BaseMetalness, CT.Height}
fill.set_source(CT.BaseColor, cm.Color(0.8, 0.2, 0.1, "sRGB"))
fill.set_source(CT.SpecularRoughness, cm.Color(0.35, 0.35, 0.35, "Raw"))
fill.set_source(CT.BaseMetalness, cm.Color(1.0, 1.0, 1.0, "Raw"))
fill.set_source(CT.Height, cm.Color(0.25, 0.25, 0.25, "Raw"))
fill.set_blending_mode(ls.BlendingMode.LinearDodge, CT.Height)
fill.set_opacity(0.85, CT.BaseColor)
group = ls.insert_group(top(stack))
group.set_name("uzp group")
group.set_blending_mode(ls.BlendingMode.Normal, CT.Height)
inner = ls.insert_fill(ls.InsertPosition.inside_node(group, ls.NodeStack.Substack))
inner.set_visible(False)
checker = resource.import_project_resource(
    IMAGES + "/checker-16.png", resource.Usage.TEXTURE, "checker"
)
inner.active_channels = {CT.BaseColor}
inner.set_source(CT.BaseColor, checker.identifier()).set_color_space("sRGB")
inner.set_projection_mode(ls.ProjectionMode.UV)
inner.set_projection_parameters(ls.UVProjectionParams(
    filtering_mode=ls.FilteringMode.BilinearHQ, uv_wrapping_mode=ls.UVWrapMode.RepeatNone,
    uv_transformation=ls.UVTransformationParams(scale_mode=ls.ScaleMode.Factors, scale=[1.0, 1.0],
                                                rotation=0.0, offset=[0.0, 0.0])))
transaction.__exit__(None, None, None)
recorded = dict(zip((2, 11, 14), transaction.result.created))

def readback(out, stack):
    for step, uid in recorded.items():
        node = ls.get_node_by_uid(uid)
        out[f"identity/s{step}"] = {"present": True, "uid_resolves_to_node": node.uid() == uid,
                                    "uid_same_as_recorded": node.uid() == uid}
    # The other readbacks address the nodes by name (LAY-06).
    f = ls.get_node_by_name("uzp fill A", stack=stack)
    g = ls.get_node_by_name("uzp group", stack=stack)
    (i,) = ls.find_nodes_by_name("Fill")
    p = i.get_projection_parameters()
    t = p.uv_transformation
    out["template/texture-sets"] = template()
    out.update({
        # The names are read through the created ids, every other value through the names.
        "s22/get_name": ls.get_node_by_uid(recorded[2]).get_name(),
        "s23/get_name": ls.get_node_by_uid(recorded[11]).get_name(),
        "s24/get_name": ls.get_node_by_uid(recorded[14]).get_name(),
        "s25/is_visible": f.is_visible(), "s26/is_visible": i.is_visible(),
        "s27/get_type": g.get_type().name,
        "s28/active_channels": sorted(c.name for c in f.active_channels),
        "s29/source_mode": f.source_mode().name,
        "s34/get_blending_mode": f.get_blending_mode(CT.BaseColor).name,
        "s35/get_blending_mode": f.get_blending_mode(CT.Height).name,
        "s36/get_opacity": f.get_opacity(CT.BaseColor), "s37/get_opacity": f.get_opacity(CT.Height),
        "s38/get_blending_mode": g.get_blending_mode(CT.Height).name,
        "s39/sub_layers": [node_tree(x) for x in g.sub_layers()],
        "s40/active_channels": sorted(c.name for c in i.active_channels),
        "s42/get_color_space": i.get_source(CT.BaseColor).get_color_space(),
        "s44/get_projection_mode": i.get_projection_mode().name,
        "s45/get_projection_parameters": {
            "class": "UVProjectionParams", "filtering_mode": p.filtering_mode.name,
            "uv_transformation": {"offset": list(t.offset), "rotation": t.rotation,
                                  "scale": list(t.scale),
                                  "scale_mode": t.scale_mode.name},
            "uv_wrapping_mode": p.uv_wrapping_mode.name},
        "s46/get_root_layer_nodes": [node_tree(x) for x in ls.get_root_layer_nodes(stack)],
    })

def exports(out):
    # Each map through the dry-run plan, a queued export job and its wait.
    for name, config in EXPORTS.items():
        (planned,) = export.plan(config)["files"]
        job = export.start(config)
        written = {f["relative_path"]: f["path"] for f in job.wait()["files"]}
        out["export/" + name] = written[planned["relativePath"]]


readback(outputs["same_session"], stack)
exports(outputs["same_session"])
path = WORK + "/readback.uzp"
project.save_as(path)
project.close()
project.open(path)
(stack,) = [s for s in ts.all_texture_sets()[0].all_stacks() if s.uid() == stack_uid]
readback(outputs["after_save_reopen"], stack)
exports(outputs["after_save_reopen"])
project.close()
result = outputs
"""
)

TEXTURESET_PROJECT_READBACK = (
    HELPERS
    + """
outputs = {"same_session": {}, "after_save_reopen": {}}

def state():
    create()
    ts.set_resolutions(ts.all_texture_sets(), ts.Resolution(512, 512))
    texture = resource.Usage.TEXTURE
    normal = resource.import_project_resource(IMAGES + "/normal-flat.png", texture, "normal_flat")
    ao = resource.import_project_resource(IMAGES + "/ao-white.png", texture, "ao_white")
    tset = ts.all_texture_sets()[0]
    tset.set_mesh_map_resource(ts.MeshMapUsage.Normal, normal.identifier())
    tset.set_mesh_map_resource(ts.MeshMapUsage.AO, ao.identifier())
    return normal

def readback(out, normal):
    tset = ts.all_texture_sets()[0]
    tset.set_mesh_map_resource(ts.MeshMapUsage.Curvature, normal.identifier())   # step 7, a probe
    r = tset.get_resolution()
    path = project.file_path()
    out.update({
        "template/texture-sets": template(),
        "s8/get_resolution": [r.width, r.height],
        "s9/get_mesh_map_resource": tset.get_mesh_map_resource(ts.MeshMapUsage.Normal).name,
        "s10/get_mesh_map_resource": tset.get_mesh_map_resource(ts.MeshMapUsage.AO).name,
        "s11/get_mesh_map_resource": tset.get_mesh_map_resource(ts.MeshMapUsage.Curvature).name,
        "s12/needs_saving": project.needs_saving(),
        "s13/file_path": (
            {"is_none": True}
            if path is None
            else {"stem": os.path.splitext(os.path.basename(path))[0]}
        ),
        "s14/name": project.name(),
    })

normal = state()
readback(outputs["same_session"], normal)
project.close()
normal = state()
project.save_as(WORK + "/probe.uzp")
project.close()
project.open(WORK + "/probe.uzp")
readback(outputs["after_save_reopen"], normal)
project.close()
result = outputs
"""
)


def golden_outputs(probe: str) -> dict[str, dict[str, Any]]:
    """`{condition: {output_id: value}}` of the probe's private golden record."""
    manifest = json.loads((API_PROBES / f"{probe}.json").read_text(encoding="utf-8"))
    store = locate()
    if store is None or not manifest["private_records"]:
        pytest.skip("no private oracle store on this machine (decision 028)")
    data = store.load(manifest["private_records"][0]["sha256"])
    assert data is not None, f"{probe}: the golden record is not in the private store"
    record = json.loads(data)
    return {
        r["condition"]: {o["output_id"]: o.get("value", o.get("values")) for o in r["outputs"]}
        for r in record["recordings"]
    }


def ok(report: dict[str, Any]) -> Any:
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    return report["result"]


def compare(native: dict[str, dict[str, Any]], golden: dict[str, dict[str, Any]]) -> list[str]:
    """Every native output that differs from the golden's, per recording."""
    differences = []
    for condition in ("same_session", "after_save_reopen"):
        for output_id, value in native[condition].items():
            if output_id.startswith("export/"):
                continue  # compared by `map_differences`
            expected = golden[condition][output_id]
            if value != expected:
                differences.append(
                    f"{condition} {output_id}: native {value!r} != Painter {expected!r}"
                )
    return differences


# The exported maps of `fill-layer-readback` the native replay compares: Height. The BaseColor
# PNG 16 is refused by the export engine (R-090, phase1.25_pilot-wand item 2.6, decision 103).
EXPORTED = ("height",)


def export_configs(probe: str, work: Path) -> dict[str, Any]:
    """Painter's export configuration of each compared map of `probe`, one map per export, as the
    recorder writes it, into `work`."""
    manifest = json.loads((API_PROBES / f"{probe}.json").read_text(encoding="utf-8"))
    job = probe_job_from_manifest(manifest)
    store = locate()
    assert store is not None
    record = json.loads(store.load(manifest["private_records"][0]["sha256"]) or b"null")
    template = next(
        o["values"] for o in record["recordings"][0]["outputs"] if o["kind"] == "template_capture"
    )
    roots = [ts if not st else f"{ts}/{st}" for ts, st in export_roots(template)]
    return {
        f"{export.step}/{out.name}": json.loads(
            json.dumps(
                dataclasses.replace(export, maps=(out,)).config(
                    work / f"export-step{export.step}-{out.name}", roots
                )
            )
        )
        for export in job.exports
        for out in export.maps
        if out.name in EXPORTED
    }


def map_differences(probe: str, native: dict[str, dict[str, Any]]) -> list[str]:
    """The compared maps that differ from Painter's on any texel, both recordings."""
    manifest = json.loads((API_PROBES / f"{probe}.json").read_text(encoding="utf-8"))
    store = locate()
    assert store is not None
    record = json.loads(store.load(manifest["private_records"][0]["sha256"]) or b"null")
    differences = []
    compared = 0
    for recording in record["recordings"]:
        for o in recording["outputs"]:
            if o["kind"] != "exported_map" or o["map"] not in EXPORTED:
                continue
            compared += 1
            name = f"{o['export_settings']['step']}/{o['map']}"
            ours = decode(Path(native[recording["condition"]]["export/" + name]).read_bytes())
            theirs = decode(store.load(o["blob"]["sha256"]) or b"")
            if ours.values.shape != theirs.values.shape or not np.array_equal(
                ours.values, theirs.values
            ):
                differences.append(f"{recording['condition']} {name}: differs from Painter's map")
    assert compared == 2 * len(EXPORTED)
    return differences


# The empty paint layer Painter's project.create puts at the bottom of every new stack. The native
# project has no such layer: paint layers are outside the Phase 1 subset
# (phase4.1_nodes-paint-layers, decision 105), and an empty one changes no channel.
PAINTER_DEFAULT_LAYER = {
    "Content": [],
    "Mask": [],
    "has_mask": False,
    "name": "Layer 1",
    "node_type": "PaintLayer",
    "visible": True,
}


def test_fill_layer_readback_equals_painter(run: Run, tmp_path: Path) -> None:
    golden = golden_outputs("fill-layer-readback")
    for condition in golden.values():
        roots = condition["s46/get_root_layer_nodes"]
        assert roots[-1] == PAINTER_DEFAULT_LAYER
        condition["s46/get_root_layer_nodes"] = roots[:-1]
    configs = export_configs("fill-layer-readback", tmp_path)
    script = traced(FILL_LAYER_READBACK).replace(
        "stack = create()", f"EXPORTS = json.loads({json.dumps(configs)!r})\nstack = create()", 1
    )
    native, trace = ok(run(script))
    assert len(native["same_session"]) == len(native["after_save_reopen"]) == 23 + len(EXPORTED)
    assert compare(native, golden) == []
    assert map_differences("fill-layer-readback", native) == []
    golden_id = "tier0/api-probes/fill-layer-readback"
    check_trace("native/fill-layer-readback", golden_id, exercised(trace))


def test_textureset_project_readback_equals_painter(run: Run, tmp_path: Path) -> None:
    golden = golden_outputs("textureset-project-readback")
    for condition in golden.values():
        for output_id in (
            "s9/get_mesh_map_resource",
            "s10/get_mesh_map_resource",
            "s11/get_mesh_map_resource",
        ):
            condition[output_id] = condition[output_id]["resource"][
                "name"
            ]  # Painter's ids: by name
        path = condition["s13/file_path"]
        condition["s13/file_path"] = (
            path if "is_none" in path else {"stem": Path(path["file_name"]).stem}
        )
    native, trace = ok(run(traced(TEXTURESET_PROJECT_READBACK)))
    assert compare(native, golden) == []
    golden_id = "tier0/api-probes/textureset-project-readback"
    check_trace("native/textureset-project-readback", golden_id, exercised(trace))
