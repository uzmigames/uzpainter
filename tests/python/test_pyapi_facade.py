"""The `substance_painter` compatibility facade (task phase1.20_pyapi-facade, items 3.2-3.8 and the
quirks of 3.1 on supported nodes).

Each test runs a script in `uzp-pyapi-tests.exe` (conftest.py, `facade` fixture), which installs
`python/` beside the embedded interpreter. CPU only: every lane runs these. The comparisons with
Painter's private goldens are `test_pyapi_facade_tier0.py` (owner's machine).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.python.conftest import REPO_ROOT, Run

INVENTORY = REPO_ROOT / "tools" / "capabilities" / "painter-api-inventory.json"


def ok(report: dict[str, Any]) -> Any:
    """The `result` of a script that ran to its end."""
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    return report["result"]


# ── 3.2 Provenance ──────────────────────────────────────────────────────────────────────────────

PROVENANCE = """
import enum, types
import substance_painter_plugins

symbols, private = [], []
ENUM_ATTRIBUTES = {"name", "value"}  # the `.name` every documented enum describes
EXCEPTION_ATTRIBUTES = {"args", "add_note", "with_traceback"}  # Python's own


def is_enum(cls):
    return issubclass(cls, enum.Enum) or hasattr(cls, "__members__")


def owner_of(cls, member):
    # The documented owner of a member: the first public class of the MRO that defines it.
    for base in cls.__mro__:
        if member in vars(base):
            return cls if base.__name__.startswith("_") else base
    return cls


def walk(module, qualified):
    for name in dir(module):
        if name.startswith("_"):
            if not (name.startswith("__") and name.endswith("__")):
                private.append(f"{qualified}.{name}")
            continue
        value = getattr(module, name)
        symbol = f"{qualified}.{name}"
        if isinstance(value, types.ModuleType):
            symbols.append(["module", symbol])
            if value.__name__ == symbol:
                walk(value, symbol)
            continue
        symbols.append(["symbol", symbol])
        if not isinstance(value, type):
            continue
        for member in dir(value):
            if member.startswith("_"):
                continue
            if is_enum(value) and member in ENUM_ATTRIBUTES:
                continue
            if issubclass(value, BaseException) and member in EXCEPTION_ATTRIBUTES:
                continue
            owner = owner_of(value, member)
            symbols.append(["symbol", f"{qualified}.{owner.__name__}.{member}"])


walk(sp, "substance_painter")
walk(substance_painter_plugins, "substance_painter_plugins")
result = {"symbols": symbols, "private": private, "version": sp.__version__,
          "private_attribute": raises(getattr, sp, "_private_helper"),
          "application": [sp.application.version(), list(sp.application.version_info())]}
"""


def test_every_facade_symbol_is_documented_and_no_private_symbol_exists(facade: Run) -> None:
    result = ok(facade(PROVENANCE))
    entries = json.loads(INVENTORY.read_text(encoding="utf-8"))["entries"]
    documented = {entry["symbol"] for entry in entries}
    undocumented = [
        symbol
        for kind, symbol in result["symbols"]
        if symbol not in documented
        # A module is documented by the objects documented under it (`substance_painter.levels`
        # has no page of its own).
        and not (kind == "module" and any(d.startswith(symbol + ".") for d in documented))
    ]
    assert undocumented == []
    assert len(result["symbols"]) > 500
    # `_version` is the one private module, required by 10 §4 (Versions row).
    assert result["private"] == ["substance_painter._version"]
    assert result["private_attribute"].startswith("AttributeError")
    assert result["version"] == "0.3.7"
    version, info = result["application"]
    assert version == ".".join(str(part) for part in info)


# ── 3.3 Desktop-only symbols ────────────────────────────────────────────────────────────────────

DESKTOP_ONLY = """
DESKTOP = ["show_main_window", "get_main_window", "get_layout", "get_layout_mode", "set_layout",
           "reset_layout", "add_dock_widget", "add_plugins_toolbar_widget", "add_menu",
           "add_toolbar", "add_action", "delete_ui_element"]
calls = {f"substance_painter.ui.{name}": getattr(ui, name) for name in DESKTOP}
stack = create()
image = resource.import_project_resource(IMAGES + "/checker-16.png", resource.Usage.TEXTURE)
calls["substance_painter.resource.Resource.show_in_ui"] = image.show_in_ui
calls["substance_painter.resource.show_resources_in_ui"] = (
    lambda: resource.show_resources_in_ui([image]))
calls["substance_painter.event.GraphicalUserInterfaceStarted"] = (
    sp.event.GraphicalUserInterfaceStarted)
