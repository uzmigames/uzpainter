"""Recorder code executed inside Adobe Substance 3D Painter 12.1.0.

The host (`tools.parity.recorder.session`) sends this file's source through Painter's documented
remote control (`--enable-remote-scripting`, POST `/run.json`), executes it into a private
namespace and then sets `session_id` there. Every `substance_painter` symbol used here is listed in
`documented_symbols.json` and appears in Painter's public Python API documentation (approved
source A-PYDOC); `tests/parity/recorder/test_provenance.py` enforces that. No private attribute,
no shipped Painter source and no community MCP bridge is used.

Each operation is non-blocking: Painter loads projects asynchronously, so readiness is polled by
the host between requests (a loop here would block Painter's own event processing). `dispatch`
returns a JSON string so that floats round-trip exactly (`repr` precision).
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

import substance_painter.application
import substance_painter.colormanagement
import substance_painter.display
import substance_painter.export
import substance_painter.js
import substance_painter.layerstack
import substance_painter.project
import substance_painter.resource
import substance_painter.source
import substance_painter.textureset
import substance_painter.ui

# Replaced by the host right after this source is executed (one id per Painter process).
session_id = ""

# Fill layers created by the instruction sequence, by step number (this namespace only).
NODES: dict[int, Any] = {}

# State-changing calls of the instruction-sequence vocabulary (UzmiGames-authored steps).
CREATE = "substance_painter.project.create"
INSERT_FILL = "substance_painter.layerstack.insert_fill"
SET_SOURCE = "substance_painter.layerstack.FillLayerNode.set_source"
SET_ACTIVE_CHANNELS = "substance_painter.layerstack.FillLayerNode.active_channels"
SET_BLENDING_MODE = "substance_painter.layerstack.Node.set_blending_mode"
SET_OPACITY = "substance_painter.layerstack.Node.set_opacity"
SET_RESOLUTIONS = "substance_painter.textureset.set_resolutions"
CAMERA = "substance_painter.display.Camera."
SET_ENVIRONMENT = "substance_painter.display.set_environment_resource"
SET_TONE_MAPPING = "substance_painter.display.set_tone_mapping"

# Readback calls (getters of the setters above).
GET_SOURCE = "substance_painter.layerstack.FillLayerNode.get_source"
GET_ACTIVE_CHANNELS = "substance_painter.layerstack.FillLayerNode.active_channels"
GET_BLENDING_MODE = "substance_painter.layerstack.Node.get_blending_mode"
GET_OPACITY = "substance_painter.layerstack.Node.get_opacity"
GET_RESOLUTION = "substance_painter.textureset.TextureSet.get_resolution"

CAMERA_PROPERTIES = (
    "projection_type",
    "position",
    "rotation",
    "field_of_view",
    "focal_length",
    "focus_distance",
    "aperture",
    "orthographic_height",
)

# Documented enum members by name. Painter's enums are not subscriptable, and attribute lookup by
# a computed name would hide which symbol is used, so each accepted member is spelled out; the
# lambdas defer the lookup to the call that needs it.
# project.NormalMapFormat members.
NORMAL_MAP_FORMATS = {
    "OpenGL": lambda: substance_painter.project.NormalMapFormat.OpenGL,
    "DirectX": lambda: substance_painter.project.NormalMapFormat.DirectX,
}

# project.TangentSpace members.
TANGENT_SPACES = {
    "PerVertex": lambda: substance_painter.project.TangentSpace.PerVertex,
    "PerFragment": lambda: substance_painter.project.TangentSpace.PerFragment,
}

# project.ProjectWorkflow members.
PROJECT_WORKFLOWS = {
    "Default": lambda: substance_painter.project.ProjectWorkflow.Default,
    "TextureSetPerUVTile": lambda: substance_painter.project.ProjectWorkflow.TextureSetPerUVTile,
    "UVTile": lambda: substance_painter.project.ProjectWorkflow.UVTile,
}

# textureset.ChannelType members the vocabulary accepts (OpenPBR, aliases, user channels).
CHANNEL_TYPES = {
    "BaseColor": lambda: substance_painter.textureset.ChannelType.BaseColor,
    "BaseWeight": lambda: substance_painter.textureset.ChannelType.BaseWeight,
    "BaseMetalness": lambda: substance_painter.textureset.ChannelType.BaseMetalness,
    "SpecularWeight": lambda: substance_painter.textureset.ChannelType.SpecularWeight,
    "SpecularColor": lambda: substance_painter.textureset.ChannelType.SpecularColor,
    "SpecularRoughness": lambda: substance_painter.textureset.ChannelType.SpecularRoughness,
    "EmissionColor": lambda: substance_painter.textureset.ChannelType.EmissionColor,
    "Opacity": lambda: substance_painter.textureset.ChannelType.Opacity,
    "Height": lambda: substance_painter.textureset.ChannelType.Height,
    "Displacement": lambda: substance_painter.textureset.ChannelType.Displacement,
    "Normal": lambda: substance_painter.textureset.ChannelType.Normal,
    "AO": lambda: substance_painter.textureset.ChannelType.AO,
    "Metallic": lambda: substance_painter.textureset.ChannelType.Metallic,
    "Roughness": lambda: substance_painter.textureset.ChannelType.Roughness,
    "Emissive": lambda: substance_painter.textureset.ChannelType.Emissive,
    "User0": lambda: substance_painter.textureset.ChannelType.User0,
    "User1": lambda: substance_painter.textureset.ChannelType.User1,
    "User2": lambda: substance_painter.textureset.ChannelType.User2,
    "User3": lambda: substance_painter.textureset.ChannelType.User3,
}

# layerstack.BlendingMode members.
BLENDING_MODES = {
    "Normal": lambda: substance_painter.layerstack.BlendingMode.Normal,
    "PassThrough": lambda: substance_painter.layerstack.BlendingMode.PassThrough,
    "Disable": lambda: substance_painter.layerstack.BlendingMode.Disable,
    "Replace": lambda: substance_painter.layerstack.BlendingMode.Replace,
    "Multiply": lambda: substance_painter.layerstack.BlendingMode.Multiply,
    "Divide": lambda: substance_painter.layerstack.BlendingMode.Divide,
    "InverseDivide": lambda: substance_painter.layerstack.BlendingMode.InverseDivide,
    "Darken": lambda: substance_painter.layerstack.BlendingMode.Darken,
    "Lighten": lambda: substance_painter.layerstack.BlendingMode.Lighten,
    "LinearDodge": lambda: substance_painter.layerstack.BlendingMode.LinearDodge,
    "Subtract": lambda: substance_painter.layerstack.BlendingMode.Subtract,
    "InverseSubtract": lambda: substance_painter.layerstack.BlendingMode.InverseSubtract,
    "Difference": lambda: substance_painter.layerstack.BlendingMode.Difference,
    "Exclusion": lambda: substance_painter.layerstack.BlendingMode.Exclusion,
    "SignedAddition": lambda: substance_painter.layerstack.BlendingMode.SignedAddition,
    "Overlay": lambda: substance_painter.layerstack.BlendingMode.Overlay,
    "Screen": lambda: substance_painter.layerstack.BlendingMode.Screen,
    "LinearBurn": lambda: substance_painter.layerstack.BlendingMode.LinearBurn,
    "ColorBurn": lambda: substance_painter.layerstack.BlendingMode.ColorBurn,
    "ColorDodge": lambda: substance_painter.layerstack.BlendingMode.ColorDodge,
    "SoftLight": lambda: substance_painter.layerstack.BlendingMode.SoftLight,
    "HardLight": lambda: substance_painter.layerstack.BlendingMode.HardLight,
    "VividLight": lambda: substance_painter.layerstack.BlendingMode.VividLight,
    "LinearLight": lambda: substance_painter.layerstack.BlendingMode.LinearLight,
    "PinLight": lambda: substance_painter.layerstack.BlendingMode.PinLight,
    "Tint": lambda: substance_painter.layerstack.BlendingMode.Tint,
    "Saturation": lambda: substance_painter.layerstack.BlendingMode.Saturation,
    "Color": lambda: substance_painter.layerstack.BlendingMode.Color,
    "Value": lambda: substance_painter.layerstack.BlendingMode.Value,
    "NormalMapCombine": lambda: substance_painter.layerstack.BlendingMode.NormalMapCombine,
    "NormalMapDetail": lambda: substance_painter.layerstack.BlendingMode.NormalMapDetail,
    "NormalMapInverseDetail": (
        lambda: substance_painter.layerstack.BlendingMode.NormalMapInverseDetail
    ),
}

# colormanagement.GenericColorSpace members.
COLOR_SPACES = {
    "sRGB": lambda: substance_painter.colormanagement.GenericColorSpace.sRGB,
    "Working": lambda: substance_painter.colormanagement.GenericColorSpace.Working,
    "Raw": lambda: substance_painter.colormanagement.GenericColorSpace.Raw,
}

# display.CameraProjectionType members.
CAMERA_PROJECTIONS = {
    "Perspective": lambda: substance_painter.display.CameraProjectionType.Perspective,
    "Orthographic": lambda: substance_painter.display.CameraProjectionType.Orthographic,
}

# display.ToneMappingFunction members.
TONE_MAPPINGS = {
    "Linear": lambda: substance_painter.display.ToneMappingFunction.Linear,
    "ACES": lambda: substance_painter.display.ToneMappingFunction.ACES,
}

# ui.UIMode members.
UI_MODES = {
    "Edition": lambda: substance_painter.ui.UIMode.Edition,
    "Visualisation": lambda: substance_painter.ui.UIMode.Visualisation,
    "Baking": lambda: substance_painter.ui.UIMode.Baking,
}


def member(table: dict[str, Any], kind: str, name: str) -> Any:
    if name not in table:
        raise ValueError(f"{kind} {name!r} is not a documented member the recorder accepts")
    return table[name]()


def colour_management() -> dict[str, Any]:
    """Colour-management mode `project.create` selects (documented: OCIO, then ACE, else Legacy)."""
    ocio = os.environ.get("OCIO")
    ace = os.environ.get("PAINTER_ACE_CONFIG")
    mode = "ocio" if ocio else "ace" if ace else "legacy"
    return {"mode": mode, "OCIO": ocio, "PAINTER_ACE_CONFIG": ace}


def js_api_version() -> str:
    value = substance_painter.js.evaluate("alg.version.api")
    return str(json.loads(value)) if value.startswith('"') else str(value)


def hello(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "version": substance_painter.application.version(),
        "version_info": list(substance_painter.application.version_info()),
        "js_api_version": js_api_version(),
        "engine_computations": substance_painter.application.engine_computations_status(),
        "project_open": substance_painter.project.is_open(),
        "colour_management": colour_management(),
    }


def state(args: dict[str, Any]) -> dict[str, Any]:
    is_open = substance_painter.project.is_open()
    in_edition = is_open and substance_painter.project.is_in_edition_state()
    return {
        "is_open": is_open,
        "in_edition": in_edition,
        "busy": substance_painter.project.is_busy(),
        "file_path": substance_painter.project.file_path() if in_edition else None,
        "now": time.time(),
    }


def channel_type(name: str) -> Any:
    return member(CHANNEL_TYPES, "ChannelType", name)


def color_of(values: list[float], color_space: str | None) -> Any:
    r, g, b = (float(v) for v in values)
    if color_space is None:
        return substance_painter.colormanagement.Color(r, g, b)
    space = member(COLOR_SPACES, "GenericColorSpace", color_space)
    return substance_painter.colormanagement.Color(r, g, b, space)


def blending_of(node: Any, channel: Any) -> dict[str, Any]:
    return {
        "blending_mode": node.get_blending_mode(channel).name,
        "opacity": node.get_opacity(channel),
    }


def fill_defaults(node: Any) -> dict[str, Any]:
    """Effective defaults of a freshly inserted fill layer, read before any instruction edits it."""
    channels = sorted(node.active_channels, key=lambda c: c.name)
    return {
        "active_channels": [c.name for c in channels],
        "source_mode": None if node.source_mode is None else node.source_mode.name,
        "per_channel": {c.name: blending_of(node, c) for c in channels},
    }


def create_project(args: dict[str, Any], resolved: dict[str, Any]) -> dict[str, Any]:
    if substance_painter.project.is_open():
        raise RuntimeError("a project is already open; the recorder only creates its own")
    project = substance_painter.project
    settings = project.Settings(
        normal_map_format=(
            member(NORMAL_MAP_FORMATS, "NormalMapFormat", args["normal_map_format"])
            if "normal_map_format" in args
            else None
        ),
        tangent_space_mode=(
            member(TANGENT_SPACES, "TangentSpace", args["tangent_space_mode"])
            if "tangent_space_mode" in args
            else None
        ),
        project_workflow=(
            member(PROJECT_WORKFLOWS, "ProjectWorkflow", args["project_workflow"])
            if "project_workflow" in args
            else None
        ),
        default_texture_resolution=args.get("default_texture_resolution"),
        import_cameras=args.get("import_cameras"),
        mesh_unit_scale=args.get("mesh_unit_scale"),
    )
    project.create(mesh_file_path=resolved["mesh"], settings=settings)
    return {"colour_management": colour_management()}


def insert_position(args: dict[str, Any]) -> Any:
    layerstack = substance_painter.layerstack
    if "above_step" in args:
        return layerstack.InsertPosition.above_node(NODES[int(args["above_step"])])
    if "below_step" in args:
        return layerstack.InsertPosition.below_node(NODES[int(args["below_step"])])
    if args.get("position", "top") != "top":
        raise ValueError(f"unsupported insert position {args['position']!r}")
    stack = substance_painter.textureset.get_active_stack()
    return layerstack.InsertPosition.from_textureset_stack(stack)


def set_camera(name: str, value: Any) -> None:
    """Set one documented property of the default camera."""
    camera = substance_painter.display.Camera.get_default_camera()
    if name == "projection_type":
        camera.projection_type = member(CAMERA_PROJECTIONS, "CameraProjectionType", value)
    elif name == "position":
        camera.position = [float(v) for v in value]
    elif name == "rotation":
        camera.rotation = [float(v) for v in value]
    elif name == "field_of_view":
        camera.field_of_view = float(value)
    elif name == "focal_length":
        camera.focal_length = float(value)
    elif name == "focus_distance":
        camera.focus_distance = float(value)
    elif name == "aperture":
        camera.aperture = float(value)
    elif name == "orthographic_height":
        camera.orthographic_height = float(value)
    else:
        raise ValueError(f"unsupported camera property {name!r}")


def apply_step(args: dict[str, Any]) -> dict[str, Any]:
    """Apply one state-changing instruction; returns effective defaults where they are read."""
    step = int(args["step"])
    call = args["call"]
    params = args.get("args", {})
    resolved = args.get("resolved", {})
    result: dict[str, Any] = {}
    if call == CREATE:
        result = create_project(params, resolved)
    elif call == INSERT_FILL:
        node = substance_painter.layerstack.insert_fill(insert_position(params))
        NODES[step] = node
        result = {"defaults": fill_defaults(node)}
    elif call == SET_SOURCE:
        node = NODES[int(params["node_step"])]
        if "resource" in params:
            source = substance_painter.resource.ResourceID.from_url(params["resource"])
        else:
            source = color_of(params["color"], params.get("color_space"))
        node.set_source(channel_type(params["channel"]), source)
    elif call == SET_ACTIVE_CHANNELS:
        node = NODES[int(params["node_step"])]
        node.active_channels = {channel_type(c) for c in params["channels"]}
    elif call == SET_BLENDING_MODE:
        node = NODES[int(params["node_step"])]
        mode = member(BLENDING_MODES, "BlendingMode", params["blending_mode"])
        node.set_blending_mode(mode, channel_type(params["channel"]))
    elif call == SET_OPACITY:
        node = NODES[int(params["node_step"])]
        node.set_opacity(float(params["opacity"]), channel_type(params["channel"]))
    elif call == SET_RESOLUTIONS:
        resolution = substance_painter.textureset.Resolution(
            int(params["width"]), int(params["height"])
        )
        substance_painter.textureset.set_resolutions(
            substance_painter.textureset.all_texture_sets(), resolution
        )
    elif call.startswith(CAMERA) and call[len(CAMERA) :] in CAMERA_PROPERTIES:
        set_camera(call[len(CAMERA) :], params["value"])
    elif call == SET_ENVIRONMENT:
        resource = substance_painter.resource.import_project_resource(
            resolved["environment"], substance_painter.resource.Usage.ENVIRONMENT
        )
        substance_painter.display.set_environment_resource(resource.identifier())
        result = {"environment_url": resource.identifier().url()}
    elif call == SET_TONE_MAPPING:
        function = member(TONE_MAPPINGS, "ToneMappingFunction", params["function"])
        substance_painter.display.set_tone_mapping(function)
    else:
        raise ValueError(f"call {call!r} is not in the recorder vocabulary")
    result["done_at"] = time.time()
    return result


def property_value(value: Any) -> Any:
    """A `Property.value()` as JSON: colours in working space, tuples as lists."""
    if isinstance(value, substance_painter.colormanagement.Color):
        return {"working": list(value.working)}
    if isinstance(value, (tuple, list)):
        return [property_value(item) for item in value]
    return value


def source_value(source: Any) -> Any:
    """Readback of a fill source: a uniform colour, or every `Property` of a substance."""
    if isinstance(source, substance_painter.source.SourceUniformColor):
        return {"uniform_color_working": list(source.get_color().working)}
    if isinstance(source, substance_painter.source.SourceSubstance):
        properties = source.get_properties()
        return {
            "substance_properties": {
                name: {
                    "value": property_value(properties[name].value()),
                    "widget_type": properties[name].widget_type(),
                    "label": properties[name].label(),
                }
                for name in sorted(properties)
            }
        }
    return {"source_kind": "neither uniform colour nor substance"}


def readback(args: dict[str, Any]) -> Any:
    """Read one documented getter; the host records the value (or the documented exception)."""
    call = args["call"]
    params = args.get("args", {})
    if call == GET_SOURCE:
        node = NODES[int(params["node_step"])]
        return source_value(node.get_source(channel_type(params["channel"])))
    if call == GET_ACTIVE_CHANNELS:
        node = NODES[int(params["node_step"])]
        return sorted(c.name for c in node.active_channels)
    if call == GET_BLENDING_MODE:
        node = NODES[int(params["node_step"])]
        return node.get_blending_mode(channel_type(params["channel"])).name
    if call == GET_OPACITY:
        node = NODES[int(params["node_step"])]
        return node.get_opacity(channel_type(params["channel"]))
    if call == GET_RESOLUTION:
        texture_set = substance_painter.textureset.TextureSet.from_name(params["texture_set"])
        resolution = texture_set.get_resolution()
        return [resolution.width, resolution.height]
    raise ValueError(f"readback {call!r} is not in the recorder vocabulary")


def channel_description(channel: Any) -> dict[str, Any]:
    return {
        "format": channel.format().name,
        "bit_depth": channel.bit_depth(),
        "is_color": channel.is_color(),
        "is_floating": channel.is_floating(),
        "label": channel.label(),
    }


def template_capture(args: dict[str, Any]) -> dict[str, Any]:
    """Texture sets, stacks and channel formats of the open project (template capture)."""
    sets: dict[str, Any] = {}
    for texture_set in substance_painter.textureset.all_texture_sets():
        resolution = texture_set.get_resolution()
        stacks: dict[str, Any] = {}
        for stack in texture_set.all_stacks():
            channels = stack.all_channels()
            stacks[stack.name()] = {
                kind.name: channel_description(channels[kind])
                for kind in sorted(channels, key=lambda c: c.name)
            }
        sets[texture_set.name()] = {
            "resolution": [resolution.width, resolution.height],
            "stacks": stacks,
        }
    return {"texture_sets": sets}


def node_locations(args: dict[str, Any]) -> dict[str, Any]:
    """Where each recorded fill layer sits among its stack's root layers (stable across reopen)."""
    locations: dict[str, Any] = {}
    for step, node in sorted(NODES.items()):
        stack = node.get_stack()
        roots = substance_painter.layerstack.get_root_layer_nodes(stack)
        uids = [root.uid() for root in roots]
        locations[str(step)] = {
            "texture_set": stack.material().name(),
            "stack": stack.name(),
            "index": uids.index(node.uid()),
        }
    return locations


