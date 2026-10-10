"""Comparison at native depth (`parity/CONTRACT.md` §3.1, §8.1) for the feasibility study.

Values are compared as stored 16-bit code values. The comparison domain is the texels the
fixture's UV triangles cover (centre inside a triangle), eroded by one texel; texels outside it
are export padding (`padding: passthrough` leaves them undefined), never generator output. The
covered and padding texel counts are reported with every result.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from functools import cache
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.feasibility import png
from tools.parity.feasibility.cases import Case
from tools.parity.feasibility.fixtures import FIXTURES, RESOLUTION, Mesh
from tools.parity.schemas import load_json
from tools.parity.store.store import OracleStore, load_oracle

Mask = npt.NDArray[np.bool_]
Codes = npt.NDArray[np.int64]


@dataclass(frozen=True)
class Difference:
    """|Δ| statistics over one domain, in native code values (CONTRACT §8.1)."""

    max: int
    mean: float
    p99: int
    differing: int  # differing values (every channel of every texel)
    total: int
    affected_texels: int  # texels with at least one differing channel
    texels: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def difference(a: Codes, b: Codes, domain: Mask) -> Difference:
    """max, mean and nearest-rank p99 of |a - b| over every channel of the domain's texels."""
    if a.shape != b.shape:
        raise ValueError(f"shape {a.shape} differs from {b.shape}")
    per_texel = np.abs(a.astype(np.int64) - b.astype(np.int64))[domain]
    delta = per_texel.ravel()
    if delta.size == 0:
        raise ValueError("empty comparison domain")
    ordered = np.sort(delta)
    rank = math.ceil(0.99 * ordered.size)
    return Difference(
        int(ordered[-1]),
        float(delta.mean()),
        int(ordered[rank - 1]),
        int(np.count_nonzero(delta)),
        int(delta.size),
        int(np.count_nonzero(per_texel.reshape(per_texel.shape[0], -1).any(axis=1))),
        int(per_texel.shape[0]),
    )


def rasterise_uv(mesh: Mesh, resolution: int = RESOLUTION) -> Mask:
    """Texels whose centre lies inside (or on the edge of) a UV triangle; row 0 is v = 1."""
    covered = np.zeros((resolution, resolution), np.bool_)
    uv = mesh.uvs * resolution
    for a, b, c in uv[mesh.triangles]:
        low = np.floor(np.minimum(np.minimum(a, b), c) - 0.5).astype(int)
        high = np.ceil(np.maximum(np.maximum(a, b), c) + 0.5).astype(int)
        x0, y0 = max(low[0], 0), max(low[1], 0)
        x1, y1 = min(high[0], resolution), min(high[1], resolution)
        if x0 >= x1 or y0 >= y1:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(denominator) < 1e-12:
            continue
        w0 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / denominator
        w1 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / denominator
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (1.0 - w0 - w1 >= -1e-9)
        rows = resolution - 1 - np.arange(y0, y1)
        covered[rows[:, None], np.arange(x0, x1)[None, :]] |= inside
    return covered


def erode(mask: Mask) -> Mask:
    """Texels whose 3 x 3 neighbourhood is entirely in the mask (edges of the image excluded)."""
    padded = np.pad(mask, 1, constant_values=False)
    result = np.ones_like(mask)
    height, width = mask.shape
    for dy in range(3):
        for dx in range(3):
            result &= padded[dy : dy + height, dx : dx + width]
    return result


@cache
def comparison_domain(fixture: str) -> Mask:
    build_mesh, _ = FIXTURES[fixture]
    domain: Mask = erode(rasterise_uv(build_mesh()))
    return domain


@dataclass(frozen=True)
class OracleMaps:
    """The exported maps of every admitted recording of one golden, as decoded code values."""

    recordings: dict[str, dict[str, Codes]]  # recording id -> map name -> (h, w, c)


def oracle_maps(store: OracleStore | None, case: Case) -> OracleMaps | None:
    """Decode a golden's recorded maps from the private store; None when any blob is missing."""
    manifest = load_json(case.manifest_path)
    refs = {ref["record_id"]: ref for ref in manifest["private_records"]}
    if "golden-record" not in refs:
        return None
    record_bytes = load_oracle(store, refs["golden-record"])
    if record_bytes is None:
        return None
    record = json.loads(record_bytes.decode("utf-8"))
    recordings: dict[str, dict[str, Codes]] = {}
    for recording in record["recordings"]:
        maps: dict[str, Codes] = {}
        for output in recording["outputs"]:
            if output["kind"] != "exported_map":
                continue
            blob = load_oracle(
                store,
                {"sha256": output["blob"]["sha256"], "size_bytes": output["blob"]["size_bytes"]},
            )
            if blob is None:
                return None
            maps[str(output["map"])] = png.decode(blob).astype(np.int64)
        recordings[str(recording["recording_id"])] = maps
    return OracleMaps(recordings)
