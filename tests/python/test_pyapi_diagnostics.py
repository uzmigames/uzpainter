"""`uzpainter.diagnostics` (task phase2.1_recipe-diagnostic-views, items 3.1-3.6; decision 136).

Each test runs a script in `uzp-pyapi-tests.exe` (conftest.py) on the plane fixture. CPU only. The
diagnostics' maps are compared with OpenEXR 32f exports (padding `passthrough`) of the same
project, decoded independently here: a diagnostic equals the export of its `diagnosticMap` source
(decision 076), and the documentMap export of the stack with the node hidden by hand.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tests.python.conftest import Run
from tests.python.test_pyapi_native import ok
from tools.parity.fit.decode import decode

F32 = npt.NDArray[np.float32]

# Script helpers: the export configuration of `(file, srcMapType, srcMapName, components)` maps as
# OpenEXR 32f with padding `passthrough`, and the writing of a diagnostic map's bytes.
HELPERS = """
from uzpainter import diagnostics

def exr_config(folder, maps):
    entries = []
    for file_name, kind, name, components in maps:
        letters = ["R", "G", "B"] if components == 3 else ["L"]
        channels = [{"destChannel": c, "srcChannel": c, "srcMapType": kind, "srcMapName": name}
                    for c in letters]
        entries.append({"fileName": file_name, "channels": channels})
    return {"exportPath": folder, "exportShaderParams": False, "defaultExportPreset": "d",
            "exportPresets": [{"name": "d", "maps": entries}],
            "exportList": [{"rootPath": "uzp_plane"}],
            "exportParameters": [{"parameters": {
                "fileFormat": "exr", "bitDepth": "32f", "dithering": False,
                "paddingAlgorithm": "passthrough"}}]}

def exported(config):
    return {f["relative_path"]: f["path"] for f in export.export_project_textures(config)["files"]}

def save(name, m):
    path = WORK + "/" + name + ".bin"
    with open(path, "wb") as out:
        out.write(m["values"])
    return {"path": path, "shape": [m["height"], m["width"], m["components"]]}

def visibility():
    return [(n["uid"], n["visible"]) for n in diagnostics.snapshot_layer_tree()["nodes"]]
"""


def values(saved: dict[str, Any]) -> F32:
    """A diagnostic map the script saved: float32, shape (height, width, components)."""
    data = np.frombuffer(Path(saved["path"]).read_bytes(), dtype="<f4")
    return data.reshape(saved["shape"])


def exr(path: str) -> F32:
    """An OpenEXR 32f export as float32, shape (height, width, channels)."""
    decoded = decode(Path(path).read_bytes())
    assert not decoded.integer and decoded.bits == 32
    as_float: F32 = decoded.values.astype(np.float32)
    assert np.array_equal(as_float.astype(np.float64), decoded.values)
    return as_float


def same_bits(a: F32, b: F32) -> bool:
    return a.shape == b.shape and bool(np.array_equal(a.view(np.uint32), b.view(np.uint32)))


# ── 3.1, 3.2 and 3.6: isolate and contribution ─────────────────────────────────────────────────

ISOLATE = """
stack = create()
low = ls.insert_fill(top(stack))
low.active_channels = {CT.BaseColor, CT.Height}
low.set_source(CT.BaseColor, cm.Color(0.8, 0.2, 0.1, "Raw"))
low.set_source(CT.Height, cm.Color(0.25, 0.25, 0.25, "Raw"))
high = ls.insert_fill(top(stack))
high.active_channels = {CT.BaseColor, CT.Height}
high.set_source(CT.BaseColor, cm.Color(0.1, 0.6, 0.3, "Raw"))
high.set_opacity(0.5, CT.BaseColor)
high.set_source(CT.Height, cm.Color(0.375, 0.375, 0.375, "Raw"))
high.set_blending_mode(ls.BlendingMode.LinearDodge, CT.Height)
uid = high.uid()

rev0 = project.revision()
vis0 = visibility()
iso = diagnostics.isolate(high, CT.BaseColor)
con = diagnostics.contribution(uid, CT.BaseColor)
iso_h = diagnostics.isolate(high, "Height")
failed = [raises(diagnostics.isolate, high, "Emissive"),
          raises(diagnostics.isolate, 999999, CT.BaseColor),
          raises(diagnostics.isolate, high, "Bogus")]
rev1 = project.revision()
vis1 = visibility()
with uzpainter.Transaction("t"):
    in_transaction = raises(diagnostics.isolate, high, CT.BaseColor)