revision = uzpainter.project.revision()
out = {}
for symbol, call in calls.items():
    try:
        call()
    except uzpainter.UnsupportedInUzPainter as error:
        out[symbol] = [error.symbol, error.reason, error.alternative]
    else:
        out[symbol] = "returned"
result = {"raised": out, "revision_unchanged": uzpainter.project.revision() == revision}
"""


def test_each_desktop_only_symbol_raises_naming_symbol_reason_and_alternative(facade: Run) -> None:
    result = ok(facade(DESKTOP_ONLY))
    assert result["revision_unchanged"] is True
    assert len(result["raised"]) == 15
    for symbol, raised in result["raised"].items():
        assert isinstance(raised, list), f"{symbol} {raised}"
        name, reason, alternative = raised
        assert name == symbol
        assert "changes no texture, render or script-visible state" in reason
        assert alternative


# ── 3.4 Inert script state ──────────────────────────────────────────────────────────────────────

INERT = """
CONFIG = {
    "exportShaderParams": False,
    "defaultExportPreset": "p",
    "exportPresets": [{"name": "p", "maps": [
        {"fileName": "$textureSet_height", "channels": [
            {"destChannel": "L", "srcChannel": "L", "srcMapType": "documentMap",
             "srcMapName": "height"}]}]}],
    "exportParameters": [{"parameters": {"fileFormat": "png", "bitDepth": "16",
                                         "dithering": False, "paddingAlgorithm": "infinite"}}],
}


def export(folder):
    config = dict(CONFIG, exportPath=WORK + "/" + folder,
                  exportList=[{"rootPath": t.name()} for t in ts.all_texture_sets()])
    out = sp.export.export_project_textures(config)
    files = sorted(f for fs in out.textures.values() for f in fs)
    return [open(f, "rb").read().hex() for f in files], out.status.name, out.message


stack = create()
first = ls.insert_fill(top(stack))
first.active_channels = {CT.Height}
first.set_source(CT.Height, cm.Color(0.3, 0.3, 0.3))
group = ls.insert_group(top(stack))
second = ls.insert_fill(ls.InsertPosition.inside_node(group, ls.NodeStack.Substack))
second.active_channels = {CT.Height}
second.set_source(CT.Height, cm.Color(0.6, 0.6, 0.6, "Raw"))
before, status, message = export("before")

out = {}
ls.set_selected_nodes([second])
out["selected"] = [n.uid() for n in ls.get_selected_nodes(stack)] == [second.uid()]
out["type_default"] = ls.get_selection_type(first).name
ls.set_selection_type(first, ls.SelectionType.Mask)
out["type"] = ls.get_selection_type(first).name
out["properties"] = raises(ls.set_selection_type, first, ls.SelectionType.Properties)
group.set_collapsed(True)
out["collapsed"] = ls.get_node_by_uid(group.uid()).is_collapsed()
ts.set_active_stack(stack)
out["active"] = ts.get_active_stack() == stack
out["mode_default"] = ui.get_current_mode().name
ui.switch_to_mode(ui.UIMode.Baking)
out["mode"] = ui.get_current_mode().name
out["menus"] = [m.name for m in ui.ApplicationMenu]
with ls.ScopedModification("scope"):
    out["scoped_selection"] = raises(ls.set_selected_nodes, [first])
    out["scoped_type"] = raises(ls.set_selection_type, first, ls.SelectionType.Content)
after, _, _ = export("after")
out["exports_identical"] = before == after and len(before) == 1
out["status"] = [status, message]
project.close()
result = out
"""


def test_each_inert_state_symbol_reads_back_what_was_set_and_exports_are_identical(
    facade: Run,
) -> None:
    result = ok(facade(INERT))
    assert result["selected"] is True
    assert result["type_default"] == "Content"
    assert result["type"] == "Mask"
    assert result["properties"].startswith("ValueError")
    assert result["collapsed"] is True
    assert result["active"] is True
    assert result["mode_default"] == "Edition"
    assert result["mode"] == "Baking"
    assert result["menus"] == ["File", "Edit", "Mode", "Window", "Viewport", "Help"]
    assert result["scoped_selection"].startswith("RuntimeError")
    assert result["scoped_type"].startswith("RuntimeError")
    assert result["exports_identical"] is True
    assert result["status"] == ["Success", "Export successfully finished"]


# ── 3.5 js.evaluate ─────────────────────────────────────────────────────────────────────────────

JS = """
stack = create()
out = {}
def revision():
    return uzpainter.project.revision() if project.is_open() else None

def run(code):
    before = revision()
    try:
        value = js.evaluate(code)
    except BaseException as error:
        value = {"raised": type(error).__name__, "message": str(error)}
    return {"value": value, "revision_unchanged": revision() == before}

