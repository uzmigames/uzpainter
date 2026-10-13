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
import posixpath
import time
from typing import Any

import substance_painter.application
import substance_painter.baking
import substance_painter.colormanagement
import substance_painter.display
import substance_painter.event
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

# Resources imported by the instruction sequence, by step number (this namespace only).
RESOURCES: dict[int, Any] = {}

# The bake a `bake_async` step launched (this namespace only): texture sets still queued, the
# one baking, the status the `BakingProcessEnded` handler received, each finished set's status,
# and whether the handler is connected.
BAKE_STATE: dict[str, Any] = {
    "queue": [],
    "current": None,
    "status": None,
    "baked": [],
    "connected": False,
}

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

# Export probe (decision 087): the dry run of a literal `json_config`; when it succeeds the same
# configuration is exported (`export_textures`).
LIST_TEXTURES = "substance_painter.export.list_project_textures"

# Captures of texture jobs (recordings R6/R7): the export presets Painter lists and their output
# maps, and the colour spaces of a bitmap source. Read after the state steps, in every recording.
LIST_PREDEFINED_PRESETS = "substance_painter.export.list_predefined_export_presets"
LIST_RESOURCE_PRESETS = "substance_painter.export.list_resource_export_presets"
PREDEFINED_OUTPUT_MAPS = "substance_painter.export.PredefinedExportPreset.list_output_maps"
RESOURCE_OUTPUT_MAPS = "substance_painter.export.ResourceExportPreset.list_output_maps"
LIST_COLOR_SPACES = "substance_painter.source.SourceBitmap.list_available_color_spaces"

# An attempted `SourceBitmap.set_color_space` (decision 156): a state step whose refusal is the
# observation. What Painter raises is recorded in the effective defaults instead of failing the
# golden (e.g. a mask fill effect's grey source set to sRGB, decision 145 s5).
SET_COLOR_SPACE = "substance_painter.source.SourceBitmap.set_color_space"

# Procedural vocabulary (phase0.6_procedural-feasibility): imported resources, mesh maps, masks,
# generator effects, smart materials and substance parameters.
IMPORT_RESOURCE = "substance_painter.resource.import_project_resource"
SET_MESH_MAP = "substance_painter.textureset.TextureSet.set_mesh_map_resource"
ADD_MASK = "substance_painter.layerstack.LayerNode.add_mask"
INSERT_GENERATOR = "substance_painter.layerstack.insert_generator_effect"
INSERT_SMART_MATERIAL = "substance_painter.layerstack.insert_smart_material"
SET_PARAMETERS = "substance_painter.source.SourceSubstance.set_parameters"
GET_MESH_MAP = "substance_painter.textureset.TextureSet.get_mesh_map_resource"
GET_GENERATOR_SOURCE = "substance_painter.layerstack.GeneratorEffectNode.get_source"
GET_SUB_LAYERS = "substance_painter.layerstack.GroupLayerNode.sub_layers"

# Tier 0 semantics vocabulary: groups, content and mask effects, levels, UV projection, channels.
INSERT_GROUP = "substance_painter.layerstack.insert_group"
INSERT_LEVELS = "substance_painter.layerstack.insert_levels_effect"
INSERT_FILTER = "substance_painter.layerstack.insert_filter_effect"
RESOURCE_SEARCH = "substance_painter.resource.search"
SET_EFFECT_SOURCE = "substance_painter.layerstack.FillEffectNode.set_source"
SET_EFFECT_CHANNELS = "substance_painter.layerstack.FillEffectNode.active_channels"
SET_FILTER_CHANNELS = "substance_painter.layerstack.FilterEffectNode.active_channels"
SET_LEVELS_CHANNEL = "substance_painter.layerstack.LevelsEffectNode.affected_channel"
SET_LEVELS = "substance_painter.layerstack.LevelsEffectNode.set_parameters"
SET_PROJECTION = "substance_painter.layerstack.FillLayerNode.set_projection_parameters"
ADD_CHANNEL = "substance_painter.textureset.Stack.add_channel"
EDIT_CHANNEL = "substance_painter.textureset.Stack.edit_channel"
GET_EFFECT_SOURCE = "substance_painter.layerstack.FillEffectNode.get_source"
GET_LEVELS = "substance_painter.layerstack.LevelsEffectNode.get_parameters"
GET_PROJECTION = "substance_painter.layerstack.FillLayerNode.get_projection_parameters"
LEVELS_FIELDS = ("input_min", "input_max", "gamma", "output_min", "output_max", "clamp")

# Readback calls (getters of the setters above).
GET_SOURCE = "substance_painter.layerstack.FillLayerNode.get_source"
GET_ACTIVE_CHANNELS = "substance_painter.layerstack.FillLayerNode.active_channels"
GET_BLENDING_MODE = "substance_painter.layerstack.Node.get_blending_mode"
GET_OPACITY = "substance_painter.layerstack.Node.get_opacity"
GET_RESOLUTION = "substance_painter.textureset.TextureSet.get_resolution"

# Baking-defaults captures (read on every texture set of a fresh project).
BAKING_COMMON = "substance_painter.baking.BakingParameters.common"
BAKING_BAKER = "substance_painter.baking.BakingParameters.baker"
BAKING_CURVATURE_METHOD = "substance_painter.baking.BakingParameters.get_curvature_method"
BAKING_ENABLED_BAKERS = "substance_painter.baking.BakingParameters.get_enabled_bakers"
BAKING_TEXTURESET_ENABLED = "substance_painter.baking.BakingParameters.is_textureset_enabled"

# Baking jobs (phase0.9_normal-convention-fixture): parameters, enabled bakers, the bake itself.
BAKING_SET = "substance_painter.baking.BakingParameters.set"
BAKING_SET_ENABLED_BAKERS = "substance_painter.baking.BakingParameters.set_enabled_bakers"
BAKE = "substance_painter.baking.bake_async"
GET_PROPERTY_VALUE = "substance_painter.properties.Property.value"
# Arguments of a `BakingParameters.set` step: the parameter, its value (exactly one of `value`,
# `enum_label`, `input`), the baker `usage` (else a common parameter), the texture set.
BAKING_SET_ARGS = ("parameter", "value", "enum_label", "input", "usage", "texture_set")
# `baking.BakingStatus` member name of a bake that completed.
BAKE_SUCCESS = "Success"

# The ten bakers (textureset.MeshMapUsage members), in the order of 06-baking.md §2.
BAKER_USAGES = (
    "Normal",
    "WorldSpaceNormal",
    "ID",
    "AO",
    "Curvature",
    "Position",
    "Thickness",
    "Height",
    "BentNormals",
    "Opacity",
)

