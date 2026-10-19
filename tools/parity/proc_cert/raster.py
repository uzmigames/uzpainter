"""Decoding pinned rasters and measuring residuals in native integer code values.

Exact means bit-exact: every channel of every texel equal. The residual of a case is the
histogram of |candidate - oracle| over all its values, so per-case and pooled statistics (max,
exact sum and mean, nearest-rank p99, affected texels) are computed without floating error.
"""

from __future__ import annotations

import hashlib
import math
import struct
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.feasibility import png
from tools.parity.proc_cert.batch import FORMATS, RasterSpec

Raster = npt.NDArray[np.uint8] | npt.NDArray[np.uint16]
DTYPES: dict[str, np.dtype[Any]] = {"u8": np.dtype("<u1"), "u16": np.dtype("<u2")}


class RasterError(Exception):
    """Bytes or an array that are not a raster of the declared spec."""


def decode(spec: RasterSpec, encoding: str, data: bytes) -> Raster:
    """The (h, w, c) code values of a pinned blob, read-only."""
    dtype = DTYPES[spec.format]
    if encoding == "raw":
        expected = math.prod(spec.shape) * dtype.itemsize
        if len(data) != expected:
            raise RasterError(f"raw raster has {len(data)} bytes, {spec} needs {expected}")
        values: Raster = np.frombuffer(data, dtype).reshape(spec.shape)
    elif encoding == "png":
        try:
            header = png.chunks(data)[0][1]
            depth = struct.unpack(">IIB", header[:9])[2]
            samples = png.decode(data)
        except (png.PngError, IndexError, struct.error, ValueError) as error:
            raise RasterError(f"PNG does not decode: {error}") from error
        if depth != dtype.itemsize * 8:
            raise RasterError(
                f"PNG has {depth}-bit samples, {spec.format} needs {dtype.itemsize * 8}"
            )
        if samples.shape != spec.shape:
            raise RasterError(f"PNG has shape {samples.shape}, {spec} needs {spec.shape}")
        values = samples.astype(dtype)
    else:
        raise RasterError(f"unknown encoding {encoding!r}")
    values.setflags(write=False)
    return values


def check_candidate(spec: RasterSpec, output: Any) -> Raster:
    """A candidate's output must already be the declared integer raster: nothing is converted."""
    dtype = DTYPES[spec.format]
    if not isinstance(output, np.ndarray):
        raise RasterError(f"candidate returned {type(output).__name__}, not an array")
    if output.dtype.kind != "u" or output.dtype.itemsize != dtype.itemsize:
        raise RasterError(f"candidate output is {output.dtype}, {spec.format} needs {dtype}")
    if output.shape != spec.shape:
        raise RasterError(f"candidate output has shape {output.shape}, needs {spec.shape}")
    if int(output.max(initial=0)) > FORMATS[spec.format]:
        raise RasterError("candidate output exceeds the format's range")
    checked: Raster = np.ascontiguousarray(output, dtype)
    return checked


def raster_sha256(values: Raster) -> str:
    """SHA-256 of the little-endian, row-major samples (the `raw` encoding)."""
    return hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()


@dataclass(frozen=True)
class Residual:
    histogram: tuple[tuple[int, int], ...]  # (|Δ|, number of values), |Δ| ascending
    affected_texels: int
    texels: int

    @property
    def values(self) -> int:
        return sum(count for _, count in self.histogram)

    @property
    def total(self) -> int:
        return sum(delta * count for delta, count in self.histogram)

    @property
    def exact(self) -> bool:
        return self.total == 0

    def p99(self) -> int:
        """Nearest-rank 99th percentile of |Δ| (as `tools.parity.verdict.diagnose`)."""
        rank, seen = math.ceil(0.99 * self.values), 0
        for delta, count in self.histogram:
            seen += count
            if seen >= rank:
                return delta
        raise ValueError("empty residual")

    def as_json(self) -> dict[str, Any]:
        return {
            "max_abs_diff": self.histogram[-1][0],
            "sum_abs_diff": self.total,
            "mean_abs_diff": self.total / self.values,
            "p99_abs_diff": self.p99(),
            "differing_values": sum(count for delta, count in self.histogram if delta),
            "values": self.values,
            "affected_texels": self.affected_texels,
            "texels": self.texels,
        }


def residual(oracle: Raster, candidate: Raster) -> Residual:
    if oracle.shape != candidate.shape:
        raise RasterError(f"shape {candidate.shape} differs from the oracle's {oracle.shape}")
    delta = np.abs(oracle.astype(np.int64) - candidate.astype(np.int64))
    deltas, counts = np.unique(delta, return_counts=True)
    per_texel = delta.reshape(oracle.shape[0] * oracle.shape[1], -1)
    return Residual(
        tuple((int(d), int(c)) for d, c in zip(deltas, counts, strict=True)),
        int(np.count_nonzero(per_texel.any(axis=1))),
        int(per_texel.shape[0]),
    )


def pooled(residuals: Iterable[Residual]) -> Residual:
    histogram: Counter[int] = Counter()
    affected = texels = 0
    for one in residuals:
        histogram.update(dict(one.histogram))
        affected += one.affected_texels
        texels += one.texels
    return Residual(tuple(sorted(histogram.items())), affected, texels)
