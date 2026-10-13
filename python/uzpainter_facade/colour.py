"""`substance_painter.colormanagement` and the facade's colour rules (10 §4 Colour row; decisions
105 §2 and 107; `python/FACADE.md` §4).

Colour management is Painter's Legacy mode, the one pinned profile (`PROFILES`): the working space
is linear sRGB and images come in and go out as sRGB, the Assets3D contract (PRJ-05). A project
declaring any other configuration fails with `NotYetSupported` before anything is evaluated;
recording `OCIO` or `PAINTER_ACE_CONFIG` does not make it supported. The facade never rewrites a
project's declared mode, working space, input rules or display transform.

Uniform colours. A colour without a space is sRGB on a colour-managed channel (an sRGB8 channel:
BaseColor in the templates) and Raw elsewhere, as Painter documents and the
`export-ocio-encode-legacy` readbacks record. A user channel is not colour managed for a uniform
colour, sRGB8 or not: Painter reads back and exports the value set whatever its space
(`colour-ramps-srgb`, `-working`, `-raw`; decision 115), and so does any channel the facade does not
colour-manage. The facade stores every uniform colour as its
working-space value (`Color(working, "Working")`): the native evaluator takes a stored value as
linear, so it receives the value Painter composites, and Painter's readback (`.working`) is that
value. The sRGB transfer runs in float32 as Painter's readbacks show it: x = f32(v),
((x + 0.055f) / 1.055f) ^ 2.4f with the power of the float32 operands rounded once to float32
(`fill-layer-readback` s5 and s30, `export-ocio-encode-legacy` readbacks: 6 of 7 recorded
components; the seventh is decision 107's named residual).

Bitmap sources. A bitmap takes Painter's default space for its channel when bound
(`DEFAULT_BITMAP_SPACES`, from the recorded `get_source` readbacks) and lists Painter's available
spaces (`fill-layer-readback` s43, `export-ocio-encode-legacy` colour-space captures); a channel
without a recorded default or list raises `NotYetSupported` naming the recording that settles it.
"""

from __future__ import annotations

import enum
import struct
from typing import Any

import uzpainter

MODULE = "substance_painter.colormanagement"


class GenericColorSpace(enum.Enum):
    """Generic color spaces valid with any color space engine used."""

    sRGB = 0
    Working = 1
    Raw = 2


class LegacyColorSpace(enum.Enum):
    """Legacy color spaces (resources only)."""

    Linear = 0
    sRGB = 1


class DataColorSpace(enum.Enum):
    """Data color spaces, for channels that are not color managed (resources only)."""

    Data = 0
    DataSigned = 1


class NormalColorSpace(enum.Enum):
    """Normal color spaces (resources only)."""

    NormalXYZRight = 0
    NormalXYZLeft = 1


SPACE_ENUMS: tuple[type[enum.Enum], ...] = (
    GenericColorSpace,
    LegacyColorSpace,
    DataColorSpace,
    NormalColorSpace,
)
for _enum in SPACE_ENUMS:
    _enum.__module__ = MODULE

# The colour-management configurations the facade evaluates (10 §4): only Painter's Legacy mode,
# whose working space is linear sRGB with sRGB input and output. The native project reports an
# unset mode for a project it created; Legacy is the mode every Tier 0 golden was recorded in.
PROFILES = {"": "legacy", "legacy": "legacy"}
DEFAULT_PROFILE = "legacy"
SESSION_O = (
    "the OCIO goldens export-ocio-encode and export-presets-ocio (Painter recording Session O, "
    "decision 101)"
)


def require_supported_configuration() -> str:
    """The pinned profile of the open project; `NotYetSupported` before any evaluation when its
    declared configuration is not pinned."""
    declared = uzpainter.colormanagement.get_color_management()
    mode = str(declared.get("mode", ""))
    if mode not in PROFILES:
        raise uzpainter.NotYetSupported(
            f"colour management '{mode}' (working space '{declared.get('working_space', '')}') "
            f"is not a pinned colour profile; only Painter's Legacy mode (linear working space, "
            f"sRGB I/O) is supported until {SESSION_O} are recorded and fitted "
            "(phase1.15_compositor-colour-fits, decision 107)"
        )
    return PROFILES[mode]


# ── float32 arithmetic ─────────────────────────────────────────────────────────────────────────


def f32(value: float) -> float:
    """`value` rounded to float32."""
    return float(struct.unpack("f", struct.pack("f", value))[0])


_F_0_04045 = f32(0.04045)
_F_12_92 = f32(12.92)
_F_0_055 = f32(0.055)
_F_1_055 = f32(1.055)
_F_2_4 = f32(2.4)
_F_0_0031308 = f32(0.0031308)
_F_INV_2_4 = f32(1.0 / 2.4)


