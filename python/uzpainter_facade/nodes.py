"""`substance_painter.layerstack` and `substance_painter.source`: nodes, sources, insertion,
selection and `ScopedModification` with Painter's quirks (10 §4 Quirks row; decision 107;
`python/FACADE.md` §3).

Painter's quirks reproduced here, each from a Tier 0 api-probe golden:
- Assigning `active_channels` resets the source of every channel of the new set to the channel's
  default (`active-channel-reset`, `active-channel-reset-superset`; the control
  `active-channel-order-control` keeps them). The native API keeps them (LAY-01): both behaviours
  are documented side by side. Setting a source on an inactive channel activates it without a
  reset (`set-source-none-multichannel` s17-s19).
- Channel contexts: a content-stack fill takes a channel (None raises EditionContextException
  "Only valid in mono channel context"); a mask-stack fill takes None (a channel raises
  EditionContextException "Channel <n> isn't valid in this context"); blending and opacity of a
  mask-stack node take None (ValueError), of a content node a channel (ValueError); a node
  without blending raises ValueError (`mask-stack`, `set-source-none-multichannel`).
- Insertion positions raise ValueError with Painter's messages (`insert-positions`).
- Default names: "Fill", "Folder", "Levels" ("Levels - Base color" in a content stack, whose
  levels affect BaseColor) and "Compare mask" (`insert-positions`).

Each facade call commits one revision (`state.one_transaction`); `ScopedModification` groups calls
without rolling back. Nothing evaluates until an export asks for it, so there is no per-call
invalidation to batch.

`LayerStacksModelDataChanged` is delivered before the call returns by the calls the Tier 0 R10
probes record emitting it: `insert_fill` (layer or effect), `insert_group`, `set_name`,
`delete_node` and `add_mask` (`structural`). The recorded silent ones stay silent
(`active_channels`, `set_source`); every other edit call is unrecorded, emits nothing, and is
named with its recording P21-E in decision 110.
"""

from __future__ import annotations

import dataclasses
import enum
import functools
from collections.abc import Callable, Iterable
from typing import Any

import uzpainter

from uzpainter_facade import colour, event, levels, resource
from uzpainter_facade.state import SESSION, edits, one_transaction
from uzpainter_facade.textureset import Stack, TextureSet, native_of


def structural[F: Callable[..., Any]](function: F) -> F:
    """Marks a call Painter answers with `LayerStacksModelDataChanged` once it is committed."""

    @functools.wraps(function)
    def call(*args: Any, **kwargs: Any) -> Any:
        result = function(*args, **kwargs)
        event.emit_sync(event.LayerStacksModelDataChanged())
        return result

    return call  # type: ignore[return-value]


LAYERSTACK = "substance_painter.layerstack"
SOURCE = "substance_painter.source"
_ls = uzpainter.layerstack
ChannelType = uzpainter.textureset.ChannelType

# The default source of a channel after a reset, in the working space (`active-channel-reset`,
# `active-channel-reset-superset`: BaseColor 0.8 grey, Height 0, both recordings). Every other
# channel's default is unrecorded: its native source is removed, and reading it or exporting it
# raises NotYetSupported until the defaults probe (colour.CHANNEL_DEFAULTS_PROBE) is recorded.
DEFAULT_SOURCES: dict[str, tuple[float, float, float]] = {
    "BaseColor": (0.8, 0.8, 0.8),
    "Height": (0.0, 0.0, 0.0),
}
# Painter's channel numbers in its context errors ("Channel 0 isn't valid in this context" for
# BaseColor, `mask-stack` s15, s17, s26); other channels are named.
PAINTER_CHANNEL_NUMBERS = {"BaseColor": 0}

MONO_CONTEXT = "Only valid in mono channel context"
MULTI_CONTEXT = "Only valid in multi channel context"
MASK_BLENDING = "This node is part of a mask stack and does not support Channel Types for blending"
CONTENT_BLENDING = "This node is not part of a mask stack, a Channel Type must be specified"
NO_BLENDING = "This node does not support channel blending information"


def channel_error(channel: Any) -> Exception:
    number = PAINTER_CHANNEL_NUMBERS.get(channel.name, channel.name)
    error: Exception = uzpainter.EditionContextException(
        f"Channel {number} isn't valid in this context"
    )
    return error


