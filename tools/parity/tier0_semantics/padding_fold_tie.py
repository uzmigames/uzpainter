"""Folded-seam tie probe (phase3.1_export-island-padding item 2.1): seam pairs whose ring texels'
far points lie exactly on a far window boundary along the seam, across a fold, in exact
arithmetic. Authored geometry only; no Painter data or fitted values. The design is the next
probe of `parity/reports/phase1/padding-tie-side-mixed-chain-diagnostic.md` (cycle 1).

**Why.** On the bevelled cube's kernel probe most window-side residuals are along-seam ties across
a fold (the seam vertical in the far triangle J's UV, the tie in v), and no tested float32
arithmetic predicts which side Painter takes. If Painter takes the exact-tie side wherever every
float32 formulation is exact, the cube's flips are arithmetic noise of the fold; otherwise a
geometric side rule exists.

**A copy.** Island A, a SIDE x SIDE texel square in y = 0 over x in [-SIDE, 0] texels, its seam
edge on the z axis; island B beyond the seam, SIDE x SIDE texels, folded convex about the seam
along a Pythagorean direction (a, b) / c (flat and 90 degrees included), its own UV island at
ratio 1 turned by 0, 90, 180 or 270 degrees, so that the seam is vertical (0, 180) or horizontal
(90, 270) in J's UV. One texel is c 2^-k cm (k = round(log2 c)), so every corner and every ring
texel's fold point is dyadic. A's UV box sits ACROSS texel off the grid across the seam, B's is
placed so that the far point of every ring texel along the seam lies exactly on a far texel centre
along the seam (the window boundary of decision 275) and `offset` texel off it across.

**Twins.** Every configuration is copied twice: `dyadic`, at whole-centimetre positions in a mesh
box of exactly [-256, 256] cm in x and z (decision 273's normalisation exact), so that every
position and UV is exact in float32 and the far point is exact in any float32 arithmetic whose
rotation entries are exact (the flat and 90-degree folds), rational otherwise; and `offset`, the
same copy moved by TWIN_DELTA, a non-dyadic translation, so that the written float32 positions
round and the tie is broken by arithmetic noise only.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from tools.parity.tier0_semantics import request_fixtures as rf
from tools.parity.tier0_semantics.corpus import Golden
from tools.parity.tier0_semantics.fixtures import obj

MESH = "padding-fold-tie"
MATERIAL = "uzp_fold_tie"
GOLDEN = f"export-{MESH}"
RESOLUTION = rf.SWEEP_RESOLUTION
SIDE = 4
B_COLUMN = SIDE + 8  # B's UV box starts this many texels right of A's
ACROSS = (0.125, 0.25, 0.375)  # A's UV box offset across the seam (texels)
OFFSETS = (0.25, 0.625, 0.875)  # the far point's offset from a far texel centre across the seam
# J's direction (a, b, c): B at (a, -b) / c from the seam, convex (decision 278's gate is open).
FOLDS: dict[str, tuple[int, int, int]] = {
    "flat": (1, 0, 1),
    "x90": (0, 1, 1),
    "f37": (4, 3, 5),
    "f53": (3, 4, 5),
    "f23": (12, 5, 13),
    "f67": (5, 12, 13),
}
# B's UV frame turned by 90-degree steps: (across, along) unit vectors in (column, row down), each
# with A's orientation (determinant -1), so every triangle keeps A's winding.
TURNS: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {
    0: ((1, 0), (0, -1)),
    90: ((0, -1), (-1, 0)),
    180: ((-1, 0), (0, 1)),
    270: ((0, 1), (1, 0)),
}
TWINS = ("dyadic", "offset")
TWIN_DELTA: rf.Vec3 = (0.1, 0.03, 0.3)  # cm, not dyadic
POSITION_GRID = 2.0**-8  # cm
UV_GRID = 2.0**-8  # texel


def unit(c: int) -> float:
    """cm per texel of a copy folded along (a, b) / c: c 2^-k, k = round(log2 c)."""
    return c / 2.0 ** round(math.log2(c))


def _frac(value: float) -> float:
    return value - math.floor(value)


class TieCopy:
    """One copy: fold `fold`, B's UV `turn`, A's `across` offset, the far `offset`, `twin`. Its
    triangles are in local cm (A in y = 0 over x in [-SIDE, 0] texels, the seam on the z axis
    from (0, 0, 0) to (0, 0, -SIDE)), with layout UVs from the slot's top-left texel."""

    def __init__(self, fold: str, turn: int, across: float, offset: float, twin: str) -> None:
        self.fold, self.turn, self.across, self.offset, self.twin = fold, turn, across, offset, twin
        self.name = f"{fold}-t{turn}-a{across:g}-o{offset:g}-{twin}"
        fa, fb, fc = FOLDS[fold]
        u = unit(fc)
        side = float(SIDE)
        row = 0.125  # A's UV box offset along the seam
        a_pq = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
        a3 = [(u * (p - side), 0.0, -u * q) for p, q in a_pq]
        a_uv = [(across + p, row + side - q) for p, q in a_pq]
        # The far point of a ring texel at (column + 1/2, r + 1/2) beyond A's seam edge: the fold
        # keeps its distance d past the seam and its along-seam coordinate q, so in B's frame it
        # is origin + d across + q along. Its fractional parts, with the origin at 0, are those
        # of q's and d's for any ring texel (d and q move by whole texels).
        e_across, e_along = TURNS[turn]
        d0 = 0.5 - _frac(across + side)
        q0 = row + side - 0.5
        far0 = (d0 * e_across[0] + q0 * e_along[0], d0 * e_across[1] + q0 * e_along[1])
        along_axis = 0 if e_along[0] != 0 else 1
        want = [0.0, 0.0]
        want[along_axis] = 0.5
        want[1 - along_axis] = _frac(0.5 + offset)
        origin_frac = [_frac(want[i] - far0[i]) for i in range(2)]
        corners = [
            (p * e_across[0] + q * e_along[0], p * e_across[1] + q * e_along[1]) for p, q in a_pq
        ]
        low = [min(c[i] for c in corners) for i in range(2)]
        base = (float(B_COLUMN), 0.0)
        origin = [base[i] + origin_frac[i] - low[i] for i in range(2)]
        b3 = [(u * p * fa / fc, -u * p * fb / fc, -u * q) for p, q in a_pq]
        b_uv = [(origin[0] + c[0], origin[1] + c[1]) for c in corners]
        tris = rf._quad_tris(a3, a_uv, 1) + rf._quad_tris(b3, b_uv, 1)
        self.far_frac = (origin_frac, far0)
        self.tris: list[rf.Tri] = tris
        uvs = [uv for _, us in tris for uv in us]
        self.size = (math.ceil(max(c for c, _ in uvs)), math.ceil(max(r for _, r in uvs)))

    def bounds(self) -> tuple[rf.Vec3, rf.Vec3]:
        points = [p for ps, _ in self.tris for p in ps]
        low = tuple(min(p[i] for p in points) for i in range(3))
        high = tuple(max(p[i] for p in points) for i in range(3))
        return rf._vec3(low), rf._vec3(high)


