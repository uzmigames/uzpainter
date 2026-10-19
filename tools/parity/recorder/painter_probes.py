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
import datetime
import enum
import importlib
import json
import os
import sys
import threading
import time
import uuid
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Any

import substance_painter.application
import substance_painter.colormanagement
import substance_painter.display
import substance_painter.event
import substance_painter.export
import substance_painter.js
import substance_painter.layerstack
import substance_painter.levels
import substance_painter.logging
import substance_painter.project
import substance_painter.resource
import substance_painter.source
import substance_painter.textureset
import substance_painter.ui
import substance_painter_plugins

if TYPE_CHECKING:
    # At run time these names come from the copy of `painter_side.py`'s namespace.
    from tools.parity.recorder.painter_side import (
        BLENDING_MODES,
        CHANNEL_FORMATS,
        OPERATIONS,
        TONE_MAPPINGS,
        UI_MODES,
        channel_type,
        color_of,
        create_project,
        levels_field,
        member,
        scene_bounding_box,
        set_camera,
        source_value,
    )

# Nodes inserted by probe steps, and resources imported by them, by step number.
PROBE_NODES: dict[int, Any] = {}
PROBE_RESOURCES: dict[int, Any] = {}
# The imported `Resource` objects (`update_layer_stack_resource` takes one), and the uid of every
# inserted node a `delete_node` step removed (with the node itself or with its parent).
PROBE_RESOURCE_HANDLES: dict[int, Any] = {}
DELETED_UIDS: dict[int, int] = {}

# Asynchronous calls still waiting for their callback (or, for a resource reload, for the
# documented `is_reload_modified_resources_running()` to turn false), by name; the callbacks
# handed to Painter, kept alive; the step running now (events note it when dispatched during
# the call); whether a probe disabled the engine computations (restored by `probe_finish`).
CALLBACK_STATE: dict[str, bool] = {}
RESOURCE_RELOADS: dict[str, bool] = {}
HELD_CALLBACKS: list[Any] = []
CURRENT: dict[str, Any] = {"step": None}
ENGINE: dict[str, bool] = {"disabled_by_probe": False}

# Event log filled by the connected callbacks, and the callbacks kept alive (the documented
# dispatcher holds them weakly).
EVENT_LOG: list[dict[str, Any]] = []
CALLBACKS: dict[str, Any] = {}

# The run's private directory (paths under it are recorded relative to it); the shelves a probe
# added, by name with the folder that identifies them (removed again once the project is closed,
# as `Shelves.remove` requires; kept until their removal is confirmed, SUP-016/017); the pending
# keys of a shelf crawl (shelf name) and of a project being opened (P21-D, P21-G; decision 110).
ROOT: dict[str, Any] = {"dir": None}
SHELVES_ADDED: dict[str, str] = {}
SHELF_CRAWLS: dict[str, str] = {}
OPENING: dict[str, bool] = {}
CLOSED: dict[str, Any] = {"path": None}

# Lifecycle timing (P21-F, decision 109): readiness polled by a second thread from the start of a
# `create` or `open` until `ProjectEditionEntered` is dispatched.
TIMING: dict[str, Any] = {"polls": [], "count": 0, "running": False, "entered_ms": None}
TIMING_PERIOD_S = 0.001
TIMING_LIMIT_S = 600.0

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
DELETE_NODE = "substance_painter.layerstack.delete_node"
UPDATE_RESOURCE = "substance_painter.resource.update_layer_stack_resource"

# Project, resource and engine operations (`phase1.22` R10 probes); asynchronous ones complete
# through a callback or an event, which the host waits for (`probe_state`).
PROJECT_SAVE_AS_COPY = "substance_painter.project.save_as_copy"
RELOAD_MESH = "substance_painter.project.reload_mesh"
EXECUTE_WHEN_NOT_BUSY = "substance_painter.project.execute_when_not_busy"
RELOAD_RESOURCES = "substance_painter.resource.reload_modified_resources_async"
ENABLE_ENGINE = "substance_painter.application.enable_engine_computations"
DISABLE_ENGINE = "substance_painter.application.disable_engine_computations"

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
GET_UID = "substance_painter.layerstack.Node.uid"
GET_NODE_BY_UID = "substance_painter.layerstack.get_node_by_uid"
ALL_TEXTURE_SETS = "substance_painter.textureset.all_texture_sets"
IS_BUSY = "substance_painter.project.is_busy"
ENGINE_STATUS = "substance_painter.application.engine_computations_status"
IS_RELOADING_RESOURCES = "substance_painter.resource.is_reload_modified_resources_running"

# Lifecycle probe (event order, readiness transitions).
EVENT_CONNECT = "substance_painter.event.Dispatcher.connect"
PROJECT_SAVE_AS = "substance_painter.project.save_as"
PROJECT_SAVE = "substance_painter.project.save"
PROJECT_CLOSE = "substance_painter.project.close"
PROJECT_OPEN = "substance_painter.project.open"
PROJECT_STATE = "substance_painter.project.is_in_edition_state"
LIFECYCLE_CALLS = (EVENT_CONNECT, PROJECT_SAVE_AS, PROJECT_SAVE, PROJECT_CLOSE, PROJECT_OPEN)

# Host behaviour probes (decisions 109, 110, 132; R-095 P7): layer-stack edits, shelves, display
# and camera, default paths and resource search.
INSERT_PAINT = "substance_painter.layerstack.insert_paint"
INSERT_ANCHOR_POINT = "substance_painter.layerstack.insert_anchor_point_effect"
REMOVE_MASK = "substance_painter.layerstack.LayerNode.remove_mask"
SET_MASK_BACKGROUND = "substance_painter.layerstack.LayerNode.set_mask_background"
RESET_SOURCE = "substance_painter.layerstack.FillLayerNode.reset_source"
SET_UNIFORM_COLOR = "substance_painter.source.SourceUniformColor.set_color"
RESET_BITMAP_COLOR_SPACE = "substance_painter.source.SourceBitmap.reset_color_space"
SET_SYMMETRY = "substance_painter.layerstack.FillLayerNode.set_symmetry_enabled"
SHELVES_ADD = "substance_painter.resource.Shelves.add"
SHELF_REFRESH = "substance_painter.resource.Shelf.refresh"
SET_DISPLAY_ENVIRONMENT = "substance_painter.display.set_environment_resource"
SET_DISPLAY_COLOR_LUT = "substance_painter.display.set_color_lut_resource"
SET_DISPLAY_TONE_MAPPING = "substance_painter.display.set_tone_mapping"
CAMERA_PROPERTY = "substance_painter.display.Camera."
DEFAULT_CAMERA = "substance_painter.display.Camera.get_default_camera"
GET_DISPLAY_ENVIRONMENT = "substance_painter.display.get_environment_resource"
GET_DISPLAY_COLOR_LUT = "substance_painter.display.get_color_lut_resource"
GET_DISPLAY_TONE_MAPPING = "substance_painter.display.get_tone_mapping"
SCENE_BOUNDING_BOX = "substance_painter.project.get_scene_bounding_box"
DEFAULT_EXPORT_PATH = "substance_painter.export.get_default_export_path"
THROTTLING_PERIOD = (
    "substance_painter.event.TextureStateEvent.cache_key_invalidation_throttling_period"
)
SHELVES_ALL = "substance_painter.resource.Shelves.all"
APPLICATION_SHELF = "substance_painter.resource.Shelves.application_shelf"
USER_SHELF = "substance_painter.resource.Shelves.user_shelf"
SHELVES_EXISTS = "substance_painter.resource.Shelves.exists"
SHELF_IS_CRAWLING = "substance_painter.resource.Shelf.is_crawling"
RESOURCE_SEARCH = "substance_painter.resource.search"