def unrecorded_default(channel: Any) -> Exception:
    name = "the mask source" if channel is None else channel.name
    error: Exception = uzpainter.NotYetSupported(
        f"Painter's default source of {name} is not recorded: set it before reading or exporting "
        f"it ({colour.CHANNEL_DEFAULTS_PROBE}; phase1.14_compositor-core)"
    )
    return error


def colour_managed(native_node: Any, channel: Any) -> bool:
    """Whether `channel` of the node's stack is colour managed: an sRGB8 channel."""
    if channel is None:
        return False
    stack = native_node.get_stack()
    if not stack.has_channel(channel):
        return False
    return bool(stack.get_channel(channel).format() == uzpainter.textureset.ChannelFormat.sRGB8)


# ── Projection parameters (Painter's dataclasses) ────────────────────────────────────────────


@dataclasses.dataclass
class UVTransformationParams:
    """The UV transformation of a projection."""

    scale_mode: Any = None
    scale: list[float] | None = None
    rotation: float | None = None
    offset: list[float] | None = None


@dataclasses.dataclass
class UVProjectionParams:
    """The parameters of the UV projection."""

    filtering_mode: Any = None
    uv_wrapping_mode: Any = None
    uv_transformation: UVTransformationParams = dataclasses.field(
        default_factory=UVTransformationParams
    )


for _params in (UVTransformationParams, UVProjectionParams):
    _params.__module__ = LAYERSTACK


def projection_to_native(params: Any) -> Any:
    if not isinstance(params, UVProjectionParams):
        raise uzpainter.NotYetSupported(
            f"{type(params).__name__}: projection parameters other than UVProjectionParams are "
            "release gaps (phase3.4_smart-projections, phase4.1_nodes-projections)"
        )
    t = params.uv_transformation
    return _ls.UVProjectionParams(
        filtering_mode=params.filtering_mode,
        uv_wrapping_mode=params.uv_wrapping_mode,
        uv_transformation=_ls.UVTransformationParams(
            scale_mode=t.scale_mode,
            scale=None if t.scale is None else [float(v) for v in t.scale],
            rotation=None if t.rotation is None else float(t.rotation),
            offset=None if t.offset is None else [float(v) for v in t.offset],
        ),
    )


def projection_from_native(native: Any) -> UVProjectionParams:
    t = native.uv_transformation
    return UVProjectionParams(
        filtering_mode=native.filtering_mode,
        uv_wrapping_mode=native.uv_wrapping_mode,
        uv_transformation=UVTransformationParams(
            scale_mode=t.scale_mode,
            scale=None if t.scale is None else list(t.scale),
            rotation=t.rotation,
            offset=None if t.offset is None else list(t.offset),
        ),
    )


# ── Sources (`substance_painter.source`) ────────────────────────────────────────────────────────


class SourceUniformColor:
    """A uniform colour source of a fill."""

    __slots__ = ("_channel", "_node")

    def __init__(self, node: int, channel: Any) -> None:
        self._node = node
        self._channel = channel

    def _native(self) -> Any:
        source = _ls.get_node_by_uid(self._node).get_source(self._channel)
        if source is None:
            raise ValueError("stale source: the fill no longer has this uniform colour source")
        return source

    def get_color(self) -> colour.Color:
        return colour.read_color(self._native().get_color())

    @edits
    def set_color(self, color: Any) -> None:
        managed = colour_managed(_ls.get_node_by_uid(self._node), self._channel)
        self._native().set_color(colour.stored_color(color, managed))

    def __repr__(self) -> str:
        return f"SourceUniformColor({self._node}, {self._channel})"


class SourceBitmap:
    """A bitmap source of a fill."""

    __slots__ = ("_channel", "_node")

    def __init__(self, node: int, channel: Any) -> None:
        self._node = node
        self._channel = channel

    def _native(self) -> Any:
        source = _ls.get_node_by_uid(self._node).get_source(self._channel)
        if source is None:
            raise ValueError("stale source: the fill no longer has this bitmap source")
        return source

    def _key(self) -> tuple[Any, ...]:
        return ("source", self._node, None if self._channel is None else self._channel.name)

    @property
    def resource_id(self) -> resource.ResourceID:
        native = self._native().resource_id()
        return resource.from_native(native, SESSION.bound_context.get(self._key()))

    def get_color_space(self) -> Any:
        return colour.space_member(self._native().get_color_space())

    @edits
    def set_color_space(self, color_space: Any) -> None:
        name = colour.space_name(color_space)
        available = [colour.space_name(s) for s in self.list_available_color_spaces()]
        if name not in available:
            raise ValueError(f"'{name}' is not an available colour space here ({available})")
        self._native().set_color_space(name)

    @edits
    def reset_color_space(self) -> None:
        native = self._native()
        sha256 = native.resource_id().version
        space = colour.default_bitmap_space(
            None if self._channel is None else self._channel.name,
            resource.is_colour_image(sha256),
        )
        native.set_color_space(colour.space_name(space))

    def list_available_color_spaces(self) -> list[Any]:
        node = _ls.get_node_by_uid(self._node)
        return colour.available_bitmap_spaces(
            None if self._channel is None else self._channel.name,
            colour_managed(node, self._channel),
        )

    def __repr__(self) -> str:
        return f"SourceBitmap({self._node}, {self._channel})"


