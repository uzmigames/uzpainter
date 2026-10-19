"""The diagnostic measure export's combined virtual normal on UV islands
(`src/export/virtual_maps.h`, `VirtualMapRequest::islandNormal`; decisions 263, 276, 285, 287,
288 and 308), on the CPU through `uzp-export-tests export-diagnostic`: the sphere, whose UV
islands leave texels uncovered, with a Height ramp, an empty Normal channel and, in one variant,
a bound 16-bit Normal mesh map, exporting `Normal_OpenGL` and Height as OpenEXR 32f with
`infinite` padding.

Each rule is checked against an independent model: the height-to-normal pass is
`tools/parity/fit/normal.py` (the evaluator's float32 steps), the padding is
`tests/export/padding_reference.py`. The bitmap Height is stored on the half grid at opacity 1, so
its read-out equals its stored value and the exported Height gives the stencil's covered taps. This
mode is not conformant (decision 286); none of this is Painter's output, and the production refusals
are tested unchanged in `test_export_encoders.py`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.export import padding_reference
from tests.export.test_export_encoders import SPHERE, TEMPLATES, chan, export, run, spec
from tools.parity.feasibility import png
from tools.parity.fit import normal as model
from tools.parity.fit.decode import decode

F32 = np.float32
SIZE = 256
EXR32 = {"fileFormat": "exr", "bitDepth": "32f", "dithering": False, "paddingAlgorithm": "infinite"}


def mesh_map(path: Path) -> str:
    """A smooth 16-bit RGB OpenGL normal field at 256 px; returns its SHA-256."""
    y, x = np.mgrid[0:SIZE, 0:SIZE].astype(np.float64)
    sx = 0.35 * np.sin(2 * np.pi * x / SIZE)
    sy = 0.30 * np.cos(2 * np.pi * y / (SIZE / 2))
    n = np.stack([sx, sy, np.ones_like(sx)], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    codes = np.rint((n * 0.5 + 0.5) * 65535).astype(np.int64)
    data = png.encode(codes, 16)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def project(tmp: Path, with_mesh: bool) -> Path:
    path = spec(tmp, SPHERE, "uzp_sphere", height=True)
    if with_mesh:
        document = json.loads(path.read_text(encoding="utf-8"))
        sha = mesh_map(tmp / "mesh-normal.png")
        document["resources"].append({"sha256": sha, "png": "mesh-normal.png"})
        document["mesh_maps"] = {"Normal": sha}
        path.write_text(json.dumps(document), encoding="utf-8")
    return path


def configuration(out: Path, padding: str = "infinite") -> dict[str, Any]:
    maps = [
        {
            "fileName": "$textureSet_n",
            "channels": [chan(c, "virtualMap", "Normal_OpenGL") for c in "RGB"],
        },
        {"fileName": "$textureSet_h", "channels": [chan("L", "documentMap", "height")]},
    ]
    return {
        "exportShaderParams": False,
        "exportPath": out.as_posix(),
        "defaultExportPreset": "p",
        "exportPresets": [{"name": "p", "maps": maps}],
        "exportList": [{"rootPath": "uzp_sphere"}],
        "exportParameters": [{"parameters": EXR32 | {"paddingAlgorithm": padding}}],
    }


def values(path: Path) -> np.ndarray:
    return np.asarray(decode(path.read_bytes()).values, F32).reshape(SIZE, SIZE, -1)


def encoded(n: model.Vec) -> np.ndarray:
    half = F32(0.5)
    return np.stack([model.fma(c, half, half) for c in n], axis=-1)


def combined(height: np.ndarray, mesh: np.ndarray | None) -> np.ndarray:
    """The evaluator's encoded Normal_OpenGL of a float32 Height (Sharp, wrap-around) with the empty
    Normal channel and the mesh map's operands `mesh` (flat when None)."""
    h = np.asarray(height, F32)
    first: model.Vec = (np.zeros_like(h), np.zeros_like(h), np.ones_like(h))
    if mesh is not None:
        first = model.decode((mesh[..., 0], mesh[..., 1], mesh[..., 2]))
    base = model.normalise(
        model.reoriented(first, model.normalise(model.height_vector(h, "Sharp", SIZE)))
    )
    flat = model.decode((np.full_like(h, F32(0.5)), np.full_like(h, F32(0.5)), np.ones_like(h)))
    return encoded(model.normalise(model.reoriented(base, flat)))


