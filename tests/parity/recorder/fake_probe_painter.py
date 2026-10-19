"""A fake layer-stack tree, events and resources for the API-probe recorder tests (no Painter).

`ProbeWorld` extends the recorder's `FakeWorld` (`fake_painter.py`) with the documented surface
`painter_probes.py` uses: groups, content and mask stacks, effects, insertion rules, masks,
bitmap sources, levels, mesh maps and project events. The behaviour is simple and authored for
the tests (it states what the fake does, not what Painter does): the multichannel/mask rules raise
`EditionContextException` or `ValueError`, assigning `active_channels` clears the fill's sources,
and every node gets a new uid when a project is reopened. Asynchronous work (`reload_mesh`,
`execute_when_not_busy`, `reload_modified_resources_async`, a shelf crawl) is queued and runs one
task per `project.is_busy()` poll; the project is busy while a mesh reload is queued. Mesh maps
given to `project.create` bind by the file stem `<texture set>_<name>`, with the mesh-map names of
the documented export configuration (an authored rule of the fake).
"""

from __future__ import annotations

import datetime
import enum
import json
import types
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from uzp_recorder_fake_painter import (  # type: ignore[import-not-found]
    BlendingMode,
    ChannelType,
    Color,
    ExportStatus,
    FakeWorld,
    GenericColorSpace,
    ProjectError,
    SourceMode,
    SourceUniformColor,
)


class EditionContextException(Exception):
    pass


class NodeType(enum.Enum):
    FillLayer = 1
    FillEffect = 2
    GroupLayer = 3
    LevelsEffect = 4
    CompareMaskEffect = 5
    ColorSelectionEffect = 6
    PaintLayer = 7
    PaintEffect = 8
    AnchorPointEffect = 9


class NodeStack(enum.Enum):
    Substack = 0
    Content = 1
    Mask = 2


class MaskBackground(enum.Enum):
    Black = 0
    White = 1


class ProjectionMode(enum.Enum):
    Fill = 0
    UV = 1
    Triplanar = 2
    Planar = 3
    Spherical = 4
    Cylindrical = 5


class FilteringMode(enum.Enum):
    BilinearHQ = 0
    BilinearSharp = 1
    Nearest = 2


class UVWrapMode(enum.Enum):
    RepeatNone = 0
    RepeatHorizontally = 1
    RepeatVertically = 2
    Repeat = 3


class ScaleMode(enum.Enum):
    Factors = 0
    MaterialPhysicalSize = 1
    CustomPhysicalSize = 2


class LegacyColorSpace(enum.Enum):
    Linear = 0
    sRGB = 1


class DataColorSpace(enum.Enum):
    Data = 0
    DataSigned = 1


class MeshMapUsage(enum.Enum):
    AO = 0
    Curvature = 1
    Height = 2
    Normal = 3
    BentNormals = 4
    ID = 5
    Opacity = 6
    Position = 7
    Thickness = 8
    WorldSpaceNormal = 9


# The fake's binding of `project.create(mesh_map_file_paths=...)`: file stem suffix -> usage.
MESH_MAP_SUFFIXES = {
    "ambient_occlusion": MeshMapUsage.AO,
    "id": MeshMapUsage.ID,
    "curvature": MeshMapUsage.Curvature,
    "normal_base": MeshMapUsage.Normal,
    "world_space_normals": MeshMapUsage.WorldSpaceNormal,
    "position": MeshMapUsage.Position,
    "thickness": MeshMapUsage.Thickness,
}
# Paths the fake reports for the shelves it ships and for the application's default export path.
APPLICATION_SHELF_PATH = "C:/fake-painter/resources/shelf"
USER_SHELF_PATH = "C:/fake-documents/Adobe/Adobe Substance 3D Painter"
DEFAULT_EXPORT_PATH = "C:/fake-documents/Adobe/Adobe Substance 3D Painter/export"


class ReloadMeshStatus(enum.Enum):
    SUCCESS = 0
    ERROR = 2


@dataclass
class MeshReloadingSettings:
    import_cameras: bool = True
    preserve_strokes: bool = True


class AllResourcesFilter:
    pass


class ProjectFilter:
    pass


class ResourcesUsedByProjectFilter:
    pass


class SessionFilter:
    pass


class ResourcesListFilter:
    def __init__(self, resources: list[Any]) -> None:
        self.resources = list(resources)


@dataclass
class ReloadedResourceResult:
    old_resource_id: Any
    new_resource_id: Any


@dataclass
class UVTransformationParams:
    scale_mode: Any = None
    scale: Any = None
    rotation: Any = None
    offset: Any = None


@dataclass
class UVProjectionParams:
    filtering_mode: Any = None
    uv_wrapping_mode: Any = None
    uv_transformation: UVTransformationParams = field(default_factory=UVTransformationParams)


@dataclass
class LevelsParamsMono:
    input_min: float = 0.0
    input_max: float = 1.0
    gamma: float = 1.0
    output_min: float = 0.0
    output_max: float = 1.0
    clamp: bool = False


LAYER_KINDS = (NodeType.FillLayer, NodeType.GroupLayer, NodeType.PaintLayer)
CONTAINERS = ("Substack", "Content", "Mask")


