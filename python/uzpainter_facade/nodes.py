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
- `BlendingMode` has no PassThrough member, a new group is collapsed, a UV fill reads no symmetry,
  `reset_source` gives a mask fill uniform white, and selection refusals name their scope
  (`phase1-blending-modes-layer`, `-mask`, `phase1-layer-navigation`).

Each facade call commits one revision (`state.one_transaction`); `ScopedModification` groups calls
without rolling back. Nothing evaluates until an export asks for it, so there is no per-call
invalidation to batch.

`LayerStacksModelDataChanged` is delivered before the call returns by the calls the Tier 0 R10
probes and P21-E (`phase1-layer-stack-events`, decision 319) record emitting it: `insert_fill`
(layer or effect), `insert_paint` (a layer, s14), `insert_group`, `insert_levels_effect`,
`set_name`, `delete_node`, `add_mask`, `remove_mask`, `set_blending_mode` and `set_opacity`, even
when the value is unchanged (`structural`), and `set_visible` when the visibility changes. The
recorded silent ones stay silent: `active_channels`, `set_source`, `set_mask_background`,
`enable_mask`, `set_projection_mode`, `set_projection_parameters`,
`LevelsEffectNode.affected_channel`, `SourceUniformColor.set_color`, `reset_source`,
`SourceBitmap.set_color_space` and `reset_color_space`. Every other edit call is unrecorded and
emits nothing.
"""

from __future__ import annotations

import dataclasses
import enum
import functools
from collections.abc import Callable, Iterable
from typing import Any

import uzpainter

from uzpainter_facade import colour, event, levels, resource
from uzpainter_facade.procedural import ResolutionMode, ResolutionOverride
from uzpainter_facade.state import SESSION, edits, one_transaction, value_edit
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

# The module Painter's binding names in its missing-attribute errors on a layerstack enum
# (`phase1-blending-modes-layer` s9, s79 and `-mask` s11, both recordings).
PAINTER_BINDING = "_substance_painter.layerstack"


class _PainterEnumType(enum.EnumType):
    """Painter's enum classes: a missing member raises its binding's AttributeError."""

    def __getattr__(cls, name: str) -> Any:
        raise AttributeError(
            f"type object '{PAINTER_BINDING}.{cls.__name__}' has no attribute '{name}'"
        )


class _PainterEnum(enum.Enum, metaclass=_PainterEnumType):
    pass


# Painter 12.1.5's BlendingMode: the native members but PassThrough, which Painter's API does not
# have although its documentation lists it (`phase1-blending-modes-layer` s9-s10, s79-s80 and
# `-mask` s11-s12, both recordings: setting it raises AttributeError and the mode stays Normal).
# The native API keeps PassThrough (a group's pass-through blending).
NATIVE_ONLY_BLENDING = frozenset({"PassThrough"})
BlendingMode: type[_PainterEnum] = _PainterEnum(  # type: ignore[call-arg, assignment]
    "BlendingMode",
    [
        (name, int(member))
        for name, member in _ls.BlendingMode.__members__.items()
        if name not in NATIVE_ONLY_BLENDING
    ],
    module=LAYERSTACK,
)


def blending_to_native(mode: Any) -> Any:
    """The native member of a facade BlendingMode (a native member passes as it is)."""
    if isinstance(mode, BlendingMode):
        return _ls.BlendingMode.__members__[mode.name]
    return mode


def blending_from_native(native: Any) -> Any:
    if native.name in NATIVE_ONLY_BLENDING:
        raise uzpainter.NotYetSupported(
            f"BlendingMode.{native.name} is not a member of Painter's API: reading it through "
            "substance_painter is unrecorded (phase1.24_python-api-facade item 4.1)"
        )
    return BlendingMode[native.name]


# The default source of a channel after a reset, in the working space (P20-A,
# `phase1-fill-channel-defaults`, the default template's five channels, and `active-channel-reset`,
# `active-channel-reset-superset`; both recordings; decision 214). Every other channel's default is
# unrecorded: its native source is removed, and reading it or exporting it raises NotYetSupported
# until a defaults probe (colour.CHANNEL_DEFAULTS_PROBE) records it.
DEFAULT_SOURCES: dict[str, tuple[float, float, float]] = {
    "BaseColor": (0.8, 0.8, 0.8),
    "BaseMetalness": (0.0, 0.0, 0.0),
    "Height": (0.0, 0.0, 0.0),
    "Normal": (0.5, 0.5, 1.0),
    "SpecularRoughness": (0.3, 0.3, 0.3),
}
# The source `reset_source` gives a mask-stack fill: uniform white in the working space (Legacy,
# `phase1-layer-navigation` s78-s79, both recordings). A new mask fill has no source (`mask-stack`
# defaults of step 6).
MASK_RESET_SOURCE = (1.0, 1.0, 1.0)
# Painter's channel numbers in its context errors ("Channel 0 isn't valid in this context" for
# BaseColor, `mask-stack` s15, s17, s26); other channels are named.
PAINTER_CHANNEL_NUMBERS = {"BaseColor": 0}

MONO_CONTEXT = "Only valid in mono channel context"
MULTI_CONTEXT = "Only valid in multi channel context"
MASK_BLENDING = "This node is part of a mask stack and does not support Channel Types for blending"
CONTENT_BLENDING = "This node is not part of a mask stack, a Channel Type must be specified"
NO_BLENDING = "This node does not support channel blending information"
SYMMETRY_3D = "Symmetry is only available when using 3D projection modes"


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
        f"it ({colour.CHANNEL_DEFAULTS_PROBE}; phase1.15_compositor-colour-fits)"
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


def channel_format_name(native_node: Any, channel: Any) -> str | None:
    """The format name of `channel` in the node's stack, or None (a mask's mono source, or a
    channel the stack lacks)."""
    if channel is None:
        return None
    stack = native_node.get_stack()
    if not stack.has_channel(channel):
        return None
    return str(stack.get_channel(channel).format().name)


def bitmap_default(native_node: Any, channel: Any, sha256: str) -> Any:
    """The default colour space of the bitmap `sha256` bound on `channel` of the node's stack
    (colour.bitmap_default_space); resolved before any mutation."""
    return colour.bitmap_default_space(
        None if channel is None else channel.name,
        channel_format_name(native_node, channel),
        resource.descriptor_of(sha256),
        resource.is_colour_image(sha256),
    )


def decodes_colour(native_node: Any, channel: Any) -> bool:
    """Whether Painter decodes an sRGB uniform colour set on `channel` to the working space: a
    colour-managed channel other than a user channel. A user channel takes a uniform colour as
    given whatever its space, sRGB8 or not: its readback and its export are the value set
    (`colour-ramps-srgb`, `-working`, `-raw`; decision 115)."""
    return colour_managed(native_node, channel) and not str(channel.name).startswith("User")


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
        managed = decodes_colour(_ls.get_node_by_uid(self._node), self._channel)
        return colour.read_color(self._native().get_color(), managed)

    @edits
    def set_color(self, color: Any) -> None:
        managed = decodes_colour(_ls.get_node_by_uid(self._node), self._channel)
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
        return colour.bitmap_space_member(self._native().get_color_space())

    @edits
    def set_color_space(self, color_space: Any) -> None:
        tag = colour.bitmap_space_tag(color_space)
        available = [colour.bitmap_space_tag(s) for s in self.list_available_color_spaces()]
        if tag not in available:
            if tag == colour.space_name(colour.GenericColorSpace.sRGB):
                raise ValueError(colour.SRGB_REFUSAL)
            raise ValueError(f"'{tag}' is not an available colour space here ({available})")
        self._native().set_color_space(tag)

    @edits
    def reset_color_space(self) -> None:
        native = self._native()
        sha256 = native.resource_id().version
        space = bitmap_default(_ls.get_node_by_uid(self._node), self._channel, sha256)
        native.set_color_space(colour.bitmap_space_tag(space))

    def list_available_color_spaces(self) -> list[Any]:
        node = _ls.get_node_by_uid(self._node)
        return colour.available_bitmap_spaces(
            None if self._channel is None else self._channel.name,
            colour_managed(node, self._channel),
        )

    def __repr__(self) -> str:
        return f"SourceBitmap({self._node}, {self._channel})"


class SourceSubstance:
    """A stored procedural source; edits must match an admitted project snapshot.

    A fill's material source (`material`, decision 413) is served from a multi-output capture:
    its `output_mapping`, `mask_output`, presets and image inputs reproduce the recorded
    `source-substance-presets-inputs` and P413 probes; every unrecorded case refuses before any
    change (`NotYetSupported`)."""

    __slots__ = ("_channel", "_effect", "_material", "_node", "_origin")

    def __init__(
        self,
        node: int,
        channel: Any,
        effect: bool = False,
        origin: Any = None,
        material: bool = False,
    ) -> None:
        self._node = node
        self._channel = channel
        self._effect = effect
        self._material = material
        # The native handle of an observation-origin source (decision 362): it carries the lease
        # captured when it was created, so it is kept rather than resolved again by UID.
        self._origin = origin

    def _native(self) -> Any:
        if self._origin is not None:
            return self._origin
        node = _ls.get_node_by_uid(self._node)
        if self._material:
            if node.source_mode() != SourceMode.Material:
                raise ValueError("stale source: the fill no longer has this material source")
            source = node.get_material_source()
        else:
            # A generator or filter effect's get_source() takes no channel.
            source = node.get_source() if self._effect else node.get_source(self._channel)
        if not isinstance(source, uzpainter.source.SourceSubstance):
            raise ValueError("stale source: the node no longer has this procedural source")
        return source

    # Multiple outputs, presets and image inputs (decisions 412, 413).

    @property
    def output_mapping(self) -> OutputMapping:
        # The property reads on every source; on a split source each use of the mapping raises
        # (`source-substance-mapping-access` s16-s31, both recordings).
        self._native()
        return OutputMapping(self)

    @output_mapping.setter
    def output_mapping(self, mapping: Any) -> None:
        raise unrecorded("assigning a whole output mapping is unrecorded; assign its items")

    @property
    def mask_output(self) -> str:
        native = self._native()
        stored = native._mask_output()  # a split source raises Painter's context error
        return str(stored) if stored is not None else self._default_mask()

    @mask_output.setter
    @edits
    def mask_output(self, output: str) -> None:
        native = self._native()
        if not self._material:
            raise unrecorded("mask_output on a split source is unrecorded")
        if output == self._default_mask():
            # Assigning the default back (`source-substance-presets-inputs` s79, both recordings).
            raise ValueError(f"Invalid output name {output}")
        if output not in self.image_outputs:
            raise unrecorded(f"mask_output {output!r} is not a listed output; unrecorded")
        native._set_mask_output(output)

    def _default_mask(self) -> str:
        return str(self._native()._material_context()["material"]["mask_output"])

    @edits
    def apply_preset(self, preset: str) -> None:
        self._native().apply_preset(preset)

    def _input(self, name: str) -> str:
        if not self._material:
            raise unrecorded("image inputs of a split source are unrecorded")
        if name not in self.image_inputs:
            raise unrecorded(f"image input {name!r} is not listed; unrecorded")
        return name

    def get_source(self, name: str) -> Any:
        name = self._input(name)
        return input_source(self, name, self._native()._input_source(name))

    @edits
    def set_source(self, name: str, source: Any) -> Any:
        name = self._input(name)
        native = self._native()
        if isinstance(source, colour.Color):
            space = source.color_space
            if space is None or colour.color_space_name(space) != "Working":
                raise unrecorded("an image input colour outside the working space is unrecorded")
            native._set_input_colour(name, [float(v) for v in source.value_raw])
        elif isinstance(source, (resource.ResourceID, resource.Resource)):
            identifier = source.identifier() if isinstance(source, resource.Resource) else source
            bound = resource.to_native(identifier)
            # Painter reads a plugged bitmap back as Data (`source-substance-presets-inputs` s44).
            native._set_input_bitmap(name, bound, "Data")
            SESSION.bound_context[("input", self._node, name)] = identifier.context
        elif isinstance(source, AnchorPointEffectNode):
            raise uzpainter.NotYetSupported(
                "anchor reference sources are release gaps (phase4.1_nodes-instances-anchors)"
            )
        else:
            raise unrecorded(f"{source!r} as an image input source is unrecorded")
        return self.get_source(name)

    @edits
    def reset_source(self, name: str) -> None:
        self._native()._reset_input(self._input(name))

    @edits
    def remove_source(self, name: str) -> None:
        self._native()._remove_input(self._input(name))

    @property
    def resource_id(self) -> resource.ResourceID:
        native = self._native().resource_id()
        if isinstance(native, uzpainter.resource._ObservedResourceID):
            return resource.ObservedResourceID(native)
        return resource.ResourceID(native.context, native.name, native.version)

    @property
    def image_outputs(self) -> list[str]:
        return [str(name) for name in self._native().image_outputs]

    @property
    def image_inputs(self) -> list[str]:
        return [str(name) for name in self._native().image_inputs]

    def get_preset_list(self) -> list[str]:
        return [str(name) for name in self._native().get_preset_list()]

    def get_properties(self) -> dict[str, Any]:
        # The native `properties.Property` handles are the facade's class (as for baking).
        return dict(self._native().get_properties())

    def get_parameters(self) -> dict[str, Any]:
        parameters = dict(self._native().get_parameters())
        if not any(_colour_parameter(value) for value in parameters.values()):
            return parameters
        # A colour reads back as a `Color` of its recorded components. The capture's split sources
        # read it in Raw, the material source in sRGB (recorded beside the material context).
        spaces = (
            self._native()._material_context()["material"]["colour_spaces"]
            if self._material
            else {}
        )
        return {
            name: (
                colour.Color(
                    *value["components"],
                    getattr(colour.GenericColorSpace, spaces.get(name, value["working_space"])),
                )
                if _colour_parameter(value)
                else value
            )
            for name, value in parameters.items()
        }

    @edits
    def set_parameters(self, parameters: dict[str, Any]) -> None:
        current = self._native().get_parameters()
        native: dict[str, Any] = {}
        for name, value in parameters.items():
            if not _colour_parameter(current.get(name)):
                native[name] = value
            elif isinstance(value, colour.Color):
                native[name] = {
                    "type": "color",
                    "working_space": colour.color_space_name(value.color_space),
                    "components": [float(c) for c in value.value_raw],
                    "alpha": None,
                }
            elif isinstance(value, (list, tuple)):
                # Painter's refusal of a list or a tuple for a colour parameter (the 2026-11-11
                # material channel survey, felt and leather grain).
                items = ", ".join(type(item).__name__ for item in value)
                raise TypeError(
                    f"Bad value for property '{name}': expected value of type <Color> but got "
                    f"<tuple[{items}]>."
                )
            else:
                raise TypeError(f"Bad value for property '{name}': expected value of type <Color>")
        self._native().set_parameters(native)

    @property
    def active_output(self) -> str:
        return str(self._native().active_output)

    @active_output.setter
    @edits
    def active_output(self, output: str) -> None:
        self._native().active_output = output

    @property
    def resolution(self) -> ResolutionOverride:
        value = self._native().resolution
        if value is None and self._material:
            # The capture records no default resolution of a material source (decision 416).
            raise uzpainter.UnsupportedProcedural(
                "a material source's default resolution is not recorded "
                "(phase3.3_procedural-families item 2.7)"
            )
        if value is None:
            raise uzpainter.UnsupportedProcedural(
                "default source resolution requires recorded asset metadata "
                "(phase3.1_proc-backend-seam)"
            )
        # Painter's getter returns `value` as a list, not the tuple a constructor takes
        # (tier0/api-probes/source-substance-single-output, r1 and r2).
        return ResolutionOverride(ResolutionMode(value.mode), list(value.value), value.log2_offset)

    @resolution.setter
    @edits
    def resolution(self, value: ResolutionOverride) -> None:
        if not isinstance(value, ResolutionOverride):
            raise TypeError("resolution requires a ResolutionOverride")
        if not isinstance(value.mode, ResolutionMode):
            raise TypeError("resolution mode requires a ResolutionMode")
        self._native().resolution = uzpainter.source._ResolutionOverride(
            value.mode.value, value.value, value.log2_offset
        )

    def __repr__(self) -> str:
        if self._material:
            return f"SourceSubstance({self._node}, material)"
        return f"SourceSubstance({self._node}, {self._channel})"


# The owner every unrecorded multiple-output case names.
OWNER = "(phase3.2_source-substance-presets-inputs)"


def _colour_parameter(value: Any) -> bool:
    """Whether a native parameter value is the seam's tagged colour (store `IsColourParam`)."""
    return isinstance(value, dict) and value.get("type") == "color"


