"""The native `uzpainter` module (task phase1.19_pyapi-native-module, items 3.1 and 3.3-3.8).

Each test runs a script in `uzp-pyapi-tests.exe` (conftest.py) on the plane fixture. CPU only.
"""

from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path
from typing import Any

import numpy as np

from tests.python.conftest import PROBE_IMAGES, REPO_ROOT, Run
from tools.parity.fit.decode import decode


def with_values(script: str) -> str:
    """`script` with `__CALLS__` (LATER_PHASE) and `__CONFIG__` (CONFIG_EXPRESSION) filled in."""
    return script.replace("__CALLS__", json.dumps(LATER_PHASE)).replace(
        "__CONFIG__", CONFIG_EXPRESSION
    )


def ok(report: dict[str, Any]) -> Any:
    """The `result` of a script that ran to its end."""
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    return report["result"]


# ── 3.1 set -> get -> save -> reopen -> get ─────────────────────────────────────────────────────

SETTERS = """
stack = create()
tset = stack.material()
checker = resource.import_project_resource(IMAGES + "/checker-16.png", resource.Usage.TEXTURE)
mask_image = resource.import_project_resource(
    IMAGES + "/mask-left-half.png", resource.Usage.TEXTURE
)
normal = resource.import_project_resource(IMAGES + "/normal-flat.png", resource.Usage.TEXTURE)

fill = ls.insert_fill(top(stack))
fill.set_name("uzp fill A")
fill.active_channels = {CT.BaseColor, CT.SpecularRoughness, CT.Height}
fill.set_source(CT.BaseColor, cm.Color(0.8, 0.2, 0.1, cm.GenericColorSpace.sRGB))
rough = fill.set_source(CT.SpecularRoughness, cm.Color(0.5, 0.5, 0.5, "Raw"))
rough.set_color(cm.Color(0.35, 0.35, 0.35, "Raw"))
fill.set_source(CT.Height, cm.Color(0.25, 0.25, 0.25))
fill.set_blending_mode(ls.BlendingMode.LinearDodge, CT.Height)
fill.set_opacity(0.85, CT.BaseColor)
fill.add_mask(ls.MaskBackground.White)
fill.set_mask_background(ls.MaskBackground.Black)
fill.enable_mask(False)
mask_fill = ls.insert_fill(ls.InsertPosition.inside_node(fill, ls.NodeStack.Mask))
mask_fill.set_source(None, mask_image.identifier())
mask_fill.set_opacity(0.5)
mask_fill.set_blending_mode(ls.BlendingMode.Multiply)
levels_fx = ls.insert_levels_effect(ls.InsertPosition.inside_node(fill, ls.NodeStack.Content))
levels_fx.affected_channel = CT.SpecularRoughness
levels_fx.set_parameters(levels.LevelsParamsMono(0.1, 0.9, 1.5, 0.05, 0.95, True))

group = ls.insert_group(top(stack))
group.set_name("uzp group")
group.set_blending_mode(ls.BlendingMode.Normal, CT.Height)
group.set_collapsed(True)
inner = ls.insert_fill(ls.InsertPosition.inside_node(group, ls.NodeStack.Substack))
inner.set_visible(False)
inner.active_channels = {CT.BaseColor}
bitmap = inner.set_source(CT.BaseColor, checker.identifier())
bitmap.set_color_space("sRGB")
inner.set_projection_mode(ls.ProjectionMode.UV)
inner.set_projection_parameters(
    ls.UVProjectionParams(
        filtering_mode=ls.FilteringMode.Nearest,
        uv_wrapping_mode=ls.UVWrapMode.RepeatNone,
        uv_transformation=ls.UVTransformationParams(
            scale_mode=ls.ScaleMode.Factors, scale=[2.0, 0.5], rotation=30.0, offset=[0.1, 0.2]
        ),
    )
)

tset.set_resolution(ts.Resolution(512, 512))
tset.set_mesh_map_resource(ts.MeshMapUsage.Normal, normal.identifier())
stack.add_channel(CT.User0, ts.ChannelFormat.L16, "mask zero")
stack.edit_channel(CT.User0, ts.ChannelFormat.L8, "mask zero b")
project.Metadata("uzp-tests").set("version", {"major": 1, "minor": [2, 3], "name": "x", "on": True})

uids = {
    "fill": fill.uid(),
    "mask_fill": mask_fill.uid(),
    "levels": levels_fx.uid(),
    "group": group.uid(),
    "inner": inner.uid(),
}


def color(source):
    c = source.get_color()
    return [list(c.value_raw), c.color_space]


def state():
    n = {k: ls.get_node_by_uid(v) for k, v in uids.items()}  # freshly resolved handles
    f, m, lv, g, i = n["fill"], n["mask_fill"], n["levels"], n["group"], n["inner"]
    p = i.get_projection_parameters()
    t = p.uv_transformation
    lp = lv.get_parameters()
    s = ts.get_active_stack()
    return {
        "names": [x.get_name() for x in n.values()],
        "types": [str(x.get_type()) for x in n.values()],
        "classes": [type(x).__name__ for x in n.values()],
        "visible": [x.is_visible() for x in n.values()],
        "active": sorted(str(c) for c in f.active_channels),
        "inner_active": sorted(str(c) for c in i.active_channels),
        "base": color(f.get_source(CT.BaseColor)),
        "rough": color(f.get_source(CT.SpecularRoughness)),
        "height": color(f.get_source(CT.Height)),
        "blend": [
            str(f.get_blending_mode(CT.Height)),
            str(f.get_blending_mode(CT.BaseColor)),
            str(g.get_blending_mode(CT.Height)),
            str(m.get_blending_mode()),
        ],
        "opacity": [f.get_opacity(CT.BaseColor), f.get_opacity(CT.Height), m.get_opacity()],
        "mask": [
            f.has_mask(),
            str(f.get_mask_background()),
            f.is_mask_enabled(),
            [e.uid() for e in f.mask_effects()],
            [e.uid() for e in f.content_effects()],
        ],
        "mask_source": m.get_source(None).resource_id().url(),
        "levels": [
            str(lv.affected_channel),
            lp.input_min,
            lp.input_max,
            lp.gamma,
            lp.output_min,
            lp.output_max,
            lp.clamp,
        ],
        "collapsed": g.is_collapsed(),
        "sub_layers": [x.uid() for x in g.sub_layers()],
        "bitmap": [
            i.get_source(CT.BaseColor).resource_id().url(),
            i.get_source(CT.BaseColor).get_color_space(),
        ],
        "projection": [
            str(i.get_projection_mode()),
            str(p.filtering_mode),
            str(p.uv_wrapping_mode),
            str(t.scale_mode),
            list(t.scale),
            t.rotation,
            list(t.offset),
        ],
        "roots": [x.uid() for x in ls.get_root_layer_nodes(s)],
        "resolution": [s.material().get_resolution().width, s.material().get_resolution().height],
        "mesh_map": s.material().get_mesh_map_resource(ts.MeshMapUsage.Normal).url(),
        "channel": [str(s.get_channel(CT.User0).format()), s.get_channel(CT.User0).label()],
        "metadata": project.Metadata("uzp-tests").get("version"),
        "resources": sorted(r.url() for r in resource.list_project_resources()),
    }


before = state()
path = WORK + "/sub/readback.uzp"
project.save_as(path)
saved = project.needs_saving()
project.close()
project.open(path)
after = state()
result = {
    "before": before,
    "after": after,
    "needs_saving_after_save": saved,
    "needs_saving_reopened": project.needs_saving(),
    "file_path": project.file_path(),
    "name": project.name(),
}
project.close()
"""