@dataclass
class Item:
    """One node of the fake tree."""

    uid: int
    kind: NodeType
    container: str  # Root, Substack, Content or Mask
    parent: Item | None
    name: str
    visible: bool = True
    children: dict[str, list[Item]] = field(
        default_factory=lambda: {name: [] for name in CONTAINERS}
    )
    channels: set[Any] = field(default_factory=set)
    sources: dict[Any, Any] = field(default_factory=dict)
    blending: dict[Any, BlendingMode] = field(default_factory=dict)
    opacity: dict[Any, float] = field(default_factory=dict)
    mask: MaskBackground | None = None
    mask_enabled: bool = True
    projection: ProjectionMode = ProjectionMode.UV
    projection_parameters: UVProjectionParams = field(default_factory=UVProjectionParams)
    levels: LevelsParamsMono = field(default_factory=LevelsParamsMono)
    affected_channel: Any = None
    symmetry: bool = False

    @property
    def is_layer(self) -> bool:
        return self.kind in LAYER_KINDS

    @property
    def multichannel(self) -> bool:
        return self.container != "Mask"


class ProbeWorld(FakeWorld):  # type: ignore[misc]
    """FakeWorld plus a node tree; `roots` are ordered like Painter lists them (top first)."""

    def __init__(self) -> None:
        super().__init__()
        self.roots: list[Item] = []
        self.items: dict[int, Item] = {}
        self.mesh_maps: dict[MeshMapUsage, Any] = {}
        self.listeners: dict[type, list[Any]] = {}
        self.edition_entered = False
        self.saved = False
        self.deferred: list[Callable[[], None]] = []  # asynchronous work, one task per poll
        self.dispatching = 0  # no queued task runs from inside a callback or another task
        self.engine = True
        self.reloading = False
        self.shelves: dict[str, str] = {}  # shelves a script added: name -> folder
        self.crawling: set[str] = set()
        extend_modules(self)

    # Tree ----------------------------------------------------------------------------------
    def new_item(self, kind: NodeType, container: str, parent: Item | None) -> Item:
        self.next_uid += 1
        item = Item(self.next_uid, kind, container, parent, f"{kind.name} {self.next_uid}")
        if kind == NodeType.LevelsEffect:
            item.affected_channel = None if container == "Mask" else ChannelType.BaseColor
        self.items[item.uid] = item
        return item

    def siblings(self, item: Item) -> list[Item]:
        return self.roots if item.parent is None else item.parent.children[item.container]

    def item(self, uid: int) -> Item:
        if uid not in self.items:
            raise ValueError(f"uid {uid} does not correspond to a valid node")
        return self.items[uid]

    def emit(self, event: Any) -> None:
        self.dispatching += 1
        try:
            for callback in list(self.listeners.get(type(event), [])):
                callback(event)
        finally:
            self.dispatching -= 1

    # Persistence ---------------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        def dump(item: Item) -> dict[str, Any]:
            return {
                "kind": item.kind.name,
                "container": item.container,
                "name": item.name,
                "visible": item.visible,
                "children": {k: [dump(c) for c in v] for k, v in item.children.items()},
                "channels": sorted(c.name for c in item.channels),
                "sources": {
                    ("" if c is None else c.name): (
                        ["color", list(s.color.working)]
                        if isinstance(s, SourceUniformColor)
                        else ["bitmap", s.rid.url()]
                    )
                    for c, s in item.sources.items()
                },
                "blending": {
                    ("" if c is None else c.name): m.name for c, m in item.blending.items()
                },
                "opacity": {("" if c is None else c.name): o for c, o in item.opacity.items()},
                "mask": None if item.mask is None else item.mask.name,
                "levels": [item.levels.input_min, item.levels.input_max, item.levels.gamma],
            }

        data: dict[str, Any] = super().snapshot()
        data["tree"] = [dump(item) for item in self.roots]
        data["mesh_maps"] = {usage.name: rid.url() for usage, rid in self.mesh_maps.items()}
        data["p295"] = p295_snapshot(self)
        return data

    def restore(self, data: dict[str, Any]) -> None:
        super().restore(data)
        self.items = {}
        self.next_uid += 500  # uids change across reopen
        modules = self.modules
        resource_id = modules["substance_painter.resource"].ResourceID

        def channel(name: str) -> Any:
            return None if name == "" else ChannelType[name]

        def load(entry: dict[str, Any], parent: Item | None) -> Item:
            item = self.new_item(NodeType[entry["kind"]], entry["container"], parent)
            item.name, item.visible = entry["name"], entry["visible"]
            item.channels = {ChannelType[c] for c in entry["channels"]}
            for name, (kind, value) in entry["sources"].items():
                if kind == "color":
                    item.sources[channel(name)] = SourceUniformColor(
                        Color(*value, GenericColorSpace.Working)
                    )
                else:
                    item.sources[channel(name)] = SourceBitmap(resource_id.from_url(value))
            item.blending = {channel(c): BlendingMode[m] for c, m in entry["blending"].items()}
            item.opacity = {channel(c): o for c, o in entry["opacity"].items()}
            item.mask = None if entry["mask"] is None else MaskBackground[entry["mask"]]
            item.levels = LevelsParamsMono(*entry["levels"])
            for key, children in entry["children"].items():
                item.children[key] = [load(child, item) for child in children]
            return item

        self.roots = [load(entry, None) for entry in data["tree"]]
        self.mesh_maps = {
            MeshMapUsage[name]: resource_id.from_url(url) for name, url in data["mesh_maps"].items()
        }
        p295_restore(self, data["p295"])

    # Export --------------------------------------------------------------------------------
    def composite(self, channel: ChannelType) -> tuple[float, float, float]:
        value = (0.0, 0.0, 0.0)

        def coverage(item: Item) -> float:
            if item.mask is None or not item.mask_enabled:
                return 1.0
            mask = 1.0 if item.mask == MaskBackground.White else 0.0
            for effect in reversed(item.children["Mask"]):
                source = effect.sources.get(None)
                if effect.kind == NodeType.FillEffect and source is not None:
                    level = (
                        source.color.working[0] if isinstance(source, SourceUniformColor) else 0.5
                    )
                    alpha = effect.opacity.get(None, 1.0)
                    mask = mask + (level - mask) * alpha
            return mask

        def visit(items: list[Item]) -> None:
            nonlocal value
            for item in reversed(items):  # bottom to top
                if not item.visible:
                    continue
                if item.kind == NodeType.GroupLayer:
                    visit(item.children["Substack"])
                    continue
                source = item.sources.get(channel)
                if channel not in item.channels or not isinstance(source, SourceUniformColor):
                    continue
                top = source.color.working
                alpha = item.opacity.get(channel, 1.0) * coverage(item)
                value = tuple(v + (t - v) * alpha for v, t in zip(value, top, strict=True))

        visit(self.roots)
        return value