def unrecorded(what: str) -> Exception:
    """The refusal of a multiple-output case no recording observed, raised before any change."""
    return uzpainter.NotYetSupported(f"{what} {OWNER}")


class OutputMapping:
    """A source's `output_mapping` (decision 413): channel types to output identifiers.

    On a material source it reads and assigns the stored mapping item by item; iteration gives
    the mapped channels, an unmapped channel raises Painter's `ValueError("output not found")`
    (`source-substance-mapping-access` s33-s37). On a split source every use raises Painter's
    `EditionContextException` (s17-s31). Assigning an item edits the source in one transaction."""

    __slots__ = ("_source",)

    def __init__(self, source: SourceSubstance) -> None:
        self._source = source

    def _items(self) -> dict[Any, str]:
        mapping = self._source._native()._output_mapping()
        return {getattr(ChannelType, name): str(output) for name, output in mapping.items()}

    def __iter__(self) -> Any:
        return iter(list(self._items()))

    def __len__(self) -> int:
        return len(self._items())

    def __getitem__(self, channel: Any) -> str:
        items = self._items()
        if channel not in items:
            raise ValueError("output not found")
        return items[channel]

    @edits
    def __setitem__(self, channel: Any, output: str) -> None:
        source = self._source
        native = source._native()
        native._output_mapping()  # a split source raises Painter's context error first
        if not isinstance(channel, ChannelType):
            raise TypeError("an output mapping key is a ChannelType")
        if output not in source.image_outputs:
            raise unrecorded(f"output {output!r} is not a listed output; unrecorded")
        native._set_output_mapping(channel.name, output)

    def __repr__(self) -> str:
        return f"OutputMapping({self._source!r})"


