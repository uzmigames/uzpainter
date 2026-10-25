"""`substance_painter.colormanagement` and the facade's colour rules (10 §4 Colour row; decisions
105 §2, 107 and 202; `python/FACADE.md` §4).

Two colour-management configurations are pinned profiles: Painter's Legacy mode (`PROFILES`; the
working space is linear sRGB and images come in and go out as sRGB, the Assets3D contract PRJ-05)
and OCIO with Painter's substance config, identified by its SHA-256 (`PAINTER_OCIO_CONFIG_SHA256`,
the evaluator's `kPainterOcioConfigSha256`; the file is hashed, never parsed). A project declaring
any other configuration fails with `NotYetSupported` before anything is evaluated. The facade never
rewrites a project's declared mode, working space, input rules or display transform.

Creation (decision 207). `project.create` takes the mode from the environment at the call, as
Painter documents: `OCIO` naming a configuration gives an OCIO project, else `PAINTER_ACE_CONFIG`
an ACE project, else Legacy (`creation_ocio_config_hash`). The pipeline sets `OCIO` in-process
before `create`, so the variable is read at the call, not at start-up. Only Painter's substance
config is created; any other configuration raises before anything is created.

Uniform colours. A colour without a space is sRGB on a colour-managed channel (an sRGB8 channel:
BaseColor in the templates) and Raw elsewhere, as Painter documents and the
`export-ocio-encode-legacy` readbacks record. A user channel is not colour managed for a uniform
colour, sRGB8 or not: Painter reads back and exports the value set whatever its space
(`colour-ramps-srgb`, `-working`, `-raw`; decision 115), and so does any channel the facade does not
colour-manage. The facade stores every uniform colour as its
working-space value (`Color(working, "Working")`): the native evaluator takes a stored value as
linear, so it receives the value Painter composites, and Painter's readback (`.working`) is that
value. The working value is computed by the native rule every setter uses
(`uzpainter.colormanagement._working_value`, `python::WorkingColour`; decision 240), so the facade,
the native API, the MCP `source_set` and `sync_stack` store the same value for the same colour,
with the same refusals. In Legacy the sRGB decode is Painter's float32 formula (decision 214):
x = f32(v), x * (1 / 12.92f) up to 0.04045f, else ((x + 0.055f) * (1 / 1.055f)) ^ 2.4f, each
reciprocal the float32 quotient of 1 by the float32 constant and the power of the float32 operands
rounded once to float32 (P20-B, `phase1-srgb-uniform-decode-part1..4`: all 448 recorded
components, both recordings).

Bitmap sources. A bitmap takes Painter's default space for its channel when bound
(`default_bitmap_space`, from the recorded `get_source` readbacks) and lists Painter's available
spaces (`available_bitmap_spaces`: `fill-layer-readback` s43, `export-ocio-encode-legacy`
colour-space captures and P20-A, `phase1-fill-channel-defaults`, on the default template's five
channels and a mask, colour and grey bitmaps alike); a channel without a recorded default or list
raises `NotYetSupported` naming the recording that settles it.

Under OCIO (decision 202) only what Session O records is admitted; everything else raises
`NotYetSupported` before any change:
- an sRGB uniform colour (explicit, or without a space on a decoding channel) reads Painter's
  measured working value of each float32 component (`ocio_srgb`, the 256 codes c / 255 and every
  other recorded component, generated into the native `evaluator::PainterOcioSrgbDecode`, decision
  212); no analytic decode reproduces it. Raw, Working and a colour without a space on a channel
  that does not decode are taken as given, as recorded;
- a bitmap on BaseColor lists the eleven spaces Painter offers there (`OCIO_COLOUR_SPACES` after
  the generic three) and a mask's mono source the three data spaces; a colour bitmap on BaseColor
  defaults to sRGB and a mask source to Data (`export-ocio-encode` captures and readbacks).
"""

from __future__ import annotations

import enum
import hashlib
import os
import struct
from typing import Any

import uzpainter

from uzpainter_facade import bitmap_defaults

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
OCIO_PROFILE = "ocio"
# SHA-256 of Painter 12.1.5's resources/ocio/substance/config.ocio (decision 134): the evaluator's
# kPainterOcioConfigSha256 (src/evaluator/sources.h).
PAINTER_OCIO_CONFIG_SHA256 = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"
OCIO_GAP = "phase1.15_compositor-colour-fits item 2.6, decision 202"