def mesh_on_padded(mesh: np.ndarray, free: np.ndarray) -> np.ndarray:
    """virtual_maps.h step 4: normalise(reoriented(decode(F), decode(M))), encoded in OpenGL."""
    f = model.decode((mesh[..., 0], mesh[..., 1], mesh[..., 2]))
    m = model.decode((free[..., 0], free[..., 1], free[..., 2]))
    return encoded(model.normalise(model.reoriented(f, m)))


def bits(a: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(a, F32).view(np.uint32)


@pytest.fixture(scope="module")
def sphere(export_tests: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Both variants exported once, with the coverage, ring and models they are checked against."""
    tmp = tmp_path_factory.mktemp("island-normal")
    out: dict[str, Any] = {}
    for label, with_mesh in (("free", False), ("mesh", True)):
        path = project(tmp / label, with_mesh)
        target = tmp / f"out-{label}"
        (tmp / f"config-{label}.json").write_text(
            json.dumps(configuration(target)), encoding="utf-8"
        )
        [result] = run(
            export_tests,
            "export-diagnostic",
            str(TEMPLATES),
            str(path),
            str(tmp / f"config-{label}.json"),
        )
        assert "error" not in result, result
        written = {f["relativePath"]: f for f in result["written"]}
        out[label] = {
            "normal": values(target / "uzp_sphere_n.exr"),
            "height": values(target / "uzp_sphere_h.exr")[..., 0],
            "written": written,
        }
    # The whole-tile Height, as production evaluates it (passthrough keeps every texel).
    whole = tmp / "out-passthrough"
    cfg = configuration(whole, "passthrough")
    cfg["exportPresets"][0]["maps"] = cfg["exportPresets"][0]["maps"][1:]
    result = export(export_tests, project(tmp / "passthrough", False), cfg, tmp / "run-passthrough")
    assert "error" not in result, result
    out["tile_height"] = values(whole / "uzp_sphere_h.exr")[..., 0]
    ring = padding_reference.Ring(SPHERE, "uzp_sphere", SIZE, SIZE)
    covered = ring.owner >= 0
    neighbours = np.zeros_like(covered)
    for dy, dx in padding_reference.NEIGHBOURS:
        shifted = np.roll(covered, -dx, axis=1)  # x wraps
        if dy > 0:
            shifted = np.vstack([shifted[dy:], np.zeros((dy, SIZE), bool)])
        elif dy < 0:
            shifted = np.vstack([np.zeros((-dy, SIZE), bool), shifted[:dy]])
        neighbours |= shifted
    out["covered"] = covered
    out["ring"] = ~covered & neighbours
    out["gutter"] = ~covered & ~neighbours
    out["edge"] = covered & ~np.all(
        [np.roll(np.roll(covered, -dy, 0), -dx, 1) for dy, dx in padding_reference.NEIGHBOURS],
        axis=0,
    )
    # The Height the stencil reads: the covered read-out, the ring's raw chain and the flood.
    padded = padding_reference.padding(
        out["free"]["height"][..., None], SPHERE, "uzp_sphere", rounded=False
    )
    out["padded_height"] = np.where(covered, out["free"]["height"], padded[..., 0])
    data = (tmp / "mesh" / "mesh-normal.png").read_bytes()
    out["mesh_operands"] = (png.decode(data).astype(np.float64) / 65535.0).astype(F32)
    return out


def test_covered_edge_texels_read_the_padded_height(sphere: dict[str, Any]) -> None:
    """Decisions 263 and 288 (a): every covered texel is the stencil of the Height read-out on the
    covered texels and, outside them, of the measured ring without its 1 - (1 - m) step and the
    flood, bit for bit, with and without the mesh map; the whole-tile Height gives the same interior
    but other island-edge texels. The two production refusals are recorded as bypassed."""
    covered, edge = sphere["covered"], sphere["edge"]
    for label, mesh in (("free", None), ("mesh", sphere["mesh_operands"])):
        expected = combined(sphere["padded_height"], mesh)
        got = sphere[label]["normal"]
        assert np.array_equal(bits(got[covered]), bits(expected[covered])), label
        whole = combined(sphere["tile_height"], mesh)
        differs = np.any(bits(got) != bits(whole), axis=-1)
        assert not np.any(differs & covered & ~edge), label
        assert np.any(differs & edge), label
        refusals = sphere[label]["written"]["uzp_sphere_n.exr"]["bypassed"]
        assert (
            len(refusals) == 2 and "decision 245" in refusals[0] and "decision 259" in refusals[1]
        ), refusals


def test_ring_texels_copy_the_nearest_covered_mesh_free_normal(sphere: dict[str, Any]) -> None:
    """Decision 287: without a mesh map, each ring texel is a bit-exact copy of its nearest covered
    8-neighbour without wrap-around (ties in decision 197's offset order); one whose covered
    neighbours all lie across the x border keeps the flat height normal combined with the Normal
    channel there. No texel is undecided."""
    covered, ring = sphere["covered"], sphere["ring"]
    got = sphere["free"]["normal"]
    flat = combined(np.zeros((SIZE, SIZE), F32), None)
    unpadded = np.where(covered[..., None], got, flat)
    expected = padding_reference.island_normal(unpadded, covered)
    assert np.array_equal(bits(got[ring]), bits(expected[ring]))
    # The sphere has both kinds: ring texels at the tile's x border keep their own value.
    across = np.array(
        [(y, x) for y, x in zip(*np.nonzero(ring), strict=True) if x in (0, SIZE - 1)]
    )
    assert len(across) > 0
    kept = np.all(bits(got[ring]) == bits(flat[ring]), axis=-1)
    assert 0 < int(kept.sum()) < int(ring.sum())
    assert sphere["free"]["written"]["uzp_sphere_n.exr"]["undecided"] == 0


def test_gutter_floods_the_padded_normal_under_the_mesh_map(sphere: dict[str, Any]) -> None:
    """Decisions 197, 276 and 285: without a mesh map every gutter texel is its clamped-flood seed's
    padded normal; with one, every uncovered texel is the mesh map at that texel combined with the
    same padded mesh-free normal (the best-known form of decision 276 items 4 (b), (c), decision
    308), and each is counted as undecided. The Height keeps the export's own padding."""
    covered, gutter = sphere["covered"], sphere["gutter"]
    free = sphere["free"]["normal"]
    flat = combined(np.zeros((SIZE, SIZE), F32), None)
    expected = padding_reference.island_normal(np.where(covered[..., None], free, flat), covered)
    assert np.array_equal(bits(free[gutter]), bits(expected[gutter]))
    with_mesh = sphere["mesh"]["normal"]
    combination = mesh_on_padded(sphere["mesh_operands"], free)
    assert np.array_equal(bits(with_mesh[~covered]), bits(combination[~covered]))
    assert sphere["mesh"]["written"]["uzp_sphere_n.exr"]["undecided"] == int((~covered).sum())
    assert sphere["mesh"]["written"]["uzp_sphere_h.exr"]["undecided"] == 0
    # Stored as the L16F channel stores it (decision 274): the half toward zero.
    height = model.half_toward_zero(
        padding_reference.padding(sphere["free"]["height"][..., None], SPHERE, "uzp_sphere")[..., 0]
    )
    assert np.array_equal(bits(sphere["mesh"]["height"]), bits(height))