class InputUniformColor(SourceUniformColor):
    """A uniform colour plugged into an image input, in the working space (s39, s43)."""

    __slots__ = ("_input_name", "_owner")

    def __init__(self, owner: SourceSubstance, name: str) -> None:
        super().__init__(owner._node, None)
        self._owner = owner
        self._input_name = name

    def get_color(self) -> colour.Color:
        state = self._owner._native()._input_source(self._input_name)
        if state is None or "working_colour" not in state:
            raise ValueError("stale source: the image input no longer holds this colour")
        return colour.Color(*state["working_colour"], "Working")

    def set_color(self, color: Any) -> None:
        raise unrecorded("editing an image input's colour in place is unrecorded")

    def __repr__(self) -> str:
        return f"SourceUniformColor({self._owner!r}, {self._input_name!r})"


class InputBitmap(SourceBitmap):
    """A bitmap plugged into an image input (s44, s48), or the source Painter returns for an
    unplugged one, whose `resource_id` raises the recorded error (decision 413)."""

    __slots__ = ("_input_name", "_owner")

    def __init__(self, owner: SourceSubstance, name: str) -> None:
        super().__init__(owner._node, None)
        self._owner = owner
        self._input_name = name

    def _state(self) -> Any:
        return self._owner._native()._input_source(self._input_name)

    def _recorded(self) -> dict[str, Any]:
        return dict(self._owner._native()._input_sources()[self._input_name])

    @property
    def resource_id(self) -> resource.ResourceID:
        state = self._state()
        if state is None:
            raised = self._recorded().get("resource_id", {}).get("raised")
            if raised is None or raised.get("type") != "ValueError":
                raise unrecorded("the unplugged input's resource_id is unrecorded")
            raise ValueError(str(raised["message"]))
        if "bitmap_sha256" not in state:
            raise ValueError("stale source: the image input no longer holds a bitmap")
        for native in uzpainter.resource.list_project_resources():
            if native.version == state["bitmap_sha256"]:
                context = SESSION.bound_context.get(("input", self._owner._node, self._input_name))
                return resource.from_native(native, context)
        raise ValueError("stale source: the plugged bitmap is not a project resource")

    def get_color_space(self) -> Any:
        state = self._state()
        if state is None:
            recorded = self._recorded()
            if "colour_space" not in recorded:
                raise unrecorded("the unplugged input's colour space is unrecorded")
            return colour.bitmap_space_member(str(recorded["colour_space"]))
        return colour.bitmap_space_member(str(state["colour_space"]))

    def set_color_space(self, color_space: Any) -> None:
        raise unrecorded("an image input's colour space edit is unrecorded")

    def reset_color_space(self) -> None:
        raise unrecorded("an image input's colour space edit is unrecorded")

    def list_available_color_spaces(self) -> list[Any]:
        raise unrecorded("an image input's available colour spaces are unrecorded")

    def __repr__(self) -> str:
        return f"SourceBitmap({self._owner!r}, {self._input_name!r})"