for code in [
    "alg.version.painter", "alg.project.isOpen()", "alg.project.name();",
    "alg.mapexport.channelIdentifiers()", "alg.mapexport.convertedMapIdentifiers()",
    "alg.mapexport.meshMapIdentifiers()",
    "alg.shaders.instances()", 'alg.shaders.parameters(0)',
    'alg.shaders.setParameters(0, {"a": 1})',
    'alg.shaders.updateShaderInstance(0, "url")',
    'alg.mapexport.save(["uzp_plane", "basecolor"], "C:/x.png")',
    'alg.mapexport.saveChannelMap("uzp_plane", "basecolor", "C:/x.png", {"dithering": false})',
    'alg.mapexport.saveMeshMap("uzp_plane", "normal_base", "C:/x.png")',
    'alg.mapexport.saveConvertedMap("uzp_plane", "normal", "C:/x.png")',
    "alg.project.close(); 1+1", "alg.project.close()", "1+1", "alg.shaders.parameters(foo)",
    "alg.mapexport.save(['a'], 'b')", "alg.project.isOpen(1)", "alg.version.painter()",
    "alg.project.isOpen",
]:
    out[code] = run(code)
out["application"] = sp.application.version()
project.save_as(WORK + "/js.spp")
out["saveAndClose"] = run("alg.project.saveAndClose()")
out["closed"] = not project.is_open()
result = out
"""


def test_js_evaluate_maps_the_whitelist_and_rejects_everything_else_before_mutation(
    facade: Run,
) -> None:
    result = ok(facade(JS))
    assert result["alg.version.painter"]["value"] == result["application"]
    assert result["alg.project.isOpen()"]["value"] is True
    assert result["alg.project.name();"]["value"] == "Untitled"
    assert "basecolor" in result["alg.mapexport.channelIdentifiers()"]["value"]
    assert "normal_directx" in result["alg.mapexport.convertedMapIdentifiers()"]["value"]
    assert "normal_base" in result["alg.mapexport.meshMapIdentifiers()"]["value"]
    for code in [
        "alg.shaders.instances()",
        "alg.shaders.parameters(0)",
        'alg.shaders.setParameters(0, {"a": 1})',
        'alg.shaders.updateShaderInstance(0, "url")',
        'alg.mapexport.save(["uzp_plane", "basecolor"], "C:/x.png")',
        'alg.mapexport.saveChannelMap("uzp_plane", "basecolor", "C:/x.png", {"dithering": false})',
        'alg.mapexport.saveMeshMap("uzp_plane", "normal_base", "C:/x.png")',
        'alg.mapexport.saveConvertedMap("uzp_plane", "normal", "C:/x.png")',
    ]:
        assert result[code]["value"]["raised"] == "NotYetSupported", code
    for code in [
        "alg.project.close(); 1+1",
        "alg.project.close()",
        "1+1",
        "alg.shaders.parameters(foo)",
        "alg.mapexport.save(['a'], 'b')",
        "alg.version.painter()",
        "alg.project.isOpen",
    ]:
        assert result[code]["value"]["raised"] == "UnsupportedInUzPainter", code
    assert result["alg.project.isOpen(1)"]["value"]["raised"] == "RuntimeError"
    assert all(outcome["revision_unchanged"] for code, outcome in result.items() if code in (
        "alg.project.close(); 1+1", "alg.shaders.parameters(foo)", "alg.mapexport.save(['a'], 'b')"
    ))  # fmt: skip
    assert result["saveAndClose"]["value"] is None
    assert result["closed"] is True


# ── 3.6 Colour ──────────────────────────────────────────────────────────────────────────────────

COLOUR = """
stack = create()
fill = ls.insert_fill(top(stack))
fill.active_channels = {CT.BaseColor, CT.SpecularRoughness}
out = {}
def working(channel):
    return list(fill.get_source(channel).get_color().working)

fill.set_source(CT.BaseColor, cm.Color(0.2, 0.5, 0.8))
out["implicit_base"] = working(CT.BaseColor)
fill.set_source(CT.BaseColor, cm.Color(0.2, 0.5, 0.8, cm.GenericColorSpace.sRGB))
out["srgb_base"] = working(CT.BaseColor)
fill.set_source(CT.BaseColor, cm.Color(0.2, 0.5, 0.8, "Raw"))
out["raw_base"] = working(CT.BaseColor)
fill.set_source(CT.SpecularRoughness, cm.Color(0.2, 0.5, 0.8))
out["implicit_rough"] = working(CT.SpecularRoughness)
color = cm.Color(1.0, 0.54902, 0.0, cm.GenericColorSpace.sRGB)
out["convert"] = [list(color.working), list(color.sRGB), list(color.value),
                  list(color.convert(cm.GenericColorSpace.Working))]