# P22-B layer stack, levels and colour probes (phase1.24 item 3.4, decision 296): navigation,
# selection, scoped modifications, group collapse, fill-effect sources and symmetry, material
# sources, instances, filter and generator effects, explicit levels parameters, `Color.sRGB` and
# `Color.value`.
SET_COLLAPSED = "substance_painter.layerstack.GroupLayerNode.set_collapsed"
IS_COLLAPSED = "substance_painter.layerstack.GroupLayerNode.is_collapsed"
EFFECT_RESET_SOURCE = "substance_painter.layerstack.FillEffectNode.reset_source"
EFFECT_SET_SYMMETRY = "substance_painter.layerstack.FillEffectNode.set_symmetry_enabled"
LAYER_IS_SYMMETRY = "substance_painter.layerstack.FillLayerNode.is_symmetry_enabled"
EFFECT_IS_SYMMETRY = "substance_painter.layerstack.FillEffectNode.is_symmetry_enabled"
LAYER_MATERIAL_SOURCE = "substance_painter.layerstack.FillLayerNode.get_material_source"
EFFECT_MATERIAL_SOURCE = "substance_painter.layerstack.FillEffectNode.get_material_source"
INSTANTIATE = "substance_painter.layerstack.instantiate"
INSERT_FILTER_EFFECT = "substance_painter.layerstack.insert_filter_effect"
INSERT_GENERATOR_EFFECT = "substance_painter.layerstack.insert_generator_effect"
INSTANCE_SOURCE = "substance_painter.layerstack.InstanceLayerNode.instance_source"
INSTANCES = "substance_painter.layerstack.LayerNode.instances"
GET_PARENT = "substance_painter.layerstack.Node.get_parent"
NEXT_SIBLING = "substance_painter.layerstack.Node.get_next_sibling"
PREVIOUS_SIBLING = "substance_painter.layerstack.Node.get_previous_sibling"
GET_TEXTURE_SET = "substance_painter.layerstack.Node.get_texture_set"
IS_EFFECT_NODE = "substance_painter.layerstack.EffectNode"
GET_SELECTED = "substance_painter.layerstack.get_selected_nodes"
SET_SELECTED = "substance_painter.layerstack.set_selected_nodes"
GET_SELECTION_TYPE = "substance_painter.layerstack.get_selection_type"
SET_SELECTION_TYPE = "substance_painter.layerstack.set_selection_type"
SCOPED_MODIFICATION = "substance_painter.layerstack.ScopedModification"
LEVELS_MONO = "substance_painter.levels.LevelsParamsMono"
LEVELS_RGB = "substance_painter.levels.LevelsParamsRGB"
COLOR_SRGB = "substance_painter.colormanagement.Color.sRGB"
COLOR_VALUE = "substance_painter.colormanagement.Color.value"

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
    "substance_painter.layerstack.delete_node",
    "substance_painter.resource.update_layer_stack_resource",
    "substance_painter.event.Dispatcher.connect",
    "substance_painter.project.save_as",
    "substance_painter.project.save_as_copy",
    "substance_painter.project.save",
    "substance_painter.project.reload_mesh",
    "substance_painter.project.execute_when_not_busy",
    "substance_painter.resource.reload_modified_resources_async",
    "substance_painter.application.enable_engine_computations",
    "substance_painter.application.disable_engine_computations",
    "substance_painter.layerstack.insert_paint",
    "substance_painter.layerstack.insert_anchor_point_effect",
    "substance_painter.layerstack.LayerNode.remove_mask",
    "substance_painter.layerstack.LayerNode.set_mask_background",
    "substance_painter.layerstack.FillLayerNode.reset_source",
    "substance_painter.source.SourceUniformColor.set_color",
    "substance_painter.source.SourceBitmap.reset_color_space",
    "substance_painter.layerstack.FillLayerNode.set_symmetry_enabled",
    "substance_painter.resource.Shelves.add",
    "substance_painter.resource.Shelf.refresh",
    "substance_painter.display.set_environment_resource",
    "substance_painter.display.set_color_lut_resource",
    "substance_painter.display.set_tone_mapping",
    "substance_painter.project.close",
    "substance_painter.project.open",
    # P22-B layer stack, levels and colour (decision 296).
    "substance_painter.layerstack.GroupLayerNode.set_collapsed",
    "substance_painter.layerstack.FillEffectNode.reset_source",
    "substance_painter.layerstack.FillEffectNode.set_symmetry_enabled",
    "substance_painter.layerstack.instantiate",
    "substance_painter.layerstack.insert_filter_effect",
    "substance_painter.layerstack.insert_generator_effect",
    "substance_painter.layerstack.set_selected_nodes",
    "substance_painter.layerstack.set_selection_type",
    "substance_painter.layerstack.ScopedModification",
    "substance_painter.levels.LevelsParamsMono",
    "substance_painter.levels.LevelsParamsRGB",
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
    "substance_painter.layerstack.Node.uid",
    "substance_painter.layerstack.get_node_by_uid",
    "substance_painter.textureset.all_texture_sets",
    "substance_painter.project.is_busy",
    "substance_painter.application.engine_computations_status",
    "substance_painter.resource.is_reload_modified_resources_running",
    "substance_painter.display.Camera.get_default_camera",
    "substance_painter.display.Camera.projection_type",
    "substance_painter.display.Camera.position",
    "substance_painter.display.Camera.rotation",
    "substance_painter.display.Camera.field_of_view",
    "substance_painter.display.Camera.focal_length",
    "substance_painter.display.Camera.focus_distance",
    "substance_painter.display.Camera.aperture",
    "substance_painter.display.Camera.orthographic_height",
    "substance_painter.display.get_environment_resource",
    "substance_painter.display.get_color_lut_resource",
    "substance_painter.display.get_tone_mapping",
    "substance_painter.project.get_scene_bounding_box",
    "substance_painter.export.get_default_export_path",
    "substance_painter.event.TextureStateEvent.cache_key_invalidation_throttling_period",
    "substance_painter.resource.Shelves.all",
    "substance_painter.resource.Shelves.application_shelf",
    "substance_painter.resource.Shelves.user_shelf",
    "substance_painter.resource.Shelves.exists",
    "substance_painter.resource.Shelf.is_crawling",
    "substance_painter.resource.search",
    # P22-B layer stack, levels and colour (decision 296).
    "substance_painter.layerstack.GroupLayerNode.is_collapsed",
    "substance_painter.layerstack.FillLayerNode.is_symmetry_enabled",
    "substance_painter.layerstack.FillEffectNode.is_symmetry_enabled",
    "substance_painter.layerstack.FillLayerNode.get_material_source",
    "substance_painter.layerstack.FillEffectNode.get_material_source",
    "substance_painter.layerstack.InstanceLayerNode.instance_source",
    "substance_painter.layerstack.LayerNode.instances",
    "substance_painter.layerstack.Node.get_parent",
    "substance_painter.layerstack.Node.get_next_sibling",
    "substance_painter.layerstack.Node.get_previous_sibling",
    "substance_painter.layerstack.Node.get_texture_set",
    "substance_painter.layerstack.EffectNode",
    "substance_painter.layerstack.get_selected_nodes",
    "substance_painter.layerstack.get_selection_type",
    "substance_painter.colormanagement.Color.sRGB",
    "substance_painter.colormanagement.Color.value",
)

# Arguments that, when present, make `active_channels`, `affected_channel` or a camera property
# an assignment.
VALUE_ARGS = {
    "substance_painter.layerstack.FillLayerNode.active_channels": "channels",
    "substance_painter.layerstack.LevelsEffectNode.affected_channel": "channel",
    "substance_painter.display.Camera.projection_type": "value",
    "substance_painter.display.Camera.position": "value",
    "substance_painter.display.Camera.rotation": "value",
    "substance_painter.display.Camera.field_of_view": "value",
    "substance_painter.display.Camera.focal_length": "value",
    "substance_painter.display.Camera.focus_distance": "value",
    "substance_painter.display.Camera.aperture": "value",
    "substance_painter.display.Camera.orthographic_height": "value",
    # P22-B (decision 296): `Color.sRGB` reads, or with `value` assigns.
    "substance_painter.colormanagement.Color.sRGB": "value",
}

# Steps that create a node.
INSERT_CALLS = (
    "substance_painter.layerstack.insert_fill",
    "substance_painter.layerstack.insert_group",
    "substance_painter.layerstack.insert_levels_effect",
    "substance_painter.layerstack.insert_compare_mask_effect",
    "substance_painter.layerstack.insert_color_selection_effect",
    "substance_painter.layerstack.insert_paint",
    "substance_painter.layerstack.insert_anchor_point_effect",
    # P22-B layer stack (decision 296).
    "substance_painter.layerstack.instantiate",
    "substance_painter.layerstack.insert_filter_effect",
    "substance_painter.layerstack.insert_generator_effect",
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
    "ENVIRONMENT": lambda: substance_painter.resource.Usage.ENVIRONMENT,
    # Host-module probes (decision 297).
    "COLOR_LUT": lambda: substance_painter.resource.Usage.COLOR_LUT,
    "GENERATOR": lambda: substance_painter.resource.Usage.GENERATOR,
    "SMART_MATERIAL": lambda: substance_painter.resource.Usage.SMART_MATERIAL,
}

# textureset.MeshMapUsage members.
MESH_MAP_USAGES = {
    "AO": lambda: substance_painter.textureset.MeshMapUsage.AO,
    "Curvature": lambda: substance_painter.textureset.MeshMapUsage.Curvature,
    "Normal": lambda: substance_painter.textureset.MeshMapUsage.Normal,
    "Height": lambda: substance_painter.textureset.MeshMapUsage.Height,
    "BentNormals": lambda: substance_painter.textureset.MeshMapUsage.BentNormals,
    "ID": lambda: substance_painter.textureset.MeshMapUsage.ID,
    "Opacity": lambda: substance_painter.textureset.MeshMapUsage.Opacity,
    "Position": lambda: substance_painter.textureset.MeshMapUsage.Position,
    "Thickness": lambda: substance_painter.textureset.MeshMapUsage.Thickness,
    "WorldSpaceNormal": lambda: substance_painter.textureset.MeshMapUsage.WorldSpaceNormal,
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
    "EngineComputationsStatusChanged": lambda: (
        substance_painter.event.EngineComputationsStatusChanged
    ),
    "ReloadResourcesStarted": lambda: substance_painter.event.ReloadResourcesStarted,
    "ReloadResourcesEnded": lambda: substance_painter.event.ReloadResourcesEnded,
    "ExportTexturesAboutToStart": lambda: substance_painter.event.ExportTexturesAboutToStart,
    "ExportTexturesEnded": lambda: substance_painter.event.ExportTexturesEnded,
    "LayerStacksModelDataChanged": lambda: substance_painter.event.LayerStacksModelDataChanged,
    "ShelfCrawlingStarted": lambda: substance_painter.event.ShelfCrawlingStarted,
    "ShelfCrawlingEnded": lambda: substance_painter.event.ShelfCrawlingEnded,
    "CameraPropertiesChanged": lambda: substance_painter.event.CameraPropertiesChanged,
}

# project.ProjectSaveMode members.
SAVE_MODES = {
    "Full": lambda: substance_painter.project.ProjectSaveMode.Full,
    "Incremental": lambda: substance_painter.project.ProjectSaveMode.Incremental,
}

# Reload filters of resource.reload_modified_resources_async (ResourcesListFilter takes the
# resources imported by `resource_steps`).
RESOURCE_FILTERS = {
    "AllResourcesFilter": lambda: substance_painter.resource.AllResourcesFilter,
    "ProjectFilter": lambda: substance_painter.resource.ProjectFilter,
    "ResourcesListFilter": lambda: substance_painter.resource.ResourcesListFilter,
    "ResourcesUsedByProjectFilter": lambda: substance_painter.resource.ResourcesUsedByProjectFilter,
    "SessionFilter": lambda: substance_painter.resource.SessionFilter,
    # Host-module probes (decision 297): takes the shelves named by `shelves`.
    "ShelvesListFilter": lambda: substance_painter.resource.ShelvesListFilter,
}

# layerstack.SelectionType members (P22-B, decision 296).
SELECTION_TYPES = {
    "Content": lambda: substance_painter.layerstack.SelectionType.Content,
    "Mask": lambda: substance_painter.layerstack.SelectionType.Mask,
    "GeometryMask": lambda: substance_painter.layerstack.SelectionType.GeometryMask,
    "Properties": lambda: substance_painter.layerstack.SelectionType.Properties,
}

# --- Host-module probes (decision 297; phase1.24 item 3.4, P22-B) ---------------------------
# application, logging, js and ui; event (strong connections, the base class, texture-state
# events and their throttling period); resource (project resources, resource ids, shelves,
# reload filters); substance_painter_plugins on throwaway modules the host writes in the run's
# private directory. Every name of this block is listed in HOST_EDIT_CALLS or HOST_GETTER_CALLS.
APPLICATION_VERSION = "substance_painter.application.version"
APPLICATION_VERSION_INFO = "substance_painter.application.version_info"
LOG_INFO = "substance_painter.logging.info"
LOG_WARNING = "substance_painter.logging.warning"
LOG_ERROR = "substance_painter.logging.error"
LOG = "substance_painter.logging.log"
JS_EVALUATE = "substance_painter.js.evaluate"
UI_CURRENT_MODE = "substance_painter.ui.get_current_mode"
UI_SWITCH_MODE = "substance_painter.ui.switch_to_mode"
EVENT_CONNECT_STRONG = "substance_painter.event.Dispatcher.connect_strong"
SET_THROTTLING_PERIOD = (
    "substance_painter.event.TextureStateEvent.set_cache_key_invalidation_throttling_period"
)
LIST_PROJECT_RESOURCES = "substance_painter.resource.list_project_resources"
RESOURCE_FROM_PROJECT = "substance_painter.resource.ResourceID.from_project"
RESOURCE_FROM_URL = "substance_painter.resource.ResourceID.from_url"
SHELVES_REFRESH_ALL = "substance_painter.resource.Shelves.refresh_all"
SHELVES_REMOVE = "substance_painter.resource.Shelves.remove"
PLUGINS_PATH = "substance_painter_plugins.path"
PLUGINS_UPDATE_SYS_PATH = "substance_painter_plugins.update_sys_path"
PLUGIN_MODULE_NAMES = "substance_painter_plugins.plugin_module_names"
STARTUP_MODULE_NAMES = "substance_painter_plugins.startup_module_names"
START_PLUGIN = "substance_painter_plugins.start_plugin"
CLOSE_PLUGIN = "substance_painter_plugins.close_plugin"
RELOAD_PLUGIN = "substance_painter_plugins.reload_plugin"
IS_PLUGIN_STARTED = "substance_painter_plugins.is_plugin_started"
STARTED_PLUGINS = "substance_painter_plugins.plugins"