class SourceSubstance:
    """A procedural (Substance) source: a release gap, so no fill holds one and none can be made
    (phase3.3_procedural-families)."""

    __slots__ = ()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise uzpainter.UnsupportedProcedural(
            "procedural sources are release gaps (phase3.3_procedural-families)"
        )


for _source in (SourceUniformColor, SourceBitmap, SourceSubstance):
    _source.__module__ = SOURCE
SourceMode = uzpainter.source.SourceMode


def wrap_source(node: int, channel: Any, native: Any) -> Any:
    if native is None:
        return None
    if isinstance(native, uzpainter.source.SourceUniformColor):
        return SourceUniformColor(node, channel)
    if isinstance(native, uzpainter.source.SourceBitmap):
        return SourceBitmap(node, channel)
    raise TypeError(f"unexpected native source {native!r}")


# ── Nodes ───────────────────────────────────────────────────────────────────────────────────────


class Node:
    """A layer or an effect of a layer stack."""

    __slots__ = ("_uid",)

    def __init__(self, uid: int) -> None:
        self._uid = int(uid)

    def _native(self) -> Any:
        return _ls.get_node_by_uid(self._uid)

    def uid(self) -> int:
        return self._uid

    def get_type(self) -> Any:
        return self._native().get_type()

    def get_texture_set(self) -> TextureSet:
        return TextureSet(self._native().get_texture_set())

    def get_stack(self) -> Stack:
        return Stack(self._native().get_stack())

    def is_visible(self) -> bool:
        return bool(self._native().is_visible())

    @edits
    def set_visible(self, visible: bool) -> None:
        self._native().set_visible(visible)

    def get_name(self) -> str:
        return str(self._native().get_name())

    @edits
    @structural
    def set_name(self, name: str) -> None:
        self._native().set_name(name)

    def is_in_mask_stack(self) -> bool:
        return bool(self._native().is_in_mask_stack())

    def has_blending(self) -> bool:
        return bool(self._native().has_blending())

    def _blending(self, channel: Any) -> Any:
        native = self._native()
        if not native.has_blending():
            raise ValueError(NO_BLENDING)
        if native.is_in_mask_stack():
            if channel is not None:
                raise ValueError(MASK_BLENDING)
        elif channel is None:
            raise ValueError(CONTENT_BLENDING)
        return native

    def get_blending_mode(self, channel: Any = None) -> Any:
        return self._blending(channel).get_blending_mode(channel)

    @edits
    def set_blending_mode(self, blending_mode: Any, channel: Any = None) -> None:
        self._blending(channel).set_blending_mode(blending_mode, channel)

    def get_opacity(self, channel: Any = None) -> float:
        return float(self._blending(channel).get_opacity(channel))

    @edits
    def set_opacity(self, opacity: float, channel: Any = None) -> None:
        self._blending(channel).set_opacity(opacity, channel)

    def get_parent(self) -> Any:
        return wrap(self._native().get_parent())

    def get_next_sibling(self) -> Any:
        return wrap(self._native().get_next_sibling())

    def get_previous_sibling(self) -> Any:
        return wrap(self._native().get_previous_sibling())

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Node) and self._uid == other._uid

    def __hash__(self) -> int:
        return hash(self._uid)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._uid})"