out["no_space"] = [raises(lambda: cm.Color(1, 0, 0).working),
                   list(cm.Color(1, 0, 0).value)]
out["legacy_space"] = raises(cm.Color, 1, 0, 0, cm.LegacyColorSpace.Linear)
out["read_space"] = fill.get_source(CT.BaseColor).get_color().color_space.name
declared = uzpainter.colormanagement.get_color_management()
project.save_as(WORK + "/colour.spp")
project.close()
project.open(WORK + "/colour.spp")
out["profile_round_trip"] = uzpainter.colormanagement.get_color_management() == declared
out["declared"] = declared["mode"]
fill = ls.get_node_by_uid(fill.uid())
out["implicit_base_reopened"] = list(fill.get_source(CT.BaseColor).get_color().working)

# An unpinned configuration (an OCIO project) fails before anything is evaluated.
original = uzpainter.colormanagement.get_color_management
uzpainter.colormanagement.get_color_management = lambda: dict(declared, mode="ocio",
                                                                 working_space="ACEScg")
revision = uzpainter.project.revision()
out["ocio_export"] = raises(sp.export.export_project_textures, {"exportPath": WORK + "/ocio"})
out["ocio_nothing_written"] = not os.path.exists(WORK + "/ocio")
out["ocio_revision"] = uzpainter.project.revision() == revision

# OCIO with Painter's substance config (decision 202): recorded components read Painter's measured
# working value; an unrecorded component, an sRGB colour on a data channel and the OCIO encode
# raise before any change.
PAINTER_OCIO = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"
uzpainter.colormanagement.get_color_management = lambda: dict(declared, mode="ocio",
                                                                 config_hash=PAINTER_OCIO)
fill.set_source(CT.BaseColor, cm.Color(75 / 255, 70 / 255, 65 / 255, cm.GenericColorSpace.sRGB))
out["ocio_base"] = working(CT.BaseColor)
fill.set_source(CT.BaseColor, cm.Color(0.2, 0.5, 0.8))
out["ocio_implicit_base"] = working(CT.BaseColor)
revision = uzpainter.project.revision()
out["ocio_unrecorded"] = raises(fill.set_source, CT.BaseColor,
                                cm.Color(0.2, 0.51, 0.8, cm.GenericColorSpace.sRGB))
out["ocio_data_srgb"] = raises(fill.set_source, CT.SpecularRoughness,
                               cm.Color(0.2, 0.2, 0.2, cm.GenericColorSpace.sRGB))
out["ocio_space"] = raises(fill.set_source, CT.BaseColor, cm.Color(0.2, 0.2, 0.2, "Rec709"))
out["ocio_unchanged"] = uzpainter.project.revision() == revision and working(CT.BaseColor) == (
    out["ocio_implicit_base"])
out["ocio_raw_rough"] = (fill.set_source(CT.SpecularRoughness, cm.Color(0.37, 0.37, 0.37)),
                         working(CT.SpecularRoughness))[1]