class SourceReference:
    """An anchor reference source: a release gap (phase4.1_nodes-instances-anchors). The class
    exists so that `isinstance` checks of Painter scripts run; constructing one refuses."""

    __slots__ = ()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise uzpainter.NotYetSupported(
            "anchor reference sources are release gaps (phase4.1_nodes-instances-anchors)"
        )


def input_source(owner: SourceSubstance, name: str, state: Any) -> Any:
    """The facade source of an image input's native state (None: unplugged)."""
    if state is not None and "working_colour" in state:
        return InputUniformColor(owner, name)
    return InputBitmap(owner, name)


for _source in (
    SourceUniformColor,
    SourceBitmap,
    SourceSubstance,
    OutputMapping,
    SourceReference,
    InputUniformColor,
    InputBitmap,
):
    _source.__module__ = SOURCE
# Painter's classes as the recorder reads them (`type(value)`; s39, s44 of
# `source-substance-presets-inputs`).
InputUniformColor.__name__ = InputUniformColor.__qualname__ = "SourceUniformColor"
InputBitmap.__name__ = InputBitmap.__qualname__ = "SourceBitmap"
SourceMode = uzpainter.source.SourceMode


def wrap_source(node: int, channel: Any, native: Any) -> Any:
    if native is None:
        return None
    if isinstance(native, uzpainter.source.SourceUniformColor):
        return SourceUniformColor(node, channel)
    if isinstance(native, uzpainter.source.SourceBitmap):
        return SourceBitmap(node, channel)
    if isinstance(native, uzpainter.source.SourceSubstance):
        return SourceSubstance(node, channel, origin=observation_origin(native))
    raise TypeError(f"unexpected native source {native!r}")