def srgb_to_linear(value: float) -> float:
    """Painter's float32 sRGB decode of one component."""
    x = f32(value)
    if x <= _F_0_04045:
        return f32(x / _F_12_92)
    base = f32(f32(x + _F_0_055) / _F_1_055)
    return f32(base**_F_2_4)


def linear_to_srgb(value: float) -> float:
    """The float32 sRGB encode of one component (the inverse transfer)."""
    x = f32(value)
    if x <= _F_0_0031308:
        return f32(x * _F_12_92)
    return f32(f32(_F_1_055 * f32(max(x, 0.0) ** _F_INV_2_4)) - _F_0_055)


# ── Colour spaces by name ──────────────────────────────────────────────────────────────────────

# Colour spaces of a uniform colour in Legacy mode, by how they relate to the working space.
_LINEAR = {"Working", "Linear"}
_SRGB = {"sRGB"}
_RAW = {"Raw"}


def space_name(space: Any) -> str:
    """The name of a colour space given as a documented enum member or a string."""
    if isinstance(space, str):
        return space
    if isinstance(space, SPACE_ENUMS):
        return str(space.name)
    raise TypeError(f"{space!r} is not a colour space")


def color_space_name(space: Any) -> str:
    """The name of a `Color.color_space`: a GenericColorSpace member or a string (Painter
    documents the other enums as resource-only)."""
    if isinstance(space, (LegacyColorSpace, DataColorSpace, NormalColorSpace)):
        raise TypeError(f"{space} can be used for resources only, not for Color.color_space")
    return space_name(space)


def to_working(rgb: tuple[float, float, float], space: str) -> tuple[float, float, float]:
    """`rgb` encoded in `space`, as float32 working-space values (Legacy mode)."""
    if space in _SRGB:
        r, g, b = (srgb_to_linear(c) for c in rgb)
    elif space in _LINEAR or space in _RAW:
        r, g, b = (f32(c) for c in rgb)
    else:
        raise ValueError(f"'{space}' is not a colour space of Painter's Legacy colour management")
    return (r, g, b)


def from_working(rgb: tuple[float, float, float], space: str) -> tuple[float, float, float]:
    """Working-space values encoded in `space` (Legacy mode), as float32."""
    if space in _SRGB:
        r, g, b = (linear_to_srgb(c) for c in rgb)
    elif space in _LINEAR or space in _RAW:
        r, g, b = (f32(c) for c in rgb)
    else:
        raise ValueError(f"'{space}' is not a colour space of Painter's Legacy colour management")
    return (r, g, b)


def _rgb(values: Any) -> tuple[float, float, float]:
    r, g, b = values
    return (float(r), float(g), float(b))


class Color:
    """Describe a color (with a color space)."""

    __slots__ = ("color_space", "value_raw")

    def __init__(self, r: float, g: float, b: float, color_space: Any = None) -> None:
        if color_space is not None:
            color_space_name(color_space)
        self.value_raw: tuple[float, float, float] = (float(r), float(g), float(b))
        self.color_space: Any = color_space

    def _space(self) -> str:
        if self.color_space is None:
            raise RuntimeError("Color.color_space is None: the colour has no colour space")
        return color_space_name(self.color_space)

    def convert(self, color_space: Any) -> tuple[float, float, float]:
        """Get r,g,b values encoded in the given color space."""
        working = to_working(self.value_raw, self._space())
        return from_working(working, color_space_name(color_space))

    @property
    def value(self) -> tuple[float, float, float]:
        """The colour encoded in sRGB if its space is defined and not Raw, else `value_raw`."""
        if self.color_space is None or color_space_name(self.color_space) in _RAW:
            return self.value_raw
        return self.sRGB

    @property
    def sRGB(self) -> tuple[float, float, float]:
        return self.convert(GenericColorSpace.sRGB)

    @sRGB.setter
    def sRGB(self, rgb: tuple[float, float, float]) -> None:
        self.value_raw = from_working(to_working(_rgb(rgb), "sRGB"), self._space())

    @property
    def working(self) -> tuple[float, float, float]:
        return self.convert(GenericColorSpace.Working)

    @working.setter
    def working(self, rgb: tuple[float, float, float]) -> None:
        self.value_raw = from_working(to_working(_rgb(rgb), "Working"), self._space())

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Color)
            and self.value_raw == other.value_raw
            and self.color_space == other.color_space
        )

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        r, g, b = self.value_raw
        return f"Color({r!r}, {g!r}, {b!r}, {self.color_space!r})"


Color.__module__ = MODULE