HOST_EDIT_CALLS = (
    "substance_painter.logging.info",
    "substance_painter.logging.warning",
    "substance_painter.logging.error",
    "substance_painter.logging.log",
    "substance_painter.ui.switch_to_mode",
    "substance_painter.event.Dispatcher.connect_strong",
    "substance_painter.event.TextureStateEvent.set_cache_key_invalidation_throttling_period",
    "substance_painter.resource.Shelves.refresh_all",
    "substance_painter.resource.Shelves.remove",
    "substance_painter_plugins.path",
    "substance_painter_plugins.update_sys_path",
    "substance_painter_plugins.start_plugin",
    "substance_painter_plugins.close_plugin",
    "substance_painter_plugins.reload_plugin",
)
HOST_GETTER_CALLS = (
    "substance_painter.application.version",
    "substance_painter.application.version_info",
    "substance_painter.logging.INFO",
    "substance_painter.logging.WARNING",
    "substance_painter.logging.ERROR",
    "substance_painter.logging.DBG_INFO",
    "substance_painter.logging.DBG_WARNING",
    "substance_painter.logging.DBG_ERROR",
    "substance_painter.js.evaluate",
    "substance_painter.ui.get_current_mode",
    "substance_painter.resource.list_project_resources",
    "substance_painter.resource.ResourceID.from_project",
    "substance_painter.resource.ResourceID.from_url",
    "substance_painter_plugins.path",
    "substance_painter_plugins.plugin_module_names",
    "substance_painter_plugins.startup_module_names",
    "substance_painter_plugins.is_plugin_started",
    "substance_painter_plugins.plugins",
)
# `plugins.path` with `folder` appends the probe's plugin root; without it, reads.
HOST_VALUE_ARGS = {"substance_painter_plugins.path": "folder"}

# logging severities, each read back or passed to `log` by name.
LOG_SEVERITIES = {
    "INFO": lambda: substance_painter.logging.INFO,
    "WARNING": lambda: substance_painter.logging.WARNING,
    "ERROR": lambda: substance_painter.logging.ERROR,
    "DBG_INFO": lambda: substance_painter.logging.DBG_INFO,
    "DBG_WARNING": lambda: substance_painter.logging.DBG_WARNING,
    "DBG_ERROR": lambda: substance_painter.logging.DBG_ERROR,
}
# Event classes a strong connection may name besides EVENT_CLASSES.
HOST_EVENT_CLASSES = {
    "Event": lambda: substance_painter.event.Event,
    "TextureStateEvent": lambda: substance_painter.event.TextureStateEvent,
}
# The throwaway plugin modules (the host writes them; RECORDER.md 9) and the file of their plugin
# root their hooks append to (its path is written into each module: SUP-028).
PROBE_PLUGIN_MODULES = ("uzp_probe_plugin", "uzp_probe_startup")
# The folder of the plugin root each probe module is written in (its only accepted origin).
PROBE_PLUGIN_FOLDERS = {"uzp_probe_plugin": "plugins", "uzp_probe_startup": "startup"}
PLUGIN_HOOK_LOG_FILE = "hooks.log"
NEWLINE = chr(10)


class ProbeGuardError(Exception):
    """A guard refusing a host change the run cannot own or undo (SUP-016, SUP-017): a shelf or
    module of the probe's name it did not make, a module that would import from elsewhere, an old
    value it could not read. Never the outcome of a probe step: it aborts the recording."""


def normal_path(value: Any) -> str:
    return os.path.normcase(os.path.normpath(str(value)))


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
    if isinstance(value, substance_painter.resource.Shelf):
        return {"shelf": value.name(), "path": attempt(lambda: run_path(value.path()))}
    if isinstance(value, substance_painter.resource.Resource):
        return {
            "identifier": describe(value.identifier()),
            "gui_name": attempt(value.gui_name),
            "usages": attempt(value.usages),
        }
    if isinstance(value, datetime.timedelta):
        return {"timedelta_ms": value / datetime.timedelta(milliseconds=1)}
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


def run_path(value: Any) -> Any:
    """A path Painter returned: its parts relative to the run's private directory when it lies
    under it (the default save and export folders a probe set), else as Painter gave it."""
    if value is None:
        return None
    path = os.path.normpath(str(value))
    root = ROOT["dir"]
    if root is not None:
        base = os.path.normpath(str(root))
        if os.path.normcase(os.path.commonpath([path, base])) == os.path.normcase(base):
            return {"run_relative": os.path.relpath(path, base).split(os.sep)}
    return {"path": str(value)}


def camera_property(name: str) -> Any:
    """One documented property of the default camera (decision 132, R-132-A and B)."""
    camera = substance_painter.display.Camera.get_default_camera()
    if name == "projection_type":
        return camera.projection_type
    if name == "position":
        return list(camera.position)
    if name == "rotation":
        return list(camera.rotation)
    if name == "field_of_view":
        return camera.field_of_view
    if name == "focal_length":
        return camera.focal_length
    if name == "focus_distance":
        return camera.focus_distance
    if name == "aperture":
        return camera.aperture
    if name == "orthographic_height":
        return camera.orthographic_height
    raise ValueError(f"unsupported camera property {name!r}")


CAMERA_FIELDS = (
    "projection_type",
    "position",
    "rotation",
    "field_of_view",
    "focal_length",
    "focus_distance",
    "aperture",
    "orthographic_height",
)


def camera_record() -> dict[str, Any]:
    """Every documented property of the default camera, each read or the error it raised."""
    return {name: attempt(partial(camera_property, name)) for name in CAMERA_FIELDS}


def shelf_named(name: str) -> Any:
    """The shelf of that name among `Shelves.all()` (a shelf is identified by its name)."""
    for shelf in substance_painter.resource.Shelves.all():
        if shelf.name() == name:
            return shelf
    raise ValueError(f"no shelf named {name!r}")


def owned_shelf(name: str) -> Any:
    """The shelf this run added under that name, identified by its name and folder, or None once
    it is gone; a shelf of that name the run did not add is refused (SUP-016)."""
    if name not in SHELVES_ADDED:
        raise ProbeGuardError(f"shelf {name!r} was not added by this probe run")
    for shelf in substance_painter.resource.Shelves.all():
        if shelf.name() == name:
            if normal_path(shelf.path()) != SHELVES_ADDED[name]:
                raise ProbeGuardError(f"shelf {name!r} is not the one this probe run added")
            return shelf
    return None


def owned_shelf_named(name: str) -> Any:
    shelf = owned_shelf(name)
    if shelf is None:
        raise ValueError(f"no shelf named {name!r}")
    return shelf


def remove_shelf(name: str) -> Any:
    """`Shelves.remove` of a shelf this run added; once it is gone the call still goes to Painter
    (its answer for a removed name is the evidence), but never for a shelf it did not add."""
    owned_shelf(name)
    return substance_painter.resource.Shelves.remove(name)


def shelf_crawling(name: str) -> bool:
    return bool(shelf_named(name).is_crawling())


def watch_shelf(step: int, name: str) -> None:
    """A crawl of the shelf stays pending while `Shelf.is_crawling()` is true."""
    key = f"s{step}/shelf/{name}"
    SHELF_CRAWLS[key] = name
    CALLBACK_STATE[key] = True


def add_shelf(step: int, args: dict[str, Any], resolved: dict[str, Any]) -> Any:
    name = str(args["name"])
    if substance_painter.resource.Shelves.exists(name):
        raise ProbeGuardError(f"a shelf named {name!r} exists already; the probe never adds it")
    shelf = substance_painter.resource.Shelves.add(name, resolved["shelf_path"])
    SHELVES_ADDED[name] = normal_path(resolved["shelf_path"])
    watch_shelf(step, name)
    return shelf


def close_project_probe() -> Any:
    """`project.close`, keeping the file it had for a later `project.open` step (P21-G)."""
    CLOSED["path"] = substance_painter.project.file_path()
    return substance_painter.project.close()


def open_project_probe(step: int, resolved: dict[str, Any]) -> Any:
    """`project.open` of a work file, or of the file the last `project.close` step closed;
    pending until the project is in edition and not busy (the host then finds the inserted nodes
    again)."""
    path = resolved.get("work_file", CLOSED["path"])
    if path is None:
        raise ValueError("no work file and no closed project file to open")
    returned = substance_painter.project.open(path)
    key = f"s{step}/open"
    OPENING[key] = True
    CALLBACK_STATE[key] = True
    return returned


def texture_files(textures: Any) -> dict[str, list[str]]:
    """Exported textures by `texture set/stack`, as file names (no private directory)."""
    return {
        f"{key[0]}/{key[1]}": sorted(os.path.basename(name) for name in files)
        for key, files in sorted(textures.items())
    }


def node_uid(step: int) -> int:
    """Uid of an inserted node, or the uid it had when a `delete_node` step removed it."""
    if step in PROBE_NODES:
        return int(PROBE_NODES[step].uid())
    return DELETED_UIDS[step]


def resolves(uid: int) -> bool:
    return optional(lambda: resolve(uid)) is not None


def delete_node(step: int) -> Any:
    """Delete a node; every inserted node whose uid no longer resolves (the node, and the nodes
    it held) leaves the probe's nodes and keeps its last uid for `get_node_by_uid` probes."""
    uids = {other: int(node.uid()) for other, node in PROBE_NODES.items()}
    returned = substance_painter.layerstack.delete_node(fresh(step))
    for other, uid in sorted(uids.items()):
        if not resolves(uid):
            DELETED_UIDS[other] = uid
            del PROBE_NODES[other]
    return returned


def save_project(call: str, args: dict[str, Any], resolved: dict[str, Any]) -> Any:
    project = substance_painter.project
    mode = member(SAVE_MODES, "ProjectSaveMode", args["mode"])
    if call == PROJECT_SAVE:
        return project.save(mode)
    if call == PROJECT_SAVE_AS:
        return project.save_as(resolved["work_file"], mode)
    return project.save_as_copy(resolved["work_file"], mode)


def callback_entry(name: str, step: int) -> dict[str, Any]:
    """An event-log entry for a callback Painter called (logged like a dispatched event)."""
    entry: dict[str, Any] = {"event": name, "callback_of_step": step, **project_state()}
    if CURRENT["step"] is not None:
        entry["during_step"] = CURRENT["step"]
    return entry


