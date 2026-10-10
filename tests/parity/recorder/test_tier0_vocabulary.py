"""Recorder vocabulary of the Tier 0 semantics goldens (`phase0.6_tier0-semantics-goldens`).

`painter_side.py` runs here against a small fake layer tree (groups, content and mask effects,
levels, filters, UV projection, channel edits) built on the shared fake Painter's modules. The
fake only stores what the documented calls set; it does not composite.
"""

from __future__ import annotations

import enum
import types
from dataclasses import dataclass, field
from typing import Any

import pytest

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.job import parse_output_map
from tools.parity.recorder.session import PAINTER_SIDE
from tools.parity.recorder.texture import channel_encoding

ChannelType = enum.Enum(
    "ChannelType",
    "BaseColor Normal Height AO Scattering User0 User1 User2 User3 User4 User5 User6 User7",
)


class NodeStack(enum.Enum):
    Substack = 1
    Content = 2
    Mask = 3


class FilteringMode(enum.Enum):
    BilinearHQ = 1
    BilinearSharp = 2
    Nearest = 3


class UVWrapMode(enum.Enum):
    RepeatNone = 1
    RepeatHorizontally = 2
    RepeatVertically = 3
    Repeat = 4


class ScaleMode(enum.Enum):
    Factors = 1


class ProjectionMode(enum.Enum):
    UV = 1


class MaskBackground(enum.Enum):
    Black = 1
    White = 2


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
    uv_transformation: Any = None


@dataclass
class LevelsParamsMono:
    input_min: float = 0.0
    input_max: float = 1.0
    gamma: float = 1.0
    output_min: float = 0.0
    output_max: float = 1.0
    clamp: bool = False


class Tree:
    """Root layers (top first) per texture set, and a uid counter."""

    def __init__(self, fake: types.ModuleType) -> None:
        self.fake = fake
        self.roots: dict[str, list[Node]] = {"s0": [], "s1": []}
        self.next_uid = 1
        self.added: list[tuple[str, str, str]] = []

    def uid(self) -> int:
        self.next_uid += 1
        return self.next_uid


@dataclass(eq=False)
class Node:
    tree: Tree
    texture_set: str
    tag: str
    parent: Node | None = None
    in_mask: bool = False
    uid_value: int = 0
    sub: list[Node] = field(default_factory=list)
    content: list[Node] = field(default_factory=list)
    mask: list[Node] = field(default_factory=list)
    has_mask_value: bool = False
    blending: dict[Any, tuple[Any, float]] = field(default_factory=dict)
    channels: set[Any] = field(default_factory=set)
    sources: dict[Any, Any] = field(default_factory=dict)
    channel: Any = None
    params: Any = None
    projection: Any = None

    def get_parent(self) -> Node | None:
        return self.parent

    def is_in_mask_stack(self) -> bool:
        return self.in_mask

    def uid(self) -> int:
        return self.uid_value

    def get_stack(self) -> Any:
        return self.tree.fake_stack(self.texture_set)  # type: ignore[attr-defined]

    def sub_layers(self) -> list[Node]:
        return list(self.sub)

    def content_effects(self) -> list[Node]:
        return list(self.content)

    def mask_effects(self) -> list[Node]:
        return list(self.mask)

    def check_channel(self, channel: Any) -> None:
        if (channel is None) != self.in_mask:
            raise ValueError("channel must be None exactly in a mask stack")

    def set_blending_mode(self, mode: Any, channel: Any = None) -> None:
        self.check_channel(channel)
        self.blending[channel] = (mode, self.blending.get(channel, (mode, 1.0))[1])

    def get_blending_mode(self, channel: Any = None) -> Any:
        self.check_channel(channel)
        return self.blending.get(channel, (self.tree.fake.BlendingMode.Normal, 1.0))[0]

    def set_opacity(self, opacity: float, channel: Any = None) -> None:
        self.check_channel(channel)
        self.blending[channel] = (self.get_blending_mode(channel), opacity)

    def get_opacity(self, channel: Any = None) -> float:
        self.check_channel(channel)
        return self.blending.get(channel, (None, 1.0))[1]

    @property
    def active_channels(self) -> set[Any]:
        return set(self.channels)

    @active_channels.setter
    def active_channels(self, channels: set[Any]) -> None:
        self.channels = set(channels)

    @property
    def source_mode(self) -> Any:
        return None

    def set_source(self, channel: Any, source: Any) -> None:
        self.check_channel(channel)
        self.sources[channel] = source

    def get_source(self, channel: Any) -> Any:
        source = self.sources[channel]
        if isinstance(source, self.tree.fake.Color):
            return self.tree.fake.SourceUniformColor(source)
        return SourceBitmap(source.url())

    def add_mask(self, background: Any) -> None:
        self.has_mask_value = True

    @property
    def affected_channel(self) -> Any:
        return self.channel

    @affected_channel.setter
    def affected_channel(self, channel: Any) -> None:
        self.channel = channel

    def get_parameters(self) -> LevelsParamsMono:
        return LevelsParamsMono(**vars(self.params))

    def set_parameters(self, params: LevelsParamsMono) -> None:
        self.params = params

    def set_projection_parameters(self, params: UVProjectionParams) -> None:
        self.projection = params

    def get_projection_parameters(self) -> UVProjectionParams:
        assert isinstance(self.projection, UVProjectionParams)
        return self.projection

    def get_projection_mode(self) -> ProjectionMode:
        return ProjectionMode.UV