class LayerNode(Node):
    """A layer: a fill, paint, group or instance layer."""

    __slots__ = ()

    def has_mask(self) -> bool:
        return bool(self._native().has_mask())

    @edits
    @structural
    def add_mask(self, mask_background: Any) -> None:
        native = self._native()
        if native.has_mask():
            raise ValueError("This node already has a mask")
        native.add_mask(mask_background)

    @edits
    def remove_mask(self) -> None:
        self._native().remove_mask()

    def get_mask_background(self) -> Any:
        return self._native().get_mask_background()

    @edits
    def set_mask_background(self, mask_background: Any) -> None:
        self._native().set_mask_background(mask_background)

    def is_mask_enabled(self) -> bool:
        return bool(self._native().is_mask_enabled())

    @edits
    def enable_mask(self, enable: bool) -> None:
        self._native().enable_mask(enable)

    def content_effects(self) -> list[Any]:
        return [wrap(effect) for effect in self._native().content_effects()]

    def mask_effects(self) -> list[Any]:
        return [wrap(effect) for effect in self._native().mask_effects()]

    def instances(self) -> list[Any]:
        return [wrap(layer) for layer in self._native().instances()]


class EffectNode(Node):
    """An effect of a content or mask stack."""

    __slots__ = ()


class _Fill(Node):
    """The fill members shared by FillLayerNode and FillEffectNode."""

    __slots__ = ()

    def _context(self, channel: Any) -> Any:
        """The native fill after Painter's channel-context check."""
        native = self._native()
        if native.is_in_mask_stack():
            if channel is not None:
                raise channel_error(channel)
        elif channel is None:
            raise uzpainter.EditionContextException(MONO_CONTEXT)
        return native

    @property
    def active_channels(self) -> set[Any]:
        native = self._native()
        if native.is_in_mask_stack():
            raise uzpainter.EditionContextException(MULTI_CONTEXT)
        return set(native.active_channels)

    @active_channels.setter
    @edits
    def active_channels(self, channels: Iterable[Any]) -> None:
        native = self._native()
        wanted = set(channels)
        if native.is_in_mask_stack():
            first = min(wanted, key=lambda c: c.name) if wanted else ChannelType.BaseColor
            raise channel_error(first)
        with one_transaction("layerstack.FillLayerNode.active_channels"):
            native.active_channels = wanted
            for channel in sorted(wanted, key=lambda c: c.name):
                reset_to_default(native, channel)

    @property
    def source_mode(self) -> Any:
        native = self._native()
        if native.is_in_mask_stack():
            return None
        return native.source_mode()

    def get_source(self, channeltype: Any = None) -> Any:
        native = self._context(channeltype)
        source = native.get_source(channeltype)
        if source is None and channeltype is not None:
            raise unrecorded_default(channeltype)
        # A mask fill without a source reads None (`mask-stack` defaults of step 6).
        return wrap_source(self.uid(), channeltype, source)

    @edits
    def set_source(self, channeltype: Any, source: Any) -> Any:
        native = self._context(channeltype)
        uid = self.uid()
        with one_transaction("layerstack.FillLayerNode.set_source"):
            if channeltype is not None and channeltype not in native.active_channels:
                # Implicit activation, without the reset of an assignment (set-source-none-
                # multichannel s17-s19).
                native.active_channels = set(native.active_channels) | {channeltype}
            if isinstance(source, colour.Color):
                native.set_source(
                    channeltype, colour.stored_color(source, colour_managed(native, channeltype))
                )
            elif isinstance(source, (resource.ResourceID, resource.Resource)):
                identifier = (
                    source.identifier() if isinstance(source, resource.Resource) else source
                )
                target = resource.to_native(identifier)
                bitmap = native.set_source(channeltype, target)
                space = colour.default_bitmap_space(
                    None if channeltype is None else channeltype.name,
                    resource.is_colour_image(target.version),
                )
                bitmap.set_color_space(colour.space_name(space))
                key = ("source", uid, None if channeltype is None else channeltype.name)
                SESSION.bound_context[key] = identifier.context
            elif isinstance(source, AnchorPointEffectNode):
                raise uzpainter.NotYetSupported(
                    "anchor reference sources are release gaps (phase4.1_nodes-instances-anchors)"
                )
            else:
                raise ValueError(f"{source!r} is not a valid source (a Color or a ResourceID)")
        return wrap_source(uid, channeltype, native.get_source(channeltype))

    @edits
    def reset_source(self, channeltype: Any = None) -> None:
        native = self._context(channeltype)
        with one_transaction("layerstack.FillLayerNode.reset_source"):
            reset_to_default(native, channeltype)

    def get_projection_mode(self) -> Any:
        return self._native().get_projection_mode()

    @edits
    def set_projection_mode(self, projection_mode: Any) -> None:
        self._native().set_projection_mode(projection_mode)

    def get_projection_parameters(self) -> Any:
        return projection_from_native(self._native().get_projection_parameters())

    @edits
    def set_projection_parameters(self, parameters: Any) -> None:
        self._native().set_projection_parameters(projection_to_native(parameters))

    def is_symmetry_enabled(self) -> bool:
        return bool(self._native().is_symmetry_enabled())

    @edits
    def set_symmetry_enabled(self, enabled: bool) -> None:
        self._native().set_symmetry_enabled(enabled)

    def get_material_source(self) -> Any:
        return self._native().get_material_source()

    @edits
    def set_material_source(self, source: Any) -> Any:
        return self._native().set_material_source(source)