def call_async(key: str, function: Callable[[], Any], callback: Callable[..., None]) -> Any:
    """Run a documented call that answers through `callback`; `key` stays pending until then."""
    HELD_CALLBACKS.append(callback)
    CALLBACK_STATE[key] = True
    try:
        return function()
    except Exception:
        del CALLBACK_STATE[key]
        raise


def reload_mesh(step: int, args: dict[str, Any], resolved: dict[str, Any]) -> Any:
    """`project.reload_mesh` of a staged mesh (`mesh`) or of a missing work file (`work_file`)."""
    path = resolved["mesh"] if "mesh" in resolved else resolved["work_file"]
    settings = substance_painter.project.MeshReloadingSettings(
        import_cameras=bool(args.get("import_cameras", True)),
        preserve_strokes=bool(args.get("preserve_strokes", True)),
    )
    key = f"s{step}/reload_mesh"

    def loading_status_cb(status: Any) -> None:
        entry = callback_entry("reload_mesh.loading_status_cb", step)
        entry["status"] = describe(status)
        EVENT_LOG.append(entry)
        CALLBACK_STATE[key] = False

    return call_async(
        key,
        lambda: substance_painter.project.reload_mesh(path, settings, loading_status_cb),
        loading_status_cb,
    )


def execute_when_not_busy(step: int) -> Any:
    key = f"s{step}/execute_when_not_busy"

    def callback() -> None:
        EVENT_LOG.append(callback_entry("execute_when_not_busy.callback", step))
        CALLBACK_STATE[key] = False

    return call_async(
        key, lambda: substance_painter.project.execute_when_not_busy(callback), callback
    )


def resource_filter(args: dict[str, Any]) -> Any:
    kind = member(RESOURCE_FILTERS, "reload filter", args["filter"])
    if args["filter"] == "ResourcesListFilter":
        return kind([PROBE_RESOURCES[int(step)] for step in args["resource_steps"]])
    if args["filter"] == "ShelvesListFilter":  # decision 297
        return kind([owned_shelf_named(str(name)) for name in args["shelves"]])
    return kind()


def filter_name(value: Any) -> Any:
    for name in RESOURCE_FILTERS:
        if isinstance(value, member(RESOURCE_FILTERS, "reload filter", name)):
            return name
    return {"unrecognised": class_name(value)[:80]}


def reload_resources(step: int, args: dict[str, Any]) -> dict[str, Any]:
    """`reload_modified_resources_async`: what it returned, and whether a reload runs right after.

    A started reload stays pending until `is_reload_modified_resources_running()` turns false."""
    started = substance_painter.resource.reload_modified_resources_async(resource_filter(args))
    if started:
        key = f"s{step}/reload_modified_resources_async"
        CALLBACK_STATE[key] = True
        RESOURCE_RELOADS[key] = True
    return {
        "returned": started,
        "running_after_call": substance_painter.resource.is_reload_modified_resources_running(),
    }


def enable_engine(args: dict[str, Any]) -> Any:
    enable = bool(args["enable"])
    returned = substance_painter.application.enable_engine_computations(enable)
    ENGINE["disabled_by_probe"] = not enable
    return returned


def engine_disabled(args: dict[str, Any]) -> dict[str, Any]:
    """`disable_engine_computations()` is a context manager: the readbacks (and the optional
    `set_source` on `node_step`) run inside it, within this one call."""
    application = substance_painter.application
    with application.disable_engine_computations():
        inside: dict[str, Any] = {
            "engine_computations": application.engine_computations_status(),
            "busy": substance_painter.project.is_busy(),
        }
        if "node_step" in args:
            node = fresh(args["node_step"])
            source = color_of(args["color"], args.get("color_space"))
            inside["set_source"] = attempt(lambda: node.set_source(channel_arg(args), source))
    return {"inside": inside, "engine_computations_after": application.engine_computations_status()}


# P22-B layer stack, levels and colour (phase1.24 item 3.4, decision 296) -------------------------

# Every call the P22-B block below answers, edit or readback.
P22B_CALLS = frozenset(
    {
        SET_COLLAPSED,
        IS_COLLAPSED,
        EFFECT_RESET_SOURCE,
        EFFECT_SET_SYMMETRY,
        LAYER_IS_SYMMETRY,
        EFFECT_IS_SYMMETRY,
        LAYER_MATERIAL_SOURCE,
        EFFECT_MATERIAL_SOURCE,
        INSTANTIATE,
        INSERT_FILTER_EFFECT,
        INSERT_GENERATOR_EFFECT,
        INSTANCE_SOURCE,
        INSTANCES,
        GET_PARENT,
        NEXT_SIBLING,
        PREVIOUS_SIBLING,
        GET_TEXTURE_SET,
        IS_EFFECT_NODE,
        GET_SELECTED,
        SET_SELECTED,
        GET_SELECTION_TYPE,
        SET_SELECTION_TYPE,
        SCOPED_MODIFICATION,
        LEVELS_MONO,
        LEVELS_RGB,
        COLOR_SRGB,
        COLOR_VALUE,
    }
)


def searched_resource(query: str) -> Any:
    """The first resource the documented search finds (a starter-asset filter or generator,
    named exactly by the query, as `effect-order` finds its Blur filter)."""
    found = substance_painter.resource.search(query)
    if not found:
        raise ValueError(f"no resource matches {query!r}")
    return found[0].identifier()


def triple(value: Any) -> tuple[float, float, float]:
    r, g, b = (float(component) for component in value)
    return (r, g, b)


def levels_params(call: str, args: dict[str, Any]) -> Any:
    """Levels parameters built with every documented field the step gives (all six)."""
    if call == LEVELS_RGB:
        return substance_painter.levels.LevelsParamsRGB(
            input_min=triple(args["input_min"]),
            input_max=triple(args["input_max"]),
            gamma=triple(args["gamma"]),
            output_min=triple(args["output_min"]),
            output_max=triple(args["output_max"]),
            clamp=bool(args["clamp"]),
        )
    return substance_painter.levels.LevelsParamsMono(
        input_min=float(args["input_min"]),
        input_max=float(args["input_max"]),
        gamma=float(args["gamma"]),
        output_min=float(args["output_min"]),
        output_max=float(args["output_max"]),
        clamp=bool(args["clamp"]),
    )


def levels_record(params: Any) -> dict[str, Any]:
    """Levels parameters read field by field, with the documented class they are."""
    if isinstance(params, substance_painter.levels.LevelsParamsRGB):
        kind = "LevelsParamsRGB"
    elif isinstance(params, substance_painter.levels.LevelsParamsMono):
        kind = "LevelsParamsMono"
    else:
        kind = class_name(params)
    return {
        "class": kind,
        "input_min": levels_field(params.input_min),
        "input_max": levels_field(params.input_max),
        "gamma": levels_field(params.gamma),
        "output_min": levels_field(params.output_min),
        "output_max": levels_field(params.output_max),
        "clamp": params.clamp,
    }


def step_color(args: dict[str, Any]) -> Any:
    """The colour a step names: the uniform colour source of `node_step` on `channel` (as
    `SourceUniformColor.get_color` returns it), or one built from `color` and `color_space`
    (no colour space when the step gives none)."""
    if "node_step" in args:
        return fresh(args["node_step"]).get_source(channel_arg(args)).get_color()
    return color_of(args["color"], args.get("color_space"))


def set_srgb(args: dict[str, Any]) -> Any:
    """`Color.sRGB = value`: on the colour of a uniform source, then set back on that source with
    `SourceUniformColor.set_color`; or on a built colour, whose conversions are returned."""
    value = triple(args["value"])
    if "node_step" in args:
        source = fresh(args["node_step"]).get_source(channel_arg(args))
        color = source.get_color()
        color.sRGB = value
        return source.set_color(color)
    built = color_of(args["color"], args.get("color_space"))
    built.sRGB = value
    return {
        "sRGB": attempt(lambda: list(built.sRGB)),
        "working": attempt(lambda: list(built.working)),
        "value_raw": list(built.value_raw),
        "color_space": describe(built.color_space),
    }


def scoped_modification(args: dict[str, Any]) -> dict[str, Any]:
    """A `ScopedModification` holding a rename and an opacity edit of `node_step`, and the
    selection calls its documentation says raise inside it; each inner outcome is recorded."""
    layerstack = substance_painter.layerstack
    node = fresh(args["node_step"])
    channel = channel_arg(args)
    inside: dict[str, Any] = {}
    with layerstack.ScopedModification(str(args["name"])):
        inside["set_name"] = attempt(partial(node.set_name, str(args["new_name"])))
        inside["set_opacity"] = attempt(partial(node.set_opacity, float(args["opacity"]), channel))
        inside["set_selected_nodes"] = attempt(partial(layerstack.set_selected_nodes, [node]))
        content = member(SELECTION_TYPES, "SelectionType", "Content")
        inside["set_selection_type"] = attempt(
            partial(layerstack.set_selection_type, node, content)
        )
        inside["get_name"] = attempt(node.get_name)
    return {"inside": inside, "get_name_after": attempt(fresh(args["node_step"]).get_name)}


def p22b_edit(call: str, args: dict[str, Any]) -> Any:
    """One P22-B edit call; returns what the documented call returned."""
    layerstack = substance_painter.layerstack
    if call == INSTANTIATE:
        return layerstack.instantiate(insert_position(args), fresh(args["layer_step"]))
    if call == INSERT_FILTER_EFFECT:
        found = searched_resource(str(args["search"]))
        return layerstack.insert_filter_effect(insert_position(args), found)
    if call == INSERT_GENERATOR_EFFECT:
        found = searched_resource(str(args["search"]))
        return layerstack.insert_generator_effect(insert_position(args), found)
    if call == SET_SELECTED:
        return layerstack.set_selected_nodes([fresh(step) for step in args["node_steps"]])
    if call == SCOPED_MODIFICATION:
        return scoped_modification(args)
    if call == COLOR_SRGB:
        return set_srgb(args)
    node = fresh(args["node_step"])
    if call == SET_COLLAPSED:
        return node.set_collapsed(bool(args["collapsed"]))
    if call == EFFECT_RESET_SOURCE:
        return node.reset_source(channel_arg(args))
    if call == EFFECT_SET_SYMMETRY:
        return node.set_symmetry_enabled(bool(args["enabled"]))
    if call == SET_SELECTION_TYPE:
        kind = member(SELECTION_TYPES, "SelectionType", args["selection_type"])
        return layerstack.set_selection_type(node, kind)
    if call in (LEVELS_MONO, LEVELS_RGB):
        node.set_parameters(levels_params(call, args))
        return levels_record(node.get_parameters())
    raise ValueError(f"call {call!r} is not in the probe vocabulary")