out["ocio_encode"] = raises(lambda: cm.Color(0.2, 0.2, 0.2, cm.GenericColorSpace.Working).sRGB)
uzpainter.colormanagement.get_color_management = original
result = out
"""


def test_colour_rules_implicit_space_conversions_and_the_pinned_profile(facade: Run) -> None:
    result = ok(facade(COLOUR))
    srgb = [0.03310476243495941, 0.21404114365577698, 0.6038274168968201]
    assert result["implicit_base"] == srgb  # sRGB on a colour-managed channel
    assert result["srgb_base"] == srgb
    assert result["raw_base"] == [0.20000000298023224, 0.5, 0.800000011920929]
    assert result["implicit_rough"] == [0.20000000298023224, 0.5, 0.800000011920929]  # Raw
    working, srgb_values, value, converted = result["convert"]
    assert working == converted
    assert [round(c, 5) for c in working] == [1.0, 0.26225, 0.0]
    assert [round(c, 5) for c in srgb_values] == [round(c, 5) for c in value]
    assert result["no_space"][0].startswith("RuntimeError")
    assert result["no_space"][1] == [1.0, 0.0, 0.0]
    assert result["legacy_space"].startswith("TypeError")
    assert result["read_space"] == "Working"
    assert result["profile_round_trip"] is True
    assert result["declared"] in ("", "legacy")
    assert result["implicit_base_reopened"] == [0.20000000298023224, 0.5, 0.800000011920929]
    assert result["ocio_export"].startswith("NotYetSupported")
    assert "not a pinned colour profile" in result["ocio_export"]
    assert result["ocio_nothing_written"] is True
    assert result["ocio_revision"] is True
    # Painter's OCIO readbacks (`export-ocio-encode` s0 and s6, `phase1-srgb-uniform-decode-ocio`)
    assert result["ocio_base"] == [0.07036010175943375, 0.06124616786837578, 0.0528603233397007]
    assert result["ocio_implicit_base"] == [
        0.033104557543992996,
        0.21404145658016205,
        0.6038273572921753,
    ]
    for key in ("ocio_unrecorded", "ocio_data_srgb", "ocio_space", "ocio_encode"):
        assert result[key].startswith("NotYetSupported: under OCIO"), result[key]
    assert "0.51" in result["ocio_unrecorded"]
    assert result["ocio_unchanged"] is True
    assert result["ocio_raw_rough"] == [0.3700000047683716] * 3


# ── Colour management at create (decision 207) ──────────────────────────────────────────────────

# Painter's substance config where Painter 12.1 installs it (the Wand's `painter_create.py` names
# this path); it is hashed, never read otherwise, and never copied into the repository.
PAINTER_OCIO_CONFIG = Path(
    r"C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\ocio\substance\config.ocio"
)
PAINTER_OCIO_SHA256 = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"

CREATE_COLOUR = """
def attempt(**variables):
    for name in ("OCIO", "PAINTER_ACE_CONFIG"):
        os.environ.pop(name, None)
    os.environ.update(variables)
    raised = raises(create)
    declared = None if raised else uzpainter.colormanagement.get_color_management()
    if project.is_open():
        project.close()
    return [raised, declared]

other = WORK + "/other.ocio"
with open(other, "w", encoding="utf-8") as file:
    file.write("ocio_profile_version: 2\\n")
ace = WORK + "/ace.json"
with open(ace, "w", encoding="utf-8") as file:
    file.write("{}")
out = {
    "legacy": attempt(),
    "empty": attempt(OCIO=""),
    "other": attempt(OCIO=other),
    "missing": attempt(OCIO=WORK + "/missing.ocio"),
    "ace": attempt(PAINTER_ACE_CONFIG=ace),
    "ace_missing": attempt(PAINTER_ACE_CONFIG=WORK + "/missing.json"),
    "ocio_and_ace": attempt(OCIO=__CONFIG__, PAINTER_ACE_CONFIG=ace),
}
out["open_after_refusals"] = uzpainter.project.is_open()

# As the Wand's painter_create.py: OCIO set in-process right before create.
for name in ("OCIO", "PAINTER_ACE_CONFIG"):
    os.environ.pop(name, None)
os.environ["OCIO"] = __CONFIG__
stack = create()
fill = ls.insert_fill(top(stack))
fill.active_channels = {CT.BaseColor}
fill.set_source(CT.BaseColor, cm.Color(75 / 255, 70 / 255, 65 / 255, cm.GenericColorSpace.sRGB))
out["ocio_base"] = list(fill.get_source(CT.BaseColor).get_color().working)
# A colour bitmap on BaseColor binds in its default space, sRGB, in one call (the Wand's T_base).
image = resource.import_project_resource(IMAGES + "/checker-16.png", resource.Usage.TEXTURE)
bitmap = ls.insert_fill(top(stack))
bitmap.active_channels = {CT.BaseColor}
out["ocio_bitmap"] = bitmap.set_source(CT.BaseColor, image.identifier()).get_color_space().name
project.save_as(WORK + "/ocio.spp")
project.close()
del os.environ["OCIO"]
project.open(WORK + "/ocio.spp")
out["reopened"] = uzpainter.colormanagement.get_color_management()
project.close()
result = out
"""


def test_create_takes_colour_management_from_the_environment_at_the_call(facade: Run) -> None:
    """Painter's documented `create` rule (decision 207): `OCIO` naming Painter's substance config
    gives an OCIO project with its hash (over `PAINTER_ACE_CONFIG` too), read at the call as the
    Wand sets it; any other OCIO configuration or ACE raises `NotYetSupported`, a file that cannot
    be read `ProjectError`, before anything is created; neither variable gives Legacy. On the OCIO
    project a colour bitmap binds on BaseColor in its default space, sRGB."""
    if not PAINTER_OCIO_CONFIG.is_file():
        pytest.skip(f"Painter's substance config is not installed at {PAINTER_OCIO_CONFIG}")
    config = PAINTER_OCIO_CONFIG.as_posix()
    result = ok(facade(CREATE_COLOUR.replace("__CONFIG__", repr(config))))
    ocio = {"config_hash": PAINTER_OCIO_SHA256, "io_rules": [], "mode": "ocio", "working_space": ""}
    legacy = {"config_hash": "", "io_rules": [], "mode": "", "working_space": ""}
    assert result["legacy"] == [None, legacy]
    assert result["empty"] == [None, legacy]
    assert result["other"][0].startswith("NotYetSupported: create under the OCIO configuration")
    assert "pinned colour profile" in result["other"][0]
    assert result["missing"][0].startswith("ProjectError: the OCIO configuration")
    assert result["ace"][0].startswith("NotYetSupported: create under PAINTER_ACE_CONFIG")
    assert result["ace_missing"][0].startswith("ProjectError: the PAINTER_ACE_CONFIG configuration")
    for key in ("other", "missing", "ace", "ace_missing"):
        assert result[key][1] is None, key
    assert result["ocio_and_ace"] == [None, ocio]
    assert result["open_after_refusals"] is False
    # Painter's OCIO readback of (75, 70, 65)/255 in sRGB (`export-ocio-encode` s6, decision 202)
    assert result["ocio_base"] == [0.07036010175943375, 0.06124616786837578, 0.0528603233397007]
    assert result["ocio_bitmap"] == "sRGB"
    assert result["reopened"] == ocio


# ── Bitmap colour spaces Painter offers and refuses (decision 174) ───────────────────────────────

BITMAP_SPACES = """
stack = create()
FORMATS = {"User1": "RGB8", "User2": "L8", "User3": "RGB16", "User4": "L16", "User5": "RGB16F",
           "User7": "RGB32F"}