def reset_to_default(native: Any, channel: Any) -> None:
    """Painter's default source on `channel` (None: the mono source) of a native fill."""
    default = None if channel is None else DEFAULT_SOURCES.get(channel.name)
    if default is not None:
        native.set_source(channel, uzpainter.colormanagement.Color(*default, "Working"))
    elif native.get_source(channel) is not None:
        native.reset_source(channel)


class FillLayerNode(_Fill, LayerNode):
    """A fill layer."""

    __slots__ = ()


class FillEffectNode(_Fill, EffectNode):
    """A fill effect."""

    __slots__ = ()


class GroupLayerNode(LayerNode):
    """A group (folder) of layers."""

    __slots__ = ()

    def sub_layers(self) -> list[Any]:
        return [wrap(layer) for layer in self._native().sub_layers()]

    def is_collapsed(self) -> bool:
        return bool(self._native().is_collapsed())

    def set_collapsed(self, collapsed: bool) -> None:
        self._native().set_collapsed(collapsed)


class InstanceLayerNode(LayerNode):
    """An instance of another layer."""

    __slots__ = ()

    def instance_source(self) -> Any:
        return wrap(self._native().instance_source())


class LevelsEffectNode(EffectNode):
    """A levels effect."""

    __slots__ = ()

    def _content(self) -> Any:
        native = self._native()
        if native.is_in_mask_stack():
            raise ValueError("Property 'affected_channel' is invalid in mask context")
        return native

    @property
    def affected_channel(self) -> Any:
        return self._content().affected_channel

    @affected_channel.setter
    @edits
    def affected_channel(self, channel: Any) -> None:
        self._content().affected_channel = channel

    def get_parameters(self) -> Any:
        return levels.from_native(self._native().get_parameters())

    @edits
    def set_parameters(self, params: Any) -> None:
        self._native().set_parameters(levels.to_native(params))


class PaintLayerNode(LayerNode):
    __slots__ = ()


class PaintEffectNode(EffectNode):
    __slots__ = ()


class GeneratorEffectNode(EffectNode):
    __slots__ = ()


class FilterEffectNode(EffectNode):
    __slots__ = ()


class CompareMaskEffectNode(EffectNode):
    __slots__ = ()


class ColorSelectionEffectNode(EffectNode):
    __slots__ = ()


class AnchorPointEffectNode(EffectNode):
    __slots__ = ()


NODE_CLASSES: dict[str, type[Node]] = {
    cls.__name__: cls
    for cls in (
        Node,
        LayerNode,
        EffectNode,
        FillLayerNode,
        FillEffectNode,
        GroupLayerNode,
        InstanceLayerNode,
        LevelsEffectNode,
        PaintLayerNode,
        PaintEffectNode,
        GeneratorEffectNode,
        FilterEffectNode,
        CompareMaskEffectNode,
        ColorSelectionEffectNode,
        AnchorPointEffectNode,
    )
}
for _node in NODE_CLASSES.values():
    _node.__module__ = LAYERSTACK


def wrap(native: Any) -> Any:
    """The facade node of a native node handle (None stays None)."""
    if native is None:
        return None
    return NODE_CLASSES[type(native).__name__](native.uid())


def native_node(node: Any) -> Any:
    if not isinstance(node, Node):
        raise TypeError(f"{node!r} is not a layerstack node")
    return node._native()


# ── Insertion ───────────────────────────────────────────────────────────────────────────────────

NodeStack = _ls.NodeStack