def p22b_read(call: str, args: dict[str, Any]) -> Any:
    """One P22-B readback; returns the raw documented value."""
    layerstack = substance_painter.layerstack
    if call == GET_SELECTED:
        return layerstack.get_selected_nodes(substance_painter.textureset.get_active_stack())
    if call == COLOR_SRGB:
        return list(step_color(args).sRGB)
    if call == COLOR_VALUE:
        return list(step_color(args).value)
    node = fresh(args["node_step"])
    if call == IS_COLLAPSED:
        return node.is_collapsed()
    if call in (LAYER_IS_SYMMETRY, EFFECT_IS_SYMMETRY):
        return node.is_symmetry_enabled()
    if call in (LAYER_MATERIAL_SOURCE, EFFECT_MATERIAL_SOURCE):
        return node.get_material_source()
    if call == INSTANCE_SOURCE:
        return node.instance_source()
    if call == INSTANCES:
        return node.instances()
    if call == GET_PARENT:
        return node.get_parent()
    if call == NEXT_SIBLING:
        return node.get_next_sibling()
    if call == PREVIOUS_SIBLING:
        return node.get_previous_sibling()
    if call == GET_TEXTURE_SET:
        return node.get_texture_set().name()
    if call == IS_EFFECT_NODE:
        # The documented alias of the effect node classes, as an `isinstance` check takes it.
        return isinstance(node, layerstack.EffectNode)
    if call == GET_SELECTION_TYPE:
        return layerstack.get_selection_type(node)
    raise ValueError(f"readback {call!r} is not in the probe vocabulary")


def edit(step: int, call: str, args: dict[str, Any], resolved: dict[str, Any]) -> Any:
    """Apply one edit call; returns what the documented call returned."""
    if call in P295_EDIT_CALLS or call in P295_VALUE_ARGS:
        return p295_edit(call, args)
    if call in HOST_EDIT_CALLS:  # decision 297
        return host_edit(step, call, args, resolved)
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
        PROBE_RESOURCE_HANDLES[step] = resource
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
    if call == UPDATE_RESOURCE:
        old = PROBE_RESOURCES[int(args["resource_step"])]
        new = PROBE_RESOURCE_HANDLES[int(args["new_resource_step"])]
        return substance_painter.resource.update_layer_stack_resource(old, new)
    if call == EVENT_CONNECT:
        return events_connect(args)
    if call in (PROJECT_SAVE_AS, PROJECT_SAVE_AS_COPY, PROJECT_SAVE):
        return save_project(call, args, resolved)
    if call == RELOAD_MESH:
        return reload_mesh(step, args, resolved)
    if call == EXECUTE_WHEN_NOT_BUSY:
        return execute_when_not_busy(step)
    if call == RELOAD_RESOURCES:
        return reload_resources(step, args)
    if call == ENABLE_ENGINE:
        return enable_engine(args)
    if call == DISABLE_ENGINE:
        return engine_disabled(args)
    if call == DELETE_NODE:
        return delete_node(int(args["node_step"]))
    if call == INSERT_PAINT:
        return layerstack.insert_paint(insert_position(args))
    if call == INSERT_ANCHOR_POINT:
        return layerstack.insert_anchor_point_effect(insert_position(args), str(args["name"]))
    if call == SHELVES_ADD:
        return add_shelf(step, args, resolved)
    if call == SHELF_REFRESH:
        name = str(args["name"])
        returned = shelf_named(name).refresh()
        watch_shelf(step, name)
        return returned
    if call == SET_DISPLAY_ENVIRONMENT:
        environment = PROBE_RESOURCES[int(args["resource_step"])]
        return substance_painter.display.set_environment_resource(environment)
    if call == SET_DISPLAY_COLOR_LUT:
        lut = PROBE_RESOURCES[int(args["resource_step"])] if "resource_step" in args else None
        return substance_painter.display.set_color_lut_resource(lut)
    if call == SET_DISPLAY_TONE_MAPPING:
        function = member(TONE_MAPPINGS, "ToneMappingFunction", args["function"])
        return substance_painter.display.set_tone_mapping(function)
    if call.startswith(CAMERA_PROPERTY):
        return set_camera(call[len(CAMERA_PROPERTY) :], args["value"])
    if call == PROJECT_CLOSE:
        return close_project_probe()
    if call == PROJECT_OPEN:
        return open_project_probe(step, resolved)
    if call in P22B_CALLS:
        return p22b_edit(call, args)
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
    if call == REMOVE_MASK:
        return node.remove_mask()
    if call == SET_MASK_BACKGROUND:
        background = member(MASK_BACKGROUNDS, "MaskBackground", args["background"])
        return node.set_mask_background(background)
    if call == RESET_SOURCE:
        return node.reset_source(channel_arg(args))
    if call == SET_UNIFORM_COLOR:
        color = color_of(args["color"], args.get("color_space"))
        return node.get_source(channel_arg(args)).set_color(color)
    if call == RESET_BITMAP_COLOR_SPACE:
        return node.get_source(channel_arg(args)).reset_color_space()
    if call == SET_SYMMETRY:
        return node.set_symmetry_enabled(bool(args["enabled"]))
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
    if call in P295_GETTER_CALLS:
        return p295_read(call, args)
    if call in HOST_GETTER_CALLS:  # decision 297
        return host_read(call, args)
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
    if call == ALL_TEXTURE_SETS:
        return [
            texture_set.name() for texture_set in substance_painter.textureset.all_texture_sets()
        ]
    if call == IS_BUSY:
        return substance_painter.project.is_busy()
    if call == ENGINE_STATUS:
        return substance_painter.application.engine_computations_status()
    if call == IS_RELOADING_RESOURCES:
        return substance_painter.resource.is_reload_modified_resources_running()
    if call == GET_NODE_BY_UID:
        return resolve(node_uid(int(args["node_step"])))
    if call == DEFAULT_CAMERA:
        return camera_record()
    if call.startswith(CAMERA_PROPERTY):
        return camera_property(call[len(CAMERA_PROPERTY) :])
    if call == GET_DISPLAY_ENVIRONMENT:
        return substance_painter.display.get_environment_resource()
    if call == GET_DISPLAY_COLOR_LUT:
        return substance_painter.display.get_color_lut_resource()
    if call == GET_DISPLAY_TONE_MAPPING:
        return substance_painter.display.get_tone_mapping()
    if call == SCENE_BOUNDING_BOX:
        return scene_bounding_box({})
    if call == DEFAULT_EXPORT_PATH:
        return run_path(substance_painter.export.get_default_export_path())
    if call == THROTTLING_PERIOD:
        return substance_painter.event.TextureStateEvent.cache_key_invalidation_throttling_period()
    if call == SHELVES_ALL:
        return sorted(
            (describe(shelf) for shelf in substance_painter.resource.Shelves.all()),
            key=lambda entry: str(entry["shelf"]),
        )
    if call == APPLICATION_SHELF:
        return substance_painter.resource.Shelves.application_shelf()
    if call == USER_SHELF:
        return substance_painter.resource.Shelves.user_shelf()
    if call == SHELVES_EXISTS:
        return substance_painter.resource.Shelves.exists(str(args["name"]))
    if call == SHELF_IS_CRAWLING:
        return shelf_named(str(args["name"])).is_crawling()
    if call == RESOURCE_SEARCH:
        found = substance_painter.resource.search(str(args["query"]))
        return sorted(
            (describe(item) for item in found), key=lambda entry: json.dumps(entry, sort_keys=True)
        )
    if call in P22B_CALLS:
        return p22b_read(call, args)
    node = fresh(args["node_step"])
    if call == GET_UID:
        return node.uid()
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


# --- P22-B: texture sets, channels and project (decision 295) ------------------------------------
# Explicit calls for the pending-evidence Painter symbols of the textureset and project modules
# (phase1.24 item 3.4). Channel calls address the active stack and texture-set calls its texture
# set, both resolved again for every call.
P295_ADD_CHANNEL = "substance_painter.textureset.Stack.add_channel"
P295_EDIT_CHANNEL = "substance_painter.textureset.Stack.edit_channel"
P295_REMOVE_CHANNEL = "substance_painter.textureset.Stack.remove_channel"
P295_SET_RESOLUTION = "substance_painter.textureset.TextureSet.set_resolution"
P295_SET_ACTIVE_STACK = "substance_painter.textureset.set_active_stack"
P295_METADATA_SET = "substance_painter.project.Metadata.set"
P295_HAS_CHANNEL = "substance_painter.textureset.Stack.has_channel"
P295_GET_CHANNEL = "substance_painter.textureset.Stack.get_channel"
P295_FROM_NAME = "substance_painter.textureset.TextureSet.from_name"
P295_ORIGINAL_NAME = "substance_painter.textureset.TextureSet.original_name"
P295_DESCRIPTION = "substance_painter.textureset.TextureSet.description"
P295_IS_LAYERED = "substance_painter.textureset.TextureSet.is_layered_material"
P295_GET_ACTIVE_STACK = "substance_painter.textureset.get_active_stack"
P295_METADATA_LIST = "substance_painter.project.Metadata.list"
P295_METADATA_GET = "substance_painter.project.Metadata.get"
P295_GET_UUID = "substance_painter.project.get_uuid"
P295_LAST_MESH = "substance_painter.project.last_imported_mesh_path"

P295_EDIT_CALLS = (
    "substance_painter.textureset.Stack.add_channel",
    "substance_painter.textureset.Stack.edit_channel",
    "substance_painter.textureset.Stack.remove_channel",
    "substance_painter.textureset.Channel.edit",
    "substance_painter.textureset.TextureSet.set_resolution",
    "substance_painter.textureset.set_active_stack",
    "substance_painter.project.Metadata.set",
)
P295_GETTER_CALLS = (
    "substance_painter.textureset.Stack.has_channel",
    "substance_painter.textureset.Stack.get_channel",
    "substance_painter.textureset.TextureSet.from_name",
    "substance_painter.textureset.TextureSet.original_name",
    "substance_painter.textureset.TextureSet.description",
    "substance_painter.textureset.TextureSet.is_layered_material",
    "substance_painter.textureset.get_active_stack",
    "substance_painter.project.Metadata.list",
    "substance_painter.project.Metadata.get",
    "substance_painter.project.get_uuid",
    "substance_painter.project.last_imported_mesh_path",
)
# `TextureSet.description` with `value` assigns the documented property.
P295_VALUE_ARGS = {"substance_painter.textureset.TextureSet.description": "value"}

# The first `get_uuid` value of each run, by the run's private directory: a project's UUID is new
# for every created project, so a readback records facts about it, never the value.
P295_UUIDS: dict[str, str] = {}


def active_texture_set() -> Any:
    return substance_painter.textureset.get_active_stack().material()


def call_form(attribute: Any) -> dict[str, Any]:
    """How a TextureSet member documented as a property reads (SUP-012): whether the attribute
    is callable or a string, the value through the form that works (the call when callable, else
    the attribute), and the other form's outcome when it is the call of a non-callable. The
    python-doc labels `name`, `original_name` and `description` as properties while its own
    examples, and the pipeline scripts Painter ran, call `name()`; the recording settles it."""
    callable_ = callable(attribute)
    form: dict[str, Any] = {"callable": callable_, "is_str": isinstance(attribute, str)}
    if callable_:
        return {"value": attempt(attribute), "form": form}
    form["called"] = attempt(attribute)
    return {"value": describe(attribute), "form": form}


