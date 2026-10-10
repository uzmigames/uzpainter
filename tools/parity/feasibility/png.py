"""PNG encode and decode at native depth (8- or 16-bit integer samples) with numpy.

Pillow truncates 16-bit RGB PNGs to 8 bits, so the study decodes PNG itself (ISO/IEC 15948:
IHDR, IDAT, the five row filters) to compare oracle and prototype values code for code
(`parity/CONTRACT.md` §3.1). Only non-interlaced grey, grey-alpha, RGB and RGBA images are used.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np
import numpy.typing as npt

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS_OF_COLOR_TYPE = {0: 1, 4: 2, 2: 3, 6: 4}
COLOR_TYPE_OF_CHANNELS = {1: 0, 2: 4, 3: 2, 4: 6}

Samples = npt.NDArray[np.uint16]


class PngError(ValueError):
    """The bytes are not a PNG this module decodes."""


def chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    if not data.startswith(SIGNATURE):
        raise PngError("not a PNG file")
    found: list[tuple[bytes, bytes]] = []
    offset = len(SIGNATURE)
    while offset + 8 <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        found.append((kind, data[offset + 8 : offset + 8 + length]))
        offset += 12 + length
        if kind == b"IEND":
            break
    return found


def _paeth_row(raw: npt.NDArray[np.uint8], up: npt.NDArray[np.uint8], bpp: int) -> bytearray:
    line = bytearray(raw.tobytes())
    above = up.tobytes()
    for i in range(len(line)):
        a = line[i - bpp] if i >= bpp else 0
        b = above[i]
        c = above[i - bpp] if i >= bpp else 0
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        predictor = a if pa <= pb and pa <= pc else b if pb <= pc else c
        line[i] = (line[i] + predictor) & 0xFF
    return line


def _average_row(raw: npt.NDArray[np.uint8], up: npt.NDArray[np.uint8], bpp: int) -> bytearray:
    line = bytearray(raw.tobytes())
    above = up.tobytes()
    for i in range(len(line)):
        a = line[i - bpp] if i >= bpp else 0
        line[i] = (line[i] + ((a + above[i]) >> 1)) & 0xFF
    return line


def decode(data: bytes) -> Samples:
    """Decoded samples as `uint16`, shape (height, width, channels), top row first."""
    found = chunks(data)
    if not found or found[0][0] != b"IHDR":
        raise PngError("PNG without IHDR")
    width, height, depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", found[0][1])
    if depth not in (8, 16) or color_type not in CHANNELS_OF_COLOR_TYPE or interlace:
        raise PngError(f"unsupported PNG layout (depth {depth}, colour type {color_type})")
    channels = CHANNELS_OF_COLOR_TYPE[color_type]
    bpp = channels * depth // 8
    stride = width * bpp
    raw = np.frombuffer(
        zlib.decompress(b"".join(body for kind, body in found if kind == b"IDAT")), np.uint8
    )
    if raw.size != height * (stride + 1):
        raise PngError("IDAT size does not match the header")
    rows = raw.reshape(height, stride + 1)
    out = np.zeros((height, stride), np.uint8)
    previous = np.zeros(stride, np.uint8)
    for y in range(height):
        kind, line = int(rows[y, 0]), rows[y, 1:]
        if kind == 0:
            current = line.copy()
        elif kind == 1:
            lanes = line.reshape(width, bpp).astype(np.uint64)
            current = (np.cumsum(lanes, axis=0) & 0xFF).astype(np.uint8).reshape(stride)
        elif kind == 2:
            current = line + previous
        elif kind == 3:
            current = np.frombuffer(_average_row(line, previous, bpp), np.uint8)
        elif kind == 4:
            current = np.frombuffer(_paeth_row(line, previous, bpp), np.uint8)
        else:
            raise PngError(f"invalid PNG filter {kind}")
        out[y] = current
        previous = out[y]
    if depth == 16:
        samples = out.reshape(height, width * channels, 2).astype(np.uint16)
        values: Samples = (samples[..., 0] * np.uint16(256) + samples[..., 1]).astype(np.uint16)
    else:
        values = out.astype(np.uint16)
    decoded: Samples = values.reshape(height, width, channels).astype(np.uint16)
    return decoded


def encode(samples: npt.NDArray[np.integer], depth: int = 16) -> bytes:
    """A PNG of integer samples (shape (h, w) or (h, w, c)); every row uses the Up filter."""
    array = np.asarray(samples)
    if array.ndim == 2:
        array = array[:, :, None]
    height, width, channels = array.shape
    if depth not in (8, 16) or channels not in COLOR_TYPE_OF_CHANNELS:
        raise PngError(f"cannot encode depth {depth} with {channels} channels")
    if array.min() < 0 or array.max() >= (1 << depth):
        raise PngError(f"samples out of range for {depth}-bit")
    if depth == 16:
        big = array.astype(">u2").view(np.uint8).reshape(height, width * channels * 2)
    else:
        big = array.astype(np.uint8).reshape(height, width * channels)
    up = np.vstack([big[:1], big[1:] - big[:-1]]).astype(np.uint8)
    raw = np.hstack([np.full((height, 1), 2, np.uint8), up]).tobytes()

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(
        ">IIBBBBB", width, height, depth, COLOR_TYPE_OF_CHANNELS[channels], 0, 0, 0
    )
    return (
        SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def read(path: Path) -> Samples:
    return decode(path.read_bytes())


def write(path: Path, samples: npt.NDArray[np.integer], depth: int = 16) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode(samples, depth))
