"""A fake layer-stack tree, events and resources for the API-probe recorder tests (no Painter).

`ProbeWorld` extends the recorder's `FakeWorld` (`fake_painter.py`) with the documented surface
`painter_probes.py` uses: groups, content and mask stacks, effects, insertion rules, masks,
bitmap sources, levels, mesh maps and project events. The behaviour is simple and authored for
the tests (it states what the fake does, not what Painter does): the multichannel/mask rules raise
`EditionContextException` or `ValueError`, assigning `active_channels` clears the fill's sources,
and every node gets a new uid when a project is reopened.
"""

from __future__ import annotations

import enum
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from uzp_recorder_fake_painter import (  # type: ignore[import-not-found]
    BlendingMode,
    ChannelType,
    Color,
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


LAYER_KINDS = (NodeType.FillLayer, NodeType.GroupLayer)
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
        for callback in list(self.listeners.get(type(event), [])):
            callback(event)

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

    classes = {
        NodeType.FillLayer: FillLayerNode,
        NodeType.FillEffect: FillEffectNode,
        NodeType.GroupLayer: GroupLayerNode,
        NodeType.LevelsEffect: LevelsEffectNode,
        NodeType.CompareMaskEffect: CompareMaskEffectNode,
        NodeType.ColorSelectionEffect: ColorSelectionEffectNode,
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

    def get_root_layer_nodes(stack: Any) -> list[Any]:
        return [handle(item) for item in world.roots]

    def get_node_by_uid(uid: int) -> Any:
        return handle(world.item(uid))

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
        get_root_layer_nodes=get_root_layer_nodes,
        get_node_by_uid=get_node_by_uid,
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

    root = modules["substance_painter"]
    root.layerstack = modules["substance_painter.layerstack"]
    root.event = modules["substance_painter.event"]


def module(name: str, **members: Any) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key, value in members.items():
        setattr(mod, key, value)
    return mod