def rebind_nodes(args: dict[str, Any]) -> dict[str, Any]:
    """After reopening, find each recorded fill layer again at its recorded location."""
    NODES.clear()
    for step, where in args["locations"].items():
        stack = substance_painter.textureset.Stack.from_name(where["texture_set"], where["stack"])
        roots = substance_painter.layerstack.get_root_layer_nodes(stack)
        NODES[int(step)] = roots[int(where["index"])]
    return {"rebound": len(NODES)}


def export_textures(args: dict[str, Any]) -> dict[str, Any]:
    if not substance_painter.project.is_in_edition_state() or substance_painter.project.is_busy():
        raise RuntimeError("project not ready for export")
    called_at = time.time()
    result = substance_painter.export.export_project_textures(args["config"])
    return {
        "status": result.status.name,
        "message": result.message,
        "textures": [
            {"texture_set": key[0], "stack": key[1], "files": list(files)}
            for key, files in sorted(result.textures.items())
        ],
        "called_at": called_at,
        "returned_at": time.time(),
    }


def save_as(args: dict[str, Any]) -> dict[str, Any]:
    substance_painter.project.save_as(args["path"], substance_painter.project.ProjectSaveMode.Full)
    return {"saved_at": time.time()}


def close_project(args: dict[str, Any]) -> dict[str, Any]:
    if substance_painter.project.is_open():
        substance_painter.project.close()
    NODES.clear()
    return {"closed_at": time.time()}


