"""The island-edge coverage near-tie (decision 401): a candidate vertex rule, scored on the CPU
against decision 281's coverage on every recorded mesh (`phase3.1_export-island-padding`).

Decision 281's coverage (`tools/parity/coverage.py`, `src/evaluator/geometry_mask.cpp`) rounds each
vertex's texel-space UV, computed exactly in double as (u W, (1 - v) H), to the nearest 1/256
texel. On the Tunic at 4096 px three covered island-edge texels are padding in Painter's export
(decision 401). The candidate here, `ndc_coverage`, computes each vertex as a float32 rasteriser
would with v up: each coordinate t goes to normalised device coordinates and back,
p = ((2 t - 1) + 1) * N / 2, every operation rounded to float32; then p is rounded to the nearest
1/256 texel (ties to even) and the rows are flipped (y = H - p_v). The edge test is decision 281's.

Below 2^-1 the float32 sum 2 t - 1 is not exact, so p can differ from t N by up to half a float32
ulp of the device coordinate, and a vertex near a 1/256 rounding tie can land on the other grid
point. Everything else equals decision 281's rule.

    python -m tools.parity.fit.padding_coverage

prints, per recorded mesh, material and size, the texels each rule covers that the other does not.
Counts only: coordinates of the private Assets3D meshes stay off the repository.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

import numpy as np
import numpy.typing as npt

from tools.parity.coverage import SUB_TEXEL, Mask, Triangles, coverage, obj_materials, obj_triangles
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import locate

F32 = np.float32


def ndc_vertex(t: npt.ArrayLike, size: int) -> npt.NDArray[np.float64]:
    """((2 t - 1) + 1) * size / 2 of float32 coordinates `t`, each operation rounded to float32
    (size / 2 is a power of two for every recorded size, so the product is exact)."""
    v = np.asarray(t, dtype=F32)
    device = F32(2) * v - F32(1)
    result: npt.NDArray[np.float64] = ((device + F32(1)) * F32(size / 2)).astype(np.float64)
    return result


def _cross(
    a: npt.NDArray[np.float64], b: npt.NDArray[np.float64], px: object, py: object
) -> npt.NDArray[np.float64]:
    result: npt.NDArray[np.float64] = (b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])
    return result


def snapped(triangles: Triangles, width: int, height: int) -> npt.NDArray[np.float64]:
    """(n, 3, 2) texel-space vertices, rows top first, under the candidate rule."""
    out = np.empty(triangles.shape, dtype=np.float64)
    out[..., 0] = np.round(ndc_vertex(triangles[..., 0], width) * SUB_TEXEL) / SUB_TEXEL
    out[..., 1] = height - np.round(ndc_vertex(triangles[..., 1], height) * SUB_TEXEL) / SUB_TEXEL
    return out


def ndc_coverage(triangles: Triangles, width: int, height: int) -> Mask:
    """The covered texels (rows top first) of `triangles` under the candidate vertex rule, with
    decision 281's edge test (inside or on an edge; degenerate triangles cover nothing)."""
    covered = np.zeros((height, width), dtype=bool)
    for p in snapped(triangles, width, height):
        area = float(_cross(p[0], p[1], p[2][0], p[2][1]))
        if area == 0.0:
            continue
        col_lo = max(0.0, np.floor(p[:, 0].min() - 0.5))
        col_hi = min(width - 1.0, np.ceil(p[:, 0].max() - 0.5))
        row_lo = max(0.0, np.floor(p[:, 1].min() - 0.5))
        row_hi = min(height - 1.0, np.ceil(p[:, 1].max() - 0.5))
        if col_lo > col_hi or row_lo > row_hi:
            continue
        px = (np.arange(int(col_lo), int(col_hi) + 1, dtype=np.float64) + 0.5)[None, :]
        py = (np.arange(int(row_lo), int(row_hi) + 1, dtype=np.float64) + 0.5)[:, None]
        w = [_cross(p[i], p[(i + 1) % 3], px, py) for i in range(3)]
        if area > 0.0:
            inside = (w[0] >= 0.0) & (w[1] >= 0.0) & (w[2] >= 0.0)
        else:
            inside = (w[0] <= 0.0) & (w[1] <= 0.0) & (w[2] <= 0.0)
        covered[int(row_lo) : int(row_hi) + 1, int(col_lo) : int(col_hi) + 1] |= inside
    return covered


def compare(triangles: Triangles, width: int, height: int) -> tuple[int, int]:
    """(texels decision 281 covers and the candidate does not, the reverse)."""
    a = coverage(triangles, width, height)
    b = ndc_coverage(triangles, width, height)
    return int((a & ~b).sum()), int((~a & b).sum())


# ── Every recorded mesh ────────────────────────────────────────────────────────────────────────


def recorded_meshes() -> Iterator[tuple[str, Path, list[int]]]:
    """(golden, OBJ path, sizes) of every manifest of the current envelope with a mesh input: the
    tier0 semantics padding and height-normal goldens at their kernel or project size, and the
    Tier 1 pilots at 1024, 2048 and 4096 (their meshes from the private store)."""
    root = manifest_root(current_envelope())
    store = locate()
    semantics = sorted((root / "tier0" / "semantics").glob("export-padding*.json"))
    semantics += sorted((root / "tier0" / "semantics").glob("height-normal-*.json"))
    semantics += sorted((root / "tier0" / "assets3d").glob("export-padding*.json"))
    pilots = sorted(root.glob("phase*/tier1/*.json"))
    for path in semantics + pilots:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        inputs = manifest["inputs"]
        meshes = [r for r in inputs if r["kind"] == "mesh" and "mtl" not in r["input_id"]]
        if not meshes:
            continue
        row = meshes[0]
        if "path" in row:
            mesh = REPO_ROOT / row["path"]
        elif store is not None:
            mesh = store.blob_path(row["sha256"])
        else:
            continue
        if path in pilots:
            sizes = [1024, 2048, 4096]
        else:
            sizes = sorted(
                {
                    int(s["args"]["default_texture_resolution"])
                    for s in manifest["instruction_sequence"]["steps"]
                    if s["call"].endswith("project.create")
                }
            )
            kernel = [r for r in inputs if r["input_id"].startswith("kernel-onehot-a-n")]
            if kernel:
                sizes = [int(kernel[0]["input_id"].rsplit("-n", 1)[1])]
        yield str(manifest["golden_id"]), mesh, sizes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.parse_args(argv)
    seen: set[tuple[str, int, str]] = set()
    changed = 0
    for golden, mesh, sizes in recorded_meshes():
        if not mesh.is_file():
            print(f"{golden}: mesh unavailable")
            continue
        for material in obj_materials(mesh):
            triangles = obj_triangles(mesh, material)
            for size in sizes:
                key = (str(mesh), size, material)
                if key in seen:
                    continue
                seen.add(key)
                lost, gained = compare(triangles, size, size)
                changed += lost + gained
                print(f"{golden:<52} {size:>5} {material:<26} only-281 {lost} only-ndc {gained}")
    print(f"texels that differ: {changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