def observation_origin(native: Any) -> Any:
    """`native` when it is an observation-origin procedural source handle, else None."""
    return native if native._observation_origin else None


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

    def set_visible(self, visible: bool) -> None:
        native = self._native()
        changed = bool(native.is_visible()) != bool(visible)
        value_edit((self._uid, "visible"), native.is_visible, lambda: native.set_visible(visible))
        if changed:  # P21-E s19: a change emits, the same visibility again does not
            event.emit_sync(event.LayerStacksModelDataChanged())

    def get_name(self) -> str:
        return str(self._native().get_name())

    @structural
    def set_name(self, name: str) -> None:
        # A rename back to the saved name leaves the project as saved (`state.value_edit`;
        # `phase1-save-modes` s15-s17 after save and reopen, `phase1-restored-values` s21-s28).
        native = self._native()
        value_edit((self._uid, "name"), native.get_name, lambda: native.set_name(name))

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
        return blending_from_native(self._blending(channel).get_blending_mode(channel))

    @structural
    def set_blending_mode(self, blending_mode: Any, channel: Any = None) -> None:
        native = self._blending(channel)
        value_edit(
            (self._uid, "blending_mode", str(channel)),
            lambda: native.get_blending_mode(channel),
            lambda: native.set_blending_mode(blending_to_native(blending_mode), channel),
        )

    def get_opacity(self, channel: Any = None) -> float:
        return float(self._blending(channel).get_opacity(channel))

    @structural
    def set_opacity(self, opacity: float, channel: Any = None) -> None:
        native = self._blending(channel)
        value_edit(
            (self._uid, "opacity", str(channel)),
            lambda: native.get_opacity(channel),
            lambda: native.set_opacity(opacity, channel),
        )

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
    @structural
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
        context: str | None = None
        tag: str | None = None
        # Every facade refusal and the native payload come before anything changes, including the
        # implicit activation below, which an enclosing transaction would otherwise commit after a
        # caught refusal (an observed ResourceID, decision 361; an unrecorded default space).
        if isinstance(source, colour.Color):
            value: Any = colour.stored_color(source, decodes_colour(native, channeltype))
        elif isinstance(source, (resource.ResourceID, resource.Resource)):
            identifier = source.identifier() if isinstance(source, resource.Resource) else source
            value = resource.to_native(identifier)
            space = bitmap_default(native, channeltype, value.version)
            # Bound in its default space in one native call, by its native tag (a LegacyColorSpace
            # member keeps its class): under OCIO a bitmap without a space on BaseColor is
            # unrecorded, and the support check runs per call.
            tag = colour.bitmap_space_tag(space)
            context = identifier.context
        elif isinstance(source, AnchorPointEffectNode):
            raise uzpainter.NotYetSupported(
                "anchor reference sources are release gaps (phase4.1_nodes-instances-anchors)"
            )
        else:
            raise ValueError(f"{source!r} is not a valid source (a Color or a ResourceID)")
        with one_transaction("layerstack.FillLayerNode.set_source"):
            if channeltype is not None and channeltype not in native.active_channels:
                # Implicit activation, without the reset of an assignment (set-source-none-
                # multichannel s17-s19).
                native.active_channels = set(native.active_channels) | {channeltype}
            # Spelled out, not `set_source(*args)`: CPython 3.13 reports no C_RETURN for a bound
            # native method called with `*args`, so the decision-112 trace would miss this call.
            native.set_source(channeltype, value, tag)
        if context is not None:
            # Once committed: the transaction's commit checks the bitmap's image (decision 240).
            key = ("source", uid, None if channeltype is None else channeltype.name)
            SESSION.bound_context[key] = context
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
        native = self._native()
        if native.get_projection_mode() == _ls.ProjectionMode.UV:
            # Painter reads no symmetry of a UV fill, layer or effect (`phase1-layer-navigation`
            # s60 and s71, both recordings).
            raise ValueError(SYMMETRY_3D)
        return bool(native.is_symmetry_enabled())

    @edits
    def set_symmetry_enabled(self, enabled: bool) -> None:
        native = self._native()
        if enabled and native.get_projection_mode() == _ls.ProjectionMode.UV:
            # Painter's refusal on a UV fill, both P21-E recordings (s28, decision 319); the 3D
            # projection modes stay a release gap (phase3.4_smart-projections).
            raise ValueError(SYMMETRY_3D)
        native.set_symmetry_enabled(enabled)

    def get_material_source(self) -> Any:
        # Painter's refusals, both `phase1-layer-navigation` recordings: a mask-stack fill has no
        # material (s75), a fill in split mode is not in material edition (s72-s73).
        native = self._native()
        if native.is_in_mask_stack():
            raise uzpainter.EditionContextException(MULTI_CONTEXT)
        if native.source_mode() != SourceMode.Material:
            raise RuntimeError("Fill is not in material edition mode")
        native.get_material_source()
        return SourceSubstance(self.uid(), None, material=True)

    @edits
    def set_material_source(self, source: Any) -> Any:
        # A material is served from the project's own multi-output capture of the resource
        # (decision 413): the Painter identifier selects its recorded default state.
        if isinstance(source, resource.Resource):
            source = source.identifier()
        if not isinstance(source, resource.ResourceID):
            raise unrecorded(f"{source!r} as a material source is unrecorded")
        resource.refuse_observed(source)
        self._native().set_material_source(source.url())
        return SourceSubstance(self.uid(), None, material=True)


