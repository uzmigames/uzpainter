"""TGA8 texture samples: uncompressed/RLE L, LA, RGB and RGBA, without colour conversion.

The byte layout is the public TGA format used by the pinned stb writer. Palette,
packed RGB, interleaved rows and optional TGA 2.0 metadata areas are outside this
recorder domain and fail loudly.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class Header:
    width: int
    height: int
    channels: int
    descriptor: int
    offset: int
    rle: bool


def _header(data: bytes) -> Header:
    if len(data) < 18:
        raise ValueError("TGA: truncated header")
    identifier, cmap, kind, first, length, entry_bits, _, _, w, h, bits, descriptor = (
        struct.unpack_from("<BBBHHBHHHHBB", data)
    )
    if cmap != 0 or first != 0 or length != 0 or entry_bits != 0:
        raise ValueError("TGA: color maps are not supported")
    if kind not in (2, 3, 10, 11):
        raise ValueError("TGA: image type is not supported")
    channels = bits // 8
    allowed = (8, 16) if kind in (3, 11) else (24, 32)
    if bits not in allowed or descriptor & 0xC0:
        raise ValueError("TGA: only non-interleaved 8-bit channels are supported")
    alpha_bits = 8 if channels in (2, 4) else 0
    if descriptor & 15 != alpha_bits:
        raise ValueError("TGA: ambiguous or unsupported alpha descriptor")
    if not w or not h or w * h * channels > 0x7FFFFFFF:
        raise ValueError("TGA: invalid dimensions or decoded byte count")
    if 18 + identifier > len(data):
        raise ValueError("TGA: truncated image identifier")
    return Header(w, h, channels, descriptor, 18 + identifier, kind in (10, 11))


def _packets(data: bytes, header: Header) -> Iterator[tuple[int, bytes, bool]]:
    remaining = header.width * header.height
    cursor = header.offset
    limit = len(data)
    if len(data) >= 26 and data.endswith(b"TRUEVISION-XFILE.\0"):
        limit -= 26
        offsets = struct.unpack_from("<II", data, limit)
        if any(offset and not header.offset <= offset < limit for offset in offsets):
            raise ValueError("TGA: invalid extension/developer offset")
        # These areas can reference earlier metadata blocks. Their top-level
        # offsets alone cannot establish where the pixel payload ends.
        if any(offsets):
            raise ValueError("TGA: extension/developer areas are not supported")
    while remaining:
        repeated = False
        count = remaining
        if header.rle:
            if cursor >= limit:
                raise ValueError("TGA: truncated RLE packet header")
            packet = data[cursor]
            cursor += 1
            count = (packet & 127) + 1
            repeated = bool(packet & 128)
        if count > remaining:
            raise ValueError("TGA: packet exceeds image dimensions")
        length = header.channels * (1 if repeated else count)
        if cursor + length > limit:
            raise ValueError("TGA: truncated pixel payload")
        yield count, data[cursor : cursor + length], repeated
        cursor += length
        remaining -= count
    # A TGA 2.0 footer without optional metadata areas is supported.


def inspect(data: bytes) -> Header:
    """Measure supported storage and validate the complete pixel stream without expanding it."""
    header = _header(data)
    for _ in _packets(data, header):
        pass
    return header


def decode(data: bytes) -> npt.NDArray[np.uint8]:
    """Return top-first RGB-order samples; preserve alpha and all stored 8-bit codes."""
    header = inspect(data)
    samples = np.empty((header.width * header.height, header.channels), dtype=np.uint8)
    offset = 0
    for count, payload, repeated in _packets(data, header):
        block = np.frombuffer(payload, dtype=np.uint8).reshape(-1, header.channels)
        samples[offset : offset + count] = block[0] if repeated else block
        offset += count
    image = samples.reshape(header.height, header.width, header.channels)
    if not header.descriptor & 32:
        image = image[::-1]
    if header.descriptor & 16:
        image = image[:, ::-1]
    if header.channels >= 3:
        image = image[..., [2, 1, 0, *range(3, header.channels)]]
    return np.ascontiguousarray(image)