def texture_set_name(texture_set: Any) -> Any:
    """`TextureSet.name` through the form Painter offers (`call_form`)."""
    return call_form(texture_set.name)


def channel_record(channel: Any) -> dict[str, Any]:
    """A `Channel` as its documented type, format and label."""
    return {
        "type": describe(channel.type()),
        "format": describe(channel.format()),
        "label": channel.label(),
    }


def uuid_record(value: Any) -> dict[str, Any]:
    """`project.get_uuid()` as facts that do not change between runs, as Painter gives them:
    whether it is a `uuid.UUID`, whether its text parses as one and with which version, and
    whether it equals the run's first read (the same project after save and reopen)."""
    text = str(value)
    run = str(ROOT["dir"])
    if run not in P295_UUIDS:
        P295_UUIDS[run] = text
    try:
        version = uuid.UUID(text).version
        parses = True
    except ValueError:
        version, parses = None, False
    return {
        "is_uuid_instance": isinstance(value, uuid.UUID),
        "parses_as_uuid": parses,
        "version": version,
        "same_as_first_read": text == P295_UUIDS[run],
    }


def p295_channel_edit(call: str, args: dict[str, Any]) -> Any:
    """`add_channel`, `edit_channel`, `remove_channel` or `Channel.edit` on the active stack; the
    label is passed only when the step gives one (a standard channel takes none)."""
    stack = substance_painter.textureset.get_active_stack()
    kind = channel_type(args["channel"])
    if call == P295_REMOVE_CHANNEL:
        return stack.remove_channel(kind)
    channel_format = member(CHANNEL_FORMATS, "ChannelFormat", args["format"])
    label = args.get("label")
    if call == P295_ADD_CHANNEL:
        if label is None:
            return channel_record(stack.add_channel(kind, channel_format))
        return channel_record(stack.add_channel(kind, channel_format, str(label)))
    if call == P295_EDIT_CHANNEL:
        if label is None:
            return stack.edit_channel(kind, channel_format)
        return stack.edit_channel(kind, channel_format, str(label))
    channel = stack.get_channel(kind)
    if label is None:
        return channel.edit(channel_format)
    return channel.edit(channel_format, str(label))


def p295_edit(call: str, args: dict[str, Any]) -> Any:
    textureset = substance_painter.textureset
    if call == P295_SET_RESOLUTION:
        resolution = textureset.Resolution(int(args["width"]), int(args["height"]))
        return active_texture_set().set_resolution(resolution)
    if call == P295_SET_ACTIVE_STACK:
        stack = textureset.Stack.from_name(str(args["texture_set"]), str(args.get("stack", "")))
        return textureset.set_active_stack(stack)
    if call == P295_DESCRIPTION:
        active_texture_set().description = str(args["value"])
        return None
    if call == P295_METADATA_SET:
        # A dict value is authored as `dict_keys` and `dict_values` (step arguments do not nest).
        if "dict_keys" in args:
            value = dict(zip(args["dict_keys"], args["dict_values"], strict=True))
        else:
            value = args["value"]
        metadata = substance_painter.project.Metadata(str(args["context"]))
        return metadata.set(str(args["key"]), value)
    return p295_channel_edit(call, args)


def p295_read(call: str, args: dict[str, Any]) -> Any:
    textureset = substance_painter.textureset
    project = substance_painter.project
    if call == P295_HAS_CHANNEL:
        return textureset.get_active_stack().has_channel(channel_type(args["channel"]))
    if call == P295_GET_CHANNEL:
        stack = textureset.get_active_stack()
        return channel_record(stack.get_channel(channel_type(args["channel"])))
    if call == P295_FROM_NAME:
        return {
            "texture_set": texture_set_name(
                textureset.TextureSet.from_name(str(args["texture_set"]))
            )
        }
    if call == P295_ORIGINAL_NAME:
        return call_form(active_texture_set().original_name)
    if call == P295_DESCRIPTION:
        return call_form(active_texture_set().description)
    if call == P295_IS_LAYERED:
        return active_texture_set().is_layered_material()
    if call == P295_GET_ACTIVE_STACK:
        stack = textureset.get_active_stack()
        return {"texture_set": texture_set_name(stack.material()), "stack": stack.name()}
    if call == P295_METADATA_LIST:
        return project.Metadata(str(args["context"])).list()
    if call == P295_METADATA_GET:
        return project.Metadata(str(args["context"])).get(str(args["key"]))
    if call == P295_GET_UUID:
        return uuid_record(project.get_uuid())
    if call == P295_LAST_MESH:
        return run_path(project.last_imported_mesh_path())
    raise ValueError(f"readback {call!r} is not in the probe vocabulary")


def is_read(call: str, args: dict[str, Any]) -> bool:
    values = {**VALUE_ARGS, **P295_VALUE_ARGS, **HOST_VALUE_ARGS}
    if call in values:
        return values[call] not in args
    return call in GETTER_CALLS or call in P295_GETTER_CALLS or call in HOST_GETTER_CALLS


def probe_step(args: dict[str, Any]) -> dict[str, Any]:
    """Run one probe or state step; the outcome is recorded whether it returns or raises."""
    step = int(args["step"])
    call = args["call"]
    params = args.get("args", {})
    outcome: dict[str, Any] = {}
    CURRENT["step"] = step
    try:
        if is_read(call, params):
            outcome["value"] = describe(read(call, params))
        else:
            value = edit(step, call, params, args.get("resolved", {}))
            outcome["value"] = describe(value)
            if call in INSERT_CALLS:
                PROBE_NODES[step] = value
                outcome["defaults"] = node_defaults(value)
    except ProbeGuardError:
        raise
    except Exception as error:
        outcome["value"] = None
        outcome["raised"] = raised(error)
    finally:
        CURRENT["step"] = None
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
    PROBE_RESOURCE_HANDLES.clear()
    DELETED_UIDS.clear()
    CALLBACK_STATE.clear()
    RESOURCE_RELOADS.clear()
    HELD_CALLBACKS.clear()
    SHELF_CRAWLS.clear()
    OPENING.clear()
    CLOSED["path"] = None
    ROOT["dir"] = args.get("root")
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
        if CURRENT["step"] is not None:
            entry["during_step"] = CURRENT["step"]
        if name == "BusyStatusChanged":
            entry["busy_argument"] = event.busy
        if name == "ProjectAboutToSave":
            entry["file_path_argument"] = project_file(event.file_path)
        if name == "EngineComputationsStatusChanged":
            entry["engine_computations_enabled_argument"] = event.engine_computations_enabled
        if name in ("ReloadResourcesStarted", "ReloadResourcesEnded"):
            entry["filter_argument"] = filter_name(event.filter)
        if name == "ReloadResourcesEnded":
            entry["reloaded_resources_argument"] = [
                {"old": describe(item.old_resource_id), "new": describe(item.new_resource_id)}
                for item in event.reloaded_resources
            ]
            entry["resource_errors_argument"] = [
                {"resource": describe(item.resource_id), "error_msg": item.error_msg}
                for item in event.resource_errors
            ]
        if name in ("ExportTexturesAboutToStart", "ExportTexturesEnded"):
            entry["textures_argument"] = texture_files(event.textures)
        if name == "ExportTexturesEnded":
            entry["status_argument"] = describe(event.status)
            entry["message_argument"] = event.message
        if name in ("ShelfCrawlingStarted", "ShelfCrawlingEnded"):
            entry["shelf_name_argument"] = event.shelf_name
        if name == "CameraPropertiesChanged":
            entry["camera_id_argument"] = event.camera_id
        if name == "ProjectEditionEntered" and TIMING["running"]:
            TIMING["entered_ms"] = timing_ms()
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
    """Disconnect every connected callback, each whatever the others did; one that could not be
    disconnected stays listed and the call raises (SUP-017)."""
    failed = []
    for name, callback in list(CALLBACKS.items()):
        try:
            cls = member(EVENT_CLASSES, "event", name)
            substance_painter.event.DISPATCHER.disconnect(cls, callback)
        except Exception as error:
            failed.append(f"{name}: {raised(error)['type']}: {error}")
        else:
            del CALLBACKS[name]
    EVENT_LOG.clear()
    if failed:
        raise RuntimeError(f"events not disconnected: {failed}")
    return {"disconnected": True}


def project_save(args: dict[str, Any]) -> dict[str, Any]:
    substance_painter.project.save(substance_painter.project.ProjectSaveMode.Full)
    return {"saved_at": time.time()}


def pending_names() -> list[str]:
    """Asynchronous calls not answered yet (a started resource reload: while one runs; a shelf
    crawl: while the shelf crawls; an opened project: until it is in edition and not busy)."""
    running = None
    for key in sorted(RESOURCE_RELOADS):
        if CALLBACK_STATE.get(key):
            if running is None:
                running = substance_painter.resource.is_reload_modified_resources_running()
            CALLBACK_STATE[key] = running
    for key, name in sorted(SHELF_CRAWLS.items()):
        if CALLBACK_STATE.get(key):
            CALLBACK_STATE[key] = shelf_named(name).is_crawling()
    for key in sorted(OPENING):
        if CALLBACK_STATE.get(key):
            project = substance_painter.project
            CALLBACK_STATE[key] = not (project.is_in_edition_state() and not project.is_busy())
    return sorted(key for key, waiting in CALLBACK_STATE.items() if waiting)


def probe_state(args: dict[str, Any]) -> dict[str, Any]:
    """Readiness, engine computations and pending asynchronous calls, polled by the host; with
    the crawl state of every shelf a probe added, once one was added."""
    state = {
        **project_state(),
        "engine_computations": attempt(substance_painter.application.engine_computations_status),
        "pending": pending_names(),
    }
    if SHELVES_ADDED:
        state["shelves_crawling"] = {
            name: attempt(partial(shelf_crawling, name)) for name in SHELVES_ADDED
        }
    return state


def probe_export(args: dict[str, Any]) -> dict[str, Any]:
    """An export request made as a probe step (no readiness check): its result or its error."""
    CURRENT["step"] = int(args["step"])
    try:
        result = substance_painter.export.export_project_textures(args["config"])
        value: dict[str, Any] = {
            "status": describe(result.status),
            "message": result.message,
            "textures": texture_files(result.textures),
        }
        if args.get("locations"):
            # A configuration without `exportPath` (P21-B): where each file went.
            value["locations"] = {
                f"{key[0]}/{key[1]}": [run_path(name) for name in files]
                for key, files in sorted(result.textures.items())
            }
        return {"value": value}
    except Exception as error:
        return {"value": None, "raised": raised(error)}
    finally:
        CURRENT["step"] = None


def cleanup_stage(failures: list[dict[str, Any]], stage: str, function: Callable[[], Any]) -> bool:
    """Run one restoring stage of `probe_finish` or `probe_cleanup`; a failure is listed (the
    host then publishes nothing, SUP-017) and the next stages still run."""
    try:
        function()
    except Exception as error:
        failures.append({"stage": stage, "raised": raised(error)})
        return False
    return True