for name, fmt in FORMATS.items():
    stack.add_channel(getattr(CT, name), getattr(ts.ChannelFormat, fmt))
colour = resource.import_project_resource(IMAGES + "/checker-16.png", resource.Usage.TEXTURE)
grey = resource.import_project_resource(IMAGES + "/mask-left-half.png", resource.Usage.TEXTURE)
fill = ls.insert_fill(top(stack))
out = {"user": {}, "legacy": {}}

def spaces(source):
    return [[type(s).__name__, s.name] for s in source.list_available_color_spaces()]

def attempt(source, space):
    revision = uzpainter.project.revision()
    raised = raises(source.set_color_space, space)
    return [raised, type(source.get_color_space()).__name__, source.get_color_space().name,
            uzpainter.project.revision() == revision]

for name, fmt in FORMATS.items():
    image = grey if fmt.startswith("L") else colour
    source = fill.set_source(getattr(CT, name), image.identifier())
    out["user"][name] = [spaces(source), attempt(source, cm.GenericColorSpace.sRGB)]
fill.add_mask(ls.MaskBackground.Black)
mask = ls.insert_fill(ls.InsertPosition.inside_node(fill, ls.NodeStack.Mask))
mono = mask.set_source(None, grey.identifier())
out["mask"] = [spaces(mono), attempt(mono, cm.GenericColorSpace.sRGB)]
base = fill.set_source(CT.BaseColor, colour.identifier())
for space in (cm.GenericColorSpace.Working, cm.LegacyColorSpace.Linear, cm.LegacyColorSpace.sRGB,
              cm.GenericColorSpace.sRGB):
    base.set_color_space(space)
    read = base.get_color_space()
    out["legacy"][type(space).__name__ + "." + space.name] = [type(read).__name__, read.name]
result = out
"""


def test_bitmap_spaces_offered_and_refused_as_painter(facade: Run) -> None:
    """phase1.15_compositor-colour-fits item 2.2 (decision 174; `srgb-bitmap-variants-v2`): a
    bitmap on a user channel of every format but sRGB8 and a mask's mono source are offered Raw,
    Data and DataSigned, keep Data, and refuse sRGB with Painter's ValueError before any mutation;
    a BaseColor bitmap reads back the Working and Legacy spaces it is set to."""
    result = ok(facade(BITMAP_SPACES))
    data_spaces = [
        ["GenericColorSpace", "Raw"],
        ["DataColorSpace", "Data"],
        ["DataColorSpace", "DataSigned"],
    ]
    refusal = [
        "ValueError: Invalid colorspace 'standard sRGB'",
        "DataColorSpace",
        "Data",
        True,
    ]
    assert result["user"] == {
        name: [data_spaces, refusal]
        for name in ("User1", "User2", "User3", "User4", "User5", "User7")
    }
    assert result["mask"] == [data_spaces, refusal]
    assert result["legacy"] == {
        "GenericColorSpace.Working": ["GenericColorSpace", "Working"],
        "LegacyColorSpace.Linear": ["LegacyColorSpace", "Linear"],
        "LegacyColorSpace.sRGB": ["LegacyColorSpace", "sRGB"],
        "GenericColorSpace.sRGB": ["GenericColorSpace", "sRGB"],
    }


# ── 3.7 ScopedModification ──────────────────────────────────────────────────────────────────────

SCOPED = """
stack = create()
revision = uzpainter.project.revision()
try:
    with ls.ScopedModification("insert then fail"):
        fill = ls.insert_fill(top(stack))
        fill.set_name("kept")
        raise KeyError("inside the block")