def require_supported_configuration() -> str:
    """The pinned profile of the open project; `NotYetSupported` before any evaluation when its
    declared configuration is not pinned."""
    declared = uzpainter.colormanagement.get_color_management()
    mode = str(declared.get("mode", ""))
    if mode in PROFILES:
        return PROFILES[mode]
    if mode == OCIO_PROFILE and declared.get("config_hash") == PAINTER_OCIO_CONFIG_SHA256:
        return OCIO_PROFILE
    raise uzpainter.NotYetSupported(
        f"colour management '{mode}' (working space '{declared.get('working_space', '')}', config "
        f"hash '{declared.get('config_hash', '')}') is not a pinned colour profile; only Painter's "
        "Legacy mode and OCIO with Painter's substance config (SHA-256 "
        f"{PAINTER_OCIO_CONFIG_SHA256[:8]}...) are supported (decisions 107, 190 and 202)"
    )


def _configuration_sha256(variable: str, path: str) -> str:
    """The SHA-256 of the configuration file `variable` names; `ProjectError` when it cannot be
    read (Painter refuses an invalid configuration at create)."""
    try:
        with open(path, "rb") as file:
            return hashlib.sha256(file.read()).hexdigest()
    except OSError as error:
        raise uzpainter.ProjectError(
            f"the {variable} configuration {path!r} cannot be read ({error.strerror}): Painter "
            "refuses an invalid configuration at create"
        ) from None


def creation_ocio_config_hash() -> str | None:
    """The OCIO configuration hash `project.create` gives the new project; None for Legacy.

    Painter's documented rule: `OCIO` naming a configuration selects OCIO (it wins over
    `PAINTER_ACE_CONFIG`), `PAINTER_ACE_CONFIG` alone selects ACE, neither selects Legacy, and an
    invalid configuration raises `ProjectError`. The file `OCIO` names is hashed; only Painter's
    substance config is created, and ACE is not fitted: both raise `NotYetSupported`. Every
    refusal comes before anything is created."""
    ocio = os.environ.get("OCIO")
    if ocio:
        digest = _configuration_sha256("OCIO", ocio)
        if digest != PAINTER_OCIO_CONFIG_SHA256:
            raise uzpainter.NotYetSupported(
                f"create under the OCIO configuration {ocio!r} (SHA-256 {digest}): only "
                f"Painter's substance config (SHA-256 {PAINTER_OCIO_CONFIG_SHA256[:8]}...) is a "
                "pinned colour profile (decisions 190, 202 and 207)"
            )
        return digest
    ace = os.environ.get("PAINTER_ACE_CONFIG")
    if ace:
        _configuration_sha256("PAINTER_ACE_CONFIG", ace)
        raise uzpainter.NotYetSupported(
            "create under PAINTER_ACE_CONFIG: Painter's ACE colour management is not a pinned "
            "colour profile (decision 207); unset it for a Legacy project, or set OCIO to "
            "Painter's substance config"
        )
    return None


def active_profile() -> str:
    """The pinned profile of the open project, Legacy without one."""
    if not uzpainter.project.is_open():
        return DEFAULT_PROFILE
    return require_supported_configuration()


# ── float32 arithmetic ─────────────────────────────────────────────────────────────────────────


def f32(value: float) -> float:
    """`value` rounded to float32."""
    return float(struct.unpack("f", struct.pack("f", value))[0])


_F_12_92 = f32(12.92)
_F_0_055 = f32(0.055)
_F_1_055 = f32(1.055)
_F_0_0031308 = f32(0.0031308)
_F_INV_2_4 = f32(1.0 / 2.4)


def linear_to_srgb(value: float) -> float:
    """The float32 sRGB encode of one component (the inverse transfer)."""
    x = f32(value)
    if x <= _F_0_0031308:
        return f32(x * _F_12_92)
    return f32(f32(_F_1_055 * f32(max(x, 0.0) ** _F_INV_2_4)) - _F_0_055)


def _ocio_unrecorded(what: str) -> Exception:
    error: Exception = uzpainter.NotYetSupported(f"under OCIO, {what} is not recorded ({OCIO_GAP})")
    return error


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


