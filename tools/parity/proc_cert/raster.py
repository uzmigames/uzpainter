"""Decoding pinned rasters and measuring residuals in native code values or in ULPs.

Exact means bit-exact: every channel of every texel equal. The residual of a case is the
histogram of its per-value distances, so per-case and pooled statistics (max, exact sum and mean,
nearest-rank p99, affected texels) are computed without floating error:

- integer formats (`u8`, `u16`): |candidate - oracle| in code values;
- float formats (`f16`, `f32`, decision 305): the ULP distance, the number of representable
  values between the two bit patterns in IEEE 754 total order (-0 and +0 are 1 ULP apart), so a
  distance of 0 is exactly equal bits.

A candidate's output is copied into an owned, read-only array as soon as it is returned, so a
candidate that reuses one buffer for several cases cannot change an output already returned.
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
from tools.parity.proc_cert.batch import FLOAT_FORMATS, INTEGER_FORMATS, RasterSpec

Raster = (
    npt.NDArray[np.uint8]
    | npt.NDArray[np.uint16]
    | npt.NDArray[np.float16]
    | npt.NDArray[np.float32]
)
DTYPES: dict[str, np.dtype[Any]] = {
    "u8": np.dtype("<u1"),
    "u16": np.dtype("<u2"),
    "f16": np.dtype("<f2"),
    "f32": np.dtype("<f4"),
}
# The residual unit of each format: integer code values, or ULPs of the float format.
UNITS = {"u8": "code_u8", "u16": "code_u16", "f16": "ulp_f16", "f32": "ulp_f32"}
_BITS: dict[str, np.dtype[Any]] = {"f16": np.dtype("<u2"), "f32": np.dtype("<u4")}


class RasterError(Exception):
    """Bytes or an array that are not a raster of the declared spec."""


class DecoderMissing(RasterError):
    """This machine has no decoder for the blob's encoding (OpenEXR's binding)."""


def _decode_exr(spec: RasterSpec, data: bytes) -> Raster:
    """Decision 305: `tools.parity.fit.decode.decode_exr` widens the stored samples exactly to
    float64; narrowing back to the declared type restores the stored bits, and narrowing that
    loses a value (a channel stored at another precision) is refused."""
    try:
        from tools.parity.fit.decode import decode_exr

        decoded = decode_exr(data)
    except ImportError as error:
        raise DecoderMissing(f"OpenEXR's Python binding is not installed: {error}") from error
    except Exception as error:  # the binding raises its own types for a damaged file
        raise RasterError(f"EXR does not decode: {type(error).__name__}: {error}") from error
    bits = 16 if spec.format == "f16" else 32
    if decoded.bits != bits:
        raise RasterError(f"EXR has {decoded.bits}-bit samples, {spec.format} needs {bits}")
    with np.errstate(over="ignore", invalid="ignore"):  # a lossy narrowing is refused below
        narrowed = decoded.values.astype(DTYPES[spec.format])
    widened = narrowed.astype(np.float64)
    if not np.array_equal(widened.view(np.uint64), decoded.values.view(np.uint64)):
        raise RasterError(f"EXR holds samples that are not {spec.format} values")
    if narrowed.shape != spec.shape:
        raise RasterError(f"EXR has shape {narrowed.shape}, {spec} needs {spec.shape}")
    values: Raster = np.ascontiguousarray(narrowed)
    return values


def decode(spec: RasterSpec, encoding: str, data: bytes) -> Raster:
    """The (h, w, c) samples of a pinned blob, read-only."""
    dtype = DTYPES[spec.format]
    if encoding == "raw":
        expected = math.prod(spec.shape) * dtype.itemsize
        if len(data) != expected:
            raise RasterError(f"raw raster has {len(data)} bytes, {spec} needs {expected}")
        values: Raster = np.frombuffer(data, dtype).reshape(spec.shape)
    elif encoding == "png" and spec.format in INTEGER_FORMATS:
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
    elif encoding == "exr" and spec.format in FLOAT_FORMATS:
        values = _decode_exr(spec, data)
    else:
        raise RasterError(f"a {encoding!r} blob cannot hold {spec.format} samples")
    values.setflags(write=False)
    return values


def check_candidate(spec: RasterSpec, output: Any) -> Raster:
    """A candidate's output must already be the declared raster: nothing is converted. The
    result is an owned, read-only copy, never a view of the candidate's buffer."""
    dtype = DTYPES[spec.format]
    if not isinstance(output, np.ndarray):
        raise RasterError(f"candidate returned {type(output).__name__}, not an array")
    if output.dtype.kind != dtype.kind or output.dtype.itemsize != dtype.itemsize:
        raise RasterError(f"candidate output is {output.dtype}, {spec.format} needs {dtype}")
    if output.shape != spec.shape:
        raise RasterError(f"candidate output has shape {output.shape}, needs {spec.shape}")
    snapshot: Raster = np.array(output, dtype=dtype, order="C", copy=True)
    if (
        spec.format in INTEGER_FORMATS
        and int(snapshot.max(initial=0)) > INTEGER_FORMATS[spec.format]
    ):
        raise RasterError("candidate output exceeds the format's range")
    snapshot.setflags(write=False)
    return snapshot