def f32(value: float) -> float:
    """`value` rounded to float32, as the API stores it."""
    return float(struct.unpack("f", struct.pack("f", value))[0])


def test_every_setter_reads_back_through_fresh_handles_and_after_reopen(run: Run) -> None:
    result = ok(run(SETTERS))
    before, after = result["before"], result["after"]
    assert before == after
    assert result["needs_saving_after_save"] is False
    assert result["needs_saving_reopened"] is False
    assert result["file_path"].endswith("/sub/readback.uzp")
    assert result["name"] == "readback"
    assert before["names"] == ["uzp fill A", "Fill", "Levels - Base color", "uzp group", "Fill"]
    assert before["classes"] == [
        "FillLayerNode",
        "FillEffectNode",
        "LevelsEffectNode",
        "GroupLayerNode",
        "FillLayerNode",
    ]
    assert before["visible"] == [True, True, True, True, False]
    assert before["active"] == [
        "ChannelType.BaseColor",
        "ChannelType.Height",
        "ChannelType.SpecularRoughness",
    ]
    assert before["base"] == [[f32(0.8), f32(0.2), f32(0.1)], "sRGB"]
    assert before["rough"] == [[f32(0.35)] * 3, "Raw"]
    assert before["height"] == [[0.25] * 3, None]
    assert before["blend"] == [
        "BlendingMode.LinearDodge",
        "BlendingMode.Normal",
        "BlendingMode.Normal",
        "BlendingMode.Multiply",
    ]
    assert before["opacity"] == [f32(0.85), 1.0, 0.5]
    assert before["mask"][:3] == [True, "MaskBackground.Black", False]
    assert before["levels"] == [
        "ChannelType.SpecularRoughness",
        f32(0.1),
        f32(0.9),
        1.5,
        f32(0.05),
        f32(0.95),
        True,
    ]
    assert before["collapsed"] is True
    assert before["bitmap"][1] == "sRGB"
    assert before["projection"] == [
        "ProjectionMode.UV",
        "FilteringMode.Nearest",
        "UVWrapMode.RepeatNone",
        "ScaleMode.Factors",
        [2.0, 0.5],
        30.0,
        [f32(0.1), f32(0.2)],
    ]
    assert before["resolution"] == [512, 512]
    assert before["channel"] == ["ChannelFormat.L8", "mask zero b"]
    assert before["metadata"] == {"major": 1, "minor": [2, 3], "name": "x", "on": True}