class GroupLayerNode(Node):
    pass


class SourceBitmap:
    def __init__(self, url: str) -> None:
        self.url = url

    @property
    def resource_id(self) -> Any:
        return types.SimpleNamespace(url=lambda: self.url)

    def get_color_space(self) -> str:
        return "fake-space"

    def list_available_color_spaces(self) -> list[str]:
        return ["fake-space"]


@dataclass
class InsertPosition:
    texture_set: str | None = None
    node: Node | None = None
    stack: Any = None
    relative: int = 0  # 1 above, -1 below, 0 inside or top

    @staticmethod
    def from_textureset_stack(stack: Any) -> InsertPosition:
        return InsertPosition(texture_set=stack.texture_set)

    @staticmethod
    def above_node(node: Node) -> InsertPosition:
        return InsertPosition(node=node, relative=1)

    @staticmethod
    def below_node(node: Node) -> InsertPosition:
        return InsertPosition(node=node, relative=-1)

    @staticmethod
    def inside_node(node: Node, stack: NodeStack) -> InsertPosition:
        return InsertPosition(node=node, stack=stack)


def install_tree(world: Any, fake: types.ModuleType) -> Tree:
    tree = Tree(fake)

    class Stack:
        def __init__(self, texture_set: str) -> None:
            self.texture_set = texture_set

        @staticmethod
        def from_name(texture_set_name: str, stack_name: str = "") -> Stack:
            return Stack(texture_set_name)

        def name(self) -> str:
            return ""

        def material(self) -> Any:
            return types.SimpleNamespace(name=lambda: self.texture_set)

        def all_channels(self) -> dict[Any, Any]:
            return {ChannelType.BaseColor: None}

        def add_channel(self, kind: Any, channel_format: Any) -> None:
            tree.added.append((self.texture_set, kind.name, channel_format.name))

        def edit_channel(self, kind: Any, channel_format: Any) -> None:
            tree.added.append((self.texture_set, kind.name, "edit:" + channel_format.name))

    tree.fake_stack = Stack  # type: ignore[attr-defined]

    def insert(position: InsertPosition, kind: type[Node], tag: str) -> Node:
        if position.node is None:
            assert position.texture_set is not None
            node = kind(tree, position.texture_set, tag, uid_value=tree.uid())
            tree.roots[position.texture_set].insert(0, node)
            return node
        anchor = position.node
        if position.relative == 0:
            target = {
                NodeStack.Substack: anchor.sub,
                NodeStack.Content: anchor.content,
                NodeStack.Mask: anchor.mask,
            }[position.stack]
            parent: Node | None = anchor
            in_mask, index = position.stack == NodeStack.Mask, 0
        else:
            parent, in_mask = anchor.parent, anchor.in_mask
            if parent is None:
                target = tree.roots[anchor.texture_set]
            elif anchor.in_mask:
                target = parent.mask
            elif anchor in parent.sub:
                target = parent.sub
            else:
                target = parent.content
            index = target.index(anchor) + (0 if position.relative == 1 else 1)
        node = kind(tree, anchor.texture_set, tag, parent, in_mask, tree.uid())
        target.insert(index, node)
        return node

    textureset = world.modules["substance_painter.textureset"]
    textureset.Stack = Stack
    textureset.ChannelType = ChannelType
    textureset.ChannelFormat = enum.Enum(  # type: ignore[misc]
        "ChannelFormat", "sRGB8 L8 RGB8 L16 RGB16 L16F RGB16F L32F RGB32F"
    )
    textureset.all_texture_sets = lambda: [
        types.SimpleNamespace(get_stack=lambda name=n: Stack(name)) for n in tree.roots
    ]
    layerstack = world.modules["substance_painter.layerstack"]
    layerstack.InsertPosition = InsertPosition
    layerstack.NodeStack = NodeStack
    layerstack.GroupLayerNode = GroupLayerNode
    layerstack.FilteringMode = FilteringMode
    layerstack.UVWrapMode = UVWrapMode
    layerstack.ScaleMode = ScaleMode
    layerstack.UVTransformationParams = UVTransformationParams
    layerstack.UVProjectionParams = UVProjectionParams
    layerstack.MaskBackground = MaskBackground
    layerstack.insert_fill = lambda position: insert(position, Node, "fill")
    layerstack.insert_group = lambda position: insert(position, GroupLayerNode, "group")

    def insert_levels(position: InsertPosition) -> Node:
        node = insert(position, Node, "levels")
        node.channel, node.params = ChannelType.BaseColor, LevelsParamsMono()
        return node

    layerstack.insert_levels_effect = insert_levels
    layerstack.insert_filter_effect = lambda position, rid: insert(position, Node, rid.url())
    layerstack.get_root_layer_nodes = lambda stack: list(tree.roots[stack.texture_set])
    resource = world.modules["substance_painter.resource"]
    resource.search = lambda query: (
        [types.SimpleNamespace(identifier=lambda: resource.ResourceID("blur", "starter"))]
        if query == "s:starterassets u:filter n:Blur="
        else []
    )
    world.modules["substance_painter.source"].SourceBitmap = SourceBitmap
    return tree