class SourceBitmap:
    def __init__(self, rid: Any) -> None:
        self.rid = rid
        self.space: Any = GenericColorSpace.sRGB

    @property
    def resource_id(self) -> Any:
        return self.rid

    def get_color_space(self) -> Any:
        return self.space

    def list_available_color_spaces(self) -> list[Any]:
        return [GenericColorSpace.sRGB, GenericColorSpace.Raw]

    def set_color_space(self, space: Any) -> None:
        if space not in self.list_available_color_spaces():
            raise ValueError(f"color space {space} is not supported in the current context")
        self.space = space

    def reset_color_space(self) -> None:
        self.space = GenericColorSpace.sRGB


def extend_modules(world: ProbeWorld) -> None:
    """Replace the fake layerstack and add the modules and members the probes use."""
    modules = world.modules
    textureset = modules["substance_painter.textureset"]
    project = modules["substance_painter.project"]
    resource = modules["substance_painter.resource"]

    class Node:
        def __init__(self, uid: int) -> None:
            self.node_uid = uid

        @property
        def data(self) -> Item:
            return world.item(self.node_uid)

        def uid(self) -> int:
            return self.node_uid

        def get_type(self) -> NodeType:
            return self.data.kind

        def get_name(self) -> str:
            return self.data.name

        def set_name(self, name: str) -> None:
            self.data.name = name

        def is_visible(self) -> bool:
            return self.data.visible

        def set_visible(self, visible: bool) -> None:
            self.data.visible = visible

        def is_in_mask_stack(self) -> bool:
            return self.data.container == "Mask"

        def has_blending(self) -> bool:
            return True

        def blend_key(self, channel: Any) -> Any:
            if self.is_in_mask_stack() and channel is not None:
                raise ValueError("a node in a mask stack takes no channel type")
            if not self.is_in_mask_stack() and channel is None:
                raise ValueError("a channel type is required")
            return channel

        def get_blending_mode(self, channel: Any = None) -> BlendingMode:
            return self.data.blending.get(self.blend_key(channel), BlendingMode.Normal)

        def set_blending_mode(self, mode: BlendingMode, channel: Any = None) -> None:
            self.data.blending[self.blend_key(channel)] = mode

        def get_opacity(self, channel: Any = None) -> float:
            return self.data.opacity.get(self.blend_key(channel), 1.0)

        def set_opacity(self, opacity: float, channel: Any = None) -> None:
            self.data.opacity[self.blend_key(channel)] = opacity

        def get_stack(self) -> Any:
            return textureset.Stack(world.texture_set, "")

        def get_parent(self) -> Any:
            parent = self.data.parent
            return None if parent is None else handle(parent)

    class LayerNode(Node):
        def content_effects(self) -> list[Any]:
            return [handle(i) for i in self.data.children["Content"]]

        def mask_effects(self) -> list[Any]:
            return [handle(i) for i in self.data.children["Mask"]]

        def has_mask(self) -> bool:
            return self.data.mask is not None

        def add_mask(self, background: MaskBackground) -> None:
            if self.data.mask is not None:
                raise ValueError("a mask is already set on this node")
            self.data.mask = background

        def require_mask(self) -> Item:
            if self.data.mask is None:
                raise ValueError("no mask exists on this node")
            return self.data

        def get_mask_background(self) -> MaskBackground | None:
            return self.require_mask().mask

        def is_mask_enabled(self) -> bool:
            return self.require_mask().mask_enabled

        def enable_mask(self, enabled: bool) -> None:
            self.require_mask().mask_enabled = enabled

        def remove_mask(self) -> None:
            item = self.require_mask()
            item.mask, item.mask_enabled, item.children["Mask"] = None, True, []

        def set_mask_background(self, background: MaskBackground) -> None:
            self.require_mask().mask = background

    class GroupLayerNode(LayerNode):
        def sub_layers(self) -> list[Any]:
            return [handle(i) for i in self.data.children["Substack"]]

    class FillMixin(Node):
        @property
        def source_mode(self) -> SourceMode | None:
            return SourceMode.Split if self.data.multichannel else None

        def source_key(self, channel: Any) -> Any:
            data = self.data
            if not data.multichannel:
                if channel is not None:
                    raise EditionContextException("no channel type in a mono-channel context")
                return None
            if channel is None or channel not in data.channels:
                raise EditionContextException("the channel type is not valid in this context")
            return channel

        @property
        def active_channels(self) -> set[Any]:
            return set(self.data.channels)

        @active_channels.setter
        def active_channels(self, channels: set[Any]) -> None:
            if not self.data.multichannel:
                raise EditionContextException("no channels in a mono-channel context")
            self.data.channels = set(channels)
            self.data.sources = {}  # the fake's authored rule: assigning channels clears sources

        def set_source(self, channel: Any, source: Any) -> Any:
            key = self.source_key(channel)
            if isinstance(source, resource.ResourceID):
                made: Any = SourceBitmap(source)
            elif isinstance(source, Color):
                made = SourceUniformColor(source)
            else:
                raise ValueError("the source parameter is not valid")
            self.data.sources[key] = made
            return made

        def get_source(self, channel: Any = None) -> Any:
            key = self.source_key(channel)
            default = SourceUniformColor(Color(1.0, 1.0, 1.0, GenericColorSpace.Working))
            return self.data.sources.get(key, default)

        def reset_source(self, channel: Any = None) -> None:
            self.data.sources.pop(self.source_key(channel), None)

        def set_symmetry_enabled(self, enabled: bool) -> None:
            self.data.symmetry = enabled

        def get_projection_mode(self) -> ProjectionMode:
            return self.data.projection

        def set_projection_mode(self, mode: ProjectionMode) -> None:
            self.data.projection = mode

        def get_projection_parameters(self) -> UVProjectionParams:
            return self.data.projection_parameters

        def set_projection_parameters(self, parameters: UVProjectionParams) -> None:
            self.data.projection = ProjectionMode.UV
            self.data.projection_parameters = parameters

    class FillLayerNode(FillMixin, LayerNode):
        pass

    class FillEffectNode(FillMixin):
        pass

    class LevelsEffectNode(Node):
        @property
        def affected_channel(self) -> Any:
            return self.data.affected_channel

        @affected_channel.setter
        def affected_channel(self, channel: Any) -> None:
            self.data.affected_channel = channel

        def get_parameters(self) -> LevelsParamsMono:
            return self.data.levels

        def set_parameters(self, parameters: LevelsParamsMono) -> None:
            self.data.levels = parameters

    class CompareMaskEffectNode(Node):
        pass

    class ColorSelectionEffectNode(Node):
        pass

    class PaintLayerNode(LayerNode):
        pass

    class PaintEffectNode(Node):
        pass

    class AnchorPointEffectNode(Node):
        pass

    classes = {
        NodeType.FillLayer: FillLayerNode,
        NodeType.FillEffect: FillEffectNode,
        NodeType.GroupLayer: GroupLayerNode,
        NodeType.LevelsEffect: LevelsEffectNode,
        NodeType.CompareMaskEffect: CompareMaskEffectNode,
        NodeType.ColorSelectionEffect: ColorSelectionEffectNode,
        NodeType.PaintLayer: PaintLayerNode,
        NodeType.PaintEffect: PaintEffectNode,
        NodeType.AnchorPointEffect: AnchorPointEffectNode,
    }

    def handle(item: Item) -> Any:
        return classes[item.kind](item.uid)

    @dataclass
    class InsertPosition:
        kind: str  # top, above, below, inside
        reference: Item | None = None
        stack: NodeStack | None = None

        @staticmethod
        def from_textureset_stack(stack: Any) -> InsertPosition:
            return InsertPosition("top")

        @staticmethod
        def above_node(node: Node) -> InsertPosition:
            return InsertPosition("above", node.data)

        @staticmethod
        def below_node(node: Node) -> InsertPosition:
            return InsertPosition("below", node.data)

        @staticmethod
        def inside_node(node: Node, stack: NodeStack) -> InsertPosition:
            return InsertPosition("inside", node.data, stack)

    def place(position: InsertPosition, layer: NodeType | None, effect: NodeType | None) -> Any:
        """Insert per the documented insertion table; `None` means the kind is not allowed."""
        world.require_open()
        ref = position.reference
        if position.kind == "top":
            if layer is None:
                raise ValueError("insertion failed due to an invalid position")
            item = world.new_item(layer, "Root", None)
            world.roots.insert(0, item)
            return handle(item)
        assert ref is not None
        if position.kind in ("above", "below"):
            kind = layer if ref.is_layer else effect
            if kind is None:
                raise ValueError("insertion failed due to an invalid position")
            item = world.new_item(kind, ref.container, ref.parent)
            siblings = world.siblings(ref)
            index = siblings.index(ref)
            siblings.insert(index if position.kind == "above" else index + 1, item)
            return handle(item)
        assert position.stack is not None
        container = position.stack.name
        if container == "Substack":
            kind = layer if ref.kind == NodeType.GroupLayer else None
        else:
            kind = effect if ref.is_layer else None
            if container == "Mask" and ref.mask is None:
                kind = None
        if kind is None:
            raise ValueError("insertion failed due to an invalid position")
        item = world.new_item(kind, container, ref)
        ref.children[container].insert(0, item)
        return handle(item)

    def insert_fill(position: InsertPosition) -> Any:
        return place(position, NodeType.FillLayer, NodeType.FillEffect)

    def insert_group(position: InsertPosition) -> Any:
        return place(position, NodeType.GroupLayer, None)

    def mask_only(position: InsertPosition) -> bool:
        ref = position.reference
        if ref is None:
            return False
        return position.stack == NodeStack.Mask or (not ref.is_layer and ref.container == "Mask")

    def insert_levels_effect(position: InsertPosition) -> Any:
        return place(position, None, NodeType.LevelsEffect)

    def insert_compare_mask_effect(position: InsertPosition) -> Any:
        effect = NodeType.CompareMaskEffect if mask_only(position) else None
        return place(position, None, effect)

    def insert_color_selection_effect(position: InsertPosition) -> Any:
        effect = NodeType.ColorSelectionEffect if mask_only(position) else None
        return place(position, None, effect)

    def insert_paint(position: InsertPosition) -> Any:
        return place(position, NodeType.PaintLayer, NodeType.PaintEffect)

    def insert_anchor_point_effect(position: InsertPosition, name: str) -> Any:
        node = place(position, None, NodeType.AnchorPointEffect)
        node.set_name(name)
        return node

    def get_root_layer_nodes(stack: Any) -> list[Any]:
        return [handle(item) for item in world.roots]

    def get_node_by_uid(uid: int) -> Any:
        return handle(world.item(uid))

    def delete_node(node: Node) -> None:
        item = node.data

        def forget(gone: Item) -> None:
            del world.items[gone.uid]
            for children in gone.children.values():
                for child in children:
                    forget(child)

        world.siblings(item).remove(item)
        forget(item)

    modules["substance_painter.layerstack"] = module(
        "substance_painter.layerstack",
        BlendingMode=BlendingMode,
        NodeType=NodeType,
        NodeStack=NodeStack,
        MaskBackground=MaskBackground,
        ProjectionMode=ProjectionMode,
        FilteringMode=FilteringMode,
        UVWrapMode=UVWrapMode,
        ScaleMode=ScaleMode,
        UVProjectionParams=UVProjectionParams,
        UVTransformationParams=UVTransformationParams,
        InsertPosition=InsertPosition,
        Node=Node,
        LayerNode=LayerNode,
        GroupLayerNode=GroupLayerNode,
        FillLayerNode=FillLayerNode,
        FillEffectNode=FillEffectNode,
        LevelsEffectNode=LevelsEffectNode,
        insert_fill=insert_fill,
        insert_group=insert_group,
        insert_levels_effect=insert_levels_effect,
        insert_compare_mask_effect=insert_compare_mask_effect,
        insert_color_selection_effect=insert_color_selection_effect,
        insert_paint=insert_paint,
        insert_anchor_point_effect=insert_anchor_point_effect,
        get_root_layer_nodes=get_root_layer_nodes,
        get_node_by_uid=get_node_by_uid,
        delete_node=delete_node,
    )

    # Mesh maps on texture sets, and the enum the probes use.
    def set_mesh_map_resource(self: Any, usage: MeshMapUsage, rid: Any) -> None:
        for other, used in world.mesh_maps.items():
            if other != usage and rid is not None and used.url() == rid.url():
                raise ValueError("the resource is already used for another mesh map usage")
        world.mesh_maps[usage] = rid

    def get_mesh_map_resource(self: Any, usage: MeshMapUsage) -> Any:
        return world.mesh_maps.get(usage)

    textureset.TextureSet.set_mesh_map_resource = set_mesh_map_resource
    textureset.TextureSet.get_mesh_map_resource = get_mesh_map_resource
    textureset.MeshMapUsage = MeshMapUsage

    colormanagement = modules["substance_painter.colormanagement"]
    colormanagement.LegacyColorSpace = LegacyColorSpace
    colormanagement.DataColorSpace = DataColorSpace
    modules["substance_painter.source"].SourceBitmap = SourceBitmap
    modules["substance_painter.source"].SourceMode = SourceMode
    resource.ResourceID.version = None  # documented member the base fake does not model

    # Events: the documented dispatcher and the project events the lifecycle probe uses.
    def event_class(name: str, *fields: str) -> type:
        def init(self: Any, *values: Any) -> None:
            for key, value in zip(fields, values, strict=True):
                setattr(self, key, value)

        return type(name, (), {"__init__": init})

    events = {
        name: event_class(name)
        for name in (
            "ProjectOpened",
            "ProjectCreated",
            "ProjectAboutToClose",
            "ProjectClosed",
            "ProjectSaved",
            "ProjectEditionEntered",
            "ProjectEditionLeft",
        )
    }
    events["ProjectAboutToSave"] = event_class("ProjectAboutToSave", "file_path")
    events["BusyStatusChanged"] = event_class("BusyStatusChanged", "busy")
    events["EngineComputationsStatusChanged"] = event_class(
        "EngineComputationsStatusChanged", "engine_computations_enabled"
    )
    events["ReloadResourcesStarted"] = event_class("ReloadResourcesStarted", "filter")
    events["ReloadResourcesEnded"] = event_class(
        "ReloadResourcesEnded", "filter", "reloaded_resources", "resource_errors"
    )
    events["ExportTexturesAboutToStart"] = event_class("ExportTexturesAboutToStart", "textures")
    events["ExportTexturesEnded"] = event_class(
        "ExportTexturesEnded", "status", "message", "textures"
    )
    events["LayerStacksModelDataChanged"] = event_class("LayerStacksModelDataChanged")
    events["ShelfCrawlingStarted"] = event_class("ShelfCrawlingStarted", "shelf_name")
    events["ShelfCrawlingEnded"] = event_class("ShelfCrawlingEnded", "shelf_name")
    events["CameraPropertiesChanged"] = event_class("CameraPropertiesChanged", "camera_id")

    class TextureStateEvent:
        @staticmethod
        def cache_key_invalidation_throttling_period() -> datetime.timedelta:
            return datetime.timedelta(seconds=1)

    events["TextureStateEvent"] = TextureStateEvent

    class Dispatcher:
        def connect(self, event_cls: type, callback: Any) -> None:
            world.listeners.setdefault(event_cls, []).append(callback)

        def disconnect(self, event_cls: type, callback: Any) -> None:
            world.listeners[event_cls].remove(callback)

    modules["substance_painter.event"] = module(
        "substance_painter.event", DISPATCHER=Dispatcher(), Dispatcher=Dispatcher, **events
    )

    # Project lifecycle with events.
    create, save_as, close, open_ = project.create, project.save_as, project.close, project.open
    edition = project.is_in_edition_state

    def create_with_events(mesh_file_path: str, settings: Any, **others: Any) -> None:
        create(mesh_file_path=mesh_file_path, settings=settings, **others)
        world.roots, world.items, world.mesh_maps = [], {}, {}
        prefix = f"{world.texture_set}_"
        for path in others.get("mesh_map_file_paths") or []:
            stem = Path(path).stem
            usage = MESH_MAP_SUFFIXES.get(stem[len(prefix) :]) if stem.startswith(prefix) else None
            if usage is not None:
                world.mesh_maps[usage] = resource.ResourceID(stem)
        world.edition_entered = False
        world.saved = False
        world.emit(events["ProjectCreated"]())

    def is_in_edition_state() -> bool:
        ready: bool = edition()
        if ready and not world.edition_entered:
            world.edition_entered = True
            world.emit(events["ProjectEditionEntered"]())
        return ready

    def save_as_with_events(path: str, mode: Any) -> None:
        world.emit(events["ProjectAboutToSave"](path))
        save_as(path, mode)
        world.saved = True
        world.emit(events["ProjectSaved"]())

    def save(mode: Any) -> None:
        if world.file_path is None:
            raise ProjectError("the project has never been saved")
        save_as_with_events(world.file_path, mode)

    def close_with_events() -> None:
        world.emit(events["ProjectAboutToClose"]())
        world.emit(events["ProjectEditionLeft"]())
        close()
        world.emit(events["ProjectClosed"]())

    def open_with_events(path: str) -> None:
        open_(path)
        world.edition_entered = False
        world.saved = True
        world.emit(events["ProjectOpened"]())

    def needs_saving() -> bool:
        world.require_open()
        return not world.saved

    def name() -> str | None:
        world.require_open()
        return None if world.file_path is None else Path(world.file_path).stem

    project.create = create_with_events
    project.is_in_edition_state = is_in_edition_state
    project.save_as = save_as_with_events
    project.save = save
    project.close = close_with_events
    project.open = open_with_events
    project.needs_saving = needs_saving
    project.name = name
    extend_async(world, events)
    extend_host(world, events)
    extend_p295(world, events)

    root = modules["substance_painter"]
    root.layerstack = modules["substance_painter.layerstack"]
    root.event = modules["substance_painter.event"]