def test_lay01_active_channels_keep_every_source(run: Run) -> None:
    """LAY-01: reassigning active_channels after set_source changes no source (the facade adds
    Painter's reset, phase1.20)."""
    result = ok(
        run("""
        stack = create()
        fill = ls.insert_fill(top(stack))
        fill.active_channels = {CT.BaseColor, CT.Height}
        fill.set_source(CT.BaseColor, cm.Color(0.8, 0.3, 0.2, "Working"))
        fill.set_source(CT.Height, cm.Color(0.4, 0.4, 0.4, "Raw"))
        snapshot = lambda: [
            list(fill.get_source(c).get_color().value_raw) for c in (CT.BaseColor, CT.Height)
        ]
        first = snapshot()
        fill.active_channels = {CT.BaseColor, CT.Height}
        same = snapshot()
        fill.active_channels = {CT.BaseColor}
        fewer = snapshot()
        fill.active_channels = {CT.BaseColor, CT.Height, CT.SpecularRoughness}
        result = {
            "first": first,
            "same": same,
            "fewer": fewer,
            "more": snapshot(),
            "active": sorted(str(c) for c in fill.active_channels),
        }
        """)
    )
    assert result["first"] == result["same"] == result["fewer"] == result["more"]
    assert result["active"] == [
        "ChannelType.BaseColor",
        "ChannelType.Height",
        "ChannelType.SpecularRoughness",
    ]


def test_inserts_give_painters_effective_defaults(run: Run) -> None:
    """Decision 115: a new fill or group in a content stack blends Height LinearDodge and Normal
    NormalMapDetail (a content fill effect too, once the support check admits it); a new fill
    holds BaseColor 0.8 and Height 0 (working space) with no active channel; the levels effect
    of a content stack affects BaseColor and is named "Levels - Base color" (a compare mask is
    named "Compare mask" once the support check admits it). A mask-stack node keeps the plain
    defaults, a named insert keeps its name, and LAY-01 still holds."""
    result = ok(
        run("""
        stack = create()
        fill = ls.insert_fill(top(stack))
        group = ls.insert_group(top(stack))
        levels = ls.insert_levels_effect(ls.InsertPosition.inside_node(fill, ls.NodeStack.Content))
        named = ls.insert_levels_effect(ls.InsertPosition.above_node(levels), name="mine")
        fill.add_mask(ls.MaskBackground.Black)
        in_mask = ls.insert_fill(ls.InsertPosition.inside_node(fill, ls.NodeStack.Mask))


        def blending(node):
            return {c.name: [node.get_blending_mode(c).name, node.get_opacity(c)]
                    for c in (CT.BaseColor, CT.Height, CT.Normal, CT.SpecularRoughness)}


        def sources(node):
            out = {}
            for c in (CT.BaseColor, CT.Height, CT.SpecularRoughness):
                s = node.get_source(c)
                out[c.name] = None if s is None else [list(s.get_color().value_raw),
                                                      s.get_color().color_space]
            return out


        before = sources(fill)
        fill.active_channels = {CT.BaseColor}
        result = {
            "names": [n.get_name() for n in (fill, group, levels, named, in_mask)],
            "fill": blending(fill), "group": blending(group), "fill_sources": before,
            "levels": [str(levels.affected_channel), type(levels.get_parameters()).__name__,
                       str(named.affected_channel)],
            "mask": [in_mask.get_blending_mode().name, in_mask.get_source(None)],
            "kept": sources(fill),
        }
        """)
    )
    assert result["names"] == [
        "Fill",
        "Folder",
        "Levels - Base color",
        "mine",
        "Fill",
    ]
    painter = {
        "BaseColor": ["Normal", 1.0],
        "Height": ["LinearDodge", 1.0],
        "Normal": ["NormalMapDetail", 1.0],
        "SpecularRoughness": ["Normal", 1.0],
    }
    assert result["fill"] == result["group"] == painter
    defaults = {
        "BaseColor": [[0.800000011920929] * 3, "Working"],
        "Height": [[0.0] * 3, "Working"],
        "SpecularRoughness": None,  # unrecorded (recording P20-A): no source
    }
    assert result["fill_sources"] == defaults
    assert result["levels"] == [
        "ChannelType.BaseColor",
        "LevelsParamsRGB",
        "ChannelType.BaseColor",
    ]
    assert result["mask"] == ["Normal", None]
    assert result["kept"] == defaults  # LAY-01: assigning active channels changes no source


def test_a_project_records_its_template(run: Run) -> None:
    """Decision 116: `Settings(template=...)` creates the stacks from an installed template, the
    project records it through save and reopen, and an export reads its base values: the empty
    Glossiness channel of Dota 2 (a channel the default template and the channel defaults lack)
    exports the template's base 178/255. An unknown id fails before anything is created."""
    result = ok(
        run(
            with_values("""
        listed = {t["id"]: t["painter_template"] for t in project.templates()}
        bad = raises(project.create, PLANE, project.Settings(template="nope"))
        open_after_bad = project.is_open()
        project.create(PLANE, project.Settings(default_texture_resolution=256, template="dota-2"))
        channels = sorted(c.name for c in ts.get_active_stack().all_channels())
        project.save_as(WORK + "/dota.uzp")
        project.close()
        project.open(WORK + "/dota.uzp")
        reopened = project.template()
        config = __CONFIG__
        config["exportPresets"][0]["maps"][0]["channels"][0]["srcMapName"] = "glossiness"
        out = export.export_project_textures(config)
        files = [[f["relative_path"], f["path"]] for f in out["files"]]
        project.close()
        create()
        default_template = project.template()
        project.close()
        result = {"listed": listed, "bad": bad, "open_after_bad": open_after_bad,
                  "channels": channels, "reopened": reopened, "files": files,
                  "default": default_template}
        """)
        )
    )
    assert result["listed"]["default"] is None
    assert result["listed"]["dota-2"] == "templates/Dota 2.spt"
    assert len(result["listed"]) == 27
    assert result["bad"].startswith("ValueError: no project template 'nope'")
    assert result["open_after_bad"] is False
    assert result["reopened"] == "dota-2"
    assert result["default"] == "default"
    template = json.loads((REPO_ROOT / "assets/templates/dota-2.json").read_text(encoding="utf-8"))
    assert result["channels"] == sorted(c["type"] for c in template["channels"])
    [(relative, path)] = result["files"]
    assert relative == "uzp_plane_height.png"
    exported = decode(Path(path).read_bytes())
    assert exported.values.shape[:2] == (256, 256)
    assert set(np.unique(exported.values).tolist()) == {178 * 257}


