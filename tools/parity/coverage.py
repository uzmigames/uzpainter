"""Texel-centre UV coverage of an OBJ material, as the export pads it (decision 223).

The convention of `src/evaluator/geometry_mask.h` and the OBJ reading of `src/mesh/obj_parser.cpp`:

- `vt` values are read as doubles and stored as float32; faces with more than three corners are
  fanned from their last corner, (c[i], c[i+1], c[n-1]); faces before any `usemtl` belong to the
  material `default`;
- row 0 is the top of UV tile 1001 (v = 1); texel (col, row) has its centre at
  u = (col + 1/2) / W, v = 1 - (row + 1/2) / H, and is covered when that centre lies inside or on
  the boundary of a non-degenerate triangle of the material.

The coverage separates the texels compared exactly from the padding texels exception EXC-007
excepts (`tools/parity/verdict.py`). It equals the export's own coverage
(`tests/export/test_export_encoders.py`) and Painter's on the position-encoded padding probes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

Triangles = npt.NDArray[np.float64]  # (n, 3, 2): the float32 UVs of each triangle, widened
Mask = npt.NDArray[np.bool_]
DEFAULT_MATERIAL = "default"


def obj_materials(path: Path) -> list[str]:
    """The materials of the OBJ file at `path` that hold faces, in file order."""
    found: list[str] = []
    current = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        keyword, _, rest = line.partition(" ")
        if keyword == "usemtl":
            current = rest.strip()
        elif keyword == "f" and (current or DEFAULT_MATERIAL) not in found:
            found.append(current or DEFAULT_MATERIAL)
    return found


def obj_triangles(path: Path, material: str) -> Triangles:
    """The UV triangles of `material` in the OBJ file at `path`."""
    uvs: list[tuple[float, float]] = []
    found: list[tuple[tuple[float, float], ...]] = []
    current = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        keyword, _, rest = line.partition(" ")
        tokens = rest.split()
        if keyword == "vt":
            u = float(np.float32(float(tokens[0])))
            v = float(np.float32(float(tokens[1]))) if len(tokens) > 1 else 0.0
            uvs.append((u, v))
        elif keyword == "usemtl":
            current = rest.strip()
        elif keyword == "f":
            if (current or DEFAULT_MATERIAL) != material:
                continue
            corners = []
            for ref in tokens:
                parts = ref.split("/")
                index = int(parts[1]) if len(parts) > 1 and parts[1] else 0
                if index == 0:
                    corners.append((0.0, 0.0))  # a corner without UV
                    continue
                corners.append(uvs[index - 1 if index > 0 else len(uvs) + index])
            last = corners[-1]
            for i in range(len(corners) - 2):
                found.append((corners[i], corners[i + 1], last))
    return np.array(found, dtype=np.float64).reshape(-1, 3, 2)


def _cross(
    a: npt.NDArray[np.float64], b: npt.NDArray[np.float64], pu: Any, pv: Any
) -> npt.NDArray[np.float64]:
    result: npt.NDArray[np.float64] = (b[0] - a[0]) * (pv - a[1]) - (b[1] - a[1]) * (pu - a[0])
    return result


def coverage(triangles: Triangles, width: int, height: int) -> Mask:
    """The covered texels (rows top first) of `triangles` at `width` x `height`."""
    covered = np.zeros((height, width), dtype=bool)
    for p in triangles:
        area = float(_cross(p[0], p[1], p[2][0], p[2][1]))
        if area == 0.0:
            continue
        col_lo = max(0.0, np.floor(p[:, 0].min() * width - 0.5))
        col_hi = min(width - 1.0, np.ceil(p[:, 0].max() * width - 0.5))
        row_lo = max(0.0, np.floor((1.0 - p[:, 1].max()) * height - 0.5))
        row_hi = min(height - 1.0, np.ceil((1.0 - p[:, 1].min()) * height - 0.5))
        if col_lo > col_hi or row_lo > row_hi:
            continue
        cols = np.arange(int(col_lo), int(col_hi) + 1, dtype=np.float64)
        rows = np.arange(int(row_lo), int(row_hi) + 1, dtype=np.float64)
        pu = ((cols + 0.5) / width)[None, :]
        pv = (1.0 - (rows + 0.5) / height)[:, None]
        w0, w1, w2 = (
            _cross(p[0], p[1], pu, pv),
            _cross(p[1], p[2], pu, pv),
            _cross(p[2], p[0], pu, pv),
        )
        if area > 0.0:
            inside = (w0 >= 0.0) & (w1 >= 0.0) & (w2 >= 0.0)
        else:
            inside = (w0 <= 0.0) & (w1 <= 0.0) & (w2 <= 0.0)
        covered[int(row_lo) : int(row_hi) + 1, int(col_lo) : int(col_hi) + 1] |= inside
    return covered


BANDS = (1, 2, 4, 8)


def distance_bands(covered: Mask, reach: int = BANDS[-1]) -> npt.NDArray[np.int64]:
    """Per texel, the chessboard distance in texels to the nearest covered texel, x wrapping as the
    ring does (padding.h): 0 when covered, `reach + 1` beyond `reach` or when nothing is covered."""
    distance = np.full(covered.shape, reach + 1, dtype=np.int64)
    distance[covered] = 0
    grown = covered.copy()
    for step in range(1, reach + 1):
        rows = grown.copy()
        rows[1:] |= grown[:-1]
        rows[:-1] |= grown[1:]
        nxt = rows | np.roll(rows, 1, axis=1) | np.roll(rows, -1, axis=1)
        distance[nxt & ~grown] = step
        grown = nxt
    return distance