def reset_to_default(native: Any, channel: Any) -> None:
    """Painter's default source on `channel` (None: the mono source) of a native fill. Under OCIO
    every default is unrecorded (DEFAULT_SOURCES are Legacy recordings; decision 202)."""
    legacy = colour.active_profile() != colour.OCIO_PROFILE
    if channel is None:
        default = MASK_RESET_SOURCE if legacy else None
    else:
        default = DEFAULT_SOURCES.get(channel.name) if legacy else None
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

    def get_source(self) -> SourceSubstance | None:
        native = self._native().get_source()
        if native is None:
            return None
        return SourceSubstance(self.uid(), None, effect=True, origin=observation_origin(native))


class FilterEffectNode(EffectNode):
    __slots__ = ()

    def get_source(self) -> SourceSubstance | None:
        native = self._native().get_source()
        if native is None:
            return None
        return SourceSubstance(self.uid(), None, effect=True, origin=observation_origin(native))


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


# The native inserts give a new node Painter's effective defaults (decision 115): per-channel
# blending of a fill, fill effect or group in a content stack (Height LinearDodge, Normal
# NormalMapDetail), a fill's recorded default sources (DEFAULT_SOURCES) with its active channels
# empty, and the names "Fill", "Folder", "Levels - Base color" (a content-stack levels effect,
# affecting BaseColor) and "Compare mask".
def insert(
    call: str, position: Any, kind: Kind, mask_only: str | None = None, name: str | None = None
) -> Any:
    stack = check_position(position, kind, mask_only)
    native = getattr(_ls, call)(position._native(), name)
    return wrap(native), stack