# ── 3.3 handles and later-phase calls ───────────────────────────────────────────────────────────


def test_unknown_attribute_and_stale_handle(run: Run) -> None:
    result = ok(
        run("""
        stack = create()
        fill = ls.insert_fill(top(stack))
        rev = project.revision()
        typo = raises(setattr, fill, "active_channels_typo", {CT.BaseColor})
        after_typo = project.revision()
        uid = fill.uid()
        ls.delete_node(fill)
        stale = [raises(fill.get_name), raises(fill.set_name, "x"), raises(ls.get_node_by_uid, uid)]
        slots = [type(fill).__slots__, type(stack).__slots__, ls.Node.__slots__]
        result = {
            "typo": typo,
            "rev": [rev, after_typo],
            "stale": stale,
            "slots": [list(s) for s in slots],
            "uid_type": type(uid).__name__,
        }
        """)
    )
    assert result["typo"].startswith("AttributeError")
    assert result["rev"][0] == result["rev"][1]
    assert all(s is not None and s.startswith("ValueError: stale handle") for s in result["stale"])
    assert result["slots"] == [[], [], []]
    assert result["uid_type"] == "int"


LATER_PHASE = [
    ("uzpainter.baking", "bake_async", "phase3.5_embree-bakers"),
    ("uzpainter.baking", "bake_selected_textures_async", "phase3.5_embree-bakers"),
    ("uzpainter.baking", "BakingParameters", "phase3.5_embree-bakers"),
    ("uzpainter.render", "capture", "phase2.3_realtime-preview"),
    ("uzpainter.render.shader", "set_parameters", "phase2.3_realtime-preview"),
    ("uzpainter.render.display", "set_exposure", "phase2.3_realtime-preview"),
    ("uzpainter.display", "set_environment_resource", "phase2.3_realtime-preview"),
    ("uzpainter.display", "set_tone_mapping", "phase2.3_realtime-preview"),
    ("uzpainter.diagnostics", "isolate", "phase2.2_recipe-and-diagnostics"),
    ("uzpainter.diagnostics", "region_stats", "phase2.2_recipe-and-diagnostics"),
    ("uzpainter.project", "dump_recipe", "phase2.2_recipe-and-diagnostics"),
]


def test_later_phase_calls_raise_not_yet_supported_before_mutation(run: Run) -> None:
    result = ok(
        run(
            with_values("""
        import importlib

        stack = create()
        fill = ls.insert_fill(top(stack))
        before = (project.revision(), project.needs_saving())
        out = []
        for module, name, owner in __CALLS__:
            call = getattr(importlib.import_module(module), name)
            out.append([module, name, owner, raises(call, fill, 1, key="value")])
        procedural = [
            raises(ls.insert_generator_effect, top(stack), None),
            raises(ls.insert_filter_effect, top(stack)),
            raises(fill.set_material_source, None),
        ]
        gaps = [
            raises(fill.set_projection_mode, ls.ProjectionMode.Triplanar),
            raises(ls.insert_paint, top(stack)),
            raises(
                ls.insert_compare_mask_effect,
                ls.InsertPosition.inside_node(fill, ls.NodeStack.Content),
            ),
        ]
        result = {
            "out": out,
            "procedural": procedural,
            "gaps": gaps,
            "before": list(before),
            "after": [project.revision(), project.needs_saving()],
        }
        """)
        )
    )
    for module, name, owner, error in result["out"]:
        assert error == f"NotYetSupported: {module}.{name} is a release gap ({owner})" or (
            name == "dump_recipe" and error.startswith("NotYetSupported") and owner in error
        ), (module, name, error)
    assert all(e.startswith("UnsupportedProcedural") for e in result["procedural"])
    assert result["gaps"][0].startswith("NotYetSupported") and "Triplanar" in result["gaps"][0]
    assert result["gaps"][1].startswith("NotYetSupported")
    assert result["gaps"][2].startswith("ValueError")  # compare masks are mask-stack only
    assert result["before"] == result["after"]


# ── 3.4 transactions ────────────────────────────────────────────────────────────────────────────


def test_failed_call_leaves_no_mutation(run: Run) -> None:
    result = ok(
        run("""
        stack = create()
        fill = ls.insert_fill(top(stack))
        rev = project.revision()
        errors = [
            raises(fill.set_opacity, 1.5, CT.BaseColor),  # validation: opacity outside 0..1
            raises(fill.set_opacity, 0.5),  # a content node needs a channel
            raises(fill.set_blending_mode, ls.BlendingMode.Multiply, CT.User7),  # no such channel
            raises(ls.insert_fill, ls.InsertPosition.inside_node(fill, ls.NodeStack.Substack)),
        ]
        result = {
            "errors": errors,
            "rev": [rev, project.revision()],
            "opacity": fill.get_opacity(CT.BaseColor),
            "last": uzpainter.last_result().status,
        }
        """)
    )
    assert [e.split(":")[0] for e in result["errors"]] == [
        "ValueError",
        "EditionContextException",
        "ValueError",
        "ValueError",
    ]
    assert result["rev"][0] == result["rev"][1]
    assert result["opacity"] == 1.0


