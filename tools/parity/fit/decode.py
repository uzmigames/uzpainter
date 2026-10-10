"""Decode exported maps at native depth (`parity/CONTRACT.md` §3.1).

PNG goes through the repository's own decoder (8- and 16-bit integer code values, no
truncation). OpenEXR exports (Painter writes PIZ-compressed float scanlines) are read with the
OpenEXR Python binding (BSD-3-Clause, approved source S-EXR), a tooling dependency of the
owner's machine only: it is imported when a float map is decoded, never on a machine without
the store.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.feasibility import png

Array = npt.NDArray[Any]


@dataclass(frozen=True)
class Decoded:
    """Samples of one map, shape (height, width, channels), top row first.

    `integer` maps hold code values as int64; float maps hold float64 values widened exactly
    from the stored half or float samples. `bits` is the stored bits per channel.
    """

    values: Array
    integer: bool
    bits: int

    @property
    def maximum_code(self) -> int:
        return (1 << self.bits) - 1


def decode_exr(data: bytes) -> Decoded:
    import OpenEXR

    handle, name = tempfile.mkstemp(suffix=".exr")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        with OpenEXR.File(name, separate_channels=True) as exr:
            channels = exr.channels()
            order = [c for c in ("R", "G", "B", "A", "Y") if c in channels]
            order += sorted(c for c in channels if c not in order)
            planes = [np.asarray(channels[c].pixels) for c in order]
    finally:
        os.unlink(name)
    bits = 16 if planes[0].dtype == np.float16 else 32
    values = np.stack([p.astype(np.float64) for p in planes], axis=-1)
    return Decoded(values, False, bits)


def decode(data: bytes) -> Decoded:
    """Decode a PNG or OpenEXR export by its signature (never by its name)."""
    if data.startswith(png.SIGNATURE):
        header = png.chunks(data)[0][1]
        return Decoded(png.decode(data).astype(np.int64), True, int(header[8]))
    if data[:4] == b"\x76\x2f\x31\x01":
        return decode_exr(data)
    raise ValueError("not a PNG or OpenEXR file")
