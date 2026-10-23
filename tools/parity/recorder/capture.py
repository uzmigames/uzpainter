"""Pixel capture checks: measured storage format, current-output verification, silhouette.

- Storage format (`golden-private.json` `storage_format`) is measured from the file bytes: PNG
  IHDR and colour chunks, OpenEXR channel list, TGA header and pixel stream.
  Never inferred from a map name.
- Current-output verification (task items 2.3, 2.4): before a capture the recorder writes a fence
  file after the last applied instruction (and, for Iray, after convergence). A capture is
  accepted only if it is exactly the set of files the capture call reported, in a directory that
  was empty, each written no earlier than the fence by the same filesystem clock. Anything else
  is refused and no record is written.
- Silhouette (07-preview-and-render-parity.md §2.2 step 5): the render's coverage must match the
  fixture's authored silhouette mask, outside the mask's don't-care band.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity import tga
from tools.parity.recorder.session import RecorderError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
EXR_MAGIC = 20000630
PNG_CHANNELS = {0: 1, 2: 3, 3: 3, 4: 2, 6: 4}
EXR_SAMPLE_TYPES = {0: ("uint", 32), 1: ("half", 16), 2: ("float", 32)}
MEDIA_TYPES = {"png": "image/png", "exr": "image/x-exr", "tga": "image/x-tga"}


class StaleCaptureError(RecorderError):
    """A captured file is not provably the output of the current state; the record is refused."""


@dataclass(frozen=True)
class StorageFormat:
    container: str
    sample_type: str
    bits_per_channel: int
    channels: int
    encoding: str | None  # None when the file itself does not state its encoding

    def as_schema(self, encoding: str) -> dict[str, Any]:
        return {
            "container": self.container,
            "sample_type": self.sample_type,
            "bits_per_channel": self.bits_per_channel,
            "channels": self.channels,
            "encoding": encoding,
        }


def png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    if not data.startswith(PNG_SIGNATURE):
        raise RecorderError("not a PNG file")
    chunks: list[tuple[bytes, bytes]] = []
    offset = len(PNG_SIGNATURE)
    while offset + 8 <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        chunks.append((kind, data[offset + 8 : offset + 8 + length]))
        offset += 12 + length
        if kind == b"IEND":
            break
    return chunks


def png_format(data: bytes) -> StorageFormat:
    chunks = png_chunks(data)
    kind, header = chunks[0]
    if kind != b"IHDR":
        raise RecorderError("PNG without IHDR")
    bit_depth, color_type = header[8], header[9]
    if color_type == 3:
        raise RecorderError("palette PNG: not a texture export the recorder accepts")
    names = {k for k, _ in chunks}
    encoding: str | None = None
    if b"sRGB" in names:
        encoding = "srgb"
    elif b"gAMA" in names:
        (gamma,) = struct.unpack(">I", dict(chunks)[b"gAMA"])
        encoding = "linear" if gamma == 100000 else None
    return StorageFormat("png", "uint", bit_depth, PNG_CHANNELS[color_type], encoding)


def exr_format(data: bytes) -> StorageFormat:
    (magic,) = struct.unpack("<i", data[:4])
    if magic != EXR_MAGIC:
        raise RecorderError("not an OpenEXR file")
    offset = 8
    while data[offset] != 0:
        end = data.index(b"\0", offset)
        name = data[offset:end]
        type_end = data.index(b"\0", end + 1)
        (size,) = struct.unpack("<i", data[type_end + 1 : type_end + 5])
        value = data[type_end + 5 : type_end + 5 + size]
        if name == b"channels":
            return exr_channel_format(value)
        offset = type_end + 5 + size
    raise RecorderError("OpenEXR header without a channel list")


def exr_channel_format(chlist: bytes) -> StorageFormat:
    types: list[int] = []
    offset = 0
    while chlist[offset] != 0:
        end = chlist.index(b"\0", offset)
        (pixel_type,) = struct.unpack("<i", chlist[end + 1 : end + 5])
        types.append(pixel_type)
        offset = end + 1 + 16
    if not types or len(set(types)) != 1 or types[0] not in EXR_SAMPLE_TYPES:
        raise RecorderError(f"OpenEXR channels have mixed or unknown sample types {types}")
    sample_type, bits = EXR_SAMPLE_TYPES[types[0]]
    return StorageFormat("exr", sample_type, bits, len(types), "linear")


def measure_storage_format(path: Path) -> StorageFormat:
    data = path.read_bytes()
    if data.startswith(PNG_SIGNATURE):
        return png_format(data)
    if len(data) >= 4 and struct.unpack("<i", data[:4])[0] == EXR_MAGIC:
        return exr_format(data)
    if path.suffix.lower() == ".tga":
        try:
            measured = tga.inspect(data)
        except ValueError as error:
            raise RecorderError(f"{path.name}: TGA not supported: {error}") from error
        return StorageFormat("tga", "uint", 8, measured.channels, None)
    raise RecorderError(
        f"{path.name}: container not supported by the recorder (PNG, OpenEXR, TGA8)"
    )


def write_fence(path: Path) -> int:
    """Write the fence file and return its modification time (filesystem clock, ns)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fence\n")
    return path.stat().st_mtime_ns