class InsertPosition:
    """Where a node is inserted: the top of a stack, above or below a node, or inside one."""

    __slots__ = ("_kind", "_node", "_node_stack", "_stack")

    def __init__(self, node_id: int, node_stack: Any = None) -> None:
        # Painter's raw form: inside `node_stack` of the node, or above the node without one.
        self._kind = "inside" if node_stack is not None else "above"
        self._node = int(node_id)
        self._node_stack = node_stack
        self._stack: Any = None

    @staticmethod
    def from_textureset_stack(stack: Any) -> InsertPosition:
        position = InsertPosition(0)
        position._kind = "top"
        position._stack = native_of(stack)
        return position

    @staticmethod
    def above_node(node: Any) -> InsertPosition:
        return InsertPosition(node.uid())

    @staticmethod
    def below_node(node: Any) -> InsertPosition:
        position = InsertPosition(node.uid())
        position._kind = "below"
        return position

    @staticmethod
    def inside_node(node: Any, node_stack: Any) -> InsertPosition:
        return InsertPosition(node.uid(), node_stack)

    def _native(self) -> Any:
        if self._kind == "top":
            return _ls.InsertPosition.from_textureset_stack(self._stack)
        node = _ls.get_node_by_uid(self._node)
        if self._kind == "above":
            return _ls.InsertPosition.above_node(node)
        if self._kind == "below":
            return _ls.InsertPosition.below_node(node)
        return _ls.InsertPosition.inside_node(node, self._node_stack)

    def __repr__(self) -> str:
        return f"InsertPosition({self._kind}, {self._node}, {self._node_stack})"


InsertPosition.__module__ = LAYERSTACK


class Kind(enum.Enum):
    LAYER = "layer"
    EFFECT = "effect"
    EITHER = "either"  # insert_fill / insert_paint: a layer or an effect by position


MASK_ONLY = {
    "compare": "Compare mask effect can only be inserted in mask stack",
    "selection": "Color selection effect can only be inserted in mask stack",
}


def check_position(position: Any, kind: Kind, mask_only: str | None = None) -> str:
    """Painter's insertion rules (`insert-positions`): ValueError before any change. Returns
    the stack the node goes into: "root", "Substack", "Content" or "Mask"."""
    if not isinstance(position, InsertPosition):
        raise TypeError("position must be a layerstack.InsertPosition")
    if position._kind == "top":
        if kind is Kind.EFFECT:
            raise ValueError("Cannot insert an effect at the top of the layerstack")
        return "root"
    target = _ls.get_node_by_uid(position._node)
    is_effect = isinstance(target, _ls.EffectNode)
    if position._kind == "inside":
        stack = position._node_stack
        if stack == NodeStack.Substack:
            if not isinstance(target, _ls.GroupLayerNode):
                raise ValueError(
                    "Invalid insert position: substack is only valid on a layer group node"
                )
            if kind is Kind.EFFECT:
                raise ValueError("Cannot insert an effect in a substack")
            return "Substack"
        name = "content" if stack == NodeStack.Content else "mask"
        if is_effect:
            raise ValueError(f"Invalid insert position: an effect has no {name} stack")
        if kind is Kind.LAYER:
            raise ValueError(f"Cannot insert a layer in {name} stack")
        if stack == NodeStack.Mask and not target.has_mask():
            raise ValueError("The layer does not have a mask")
        if stack == NodeStack.Content and mask_only:
            raise ValueError(MASK_ONLY[mask_only])
        return "Content" if stack == NodeStack.Content else "Mask"
    where = position._kind
    if is_effect:
        if kind is Kind.LAYER:
            raise ValueError(f"Cannot insert a layer {where} an effect")
        in_mask = bool(target.is_in_mask_stack())
        if mask_only and not in_mask:
            raise ValueError(MASK_ONLY[mask_only])
        return "Mask" if in_mask else "Content"
    if kind is Kind.EFFECT:
        raise ValueError(f"Cannot insert an effect {where} a layer")
    parent = target.get_parent()
    return "root" if parent is None else "Substack"


# Painter's blending of a new layer or content effect, per channel (the effective defaults of
# every inserted fill, fill effect and group in the Tier 0 api-probes): Height adds, Normal
# combines as a detail map, every other channel of the template blends Normal at opacity 1.
DEFAULT_BLENDING = {"Height": "LinearDodge", "Normal": "NormalMapDetail"}