# Project templates are `.spt` files (project.create `template_file_path`); shipped ones are
# found under the documented application shelf (resource.Shelves.application_shelf).
TEMPLATE_SUFFIX = ".spt"

# Documented `properties.Property` getters recorded for every baking parameter key.
PROPERTY_FIELDS = (
    "value",
    "name",
    "short_name",
    "label",
    "widget_type",
    "enum_values",
    "properties",
)

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
    "CoatColor": lambda: substance_painter.textureset.ChannelType.CoatColor,
    "CoatRoughness": lambda: substance_painter.textureset.ChannelType.CoatRoughness,
    "CoatWeight": lambda: substance_painter.textureset.ChannelType.CoatWeight,
    "FuzzColor": lambda: substance_painter.textureset.ChannelType.FuzzColor,
    "FuzzRoughness": lambda: substance_painter.textureset.ChannelType.FuzzRoughness,
    "FuzzWeight": lambda: substance_painter.textureset.ChannelType.FuzzWeight,
    "SubsurfaceColor": lambda: substance_painter.textureset.ChannelType.SubsurfaceColor,
    "SubsurfaceRadiusScale": lambda: substance_painter.textureset.ChannelType.SubsurfaceRadiusScale,
    "SubsurfaceWeight": lambda: substance_painter.textureset.ChannelType.SubsurfaceWeight,
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
    "User4": lambda: substance_painter.textureset.ChannelType.User4,
    "User5": lambda: substance_painter.textureset.ChannelType.User5,
    "User6": lambda: substance_painter.textureset.ChannelType.User6,
    "User7": lambda: substance_painter.textureset.ChannelType.User7,
    "User8": lambda: substance_painter.textureset.ChannelType.User8,
    "User9": lambda: substance_painter.textureset.ChannelType.User9,
    "Scattering": lambda: substance_painter.textureset.ChannelType.Scattering,
    "Anisotropylevel": lambda: substance_painter.textureset.ChannelType.Anisotropylevel,
    # The Specular Glossiness workflow's channels (decision 093).
    "Diffuse": lambda: substance_painter.textureset.ChannelType.Diffuse,
    "Specular": lambda: substance_painter.textureset.ChannelType.Specular,
    "Glossiness": lambda: substance_painter.textureset.ChannelType.Glossiness,
}

# textureset.ChannelFormat members.
CHANNEL_FORMATS = {
    "sRGB8": lambda: substance_painter.textureset.ChannelFormat.sRGB8,
    "L8": lambda: substance_painter.textureset.ChannelFormat.L8,
    "RGB8": lambda: substance_painter.textureset.ChannelFormat.RGB8,
    "L16": lambda: substance_painter.textureset.ChannelFormat.L16,
    "RGB16": lambda: substance_painter.textureset.ChannelFormat.RGB16,
    "L16F": lambda: substance_painter.textureset.ChannelFormat.L16F,
    "RGB16F": lambda: substance_painter.textureset.ChannelFormat.RGB16F,
    "L32F": lambda: substance_painter.textureset.ChannelFormat.L32F,
    "RGB32F": lambda: substance_painter.textureset.ChannelFormat.RGB32F,
}

# layerstack.NodeStack members (where `inside_step` inserts).
NODE_STACKS = {
    "Substack": lambda: substance_painter.layerstack.NodeStack.Substack,
    "Content": lambda: substance_painter.layerstack.NodeStack.Content,
    "Mask": lambda: substance_painter.layerstack.NodeStack.Mask,
}

# layerstack.FilteringMode, UVWrapMode and ScaleMode members (UV projection parameters).
FILTERING_MODES = {
    "BilinearHQ": lambda: substance_painter.layerstack.FilteringMode.BilinearHQ,
    "BilinearSharp": lambda: substance_painter.layerstack.FilteringMode.BilinearSharp,
    "Nearest": lambda: substance_painter.layerstack.FilteringMode.Nearest,
}
UV_WRAP_MODES = {
    "RepeatNone": lambda: substance_painter.layerstack.UVWrapMode.RepeatNone,
    "RepeatHorizontally": lambda: substance_painter.layerstack.UVWrapMode.RepeatHorizontally,
    "RepeatVertically": lambda: substance_painter.layerstack.UVWrapMode.RepeatVertically,
    "Repeat": lambda: substance_painter.layerstack.UVWrapMode.Repeat,
}
SCALE_MODES = {
    "Factors": lambda: substance_painter.layerstack.ScaleMode.Factors,
}

# textureset.MeshMapUsage members.
MESH_MAP_USAGES = {
    "Normal": lambda: substance_painter.textureset.MeshMapUsage.Normal,
    "WorldSpaceNormal": lambda: substance_painter.textureset.MeshMapUsage.WorldSpaceNormal,
    "ID": lambda: substance_painter.textureset.MeshMapUsage.ID,
    "AO": lambda: substance_painter.textureset.MeshMapUsage.AO,
    "Curvature": lambda: substance_painter.textureset.MeshMapUsage.Curvature,
    "Position": lambda: substance_painter.textureset.MeshMapUsage.Position,
    "Thickness": lambda: substance_painter.textureset.MeshMapUsage.Thickness,
    "Height": lambda: substance_painter.textureset.MeshMapUsage.Height,
    "BentNormals": lambda: substance_painter.textureset.MeshMapUsage.BentNormals,
    "Opacity": lambda: substance_painter.textureset.MeshMapUsage.Opacity,
}

# layerstack.MaskBackground members.
MASK_BACKGROUNDS = {
    "Black": lambda: substance_painter.layerstack.MaskBackground.Black,
    "White": lambda: substance_painter.layerstack.MaskBackground.White,
}