except KeyError:
    pass
roots = [n.get_name() for n in ls.get_root_layer_nodes(stack)]
result = {"roots": roots, "revisions": uzpainter.project.revision() - revision}
"""


def test_scoped_modification_keeps_the_calls_committed_before_an_exception(facade: Run) -> None:
    result = ok(facade(SCOPED))
    assert result["roots"] == ["kept"]
    assert result["revisions"] == 2  # insert (one transaction with its defaults), set_name


# ── 3.8 substance_painter_plugins ───────────────────────────────────────────────────────────────

PLUGINS = """
import importlib
import substance_painter_plugins as plugins
root = WORK + "/plugins-root"
for sub in ("startup", "plugins", "modules"):
    os.makedirs(root + "/" + sub, exist_ok=True)
with open(root + "/modules/uzp_log.py", "w") as f:
    f.write("EVENTS = []\\n")
with open(root + "/startup/uzp_startup.py", "w") as f:
    f.write("import uzp_log\\n"
            "def start_plugin():\\n    uzp_log.EVENTS.append('start')\\n"
            "def close_plugin():\\n    uzp_log.EVENTS.append('close')\\n")
with open(root + "/plugins/uzp_optional.py", "w") as f:
    f.write("def start_plugin():\\n    pass\\n")
plugins.path = [root]
plugins.load_startup_modules()
import uzp_log, uzp_startup
out = {
    "startup": plugins.startup_module_names(),
    "plugins": plugins.plugin_module_names(),
    "started": plugins.is_plugin_started(uzp_startup),
    "listed": sorted(plugins.plugins),
}
plugins.close_plugin(uzp_startup)
out["after_close"] = plugins.is_plugin_started(uzp_startup)
out["events"] = list(uzp_log.EVENTS)
optional = importlib.import_module("uzp_optional")
plugins.start_plugin(optional)
plugins.close_all_plugins()
out["all_closed"] = plugins.plugins == {}
result = out
"""


def test_load_startup_modules_starts_a_non_ui_module_and_close_plugin_unloads_it(
    facade: Run,
) -> None:
    result = ok(facade(PLUGINS))
    assert result["startup"] == ["uzp_startup"]
    assert result["plugins"] == ["uzp_optional"]
    assert result["started"] is True
    assert result["listed"] == ["uzp_startup"]
    assert result["after_close"] is False
    assert result["events"] == ["start", "close"]
    assert result["all_closed"] is True


# ── Quirks on supported nodes (item 3.1's rules, every lane) ────────────────────────────────────

QUIRKS = """
stack = create()
fill = ls.insert_fill(top(stack))
out = {"name": fill.get_name(), "defaults": [fill.get_blending_mode(CT.Height).name]}
fill.active_channels = {CT.BaseColor, CT.Height}
fill.set_source(CT.BaseColor, cm.Color(0.8, 0.3, 0.2, "Working"))
fill.set_source(CT.Height, cm.Color(0.4, 0.4, 0.4, "Raw"))
fill.active_channels = {CT.BaseColor, CT.Height}  # Painter resets the sources
out["reset"] = [list(fill.get_source(c).get_color().working) for c in (CT.BaseColor, CT.Height)]
native = uzpainter.layerstack.get_node_by_uid(fill.uid())
native.set_source(CT.BaseColor, uzpainter.colormanagement.Color(0.1, 0.2, 0.3, "Working"))
native.active_channels = {CT.BaseColor, CT.Height}  # LAY-01: the native API keeps them
out["native_kept"] = list(native.get_source(CT.BaseColor).get_color().value_raw)
fill.set_source(CT.SpecularRoughness, cm.Color(0.5, 0.5, 0.5, "Raw"))
out["implicit"] = sorted(c.name for c in fill.active_channels)
out["kept"] = list(fill.get_source(CT.BaseColor).get_color().working)
out["none_content"] = raises(fill.set_source, None, cm.Color(1, 0, 0))
out["get_none_content"] = raises(fill.get_source)
out["blend_none"] = raises(fill.get_blending_mode)
fill.add_mask(ls.MaskBackground.Black)
out["mask_twice"] = raises(fill.add_mask, ls.MaskBackground.White)
mask = ls.insert_fill(ls.InsertPosition.inside_node(fill, ls.NodeStack.Mask))
out["mask_type"] = type(mask).__name__
out["mask_source_default"] = mask.get_source(None)
out["mask_channel"] = raises(mask.set_source, CT.BaseColor, cm.Color(1, 1, 1))
out["mask_blend"] = raises(mask.set_blending_mode, ls.BlendingMode.Normal, CT.BaseColor)
out["mask_active"] = [raises(lambda: mask.active_channels),
                      raises(setattr, mask, "active_channels", {CT.BaseColor})]