def extend_async(world: ProbeWorld, events: dict[str, type]) -> None:
    """Saves to a copy, mesh and resource reloads, deferred callbacks, engine computations and
    export events (the R10 probe surface)."""
    modules = world.modules
    project = modules["substance_painter.project"]
    resource = modules["substance_painter.resource"]
    export = modules["substance_painter.export"]
    application = modules["substance_painter.application"]
    busy_before = project.is_busy

    def is_busy() -> bool:
        if world.deferred and not world.dispatching:
            world.dispatching += 1
            try:
                world.deferred.pop(0)()
            finally:
                world.dispatching -= 1
        return bool(busy_before())

    def set_busy(busy: bool) -> None:
        if world.busy != busy:
            world.busy = busy
            world.emit(events["BusyStatusChanged"](busy))

    def save_as_copy(backup_file_path: str, mode: Any) -> None:
        world.require_open()
        world.emit(events["ProjectAboutToSave"](backup_file_path))
        Path(backup_file_path).write_text(json.dumps(world.snapshot()), encoding="utf-8")
        world.emit(events["ProjectSaved"]())

    def reload_mesh(mesh_file_path: str, settings: Any, loading_status_cb: Any) -> None:
        world.require_open()
        if world.busy:
            raise ProjectError("Substance 3D Painter is busy")
        set_busy(True)

        def finish() -> None:
            set_busy(False)
            ok = Path(mesh_file_path).is_file()
            loading_status_cb(ReloadMeshStatus.SUCCESS if ok else ReloadMeshStatus.ERROR)

        world.deferred.append(finish)

    def execute_when_not_busy(callback: Any) -> None:
        def run() -> None:
            if world.busy:
                world.deferred.append(run)
            else:
                callback()

        world.deferred.append(run)

    def update_layer_stack_resource(old_resource_id: Any, new_resource: Any) -> list[Any]:
        world.require_open()
        replaced: list[Any] = []
        for item in world.items.values():
            for key, source in list(item.sources.items()):
                if isinstance(source, SourceBitmap) and source.rid.url() == old_resource_id.url():
                    item.sources[key] = SourceBitmap(new_resource.identifier())
                    replaced.append(source.rid)
        return replaced

    def used_bitmaps() -> list[Any]:
        return [
            source.rid
            for item in world.items.values()
            for source in item.sources.values()
            if isinstance(source, SourceBitmap)
        ]

    def reload_modified_resources_async(resource_filter: Any) -> bool:
        if world.reloading:
            return False
        world.reloading = True
        world.emit(events["ReloadResourcesStarted"](resource_filter))
        reloaded = (
            [ReloadedResourceResult(rid, rid) for rid in used_bitmaps()]
            if isinstance(resource_filter, ResourcesUsedByProjectFilter)
            else []
        )

        def finish() -> None:
            world.reloading = False
            world.emit(events["ReloadResourcesEnded"](resource_filter, reloaded, []))

        world.deferred.append(finish)
        return True

    def enable_engine_computations(enable: bool) -> None:
        if world.engine != enable:
            world.engine = enable
            world.emit(events["EngineComputationsStatusChanged"](enable))

    @contextmanager
    def disable_engine_computations() -> Iterator[None]:
        enable_engine_computations(False)
        try:
            yield
        finally:
            enable_engine_computations(True)

    export_before = export.export_project_textures

    def export_project_textures(config: dict[str, Any]) -> Any:
        world.emit(events["ExportTexturesAboutToStart"]({}))
        result = export_before(config)
        world.emit(events["ExportTexturesEnded"](result.status, result.message, result.textures))
        return result

    project.is_busy = is_busy
    project.save_as_copy = save_as_copy
    project.reload_mesh = reload_mesh
    project.execute_when_not_busy = execute_when_not_busy
    project.MeshReloadingSettings = MeshReloadingSettings
    project.ReloadMeshStatus = ReloadMeshStatus
    resource.update_layer_stack_resource = update_layer_stack_resource
    resource.reload_modified_resources_async = reload_modified_resources_async
    resource.is_reload_modified_resources_running = lambda: world.reloading
    resource.AllResourcesFilter = AllResourcesFilter
    resource.ProjectFilter = ProjectFilter
    resource.ResourcesListFilter = ResourcesListFilter
    resource.ResourcesUsedByProjectFilter = ResourcesUsedByProjectFilter
    resource.SessionFilter = SessionFilter
    application.enable_engine_computations = enable_engine_computations
    application.disable_engine_computations = disable_engine_computations
    application.engine_computations_status = lambda: world.engine
    export.export_project_textures = export_project_textures


