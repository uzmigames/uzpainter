"""Texel-centre UV coverage of an OBJ material, as the export pads it (decision 223).

The convention of `src/evaluator/geometry_mask.h` and the OBJ reading of `src/mesh/obj_parser.cpp`:

- `vt` values are read as doubles and stored as float32; faces with more than three corners are
  fanned from their last corner, (c[i], c[i+1], c[n-1]); faces before any `usemtl` belong to the
  material `default`;
- row 0 is the top of UV tile 1001 (v = 1); texel (col, row) has its centre at
  u = (col + 1/2) / W, v = 1 - (row + 1/2) / H. Each vertex coordinate t goes through float32
  device coordinates, p = ((2 t - 1) + 1) N / 2 (each operation rounded to float32), is rounded to
  the nearest 1/256 texel, ties to even (decision 281), and the rows are flipped, y = H - p_v
  (decision 408). A texel is covered when its centre lies strictly inside a triangle of the
  material that is not degenerate after that rounding, or on an edge that the top-left rule keeps:
  with the triangle wound to a positive area (rows top first), an edge with dy < 0, or horizontal
  with dx < 0 (decision 408).

The coverage separates the texels inside the UV islands from the padding texels, which the Tier 1
report publishes apart (exception EXC-007 excepted them until the owner withdrew it, decision
259; `tools/parity/verdict.py`). It equals the export's own coverage
(`tests/export/test_export_encoders.py`) and Painter's on the position-encoded padding probes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

F32 = np.float32

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


SUB_TEXEL = 256  # the coverage's vertex precision, in texels (decision 281)


def ndc_vertex(t: npt.ArrayLike, size: int) -> npt.NDArray[np.float64]:
    """((2 t - 1) + 1) * size / 2 of float32 coordinates `t`, each operation rounded to float32
    (decision 408)."""
    v = np.asarray(t, dtype=F32)
    device = F32(2) * v - F32(1)
    result: npt.NDArray[np.float64] = ((device + F32(1)) * F32(size / 2)).astype(np.float64)
    return result


def snapped(triangles: Triangles, width: int, height: int) -> npt.NDArray[np.float64]:
    """(n, 3, 2) texel-space vertices, rows top first: the float32 device round trip, the 1/256
    texel rounding (ties to even), then the row flip (decision 408)."""
    out = np.empty(triangles.shape, dtype=np.float64)
    out[..., 0] = np.round(ndc_vertex(triangles[..., 0], width) * SUB_TEXEL) / SUB_TEXEL
    out[..., 1] = height - np.round(ndc_vertex(triangles[..., 1], height) * SUB_TEXEL) / SUB_TEXEL
    return out


def coverage(triangles: Triangles, width: int, height: int) -> Mask:
    """The covered texels (rows top first) of `triangles` at `width` x `height`."""
    covered = np.zeros((height, width), dtype=bool)
    for p in snapped(triangles, width, height):
        area = float(_cross(p[0], p[1], p[2][0], p[2][1]))
        if area == 0.0:
            continue
        if area < 0.0:
            p = p[[0, 2, 1]]
        col_lo = max(0.0, np.floor(p[:, 0].min() - 0.5))
        col_hi = min(width - 1.0, np.ceil(p[:, 0].max() - 0.5))
        row_lo = max(0.0, np.floor(p[:, 1].min() - 0.5))
        row_hi = min(height - 1.0, np.ceil(p[:, 1].max() - 0.5))
        if col_lo > col_hi or row_lo > row_hi:
            continue
        px = (np.arange(int(col_lo), int(col_hi) + 1, dtype=np.float64) + 0.5)[None, :]
        py = (np.arange(int(row_lo), int(row_hi) + 1, dtype=np.float64) + 0.5)[:, None]
        inside = np.ones((py.shape[0], px.shape[1]), dtype=bool)
        for i in range(3):
            a, b = p[i], p[(i + 1) % 3]
            dx, dy = b[0] - a[0], b[1] - a[1]
            tie = bool(dy < 0.0 or (dy == 0.0 and dx < 0.0))
            w = _cross(a, b, px, py)
            inside &= (w > 0.0) | ((w == 0.0) & tie)
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
