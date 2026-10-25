"""Painter's default colour space of a bitmap source, in the observed domain only.

Shared by the facade (`colour.default_bitmap_space`) and host-side replays, so nothing here imports
the native `uzpainter` module. The table holds what two admitted Tier 0 probes observed, stable in
both recordings (`tier0/api-probes/source-bitmap-defaults-unreal-legacy` and `-ocio`): the R-322
setup, one bitmap per channel, read back with `SourceBitmap.get_color_space`. An entry matches
only its exact context (profile, OCIO configuration hash, installed template id, canonical channel,
channel format) and an exact PNG descriptor: 16-bit grey or RGB, 256 x 256, no interlace, chunks
exactly IHDR, IDAT..., IEND. Anything else is a miss (`lookup` returns None): no other depth,
layout, size, ancillary chunk, template, profile or format is inferred.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# SHA-256 of Painter's resources/ocio/substance/config.ocio (decision 134; colour.py pins the same).
PAINTER_OCIO_CONFIG_SHA256 = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"
GREY, RGB = 0, 2  # PNG IHDR colour types


@dataclass(frozen=True)
class PngDescriptor:
    width: int
    height: int
    bit_depth: int
    color_type: int
    compression: int
    filter: int
    interlace: int
    chunks: tuple[str, ...]
    # True only for the observed shape whose IDAT stream inflates, within a bound, to exactly the
    # expected scanlines (each with a filter byte 0..4) and ends there: no trailing data.
    scanlines_verified: bool = False


@dataclass(frozen=True)
class DefaultContext:
    profile: str  # "legacy" or "ocio"
    config_sha256: str | None  # the OCIO configuration's SHA-256; None in Legacy
    template_id: str  # the installed template id the project was created with
    channel: str  # canonical channel name
    channel_format: str  # the stack channel's format name (e.g. "L8", "sRGB8")


@dataclass(frozen=True)
class SpaceIdentity:
    """A colour space as Painter's `get_color_space` returns it: an enum class and member name, or
    `kind == "str"` for a configuration space given as a string."""

    kind: str
    name: str


def describe_png(data: bytes) -> PngDescriptor | None:
    """The descriptor of exactly these bytes, or None when they are not a well-formed PNG: the
    signature, IHDR first with 13 bytes, IEND last and empty, every chunk complete with its CRC."""
    if not data.startswith(PNG_SIGNATURE):
        return None
    chunks: list[str] = []
    ihdr: bytes | None = None
    idat = bytearray()
    position = len(PNG_SIGNATURE)
    while position < len(data):
        if position + 8 > len(data):
            return None
        (length,) = struct.unpack(">I", data[position : position + 4])
        kind = data[position + 4 : position + 8]
        end = position + 12 + length
        if end > len(data):
            return None
        body = data[position + 8 : position + 8 + length]
        if kind == b"IDAT":
            idat += body
        (crc,) = struct.unpack(">I", data[position + 8 + length : end])
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            return None
        name = kind.decode("latin-1")
        if not chunks and name != "IHDR":
            return None
        if name == "IHDR":
            if chunks or length != 13:
                return None
            ihdr = body
        if chunks and chunks[-1] == "IEND":
            return None
        if name == "IEND" and length != 0:
            return None
        if not chunks or chunks[-1] != name or name != "IDAT":
            chunks.append(name)
        position = end
    if ihdr is None or not chunks or chunks[-1] != "IEND":
        return None
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", ihdr
    )
    shaped = (width, height, depth, compression, filtering, interlace) == (256, 256, 16, 0, 0, 0)
    verified = shaped and colour in (GREY, RGB) and _scanlines_ok(bytes(idat), colour)
    return PngDescriptor(
        width, height, depth, colour, compression, filtering, interlace, tuple(chunks), verified
    )


def _scanlines_ok(idat: bytes, colour: int) -> bool:
    """Whether a 256 x 256 16-bit grey (1 sample) or RGB (3) IDAT stream inflates to exactly its
    scanlines with filter bytes 0..4 and nothing after the zlib stream. Bounded: never more than
    one byte beyond the expected size is inflated. Pixels are not decoded."""
    row = 1 + 256 * (1 if colour == GREY else 3) * 2
    expected = 256 * row
    inflater = zlib.decompressobj()
    try:
        out = inflater.decompress(idat, expected + 1)
    except zlib.error:
        return False
    if len(out) != expected or inflater.unconsumed_tail or not inflater.eof or inflater.unused_data:
        return False
    return all(out[i * row] <= 4 for i in range(256))


def _observed(descriptor: PngDescriptor) -> int | None:
    """The colour type when the descriptor is in the observed domain, else None."""
    if (
        descriptor.width == descriptor.height == 256
        and descriptor.bit_depth == 16
        and descriptor.color_type in (GREY, RGB)
        and (descriptor.compression, descriptor.filter, descriptor.interlace) == (0, 0, 0)
        and descriptor.chunks == ("IHDR", "IDAT", "IEND")
        and descriptor.scanlines_verified
    ):
        return descriptor.color_type
    return None


_LEGACY = ("legacy", None, "pbr-metallic-roughness-alpha-blend")
_OCIO = ("ocio", PAINTER_OCIO_CONFIG_SHA256, "default")
_DATA = SpaceIdentity("DataColorSpace", "Data")
_DATA_SIGNED = SpaceIdentity("DataColorSpace", "DataSigned")
_NORMAL = SpaceIdentity("NormalColorSpace", "NormalXYZLeft")

# (profile, config, template, canonical channel, channel format, colour type) -> observed space.
TABLE: dict[tuple[str, str | None, str, str, str, int], SpaceIdentity] = {
    (*_LEGACY, "BaseColor", "sRGB8", RGB): SpaceIdentity("LegacyColorSpace", "sRGB"),
    (*_LEGACY, "SpecularRoughness", "L8", GREY): _DATA,
    (*_LEGACY, "BaseMetalness", "L8", GREY): _DATA,
    (*_LEGACY, "Height", "L16F", GREY): _DATA_SIGNED,
    (*_LEGACY, "Normal", "RGB16F", RGB): _NORMAL,
    (*_LEGACY, "Opacity", "L8", GREY): _DATA,
    (*_LEGACY, "EmissionColor", "sRGB8", RGB): SpaceIdentity("LegacyColorSpace", "sRGB"),
    (*_LEGACY, "AO", "L16", GREY): _DATA,
    (*_LEGACY, "SpecularWeight", "L8", GREY): _DATA,
    (*_OCIO, "BaseColor", "sRGB8", RGB): SpaceIdentity("str", "sRGB"),
    (*_OCIO, "SpecularRoughness", "L8", GREY): _DATA,
    (*_OCIO, "BaseMetalness", "L8", GREY): _DATA,
    (*_OCIO, "Height", "L16F", GREY): _DATA_SIGNED,
    (*_OCIO, "Normal", "RGB16F", RGB): _NORMAL,
    (*_OCIO, "Opacity", "L8", GREY): _DATA,
    (*_OCIO, "EmissionColor", "sRGB8", RGB): SpaceIdentity("str", "sRGB"),
    (*_OCIO, "AO", "L16", GREY): _DATA,
    (*_OCIO, "SpecularWeight", "L8", GREY): _DATA,
}


def in_domain(descriptor: PngDescriptor | None) -> bool:
    """Whether a bitmap's descriptor is of the observed kind at all (no project state read):
    callers skip the context of any other bitmap and apply their older rules directly."""
    return descriptor is not None and _observed(descriptor) is not None


def lookup(context: DefaultContext, descriptor: PngDescriptor | None) -> SpaceIdentity | None:
    """The observed default space of exactly this context and descriptor, or None when no entry
    records it (a legitimate miss: callers apply their older rules, unchanged)."""
    colour = None if descriptor is None else _observed(descriptor)
    if colour is None:
        return None
    return TABLE.get(
        (
            context.profile,
            context.config_sha256,
            context.template_id,
            context.channel,
            context.channel_format,
            colour,
        )
    )


def native_tag(identity: SpaceIdentity, profile: str) -> str:
    """The native bitmap colour-space tag of an identity in `profile`, as the facade's
    `bitmap_space_tag` writes it: a LegacyColorSpace member by qualified name (its sRGB is not the
    generic one), the OCIO configuration string "sRGB" as "OcioColorSpace.sRGB" under the "ocio"
    profile, any other member by name and any other string as given."""
    if identity.kind == "LegacyColorSpace":
        return f"LegacyColorSpace.{identity.name}"
    if identity.kind == "str" and identity.name == "sRGB" and profile == "ocio":
        return "OcioColorSpace.sRGB"
    return identity.name