def _working(
    rgb: tuple[float, float, float], space: str | None, decodes: bool
) -> tuple[float, float, float]:
    """The float32 working value of `rgb` in `space` (None: no space) on a channel that `decodes`
    an sRGB colour or not, under the open project's profile: the native rule every setter uses
    (`python::WorkingColour`, decision 240). An sRGB component decodes by Painter's float32 formula
    in Legacy (decision 214) and reads Painter's measured value under OCIO, where a component it
    does not record raises `NotYetSupported`; a space outside the profile raises `ValueError`
    (Legacy) or `NotYetSupported` (OCIO); every refusal comes before any change."""
    ocio = active_profile() == OCIO_PROFILE
    r, g, b = uzpainter.colormanagement._working_value(*rgb, space, decodes, ocio)
    return (r, g, b)


def to_working(rgb: tuple[float, float, float], space: str) -> tuple[float, float, float]:
    """`rgb` encoded in `space`, as float32 working-space values (the open project's profile)."""
    return _working(rgb, space, True)


def from_working(rgb: tuple[float, float, float], space: str) -> tuple[float, float, float]:
    """Working-space values encoded in `space` (the open project's profile), as float32."""
    if active_profile() == OCIO_PROFILE and not (space in _RAW or space == "Working"):
        raise _ocio_unrecorded(f"the encode of a working-space colour in '{space}'")
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
            raise RuntimeError("color_space is undefined, no conversion can be done.")
        return color_space_name(self.color_space)

    def convert(self, color_space: Any) -> tuple[float, float, float]:
        """Get r,g,b values encoded in the given color space."""
        source = self._space()
        target = color_space_name(color_space)
        if (source == target and source in _SRGB | _LINEAR | _RAW) or source in _RAW:
            r, g, b = self.value_raw
            return (f32(r), f32(g), f32(b))
        working = to_working(self.value_raw, source)
        return from_working(working, target)

    @property
    def value(self) -> tuple[float, float, float]:
        """The colour encoded in sRGB if its space is defined and not Raw, else `value_raw`."""
        if self.color_space is None:
            return self.value_raw
        return self.sRGB

    @property
    def sRGB(self) -> tuple[float, float, float]:
        return self.convert(GenericColorSpace.sRGB)

    @sRGB.setter
    def sRGB(self, rgb: tuple[float, float, float]) -> None:
        self.value_raw = _rgb(rgb)
        self.color_space = GenericColorSpace.sRGB

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
    space = None if color.color_space is None else color_space_name(color.color_space)
    return _working(color.value_raw, space, colour_managed)


def stored_color(color: Any, colour_managed: bool) -> Any:
    """The native colour the facade stores: the working value in the Working space."""
    r, g, b = working_value(color, colour_managed)
    return uzpainter.colormanagement.Color(r, g, b, "Working")


def read_color(native: Any, colour_managed: bool = True) -> Color:
    """A native uniform colour as Painter returns it: always with a defined space."""
    space = native.color_space
    r, g, b = native.value_raw
    if not colour_managed:
        return Color(r, g, b, GenericColorSpace.Raw)
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
    "a Tier 0 probe like P20-A (phase1-fill-channel-defaults, decision 107) reading get_source, "
    "get_color_space and list_available_color_spaces of a bitmap and a fresh fill on a template "
    "with the channel"
)


def bitmap_default_space(
    channel: str | None,
    channel_format: str | None,
    descriptor: bitmap_defaults.PngDescriptor | None,
    colour_image: bool,
) -> Any:
    """Painter's colour space of a bitmap bound on `channel` (canonical name; None: a mask's mono
    source) of format `channel_format`, for a bitmap of `descriptor`. An exact observed entry
    (bitmap_defaults.lookup: profile, OCIO configuration, template, channel, format and PNG
    descriptor) answers first; a miss applies the older rules (`default_bitmap_space`) unchanged,
    which still refuse a channel they do not support."""
    # A mask source, an unknown bitmap or one of another kind never reads the project context.
    if (
        channel is not None
        and channel_format is not None
        and bitmap_defaults.in_domain(descriptor)
        and uzpainter.project.is_open()
    ):
        profile = active_profile()
        context = bitmap_defaults.DefaultContext(
            profile,
            PAINTER_OCIO_CONFIG_SHA256 if profile == OCIO_PROFILE else None,
            str(uzpainter.project.template()),
            channel,
            channel_format,
        )
        identity = bitmap_defaults.lookup(context, descriptor)
        if identity is not None:
            return observed_space(identity)
    return default_bitmap_space(channel, colour_image)


def observed_space(identity: bitmap_defaults.SpaceIdentity) -> Any:
    """The documented member (or configuration string) of an observed space identity, exactly:
    the class is matched by name, never guessed from the member name alone."""
    if identity.kind == "str":
        return identity.name
    for kind in SPACE_ENUMS:
        if kind.__name__ == identity.kind and identity.name in kind.__members__:
            return kind[identity.name]
    raise TypeError(f"{identity} is not a documented colour space")