def test_script_raising_after_two_calls_keeps_both(run: Run) -> None:
    report = run("""
        stack = create()
        a = ls.insert_fill(top(stack))
        b = ls.insert_fill(top(stack))
        raise RuntimeError("the script fails after two calls")
        """)
    assert report["status"] == "failed"
    assert report["error"]["type"] == "RuntimeError"
    assert "after two calls" in report["error"]["traceback"]
    committed = report["committed"]
    assert [c["status"] for c in committed] == ["committed"] * 3  # create + two inserts
    assert report["last_committed_revision"] == committed[-1]["revision"] == 3
    assert len(committed[1]["created"]) == 1 and len(committed[2]["created"]) == 1


def test_raising_transaction_commits_nothing_and_a_clean_one_commits_once(run: Run) -> None:
    result = ok(
        run("""
        stack = create()
        rev = project.revision()
        try:
            with uzpainter.Transaction("two layers"):
                a = ls.insert_fill(top(stack))
                b = ls.insert_fill(top(stack))
                inside = [
                    project.revision(),
                    len(ls.get_root_layer_nodes(stack)),
                    uzpainter.last_result().status,
                ]
                raise KeyError("abort")
        except KeyError:
            pass
        aborted = [
            project.revision(),
            len(ls.get_root_layer_nodes(stack)),
            raises(ls.get_node_by_uid, a.uid()),
        ]
        with uzpainter.Transaction("two layers") as t:
            a = ls.insert_fill(top(stack))
            a.set_name("first")
            b = ls.insert_group(top(stack))
            b.set_visible(False)
        r = t.result
        result = {
            "rev": rev,
            "inside": inside,
            "aborted": aborted,
            "committed": [r.status, r.revision, r.created, r.modified, r.hidden],
            "uids": [a.uid(), b.uid()],
            "roots": [n.get_name() for n in ls.get_root_layer_nodes(stack)],
        }
        """)
    )
    rev = result["rev"]
    assert result["inside"] == [rev, 2, "pending"]
    assert result["aborted"][:2] == [rev, 0]
    assert result["aborted"][2].startswith("ValueError")
    status, revision, created, _modified, hidden = result["committed"]
    assert (status, revision) == ("committed", rev + 1)
    assert created == sorted(result["uids"])
    assert hidden == []  # created hidden is created, not visible -> hidden
    assert result["roots"] == ["Folder", "first"]


def test_results_list_created_modified_hidden_and_resources(run: Run) -> None:
    result = ok(
        run("""
        stack = create()
        fill = ls.insert_fill(top(stack))
        created = uzpainter.last_result().created
        hide = fill.set_visible(False)
        same = fill.set_visible(False)
        first = resource.import_project_resource(IMAGES + "/checker-16.png", resource.Usage.TEXTURE)
        imported = uzpainter.last_result()
        again = resource.import_project_resource(IMAGES + "/checker-16.png", resource.Usage.TEXTURE)
        skipped = uzpainter.last_result()
        result = {
            "created": created,
            "fill": fill.uid(),
            "hide": [hide.status, hide.modified, hide.hidden],
            "same": [same.status, same.revision == hide.revision],
            "imported": [imported.status, imported.imported, imported.skipped],
            "skipped": [skipped.status, skipped.imported, skipped.skipped],
            "url": first.identifier().url(),
        }
        """)
    )
    assert result["created"] == [result["fill"]]
    assert result["hide"] == ["committed", [], [result["fill"]]]  # visible -> hidden is `hidden`
    assert result["same"] == ["no_op", True]
    sha = result["url"].rsplit("=", 1)[1]
    assert result["imported"] == ["committed", [sha], []]
    assert result["skipped"] == ["no_op", [], [sha]]


def test_a_call_waiting_for_another_threads_transaction_gets_stale_revision(run: Run) -> None:
    result = ok(
        run("""
        stack = create()
        fill = ls.insert_fill(top(stack))
        outcome = {}


        def other():
            outcome["error"] = raises(fill.set_name, "from the other thread")


        with uzpainter.Transaction():
            fill.set_name("inside")
            worker = threading.Thread(target=other)
            worker.start()
            time.sleep(0.3)  # the worker waits for the document lock with the GIL released
            outcome["alive_during_block"] = worker.is_alive()
        worker.join()
        result = {"outcome": outcome, "name": fill.get_name()}
        """)
    )
    assert result["outcome"]["alive_during_block"] is True
    assert result["outcome"]["error"].startswith("StaleRevisionError")
    assert result["name"] == "inside"


# ── 3.5 name addressing (LAY-06) ────────────────────────────────────────────────────────────────