def reenable_engine() -> None:
    substance_painter.application.enable_engine_computations(True)
    ENGINE["disabled_by_probe"] = False


def probe_finish(args: dict[str, Any]) -> dict[str, Any]:
    """End of a probe golden: engine computations a probe disabled are enabled again, the
    connected event callbacks are disconnected and the host-module state restored, each stage
    whatever the others did; `cleanup_failures` lists the stages that failed."""
    failures: list[dict[str, Any]] = []
    reenabled = ENGINE["disabled_by_probe"]
    if reenabled:
        cleanup_stage(failures, "enable_engine_computations", reenable_engine)
    cleanup_stage(failures, "events_disconnect", partial(events_disconnect, args))
    host = host_finish()
    return {
        "engine_reenabled": reenabled,
        "throttling_restored": host["throttling_restored"],
        "cleanup_failures": failures + host["failures"],
    }


def remove_owned_shelf(name: str) -> str:
    """Remove a shelf this run added if it is still there, and confirm it is gone; only then is
    it forgotten (SUP-016, SUP-017)."""
    if owned_shelf(name) is None:
        outcome = "already_removed"
    else:
        substance_painter.resource.Shelves.remove(name)
        if owned_shelf(name) is not None:
            raise RuntimeError(f"shelf {name!r} is still there after Shelves.remove")
        outcome = "removed"
    del SHELVES_ADDED[name]
    return outcome


def probe_cleanup(args: dict[str, Any]) -> dict[str, Any]:
    """After the project is closed: remove the shelves a probe added (`Shelves.remove` needs no
    open project; an added shelf only lives for the session anyway), then the plugin state, each
    stage whatever the others did; `cleanup_failures` lists the stages that failed."""
    failures: list[dict[str, Any]] = []
    removed: dict[str, Any] = {}
    for name in list(SHELVES_ADDED):

        def remove(name: str = name) -> None:
            removed[name] = remove_owned_shelf(name)

        cleanup_stage(failures, f"shelf/{name}", remove)
    SHELF_CRAWLS.clear()
    host = host_cleanup()
    return {
        "removed": removed,
        "plugins_closed": host["plugins_closed"],
        "cleanup_failures": failures + host["failures"],
    }


def probe_preflight(args: dict[str, Any]) -> dict[str, Any]:
    """Before the run changes anything (SUP-016): no shelf it adds exists already, and no probe
    plugin module it uses is imported, importable (the import system finds it without importing
    it) or present in a plugin root's folder (it would shadow the run's file or be shadowed by
    it); else the run is refused."""
    collisions = [
        f"a shelf named {name!r} exists already"
        for name in args.get("shelves", [])
        if substance_painter.resource.Shelves.exists(str(name))
    ]
    folders = [
        os.path.join(str(root), sub)
        for root in plugin_roots()
        for sub in ("plugins", "startup", "modules")
    ]
    for name in args.get("modules", []):
        if name in sys.modules:
            collisions.append(f"a module named {name!r} is imported already")
            continue
        spec = fresh_spec(name)
        if spec is not None:
            collisions.append(f"{name!r} is importable from {spec.origin!r}")
        collisions += [f"{name!r} is found at {found!r}" for found in homonyms(folders, name)]
    if collisions:
        raise ProbeGuardError(f"probe run refused before any change: {collisions}")
    return {"collisions": []}


def homonyms(folders: list[str], name: str) -> list[str]:
    """Files or folders of these folders a later `update_sys_path` would make importable as
    module `name` (`name.py`, `name.pyc`, an extension `name.<tag>.pyd`, a package folder)."""
    found = []
    for folder in folders:
        try:
            entries = os.listdir(folder)
        except OSError:
            continue  # a missing or unreadable folder: the import system finds nothing there
        found += [os.path.join(folder, e) for e in entries if e.split(".", 1)[0] == name]
    return found


def timing_ms() -> float:
    return round((time.perf_counter() - float(TIMING["started"])) * 1000.0, 3)


def poll_readiness() -> None:
    """The second thread of P21-F: `is_busy()` and `is_in_edition_state()` about every
    millisecond, keeping each change of state with its time, until `ProjectEditionEntered` was
    dispatched or the limit passed."""
    project = substance_painter.project
    last = None
    while TIMING["running"] and TIMING["entered_ms"] is None:
        state = {
            "busy": attempt(project.is_busy),
            "in_edition": attempt(project.is_in_edition_state),
        }
        TIMING["count"] = int(TIMING["count"]) + 1
        if state != last:
            TIMING["polls"].append({"ms": timing_ms(), **state})
            last = state
        if timing_ms() > TIMING_LIMIT_S * 1000.0:
            break
        time.sleep(TIMING_PERIOD_S)
    TIMING["running"] = False


def timed_call(args: dict[str, Any]) -> dict[str, Any]:
    """`create` or `open` of the lifecycle procedure with the step marker set to the phase (events
    dispatched inside the call carry `during_step`), while a second thread polls readiness."""
    TIMING["polls"], TIMING["count"], TIMING["entered_ms"] = [], 0, None
    TIMING["running"], TIMING["started"] = True, time.perf_counter()
    poller = threading.Thread(target=poll_readiness, daemon=True)
    threading.Thread.start(poller)
    CURRENT["step"] = args["phase"]
    try:
        if args["phase"] == "create":
            created = create_project(args["args"], args["resolved"])
        else:
            substance_painter.project.open(args["path"])
            created = {}
    finally:
        CURRENT["step"] = None
    return {**created, "returned_ms": timing_ms()}


def timing_take(args: dict[str, Any]) -> dict[str, Any]:
    """The second thread's polls of the last timed call (state changes only), then it stops."""
    TIMING["running"] = False
    return {
        "polls": list(TIMING["polls"]),
        "poll_count": TIMING["count"],
        "edition_entered_ms": TIMING["entered_ms"],
    }


# --- Host-module probes (decision 297) --------------------------------------------------------
# Strong connections by event name (Painter never drops them: `probe_finish` disconnects them),
# the throttling period read before a probe first set it (restored by `probe_finish`), and the
# plugin roots, modules and hook log of the plugin probes (removed by `probe_cleanup`).
STRONG_CALLBACKS: dict[str, Any] = {}
THROTTLING: dict[str, Any] = {"before": None, "set": False}
# `appended`: the run appended its root to the plugin path.
PLUGIN_STATE: dict[str, Any] = {"roots": [], "appended": False, "modules": {}, "log": None}


def strong_class(name: str) -> Any:
    if name in HOST_EVENT_CLASSES:
        return member(HOST_EVENT_CLASSES, "event", name)
    return member(EVENT_CLASSES, "event", name)


def dispatched_name(event: Any) -> str:
    """The documented class of a dispatched event (the subclasses first, then the base)."""
    for name in (*EVENT_CLASSES, "TextureStateEvent", "Event"):
        if isinstance(event, strong_class(name)):
            return name
    return "unlisted"


def strong_callback(name: str) -> Callable[[Any], None]:
    def callback(event: Any) -> None:
        entry: dict[str, Any] = {
            "event": name,
            "connection": "strong",
            "dispatched": dispatched_name(event),
            **project_state(),
        }
        if CURRENT["step"] is not None:
            entry["during_step"] = CURRENT["step"]
        if isinstance(event, substance_painter.event.TextureStateEvent):
            entry["action_argument"] = describe(event.action)
            entry["stack_id_argument"] = event.stack_id
            entry["tile_indices_argument"] = describe(event.tile_indices)
            entry["channel_type_argument"] = describe(event.channel_type)
            entry["cache_key_argument"] = event.cache_key
        EVENT_LOG.append(entry)

    return callback


def connect_strong(args: dict[str, Any]) -> dict[str, Any]:
    """`Dispatcher.connect_strong` of each named event; a name connected again is disconnected
    first, so every recording makes the call."""
    for name in args["events"]:
        cls = strong_class(name)
        if name in STRONG_CALLBACKS:
            substance_painter.event.DISPATCHER.disconnect(cls, STRONG_CALLBACKS[name])
            del STRONG_CALLBACKS[name]
        callback = strong_callback(name)
        substance_painter.event.DISPATCHER.connect_strong(cls, callback)
        STRONG_CALLBACKS[name] = callback
    return {"connected_strong": sorted(STRONG_CALLBACKS)}


def set_throttling(args: dict[str, Any]) -> Any:
    """`set_cache_key_invalidation_throttling_period` (global to the session): the period read
    before the first set of the golden is kept, and `probe_finish` sets it again."""
    texture_state = substance_painter.event.TextureStateEvent
    if not THROTTLING["set"]:
        # The old value must be read before anything changes (SUP-017).
        try:
            before = texture_state.cache_key_invalidation_throttling_period()
        except Exception as error:
            raise ProbeGuardError(
                f"the throttling period could not be read before setting it ({error}); "
                "nothing was changed"
            ) from error
        if before is None:
            raise ProbeGuardError("the throttling period read None; nothing was changed")
        THROTTLING["before"], THROTTLING["set"] = before, True
    period = datetime.timedelta(milliseconds=float(args["milliseconds"]))
    return texture_state.set_cache_key_invalidation_throttling_period(period)


def sorted_described(values: Any) -> list[Any]:
    return sorted((describe(v) for v in values), key=lambda e: json.dumps(e, sort_keys=True))


def resource_id(step: int, value: Any) -> Any:
    """A resource id a probe built, kept by step number for later steps (`resource_step`)."""
    PROBE_RESOURCES[step] = value
    return value


def refresh_all_shelves(step: int) -> Any:
    """`Shelves.refresh_all`: every shelf's crawl stays pending while it crawls."""
    returned = substance_painter.resource.Shelves.refresh_all()
    for shelf in substance_painter.resource.Shelves.all():
        watch_shelf(step, shelf.name())
    return returned


def plugin_roots() -> Any:
    """The documented plugin search path (a list the probe appends its root to)."""
    return substance_painter_plugins.path


def run_entries(paths: Any) -> list[Any]:
    """The entries of a path list that lie under the run's private directory (the others belong
    to the installation and the owner's machine, and are not recorded)."""
    # A path on another drive, or a relative one, cannot lie under it (`run_path` raises).
    entries = [optional(partial(run_path, p)) for p in paths]
    return [e for e in entries if isinstance(e, dict) and "run_relative" in e]


def fresh_spec(name: str) -> Any:
    """The spec the import system would find for module `name` now, asking each `sys.meta_path`
    finder as an import or a reload does, without `sys.modules` and without executing anything
    (`importlib.util.find_spec` would return a loaded module's cached spec instead: SUP-028)."""
    for finder in sys.meta_path:
        spec = finder.find_spec(name, None)
        if spec is not None:
            return spec
    return None