def verify_current_outputs(listed: list[Path], directory: Path, fence_ns: int) -> None:
    """Refuse unless `directory` holds exactly `listed`, every file written after the fence."""
    root = directory.resolve()
    expected = {p.resolve() for p in listed}
    for path in expected:
        if not path.is_relative_to(root):
            raise StaleCaptureError(f"{path} is outside the fresh capture directory {root}")
    present = {p.resolve() for p in root.rglob("*") if p.is_file()}
    if present != expected:
        missing = sorted(str(p) for p in expected - present)
        extra = sorted(str(p) for p in present - expected)
        raise StaleCaptureError(f"capture directory mismatch: missing {missing}, unlisted {extra}")
    for path in sorted(expected):
        written = path.stat().st_mtime_ns
        if written < fence_ns:
            raise StaleCaptureError(
                f"{path.name} was written at {written} ns, before the last applied instruction "
                f"({fence_ns} ns): stale output refused"
            )


@dataclass(frozen=True)
class Image:
    width: int
    height: int
    channels: int
    pixels: list[tuple[int, ...]]  # row-major


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode_png(path: Path) -> Image:
    """Decode a non-interlaced 8- or 16-bit grey/grey-alpha/RGB/RGBA PNG to integer samples."""
    chunks = png_chunks(path.read_bytes())
    header = chunks[0][1]
    width, height = struct.unpack(">II", header[:8])
    bit_depth, color_type, interlace = header[8], header[9], header[12]
    if bit_depth not in (8, 16) or color_type not in (0, 2, 4, 6) or interlace:
        raise RecorderError(f"{path.name}: PNG layout not supported for pixel checks")
    channels = PNG_CHANNELS[color_type]
    size = bit_depth // 8
    bpp = channels * size
    stride = width * bpp
    raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    previous = bytearray(stride)
    pixels: list[tuple[int, ...]] = []
    for row in range(height):
        start = row * (stride + 1)
        kind = raw[start]
        line = bytearray(raw[start + 1 : start + 1 + stride])
        for i in range(stride):
            left = line[i - bpp] if i >= bpp else 0
            up = previous[i]
            upper_left = previous[i - bpp] if i >= bpp else 0
            if kind == 1:
                line[i] = (line[i] + left) & 0xFF
            elif kind == 2:
                line[i] = (line[i] + up) & 0xFF
            elif kind == 3:
                line[i] = (line[i] + (left + up) // 2) & 0xFF
            elif kind == 4:
                line[i] = (line[i] + paeth(left, up, upper_left)) & 0xFF
            elif kind != 0:
                raise RecorderError(f"{path.name}: invalid PNG filter {kind}")
        previous = line
        for x in range(width):
            px = line[x * bpp : (x + 1) * bpp]
            pixels.append(
                tuple(int.from_bytes(px[c * size : (c + 1) * size], "big") for c in range(channels))
            )
    return Image(width, height, channels, pixels)


@dataclass(frozen=True)
class SilhouetteResult:
    background_value: tuple[int, ...]
    foreground_checked: int
    background_checked: int
    dont_care: int


def check_silhouette(render: Path, mask: Path) -> SilhouetteResult:
    """The render's coverage equals the authored mask outside its don't-care band.

    Mask (first channel): 0 = background, the maximum code value = object, anything else =
    don't care (the anti-aliased edge band the fixture author marks). Every background pixel of
    the render must hold one identical value (the clear colour) and no object pixel may hold it.
    """
    image, silhouette = decode_png(render), decode_png(mask)
    if (image.width, image.height) != (silhouette.width, silhouette.height):
        raise StaleCaptureError(
            f"render is {image.width}x{image.height}, silhouette mask is "
            f"{silhouette.width}x{silhouette.height}"
        )
    full = max(s[0] for s in silhouette.pixels)
    background = [p for p, m in zip(image.pixels, silhouette.pixels, strict=True) if m[0] == 0]
    foreground = [p for p, m in zip(image.pixels, silhouette.pixels, strict=True) if m[0] == full]
    if not background or not foreground or full == 0:
        raise StaleCaptureError("silhouette mask must mark both background and object pixels")
    values = set(background)
    if len(values) != 1:
        raise StaleCaptureError(
            f"background is not uniform ({len(values)} distinct values): wrong frame or geometry"
        )
    (clear,) = values
    covered = sum(1 for p in foreground if p == clear)
    if covered:
        raise StaleCaptureError(
            f"{covered} object pixels show the background value: wrong frame or geometry"
        )
    return SilhouetteResult(
        clear,
        len(foreground),
        len(background),
        len(image.pixels) - len(foreground) - len(background),
    )
