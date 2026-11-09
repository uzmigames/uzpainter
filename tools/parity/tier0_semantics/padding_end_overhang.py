"""Seam-end overhang sweep (phase3.1_export-island-padding item 2.1): ring texels past a seam
end, on the folded-seam tie probe's geometry, whose far point is moved along the seam off a far
texel centre in 1/64-texel steps. Authored geometry only; no Painter data or fitted values. The
design is the separating recording named by the fold tie's sides note (2026-11-08,
`tools/parity/fit/padding_fold_tie_sides.py`).

**Why.** On `export-padding-fold-tie` Painter takes the exact-tie side of the far window along
the seam on every dyadic copy for texels whose centre projects inside the seam edge, but past a
seam end it takes the other side on 178 of 580 dyadic Pythagorean-fold texels, mostly at 0.625
texel past the end; never at the flat and 90-degree folds. A tie only tells the sign of the
difference between Painter's far coordinate along the seam and the reference's. Here every
configuration is copied with the far point moved along the seam by SHIFTS (-1/8 to +1/8 texel in
1/64 steps), so the shift where Painter's side changes brackets that difference to 1/64 texel, per
fold and overhang.

**A copy.** The fold tie's seam pair (`padding_fold_tie.TieCopy`'s construction: island A, a
SIDE x SIDE texel square in y = 0 over x in [-SIDE, 0] texels, its seam edge on the z axis; island
B folded convex about the seam along the Pythagorean direction (a, b) / c, one texel c 2^-k cm),
with B's UV at turn 0 (the seam vertical in J's UV, rows along it), A's UV box ACROSS texel off the
grid across the seam and `overhang` - 1/2 texel down from a row boundary, so that the ring row
above A's top seam end lies `overhang` texel past that end (and the row below its bottom end
1 - `overhang`). B's UV is placed so that the far point of every ring texel lies `shift` texel
along the seam (positive towards A's top end, the end the swept overhang is past) from a far
texel centre and OFFSET texel across from one. Every position and UV is exact in float32 (whole
centimetre placement, the mesh box exactly [-256, 256] cm in x and z): dyadic copies only.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from tools.parity.tier0_semantics import padding_fold_tie as ft
from tools.parity.tier0_semantics import request_fixtures as rf
from tools.parity.tier0_semantics.corpus import Golden
from tools.parity.tier0_semantics.fixtures import obj

MESH = "padding-end-overhang"
MATERIAL = "uzp_end_overhang"
GOLDEN = f"export-{MESH}"
RESOLUTION = rf.SWEEP_RESOLUTION
SIDE = ft.SIDE
B_COLUMN = ft.B_COLUMN
ACROSS = 0.25  # A's UV box offset across the seam (texels)
OFFSET = 0.625  # the far point's offset from a far texel centre across the seam (texels)
TURN = 0  # B's UV turn: the seam vertical in J's UV
OVERHANGS = tuple(0.5 + k / 16 for k in range(5))  # past A's top seam end (texels)
SHIFTS = tuple(k / 64 for k in range(-8, 9))  # the far point along the seam (texels)
FOLDS = ("flat", "f23", "f37", "f53", "f67", "x90")


class OverhangCopy:
    """One copy: fold `fold`, A's top-end `overhang`, the far point's along-seam `shift`. Its
    triangles are in local cm (as `padding_fold_tie.TieCopy`), with layout UVs from the slot's
    top-left texel."""

    def __init__(self, fold: str, overhang: float, shift: float) -> None:
        self.fold, self.overhang, self.shift = fold, overhang, shift
        self.name = f"{fold}-h{overhang:g}-s{shift:g}"
        fa, fb, fc = ft.FOLDS[fold]
        u = ft.unit(fc)
        side = float(SIDE)
        row = overhang - 0.5  # A's UV box offset along the seam
        a_pq = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
        a3 = [(u * (p - side), 0.0, -u * q) for p, q in a_pq]
        a_uv = [(ACROSS + p, row + side - q) for p, q in a_pq]
        # As in TieCopy: the far point of a ring texel at (column + 1/2, r + 1/2) is, in B's frame,
        # origin + d across + q along, with d's and q's fractional parts those of the first
        # texel's; `shift` moves it along the seam (q, the direction of e_along).
        e_across, e_along = ft.TURNS[TURN]
        d0 = 0.5 - ft._frac(ACROSS + side)
        q0 = row + side - 0.5
        far0 = (d0 * e_across[0] + q0 * e_along[0], d0 * e_across[1] + q0 * e_along[1])
        along_axis = 0 if e_along[0] != 0 else 1
        want = [0.0, 0.0]
        want[along_axis] = ft._frac(0.5 + shift * e_along[along_axis])
        want[1 - along_axis] = ft._frac(0.5 + OFFSET)
        origin_frac = [ft._frac(want[i] - far0[i]) for i in range(2)]
        corners = [
            (p * e_across[0] + q * e_along[0], p * e_across[1] + q * e_along[1]) for p, q in a_pq
        ]
        low = [min(c[i] for c in corners) for i in range(2)]
        base = (float(B_COLUMN), 0.0)
        origin = [base[i] + origin_frac[i] - low[i] for i in range(2)]
        b3 = [(u * p * fa / fc, -u * p * fb / fc, -u * q) for p, q in a_pq]
        b_uv = [(origin[0] + c[0], origin[1] + c[1]) for c in corners]
        self.tris: list[rf.Tri] = rf._quad_tris(a3, a_uv, 1) + rf._quad_tris(b3, b_uv, 1)
        self.top_end = row  # A's top seam end, in layout rows
        uvs = [uv for _, us in self.tris for uv in us]
        self.size = (math.ceil(max(c for c, _ in uvs)), math.ceil(max(r for _, r in uvs)))

    def bounds(self) -> tuple[rf.Vec3, rf.Vec3]:
        points = [p for ps, _ in self.tris for p in ps]
        low = tuple(min(p[i] for p in points) for i in range(3))
        high = tuple(max(p[i] for p in points) for i in range(3))
        return rf._vec3(low), rf._vec3(high)


def copies() -> list[OverhangCopy]:
    """Every fold, overhang and shift."""
    return [
        OverhangCopy(fold, overhang, shift)
        for fold in FOLDS
        for overhang in OVERHANGS
        for shift in SHIFTS
    ]


def layout() -> tuple[list[tuple[OverhangCopy, tuple[float, float], rf.Vec3]], tuple[float, float]]:
    """Decision 278's packing (UV shelves, disjoint 3D boxes at whole centimetres)."""
    return rf._pack(copies())