def set_default_blending(native: Any) -> None:
    """Painter's per-channel default blending on a new node of a content stack."""
    stack = native.get_stack()
    for name, mode in DEFAULT_BLENDING.items():
        channel = getattr(ChannelType, name)
        if stack.has_channel(channel):
            native.set_blending_mode(getattr(_ls.BlendingMode, mode), channel)


def insert(
    call: str, position: Any, kind: Kind, mask_only: str | None = None, name: str | None = None
) -> Any:
    stack = check_position(position, kind, mask_only)
    native = getattr(_ls, call)(position._native(), name)
    return wrap(native), stack


@edits
@structural
def insert_fill(position: Any) -> Any:
    stack = check_position(position, Kind.EITHER)
    with one_transaction("layerstack.insert_fill"):
        native = _ls.insert_fill(position._native(), None)
        if stack != "Mask":
            set_default_blending(native)
            # A new fill already holds Painter's recorded default sources (DEFAULT_SOURCES); its
            # active channels stay empty, as Painter inserts it.
            for name in DEFAULT_SOURCES:
                channel = getattr(ChannelType, name)
                if native.get_stack().has_channel(channel):
                    reset_to_default(native, channel)
    return wrap(native)


@edits
def insert_paint(position: Any) -> Any:
    node, _ = insert("insert_paint", position, Kind.EITHER)
    return node


@edits
@structural
def insert_group(position: Any) -> Any:
    check_position(position, Kind.LAYER)
    with one_transaction("layerstack.insert_group"):
        native = _ls.insert_group(position._native(), None)
        set_default_blending(native)
    return wrap(native)


@edits
def insert_levels_effect(position: Any) -> Any:
    stack = check_position(position, Kind.EFFECT)
    if stack != "Content":
        return wrap(_ls.insert_levels_effect(position._native(), None))
    # In a content stack Painter names the effect after the channel it affects, BaseColor
    # ("Levels - Base color", `insert-positions` s9).
    with one_transaction("layerstack.insert_levels_effect"):
        native = _ls.insert_levels_effect(position._native(), "Levels - Base color")
        native.affected_channel = ChannelType.BaseColor
    return wrap(native)


@edits
def insert_compare_mask_effect(position: Any) -> Any:
    node, _ = insert("insert_compare_mask_effect", position, Kind.EFFECT, "compare", "Compare mask")
    return node


@edits
def insert_color_selection_effect(position: Any) -> Any:
    node, _ = insert("insert_color_selection_effect", position, Kind.EFFECT, "selection")
    return node


@edits
def insert_anchor_point_effect(position: Any, name: str) -> Any:
    node, _ = insert("insert_anchor_point_effect", position, Kind.EFFECT, None, name)
    return node


@edits
def instantiate(position: Any, layer: Any) -> Any:
    check_position(position, Kind.LAYER)
    return wrap(_ls.instantiate(position._native(), native_node(layer)))


def insert_generator_effect(position: Any, generator: Any) -> Any:
    return _ls.insert_generator_effect(position, generator)


def insert_filter_effect(position: Any, filter: Any) -> Any:
    return _ls.insert_filter_effect(position, filter)


def insert_smart_material(position: Any, smart_material: Any) -> Any:
    return _ls.insert_smart_material(position, smart_material)


def insert_smart_mask(position: Any, smart_mask: Any) -> Any:
    return _ls.insert_smart_mask(position, smart_mask)


@edits
@structural
def delete_node(node: Any) -> None:
    uid = node.uid()
    _ls.delete_node(native_node(node))
    SESSION.selection_type.pop(uid, None)


# ── Navigation ──────────────────────────────────────────────────────────────────────────────────


def get_root_layer_nodes(stack: Any) -> list[Any]:
    return [wrap(native) for native in _ls.get_root_layer_nodes(native_of(stack))]


def get_node_by_uid(node_id: int) -> Any:
    return wrap(_ls.get_node_by_uid(node_id))


def stack_order(stack: Any) -> list[int]:
    """The uids of a native stack's nodes in layer-stack order (top first; a layer's mask and
    content effects before its sub-layers)."""
    order: list[int] = []

    def visit(native: Any) -> None:
        order.append(native.uid())
        if isinstance(native, _ls.LayerNode):
            for effect in native.mask_effects():
                visit(effect)
            for effect in native.content_effects():
                visit(effect)
        if isinstance(native, _ls.GroupLayerNode):
            for child in native.sub_layers():
                visit(child)

    for root in _ls.get_root_layer_nodes(stack):
        visit(root)
    return order