def extend_host(world: ProbeWorld, events: dict[str, type]) -> None:
    """Shelves, resource search, the default export path and the display LUT reset (the host
    behaviour probes of decisions 110 and 132, and R-095 P7)."""
    modules = world.modules
    resource = modules["substance_painter.resource"]
    display = modules["substance_painter.display"]
    export = modules["substance_painter.export"]
    project = modules["substance_painter.project"]

    class Shelf:
        def __init__(self, name: str) -> None:
            self.shelf_name = name

        def name(self) -> str:
            return self.shelf_name

        def path(self) -> str:
            paths = {"starter_assets": APPLICATION_SHELF_PATH, "your_assets": USER_SHELF_PATH}
            if self.shelf_name in world.shelves:
                return world.shelves[self.shelf_name]
            if self.shelf_name not in paths:
                raise ValueError("the shelf doesn't exist anymore")
            return paths[self.shelf_name]

        def is_crawling(self) -> bool:
            return self.shelf_name in world.crawling

        def refresh(self) -> None:
            crawl(self.shelf_name)

    def crawl(name: str) -> None:
        """A crawl starts at once and ends on the next queued-task poll (the fake's rule)."""
        world.crawling.add(name)
        world.emit(events["ShelfCrawlingStarted"](name))

        def finish() -> None:
            world.crawling.discard(name)
            world.emit(events["ShelfCrawlingEnded"](name))

        world.deferred.append(finish)

    class Shelves:
        @staticmethod
        def all() -> list[Shelf]:
            return [Shelf(n) for n in ("starter_assets", "your_assets", *world.shelves)]

        @staticmethod
        def application_shelf() -> Shelf:
            return Shelf("starter_assets")

        @staticmethod
        def user_shelf() -> Shelf:
            return Shelf("your_assets")

        @staticmethod
        def exists(name: str) -> bool:
            return name in ("starter_assets", "your_assets", *world.shelves)

        @staticmethod
        def add(name: str, path: str) -> Shelf:
            if Shelves.exists(name) or not all(
                c.islower() or c.isdigit() or c in "_-" for c in name
            ):
                raise ValueError(f"invalid shelf name {name!r}")
            world.shelves[name] = path
            crawl(name)
            return Shelf(name)

        @staticmethod
        def remove(name: str) -> None:
            if world.project_open:
                raise ProjectError("a project is opened")
            if name not in world.shelves:
                raise ValueError("the shelf doesn't exist or was not created with the Python API")
            del world.shelves[name]

    @dataclass
    class Resource:
        rid: Any
        usage: Any

        def identifier(self) -> Any:
            return self.rid

        def gui_name(self) -> str:
            return str(self.rid.name)

        def usages(self) -> list[Any]:
            return [self.usage]

    def search(query: str) -> list[Resource]:
        """The fake's export presets for a query naming `u:export`; nothing otherwise."""
        if "u:export" not in query.split():
            return []
        return [
            Resource(resource.ResourceID.from_url(url), resource.Usage.TEXTURE)
            for url in world.resource_presets
        ]

    resource.Shelf, resource.Shelves, resource.Resource = Shelf, Shelves, Resource
    resource.search = search
    lut_before = display.set_color_lut_resource

    def set_color_lut_resource(rid: Any) -> None:
        if rid is None:
            world.color_lut = None
        else:
            lut_before(rid)

    display.set_color_lut_resource = set_color_lut_resource
    export.get_default_export_path = lambda: DEFAULT_EXPORT_PATH
    project.ProjectError = ProjectError