def test_ambiguous_name_fails_before_mutation_and_named_inserts_do_not_duplicate(run: Run) -> None:
    result = ok(
        run("""
        stack = create()
        a = ls.insert_fill(top(stack), name="trim")
        b = ls.insert_fill(ls.InsertPosition.below_node(a))
        b.set_name("trim")
        rev = project.revision()
        try:
            ls.get_node_by_name("trim").set_opacity(0.5, CT.BaseColor)
            ambiguous = None
        except exception.AmbiguousNameError as error:
            ambiguous = [str(error), error.candidates, isinstance(error, ValueError)]
        insert = raises(ls.insert_fill, top(stack), name="trim")
        after_ambiguous = project.revision()
        g1 = ls.insert_group(top(stack), name="body")
        r1 = uzpainter.last_result()
        g2 = ls.insert_group(top(stack), name="body")
        r2 = uzpainter.last_result()
        wrong_type = raises(ls.insert_fill, top(stack), name="body")
        child1 = ls.insert_fill(
            ls.InsertPosition.inside_node(g1, ls.NodeStack.Substack), name="trim"
        )
        child2 = ls.insert_fill(
            ls.InsertPosition.inside_node(g1, ls.NodeStack.Substack), name="trim"
        )
        scoped = ls.get_node_by_name("trim", parent=g1).uid()
        path = WORK + "/names.uzp"
        project.save_as(path)
        project.close()
        project.open(path)
        stack = ts.get_active_stack()
        g3 = ls.insert_group(top(stack), name="body")
        r3 = uzpainter.last_result()
        result = {
            "ab": [a.uid(), b.uid()],
            "ambiguous": ambiguous,
            "insert": insert,
            "rev": [rev, after_ambiguous],
            "g": [g1.uid(), g2.uid(), g3.uid()],
            "r": [r1.status, r2.status, r3.status, r2.returned],
            "wrong_type": wrong_type,
            "child": [child1.uid(), child2.uid(), scoped],
            "reopened": ls.get_node_by_name("body").uid(),
            "all_trim": len(ls.find_nodes_by_name("trim")),
        }
        """)
    )
    a, b = result["ab"]
    message, candidates, is_value_error = result["ambiguous"]
    assert candidates == [a, b] and is_value_error and str(a) in message and str(b) in message
    assert result["insert"].startswith("AmbiguousNameError")
    assert result["rev"][0] == result["rev"][1]
    g1, g2, g3 = result["g"]
    assert g1 == g2 == g3 == result["reopened"]
    assert result["r"][:3] == ["committed", "no_op", "no_op"]
    assert result["wrong_type"].startswith("ValueError")
    child1, child2, scoped = result["child"]
    assert child1 == child2 == scoped
    assert result["all_trim"] == 3


# ── 3.6 sync_stack (LAY-07) ─────────────────────────────────────────────────────────────────────