@edits
@structural
def insert_fill(position: Any) -> Any:
    node, _ = insert("insert_fill", position, Kind.EITHER)
    return node


@edits
@structural
def insert_paint(position: Any) -> Any:
    node, _ = insert("insert_paint", position, Kind.EITHER)
    return node


@edits
@structural
def insert_group(position: Any) -> Any:
    with one_transaction("layerstack.insert_group"):
        node, _ = insert("insert_group", position, Kind.LAYER)
        # Painter's new group is collapsed (`phase1-layer-navigation` s55, first recording).
        node._native().set_collapsed(True)
    return node


@edits
@structural
def insert_levels_effect(position: Any) -> Any:
    node, _ = insert("insert_levels_effect", position, Kind.EFFECT)
    return node


@edits
def insert_compare_mask_effect(position: Any) -> Any:
    node, _ = insert("insert_compare_mask_effect", position, Kind.EFFECT, "compare")
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


# Painter's error for a uid that names no node, a deleted one included (`phase1-delete-node`
# s19-s21, both recordings).
INVALID_NODE = "This node is not valid"


def get_node_by_uid(node_id: int) -> Any:
    try:
        native = _ls.get_node_by_uid(node_id)
    except ValueError as error:
        raise ValueError(INVALID_NODE) from error
    return wrap(native)


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