def working_value(color: Any, colour_managed: bool) -> tuple[float, float, float]:
    """The float32 working-space value of `color` set on a channel: a colour without a space is
    sRGB on a colour-managed channel and Raw elsewhere; a channel that is not colour managed takes
    the value as given, whatever its space."""
    if not isinstance(color, Color):
        raise TypeError("the colour must be a colormanagement.Color")
    if color.color_space is None:
        space = "sRGB" if colour_managed else "Raw"
    else:
        space = color_space_name(color.color_space)
    working = to_working(color.value_raw, space)  # a space outside Legacy mode raises here
    if not colour_managed:
        r, g, b = (f32(c) for c in color.value_raw)  # taken as given (decision 115)
        return (r, g, b)
    return working


def stored_color(color: Any, colour_managed: bool) -> Any:
    """The native colour the facade stores: the working value in the Working space."""
    r, g, b = working_value(color, colour_managed)
    return uzpainter.colormanagement.Color(r, g, b, "Working")


def read_color(native: Any) -> Color:
    """A native uniform colour as Painter returns it: always with a defined space."""
    space = native.color_space
    r, g, b = native.value_raw
    if space in (None, "", "Working"):
        return Color(r, g, b, GenericColorSpace.Working)
    return Color(r, g, b, space_member(space))


def space_member(name: str) -> Any:
    """The documented enum member named `name` (Generic first), or the string itself."""
    for kind in SPACE_ENUMS:
        if name in kind.__members__:
            return kind[name]
    return name


# ── Bitmap colour spaces (Legacy mode) ──────────────────────────────────────────────────────────

# Channels whose bitmap sources Painter 12.1.5 reports in the Data space when the steps set none
# (the recorded `get_source` readbacks; tests/evaluator/test_compositor_tile_dag.py uses the same
# table to build its specs).
DATA_CHANNELS = frozenset(
    {"AO", "BaseMetalness", "SpecularRoughness", *(f"User{i}" for i in range(10))}
)
CHANNEL_DEFAULTS_PROBE = (
    "a Tier 0 probe reading get_source, get_color_space and list_available_color_spaces of a "
    "bitmap and a fresh fill on every template channel (decision 107)"
)


def default_bitmap_space(channel: str | None, colour_image: bool) -> Any:
    """Painter's colour space of a bitmap bound on `channel` (None: a mask's mono source)."""
    if channel is None or channel in DATA_CHANNELS:
        return DataColorSpace.Data
    if channel == "BaseColor" and colour_image:
        return GenericColorSpace.sRGB
    if channel == "Height":
        return DataColorSpace.DataSigned
    if channel == "Normal":
        return NormalColorSpace.NormalXYZLeft
    raise uzpainter.NotYetSupported(
        f"Painter's default colour space of a {'colour' if colour_image else 'grey'} bitmap on "
        f"{channel} is not recorded ({CHANNEL_DEFAULTS_PROBE}; phase1.15_compositor-colour-fits)"
    )


# Painter's refusal of the sRGB space where it does not offer it: on a user channel of every format
# but sRGB8 and on a mask's mono source (`srgb-bitmap-variants-v2` s4 and s5, both recordings;
# decision 174). The bitmap keeps its space.
SRGB_REFUSAL = "Invalid colorspace 'standard sRGB'"


def bitmap_space_tag(space: Any) -> str:
    """The native tag of a bitmap colour space: a `LegacyColorSpace` member by qualified name (its
    `sRGB` is not the generic one; the evaluator reads both tags, `src/evaluator/sources.h`), any
    other member by name, a string as given."""
    if isinstance(space, LegacyColorSpace):
        return f"LegacyColorSpace.{space.name}"
    return space_name(space)


def bitmap_space_member(tag: str) -> Any:
    """The documented member of a native bitmap colour-space tag (`bitmap_space_tag`)."""
    kind, _, name = tag.partition(".")
    if kind == "LegacyColorSpace" and name in LegacyColorSpace.__members__:
        return LegacyColorSpace[name]
    return space_member(tag)


def available_bitmap_spaces(channel: str | None, colour_managed: bool) -> list[Any]:
    """`SourceBitmap.list_available_color_spaces` in Legacy mode: a mask's mono source and a user
    channel other than sRGB8 (RGB8, L8, RGB16, L16, RGB16F and RGB32F recorded) offer the data
    spaces, an sRGB8 channel the colour spaces."""
    if channel is None or (channel.startswith("User") and not colour_managed):
        return [GenericColorSpace.Raw, DataColorSpace.Data, DataColorSpace.DataSigned]
    if colour_managed:
        return [
            GenericColorSpace.Raw,
            GenericColorSpace.Working,
            GenericColorSpace.sRGB,
            LegacyColorSpace.Linear,
            LegacyColorSpace.sRGB,
        ]
    raise uzpainter.NotYetSupported(
        f"the colour spaces Painter lists for a bitmap on {channel} are not recorded "
        f"({CHANNEL_DEFAULTS_PROBE}; phase1.15_compositor-colour-fits)"
    )