def own_module(name: str) -> Any:
    """Before any import, start, reload or close of a probe module (SUP-016): the file Python
    would import under that name now is the run's (in its plugin root's folder for it), and a
    module of that name already imported is the one the run imported. Returns that module, or
    None."""
    if not PLUGIN_STATE["roots"]:
        raise ProbeGuardError(f"no plugin root of this run holds {name!r}")
    root = PLUGIN_STATE["roots"][0]
    expected = normal_path(os.path.join(root, PROBE_PLUGIN_FOLDERS[name], f"{name}.py"))
    own = PLUGIN_STATE["modules"].get(name)
    present = sys.modules.get(name)
    if present is not None and present is not own:
        raise ProbeGuardError(f"the imported module {name!r} is not the probe run's")
    spec = fresh_spec(name)
    origin = None if spec is None else spec.origin
    if origin is None or normal_path(origin) != expected:
        raise ProbeGuardError(f"{name!r} would import from {origin!r}, not the run's plugin root")
    return own


def probe_module(name: str) -> Any:
    """A throwaway plugin module of the probe, imported (once) from the probe's plugin root."""
    if name not in PROBE_PLUGIN_MODULES:
        raise ValueError(f"{name!r} is not a probe plugin module")
    own = own_module(name)
    if own is None:
        own = PLUGIN_STATE["modules"][name] = importlib.import_module(name)
        own_module(name)
    return own


def take_hooks() -> list[str]:
    """The hooks the probe modules ran since the last plugin step (their log is emptied)."""
    path = PLUGIN_STATE["log"]
    if path is None or not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as log:
        lines = [line.split(NEWLINE)[0] for line in log if line.split(NEWLINE)[0]]
    with open(path, "w", encoding="utf-8"):
        pass
    return lines


def add_plugin_root(resolved: dict[str, Any]) -> dict[str, Any]:
    """Append the probe's plugin root to `substance_painter_plugins.path` (once); the probe
    modules' hook log is the file in it whose path the host wrote into them."""
    root = str(resolved["plugin_root"])
    if PLUGIN_STATE["roots"] not in ([], [root]):
        raise ProbeGuardError("a probe run writes its plugin modules in one plugin root")
    if root not in plugin_roots():
        plugin_roots().append(root)
        PLUGIN_STATE["appended"] = True
    PLUGIN_STATE["roots"] = [root]
    PLUGIN_STATE["log"] = os.path.join(root, PLUGIN_HOOK_LOG_FILE)
    return {"probe_roots": run_entries(plugin_roots())}


def plugin_call(call: str, args: dict[str, Any]) -> dict[str, Any]:
    """A plugin edit on a probe module: what it returned, and the hooks the module ran."""
    plugins = substance_painter_plugins
    module = probe_module(str(args["module"]))
    if call == START_PLUGIN:
        returned = plugins.start_plugin(module)
    elif call == CLOSE_PLUGIN and "gc_collect" in args:
        returned = plugins.close_plugin(module, gc_collect=bool(args["gc_collect"]))
    elif call == CLOSE_PLUGIN:
        returned = plugins.close_plugin(module)
    else:
        reloaded = plugins.reload_plugin(module)
        PLUGIN_STATE["modules"][str(args["module"])] = reloaded
        returned = {"is_the_loaded_module": reloaded is sys.modules.get(str(args["module"]))}
    return {"returned": describe(returned), "hooks": take_hooks()}


def module_names(names: Any) -> list[str]:
    """The probe's own names among the listed plugin or startup modules."""
    return sorted(n for n in names if isinstance(n, str) and n.startswith("uzp_probe_"))


def started_plugins() -> Any:
    """The documented dict of started plugins."""
    return substance_painter_plugins.plugins


def started_entries() -> dict[str, Any]:
    """How `substance_painter_plugins.plugins` holds each imported probe module."""
    started = started_plugins()
    return {
        name: {
            "name_is_key": name in started,
            "module_is_key": any(key is module for key in started),
            "module_is_value": any(value is module for value in started.values()),
        }
        for name, module in sorted(PLUGIN_STATE["modules"].items())
    }


def host_edit(step: int, call: str, args: dict[str, Any], resolved: dict[str, Any]) -> Any:
    """Apply one host-module edit (decision 297); returns what the documented call returned."""
    if call == LOG_INFO:
        return substance_painter.logging.info(str(args["message"]))
    if call == LOG_WARNING:
        return substance_painter.logging.warning(str(args["message"]))
    if call == LOG_ERROR:
        return substance_painter.logging.error(str(args["message"]))
    if call == LOG:
        severity = member(LOG_SEVERITIES, "logging severity", args["severity"])
        return substance_painter.logging.log(severity, str(args["channel"]), str(args["message"]))
    if call == UI_SWITCH_MODE:
        return substance_painter.ui.switch_to_mode(member(UI_MODES, "UIMode", args["mode"]))
    if call == EVENT_CONNECT_STRONG:
        return connect_strong(args)
    if call == SET_THROTTLING_PERIOD:
        return set_throttling(args)
    if call == SHELVES_REFRESH_ALL:
        return refresh_all_shelves(step)
    if call == SHELVES_REMOVE:
        return remove_shelf(str(args["name"]))
    if call == PLUGINS_PATH:
        return add_plugin_root(resolved)
    if call == PLUGINS_UPDATE_SYS_PATH:
        returned = substance_painter_plugins.update_sys_path()
        return {"returned": describe(returned), "probe_folders": run_entries(sys.path)}
    return plugin_call(call, args)


def host_read(call: str, args: dict[str, Any]) -> Any:
    """Evaluate one host-module readback (decision 297); returns the documented value."""
    if call == APPLICATION_VERSION:
        return substance_painter.application.version()
    if call == APPLICATION_VERSION_INFO:
        return substance_painter.application.version_info()
    if call.startswith("substance_painter.logging."):
        return member(LOG_SEVERITIES, "logging severity", call.split(".")[-1])
    if call == JS_EVALUATE:
        return substance_painter.js.evaluate(str(args["code"]))
    if call == UI_CURRENT_MODE:
        return substance_painter.ui.get_current_mode()
    if call == LIST_PROJECT_RESOURCES:
        return sorted_described(substance_painter.resource.list_project_resources())
    if call == RESOURCE_FROM_PROJECT:
        ids = substance_painter.resource.ResourceID
        return resource_id(CURRENT["step"], ids.from_project(str(args["name"])))
    if call == RESOURCE_FROM_URL:
        ids = substance_painter.resource.ResourceID
        url = args["url"] if "url" in args else PROBE_RESOURCES[int(args["resource_step"])].url()
        return resource_id(CURRENT["step"], ids.from_url(str(url)))
    if call == PLUGINS_PATH:
        return {"probe_roots": run_entries(plugin_roots())}
    if call == PLUGIN_MODULE_NAMES:
        return module_names(substance_painter_plugins.plugin_module_names())
    if call == STARTUP_MODULE_NAMES:
        return module_names(substance_painter_plugins.startup_module_names())
    if call == IS_PLUGIN_STARTED:
        return substance_painter_plugins.is_plugin_started(probe_module(str(args["module"])))
    if call == STARTED_PLUGINS:
        return started_entries()
    raise ValueError(f"readback {call!r} is not in the probe vocabulary")


def disconnect_strong(name: str) -> None:
    substance_painter.event.DISPATCHER.disconnect(strong_class(name), STRONG_CALLBACKS[name])
    del STRONG_CALLBACKS[name]


def restore_throttling() -> None:
    """Set the period read before the first set back, and read it again; the snapshot is only
    dropped once the readback equals it (SUP-017)."""
    texture_state = substance_painter.event.TextureStateEvent
    texture_state.set_cache_key_invalidation_throttling_period(THROTTLING["before"])
    now = texture_state.cache_key_invalidation_throttling_period()
    if now != THROTTLING["before"]:
        raise RuntimeError(f"the throttling period reads {now!r} after restoring it")
    THROTTLING["before"], THROTTLING["set"] = None, False


def host_finish() -> dict[str, Any]:
    """End of a golden: the strong connections are disconnected and the throttling period a
    probe set is set back to the value read before, each whatever the others did; a stage that
    failed keeps its connection or snapshot and is listed in `failures`."""
    failures: list[dict[str, Any]] = []
    for name in list(STRONG_CALLBACKS):
        cleanup_stage(failures, f"disconnect_strong/{name}", partial(disconnect_strong, name))
    restored = None
    if THROTTLING["set"]:
        before = describe(THROTTLING["before"])
        if cleanup_stage(failures, "throttling", restore_throttling):
            restored = before
    return {"throttling_restored": restored, "failures": failures}


def under_roots(entry: Any, roots: list[str]) -> bool:
    """Whether a `sys.path` entry is one of the probe roots' folders (however it is spelled)."""
    path = os.path.normcase(os.path.normpath(str(entry)))
    for root in roots:
        base = os.path.normcase(os.path.normpath(root))
        if path == base or path.startswith(base + os.sep):
            return True
    return False


def forget_module(name: str, closed: dict[str, Any]) -> None:
    """Close a probe module the run imported if it is started, then drop it from `sys.modules`
    only while that entry is still the run's module (SUP-016)."""
    module = PLUGIN_STATE["modules"][name]
    if substance_painter_plugins.is_plugin_started(module):
        closed[name] = describe(substance_painter_plugins.close_plugin(module, False))
        if substance_painter_plugins.is_plugin_started(module):
            raise RuntimeError(f"{name!r} is still started after close_plugin")
    if sys.modules.get(name) is module:
        del sys.modules[name]
    del PLUGIN_STATE["modules"][name]


def restore_paths() -> None:
    """The run's root leaves the plugin path (if the run appended it) and its folders `sys.path`;
    every other entry stays."""
    roots = PLUGIN_STATE["roots"]
    if PLUGIN_STATE["appended"]:
        plugin_roots()[:] = [entry for entry in plugin_roots() if entry not in roots]
        PLUGIN_STATE["appended"] = False
    sys.path[:] = [entry for entry in sys.path if not under_roots(entry, roots)]


def host_cleanup() -> dict[str, Any]:
    """After the project is closed: the probe plugin modules are closed and forgotten, and their
    root leaves the plugin path and its folders `sys.path`, each whatever the others did; what
    failed stays recorded and is listed in `failures`. A module kept for a retry still logs to
    the run's own file (its path is written in it), never to anything outside the run."""
    failures: list[dict[str, Any]] = []
    closed: dict[str, Any] = {}
    for name in sorted(PLUGIN_STATE["modules"]):
        cleanup_stage(failures, f"plugin/{name}", partial(forget_module, name, closed))
    paths = cleanup_stage(failures, "plugin_paths", restore_paths)
    if paths and not PLUGIN_STATE["modules"]:
        PLUGIN_STATE["roots"], PLUGIN_STATE["log"] = [], None
    return {"plugins_closed": closed, "failures": failures}


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
    "probe_state": probe_state,
    "probe_export": probe_export,
    "probe_finish": probe_finish,
    "probe_cleanup": probe_cleanup,
    "probe_preflight": probe_preflight,
    "timed_call": timed_call,
    "timing_take": timing_take,
}

for operation_name, operation in PROBE_OPERATIONS.items():
    OPERATIONS[operation_name] = operation
