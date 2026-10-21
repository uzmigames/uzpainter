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

from tests.export.encoders_tier0 import srgb_to_working
from tests.python.conftest import PROBE_IMAGES, REPO_ROOT, Run, png_file
from tools.parity import ocio_srgb_table
from tools.parity.fit.decode import decode

# Painter's substance config (decisions 134, 207): the one OCIO configuration a project is made in.
OCIO_CONFIG = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"


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
    # A uniform colour is stored as Painter stores it, its working value (decision 240): sRGB
    # decoded on the sRGB8 BaseColor, Raw and a colour without a space on Height as given.
    assert before["base"] == [[srgb_to_working(c) for c in (0.8, 0.2, 0.1)], "Working"]
    assert before["rough"] == [[f32(0.35)] * 3, "Working"]
    assert before["height"] == [[0.25] * 3, "Working"]
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


def test_a_project_is_created_under_painters_ocio_config_only(run: Run) -> None:
    """Decision 207: `Settings(ocio_config_hash=...)` creates an OCIO project with Painter's
    substance config, which save and reopen keep; any other hash fails before anything is created,
    and a project created without one is Legacy."""
    result = ok(
        run("""
        SUBSTANCE = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"
        other = raises(project.create, PLANE, project.Settings(ocio_config_hash="ab" * 32))
        open_after_other = project.is_open()
        create()
        legacy = cm.get_color_management()
        project.close()
        project.create(PLANE, project.Settings(default_texture_resolution=256,
                                               ocio_config_hash=SUBSTANCE))
        created = cm.get_color_management()
        project.save_as(WORK + "/ocio.uzp")
        project.close()
        project.open(WORK + "/ocio.uzp")
        reopened = cm.get_color_management()
        project.close()
        result = {"other": other, "open_after_other": open_after_other, "legacy": legacy,
                  "created": created, "reopened": reopened}
        """)
    )
    assert result["other"].startswith("NotYetSupported: an OCIO project with the configuration ab")
    assert result["open_after_other"] is False
    assert result["legacy"]["mode"] == "" and result["legacy"]["config_hash"] == ""
    substance = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"
    assert result["created"] == {
        "config_hash": substance,
        "io_rules": [],
        "mode": "ocio",
        "working_space": "",
    }
    assert result["reopened"] == result["created"]


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


def test_empty_paint_layers(run: Run) -> None:
    """phase4.1_nodes-paint-layers items 2.1, 2.4 and 2.8 (decision 348): `project.create` puts
    Painter's empty "Layer 1" at the bottom of the stack; `insert_paint` gives a layer named
    "Paint" (`phase1-layer-stack-events` s14) and, in a content stack, a paint effect, which stays
    refused; an empty paint layer is edited and evaluated, a content effect on one is refused before
    any change."""
    result = ok(
        run("""
        stack = create()
        roots = ls.get_root_layer_nodes(stack)
        default = [[n.get_name(), n.get_type().name, type(n).__name__, n.is_visible()]
                   for n in roots]
        fill = ls.insert_fill(top(stack))
        fill.active_channels = {CT.BaseColor}
        fill.set_source(CT.BaseColor, cm.Color(0.5, 0.25, 0.75, "Raw"))
        paint = ls.insert_paint(top(stack))
        paint.set_name("uzp paint")
        paint.set_opacity(0.5, CT.BaseColor)
        paint.set_visible(False)
        paint.set_visible(True)
        before = project.revision()
        refused = [
            raises(ls.insert_levels_effect,
                   ls.InsertPosition.inside_node(paint, ls.NodeStack.Content)),
            raises(ls.insert_paint, ls.InsertPosition.inside_node(fill, ls.NodeStack.Content)),
        ]
        after = project.revision()
        layer1 = roots[0]
        ls.delete_node(layer1)
        result = {
            "default": default,
            "paint": [paint.get_name(), paint.get_type().name, type(paint).__name__],
            "order": [n.get_name() for n in ls.get_root_layer_nodes(stack)],
            "refused": refused,
            "revisions": [before, after],
        }
        """)
    )
    assert result["default"] == [["Layer 1", "PaintLayer", "PaintLayerNode", True]]
    assert result["paint"] == ["uzp paint", "PaintLayer", "PaintLayerNode"]
    assert result["order"] == ["uzp paint", "Fill"]
    assert "a content effect on a paint layer" in result["refused"][0], result["refused"]
    assert "a paint effect" in result["refused"][1], result["refused"]
    assert all(r.startswith("NotYetSupported") for r in result["refused"])
    assert result["revisions"][0] == result["revisions"][1]