def default_bitmap_space(channel: str | None, colour_image: bool) -> Any:
    """Painter's colour space of a bitmap bound on `channel` (None: a mask's mono source). In
    Legacy mode a grey bitmap takes the same space as a colour one (P20-A)."""
    if active_profile() == OCIO_PROFILE and channel is not None:
        if channel != "BaseColor":
            raise _ocio_unrecorded(f"Painter's default colour space of a bitmap on {channel}")
        if not colour_image:
            raise _ocio_unrecorded("Painter's default colour space of a grey bitmap on BaseColor")
    if channel is None or channel in DATA_CHANNELS:
        return DataColorSpace.Data
    if channel == "BaseColor":
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


# The OCIO configuration space Painter reports as the string "sRGB": its native tag is qualified so
# that it is not the generic member's "sRGB" (src/evaluator/sources.h `BitmapColourSpaceIn`, which
# evaluates it as that same space under the pinned OCIO profile only).
OCIO_STRING_TAGS = {"sRGB": "OcioColorSpace.sRGB"}


def bitmap_space_tag(space: Any) -> str:
    """The native tag of a bitmap colour space: a `LegacyColorSpace` member by qualified name (its
    `sRGB` is not the generic one; the evaluator reads both tags, `src/evaluator/sources.h`), any
    other member by name, a string as given except an OCIO configuration string of
    `OCIO_STRING_TAGS` under the pinned OCIO profile, which is qualified."""
    if isinstance(space, LegacyColorSpace):
        return f"LegacyColorSpace.{space.name}"
    if isinstance(space, str) and space in OCIO_STRING_TAGS and active_profile() == OCIO_PROFILE:
        return OCIO_STRING_TAGS[space]
    return space_name(space)


def bitmap_space_member(tag: str) -> Any:
    """The documented member, or configuration string, of a native bitmap colour-space tag
    (`bitmap_space_tag`)."""
    kind, _, name = tag.partition(".")
    if kind == "LegacyColorSpace" and name in LegacyColorSpace.__members__:
        return LegacyColorSpace[name]
    for string, qualified in OCIO_STRING_TAGS.items():
        if tag == qualified:
            return string
    return space_member(tag)


# The spaces Painter offers for a bitmap on BaseColor under OCIO with its substance config after the
# generic three, as strings (`export-ocio-encode` s43-s45, both recordings).
OCIO_COLOUR_SPACES = (
    "Linear",
    "sRGB",
    "Rec709",
    "Rec2020",
    "ACES - ACEScg",
    "Display P3",
    "ACES sRGB",
    "False Color",
)


# The channels whose bitmaps Painter lists the data spaces for, outside sRGB8 (P20-A: BaseMetalness
# and SpecularRoughness in L8, Height in L16F).
DATA_LISTED_CHANNELS = frozenset({"BaseMetalness", "SpecularRoughness", "Height"})


def available_bitmap_spaces(channel: str | None, colour_managed: bool) -> list[Any]:
    """`SourceBitmap.list_available_color_spaces`. Legacy mode: a mask's mono source, a user
    channel other than sRGB8 (RGB8, L8, RGB16, L16, RGB16F and RGB32F recorded), BaseMetalness,
    SpecularRoughness and Height offer the data spaces, Normal the normal spaces, an sRGB8 channel
    the colour spaces, for a colour and a grey bitmap alike (P20-A). OCIO: a mask's mono source
    offers the data spaces and BaseColor the generic spaces and Painter's OCIO spaces."""
    if active_profile() == OCIO_PROFILE and channel is not None:
        if channel != "BaseColor":
            raise _ocio_unrecorded(f"the colour spaces Painter lists for a bitmap on {channel}")
        generic = [GenericColorSpace.Raw, GenericColorSpace.Working, GenericColorSpace.sRGB]
        return [*generic, *OCIO_COLOUR_SPACES]
    data = channel is not None and (channel.startswith("User") or channel in DATA_LISTED_CHANNELS)
    if channel is None or (data and not colour_managed):
        return [GenericColorSpace.Raw, DataColorSpace.Data, DataColorSpace.DataSigned]
    if channel == "Normal" and not colour_managed:
        return [
            GenericColorSpace.Raw,
            NormalColorSpace.NormalXYZRight,
            NormalColorSpace.NormalXYZLeft,
        ]
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