def raster_sha256(values: Raster) -> str:
    """SHA-256 of the little-endian, row-major samples (the `raw` encoding)."""
    return hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()


@dataclass(frozen=True)
class Residual:
    unit: str  # UNITS: code values of an integer format, or ULPs of a float format
    histogram: tuple[tuple[int, int], ...]  # (distance, number of values), distance ascending
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
        """Nearest-rank 99th percentile of the distance (as `tools.parity.verdict.diagnose`)."""
        rank, seen = math.ceil(0.99 * self.values), 0
        for delta, count in self.histogram:
            seen += count
            if seen >= rank:
                return delta
        raise ValueError("empty residual")

    def statistics(self) -> dict[str, Any]:
        return {
            "max_abs_diff": self.histogram[-1][0],
            "mean_abs_diff": self.total / self.values,
            "p99_abs_diff": self.p99(),
        }

    def as_json(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            **self.statistics(),
            "sum_abs_diff": self.total,
            "differing_values": sum(count for delta, count in self.histogram if delta),
            "values": self.values,
            "affected_texels": self.affected_texels,
            "texels": self.texels,
        }


def _total_order(values: Raster, fmt: str) -> npt.NDArray[np.int64]:
    """Each float's position in IEEE 754 total order: adjacent bit patterns are 1 apart."""
    bits = values.view(_BITS[fmt]).astype(np.int64)
    sign = 1 << (8 * values.dtype.itemsize - 1)
    magnitude = bits & (sign - 1)
    ordered: npt.NDArray[np.int64] = np.where(bits & sign, -magnitude - 1, magnitude)
    return ordered


def residual(oracle: Raster, candidate: Raster, fmt: str) -> Residual:
    if oracle.shape != candidate.shape:
        raise RasterError(f"shape {candidate.shape} differs from the oracle's {oracle.shape}")
    if oracle.dtype != DTYPES[fmt] or candidate.dtype != DTYPES[fmt]:
        raise RasterError(f"{fmt} residual of {oracle.dtype} and {candidate.dtype} samples")
    if fmt in FLOAT_FORMATS:
        delta = np.abs(_total_order(oracle, fmt) - _total_order(candidate, fmt))
    else:
        delta = np.abs(oracle.astype(np.int64) - candidate.astype(np.int64))
    deltas, counts = np.unique(delta, return_counts=True)
    per_texel = delta.reshape(oracle.shape[0] * oracle.shape[1], -1)
    return Residual(
        UNITS[fmt],
        tuple((int(d), int(c)) for d, c in zip(deltas, counts, strict=True)),
        int(np.count_nonzero(per_texel.any(axis=1))),
        int(per_texel.shape[0]),
    )


def pooled(residuals: Iterable[Residual]) -> dict[str, Residual]:
    """The residuals pooled per unit: code values and ULPs of different formats never mix."""
    histograms: dict[str, Counter[int]] = {}
    texels: dict[str, list[int]] = {}
    for one in residuals:
        histograms.setdefault(one.unit, Counter()).update(dict(one.histogram))
        counts = texels.setdefault(one.unit, [0, 0])
        counts[0] += one.affected_texels
        counts[1] += one.texels
    return {
        unit: Residual(unit, tuple(sorted(histogram.items())), *texels[unit])
        for unit, histogram in sorted(histograms.items())
    }