out["mask_mode"] = mask.source_mode
levels = ls.insert_levels_effect(ls.InsertPosition.inside_node(fill, ls.NodeStack.Content))
out["levels"] = [levels.get_name(), levels.affected_channel.name,
                 type(levels.get_parameters()).__name__,
                 raises(levels.get_blending_mode, CT.BaseColor)]
group = ls.insert_group(top(stack))
out["errors"] = [
    raises(ls.insert_fill, ls.InsertPosition.inside_node(fill, ls.NodeStack.Substack)),
    raises(ls.insert_group, ls.InsertPosition.inside_node(fill, ls.NodeStack.Content)),
    raises(ls.insert_group, ls.InsertPosition.inside_node(fill, ls.NodeStack.Mask)),
    raises(ls.insert_levels_effect, top(stack)),
    raises(ls.insert_levels_effect, ls.InsertPosition.above_node(fill)),
    raises(ls.insert_group, ls.InsertPosition.above_node(levels)),
    raises(ls.insert_compare_mask_effect,
           ls.InsertPosition.inside_node(fill, ls.NodeStack.Content)),
    raises(ls.insert_color_selection_effect, top(stack)),
    raises(ls.insert_fill, ls.InsertPosition.inside_node(levels, ls.NodeStack.Content)),
    raises(ls.insert_fill, ls.InsertPosition.inside_node(group, ls.NodeStack.Mask)),
]
out["group_blend"] = group.get_blending_mode(CT.Height).name
result = out
"""


def test_painter_quirks_on_supported_nodes(facade: Run) -> None:
    result = ok(facade(QUIRKS))
    assert result["name"] == "Fill"
    assert result["defaults"] == ["LinearDodge"]
    assert result["reset"] == [[0.800000011920929] * 3, [0.0] * 3]
    assert result["native_kept"] == [0.10000000149011612, 0.20000000298023224, 0.30000001192092896]
    assert result["implicit"] == ["BaseColor", "Height", "SpecularRoughness"]
    assert result["kept"] == [0.10000000149011612, 0.20000000298023224, 0.30000001192092896]
    assert result["none_content"] == "EditionContextException: Only valid in mono channel context"
    assert result["get_none_content"] == result["none_content"]
    assert result["blend_none"] == (
        "ValueError: This node is not part of a mask stack, a Channel Type must be specified"
    )
    assert result["mask_twice"] == "ValueError: This node already has a mask"
    assert result["mask_type"] == "FillEffectNode"
    assert result["mask_source_default"] is None
    assert (
        result["mask_channel"] == "EditionContextException: Channel 0 isn't valid in this context"
    )
    assert result["mask_blend"] == (
        "ValueError: This node is part of a mask stack and does not support Channel Types for "
        "blending"
    )
    assert result["mask_active"] == [
        "EditionContextException: Only valid in multi channel context",
        "EditionContextException: Channel 0 isn't valid in this context",
    ]
    assert result["mask_mode"] is None
    assert result["levels"] == [
        "Levels - Base color",
        "BaseColor",
        "LevelsParamsRGB",
        "ValueError: This node does not support channel blending information",
    ]
    assert result["errors"] == [
        "ValueError: Invalid insert position: substack is only valid on a layer group node",
        "ValueError: Cannot insert a layer in content stack",
        "ValueError: Cannot insert a layer in mask stack",
        "ValueError: Cannot insert an effect at the top of the layerstack",
        "ValueError: Cannot insert an effect above a layer",
        "ValueError: Cannot insert a layer above an effect",
        "ValueError: Compare mask effect can only be inserted in mask stack",
        "ValueError: Cannot insert an effect at the top of the layerstack",
        "ValueError: Invalid insert position: an effect has no content stack",
        "ValueError: The layer does not have a mask",
    ]
    assert result["group_blend"] == "LinearDodge"


def test_python_sources_are_installed_beside_the_interpreter(pyapi_runner: Path) -> None:
    installed = pyapi_runner.parent / "python"
    for package in ("substance_painter", "substance_painter_plugins", "uzpainter_facade"):
        assert (installed / package / "__init__.py").is_file()
    assert not list(installed.rglob("*.md"))