def exact(copy: OverhangCopy, slot: tuple[float, float], offset: rf.Vec3) -> bool:
    """Whether every placed position is a float32 on the fold tie's position grid and every UV on
    its UV grid."""
    for ps, uvs in copy.tris:
        for p in ps:
            for i in range(3):
                v = p[i] + offset[i]
                if float(np.float32(v)) != v or not (v / ft.POSITION_GRID).is_integer():
                    return False
        for c, r in uvs:
            if (
                not ((c + slot[0]) / ft.UV_GRID).is_integer()
                or not ((r + slot[1]) / ft.UV_GRID).is_integer()
            ):
                return False
    return True


def mesh() -> bytes:
    """The sweep's OBJ; refused unless every copy is exact."""
    placed, anchors = layout()
    for copy, slot, offset in placed:
        if not exact(copy, slot, offset):
            raise ValueError(f"{copy.name}: not exact in float32")
    data, faces = rf._packed_obj_lines(placed, anchors)
    return obj(
        MATERIAL,
        f"Seam-end overhang sweep: {len(placed)} copies of the folded-seam tie probe's ratio-1 "
        "seam pair, ring texels 0.5 to 0.75 texel past a seam end, the far point moved along the "
        "seam off a far texel centre by -1/8 to +1/8 texel.",
        [(MATERIAL, faces)],
        "".join(data),
    )


def request() -> Golden:
    from tools.parity.tier0_semantics import recording_requests as rr

    n = len(copies())
    return Golden(
        GOLDEN,
        rr.EXPORT_DOMAIN,
        "Item 2.1 (phase3.1_export-island-padding) seam-end overhang sweep, exploratory: which "
        "far texel window along the seam Painter takes for a ring texel past a seam end, as the "
        "far point moves along the seam across a far texel centre (decision 275's window "
        f"boundary). {n} copies of export-padding-fold-tie's ratio-1 seam pair (A and B {SIDE} x "
        f"{SIDE} texels, separate UV islands, B at turn {TURN}, A {ACROSS:g} texel and the far "
        f"point {OFFSET:g} texel off the grid across the seam) folded convex flat, 90 degrees "
        "and along the Pythagorean directions 12-5-13, 4-3-5, 3-4-5 and 5-12-13, at c 2^-k cm "
        "per texel; the ring row above A's top seam end 0.5 to 0.75 texel past it in 1/16 "
        "steps; the far point -1/8 to +1/8 texel along the seam from a far texel centre in 1/64 "
        "steps; every position and UV exact in float32, mesh box exactly [-256, 256] cm in x and "
        f"z and [-64, 64] in y; each copy its own 3D piece; document resolution {RESOLUTION}. "
        + rr.KERNEL_TAIL,
        MESH,
        [MESH, *rr.kernel_bitmaps(RESOLUTION)],
        rr.kernel_probe(MESH, RESOLUTION),
    )


def describe() -> dict[str, Any]:
    return {
        "copies": len(copies()),
        "folds": list(FOLDS),
        "overhangs": list(OVERHANGS),
        "shifts": list(SHIFTS),
    }