diag = exported(exr_config(WORK + "/diag", [
    ("iso", "diagnosticMap", "isolated/BaseColor/%d" % uid, 3),
    ("contrib", "diagnosticMap", "contribution/BaseColor/%d" % uid, 3),
    ("iso_h", "diagnosticMap", "isolated/Height/%d" % uid, 1),
    ("full", "documentMap", "basecolor", 3)]))
high.set_visible(False)
by_hand = exported(exr_config(WORK + "/hand", [
    ("base", "documentMap", "basecolor", 3), ("height", "documentMap", "height", 1)]))

result = {"rev": [rev0, rev1], "vis": [vis0, vis1], "failed": failed,
          "in_transaction": in_transaction,
          "iso": {k: iso[k] for k in ("source", "revision", "node", "was_visible")},
          "con": {k: con[k] for k in ("source", "isolated_source", "revision", "node")},
          "uid": uid, "iso_map": save("iso", iso["map"]), "iso_h": save("iso_h", iso_h["map"]),
          "full": save("full", con["full"]), "isolated": save("isolated", con["isolated"]),
          "difference": save("difference", con["difference"]), "diag": diag, "hand": by_hand}
"""


def test_isolate_and_contribution_equal_their_exports(run: Run) -> None:
    r = ok(run(HELPERS + ISOLATE))
    uid = r["uid"]
    # 3.1: no revision and no visibility change, also after refused and failing calls.
    assert r["rev"][0] == r["rev"][1]
    assert r["vis"][0] == r["vis"][1] and all(v for _, v in r["vis"][0])
    assert r["iso"] == {
        "source": f"isolated/BaseColor/{uid}",
        "revision": r["rev"][0],
        "node": uid,
        "was_visible": True,
    }
    emissive, unknown, bogus = r["failed"]
    assert emissive is not None and "Emissive" in emissive
    assert unknown == f"ValueError: node 999999 is in no stack of revision {r['rev'][0]}"
    assert bogus is not None and bogus.startswith("ValueError: unknown map Bogus")
    assert r["in_transaction"].startswith("RuntimeError: a diagnostic reads a committed revision")

    iso = values(r["iso_map"])
    iso_h = values(r["iso_h"])
    hand_base = exr(r["hand"]["base.exr"])
    hand_height = exr(r["hand"]["height.exr"])
    # 3.1: the isolated map is the export with the node hidden by hand.
    assert same_bits(iso, hand_base)
    assert same_bits(iso_h, hand_height)
    # The node did contribute: the isolation is not the full map.
    full = values(r["full"])
    assert not np.array_equal(full, iso)
    # 3.2: the contribution is the decoded difference of the two exports, in float32.
    full_export = exr(r["diag"]["full.exr"])
    assert same_bits(full, full_export)
    assert same_bits(values(r["isolated"]), hand_base)
    assert same_bits(values(r["difference"]), full_export - hand_base)
    assert r["con"]["source"] == f"contribution/BaseColor/{uid}"
    # 3.6: each output equals the export of its diagnostic source.
    assert same_bits(iso, exr(r["diag"]["iso.exr"]))
    assert same_bits(iso_h, exr(r["diag"]["iso_h.exr"]))
    assert same_bits(values(r["difference"]), exr(r["diag"]["contrib.exr"]))


# ── 3.3, 3.4 and 3.6: material views and region statistics ─────────────────────────────────────

MATERIAL = """
stack = create()
half = resource.import_project_resource(IMAGES + "/mask-left-half.png", resource.Usage.TEXTURE)
below = ls.insert_fill(top(stack))
below.active_channels = {CT.SpecularRoughness, CT.BaseColor}
below.set_source(CT.SpecularRoughness, cm.Color(0.9, 0.9, 0.9, "Raw"))
below.set_source(CT.BaseColor, cm.Color(0.1, 0.1, 0.7, "Raw"))
mat = ls.insert_fill(top(stack))
mat.active_channels = {CT.SpecularRoughness, CT.BaseColor}
mat.set_source(CT.SpecularRoughness, cm.Color(0.2, 0.2, 0.2, "Raw"))
mat.set_source(CT.BaseColor, cm.Color(0.7, 0.3, 0.1, "Raw"))
mat.add_mask(ls.MaskBackground.Black)
# A hard-edged mask: with bilinear filtering its edge is partial, and the layer below shows there
# (a leak by decision 075).
mask_fill = ls.insert_fill(ls.InsertPosition.inside_node(mat, ls.NodeStack.Mask))
mask_fill.set_source(None, half.identifier())
mask_fill.set_projection_parameters(ls.UVProjectionParams(filtering_mode=ls.FilteringMode.Nearest))
uid = mat.uid()