@pytest.fixture
def side(fake: types.ModuleType) -> Any:
    """`painter_side.py` executed against the tree fake; yields (namespace, tree)."""
    world = fake.FakeWorld()
    world.project_open = True
    tree = install_tree(world, fake)
    with fake.installed(world):
        namespace: dict[str, Any] = {"__name__": "painter_side"}
        exec(
            compile(PAINTER_SIDE.read_text(encoding="utf-8"), "painter_side.py", "exec"), namespace
        )
        namespace["RESOURCES"][1] = types.SimpleNamespace(
            identifier=lambda: world.modules["substance_painter.resource"].ResourceID("field-a")
        )
        yield namespace, tree


def apply(namespace: dict[str, Any], step: int, call: str, **args: Any) -> dict[str, Any]:
    result: dict[str, Any] = namespace["apply_step"]({"step": step, "call": call, "args": args})
    return result


def build(namespace: dict[str, Any]) -> None:
    """A fill with a content levels effect and a mask fill effect, a group with a child."""
    apply(namespace, 2, ps.INSERT_FILL, position="top", texture_set="s1")
    apply(namespace, 3, ps.INSERT_LEVELS, inside_step=2, stack="Content")
    apply(namespace, 4, ps.SET_LEVELS_CHANNEL, node_step=3, channel="User1")
    apply(namespace, 5, ps.SET_LEVELS, node_step=3, input_min=0.25, gamma=0.5, clamp=True)
    apply(namespace, 6, ps.ADD_MASK, node_step=2, background="Black")
    apply(namespace, 7, ps.INSERT_FILL, inside_step=2, stack="Mask")
    apply(namespace, 8, ps.SET_EFFECT_SOURCE, node_step=7, channel=None, resource_step=1)
    apply(namespace, 9, ps.SET_BLENDING_MODE, node_step=7, blending_mode="Multiply", channel=None)
    apply(namespace, 10, ps.INSERT_GROUP, above_step=2)
    apply(
        namespace,
        11,
        ps.SET_BLENDING_MODE,
        node_step=10,
        blending_mode="Screen",
        channel="User0",
    )
    apply(namespace, 12, ps.INSERT_FILL, inside_step=10, stack="Substack")
    apply(
        namespace,
        13,
        ps.INSERT_FILTER,
        above_step=3,
        filter_search="s:starterassets u:filter n:Blur=",
    )