def copies() -> list[TieCopy]:
    """Every fold, turn, A offset and far offset, the dyadic copy then its offset twin."""
    return [
        TieCopy(fold, turn, across, offset, twin)
        for fold in FOLDS
        for turn in TURNS
        for across in ACROSS
        for offset in OFFSETS
        for twin in TWINS
    ]


def layout() -> tuple[list[tuple[TieCopy, tuple[float, float], rf.Vec3]], tuple[float, float]]:
    """Decision 278's packing (UV shelves, disjoint 3D boxes at whole centimetres), each offset
    twin then moved by TWIN_DELTA."""
    placed, anchors = rf._pack(copies())
    moved = [
        (
            c,
            slot,
            rf._vec3([o[i] + (TWIN_DELTA[i] if c.twin == "offset" else 0.0) for i in range(3)]),
        )
        for c, slot, o in placed
    ]
    return moved, anchors


def exact(copy: TieCopy, slot: tuple[float, float], offset: rf.Vec3) -> bool:
    """Whether every placed position is a float32 on POSITION_GRID and every UV on UV_GRID."""
    for ps, uvs in copy.tris:
        for p in ps:
            for i in range(3):
                v = p[i] + offset[i]
                if float(np.float32(v)) != v or not (v / POSITION_GRID).is_integer():
                    return False
        for c, r in uvs:
            if (
                not ((c + slot[0]) / UV_GRID).is_integer()
                or not ((r + slot[1]) / UV_GRID).is_integer()
            ):
                return False
    return True


def mesh() -> bytes:
    """The probe's OBJ; refused unless every dyadic copy is exact and no offset twin is."""
    placed, anchors = layout()
    for copy, slot, offset in placed:
        if exact(copy, slot, offset) != (copy.twin == "dyadic"):
            raise ValueError(f"{copy.name}: exactness differs from its twin kind")
    data, faces = rf._packed_obj_lines(placed, anchors)
    return obj(
        MATERIAL,
        f"Folded-seam tie probe: {len(placed)} copies of a ratio-1 seam pair whose ring texels' "
        "far points lie on a far texel centre along the seam, dyadic and offset twins.",
        [(MATERIAL, faces)],
        "".join(data),
    )


def request() -> Golden:
    from tools.parity.tier0_semantics import recording_requests as rr

    n = len(copies())
    return Golden(
        GOLDEN,
        rr.EXPORT_DOMAIN,
        "Item 2.1 (phase3.1_export-island-padding) folded-seam tie probe of "
        "parity/reports/phase1/padding-tie-side-mixed-chain-diagnostic.md, exploratory: on which "
        "side of decision 275's far window boundary Painter puts a far point that lies on it "
        "along the seam across a fold, when every float32 formulation is exact and when it is "
        f"not. {n} copies of a ratio-1 seam pair (A and B {SIDE} x {SIDE} texels, separate UV "
        "islands, B turned 0, 90, 180 or 270 degrees in UV) folded convex flat, 90 degrees and "
        "along the Pythagorean directions 3-4-5, 4-3-5, 5-12-13 and 12-5-13, at c 2^-k cm per "
        "texel; three A offsets and three far offsets across the seam, every far point on a far "
        "texel centre along it; each configuration as a dyadic copy (every position and UV exact "
        "in float32, mesh box exactly [-256, 256] cm in x and z and [-64, 64] in y) and as its "
        f"twin moved by the non-dyadic ({TWIN_DELTA[0]}, {TWIN_DELTA[1]}, {TWIN_DELTA[2]}) cm; "
        "each copy its own 3D piece; document resolution "
        f"{RESOLUTION}. " + rr.KERNEL_TAIL,
        MESH,
        [MESH, *rr.kernel_bitmaps(RESOLUTION)],
        rr.kernel_probe(MESH, RESOLUTION),
    )


def describe() -> dict[str, Any]:
    return {"copies": len(copies()), "folds": list(FOLDS), "turns": list(TURNS)}