def summary(views):
    return {"inside": views["inside"], "missing": views["missing"], "refused": views["refused"],
            "mask_source": views["mask_source"],
            "views": {name: {"leaks": v["leak_count"], "source": v["source"],
                             "leaks_source": v["leaks_source"],
                             "channel": None if v["channel"] is None else v["channel"].name,
                             "first": v["leak_texels"][:1]}
                      for name, v in views["views"].items()}}

clean = diagnostics.material_views(mat)
clean_rough = save("clean_rough", clean["views"]["Roughness"]["values"])
stats = diagnostics.region_stats(CT.SpecularRoughness, mat)
color_stats = diagnostics.region_stats("BaseColor", uid)
clean_files = exported(exr_config(WORK + "/clean", [
    ("mask", "diagnosticMap", "materialMask/%d" % uid, 1),
    ("rough", "diagnosticMap", "materialView/Roughness/%d" % uid, 1),
    ("leaks", "diagnosticMap", "materialLeaks/Roughness/%d" % uid, 1),
    ("doc_rough", "documentMap", "roughness", 1),
    ("doc_base", "documentMap", "basecolor", 3),
    ("stats", "diagnosticMap", "regionStats/SpecularRoughness/%d" % uid, 1)]))

leak = ls.insert_fill(top(stack))
leak.active_channels = {CT.SpecularRoughness}
leak.set_source(CT.SpecularRoughness, cm.Color(0.6, 0.6, 0.6, "Raw"))
seeded = diagnostics.material_views(mat)
seeded_files = exported(exr_config(WORK + "/seeded", [
    ("rough", "diagnosticMap", "materialView/Roughness/%d" % uid, 1),
    ("leaks", "diagnosticMap", "materialLeaks/Roughness/%d" % uid, 1),
    ("base", "diagnosticMap", "materialView/BaseColor/%d" % uid, 3)]))

result = {"uid": uid, "clean": summary(clean), "seeded": summary(seeded),
          "clean_mask": save("clean_mask", clean["mask"]), "clean_rough": clean_rough,
          "seeded_rough": save("seeded_rough", seeded["views"]["Roughness"]["values"]),
          "seeded_leaks": save("seeded_leaks", seeded["views"]["Roughness"]["leaks"]),
          "seeded_base": save("seeded_base", seeded["views"]["BaseColor"]["values"]),
          "stats": stats, "color_stats": color_stats, "clean_files": clean_files,
          "seeded_files": seeded_files}