# resource.Usage members the procedural vocabulary imports or looks up.
RESOURCE_USAGES = {
    "TEXTURE": lambda: substance_painter.resource.Usage.TEXTURE,
    "GENERATOR": lambda: substance_painter.resource.Usage.GENERATOR,
    "SMART_MATERIAL": lambda: substance_painter.resource.Usage.SMART_MATERIAL,
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

# Colour spaces a bitmap source may be set to: the generic ones, and the `LegacyColorSpace`
# members by qualified name (a bare `sRGB` stays the generic member; decision 156).
BITMAP_COLOR_SPACES = {
    **COLOR_SPACES,
    "LegacyColorSpace.Linear": lambda: substance_painter.colormanagement.LegacyColorSpace.Linear,
    "LegacyColorSpace.sRGB": lambda: substance_painter.colormanagement.LegacyColorSpace.sRGB,
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


def channel_type(name: str | None) -> Any:
    """A documented `ChannelType`; None stays None (mono-channel mask-stack context)."""
    if name is None:
        return None
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
    if node.is_in_mask_stack():
        return {"mask": blending_of(node, None)}
    channels = sorted(node.active_channels, key=lambda c: c.name)
    return {
        "active_channels": [c.name for c in channels],
        "source_mode": None if node.source_mode is None else node.source_mode.name,
        "per_channel": {c.name: blending_of(node, c) for c in channels},
    }


def node_defaults(node: Any) -> dict[str, Any]:
    """Blending of a freshly inserted group or effect for each channel of its stack (a raising
    getter, e.g. on a node without blending, is recorded as raised)."""
    if node.is_in_mask_stack():
        channels: list[Any] = [None]
    else:
        channels = sorted(node.get_stack().all_channels(), key=lambda c: c.name)
    values: dict[str, Any] = {}
    for channel in channels:
        name = "mask" if channel is None else channel.name
        try:
            values[name] = blending_of(node, channel)
        except Exception as error:
            values[name] = {"raised": {"type": repr(error).split("(", 1)[0], "message": str(error)}}
    return {"per_channel": values}


def levels_value(params: Any) -> dict[str, Any]:
    """`LevelsParamsMono`/`LevelsParamsRGB` fields as JSON (tuples as lists)."""
    fields = {
        "input_min": params.input_min,
        "input_max": params.input_max,
        "gamma": params.gamma,
        "output_min": params.output_min,
        "output_max": params.output_max,
        "clamp": params.clamp,
    }
    return {k: levels_field(v) for k, v in fields.items()}


def levels_field(value: Any) -> Any:
    """A levels field as JSON: a number or flag as is, an RGB triple as a list of floats."""
    if isinstance(value, (bool, int, float)):
        return value
    return [float(component) for component in value]


def colour_space_name(space: Any) -> str:
    """A documented colour space (`GenericColorSpace`, `LegacyColorSpace`, `DataColorSpace`,
    `NormalColorSpace` member, or a string) by name."""
    return space if isinstance(space, str) else str(space.name)


def set_levels(node: Any, args: dict[str, Any]) -> None:
    """Edit the documented levels fields the step gives (a scalar is used for R, G and B)."""
    params = node.get_parameters()
    rgb = not isinstance(params.input_min, (int, float))

    def value(name: str, current: Any) -> Any:
        if name not in args:
            return current
        given = args[name]
        if rgb:
            items = given if isinstance(given, list) else [given, given, given]
            return tuple(float(v) for v in items)
        return float(given)

    params.input_min = value("input_min", params.input_min)
    params.input_max = value("input_max", params.input_max)
    params.gamma = value("gamma", params.gamma)
    params.output_min = value("output_min", params.output_min)
    params.output_max = value("output_max", params.output_max)
    if "clamp" in args:
        params.clamp = bool(args["clamp"])
    node.set_parameters(params)


def uv_projection(args: dict[str, Any]) -> Any:
    """Documented `UVProjectionParams` from authored step arguments (all fields given)."""
    layerstack = substance_painter.layerstack
    transformation = layerstack.UVTransformationParams(
        scale_mode=member(SCALE_MODES, "ScaleMode", args["scale_mode"]),
        scale=[float(v) for v in args["scale"]],
        rotation=float(args["rotation"]),
        offset=[float(v) for v in args["offset"]],
    )
    return layerstack.UVProjectionParams(
        filtering_mode=member(FILTERING_MODES, "FilteringMode", args["filtering_mode"]),
        uv_wrapping_mode=member(UV_WRAP_MODES, "UVWrapMode", args["uv_wrapping_mode"]),
        uv_transformation=transformation,
    )


def projection_value(node: Any) -> dict[str, Any]:
    """Readback of a fill layer's projection mode and UV projection parameters."""
    params = node.get_projection_parameters()
    transformation = params.uv_transformation
    return {
        "projection_mode": node.get_projection_mode().name,
        "filtering_mode": params.filtering_mode.name,
        "uv_wrapping_mode": params.uv_wrapping_mode.name,
        "scale_mode": transformation.scale_mode.name,
        "scale": list(transformation.scale),
        "rotation": transformation.rotation,
        "offset": list(transformation.offset),
    }


def target_stacks(args: dict[str, Any]) -> list[Any]:
    """The stack of the named texture set, or the stack of every texture set."""
    if "texture_set" in args:
        return [substance_painter.textureset.Stack.from_name(args["texture_set"])]
    return [ts.get_stack() for ts in substance_painter.textureset.all_texture_sets()]


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
    template = shipped_template_path(args["template"]) if "template" in args else None
    project.create(mesh_file_path=resolved["mesh"], template_file_path=template, settings=settings)
    return {"colour_management": colour_management()}


def application_shelf_root() -> str:
    return str(substance_painter.resource.Shelves.application_shelf().path())


def is_template_file(name: str) -> bool:
    return os.path.normcase(os.path.splitext(name)[1]) == TEMPLATE_SUFFIX


def shipped_templates(args: dict[str, Any]) -> dict[str, Any]:
    """Identifiers (shelf-relative POSIX paths) of the `.spt` files of the application shelf.

    Only file names are listed; Painter itself opens a template through `project.create`.
    """
    root = application_shelf_root()
    found: list[str] = []
    for folder, _folders, files in os.walk(root):
        for name in files:
            if is_template_file(name):
                relative = os.path.relpath(os.path.join(folder, name), root)
                found.append(posixpath.join(*relative.split(os.sep)))
    return {"templates": sorted(found)}


def shipped_template_path(identifier: str) -> str:
    """The file of a shipped template identifier; refuses anything outside the shelf."""
    parts = identifier.split("/")
    if (
        not is_template_file(identifier)
        or os.path.isabs(identifier)
        or ":" in identifier
        or "\\" in identifier
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise ValueError(f"{identifier!r} is not a shelf-relative template identifier")
    path = os.path.join(application_shelf_root(), *parts)
    if not os.path.isfile(path):
        raise ValueError(f"{identifier!r} is not a template of the application shelf")
    return path


def json_value(value: Any) -> Any:
    """A documented return value as JSON: colours in working space, tuples as lists."""
    if isinstance(value, substance_painter.colormanagement.Color):
        return {"working": list(value.working)}
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return {"unrepresented": repr(value)}


def raised_by(error: Exception) -> dict[str, str]:
    return {"type": repr(error).split("(", 1)[0], "message": str(error)}


def describe_property(prop: Any) -> dict[str, Any]:
    """Every documented getter of one `properties.Property`; a raising getter is recorded."""
    getters = {
        "value": prop.value,
        "name": prop.name,
        "short_name": prop.short_name,
        "label": prop.label,
        "widget_type": prop.widget_type,
        "enum_values": prop.enum_values,
        "properties": prop.properties,
    }
    described: dict[str, Any] = {}
    raised: dict[str, Any] = {}
    for field in PROPERTY_FIELDS:
        try:
            described[field] = json_value(getters[field]())
        except Exception as error:
            raised[field] = raised_by(error)
    labels = described.get("enum_values")
    if isinstance(labels, dict) and labels:
        values: dict[str, Any] = {}
        for label in sorted(labels):
            try:
                values[label] = prop.enum_value(label)
            except Exception as error:
                raised["enum_value/" + label] = raised_by(error)
        described["enum_value"] = values
    if raised:
        described["raised"] = raised
    return described


def describe_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(parameters)
    return {"keys": keys, "properties": {key: describe_property(parameters[key]) for key in keys}}


def baking_capture(args: dict[str, Any]) -> dict[str, Any]:
    """One baking-defaults capture on every texture set of the open project."""
    call = args["call"]
    params = args.get("args", {})
    sets: dict[str, Any] = {}
    for texture_set in substance_painter.textureset.all_texture_sets():
        baking = substance_painter.baking.BakingParameters.from_texture_set(texture_set)
        if call == BAKING_COMMON:
            value: Any = describe_parameters(baking.common())
        elif call == BAKING_BAKER:
            usage = member(MESH_MAP_USAGES, "MeshMapUsage", params["usage"])
            value = describe_parameters(baking.baker(usage))
        elif call == BAKING_CURVATURE_METHOD:
            value = baking.get_curvature_method().name
        elif call == BAKING_ENABLED_BAKERS:
            value = sorted(usage.name for usage in baking.get_enabled_bakers())
        elif call == BAKING_TEXTURESET_ENABLED:
            value = baking.is_textureset_enabled()
        else:
            raise ValueError(f"capture {call!r} is not in the recorder vocabulary")
        sets[texture_set.name()] = value
    return {"texture_sets": sets}


def baking_parameter(texture_set: Any, params: dict[str, Any]) -> Any:
    """The `properties.Property` a step names: `parameter` among the common parameters, or among
    those of the baker its `usage` (a `MeshMapUsage` member name) names."""
    baking = substance_painter.baking.BakingParameters.from_texture_set(texture_set)
    usage = params.get("usage")
    if usage is None:
        group = baking.common()
    else:
        group = baking.baker(member(MESH_MAP_USAGES, "MeshMapUsage", usage))
    key = params["parameter"]
    if key not in group:
        raise ValueError(f"{key!r} is not a {usage or 'common'} baking parameter")
    return group[key]


def set_baking_parameter(params: dict[str, Any], resolved: dict[str, Any]) -> None:
    """One documented `BakingParameters.set` call per texture set for the step's parameter: its
    `value` (a list as a tuple), an `enum_label` through the documented `Property.enum_value`,
    or the `file:///` URL of an `input` (resolved by the host)."""
    for texture_set in texture_sets_of(params):
        prop = baking_parameter(texture_set, params)
        if "input" in resolved:
            value = resolved["input"]
        elif "enum_label" in params:
            value = prop.enum_value(params["enum_label"])
        elif isinstance(params["value"], list):
            value = tuple(params["value"])
        else:
            value = params["value"]
        substance_painter.baking.BakingParameters.set({prop: value})


def enabled_bakers(texture_set: Any) -> list[str]:
    baking = substance_painter.baking.BakingParameters.from_texture_set(texture_set)
    return sorted(usage.name for usage in baking.get_enabled_bakers())


def on_baking_ended(event: Any) -> None:
    """`event.BakingProcessEnded` handler: keeps the status for `baking_state` to report."""
    BAKE_STATE["status"] = event.status.name


def bake_disconnect() -> None:
    if BAKE_STATE["connected"]:
        substance_painter.event.DISPATCHER.disconnect(
            substance_painter.event.BakingProcessEnded, on_baking_ended
        )
        BAKE_STATE["connected"] = False


def bake_next() -> None:
    """Launch the bake of the next queued texture set; it ends with `BakingProcessEnded`."""
    queue = BAKE_STATE["queue"]
    BAKE_STATE["queue"] = queue[1:]
    BAKE_STATE["current"], BAKE_STATE["status"] = queue[0].name(), None
    substance_painter.baking.bake_async(queue[0])


def start_bake(params: dict[str, Any]) -> dict[str, Any]:
    """Connect the `BakingProcessEnded` handler, then launch the first texture set's bake.

    Returns at once (the bake is asynchronous); the host polls `baking_state`, which launches
    the remaining texture sets one after another.
    """
    if BAKE_STATE["current"] is not None:
        raise RuntimeError("a bake launched by the recorder has not ended")
    texture_sets = texture_sets_of(params)
    enabled = {texture_set.name(): enabled_bakers(texture_set) for texture_set in texture_sets}
    if not BAKE_STATE["connected"]:
        substance_painter.event.DISPATCHER.connect(
            substance_painter.event.BakingProcessEnded, on_baking_ended
        )
        BAKE_STATE["connected"] = True
    BAKE_STATE["queue"], BAKE_STATE["baked"] = texture_sets, []
    bake_next()
    return {"enabled_bakers": enabled}


def baking_state(args: dict[str, Any]) -> dict[str, Any]:
    """Whether the launched bake has ended, and its status (never waits)."""
    if BAKE_STATE["current"] is None:
        raise RuntimeError("no bake launched by the recorder is in progress")
    status = BAKE_STATE["status"]
    busy = substance_painter.project.is_busy()
    if status is None:
        return {"ended": False, "texture_set": BAKE_STATE["current"], "busy": busy}
    BAKE_STATE["baked"].append({"texture_set": BAKE_STATE["current"], "status": status})
    if status == BAKE_SUCCESS and BAKE_STATE["queue"]:
        bake_next()
        return {"ended": False, "texture_set": BAKE_STATE["current"], "busy": busy}
    BAKE_STATE["current"] = None
    bake_disconnect()
    return {"ended": True, "status": status, "baked": list(BAKE_STATE["baked"]), "busy": busy}


def insert_position(args: dict[str, Any]) -> Any:
    layerstack = substance_painter.layerstack
    if "above_step" in args:
        return layerstack.InsertPosition.above_node(NODES[int(args["above_step"])])
    if "below_step" in args:
        return layerstack.InsertPosition.below_node(NODES[int(args["below_step"])])
    if "inside_step" in args:
        node_stack = member(NODE_STACKS, "NodeStack", args["stack"])
        return layerstack.InsertPosition.inside_node(NODES[int(args["inside_step"])], node_stack)
    if args.get("position", "top") != "top":
        raise ValueError(f"unsupported insert position {args['position']!r}")
    if "texture_set" in args:
        stack = substance_painter.textureset.Stack.from_name(args["texture_set"])
    else:
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


def find_resource(params: dict[str, Any]) -> Any:
    """The `ResourceID` a step names: a `resource://` URL, or exactly one resource found by name.

    A lookup by name (`resource_name`, `resource_usage`, optional `resource_context`) uses the
    documented `resource.search`; the GUI name or the identifier name must equal the given name
    and the resource must have that usage. Zero or several matches refuse the step.
    """
    if "resource" in params:
        return substance_painter.resource.ResourceID.from_url(params["resource"])
    name = params["resource_name"]
    usage = member(RESOURCE_USAGES, "Usage", params["resource_usage"])
    context = params.get("resource_context")
    matches = []
    for found in substance_painter.resource.search(name):
        identifier = found.identifier()
        if name not in (found.gui_name(), identifier.name) or usage not in found.usages():
            continue
        if context is None or identifier.context == context:
            matches.append(identifier)
    if len(matches) != 1:
        urls = sorted(match.url() for match in matches)
        raise ValueError(
            f"{len(matches)} {params['resource_usage']} resources named {name!r}: {urls}"
        )
    return matches[0]


def texture_sets_of(params: dict[str, Any]) -> list[Any]:
    if "texture_set" in params:
        return [substance_painter.textureset.TextureSet.from_name(params["texture_set"])]
    return list(substance_painter.textureset.all_texture_sets())


def substance_description(source: Any) -> dict[str, Any]:
    """A substance source: its resource, every `Property` described, presets, image ports."""
    if not isinstance(source, substance_painter.source.SourceSubstance):
        return {"source": None if source is None else source_value(source)}
    properties = source.get_properties()
    described: dict[str, Any] = {
        "resource_url": source.resource_id.url(),
        "properties": {name: describe_property(properties[name]) for name in sorted(properties)},
    }
    getters = {
        "presets": source.get_preset_list,
        "image_inputs": lambda: source.image_inputs,
        "image_outputs": lambda: source.image_outputs,
    }
    for field, getter in getters.items():
        try:
            described[field] = json_value(getter())
        except Exception as error:
            described[field] = {"raised": raised_by(error)}
    return described


def node_structure(node: Any) -> dict[str, Any]:
    """Name, type, sources and children of a node and everything below it (private readback)."""
    kind = node.get_type().name
    entry: dict[str, Any] = {"name": node.get_name(), "type": kind}
    if kind in ("FillLayer", "FillEffect"):
        sources: dict[str, Any] = {}
        for channel in sorted(node.active_channels, key=lambda c: c.name):
            try:
                sources[channel.name] = substance_description(node.get_source(channel))
            except Exception as error:
                sources[channel.name] = {"raised": raised_by(error)}
        entry["sources"] = sources
    elif kind in ("GeneratorEffect", "FilterEffect"):
        entry["source"] = substance_description(node.get_source())
    children: tuple[str, ...] = ("sub_layers",) if kind == "GroupLayer" else ()
    if kind in ("FillLayer", "PaintLayer", "GroupLayer", "InstanceLayer"):
        children += ("content_effects", "mask_effects")
    for field in children:
        try:
            entry[field] = [node_structure(child) for child in child_nodes(node, field)]
        except Exception as error:
            entry[field] = {"raised": raised_by(error)}
    return entry


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
    elif call in (SET_SOURCE, SET_EFFECT_SOURCE):
        node = NODES[int(params["node_step"])]
        if "resource" in params:
            source = substance_painter.resource.ResourceID.from_url(params["resource"])
        elif "resource_step" in params:
            source = RESOURCES[int(params["resource_step"])].identifier()
        else:
            source = color_of(params["color"], params.get("color_space"))
        node.set_source(channel_type(params["channel"]), source)
        if "color" not in params and "color_space" in params:
            # A bitmap source's colour space (documented `SourceBitmap.set_color_space`).
            space = member(BITMAP_COLOR_SPACES, "bitmap colour space", params["color_space"])
            node.get_source(channel_type(params["channel"])).set_color_space(space)
    elif call == SET_COLOR_SPACE:
        node = NODES[int(params["node_step"])]
        space = member(BITMAP_COLOR_SPACES, "bitmap colour space", params["color_space"])
        try:
            node.get_source(channel_type(params["channel"])).set_color_space(space)
            result = {"applied": True}
        except Exception as error:  # Painter's refusal is the observation (decision 156)
            result = {"applied": False, "raised": raised_by(error)}
    elif call in (SET_ACTIVE_CHANNELS, SET_EFFECT_CHANNELS, SET_FILTER_CHANNELS):
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
        # The named texture set, else every texture set; width and height may differ.
        resolution = substance_painter.textureset.Resolution(
            int(params["width"]), int(params["height"])
        )
        substance_painter.textureset.set_resolutions(texture_sets_of(params), resolution)
    elif call.startswith(CAMERA) and call[len(CAMERA) :] in CAMERA_PROPERTIES:
        set_camera(call[len(CAMERA) :], params["value"])
    elif call == SET_ENVIRONMENT:
        if "resource_url" in params:  # a resource Painter already has (e.g. a shelf asset)
            identifier = substance_painter.resource.ResourceID.from_url(params["resource_url"])
        elif "session_environment" in params:  # the ref_match preset's session resource
            identifier = substance_painter.resource.import_session_resource(
                resolved["environment"], substance_painter.resource.Usage.ENVIRONMENT
            ).identifier()
        else:
            identifier = substance_painter.resource.import_project_resource(
                resolved["environment"], substance_painter.resource.Usage.ENVIRONMENT
            ).identifier()
        substance_painter.display.set_environment_resource(identifier)
        result = {"environment_url": identifier.url()}
    elif call == SET_TONE_MAPPING:
        function = member(TONE_MAPPINGS, "ToneMappingFunction", params["function"])
        substance_painter.display.set_tone_mapping(function)
    elif call == INSERT_GROUP:
        node = substance_painter.layerstack.insert_group(insert_position(params))
        NODES[step] = node
        result = {"defaults": node_defaults(node)}
    elif call == INSERT_LEVELS:
        node = substance_painter.layerstack.insert_levels_effect(insert_position(params))
        NODES[step] = node
        result = {
            "defaults": {
                "affected_channel": node.affected_channel.name,
                "parameters": levels_value(node.get_parameters()),
            }
        }
    elif call == INSERT_FILTER:
        found = substance_painter.resource.search(params["filter_search"])
        if not found:
            raise ValueError(f"no resource matches {params['filter_search']!r}")
        filter_id = found[0].identifier()
        node = substance_painter.layerstack.insert_filter_effect(insert_position(params), filter_id)
        NODES[step] = node
        result = {"filter_url": filter_id.url(), "defaults": node_defaults(node)}
    elif call == SET_LEVELS_CHANNEL:
        node = NODES[int(params["node_step"])]
        node.affected_channel = channel_type(params["channel"])
    elif call == SET_LEVELS:
        set_levels(NODES[int(params["node_step"])], params)
    elif call == SET_PROJECTION:
        NODES[int(params["node_step"])].set_projection_parameters(uv_projection(params))
    elif call in (ADD_CHANNEL, EDIT_CHANNEL):
        kind = channel_type(params["channel"])
        channel_format = member(CHANNEL_FORMATS, "ChannelFormat", params["format"])
        for stack in target_stacks(params):
            if call == ADD_CHANNEL:
                stack.add_channel(kind, channel_format)
            else:
                stack.edit_channel(kind, channel_format)
    elif call == IMPORT_RESOURCE:
        usage = member(RESOURCE_USAGES, "Usage", params["usage"])
        resource = substance_painter.resource.import_project_resource(resolved["input"], usage)
        RESOURCES[step] = resource
        result = {"resource_url": resource.identifier().url()}
    elif call == SET_MESH_MAP:
        usage = member(MESH_MAP_USAGES, "MeshMapUsage", params["usage"])
        identifier = RESOURCES[int(params["resource_step"])].identifier()
        for texture_set in texture_sets_of(params):
            texture_set.set_mesh_map_resource(usage, identifier)
    elif call == ADD_MASK:
        background = member(MASK_BACKGROUNDS, "MaskBackground", params["background"])
        NODES[int(params["node_step"])].add_mask(background)
    elif call == INSERT_GENERATOR:
        identifier = find_resource(params)
        NODES[step] = substance_painter.layerstack.insert_generator_effect(
            insert_position(params), identifier
        )
        result = {"resource_url": identifier.url()}
    elif call == INSERT_SMART_MATERIAL:
        identifier = find_resource(params)
        NODES[step] = substance_painter.layerstack.insert_smart_material(
            insert_position(params), identifier
        )
        result = {"resource_url": identifier.url()}
    elif call == SET_PARAMETERS:
        node = NODES[int(params["node_step"])]
        if "channel" in params:
            source = node.get_source(channel_type(params["channel"]))
        else:
            source = node.get_source()
        value = params["value"]
        source.set_parameters(
            {params["parameter"]: tuple(value) if isinstance(value, list) else value}
        )
    elif call == BAKING_SET:
        set_baking_parameter(params, resolved)
    elif call == BAKING_SET_ENABLED_BAKERS:
        usages = [member(MESH_MAP_USAGES, "MeshMapUsage", name) for name in params["usages"]]
        for texture_set in texture_sets_of(params):
            baking = substance_painter.baking.BakingParameters.from_texture_set(texture_set)
            baking.set_enabled_bakers(usages)
    elif call == BAKE:
        result = start_bake(params)
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
    if isinstance(source, substance_painter.source.SourceBitmap):
        return {
            "bitmap": {
                "resource_url": source.resource_id.url(),
                "color_space": colour_space_name(source.get_color_space()),
                "available_color_spaces": [
                    colour_space_name(space) for space in source.list_available_color_spaces()
                ],
            }
        }
    return {"source_kind": "neither uniform colour, substance nor bitmap"}


def colour_space_value(space: Any) -> dict[str, str]:
    """A colour space by documented class (`GenericColorSpace`, `LegacyColorSpace`,
    `DataColorSpace`, `NormalColorSpace`, or `str`) and name."""
    colormanagement = substance_painter.colormanagement
    if isinstance(space, str):
        kind = "str"
    elif isinstance(space, colormanagement.GenericColorSpace):
        kind = "GenericColorSpace"
    elif isinstance(space, colormanagement.LegacyColorSpace):
        kind = "LegacyColorSpace"
    elif isinstance(space, colormanagement.DataColorSpace):
        kind = "DataColorSpace"
    elif isinstance(space, colormanagement.NormalColorSpace):
        kind = "NormalColorSpace"
    else:
        return {"unrepresented": repr(space)}
    return {"class": kind, "name": colour_space_name(space)}


def bitmap_colour_spaces(source: Any) -> dict[str, Any]:
    """`SourceBitmap.list_available_color_spaces` and `get_color_space` of a bitmap source."""
    if not isinstance(source, substance_painter.source.SourceBitmap):
        raise TypeError(f"the source is not a bitmap: {source_value(source)}")
    return {
        "available_color_spaces": [
            colour_space_value(space) for space in source.list_available_color_spaces()
        ],
        "color_space": colour_space_value(source.get_color_space()),
    }


def predefined_output_maps(params: dict[str, Any]) -> dict[str, Any]:
    """`PredefinedExportPreset.list_output_maps` on the named texture set's stack, by preset
    name with its URL: the one preset `preset` names, else every preset Painter lists. A preset
    whose call raises is recorded with what it raised."""
    presets = substance_painter.export.list_predefined_export_presets()
    if "preset" in params:
        presets = [p for p in presets if p.name == params["preset"]]
        if len(presets) != 1:
            raise ValueError(
                f"{len(presets)} predefined export presets are named {params['preset']!r}"
            )
    stack = substance_painter.textureset.Stack.from_name(params["texture_set"])
    maps: dict[str, Any] = {}
    for preset in presets:
        name = str(preset.name)
        if name in maps:
            raise ValueError(f"several predefined export presets are named {name!r}")
        entry: dict[str, Any] = {"url": json_value(preset.url)}
        try:
            entry["output_maps"] = json_value(preset.list_output_maps(stack))
        except Exception as error:
            entry["raised"] = raised_by(error)
        maps[name] = entry
    return maps


def resource_id_value(identifier: Any) -> Any:
    """A `resource.ResourceID`'s URL and documented fields."""
    return json_value(
        {
            "url": identifier.url(),
            "context": identifier.context,
            "name": identifier.name,
            "version": identifier.version,
        }
    )


def readback(args: dict[str, Any]) -> Any:
    """Read one documented getter; the host records the value (or the documented exception)."""
    call = args["call"]
    params = args.get("args", {})
    if call in (GET_SOURCE, GET_EFFECT_SOURCE):
        node = NODES[int(params["node_step"])]
        return source_value(node.get_source(channel_type(params["channel"])))
    if call == GET_LEVELS:
        node = NODES[int(params["node_step"])]
        return {
            "affected_channel": node.affected_channel.name,
            "parameters": levels_value(node.get_parameters()),
        }
    if call == GET_PROJECTION:
        return projection_value(NODES[int(params["node_step"])])
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
    if call == GET_MESH_MAP:
        usage = member(MESH_MAP_USAGES, "MeshMapUsage", params["usage"])
        maps: dict[str, Any] = {}
        for texture_set in texture_sets_of(params):
            identifier = texture_set.get_mesh_map_resource(usage)
            maps[texture_set.name()] = None if identifier is None else identifier.url()
        return maps
    if call == GET_GENERATOR_SOURCE:
        return substance_description(NODES[int(params["node_step"])].get_source())
    if call == GET_SUB_LAYERS:
        return node_structure(NODES[int(params["node_step"])])
    if call == GET_PROPERTY_VALUE:
        return {
            ts.name(): json_value(baking_parameter(ts, params).value())
            for ts in texture_sets_of(params)
        }
    if call == BAKING_ENABLED_BAKERS:
        return {ts.name(): enabled_bakers(ts) for ts in texture_sets_of(params)}
    if call == LIST_PREDEFINED_PRESETS:
        return [
            json_value({"name": preset.name, "url": preset.url})
            for preset in substance_painter.export.list_predefined_export_presets()
        ]
    if call == LIST_RESOURCE_PRESETS:
        return [
            {"resource_id": resource_id_value(preset.resource_id)}
            for preset in substance_painter.export.list_resource_export_presets()
        ]
    if call == PREDEFINED_OUTPUT_MAPS:
        return predefined_output_maps(params)
    if call == RESOURCE_OUTPUT_MAPS:
        identifier = substance_painter.resource.ResourceID.from_url(params["preset"])
        preset = substance_painter.export.ResourceExportPreset(identifier)
        return json_value(preset.list_output_maps())
    if call == LIST_COLOR_SPACES:
        node = NODES[int(params["node_step"])]
        return bitmap_colour_spaces(node.get_source(channel_type(params["channel"])))
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


def child_nodes(parent: Any, kind: str) -> list[Any]:
    """One documented child list of a node: group sub-layers, content or mask effects."""
    if kind == "sub_layers":
        return list(parent.sub_layers())
    if kind == "mask_effects":
        return list(parent.mask_effects())
    return list(parent.content_effects())


def node_path(node: Any) -> list[list[Any]]:
    """The node's place from its stack's root layers down: `[kind, index]` per level."""
    path: list[list[Any]] = []
    current = node
    parent = current.get_parent()
    while parent is not None:
        if current.is_in_mask_stack():
            kind = "mask_effects"
        elif isinstance(parent, substance_painter.layerstack.GroupLayerNode):
            kind = "sub_layers"
        else:
            kind = "content_effects"
        uids = [child.uid() for child in child_nodes(parent, kind)]
        path.append([kind, uids.index(current.uid())])
        current, parent = parent, parent.get_parent()
    roots = substance_painter.layerstack.get_root_layer_nodes(current.get_stack())
    path.append(["root", [root.uid() for root in roots].index(current.uid())])
    return list(reversed(path))


def node_locations(args: dict[str, Any]) -> dict[str, Any]:
    """Where each recorded node sits in its stack: root layer, group child or effect (stable
    across reopen)."""
    locations: dict[str, Any] = {}
    for step, node in sorted(NODES.items()):
        stack = node.get_stack()
        locations[str(step)] = {
            "texture_set": stack.material().name(),
            "stack": stack.name(),
            "path": node_path(node),
        }
    return locations


def rebind_nodes(args: dict[str, Any]) -> dict[str, Any]:
    """After reopening, find each recorded node again at its recorded location."""
    NODES.clear()
    for step, where in args["locations"].items():
        stack = substance_painter.textureset.Stack.from_name(where["texture_set"], where["stack"])
        roots = substance_painter.layerstack.get_root_layer_nodes(stack)
        (_root, index), *below = where["path"]
        node = roots[int(index)]
        for kind, position in below:
            node = child_nodes(node, kind)[int(position)]
        NODES[int(step)] = node
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


def list_textures(args: dict[str, Any]) -> dict[str, Any]:
    """The files `export_project_textures` would write for a configuration (documented dry run);
    an invalid configuration raises its documented `ValueError`, which the host records."""
    if not substance_painter.project.is_in_edition_state() or substance_painter.project.is_busy():
        raise RuntimeError("project not ready for export")
    listed = substance_painter.export.list_project_textures(args["config"])
    return {
        "textures": [
            {"texture_set": key[0], "stack": key[1], "files": list(files)}
            for key, files in sorted(listed.items())
        ]
    }


def save_as(args: dict[str, Any]) -> dict[str, Any]:
    substance_painter.project.save_as(args["path"], substance_painter.project.ProjectSaveMode.Full)
    return {"saved_at": time.time()}


def close_project(args: dict[str, Any]) -> dict[str, Any]:
    if substance_painter.project.is_open():
        substance_painter.project.close()
    NODES.clear()
    RESOURCES.clear()
    bake_disconnect()
    BAKE_STATE["queue"], BAKE_STATE["current"] = [], None
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


# resource.Usage members the Iray procedure probe imports (render_procedure, iray_probe.py).
PROBE_USAGES = {
    "TEXTURE": lambda: substance_painter.resource.Usage.TEXTURE,
    "COLOR_LUT": lambda: substance_painter.resource.Usage.COLOR_LUT,
}


def scene_bounding_box(args: dict[str, Any]) -> dict[str, Any]:
    """Scene-space bounding box of the open project (silhouette verification, 07 §2.2 step 5)."""
    box = substance_painter.project.get_scene_bounding_box()
    return {"center": list(box.center), "dimensions": list(box.dimensions), "radius": box.radius}


def import_resource(args: dict[str, Any]) -> dict[str, Any]:
    """Import an authored probe input into the project; returns its `resource://` URL."""
    usage = member(PROBE_USAGES, "Usage", args["usage"])
    resource = substance_painter.resource.import_project_resource(args["path"], usage)
    return {"url": resource.identifier().url(), "imported_at": time.time()}


def set_session_environment(args: dict[str, Any]) -> dict[str, Any]:
    """Import an environment file as a session resource and display it (the `ref_match`
    preset's procedure, decision 038); returns the readback URL."""
    resource = substance_painter.resource.import_session_resource(
        args["path"], substance_painter.resource.Usage.ENVIRONMENT
    )
    substance_painter.display.set_environment_resource(resource.identifier())
    current = substance_painter.display.get_environment_resource()
    return {"environment_url": None if current is None else current.url(), "done_at": time.time()}


def set_color_lut(args: dict[str, Any]) -> dict[str, Any]:
    """Set the colour-profile LUT; returns the readback and the time it was set."""
    lut = substance_painter.resource.ResourceID.from_url(args["url"])
    substance_painter.display.set_color_lut_resource(lut)
    current = substance_painter.display.get_color_lut_resource()
    return {"color_lut_url": None if current is None else current.url(), "done_at": time.time()}


def channel_names(args: dict[str, Any]) -> dict[str, str]:
    """The `.name` of each `ChannelType` member the vocabulary accepts, by member: legacy alias
    members (e.g. `Roughness`) report the name of the member they alias."""
    names: dict[str, str] = {}
    for key in CHANNEL_TYPES:
        try:
            names[key] = channel_type(key).name
        except AttributeError:
            continue
    return names


def show_texture_set(args: dict[str, Any]) -> str:
    """Make a texture set's stack the active one, so Painter's panels show it (the operator
    step of texture goldens, `texture_sheet.py`); returns the active texture set's name."""
    texture_set = substance_painter.textureset.TextureSet.from_name(args["texture_set"])
    substance_painter.textureset.set_active_stack(texture_set.get_stack())
    return str(substance_painter.textureset.get_active_stack().material().name())


def texture_set_names(args: dict[str, Any]) -> list[dict[str, str]]:
    """Each texture set's name and the name it had when the mesh was imported (the operator's
    rename in the Texture Set List, `texture_sheet.py`, decision 093). Painter 12.1.5 exposes
    the documented `TextureSet.original_name` as a string, not a method."""
    names = []
    for texture_set in substance_painter.textureset.all_texture_sets():
        original = texture_set.original_name
        names.append(
            {
                "name": str(texture_set.name()),
                "original_name": str(original() if callable(original) else original),
            }
        )
    return names


LAYER_KINDS = ("FillLayer", "PaintLayer", "GroupLayer", "InstanceLayer")


def read_or_raised(read: Any) -> Any:
    """`read()`, or what it raised (a getter the node does not support is itself observed)."""
    try:
        return read()
    except Exception as error:
        return {"raised": raised_by(error)}


def migration_node(node: Any, channels: list[Any]) -> dict[str, Any]:
    """One node of an opened project and everything below it (decision 194; private readback):
    name, type, uid and visibility; each source (a bitmap's resource URL carries its version);
    the blending and opacity of every channel of its stack (`mask` in a mask stack); whether a
    layer has a mask, enabled, and its background; then its sub-layers and effects."""
    kind = node.get_type().name
    in_mask = node.is_in_mask_stack()
    entry: dict[str, Any] = {
        "name": node.get_name(),
        "type": kind,
        "uid": node.uid(),
        "visible": node.is_visible(),
    }
    if kind in ("FillLayer", "FillEffect") and in_mask:
        source = read_or_raised(lambda: substance_description(node.get_source()))
        entry["sources"] = {"mask": source}
    elif kind in ("FillLayer", "FillEffect"):
        active = sorted(node.active_channels, key=lambda c: c.name)
        entry["active_channels"] = [channel.name for channel in active]
        entry["sources"] = {
            channel.name: read_or_raised(
                lambda channel=channel: substance_description(node.get_source(channel))
            )
            for channel in active
        }
    elif kind in ("GeneratorEffect", "FilterEffect"):
        entry["source"] = read_or_raised(lambda: substance_description(node.get_source()))
    if in_mask:
        entry["blending"] = {"mask": read_or_raised(lambda: blending_of(node, None))}
    else:
        entry["blending"] = {
            channel.name: read_or_raised(lambda channel=channel: blending_of(node, channel))
            for channel in channels
        }
    children: tuple[str, ...] = ("sub_layers",) if kind == "GroupLayer" else ()
    if kind in LAYER_KINDS:
        has_mask = node.has_mask()
        entry["mask"] = {"has_mask": has_mask}
        if has_mask:
            entry["mask"]["enabled"] = node.is_mask_enabled()
            entry["mask"]["background"] = read_or_raised(lambda: node.get_mask_background().name)
        children += ("content_effects", "mask_effects")
    for field in children:
        entry[field] = read_or_raised(
            lambda field=field: [migration_node(c, channels) for c in child_nodes(node, field)]
        )
    return entry


def migration_readback(args: dict[str, Any]) -> dict[str, Any]:
    """The state of the project opened for a migration golden (decision 194), read through the
    documented API only: the mesh it was last imported from, and per texture set its resolution,
    its mesh-map resources (URLs with versions) and, per stack, the channels' formats and every
    root layer node with everything below it."""
    sets: dict[str, Any] = {}
    for texture_set in substance_painter.textureset.all_texture_sets():
        resolution = texture_set.get_resolution()
        maps: dict[str, Any] = {}
        for usage_name, usage in sorted(MESH_MAP_USAGES.items()):
            maps[usage_name] = read_or_raised(
                lambda texture_set=texture_set, usage=usage: (
                    None
                    if (found := texture_set.get_mesh_map_resource(usage())) is None
                    else resource_id_value(found)
                )
            )
        stacks: dict[str, Any] = {}
        for stack in texture_set.all_stacks():
            all_channels = stack.all_channels()
            channels = sorted(all_channels, key=lambda c: c.name)
            roots = substance_painter.layerstack.get_root_layer_nodes(stack)
            stacks[stack.name()] = {
                "channels": {c.name: channel_description(all_channels[c]) for c in channels},
                "layers": [migration_node(root, channels) for root in roots],
            }
        sets[texture_set.name()] = {
            "resolution": [resolution.width, resolution.height],
            "mesh_maps": maps,
            "stacks": stacks,
        }
    return {
        "file_path": substance_painter.project.file_path(),
        "last_imported_mesh_path": substance_painter.project.last_imported_mesh_path(),
        "texture_sets": sets,
    }


def show_node(args: dict[str, Any]) -> dict[str, Any]:
    """Make the stack of a recorded node the active one; returns the node's name as the Layers
    panel lists it, and its texture set."""
    node = NODES[int(args["node_step"])]
    substance_painter.textureset.set_active_stack(node.get_stack())
    return {"name": node.get_name(), "texture_set": node.get_stack().material().name()}


OPERATIONS = {
    "hello": hello,
    "state": state,
    "apply_step": apply_step,
    "readback": readback,
    "template_capture": template_capture,
    "node_locations": node_locations,
    "rebind_nodes": rebind_nodes,
    "export_textures": export_textures,
    "list_textures": list_textures,
    "save_as": save_as,
    "close_project": close_project,
    "open_project": open_project,
    "render_state": render_state,
    "switch_mode": switch_mode,
    "channel_names": channel_names,
    "show_texture_set": show_texture_set,
    "show_node": show_node,
    "texture_set_names": texture_set_names,
    "shipped_templates": shipped_templates,
    "baking_capture": baking_capture,
    "baking_state": baking_state,
    "scene_bounding_box": scene_bounding_box,
    "import_resource": import_resource,
    "set_color_lut": set_color_lut,
    "set_session_environment": set_session_environment,
    "migration_readback": migration_readback,
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