def _not_scoped() -> None:
    # Painter's refusal names the innermost scope (`phase1-layer-navigation` s103, both
    # recordings).
    if SESSION.scopes:
        raise RuntimeError(
            f'This method can\'t be called from a ScopedModification ("{SESSION.scopes[-1]}")'
        )


def get_selected_nodes(stack: Any) -> list[Any]:
    native_stack = native_of(stack)
    selected = set(SESSION.selection.get(_stack_key(native_stack), []))
    return [get_node_by_uid(uid) for uid in stack_order(native_stack) if uid in selected]


def set_selected_nodes(nodes: Any) -> None:
    _not_scoped()
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
    _not_scoped()
    native = native_node(layer)
    _in_current_texture_set(native)
    if not isinstance(layer_selection_type, SelectionType):
        raise TypeError("layer_selection_type must be a layerstack.SelectionType")
    if layer_selection_type is SelectionType.Properties and not (
        isinstance(native, _ls.InstanceLayerNode)
        or (isinstance(native, _ls.LayerNode) and native.instances())
    ):
        # `phase1-layer-navigation` s101 (a fill without instances); `phase1-layer-node-kinds`
        # s21 and s23 accept an instance and its source.
        raise ValueError(
            "Properties selection type is only valid for instance layers or instance source"
        )
    SESSION.selection_type[native.uid()] = layer_selection_type


class ScopedModification:
    """Groups layer-stack modifications under one name. Each call inside still commits its own
    revision; an exception leaves the calls already made committed (no rollback, 10 §5)."""

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        # The history entry's name in Painter (UzPainter keeps no undo history), and the scope its
        # refusals name.
        self._name = name

    def __enter__(self) -> ScopedModification:
        SESSION.scopes.append(self._name)
        return self

    def __exit__(self, *exc: object) -> None:
        SESSION.scopes.pop()


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