"""


def percentile(ordered: list[float], q: float) -> float:
    """The linear rule (Hyndman and Fan 7, numpy's default)."""
    h = (len(ordered) - 1) * q
    i = math.floor(h)
    if i + 1 >= len(ordered):
        return ordered[i]
    return ordered[i] + (h - i) * (ordered[i + 1] - ordered[i])


def value_stats(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "min": ordered[0],
        "max": ordered[-1],
        "mean": math.fsum(samples) / len(samples),
        "p10": percentile(ordered, 0.1),
        "p50": percentile(ordered, 0.5),
        "p90": percentile(ordered, 0.9),
    }


def region_stats(image: F32, mask: F32) -> dict[str, Any]:
    """DIA-01 statistics recomputed from an exported map and mask (decision 075 §5)."""
    flat_mask = [float(m) for m in mask[..., 0].ravel()]
    inside = mask[..., 0].ravel() >= 0.5
    texels = [[float(v) for v in t] for t in image.reshape(-1, image.shape[-1])[inside]]
    out: dict[str, Any] = {
        "texels": len(flat_mask),
        "inside": len(texels),
        "coverage": len(texels) / len(flat_mask),
        "mask_mean": math.fsum(flat_mask) / len(flat_mask),
        "components": [value_stats([t[c] for t in texels]) for c in range(image.shape[-1])],
        "luminance": None,
        "saturation": None,
    }
    if image.shape[-1] == 3:
        out["luminance"] = value_stats([((r + g) + b) / 3 for r, g, b in texels])
        out["saturation"] = value_stats(
            [(max(t) - min(t)) / max(t) if max(t) > 0 else 0.0 for t in texels]
        )
    return out


def test_material_views_detect_a_seeded_roughness_leak(run: Run) -> None:
    r = ok(run(HELPERS + MATERIAL))
    uid = r["uid"]
    clean, seeded = r["clean"], r["seeded"]
    half = 256 * 128
    assert clean["inside"] == seeded["inside"] == half
    # The plane has no ID mesh map; the default template's bases are observed.
    assert clean["missing"] == ["ID"] and clean["refused"] == {}
    assert clean["mask_source"] == f"materialMask/{uid}"
    assert sorted(clean["views"]) == ["BaseColor", "Height", "Metallic", "Normal", "Roughness"]
    assert clean["views"]["Roughness"]["channel"] == "SpecularRoughness"
    assert clean["views"]["Roughness"]["source"] == f"materialView/Roughness/{uid}"
    assert clean["views"]["Roughness"]["leaks_source"] == f"materialLeaks/Roughness/{uid}"
    # 3.3: the clean fixture reports no leak; the seeded one a Roughness leak on every inside
    # texel, the leaking layer's value against the material's own, and nothing else.
    assert {name: v["leaks"] for name, v in clean["views"].items()} == dict.fromkeys(
        clean["views"], 0
    )
    assert {name: v["leaks"] for name, v in seeded["views"].items()} == {
        "BaseColor": 0,
        "Height": 0,
        "Normal": 0,
        "Roughness": half,
        "Metallic": 0,
    }
    [first] = seeded["views"]["Roughness"]["first"]
    assert first["value"][0] != first["own"][0]

    mask = values(r["clean_mask"])
    inside = mask[..., 0] >= 0.5
    assert int(inside.sum()) == half
    seeded_rough = values(r["seeded_rough"])
    leaks = values(r["seeded_leaks"])
    assert np.array_equal(leaks[..., 0] == 1.0, inside)
    assert set(np.unique(leaks).tolist()) == {0.0, 1.0}
    assert np.all(seeded_rough[~inside] == 0.0)
    assert not np.array_equal(seeded_rough, values(r["clean_rough"]))

    # 3.6: every view equals the export of its source.
    clean_files, seeded_files = r["clean_files"], r["seeded_files"]
    assert same_bits(mask, exr(clean_files["mask.exr"]))
    assert same_bits(values(r["clean_rough"]), exr(clean_files["rough.exr"]))
    assert np.all(exr(clean_files["leaks.exr"]) == 0.0)
    assert same_bits(seeded_rough, exr(seeded_files["rough.exr"]))
    assert same_bits(leaks, exr(seeded_files["leaks.exr"]))
    assert same_bits(values(r["seeded_base"]), exr(seeded_files["base.exr"]))

    # 3.4: the statistics equal those computed from the exported map and mask, and (3.6) the
    # export's statistics file.
    doc_rough = exr(clean_files["doc_rough.exr"])
    doc_base = exr(clean_files["doc_base.exr"])
    assert r["stats"]["source"] == f"regionStats/SpecularRoughness/{uid}"
    assert r["stats"]["stats"] == region_stats(doc_rough, mask)
    assert r["color_stats"]["source"] == f"regionStats/BaseColor/{uid}"
    assert r["color_stats"]["stats"] == region_stats(doc_base, mask)
    stats_file = json.loads(Path(clean_files["stats.json"]).read_text(encoding="utf-8"))
    assert stats_file == r["stats"]["stats"]


# ── Decision 126 per source ─────────────────────────────────────────────────────────────────────

INFERRED = """
project.create(PLANE, project.Settings(default_texture_resolution=256, template="dota-2"))
stack = ts.get_active_stack()
mat = ls.insert_fill(top(stack))
mat.active_channels = {CT.BaseMetalness}
mat.set_source(CT.BaseMetalness, cm.Color(0.2, 0.2, 0.2, "Raw"))
views = diagnostics.material_views(mat)
result = {"isolate": raises(diagnostics.isolate, mat, CT.BaseColor),
          "contribution": raises(diagnostics.contribution, mat, CT.BaseColor),
          "stats": raises(diagnostics.region_stats, CT.BaseColor, mat),
          "metal": diagnostics.isolate(mat, CT.BaseMetalness)["source"],
          "views": sorted(views["views"]), "refused": sorted(views["refused"]),
          "reason": views["refused"].get("BaseColor", "")}
"""


def test_an_inferred_template_base_is_refused_per_source(run: Run) -> None:
    r = ok(run(HELPERS + INFERRED))
    for call in ("isolate", "contribution", "stats"):
        assert r[call].startswith("NotYetSupported") and "decision 126" in r[call]
    assert r["metal"].startswith("isolated/BaseMetalness/")
    # Dota 2 has no SpecularRoughness, Height or Normal channel: those views are missing.
    assert r["refused"] == ["BaseColor"] and r["views"] == ["Metallic"]
    assert "decision 126" in r["reason"]


# ── 3.5: layer-tree snapshot and diff ───────────────────────────────────────────────────────────

SNAPSHOT = """
stack = create()
a = ls.insert_fill(top(stack))
a.set_name("A")
a.active_channels = {CT.BaseColor}
b = ls.insert_fill(top(stack))
b.set_name("B")
b.add_mask(ls.MaskBackground.White)
first = diagnostics.snapshot_layer_tree()
again = diagnostics.snapshot_layer_tree()
b.set_opacity(0.25, CT.BaseColor)
opacity = diagnostics.snapshot_layer_tree()
fx = ls.insert_levels_effect(ls.InsertPosition.inside_node(a, ls.NodeStack.Content))
group = ls.insert_group(top(stack))
b_uid = b.uid()
ls.delete_node(b)
a.set_visible(False)
last = diagnostics.snapshot_layer_tree()
result = {"first": first, "uids": {"a": a.uid(), "b": b_uid, "fx": fx.uid(), "group": group.uid()},
          "same": diagnostics.diff_snapshots(first, again),
          "later": diagnostics.diff_snapshots(
              opacity, dict(opacity, revision=opacity["revision"] + 7)),
          "opacity": diagnostics.diff_snapshots(again, opacity),
          "structure": diagnostics.diff_snapshots(opacity, last),
          "bad": [raises(diagnostics.diff_snapshots, {"schema": "x"}, first),
                  raises(diagnostics.diff_snapshots, first, dict(first, nodes=first["nodes"] * 2))]}
"""


def test_snapshot_diff_reports_exactly_the_seeded_changes(run: Run) -> None:
    r = ok(run(HELPERS + SNAPSHOT))
    uids = r["uids"]
    first = r["first"]
    assert first["schema"] == "uzpainter/layer-tree/1"
    [stack] = first["stacks"]
    # Root layers top first.
    assert [n["uid"] for n in first["nodes"]] == [uids["b"], uids["a"]]
    b = first["nodes"][0]
    assert {k: b[k] for k in ("node", "kind", "name", "visible", "parent", "slot", "index")} == {
        "node": "layer",
        "kind": "fill",
        "name": "B",
        "visible": True,
        "parent": None,
        "slot": "Substack",
        "index": 0,
    }
    assert b["stack"] == stack["stack"] and b["texture_set"] == stack["texture_set"]
    assert b["params"]["mask"]["effects"] == [] and b["params"]["content_effects"] == []
    empty: dict[str, list[Any]] = {"added": [], "removed": [], "modified": []}

    def body(diff: dict[str, Any]) -> dict[str, Any]:
        return {k: diff[k] for k in ("added", "removed", "modified")}

    # Identical snapshots, at one revision or two, give an empty diff.
    assert body(r["same"]) == empty and r["same"]["stacks"] == empty
    assert body(r["later"]) == empty
    assert r["later"]["after_revision"] == r["later"]["before_revision"] + 7
    # One parameter changed: that layer and that parameter, nothing else.
    opacity = r["opacity"]
    assert opacity["schema"] == "uzpainter/layer-tree-diff/1"
    assert opacity["added"] == [] and opacity["removed"] == [] and opacity["stacks"] == empty
    [modified] = opacity["modified"]
    assert modified["uid"] == uids["b"]
    # A layer holds a channel's blending once it is set: the entry is new, so it has no `before`.
    [change] = modified["changes"]
    assert change["path"] == "/params/blending/BaseColor" and "before" not in change
    assert change["after"]["opacity"] == 0.25
    # Added, removed and modified nodes.
    structure = r["structure"]
    assert [n["uid"] for n in structure["added"]] == sorted([uids["fx"], uids["group"]])
    added = {n["uid"]: n for n in structure["added"]}
    assert (added[uids["fx"]]["parent"], added[uids["fx"]]["slot"]) == (uids["a"], "Content")
    assert added[uids["fx"]]["kind"] == "levels" and added[uids["group"]]["kind"] == "group"
    assert [n["uid"] for n in structure["removed"]] == [uids["b"]]
    [changed] = structure["modified"]
    assert changed["uid"] == uids["a"]
    assert changed["changes"] == [
        {"path": "/params/content_effects", "before": [], "after": [uids["fx"]]},
        {"path": "/visible", "before": True, "after": False},
    ]
    bad_schema, repeated = r["bad"]
    assert bad_schema.startswith("ValueError: diff_snapshots: the first snapshot")
    assert repeated is not None and "repeats uid" in repeated