# ── Selection (inert script state, 10 §3) ───────────────────────────────────────────────────────


class SelectionType(enum.Enum):
    """Which part of a layer is selected."""

    Content = 0
    Mask = 1
    GeometryMask = 2
    Properties = 3


SelectionType.__module__ = LAYERSTACK


def _stack_key(native_stack: Any) -> tuple[int, int]:
    return (int(native_stack.material().uid()), int(native_stack.uid()))


def _in_current_texture_set(native: Any) -> None:
    active = uzpainter.textureset.get_active_stack()
    if native.get_texture_set() != active.material():
        raise ValueError("The node doesn't belong to the currently selected texture set")


def _not_scoped(call: str) -> None:
    if SESSION.scoped:
        raise RuntimeError(f"{call} cannot be called from a ScopedModification section")


def get_selected_nodes(stack: Any) -> list[Any]:
    native_stack = native_of(stack)
    selected = set(SESSION.selection.get(_stack_key(native_stack), []))
    return [get_node_by_uid(uid) for uid in stack_order(native_stack) if uid in selected]


def set_selected_nodes(nodes: Any) -> None:
    _not_scoped("set_selected_nodes")
    natives = [native_node(node) for node in nodes]
    for native in natives:
        _in_current_texture_set(native)
    selection: dict[tuple[int, int], list[int]] = {}
    for native in natives:
        selection.setdefault(_stack_key(native.get_stack()), []).append(native.uid())
    SESSION.selection = selection


def get_selection_type(layer: Any) -> SelectionType:
    native = native_node(layer)
    _in_current_texture_set(native)
    found: SelectionType = SESSION.selection_type.get(native.uid(), SelectionType.Content)
    return found


def set_selection_type(layer: Any, layer_selection_type: Any) -> None:
    _not_scoped("set_selection_type")
    native = native_node(layer)
    _in_current_texture_set(native)
    if not isinstance(layer_selection_type, SelectionType):
        raise TypeError("layer_selection_type must be a layerstack.SelectionType")
    if layer_selection_type is SelectionType.Properties and not isinstance(
        native, _ls.InstanceLayerNode
    ):
        raise ValueError("SelectionType.Properties is only available for instances")
    SESSION.selection_type[native.uid()] = layer_selection_type


class ScopedModification:
    """Groups layer-stack modifications under one name. Each call inside still commits its own
    revision; an exception leaves the calls already made committed (no rollback, 10 §5)."""

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name  # the history entry's name in Painter; UzPainter keeps no undo history

    def __enter__(self) -> ScopedModification:
        SESSION.scoped += 1
        return self

    def __exit__(self, *exc: object) -> None:
        SESSION.scoped -= 1


ScopedModification.__module__ = LAYERSTACK


def drop_group_content_effects() -> None:
    """Painter does not keep the content effects of a group through save and reopen
    (`insert-positions` identity/s12 after reopen: missing); a facade save removes them first."""
    doomed: list[Any] = []

    def visit(native: Any) -> None:
        if isinstance(native, _ls.GroupLayerNode):
            doomed.extend(native.content_effects())
            for child in native.sub_layers():
                visit(child)

    for texture_set in uzpainter.textureset.all_texture_sets():
        for stack in texture_set.all_stacks():
            for root in _ls.get_root_layer_nodes(stack):
                visit(root)
    for effect in doomed:
        _ls.delete_node(effect)


def check_exportable() -> None:
    """NotYetSupported before an export reads a fill whose active channel holds no source: its
    Painter default is unrecorded (DEFAULT_SOURCES)."""

    def visit(native: Any) -> None:
        fill = isinstance(native, (_ls.FillLayerNode, _ls.FillEffectNode))
        if fill and native.is_visible() and not native.is_in_mask_stack():
            for channel in native.active_channels:
                if native.get_source(channel) is None:
                    raise unrecorded_default(channel)
        if isinstance(native, _ls.LayerNode):
            for effect in [*native.content_effects(), *native.mask_effects()]:
                visit(effect)
        if isinstance(native, _ls.GroupLayerNode):
            for child in native.sub_layers():
                visit(child)

    for texture_set in uzpainter.textureset.all_texture_sets():
        for stack in texture_set.all_stacks():
            for root in _ls.get_root_layer_nodes(stack):
                visit(root)