def test_sync_stack_rebuilds_only_the_named_group_and_hides_others(
    run: Run, tmp_path: Path
) -> None:
    masks = tmp_path / "masks"
    masks.mkdir()
    shutil.copy(PROBE_IMAGES / "mask-left-half.png", masks / "M_left.png")
    shutil.copy(PROBE_IMAGES / "checker-16.png", masks / "T_checker.png")
    shutil.copy(PROBE_IMAGES / "ao-white.png", masks / "M_c_only.png")
    stack_json = {
        "title": "B",
        "groups": [
            {"key": "outer", "name": "Outer", "mask": None},
            {"key": "lining", "name": "Lining", "mask": "M_left", "replace_height": True},
        ],
        "layers": [
            {
                "id": "L1",
                "group": "outer",
                "name": "base",
                "base": [204, 51, 26],
                "rough": 0.86,
                "op": 0.5,
            },
            {
                "id": "L2",
                "group": "outer",
                "name": "top",
                "base": [0.1, 0.2, 0.3],
                "height": -0.03,
                "mask": "M_left",
            },
            {"id": "L3", "group": "lining", "name": "tex", "base_tex": "T_checker", "metal": 0.0},
        ],
    }
    (tmp_path / "stack.json").write_text(json.dumps({"tunic": stack_json}), encoding="utf-8")
    original = (tmp_path / "stack.json").read_bytes()
    result = ok(
        run("""
        stack = create()
        c_res = resource.import_project_resource(
            WORK + "/masks/M_c_only.png", resource.Usage.TEXTURE
        )
        a = ls.insert_group(top(stack), name="A keep")
        b_old = ls.insert_group(top(stack), name="B")
        ls.insert_fill(
            ls.InsertPosition.inside_node(b_old, ls.NodeStack.Substack), name="old content"
        )
        c = ls.insert_group(top(stack), name="C")
        c_fill = ls.insert_fill(ls.InsertPosition.inside_node(c, ls.NodeStack.Substack))
        c_fill.active_channels = {CT.BaseColor}
        c_fill.set_source(CT.BaseColor, c_res.identifier())
        r = ls.sync_stack(
            WORK + "/stack.json", WORK + "/masks", keep_visible=["A"], stack_key="tunic"
        )
        sync = r.returned["sync"]
        root = ls.get_node_by_uid(sync["root_uid"])


        def tree(node):
            out = {
                "name": node.get_name(),
                "visible": node.is_visible(),
                "type": str(node.get_type()),
            }
            if isinstance(node, ls.GroupLayerNode):
                out["children"] = [tree(x) for x in node.sub_layers()]
            if isinstance(node, ls.LayerNode) and node.has_mask():
                out["mask"] = [
                    str(node.get_mask_background()),
                    [e.get_name() for e in node.mask_effects()],
                ]
            if isinstance(node, ls.FillLayerNode):
                out["active"] = sorted(str(ch) for ch in node.active_channels)
                out["opacity"] = node.get_opacity(CT.BaseColor)
            return out


        top_fill = ls.get_node_by_name("top", parent=ls.get_node_by_name("Outer", parent=root))
        tex = ls.get_node_by_name("tex", parent=ls.get_node_by_name("Lining", parent=root))
        lining = ls.get_node_by_name("Lining", parent=root)
        result = {
            "status": r.status,
            "sync": sync,
            "hidden_ids": r.hidden,
            "removed": r.removed,
            "roots": [
                [n.get_name(), n.is_visible(), n.uid()] for n in ls.get_root_layer_nodes(stack)
            ],
            "a": a.uid(),
            "c": c.uid(),
            "c_fill_source": c_fill.get_source(CT.BaseColor).resource_id().url(),
            "c_res": c_res.identifier().url(),
            "b_old_stale": raises(b_old.get_name),
            "tree": tree(root),
            "top_height": list(top_fill.get_source(CT.Height).get_color().value_raw),
            "top_base": [
                list(top_fill.get_source(CT.BaseColor).get_color().value_raw),
                top_fill.get_source(CT.BaseColor).get_color().color_space,
            ],
            "tex": [
                tex.get_source(CT.BaseColor).get_color_space(),
                str(tex.get_projection_mode()),
                str(tex.get_projection_parameters().uv_wrapping_mode),
            ],
            "lining_height": str(lining.get_blending_mode(CT.Height)),
            "height_blending": {
                n.get_name(): str(n.get_blending_mode(CT.Height))
                for n in (root, ls.get_node_by_name("Outer", parent=root), top_fill, tex)
            },
            "base_sources": [
                list(n.get_source(CT.Height).get_color().value_raw) for n in (
                    ls.get_node_by_name("base", parent=ls.get_node_by_name("Outer", parent=root)),
                    tex,
                )
            ],
            "resources": sorted(x.name for x in resource.list_project_resources()),
        }
        again = ls.sync_stack(
            WORK + "/stack.json", WORK + "/masks", keep_visible=["A"], stack_key="tunic"
        )
        result["again"] = [
            again.status,
            again.returned["sync"]["imported"],
            again.returned["sync"]["skipped"],
            again.returned["sync"]["deleted"] == [sync["root_uid"]],
        ]
        """)
    )
    assert (tmp_path / "stack.json").read_bytes() == original  # the JSON is read, never edited
    assert result["status"] == "committed"
    roots = result["roots"]
    assert [r[0] for r in roots] == ["B", "C", "A keep"]
    assert [r[1] for r in roots] == [True, False, True]  # C hidden (not deleted), A kept visible
    assert roots[1][2] == result["c"] and roots[2][2] == result["a"]
    assert result["hidden_ids"] == [result["c"]]
    assert result["b_old_stale"].startswith("ValueError")
    assert result["c_fill_source"] == result["c_res"]  # C's resources survive
    tree = result["tree"]
    assert [g["name"] for g in tree["children"]] == ["Lining", "Outer"]  # bottom to top in the JSON
    outer = tree["children"][1]
    assert [x["name"] for x in outer["children"]] == ["top", "base"]
    base = outer["children"][1]
    assert base["active"] == ["ChannelType.BaseColor", "ChannelType.SpecularRoughness"]
    assert base["opacity"] == 0.5
    assert outer["children"][0]["mask"] == ["MaskBackground.Black", ["M_left"]]
    assert tree["children"][0]["mask"] == ["MaskBackground.Black", ["M_left"]]
    # `base` is stored as the facade stores the script's sRGB colour: its float32 working value
    # on the sRGB8 BaseColor (decision 115).
    assert result["top_base"] == [
        [0.010022825561463833, 0.03310476243495941, 0.07323896884918213],
        "Working",
    ]
    assert result["tex"] == ["sRGB", "ProjectionMode.UV", "UVWrapMode.RepeatNone"]
    assert result["lining_height"] == "BlendingMode.Normal"
    # Painter's insert defaults, as the script's inserted nodes get them (decision 115): Height
    # adds unless the group replaces it, and a fill without a height keeps the default source 0.
    assert result["height_blending"] == {
        "B": "BlendingMode.LinearDodge",
        "Outer": "BlendingMode.LinearDodge",
        "top": "BlendingMode.LinearDodge",
        "tex": "BlendingMode.LinearDodge",
    }
    assert result["base_sources"] == [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    assert result["sync"]["imported"] == ["M_left", "T_checker"]
    assert result["resources"] == ["M_c_only", "M_left", "T_checker", "plane.obj"]
    assert result["again"] == ["committed", [], ["M_left", "T_checker"], True]


# ── 3.7 in-place resource replacement (LAY-08) ──────────────────────────────────────────────────


def test_replacing_a_mask_resource_keeps_the_node_and_changes_only_that_binding(run: Run) -> None:
    result = ok(
        run("""
        stack = create()
        left = resource.import_project_resource(
            IMAGES + "/mask-left-half.png", resource.Usage.TEXTURE
        ).identifier()
        white = resource.import_project_resource(
            IMAGES + "/ao-white.png", resource.Usage.TEXTURE
        ).identifier()
        checker = resource.import_project_resource(
            IMAGES + "/checker-16.png", resource.Usage.TEXTURE
        ).identifier()
        layer = ls.insert_fill(top(stack))
        layer.active_channels = {CT.BaseColor}
        layer.set_source(CT.BaseColor, checker)
        layer.add_mask(ls.MaskBackground.Black)
        m1 = ls.insert_fill(ls.InsertPosition.inside_node(layer, ls.NodeStack.Mask))
        m1.set_source(None, left)
        m2 = ls.insert_fill(ls.InsertPosition.inside_node(layer, ls.NodeStack.Mask))
        m2.set_source(None, left)
        r = resource.replace_node_resource(m1, white)
        wrong = [
            raises(resource.replace_node_resource, m1, white, CT.BaseColor),
            raises(resource.replace_node_resource, layer, white),
        ]
        result = {
            "r": [r.status, r.modified, r.created, r.removed],
            "m1": [m1.uid(), ls.get_node_by_uid(m1.uid()).get_source(None).resource_id().url()],
            "m2": m2.get_source(None).resource_id().url(),
            "layer": layer.get_source(CT.BaseColor).resource_id().url(),
            "urls": [left.url(), white.url(), checker.url()],
            "wrong": wrong,
        }
        """)
    )
    left, white, checker = result["urls"]
    assert result["r"] == ["committed", [result["m1"][0]], [], []]
    assert result["m1"][1] == white
    assert result["m2"] == left
    assert result["layer"] == checker
    assert result["wrong"][0].startswith("ValueError") and result["wrong"][1].startswith(
        "EditionContextException"
    )


# ── 3.8 the GIL is released while the command thread waits on an export job ────────────────────

EXPORT_CONFIG = json.dumps(
    {
        "exportShaderParams": False,
        "defaultExportPreset": "height",
        "exportPresets": [
            {
                "name": "height",
                "maps": [
                    {
                        "fileName": "$textureSet_height",
                        "channels": [
                            {
                                "destChannel": "L",
                                "srcChannel": "L",
                                "srcMapType": "documentMap",
                                "srcMapName": "height",
                            }
                        ],
                        "parameters": {
                            "fileFormat": "png",
                            "bitDepth": "16",
                            "dithering": False,
                            "paddingAlgorithm": "infinite",
                        },
                    }
                ],
            }
        ],
        "exportList": [{"rootPath": "uzp_plane"}],
    }
)
# The script's expression of the configuration, exporting under the test's folder.
CONFIG_EXPRESSION = f"dict(json.loads({EXPORT_CONFIG!r}), exportPath=WORK + '/export')"


def test_a_second_thread_runs_while_the_command_thread_waits_on_an_export(run: Run) -> None:
    result = ok(
        run(
            with_values("""
        stack = create(1024)
        fill = ls.insert_fill(top(stack))
        fill.active_channels = {CT.Height}
        fill.set_source(CT.Height, cm.Color(0.25, 0.25, 0.25, "Raw"))
        config = __CONFIG__
        ticks = []
        stop = threading.Event()


        def spin():
            while not stop.is_set():
                ticks.append(time.perf_counter())


        worker = threading.Thread(target=spin)
        worker.start()
        start = time.perf_counter()
        out = export.export_project_textures(config, fixed_names=[WORK + "/flat"])
        end = time.perf_counter()
        stop.set()
        worker.join()
        during = sum(1 for t in ticks if start < t < end)
        files = sorted(os.listdir(WORK + "/flat"))
        result = {
            "during": during,
            "seconds": end - start,
            "out": out,
            "files": files,
            "jobs": [[j.kind, j.status, j.progress] for j in jobs.list()],
        }
        """)
        )
    )
    assert result["during"] > 0
    out = result["out"]
    assert out["generation"] and out["revision"] == 4
    assert [f["relative_path"] for f in out["files"]] == ["uzp_plane_height.png"]
    assert "uzp_plane_height.png" in result["files"]
    assert result["jobs"] == [["export", "succeeded", 1.0]]


def test_export_plan_dry_run_and_job_errors(run: Run) -> None:
    result = ok(
        run(
            with_values("""
        stack = create()
        fill = ls.insert_fill(top(stack))
        fill.active_channels = {CT.Height}
        fill.set_source(CT.Height, cm.Color(0.25, 0.25, 0.25, "Raw"))
        config = __CONFIG__
        plan = export.plan(config)
        listed = {"/".join(k): v for k, v in export.list_project_textures(config).items()}
        bad = dict(config, exportList=[{"rootPath": "nope"}])
        errors = [raises(export.plan, bad), raises(export.export_project_textures, bad)]
        job = export.start(bad)
        job_error = raises(job.wait)
        busy = []
        queued = [export.start(config) for _ in range(3)]
        busy.append(raises(project.close))
        for j in queued:
            j.wait()
        result = {
            "plan": [plan["schema"], len(plan["files"]), plan["hash"]],
            "listed": listed,
            "errors": errors,
            "job": [job.status, job_error],
            "busy": busy,
            "closed": raises(project.close),
        }
        """)
        )
    )
    schema, count, digest = result["plan"]
    assert schema == "uzpainter/export-plan/1" and count == 1 and len(digest) == 64
    [(root, files)] = result["listed"].items()
    assert root == "uzp_plane/" and len(files) == 1
    assert files[0].replace("\\", "/").endswith("/export/uzp_plane_height.png")
    assert all(e.startswith("ValueError") for e in result["errors"])
    assert result["job"][0] == "failed" and result["job"][1].startswith("ValueError")
    assert result["busy"][0].startswith("BusyError")
    assert result["closed"] is None