def open_project(args: dict[str, Any]) -> dict[str, Any]:
    substance_painter.project.open(args["path"])
    return {"opened_at": time.time()}


def render_state(args: dict[str, Any]) -> dict[str, Any]:
    """Readback of every documented render setting (07-preview-and-render-parity.md §2.1)."""
    camera = substance_painter.display.Camera.get_default_camera()
    values: dict[str, Any] = {
        "camera.projection_type": camera.projection_type.name,
        "camera.position": list(camera.position),
        "camera.rotation": list(camera.rotation),
        "camera.field_of_view": camera.field_of_view,
        "camera.focal_length": camera.focal_length,
        "camera.focus_distance": camera.focus_distance,
        "camera.aperture": camera.aperture,
        "camera.orthographic_height": camera.orthographic_height,
    }
    environment = substance_painter.display.get_environment_resource()
    lut = substance_painter.display.get_color_lut_resource()
    values["environment_url"] = None if environment is None else environment.url()
    values["color_lut_url"] = None if lut is None else lut.url()
    try:
        values["tone_mapping"] = substance_painter.display.get_tone_mapping().name
    except RuntimeError as error:
        values["tone_mapping"] = {"raised": "RuntimeError", "message": str(error)}
    values["ui_mode"] = substance_painter.ui.get_current_mode().name
    values["colour_management"] = colour_management()
    return values


def switch_mode(args: dict[str, Any]) -> dict[str, Any]:
    substance_painter.ui.switch_to_mode(member(UI_MODES, "UIMode", args["mode"]))
    return {"mode": substance_painter.ui.get_current_mode().name, "switched_at": time.time()}


OPERATIONS = {
    "hello": hello,
    "state": state,
    "apply_step": apply_step,
    "readback": readback,
    "template_capture": template_capture,
    "node_locations": node_locations,
    "rebind_nodes": rebind_nodes,
    "export_textures": export_textures,
    "save_as": save_as,
    "close_project": close_project,
    "open_project": open_project,
    "render_state": render_state,
    "switch_mode": switch_mode,
}


def dispatch(operation: str, payload: str) -> str:
    """Run one operation on base64-encoded JSON arguments.

    The reply is a JSON string `{ok, value}` or `{ok: false, error}`.
    """
    try:
        value = OPERATIONS[operation](json.loads(base64.b64decode(payload).decode("utf-8")))
    except Exception as error:
        # repr(error) starts with the exception class name, e.g. "ProjectError('...')".
        kind = repr(error).split("(", 1)[0]
        return json.dumps({"ok": False, "error": {"type": kind, "message": str(error)}})
    return json.dumps({"ok": True, "value": value})