def test_insert_positions_place_nodes_in_their_stacks(side: Any) -> None:
    namespace, tree = side
    build(namespace)
    fill, group = tree.roots["s1"][1], tree.roots["s1"][0]
    assert [n.tag for n in tree.roots["s1"]] == ["group", "fill"] and tree.roots["s0"] == []
    assert [n.tag for n in fill.content] == ["resource://starter/blur", "levels"]  # top first
    assert [n.tag for n in fill.mask] == ["fill"] and fill.mask[0].in_mask and fill.has_mask_value
    assert [n.tag for n in group.sub] == ["fill"] and isinstance(group, GroupLayerNode)
    assert group.blending[namespace["channel_type"]("User0")][0].name == "Screen"
    assert fill.mask[0].blending[None][0].name == "Multiply"


def test_levels_mask_source_and_projection_are_set_and_read_back(side: Any) -> None:
    namespace, _ = side
    build(namespace)
    levels = namespace["readback"]({"call": ps.GET_LEVELS, "args": {"node_step": 3}})
    assert levels == {
        "affected_channel": "User1",
        "parameters": {
            "input_min": 0.25,
            "input_max": 1.0,
            "gamma": 0.5,
            "output_min": 0.0,
            "output_max": 1.0,
            "clamp": True,
        },
    }
    source = namespace["readback"](
        {"call": ps.GET_EFFECT_SOURCE, "args": {"node_step": 7, "channel": None}}
    )
    assert source["bitmap"]["resource_url"] == "resource://project0/field-a"
    apply(
        namespace,
        14,
        ps.SET_PROJECTION,
        node_step=2,
        filtering_mode="BilinearHQ",
        uv_wrapping_mode="Repeat",
        scale_mode="Factors",
        scale=[2, 3],
        rotation=30,
        offset=[0.5, 0.25],
    )
    assert namespace["readback"]({"call": ps.GET_PROJECTION, "args": {"node_step": 2}}) == {
        "projection_mode": "UV",
        "filtering_mode": "BilinearHQ",
        "uv_wrapping_mode": "Repeat",
        "scale_mode": "Factors",
        "scale": [2.0, 3.0],
        "rotation": 30.0,
        "offset": [0.5, 0.25],
    }


def test_channel_steps_reach_the_named_or_every_texture_set(side: Any) -> None:
    namespace, tree = side
    apply(namespace, 2, ps.ADD_CHANNEL, channel="User7", format="RGB32F")
    apply(namespace, 3, ps.EDIT_CHANNEL, channel="Scattering", format="L16F", texture_set="s1")
    assert tree.added == [
        ("s0", "User7", "RGB32F"),
        ("s1", "User7", "RGB32F"),
        ("s1", "Scattering", "edit:L16F"),
    ]


def test_unknown_filter_search_is_refused(side: Any) -> None:
    namespace, _ = side
    apply(namespace, 2, ps.INSERT_FILL, position="top", texture_set="s0")
    with pytest.raises(ValueError, match="no resource matches"):
        apply(namespace, 3, ps.INSERT_FILTER, inside_step=2, stack="Content", filter_search="n:x")


def test_nested_nodes_are_found_again_after_reopen(side: Any) -> None:
    namespace, tree = side
    build(namespace)
    locations = namespace["node_locations"]({})
    assert locations["7"]["path"] == [["root", 1], ["mask_effects", 0]]
    assert locations["12"]["path"] == [["root", 0], ["sub_layers", 0]]
    assert locations["13"]["path"] == [["root", 1], ["content_effects", 0]]
    assert locations["3"]["path"] == [["root", 1], ["content_effects", 1]]
    tags = {step: id(node) for step, node in namespace["NODES"].items()}
    for roots in tree.roots.values():  # reopening gives every node a new uid
        pending = list(roots)
        while pending:
            node = pending.pop()
            node.uid_value += 1000
            pending += node.sub + node.content + node.mask
    namespace["NODES"].clear()
    assert namespace["rebind_nodes"]({"locations": locations}) == {"rebound": len(tags)}
    assert {step: id(node) for step, node in namespace["NODES"].items()} == tags


def test_virtual_maps_take_the_encoding_of_their_source_channel() -> None:
    template = {
        "texture_sets": {
            "s0": {"stacks": {"": {"AO": {"format": "L16"}, "Normal": {"format": "RGB16F"}}}}
        }
    }
    for spec in (
        "virtualMap/AO_Mixed:L",
        "documentMap/ambientOcclusion:L",
        "virtualMap/Normal_OpenGL:RGB",
    ):
        assert channel_encoding(template, "s0", "", parse_output_map(spec)) == "linear"