def module(name: str, **members: Any) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in members.items():
        setattr(mod, key, value)
    return mod


# --- P22-B: channels, texture sets, project metadata and export status (decision 295) -------------


def p295_snapshot(world: ProbeWorld) -> dict[str, Any]:
    """What a save keeps of the P22-B state: channel labels, the texture-set description, the
    project UUID and its metadata."""
    return {
        "labels": {kind.name: label for kind, label in world.channel_labels.items()},
        "description": world.description,
        "uuid": None if world.project_uuid is None else str(world.project_uuid),
        "metadata": world.metadata,
    }


def p295_restore(world: ProbeWorld, data: dict[str, Any]) -> None:
    world.channel_labels = {ChannelType[name]: label for name, label in data["labels"].items()}
    world.description = data["description"]
    world.project_uuid = None if data["uuid"] is None else uuid.UUID(data["uuid"])
    world.metadata = json.loads(json.dumps(data["metadata"]))


def extend_p295(world: ProbeWorld, events: dict[str, type]) -> None:
    """Stack channel edits, `Channel.type`/`edit`, the texture-set description, layering and
    resolution, project UUID and metadata, and a failing export (the fake's authored rules: a
    channel exists once, only `User*` channels take a label, a resolution is a power of two from
    128 to 4096, a project gets a new UUID at create, and an export under a regular file fails
    with `ExportTexturesEnded(Error)` and raises)."""
    modules = world.modules
    textureset = modules["substance_painter.textureset"]
    project = modules["substance_painter.project"]
    export = modules["substance_painter.export"]
    world.channel_labels = {}
    world.description = ""
    world.project_uuid = None
    world.metadata = {}

    def require_channel(kind: Any) -> None:
        if kind not in world.channels:
            raise ValueError(f"there is no channel of type {kind.name} in this Texture Set")

    def check_label(kind: Any, label: str | None) -> None:
        if label is not None and not kind.name.startswith("User"):
            raise ValueError("a label was provided but the channel type is not a user type")

    class Channel:
        def __init__(self, kind: Any) -> None:
            self.kind = kind

        def type(self) -> Any:
            return self.kind

        def format(self) -> Any:
            require_channel(self.kind)
            return world.channels[self.kind]

        def label(self) -> str:
            return str(world.channel_labels.get(self.kind, ""))

        def edit(self, channel_format: Any, label: str | None = None) -> None:
            edit_channel(None, self.kind, channel_format, label)

    def add_channel(self: Any, kind: Any, channel_format: Any, label: str | None = None) -> Any:
        world.require_open()
        if kind in world.channels:
            raise ValueError(f"a channel of type {kind.name} already exists in this Texture Set")
        check_label(kind, label)
        world.channels[kind] = channel_format
        if label is not None:
            world.channel_labels[kind] = label
        return Channel(kind)

    def edit_channel(self: Any, kind: Any, channel_format: Any, label: str | None = None) -> None:
        world.require_open()
        require_channel(kind)
        check_label(kind, label)
        world.channels[kind] = channel_format
        if label is not None:
            world.channel_labels[kind] = label

    def remove_channel(self: Any, kind: Any) -> None:
        world.require_open()
        require_channel(kind)
        del world.channels[kind]
        world.channel_labels.pop(kind, None)

    def has_channel(self: Any, kind: Any) -> bool:
        world.require_open()
        return kind in world.channels

    def get_channel(self: Any, kind: Any) -> Channel:
        world.require_open()
        require_channel(kind)
        return Channel(kind)

    stack = textureset.Stack
    stack.add_channel, stack.edit_channel = add_channel, edit_channel
    stack.remove_channel, stack.has_channel, stack.get_channel = (
        remove_channel,
        has_channel,
        get_channel,
    )

    def get_description(self: Any) -> str:
        world.require_open()
        return str(world.description)

    def set_description(self: Any, value: str) -> None:
        world.require_open()
        world.description = value

    def set_resolution(self: Any, resolution: Any) -> None:
        sizes = (128, 256, 512, 1024, 2048, 4096)
        if resolution.width not in sizes or resolution.height not in sizes:
            raise ValueError("the resolution is not a valid resolution")
        world.set_resolution(self.name(), (resolution.width, resolution.height))

    texture_set = textureset.TextureSet
    texture_set.description = property(get_description, set_description)
    texture_set.is_layered_material = lambda self: False
    texture_set.set_resolution = set_resolution

    class Metadata:
        def __init__(self, context: str) -> None:
            self.context = context

        def entries(self) -> dict[str, Any]:
            world.require_open()
            entries: dict[str, Any] = world.metadata.setdefault(self.context, {})
            return entries

        def list(self) -> Any:
            return [*self.entries()]

        def get(self, key: str) -> Any:
            return self.entries().get(key)

        def set(self, key: str, value: Any) -> None:
            self.entries()[key] = json.loads(json.dumps(value))

    def get_uuid() -> uuid.UUID:
        world.require_open()
        value: uuid.UUID = world.project_uuid
        return value

    create_before = project.create

    def create(mesh_file_path: str, settings: Any, **others: Any) -> None:
        create_before(mesh_file_path=mesh_file_path, settings=settings, **others)
        world.channel_labels, world.description, world.metadata = {}, "", {}
        world.project_uuid = uuid.uuid4()

    project.create, project.get_uuid, project.Metadata = create, get_uuid, Metadata
    export_before = export.export_project_textures

    def export_project_textures(config: dict[str, Any]) -> Any:
        target = config.get("exportPath")
        if target is not None and Path(str(target)).is_file():
            world.emit(events["ExportTexturesAboutToStart"]({}))
            message = "fake: the export path is a regular file"
            world.emit(events["ExportTexturesEnded"](ExportStatus.Error, message, {}))
            raise RuntimeError(message)
        return export_before(config)

    export.export_project_textures = export_project_textures
