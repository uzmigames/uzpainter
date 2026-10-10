"""Tier 0 API probes run inside Adobe Substance 3D Painter 12.1.0 (`phase0.6_tier0-api-probes`).

The host (`tools.parity.recorder.probes`) executes this source into a copy of the private namespace
of `painter_side.py`, right after it: the probe operations below register into its `OPERATIONS`
(the same dictionary) and reuse its helpers, while the names defined here never replace
`painter_side.py`'s own. Every `substance_painter` symbol used here is listed in
`documented_symbols.json` and documented in Painter's public Python API documentation (approved
source A-PYDOC); `tests/parity/recorder/test_provenance.py` checks this file like the rest of the
recorder. No private attribute, no shipped Painter source and no community MCP bridge is used.

A probe step is one documented call. Its outcome is recorded whatever it is: the returned value,
described as JSON, or the exception Painter raised (class name and message). Node handles are
resolved freshly through `layerstack.get_node_by_uid` for every call.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import substance_painter.colormanagement
import substance_painter.event
import substance_painter.layerstack
import substance_painter.project
import substance_painter.resource
import substance_painter.source
import substance_painter.textureset

if TYPE_CHECKING:
    # At run time these names come from the copy of `painter_side.py`'s namespace.
    from tools.parity.recorder.painter_side import (
        BLENDING_MODES,
        OPERATIONS,
        channel_type,
        color_of,
        member,
        source_value,
    )

# Nodes inserted by probe steps, and resources imported by them, by step number.
PROBE_NODES: dict[int, Any] = {}
PROBE_RESOURCES: dict[int, Any] = {}

# Event log filled by the connected callbacks, and the callbacks kept alive (the documented
# dispatcher holds them weakly).
EVENT_LOG: list[dict[str, Any]] = []
CALLBACKS: dict[str, Any] = {}

# Layer stack edition (substance_painter.layerstack).
INSERT_FILL = "substance_painter.layerstack.insert_fill"
INSERT_GROUP = "substance_painter.layerstack.insert_group"
INSERT_LEVELS = "substance_painter.layerstack.insert_levels_effect"
INSERT_COMPARE_MASK = "substance_painter.layerstack.insert_compare_mask_effect"
INSERT_COLOR_SELECTION = "substance_painter.layerstack.insert_color_selection_effect"
SET_NAME = "substance_painter.layerstack.Node.set_name"
SET_VISIBLE = "substance_painter.layerstack.Node.set_visible"
SET_BLENDING_MODE = "substance_painter.layerstack.Node.set_blending_mode"
SET_OPACITY = "substance_painter.layerstack.Node.set_opacity"
ACTIVE_CHANNELS = "substance_painter.layerstack.FillLayerNode.active_channels"
SET_SOURCE = "substance_painter.layerstack.FillLayerNode.set_source"
SET_PROJECTION_MODE = "substance_painter.layerstack.FillLayerNode.set_projection_mode"
SET_PROJECTION_PARAMETERS = "substance_painter.layerstack.FillLayerNode.set_projection_parameters"
SET_BITMAP_COLOR_SPACE = "substance_painter.source.SourceBitmap.set_color_space"
ADD_MASK = "substance_painter.layerstack.LayerNode.add_mask"
ENABLE_MASK = "substance_painter.layerstack.LayerNode.enable_mask"
AFFECTED_CHANNEL = "substance_painter.layerstack.LevelsEffectNode.affected_channel"
SET_LEVELS = "substance_painter.layerstack.LevelsEffectNode.set_parameters"
IMPORT_RESOURCE = "substance_painter.resource.import_project_resource"
SET_RESOLUTIONS = "substance_painter.textureset.set_resolutions"
SET_MESH_MAP = "substance_painter.textureset.TextureSet.set_mesh_map_resource"

# Readbacks (always probes: executed again in every recording).
GET_NAME = "substance_painter.layerstack.Node.get_name"
IS_VISIBLE = "substance_painter.layerstack.Node.is_visible"
GET_BLENDING_MODE = "substance_painter.layerstack.Node.get_blending_mode"
GET_OPACITY = "substance_painter.layerstack.Node.get_opacity"
GET_TYPE = "substance_painter.layerstack.Node.get_type"
IS_IN_MASK_STACK = "substance_painter.layerstack.Node.is_in_mask_stack"
HAS_BLENDING = "substance_painter.layerstack.Node.has_blending"
SOURCE_MODE = "substance_painter.layerstack.FillLayerNode.source_mode"
GET_SOURCE = "substance_painter.layerstack.FillLayerNode.get_source"
GET_PROJECTION_MODE = "substance_painter.layerstack.FillLayerNode.get_projection_mode"
GET_PROJECTION_PARAMETERS = "substance_painter.layerstack.FillLayerNode.get_projection_parameters"
GET_BITMAP_COLOR_SPACE = "substance_painter.source.SourceBitmap.get_color_space"
LIST_BITMAP_COLOR_SPACES = "substance_painter.source.SourceBitmap.list_available_color_spaces"
HAS_MASK = "substance_painter.layerstack.LayerNode.has_mask"
GET_MASK_BACKGROUND = "substance_painter.layerstack.LayerNode.get_mask_background"
IS_MASK_ENABLED = "substance_painter.layerstack.LayerNode.is_mask_enabled"
MASK_EFFECTS = "substance_painter.layerstack.LayerNode.mask_effects"
CONTENT_EFFECTS = "substance_painter.layerstack.LayerNode.content_effects"
SUB_LAYERS = "substance_painter.layerstack.GroupLayerNode.sub_layers"
ROOT_LAYERS = "substance_painter.layerstack.get_root_layer_nodes"
GET_LEVELS = "substance_painter.layerstack.LevelsEffectNode.get_parameters"
GET_RESOLUTION = "substance_painter.textureset.TextureSet.get_resolution"
GET_MESH_MAP = "substance_painter.textureset.TextureSet.get_mesh_map_resource"
NEEDS_SAVING = "substance_painter.project.needs_saving"
FILE_PATH = "substance_painter.project.file_path"
PROJECT_NAME = "substance_painter.project.name"

# Lifecycle probe (event order, readiness transitions).
EVENT_CONNECT = "substance_painter.event.Dispatcher.connect"
PROJECT_SAVE_AS = "substance_painter.project.save_as"
PROJECT_SAVE = "substance_painter.project.save"
PROJECT_CLOSE = "substance_painter.project.close"
PROJECT_OPEN = "substance_painter.project.open"
PROJECT_STATE = "substance_painter.project.is_in_edition_state"
LIFECYCLE_CALLS = (EVENT_CONNECT, PROJECT_SAVE_AS, PROJECT_SAVE, PROJECT_CLOSE, PROJECT_OPEN)

# Calls the host replays as state steps (applied once) or, with `probe: true`, as probe steps.
EDIT_CALLS = (
    "substance_painter.layerstack.insert_fill",
    "substance_painter.layerstack.insert_group",
    "substance_painter.layerstack.insert_levels_effect",
    "substance_painter.layerstack.insert_compare_mask_effect",
    "substance_painter.layerstack.insert_color_selection_effect",
    "substance_painter.layerstack.Node.set_name",
    "substance_painter.layerstack.Node.set_visible",
    "substance_painter.layerstack.Node.set_blending_mode",
    "substance_painter.layerstack.Node.set_opacity",
    "substance_painter.layerstack.FillLayerNode.active_channels",
    "substance_painter.layerstack.FillLayerNode.set_source",
    "substance_painter.layerstack.FillLayerNode.set_projection_mode",
    "substance_painter.layerstack.FillLayerNode.set_projection_parameters",
    "substance_painter.source.SourceBitmap.set_color_space",
    "substance_painter.layerstack.LayerNode.add_mask",
    "substance_painter.layerstack.LayerNode.enable_mask",
    "substance_painter.layerstack.LevelsEffectNode.affected_channel",
    "substance_painter.layerstack.LevelsEffectNode.set_parameters",
    "substance_painter.resource.import_project_resource",
    "substance_painter.textureset.set_resolutions",
    "substance_painter.textureset.TextureSet.set_mesh_map_resource",
)

# Readback calls. `active_channels` and `affected_channel` read when no value is given.
GETTER_CALLS = (
    "substance_painter.layerstack.Node.get_name",
    "substance_painter.layerstack.Node.is_visible",
    "substance_painter.layerstack.Node.get_blending_mode",
    "substance_painter.layerstack.Node.get_opacity",
    "substance_painter.layerstack.Node.get_type",
    "substance_painter.layerstack.Node.is_in_mask_stack",
    "substance_painter.layerstack.Node.has_blending",
    "substance_painter.layerstack.FillLayerNode.source_mode",
    "substance_painter.layerstack.FillLayerNode.get_source",
    "substance_painter.layerstack.FillLayerNode.get_projection_mode",
    "substance_painter.layerstack.FillLayerNode.get_projection_parameters",
    "substance_painter.source.SourceBitmap.get_color_space",
    "substance_painter.source.SourceBitmap.list_available_color_spaces",
    "substance_painter.layerstack.LayerNode.has_mask",
    "substance_painter.layerstack.LayerNode.get_mask_background",
    "substance_painter.layerstack.LayerNode.is_mask_enabled",
    "substance_painter.layerstack.LayerNode.mask_effects",
    "substance_painter.layerstack.LayerNode.content_effects",
    "substance_painter.layerstack.GroupLayerNode.sub_layers",
    "substance_painter.layerstack.get_root_layer_nodes",
    "substance_painter.layerstack.LevelsEffectNode.get_parameters",
    "substance_painter.textureset.TextureSet.get_resolution",
    "substance_painter.textureset.TextureSet.get_mesh_map_resource",
    "substance_painter.project.needs_saving",
    "substance_painter.project.file_path",
    "substance_painter.project.name",
)

# Arguments that, when present, make `active_channels` / `affected_channel` an assignment.
VALUE_ARGS = {
    "substance_painter.layerstack.FillLayerNode.active_channels": "channels",
    "substance_painter.layerstack.LevelsEffectNode.affected_channel": "channel",
}

# Steps that create a node.
INSERT_CALLS = (
    "substance_painter.layerstack.insert_fill",
    "substance_painter.layerstack.insert_group",
    "substance_painter.layerstack.insert_levels_effect",
    "substance_painter.layerstack.insert_compare_mask_effect",
    "substance_painter.layerstack.insert_color_selection_effect",
)

# Documented enum members by name (see painter_side.py for why each member is spelled out).
# layerstack.NodeStack members.
NODE_STACKS = {
    "Substack": lambda: substance_painter.layerstack.NodeStack.Substack,
    "Content": lambda: substance_painter.layerstack.NodeStack.Content,
    "Mask": lambda: substance_painter.layerstack.NodeStack.Mask,
}

# layerstack.MaskBackground members.
MASK_BACKGROUNDS = {
    "Black": lambda: substance_painter.layerstack.MaskBackground.Black,
    "White": lambda: substance_painter.layerstack.MaskBackground.White,
}

# layerstack.ProjectionMode members.
PROJECTION_MODES = {
    "Fill": lambda: substance_painter.layerstack.ProjectionMode.Fill,
    "UV": lambda: substance_painter.layerstack.ProjectionMode.UV,
    "Triplanar": lambda: substance_painter.layerstack.ProjectionMode.Triplanar,
    "Planar": lambda: substance_painter.layerstack.ProjectionMode.Planar,
    "Spherical": lambda: substance_painter.layerstack.ProjectionMode.Spherical,
    "Cylindrical": lambda: substance_painter.layerstack.ProjectionMode.Cylindrical,
}

# layerstack.FilteringMode members.
FILTERING_MODES = {
    "BilinearHQ": lambda: substance_painter.layerstack.FilteringMode.BilinearHQ,
    "BilinearSharp": lambda: substance_painter.layerstack.FilteringMode.BilinearSharp,
    "Nearest": lambda: substance_painter.layerstack.FilteringMode.Nearest,
}

# layerstack.UVWrapMode members.
UV_WRAP_MODES = {
    "RepeatNone": lambda: substance_painter.layerstack.UVWrapMode.RepeatNone,
    "RepeatHorizontally": lambda: substance_painter.layerstack.UVWrapMode.RepeatHorizontally,
    "RepeatVertically": lambda: substance_painter.layerstack.UVWrapMode.RepeatVertically,
    "Repeat": lambda: substance_painter.layerstack.UVWrapMode.Repeat,
}

# layerstack.ScaleMode members.
SCALE_MODES = {
    "Factors": lambda: substance_painter.layerstack.ScaleMode.Factors,
    "MaterialPhysicalSize": lambda: substance_painter.layerstack.ScaleMode.MaterialPhysicalSize,
    "CustomPhysicalSize": lambda: substance_painter.layerstack.ScaleMode.CustomPhysicalSize,
}

# Colour spaces a bitmap source accepts (colormanagement Generic/Legacy/Data members).
BITMAP_COLOR_SPACES = {
    "GenericColorSpace.sRGB": lambda: substance_painter.colormanagement.GenericColorSpace.sRGB,
    "GenericColorSpace.Raw": lambda: substance_painter.colormanagement.GenericColorSpace.Raw,
    "LegacyColorSpace.sRGB": lambda: substance_painter.colormanagement.LegacyColorSpace.sRGB,
    "LegacyColorSpace.Linear": lambda: substance_painter.colormanagement.LegacyColorSpace.Linear,
    "DataColorSpace.Data": lambda: substance_painter.colormanagement.DataColorSpace.Data,
}

# resource.Usage members the probes import with.
RESOURCE_USAGES = {
    "TEXTURE": lambda: substance_painter.resource.Usage.TEXTURE,
}

# textureset.MeshMapUsage members.
MESH_MAP_USAGES = {
    "AO": lambda: substance_painter.textureset.MeshMapUsage.AO,
    "Curvature": lambda: substance_painter.textureset.MeshMapUsage.Curvature,
    "Normal": lambda: substance_painter.textureset.MeshMapUsage.Normal,
    "Height": lambda: substance_painter.textureset.MeshMapUsage.Height,
}

# Project lifecycle events of substance_painter.event the lifecycle probe listens to.
EVENT_CLASSES = {
    "ProjectOpened": lambda: substance_painter.event.ProjectOpened,
    "ProjectCreated": lambda: substance_painter.event.ProjectCreated,
    "ProjectAboutToClose": lambda: substance_painter.event.ProjectAboutToClose,
    "ProjectClosed": lambda: substance_painter.event.ProjectClosed,
    "ProjectAboutToSave": lambda: substance_painter.event.ProjectAboutToSave,
    "ProjectSaved": lambda: substance_painter.event.ProjectSaved,
    "ProjectEditionEntered": lambda: substance_painter.event.ProjectEditionEntered,
    "ProjectEditionLeft": lambda: substance_painter.event.ProjectEditionLeft,
    "BusyStatusChanged": lambda: substance_painter.event.BusyStatusChanged,
}


def raised(error: Exception) -> dict[str, str]:
    # repr(error) starts with the exception class name, e.g. "ValueError('...')".
    return {"type": repr(error).split("(", 1)[0], "message": str(error)}


def attempt(function: Callable[[], Any]) -> Any:
    """The described value of `function()`, or the exception it raised."""
    try:
        return describe(function())
    except Exception as error:
        return {"raised": raised(error)}


def class_name(value: Any) -> str:
    """Class name of a dataclass value, from its repr (`Name(field=...)`)."""
    return repr(value).split("(", 1)[0]


def describe(value: Any) -> Any:
    """A documented API value as JSON (enums by name, colours in working space)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, substance_painter.colormanagement.Color):
        return {"color_working": list(value.working)}
    if isinstance(value, substance_painter.resource.ResourceID):
        # Parts kept apart: the context names the open project instance, the version the content.
        return {
            "resource": {"context": value.context, "name": value.name, "version": value.version}
        }
    if isinstance(value, substance_painter.source.SourceBitmap):
        return {
            "bitmap": describe(value.resource_id),
            "color_space": attempt(value.get_color_space),
        }
    if isinstance(
        value,
        (substance_painter.source.SourceUniformColor, substance_painter.source.SourceSubstance),
    ):
        return source_value(value)
    if isinstance(value, substance_painter.layerstack.Node):
        return {"node_type": value.get_type().name, "name": value.get_name()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = dataclasses.asdict(value)
        return {"class": class_name(value), **{k: describe(v) for k, v in sorted(fields.items())}}
    if isinstance(value, dict):
        return {str(describe(k)): describe(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        items = [describe(v) for v in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [describe(v) for v in value]
    if hasattr(value, "name") and isinstance(value.name, str):
        return value.name  # an enumeration member that is not an `enum.Enum`
    return {"unrecognised": class_name(value)[:80]}


def resolve(uid: int) -> Any:
    """A freshly resolved node handle (documented: `get_node_by_uid` gives the node)."""
    resolved = substance_painter.layerstack.get_node_by_uid(uid)
    if isinstance(resolved, (list, tuple)):
        if len(resolved) != 1:
            raise RuntimeError(f"get_node_by_uid({uid}) returned {len(resolved)} nodes")
        return resolved[0]
    return resolved


def fresh(step: Any) -> Any:
    return resolve(PROBE_NODES[int(step)].uid())


def channel_arg(args: dict[str, Any]) -> Any:
    """The `channel` argument: a ChannelType, or None (mask and mono-channel contexts)."""
    name = args.get("channel")
    return None if name is None else channel_type(name)


def insert_position(args: dict[str, Any]) -> Any:
    layerstack = substance_painter.layerstack
    if "above_step" in args:
        return layerstack.InsertPosition.above_node(fresh(args["above_step"]))
    if "below_step" in args:
        return layerstack.InsertPosition.below_node(fresh(args["below_step"]))
    if "inside_step" in args:
        stack = member(NODE_STACKS, "NodeStack", args["node_stack"])
        return layerstack.InsertPosition.inside_node(fresh(args["inside_step"]), stack)
    if args.get("position", "top") != "top":
        raise ValueError(f"unsupported insert position {args['position']!r}")
    active = substance_painter.textureset.get_active_stack()
    return layerstack.InsertPosition.from_textureset_stack(active)


def is_fill(node: Any) -> bool:
    return isinstance(
        node,
        (substance_painter.layerstack.FillLayerNode, substance_painter.layerstack.FillEffectNode),
    )


def blending_defaults(node: Any) -> Any:
    if not node.has_blending():
        return None
    if node.is_in_mask_stack():
        return {
            "mask": {
                "blending_mode": attempt(lambda: node.get_blending_mode(None)),
                "opacity": attempt(lambda: node.get_opacity(None)),
            }
        }
    kinds = sorted(node.get_stack().all_channels(), key=lambda c: c.name)
    return {kind.name: channel_blending(node, kind) for kind in kinds}


def channel_blending(node: Any, kind: Any) -> dict[str, Any]:
    return {
        "blending_mode": attempt(lambda: node.get_blending_mode(kind)),
        "opacity": attempt(lambda: node.get_opacity(kind)),
    }


def node_defaults(node: Any) -> dict[str, Any]:
    """Effective defaults of a freshly inserted node, read before any step edits it."""
    values: dict[str, Any] = {
        "node_type": node.get_type().name,
        "name": node.get_name(),
        "visible": node.is_visible(),
        "in_mask_stack": node.is_in_mask_stack(),
        "has_blending": node.has_blending(),
        "blending": blending_defaults(node),
    }
    if is_fill(node):
        values["source_mode"] = attempt(lambda: node.source_mode)
        values["active_channels"] = attempt(lambda: node.active_channels)
        values["projection_mode"] = attempt(node.get_projection_mode)
        values["projection_parameters"] = attempt(node.get_projection_parameters)
        if node.source_mode is None:
            values["source"] = attempt(lambda: node.get_source(None))
    if isinstance(node, substance_painter.layerstack.LayerNode):
        values["has_mask"] = node.has_mask()
    if isinstance(node, substance_painter.layerstack.LevelsEffectNode):
        values["affected_channel"] = attempt(lambda: node.affected_channel)
        values["levels"] = attempt(node.get_parameters)
    return values


def child_lists(parent: Any) -> list[tuple[str, list[Any]]]:
    lists: list[tuple[str, list[Any]]] = []
    if isinstance(parent, substance_painter.layerstack.GroupLayerNode):
        lists.append(("Substack", list(parent.sub_layers())))
    if isinstance(parent, substance_painter.layerstack.LayerNode):
        lists.append(("Content", list(parent.content_effects())))
        lists.append(("Mask", list(parent.mask_effects())))
    return lists


def find_path(nodes: list[Any], uid: int, kind: str) -> list[list[Any]] | None:
    """Path from `nodes` (a stack of kind `kind`) down to the node with `uid`, or None."""
    for index, node in enumerate(nodes):
        if node.uid() == uid:
            return [[kind, index]]
        for child_kind, children in child_lists(node):
            below = find_path(children, uid, child_kind)
            if below is not None:
                return [[kind, index], *below]
    return None


def location(node: Any) -> dict[str, Any]:
    """Where a node sits: root index, then (stack kind, index) down to the node."""
    stack = node.get_stack()
    roots = list(substance_painter.layerstack.get_root_layer_nodes(stack))
    path = find_path(roots, node.uid(), "Root")
    if path is None:
        raise RuntimeError(f"node {node.uid()} is not in its stack's tree")
    return {
        "texture_set": stack.material().name(),
        "stack": stack.name(),
        "path": path,
        "uid": node.uid(),
    }


def node_at(where: dict[str, Any]) -> Any:
    stack = substance_painter.textureset.Stack.from_name(where["texture_set"], where["stack"])
    node = None
    for kind, index in where["path"]:
        if kind == "Root":
            node = list(substance_painter.layerstack.get_root_layer_nodes(stack))[int(index)]
            continue
        for name, children in child_lists(node):
            if name == kind:
                node = children[int(index)]
                break
        else:
            raise RuntimeError(f"no {kind} children at {where['path']}")
    return node


def tree(node: Any) -> dict[str, Any]:
    """Structure of a node and everything under it (types, names, visibility)."""
    entry: dict[str, Any] = {
        "node_type": node.get_type().name,
        "name": node.get_name(),
        "visible": node.is_visible(),
    }
    if isinstance(node, substance_painter.layerstack.LayerNode):
        entry["has_mask"] = node.has_mask()
    for kind, children in child_lists(node):
        entry[kind] = [tree(child) for child in children]
    return entry


def uv_projection(args: dict[str, Any]) -> Any:
    layerstack = substance_painter.layerstack
    return layerstack.UVProjectionParams(
        filtering_mode=member(FILTERING_MODES, "FilteringMode", args["filtering_mode"]),
        uv_wrapping_mode=member(UV_WRAP_MODES, "UVWrapMode", args["uv_wrapping_mode"]),
        uv_transformation=layerstack.UVTransformationParams(
            scale_mode=member(SCALE_MODES, "ScaleMode", args["scale_mode"]),
            scale=[float(v) for v in args["scale"]],
            rotation=float(args["rotation"]),
            offset=[float(v) for v in args["offset"]],
        ),
    )


LEVELS_FIELDS = ("input_min", "input_max", "gamma", "output_min", "output_max", "clamp")


def set_levels(node: Any, args: dict[str, Any]) -> None:
    changes = {name: args[name] for name in LEVELS_FIELDS if name in args}
    node.set_parameters(dataclasses.replace(node.get_parameters(), **changes))


def project_file(value: Any) -> Any:
    """`project.file_path()` without the private work directory: only the file name."""
    return {"is_none": True} if value is None else {"file_name": os.path.basename(value)}


def edit(step: int, call: str, args: dict[str, Any], resolved: dict[str, Any]) -> Any:
    """Apply one edit call; returns what the documented call returned."""
    layerstack = substance_painter.layerstack
    if call == INSERT_FILL:
        return layerstack.insert_fill(insert_position(args))
    if call == INSERT_GROUP:
        return layerstack.insert_group(insert_position(args))
    if call == INSERT_LEVELS:
        return layerstack.insert_levels_effect(insert_position(args))
    if call == INSERT_COMPARE_MASK:
        return layerstack.insert_compare_mask_effect(insert_position(args))
    if call == INSERT_COLOR_SELECTION:
        return layerstack.insert_color_selection_effect(insert_position(args))
    if call == IMPORT_RESOURCE:
        usage = member(RESOURCE_USAGES, "Usage", args["usage"])
        resource = substance_painter.resource.import_project_resource(resolved["image"], usage)
        PROBE_RESOURCES[step] = resource.identifier()
        return resource.identifier()
    if call == SET_RESOLUTIONS:
        resolution = substance_painter.textureset.Resolution(
            int(args["width"]), int(args["height"])
        )
        texture_sets = substance_painter.textureset.all_texture_sets()
        return substance_painter.textureset.set_resolutions(texture_sets, resolution)
    if call == SET_MESH_MAP:
        texture_set = substance_painter.textureset.get_active_stack().material()
        usage = member(MESH_MAP_USAGES, "MeshMapUsage", args["usage"])
        return texture_set.set_mesh_map_resource(usage, PROBE_RESOURCES[int(args["resource_step"])])
    node = fresh(args["node_step"])
    if call == SET_NAME:
        return node.set_name(str(args["name"]))
    if call == SET_VISIBLE:
        return node.set_visible(bool(args["visible"]))
    if call == SET_BLENDING_MODE:
        mode = member(BLENDING_MODES, "BlendingMode", args["blending_mode"])
        return node.set_blending_mode(mode, channel_arg(args))
    if call == SET_OPACITY:
        return node.set_opacity(float(args["opacity"]), channel_arg(args))
    if call == ACTIVE_CHANNELS:
        node.active_channels = {channel_type(c) for c in args["channels"]}
        return None
    if call == SET_SOURCE:
        if "resource_step" in args:
            source = PROBE_RESOURCES[int(args["resource_step"])]
        else:
            source = color_of(args["color"], args.get("color_space"))
        return node.set_source(channel_arg(args), source)
    if call == SET_PROJECTION_MODE:
        mode = member(PROJECTION_MODES, "ProjectionMode", args["projection_mode"])
        return node.set_projection_mode(mode)
    if call == SET_PROJECTION_PARAMETERS:
        return node.set_projection_parameters(uv_projection(args))
    if call == SET_BITMAP_COLOR_SPACE:
        space = member(BITMAP_COLOR_SPACES, "color space", args["color_space"])
        return node.get_source(channel_arg(args)).set_color_space(space)
    if call == ADD_MASK:
        return node.add_mask(member(MASK_BACKGROUNDS, "MaskBackground", args["background"]))
    if call == ENABLE_MASK:
        return node.enable_mask(bool(args["enabled"]))
    if call == AFFECTED_CHANNEL:
        node.affected_channel = channel_type(args["channel"])
        return None
    if call == SET_LEVELS:
        set_levels(node, args)
        return None
    raise ValueError(f"call {call!r} is not in the probe vocabulary")


def read(call: str, args: dict[str, Any]) -> Any:
    """Evaluate one readback call; returns the raw documented value."""
    if call == ROOT_LAYERS:
        stack = substance_painter.textureset.get_active_stack()
        return [tree(node) for node in substance_painter.layerstack.get_root_layer_nodes(stack)]
    if call == GET_RESOLUTION:
        resolution = substance_painter.textureset.get_active_stack().material().get_resolution()
        return [resolution.width, resolution.height]
    if call == GET_MESH_MAP:
        texture_set = substance_painter.textureset.get_active_stack().material()
        return texture_set.get_mesh_map_resource(
            member(MESH_MAP_USAGES, "MeshMapUsage", args["usage"])
        )
    if call == NEEDS_SAVING:
        return substance_painter.project.needs_saving()
    if call == FILE_PATH:
        return project_file(substance_painter.project.file_path())
    if call == PROJECT_NAME:
        return substance_painter.project.name()
    node = fresh(args["node_step"])
    if call == GET_NAME:
        return node.get_name()
    if call == IS_VISIBLE:
        return node.is_visible()
    if call == GET_BLENDING_MODE:
        return node.get_blending_mode(channel_arg(args))
    if call == GET_OPACITY:
        return node.get_opacity(channel_arg(args))
    if call == GET_TYPE:
        return node.get_type()
    if call == IS_IN_MASK_STACK:
        return node.is_in_mask_stack()
    if call == HAS_BLENDING:
        return node.has_blending()
    if call == ACTIVE_CHANNELS:
        return node.active_channels
    if call == SOURCE_MODE:
        return node.source_mode
    if call == GET_SOURCE:
        return node.get_source(channel_arg(args))
    if call == GET_PROJECTION_MODE:
        return node.get_projection_mode()
    if call == GET_PROJECTION_PARAMETERS:
        return node.get_projection_parameters()
    if call == GET_BITMAP_COLOR_SPACE:
        return node.get_source(channel_arg(args)).get_color_space()
    if call == LIST_BITMAP_COLOR_SPACES:
        return node.get_source(channel_arg(args)).list_available_color_spaces()
    if call == HAS_MASK:
        return node.has_mask()
    if call == GET_MASK_BACKGROUND:
        return node.get_mask_background()
    if call == IS_MASK_ENABLED:
        return node.is_mask_enabled()
    if call == MASK_EFFECTS:
        return [tree(effect) for effect in node.mask_effects()]
    if call == CONTENT_EFFECTS:
        return [tree(effect) for effect in node.content_effects()]
    if call == SUB_LAYERS:
        return [tree(layer) for layer in node.sub_layers()]
    if call == AFFECTED_CHANNEL:
        return node.affected_channel
    if call == GET_LEVELS:
        return node.get_parameters()
    raise ValueError(f"readback {call!r} is not in the probe vocabulary")


def is_read(call: str, args: dict[str, Any]) -> bool:
    if call in VALUE_ARGS:
        return VALUE_ARGS[call] not in args
    return call in GETTER_CALLS


def probe_step(args: dict[str, Any]) -> dict[str, Any]:
    """Run one probe or state step; the outcome is recorded whether it returns or raises."""
    step = int(args["step"])
    call = args["call"]
    params = args.get("args", {})
    outcome: dict[str, Any] = {}
    try:
        if is_read(call, params):
            outcome["value"] = describe(read(call, params))
        else:
            value = edit(step, call, params, args.get("resolved", {}))
            outcome["value"] = describe(value)
            if call in INSERT_CALLS:
                PROBE_NODES[step] = value
                outcome["defaults"] = node_defaults(value)
    except Exception as error:
        outcome["value"] = None
        outcome["raised"] = raised(error)
    return outcome


def probe_locations(args: dict[str, Any]) -> dict[str, Any]:
    """Location and uid of every node the probe inserted (stable across save and reopen)."""
    return {str(step): location(fresh(step)) for step in sorted(PROBE_NODES)}


def optional(function: Callable[[], Any]) -> Any:
    """`function()`, or None when it raises (a node that cannot be found)."""
    try:
        return function()
    except Exception:
        return None


def find_again(where: dict[str, Any]) -> tuple[Any, Any]:
    """The node at a recorded location, and the node its recorded uid resolves to."""
    return optional(lambda: node_at(where)), optional(lambda: resolve(int(where["uid"])))


def probe_rebind(args: dict[str, Any]) -> dict[str, Any]:
    """After reopening, find each inserted node again.

    A node is taken at its recorded location when that location holds it, or when its recorded
    uid no longer resolves; otherwise by its recorded uid. A node found neither way is missing
    (the reopened project no longer has it); probes on it then record the error.
    """
    PROBE_NODES.clear()
    found: dict[str, str] = {}
    for step, where in args["locations"].items():
        by_place, by_uid = find_again(where)
        if by_place is not None and (by_uid is None or by_place.uid() == by_uid.uid()):
            PROBE_NODES[int(step)] = by_place
            found[step] = "location"
        elif by_uid is not None:
            PROBE_NODES[int(step)] = by_uid
            found[step] = "uid"
        else:
            found[step] = "missing"
    return {"found_by": found}


def probe_identity(args: dict[str, Any]) -> dict[str, Any]:
    """Whether a node is present, keeps its uid, and whether that uid resolves to the node."""
    step = int(args["node_step"])
    if step not in PROBE_NODES:
        return {"present": False}
    node = PROBE_NODES[step]
    same = node.uid() == int(args["recorded_uid"])
    try:
        resolves = resolve(node.uid()).uid() == node.uid()
    except Exception as error:
        return {"present": True, "uid_same_as_recorded": same, "resolves": raised(error)}
    return {"present": True, "uid_same_as_recorded": same, "uid_resolves_to_node": resolves}


def probe_reset(args: dict[str, Any]) -> dict[str, Any]:
    PROBE_NODES.clear()
    PROBE_RESOURCES.clear()
    return {"reset": True}


def project_state() -> dict[str, Any]:
    project = substance_painter.project
    return {
        "is_open": attempt(project.is_open),
        "in_edition": attempt(project.is_in_edition_state),
        "busy": attempt(project.is_busy),
    }


def event_callback(name: str) -> Callable[[Any], None]:
    def callback(event: Any) -> None:
        entry: dict[str, Any] = {"event": name, **project_state()}
        if name == "BusyStatusChanged":
            entry["busy_argument"] = event.busy
        if name == "ProjectAboutToSave":
            entry["file_path_argument"] = project_file(event.file_path)
        EVENT_LOG.append(entry)

    return callback


def events_connect(args: dict[str, Any]) -> dict[str, Any]:
    EVENT_LOG.clear()
    for name in args["events"]:
        if name in CALLBACKS:
            continue
        callback = event_callback(name)
        substance_painter.event.DISPATCHER.connect(member(EVENT_CLASSES, "event", name), callback)
        CALLBACKS[name] = callback
    return {"connected": sorted(CALLBACKS)}


def events_take(args: dict[str, Any]) -> dict[str, Any]:
    """The events dispatched since the last call, in dispatch order; clears the log."""
    taken = list(EVENT_LOG)
    EVENT_LOG.clear()
    return {"events": taken}


def events_disconnect(args: dict[str, Any]) -> dict[str, Any]:
    for name, callback in CALLBACKS.items():
        substance_painter.event.DISPATCHER.disconnect(
            member(EVENT_CLASSES, "event", name), callback
        )
    CALLBACKS.clear()
    EVENT_LOG.clear()
    return {"disconnected": True}


def project_save(args: dict[str, Any]) -> dict[str, Any]:
    substance_painter.project.save(substance_painter.project.ProjectSaveMode.Full)
    return {"saved_at": time.time()}


PROBE_OPERATIONS = {
    "probe_step": probe_step,
    "probe_locations": probe_locations,
    "probe_rebind": probe_rebind,
    "probe_identity": probe_identity,
    "probe_reset": probe_reset,
    "events_connect": events_connect,
    "events_take": events_take,
    "events_disconnect": events_disconnect,
    "project_save": project_save,
}

for operation_name, operation in PROBE_OPERATIONS.items():
    OPERATIONS[operation_name] = operation