LATER_PHASE = [
    ("uzpainter.baking", "bake_async", "phase3.5_embree-bakers"),
    ("uzpainter.baking", "bake_selected_textures_async", "phase3.5_embree-bakers"),
    ("uzpainter.baking", "set_linked_group", "phase3.5_embree-bakers"),
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
            # An empty paint layer is evaluated (decision 348); a paint effect is not.
            raises(ls.insert_paint, ls.InsertPosition.inside_node(fill, ls.NodeStack.Content)),
            raises(
                ls.insert_compare_mask_effect,
                ls.InsertPosition.inside_node(fill, ls.NodeStack.Content),
            ),
        ]
        # `uzpainter.render.capture` is implemented (phase2.2, decision 148); its mode
        # painter_iray stays a release gap, refused before any work (no file written).
        iray = raises(uzpainter.render.capture, WORK + "/iray.png", "painter_iray")
        iray_written = os.path.exists(WORK + "/iray.png")
        result = {
            "out": out,
            "procedural": procedural,
            "gaps": gaps,
            "iray": [iray, iray_written],
            "before": list(before),
            "after": [project.revision(), project.needs_saving()],
        }
        """)
        )
    )
    for module, name, owner, error in result["out"]:
        assert error == f"NotYetSupported: {module}.{name} is a release gap ({owner})", (
            module,
            name,
            error,
        )
    assert all(e.startswith("UnsupportedProcedural") for e in result["procedural"])
    assert result["gaps"][0].startswith("NotYetSupported") and "Triplanar" in result["gaps"][0]
    assert result["gaps"][1].startswith("NotYetSupported") and "a paint effect" in result["gaps"][1]
    assert result["gaps"][2].startswith("ValueError")  # compare masks are mask-stack only
    iray, iray_written = result["iray"]
    assert iray.startswith("PathTracerUnavailable") and not iray_written, iray
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
    # Painter's default "Layer 1" is the bottom root of every new stack (decision 348).
    assert result["inside"] == [rev, 3, "pending"]
    assert result["aborted"][:2] == [rev, 1]
    assert result["aborted"][2].startswith("ValueError")
    status, revision, created, _modified, hidden = result["committed"]
    assert (status, revision) == ("committed", rev + 1)
    assert created == sorted(result["uids"])
    assert hidden == []  # created hidden is created, not visible -> hidden
    assert result["roots"] == ["Folder", "first", "Layer 1"]


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
    # Painter's default "Layer 1" is hidden like C, as the wand-v1 golden records (decision 348).
    assert [r[0] for r in roots] == ["B", "C", "A keep", "Layer 1"]
    assert [r[1] for r in roots] == [True, False, True, False]  # C hidden (not deleted), A kept
    assert roots[1][2] == result["c"] and roots[2][2] == result["a"]
    assert sorted(result["hidden_ids"]) == sorted([result["c"], roots[3][2]])
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


def test_sync_stack_under_ocio_reads_painters_measured_decode(run: Run, tmp_path: Path) -> None:
    """Decisions 202 and 212: on an OCIO project, `base` on the sRGB8 BaseColor is stored as the
    facade stores it, Painter's measured working value of each component (the native table
    generated from `ocio_srgb.py`); a component the table does not record raises
    `NotYetSupported` and nothing is committed."""
    (tmp_path / "masks").mkdir()
    recorded = {
        "title": "T",
        "groups": [{"key": "g", "name": "G", "mask": None}],
        "layers": [{"id": "L1", "group": "g", "name": "base", "base": [204, 51, 26]}],
    }
    unrecorded = json.loads(json.dumps(recorded))
    unrecorded["layers"][0]["base"] = [0.1, 0.2, 0.3]
    (tmp_path / "stack.json").write_text(
        json.dumps({"recorded": recorded, "unrecorded": unrecorded}), encoding="utf-8"
    )
    result = ok(
        run("""
        project.create(PLANE, project.Settings(default_texture_resolution=256,
            ocio_config_hash="15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"))
        r = ls.sync_stack(WORK + "/stack.json", WORK + "/masks", stack_key="recorded")
        root = ls.get_node_by_uid(r.returned["sync"]["root_uid"])
        layer = ls.get_node_by_name("base", parent=ls.get_node_by_name("G", parent=root))
        colour = layer.get_source(CT.BaseColor).get_color()
        rev = project.revision()
        refused = raises(ls.sync_stack, WORK + "/stack.json", WORK + "/masks",
                         stack_key="unrecorded")
        result = {"status": r.status, "base": [list(colour.value_raw), colour.color_space],
                  "refused": refused, "unchanged": project.revision() == rev}
        """)
    )
    codes = ocio_srgb_table.load_source().CODES
    assert result["status"] == "committed"
    assert result["base"] == [[codes[204], codes[51], codes[26]], "Working"]
    assert result["refused"].startswith(
        "NotYetSupported: sync_stack: under OCIO, Painter's working value of the sRGB component 0.1"
    )
    assert result["refused"].endswith("(the base colour of 'base')")
    assert result["unchanged"] is True


def test_sync_stack_decodes_base_as_every_setter_does(run: Run, tmp_path: Path) -> None:
    """B1, F5 (practical-e2e, decision 240): `sync_stack` stores `base` through the one decode
    every setter uses, so it equals `set_source` of the same sRGB colour and Painter's float32
    decode (decision 214). 70, 98 and 133 / 255 are codes where dividing by 1.055f instead of
    multiplying by its float32 reciprocal (sync_stack's own decode before) misses Painter."""
    (tmp_path / "masks").mkdir()
    stack_json = {
        "title": "T",
        "groups": [{"key": "g", "name": "G", "mask": None}],
        "layers": [{"id": "L1", "group": "g", "name": "base", "base": [70, 98, 133]}],
    }
    (tmp_path / "stack.json").write_text(json.dumps(stack_json), encoding="utf-8")
    result = ok(
        run("""
        stack = create()
        r = ls.sync_stack(WORK + "/stack.json", WORK + "/masks")
        root = ls.get_node_by_uid(r.returned["sync"]["root_uid"])
        synced = ls.get_node_by_name("base", parent=ls.get_node_by_name("G", parent=root))
        fill = ls.insert_fill(top(stack))
        fill.set_source(CT.BaseColor, cm.Color(70 / 255, 98 / 255, 133 / 255, "sRGB"))
        result = [list(n.get_source(CT.BaseColor).get_color().value_raw) for n in (synced, fill)]
        """)
    )
    expected = [srgb_to_working(c / 255) for c in (70, 98, 133)]
    assert result == [expected, expected]


# ── B5: OCIO bitmaps refused before mutation (decision 240) ─────────────────────────────────────


OCIO_BITMAPS = f"""
SUBSTANCE = {OCIO_CONFIG!r}
project.create(PLANE, project.Settings(default_texture_resolution=256, ocio_config_hash=SUBSTANCE))
stack = ts.get_active_stack()
images = {{name: resource.import_project_resource(WORK + "/" + name + ".png",
                                                  resource.Usage.TEXTURE).identifier()
          for name in ("rgb8_256", "rgb8_128", "grey8_256", "grey16_256")}}
fill = ls.insert_fill(top(stack))
fill.active_channels = {{CT.BaseColor}}
fill.add_mask(ls.MaskBackground.Black)
mask = ls.insert_fill(ls.InsertPosition.inside_node(fill, ls.NodeStack.Mask))
other = ls.insert_fill(top(stack))
other.active_channels = {{CT.BaseColor}}
out = {{}}

def refused(name, call, *args):
    revision = project.revision()
    out[name] = [raises(call, *args), project.revision() == revision]

refused("small", fill.set_source, CT.BaseColor, images["rgb8_128"], "sRGB")
refused("grey_mask", mask.set_source, None, images["grey8_256"], "Data")
out["one_to_one"] = fill.set_source(CT.BaseColor, images["rgb8_256"], "sRGB").get_color_space()
out["grey16_mask"] = mask.set_source(None, images["grey16_256"], "Data").get_color_space()
fill.set_projection_mode(ls.ProjectionMode.UV)
refused("scaled", fill.set_projection_parameters, ls.UVProjectionParams(
    uv_transformation=ls.UVTransformationParams(scale=[2.0, 2.0])))
refused("resized", stack.material().set_resolution, ts.Resolution(512, 512))

# Imported and bound in one transaction: the support check reads the staged bytes.
def staged():
    with uzpainter.Transaction("import and bind"):
        image = resource.import_project_resource(WORK + "/rgb8_64.png", resource.Usage.TEXTURE)
        other.set_source(CT.BaseColor, image.identifier(), "sRGB")
refused("staged", staged)
out["staged_resources"] = sorted(r.name for r in resource.list_project_resources())

# Legacy keeps these refusals at evaluation (sources.h).
project.close()
create()
legacy = ls.insert_fill(top(ts.get_active_stack()))
small = resource.import_project_resource(WORK + "/rgb8_128.png", resource.Usage.TEXTURE)
out["legacy_small"] = legacy.set_source(CT.BaseColor, small.identifier(), "sRGB").get_color_space()
result = out
"""


def test_ocio_bitmaps_the_evaluator_refuses_are_refused_before_mutation(
    run: Run, tmp_path: Path
) -> None:
    """B5 (practical-e2e, decision 240): under OCIO a bitmap use Session O does not record (an
    8-bit colour bitmap not at 1:1, an 8-bit grey mask source) is refused by the support check
    before anything is committed, from the PNG header, as the evaluation refuses it: on bind, on a
    projection change, on a resize of the texture set, and for bytes imported in the same
    transaction. Legacy keeps the evaluation's refusal."""
    for name, size, channels, depth in (
        ("rgb8_256", 256, 3, 8),
        ("rgb8_128", 128, 3, 8),
        ("rgb8_64", 64, 3, 8),
        ("grey8_256", 256, 1, 8),
        ("grey16_256", 256, 1, 16),
    ):
        png_file(tmp_path / f"{name}.png", size, channels, depth)
    result = ok(run(OCIO_BITMAPS))
    for name in ("small", "grey_mask", "scaled", "resized", "staged"):
        message, unchanged = result[name]
        assert message.startswith("NotYetSupported: node="), (name, message)
        assert unchanged is True, name
    assert (
        "under OCIO, a 128x128 8-bit colour bitmap on the channel BaseColor of a 256x256"
        in (result["small"][0])
    )
    assert "a 256x256 8-bit grey bitmap as a mask source" in result["grey_mask"][0]
    assert (
        "a 256x256 8-bit colour bitmap on the channel BaseColor of a 512x512"
        in (result["resized"][0])
    )
    assert "a 64x64 8-bit colour bitmap" in result["staged"][0]
    assert "rgb8_64" not in result["staged_resources"]
    assert result["one_to_one"] == "sRGB" and result["grey16_mask"] == "Data"
    assert result["legacy_small"] == "sRGB"


OCIO_RESIZE = f"""
SUBSTANCE = {OCIO_CONFIG!r}
project.create(PLANE, project.Settings(default_texture_resolution=256, ocio_config_hash=SUBSTANCE))
stack = ts.get_active_stack()
material = stack.material()
images = {{size: resource.import_project_resource(WORK + "/rgb8_" + str(size) + ".png",
                                                  resource.Usage.TEXTURE).identifier()
          for size in (256, 512)}}
fill = ls.insert_fill(top(stack))
fill.active_channels = {{CT.BaseColor}}
fill.set_source(CT.BaseColor, images[256], "sRGB")
out = {{}}

def state():
    return [material.get_resolution().width,
            fill.get_source(CT.BaseColor).resource_id().url() == images[512].url()]

with uzpainter.Transaction("resize, then rebind") as t:
    material.set_resolution(ts.Resolution(512, 512))
    fill.set_source(CT.BaseColor, images[512], "sRGB")
out["resize_then_rebind"] = [t.result.status, state()]
with uzpainter.Transaction("rebind, then resize") as t:
    fill.set_source(CT.BaseColor, images[256], "sRGB")
    material.set_resolution(ts.Resolution(256, 256))
out["rebind_then_resize"] = [t.result.status, state()]

# A transaction whose final state the evaluation refuses commits nothing.
def resize_only():
    with uzpainter.Transaction("resize only"):
        material.set_resolution(ts.Resolution(512, 512))
revision = project.revision()
out["resize_only"] = [raises(resize_only), project.revision() == revision, state()]

# Outside a transaction every call commits, so its state is checked: another source first.
routed = [raises(material.set_resolution, ts.Resolution(512, 512))]
fill.set_source(CT.BaseColor, cm.Color(0.5, 0.5, 0.5, "Working"))
routed.append(uzpainter.last_result().status)
routed.append(material.set_resolution(ts.Resolution(512, 512)).status)
fill.set_source(CT.BaseColor, images[512], "sRGB")
routed.append(uzpainter.last_result().status)
out["routed"] = routed + [state()]
result = out
"""


def test_an_ocio_resize_and_rebind_commit_in_one_transaction_in_either_order(
    run: Run, tmp_path: Path
) -> None:
    """Decision 240 review: under OCIO a texture set holding a 1:1 bitmap is resized and rebound
    to an image of the new size in one `uzpainter.Transaction`, in either order. The intermediate
    state of each order is a use Session O does not record; only the state that commits is
    checked. A transaction that commits such a state is refused at its end; outside one, every
    call commits and is checked, so another source is bound before the resize."""
    for size in (256, 512):
        png_file(tmp_path / f"rgb8_{size}.png", size, 3, 8)
    result = ok(run(OCIO_RESIZE))
    assert result["resize_then_rebind"] == ["committed", [512, True]]
    assert result["rebind_then_resize"] == ["committed", [256, False]]
    message, unchanged, state = result["resize_only"]
    assert message.startswith("NotYetSupported: node="), message
    assert "a 256x256 8-bit colour bitmap on the channel BaseColor of a 512x512" in message
    assert unchanged is True and state == [256, False]
    refused, *statuses, routed = result["routed"]
    assert refused.startswith("NotYetSupported: node="), refused
    assert "bind another source first" in refused
    assert statuses == ["committed", "committed", "committed"]
    assert routed == [512, True]


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


def test_a_job_running_on_the_worker_still_makes_saving_busy(run: Run) -> None:
    """A job is not busy with itself, and only with itself (jobs.cpp): while a job is held
    running at a barrier (the runner's `uzp_job_test` hook), `save`, `save_as` and `close` from the
    command thread raise `BusyError` naming it and write nothing; released, that job still sees
    the export queued behind it."""
    result = ok(
        run(
            with_values("""
        import uzp_job_test
        create()
        project.save_as(WORK + "/plane.uzp")
        held = uzp_job_test.hold()
        job = next(j for j in jobs.list() if j.id == held)
        status = job.status
        refused = [raises(project.save), raises(project.save_as, WORK + "/other.uzp"),
                   raises(project.close)]
        queued = export.start(__CONFIG__)
        uzp_job_test.release()
        seen = job.wait()
        queued.wait()
        result = {"held": held, "status": status, "refused": refused, "queued": queued.id,
                  "seen": seen, "busy": jobs.busy(), "other": os.path.exists(WORK + "/other.uzp"),
                  "closed": raises(project.close)}
        """)
        )
    )
    held = result["held"]
    assert result["status"] == "running"
    assert result["refused"] == [
        f"BusyError: {call} is refused while job {held} is running"
        for call in ("save()", "save_as()", "close()")
    ]
    assert result["other"] is False
    assert result["seen"] == {"busy": result["queued"]}
    assert result["busy"] is None and result["closed"] is None


def test_a_job_that_failed_or_was_cancelled_leaves_the_busy_check_as_it_was(run: Run) -> None:
    """The job thread's own job (jobs.cpp `running_here`) is reset after a body that throws and
    after one that is cancelled: in the round after each, a job held at the barrier is the one
    `save` and `save_as` from the command thread are busy with, it sees the export queued behind
    it (not itself), and once both ended `save` and `save_as` succeed."""
    result = ok(
        run(
            with_values("""
        import uzp_job_test
        create()
        project.save_as(WORK + "/plane.uzp")

        def handle(job_id):
            return next(j for j in jobs.list() if j.id == job_id)

        def end(how):
            held = uzp_job_test.hold("throw" if how == "throw" else "checkpoint")
            job = handle(held)
            if how == "cancel":
                job.cancel()
            uzp_job_test.release()
            return [raises(job.wait), job.status]

        def probe(name):
            held = uzp_job_test.hold()
            refused = [raises(project.save), raises(project.save_as, WORK + "/" + name + ".uzp")]
            queued = export.start(__CONFIG__)
            uzp_job_test.release()
            seen = handle(held).wait()
            queued.wait()
            return {"held": held, "refused": refused, "queued": queued.id, "seen": seen,
                    "busy": jobs.busy(), "written": os.path.exists(WORK + "/" + name + ".uzp"),
                    "save": raises(project.save),
                    "save_as": raises(project.save_as, WORK + "/after-" + name + ".uzp")}

        result = {"thrown": end("throw"), "after_throw": probe("throw"),
                  "cancelled": end("cancel"), "after_cancel": probe("cancel")}
        """)
        )
    )
    thrown_error, thrown_status = result["thrown"]
    assert thrown_status == "failed" and thrown_error == "RuntimeError: the held job failed"
    cancelled_error, cancelled_status = result["cancelled"]
    assert cancelled_status == "cancelled" and cancelled_error.endswith(" was cancelled")
    for after in (result["after_throw"], result["after_cancel"]):
        held = after["held"]
        assert after["refused"] == [
            f"BusyError: {call} is refused while job {held} is running"
            for call in ("save()", "save_as()")
        ], after
        assert after["written"] is False
        assert after["seen"] == {"busy": after["queued"]}, after
        assert after["busy"] is None and after["save"] is None and after["save_as"] is None, after


# ── B19: the calls on one committed revision share its CPU evaluation (decision 246) ───────────

# The export helpers: the plane's BaseColor (RGB) and Height (L) as 16-bit PNGs, passthrough; and
# an export timed, with the SHA-256 of every file it wrote.
EXPORT_HELPERS = """
def config(folder, **parameters):
    def doc(name, source, letters):
        return {"fileName": "$textureSet_" + name, "channels": [
            {"destChannel": c, "srcChannel": c, "srcMapType": "documentMap", "srcMapName": source}
            for c in letters]}
    values = {"fileFormat": "png", "bitDepth": "16", "dithering": False,
              "paddingAlgorithm": "passthrough"}
    maps = [doc("BaseColor", "basecolor", "RGB"), doc("Height", "height", "L")]
    return {"exportShaderParams": False, "exportPath": WORK + "/" + folder,
            "defaultExportPreset": "p", "exportPresets": [{"name": "p", "maps": maps}],
            "exportList": [{"rootPath": "uzp_plane"}],
            "exportParameters": [{"parameters": dict(values, **parameters)}]}


def timed(folder, **parameters):
    start = time.perf_counter()
    out = export.export_project_textures(config(folder, **parameters))
    return [time.perf_counter() - start, {f["relative_path"]: f["sha256"] for f in out["files"]}]
"""

# Eight bitmap fills magnified under bitmap masks and Levels effects, over a uniform base: so much
# more evaluation than encoding that a call which evaluates the stack again stands out against one
# that only encodes, on one thread or on many.
REVISION_STACK = (
    EXPORT_HELPERS
    + """
stack = create(256)
checker = resource.import_project_resource(IMAGES + "/checker-16.png", resource.Usage.TEXTURE)
left = resource.import_project_resource(IMAGES + "/mask-left-half.png", resource.Usage.TEXTURE)
base = ls.insert_fill(top(stack))
base.active_channels = {CT.BaseColor, CT.Height}
base.set_source(CT.BaseColor, cm.Color(0.2, 0.3, 0.4))
base.set_source(CT.Height, cm.Color(0.25, 0.25, 0.25, "Raw"))
for _ in range(8):
    detail = ls.insert_fill(top(stack))
    detail.active_channels = {CT.BaseColor}
    detail.set_source(CT.BaseColor, checker.identifier())
    detail.add_mask(ls.MaskBackground.Black)
    mask = ls.insert_fill(ls.InsertPosition.inside_node(detail, ls.NodeStack.Mask))
    mask.set_source(None, left.identifier())
    ls.insert_levels_effect(ls.InsertPosition.inside_node(detail, ls.NodeStack.Content))
"""
)


def test_calls_on_one_revision_reuse_its_evaluation(run: Run) -> None:
    """B19 (decision 246): an export of a revision an earlier export evaluated encodes from the
    kept tiles: the same bytes in a fraction of the time. A refusal raised before evaluating
    writes nothing and keeps the evaluation; a texture-space capture of the revision reads it and
    writes the export's BaseColor bytes."""
    result = ok(
        run(
            REVISION_STACK
            + """
cold = timed("cold")
warm = [timed("warm1"), timed("warm2")]
refused = raises(export.export_project_textures, config("refused", bitDepth="8", dithering=True))
after = timed("after-refusal")
capture = uzpainter.render.capture(WORK + "/capture/base.png", "base_color")
result = {"cold": cold, "warm": warm, "after": after, "refused": refused,
          "refused_written": os.path.exists(WORK + "/refused/generations"),
          "capture": capture["hashes"]["png"]}
"""
        )
    )
    cold_seconds, cold_files = result["cold"]
    assert sorted(cold_files) == ["uzp_plane_BaseColor.png", "uzp_plane_Height.png"]
    assert all(files == cold_files for _, files in [*result["warm"], result["after"]])
    # The cold export evaluated the stack; the others only encoded it again.
    warm_seconds = [seconds for seconds, _ in result["warm"]] + [result["after"][0]]
    assert max(warm_seconds) * 3 < cold_seconds, (cold_seconds, warm_seconds)
    assert result["refused"].startswith("NotYetSupported"), result["refused"]
    assert result["refused_written"] is False
    assert result["capture"] == cold_files["uzp_plane_BaseColor.png"]


def test_a_commit_supersedes_the_kept_evaluation(run: Run) -> None:
    """B19 (decision 246): after a commit, an export evaluates the new revision. Its bytes are
    the bytes a fresh process writes for that revision, never the bytes of the revision kept
    before it."""
    edited = ok(
        run(
            REVISION_STACK
            + """
before = timed("before")
base.set_source(CT.BaseColor, cm.Color(0.6, 0.3, 0.1))
after = timed("after")
project.save_as(WORK + "/edited.uzp")
result = {"before": before[1], "after": after[1]}
"""
        )
    )
    fresh = ok(
        run(
            EXPORT_HELPERS
            + """
project.open(WORK + "/edited.uzp")
result = timed("fresh")[1]
"""
        )
    )
    before, after = edited["before"], edited["after"]
    assert after["uzp_plane_BaseColor.png"] != before["uzp_plane_BaseColor.png"]
    assert after["uzp_plane_Height.png"] == before["uzp_plane_Height.png"]
    assert fresh == after


# A virtual normal map's export allocates its read-out tile before it evaluates the Normal
# channel, where a bitmap minified at 30 degrees is refused (decisions 061, 084): a refusal
# raised after a tile was allocated.
REFUSED_AFTER_ALLOCATING = (
    EXPORT_HELPERS
    + """
stack = create(256)
checker = resource.import_project_resource(IMAGES + "/checker-16.png", resource.Usage.TEXTURE)
base = ls.insert_fill(top(stack))
base.active_channels = {CT.BaseColor, CT.Height}
base.set_source(CT.BaseColor, cm.Color(0.2, 0.3, 0.4))
base.set_source(CT.Height, cm.Color(0.25, 0.25, 0.25, "Raw"))
bump = ls.insert_fill(top(stack))
bump.active_channels = {CT.Normal}
bump.set_source(CT.Normal, checker.identifier())
bump.set_projection_mode(ls.ProjectionMode.UV)
bump.set_projection_parameters(
    ls.UVProjectionParams(
        filtering_mode=ls.FilteringMode.BilinearHQ,
        uv_wrapping_mode=ls.UVWrapMode.Repeat,
        uv_transformation=ls.UVTransformationParams(
            scale_mode=ls.ScaleMode.Factors, scale=[32.0, 32.0], rotation=30.0, offset=[0.0, 0.0]
        ),
    )
)


def normal(folder):
    c = config(folder)
    channels = [{"destChannel": d, "srcChannel": d, "srcMapType": "virtualMap",
                 "srcMapName": "Normal_OpenGL"} for d in "RGB"]
    c["exportPresets"][0]["maps"] = [{"fileName": "$textureSet_Normal", "channels": channels}]
    return [raises(export.export_project_textures, c),
            os.path.exists(WORK + "/" + folder + "/generations")]
"""
)


def test_a_call_that_fails_after_allocating_a_tile_drops_the_kept_evaluation(run: Run) -> None:
    """B19 (decision 246): a call on a kept revision that fails once it has allocated a tile drops
    the evaluation, so the tile it allocated and never filled serves no later call. The virtual
    normal export allocates its read-out tile, then refuses the Normal channel's minified bitmap:
    repeated on the same revision it refuses the same way and writes nothing (before the fix the
    repeat read the unfilled tile and published a normal map), and the BaseColor and Height
    exports keep their bytes. The refusal is CheckNormalTexture's (decision 249: bilinear
    minification on the Normal channel is not recorded), which runs where the rotated footprint's
    refusal ran before it, after the read-out tile is allocated."""
    result = ok(
        run(
            REFUSED_AFTER_ALLOCATING
            + """
first = timed("first")[1]
refusals = [normal("refused"), normal("again")]
after = timed("after")[1]
result = {"first": first, "refusals": refusals, "after": after}
"""
        )
    )
    [refused, refused_written], [again, again_written] = result["refusals"]
    assert refused is not None and "Normal channel, bilinear minification" in refused, refused
    assert again == refused
    assert refused_written is False and again_written is False
    assert result["after"] == result["first"]


def test_a_capture_while_an_export_job_holds_the_evaluation_evaluates_privately(run: Run) -> None:
    """B19 (decision 246): a capture made while an export job holds the revision's evaluation
    evaluates on a private one and writes the bytes it writes from the kept evaluation once the
    job ended; the job's files equal an export of the same revision made after it."""
    result = ok(
        run(
            REVISION_STACK.replace("create(256)", "create(1024)")
            + """
job = export.start(config("job"))
while job.status in ("queued", "running") and job.progress < 0.2:  # 0.2: the job holds it
    time.sleep(0.001)
before = [job.status, job.progress]
during = uzpainter.render.capture(WORK + "/during/mask.png", "mask:%d" % detail.uid(), stack=None)
held = job.status
out = job.wait()
after = uzpainter.render.capture(WORK + "/after/mask.png", "mask:%d" % detail.uid(), stack=None)
again = timed("again")[1]
result = {"before": before, "held": held, "during": during["hashes"], "after": after["hashes"],
          "job": {f["relative_path"]: f["sha256"] for f in out["files"]}, "again": again}
"""
        )
    )
    status, progress = result["before"]
    assert status == "running" and progress >= 0.2, result["before"]
    # The job still ran when the capture ended: the capture never had the kept evaluation.
    assert result["held"] == "running"
    assert result["during"] == result["after"]
    assert result["again"] == result["job"]
