"""World-offset padding probe (phase1.25_pilot-wand item 2.7): one seam pair, the same exact shape
at growing world offsets, to tell the float32 arithmetic of a far tap's rigid turn (decision 364)
apart from the double reference. Authored geometry only; no Painter data or fitted values.

Each copy is decision 278's seam pair at TEXEL cm per texel: island A, an L x L texel square in
y = 0 over x in [-L, 0], its seam edge on the z axis; island B beyond the seam, folded about it
along a Pythagorean direction (a, b) / c, so that every corner is a dyadic rational. B is flat
(one band, the far triangle J holds every far tap) or bent (a band J of depth c / 4 or c / 8 or
c / 16 texel, then a band K along a second Pythagorean direction, hinged to J, two of three past
decision 282's gate, so that some far taps lie in K, off J's plane: the configuration of the
Wand's new texel).
B's UV island is turned 90 degrees and stretched along the seam by a dyadic fraction, so that the
far point's phase drifts along the seam and the ring texels' chains take many fractions.

Every UV is a multiple of 2^-8 texel at 512 px and every position a multiple of 2^-16 cm below
256 cm in magnitude, so the OBJ's float32 values are exact: a copy moved by any of OFFSETS keeps
its shape bit for bit, and so do the turned (90 degrees about a coordinate axis) and scaled (2,
3) controls up to their scale. A double far turn therefore gives every translated copy of a
shape the same chain (taps relative to its UV slot, chain fractions); arithmetic whose rounding
grows with the position's magnitude (float32 positions or their box normalisation, decision 273)
does not. The kernel bitmaps' codes are periodic in the tile, not in the copy's slot, so the
predicted output values differ between slots even for equal chains. No two copies share a vertex
or any 3D point: shapes at one offset are SHAPE_GAP apart in z and each control kind has its own
z lane (`overlaps`). The mesh box is
fixed by two anchors at x in [-96, 204], y in [-64, 64], z in [-150, 150] cm, so that decision
273's scale r = 1 / 150 and centre c = (54, 0, 0) are not powers of two: normalised and raw
float32 positions round differently.
"""

from __future__ import annotations

import itertools
import math
from typing import Any, NamedTuple

import numpy as np

from tools.parity.tier0_semantics import request_fixtures as rf
from tools.parity.tier0_semantics.corpus import Golden
from tools.parity.tier0_semantics.fixtures import obj

MESH = "padding-world-offset"
MATERIAL = "uzp_world_offset"
RESOLUTION = 512
TEXEL = 2.0**-5  # cm per texel of a copy at scale 1
SIDE = 12  # A's side and B's length along the seam, texels
B_COLUMN = SIDE + 6  # B's UV box starts this many texels right of A's
HALF = 150.0
SHIFT: rf.Vec3 = (54.0, 0.0, 0.0)  # the box centre: x in [-96, 204]
SHAPE_GAP = 0.5  # cm in z between the shapes at one offset, per unit of 3D scale
# Each control kind's own z lane (cm below its offset), so that no two copies share a vertex,
# an edge or any 3D point: the 3D boxes of all copies are pairwise disjoint (`overlaps`).
# The shapes of a lane are SHAPE_GAP times its gap factor apart (a turned or scaled copy
# reaches further in z).
LANES = {"dup": (4.0, 1), "y90": (8.0, 2), "z90": (16.0, 2), "s2": (24.0, 2), "s3": (34.0, 3)}
UV_GAP = 4
A_STRETCH = 17 / 16  # A's 3D length per UV texel across the seam
A_SHEAR = 1 / 8  # A's 3D shift along the seam per UV texel across it
POSITION_GRID = 2.0**-16  # cm
UV_GRID = 2.0**-8  # texel


class Shape(NamedTuple):
    """`fold`: J's direction (a, b, c), `sign` +1 concave, -1 convex; `bend`: K's direction or
    None for a flat B; `shift`: A's and B's sub-texel UV offset; `stretch`: B's extra UV length
    along the seam (texels)."""

    name: str
    fold: tuple[int, int, int]
    sign: int
    bend: tuple[int, int, int] | None
    shift: float
    stretch: float


# Every fold is convex: decision 278's gate closes a concave seam to its ring texels, which then
# take no far tap.
SHAPES = (
    Shape("f37v", (4, 3, 5), -1, None, 0.25, 0.5),
    Shape("f23v", (12, 5, 13), -1, None, 0.375, 0.75),
    Shape("f53v", (3, 4, 5), -1, None, 0.125, 0.25),
    Shape("b37-23v", (4, 3, 5), -1, (12, 5, 13), 0.25, 0.5),
    Shape("b23-53v", (12, 5, 13), -1, (3, 4, 5), 0.375, 0.75),
    Shape("b28-37v", (15, 8, 17), -1, (4, 3, 5), 0.125, 0.25),
)
# World x offsets of a copy's seam corner (cm): from the origin to the box's ends, across the
# box centre 54 (normalised x near 0) and through the float32 binades 1 to 128.
OFFSETS_X = (0.0, 1.0, 2.0, 3.0, 8.0, 16.0, 24.0, 40.0, 54.0, 64.0, 80.0, 100.0, 120.0, 128.0,
             140.0, 160.0, 180.0, 200.0, -1.0, -10.0, -30.0, -60.0, -90.0)  # fmt: skip
# Offsets on the other axes (cm), at x 0.
OFFSETS_YZ: tuple[rf.Vec3, ...] = ((0.0, 40.0, 0.0), (0.0, -40.0, 0.0), (0.0, 0.0, 100.0),
                                   (0.0, 0.0, -100.0))  # fmt: skip
CONTROL_X = (0.0, 64.0, 128.0)
TURNS: dict[str, tuple[rf.Vec3, float]] = {
    "none": ((1.0, 0.0, 0.0), 0.0),
    "y90": ((0.0, 1.0, 0.0), 90.0),
    "z90": ((0.0, 0.0, 1.0), 90.0),
}
SCALES = (1, 2, 3)


def _band_depths(shape: Shape) -> list[tuple[float, tuple[int, int, int]]]:
    """B's bands from the seam outward: (UV depth in texels, 3D direction (a, b, c))."""
    c = shape.fold[2]
    if shape.bend is None:
        return [(3 * c / 2 ** round(math.log2(c / 1.25)), shape.fold)]
    first = c / 2 ** round(math.log2(c / 1.25))
    c2 = shape.bend[2]
    return [(first, shape.fold), (2 * c2 / 2 ** round(math.log2(2 * c2 / 2.5)), shape.bend)]


class OffsetCopy:
    """One copy: a shape at a world `offset` (of the seam's corner at q = 0), turned about a
    coordinate axis and scaled in 3D (UV unchanged). `role`: `base` (the shape's copy at x 0,
    the translations' reference), `offset` (OFFSETS_X), `yz` (OFFSETS_YZ), `turn`, `scale` or
    `dup` (a translated duplicate in another UV slot)."""

    def __init__(
        self,
        shape: Shape,
        offset: rf.Vec3,
        turn: str = "none",
        scale: int = 1,
        tag: str = "",
        role: str = "offset",
    ) -> None:
        self.shape, self.offset, self.turn, self.scale = shape, offset, turn, scale
        self.role = role
        o = "_".join(f"{c:g}" for c in offset)
        self.name = f"{shape.name}-o{o}-{turn}-s{scale}{tag}"
        side = float(SIDE)
        unit = TEXEL * scale
        axis, degrees = TURNS[turn]

        def place(x: float, y: float, z: float) -> rf.Vec3:
            p = rf._turned((x * unit + 0.0, y * unit + 0.0, z * unit + 0.0), axis, degrees)
            return rf._vec3([p[i] + offset[i] - SHIFT[i] for i in range(3)])

        a_pq = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
        # A is stretched by A_STRETCH across the seam and sheared by A_SHEAR along it (the seam
        # edge p = side unchanged), so that no two own taps of a ring texel lie at equal 3D
        # distances: decision 273's float32 comparator, which orders such ties by position,
        # then decides no chain.
        a3 = [place((p - side) * A_STRETCH, 0.0, -q + (p - side) * A_SHEAR) for p, q in a_pq]
        a_uv = [(shape.shift + p, 0.125 + side - q) for p, q in a_pq]
        tris: list[rf.Tri] = rf._quad_tris(a3, a_uv, 1)
        bands = _band_depths(shape)
        depth = sum(d for d, _ in bands)
        start, base = 0.0, (0.0, 0.0)
        length = side + shape.stretch
        for d, (fa, fb, fc) in bands:

            def at(
                p: float, q: float, base: tuple[float, float] = base, start: float = start,
                fa: int = fa, fb: int = fb, fc: int = fc,
            ) -> rf.Vec3:  # fmt: skip
                # (p - start) a / c is exact: p - start is a multiple of c over a power of two.
                return place(
                    base[0] + (p - start) * fa / fc,
                    base[1] + shape.sign * ((p - start) * fb / fc),
                    -q,
                )

            b_pq = [(start, 0.0), (start + d, 0.0), (start + d, side), (start, side)]
            b3 = [at(p, q) for p, q in b_pq]
            b_uv = [
                (B_COLUMN + shape.shift + (side - q) * length / side, 0.125 + depth - p)
                for p, q in b_pq
            ]
            tris += rf._quad_tris(b3, b_uv, 1)
            base = (base[0] + d * fa / fc, base[1] + shape.sign * (d * fb / fc))
            start += d
        self.tris = tris
        uvs = [uv for _, us in tris for uv in us]
        self.size = (math.ceil(max(c for c, _ in uvs)) + 1, math.ceil(max(r for _, r in uvs)) + 1)

    def bounds(self) -> tuple[rf.Vec3, rf.Vec3]:
        points = [p for ps, _ in self.tris for p in ps]
        low = tuple(min(p[i] for p in points) for i in range(3))
        high = tuple(max(p[i] for p in points) for i in range(3))
        return rf._vec3(low), rf._vec3(high)


def _separated(index: int, offset: rf.Vec3, lane: str | None = None) -> rf.Vec3:
    extra, gap = (0.0, 1) if lane is None else LANES[lane]
    return (offset[0], offset[1], offset[2] - index * SHAPE_GAP * gap - extra)


def copies() -> list[OffsetCopy]:
    """Per shape: every OFFSETS_X and OFFSETS_YZ; turned y90 and z90 and scaled 2 and 3 at
    CONTROL_X; and a translated duplicate (another UV slot) at CONTROL_X[1:]. Shapes at one
    offset are SHAPE_GAP cm apart in z; each control kind lies in its own z lane (LANES)."""
    out = []
    for i, shape in enumerate(SHAPES):
        out += [
            OffsetCopy(shape, _separated(i, (x, 0.0, 0.0)), role="base" if x == 0 else "offset")
            for x in OFFSETS_X
        ]
        out += [OffsetCopy(shape, _separated(i, o), role="yz") for o in OFFSETS_YZ]
        out += [
            OffsetCopy(shape, _separated(i, (x, 0.0, 0.0), turn), turn, role="turn")
            for turn in ("y90", "z90")
            for x in CONTROL_X
        ]
        out += [
            OffsetCopy(shape, _separated(i, (x, 0.0, 0.0), f"s{s}"), scale=s, role="scale")
            for s in SCALES[1:]
            for x in CONTROL_X
        ]
        out += [
            OffsetCopy(shape, _separated(i, (x, 0.0, 0.0), "dup"), tag="-dup", role="dup")
            for x in CONTROL_X[1:]
        ]
    return out


def overlaps(found: list[OffsetCopy]) -> list[tuple[str, str]]:
    """The pairs of copies whose closed 3D boxes meet (shared points possible), and of copies
    sharing a float32 vertex position; empty for the probe."""
    out = []
    boxes = [c.bounds() for c in found]
    for (i, a), (j, b) in itertools.combinations(enumerate(boxes), 2):
        if all(a[0][k] <= b[1][k] and b[0][k] <= a[1][k] for k in range(3)):
            out.append((found[i].name, found[j].name))
    seen: dict[tuple[float, ...], str] = {}
    for c in found:
        for p in {tuple(float(np.float32(v + s)) for v, s in zip(q, SHIFT, strict=True))
                  for ps, _ in c.tris for q in ps}:  # fmt: skip
            if p in seen:
                out.append((seen[p], c.name))
            seen[p] = c.name
    return out


def layout() -> tuple[list[tuple[OffsetCopy, tuple[float, float]]], tuple[float, float]]:
    """Every copy with its UV slot's top-left texel (shelves UV_GAP texels apart), and the
    anchors' slot."""
    limit = RESOLUTION - rf.SWEEP_MARGIN
    column, row, shelf = rf.SWEEP_MARGIN, rf.SWEEP_MARGIN, 0
    placed = []
    for copy in copies():
        width, height = copy.size
        if column + width > limit:
            column, row, shelf = rf.SWEEP_MARGIN, row + shelf + UV_GAP, 0
        placed.append((copy, (float(column), float(row))))
        column += width + UV_GAP
        shelf = max(shelf, height)
    anchors = (float(rf.SWEEP_MARGIN), float(row + shelf + UV_GAP))
    assert anchors[1] + 1 <= limit, "the copies do not fit their tile"
    return placed, anchors


def triangles() -> tuple[list[rf.Tri], tuple[float, float]]:
    placed, anchors = layout()
    tris: list[rf.Tri] = []
    for copy, (oc, orow) in placed:
        tris += [(ps, [(c + oc, r + orow) for c, r in uvs]) for ps, uvs in copy.tris]
    return tris, anchors


def exact(tris: list[rf.Tri]) -> bool:
    """Whether every position (after the box shift) is a float32 on POSITION_GRID and every UV
    on UV_GRID, so that the OBJ's float32 values are the authored ones."""
    for ps, uvs in tris:
        for p in ps:
            for i in range(3):
                v = p[i] + SHIFT[i]
                if float(np.float32(v)) != v or not (v / POSITION_GRID).is_integer():
                    return False
        for c, r in uvs:
            if not (c / UV_GRID).is_integer() or not (r / UV_GRID).is_integer():
                return False
    return True


def mesh() -> bytes:
    tris, anchors = triangles()
    if not exact(tris):
        raise ValueError("a position or UV is not exact")
    if overlaps(copies()):
        raise ValueError("two copies share 3D space")
    data, faces = rf._sweep_obj_lines(tris, anchors, HALF, SHIFT)
    return obj(
        MATERIAL,
        f"World-offset padding probe: {len(copies())} copies of {len(SHAPES)} exact folded seam "
        "pairs at world offsets from 0 to 200 cm, turned, scaled and translated controls.",
        [(MATERIAL, faces)],
        "".join(data),
    )


def request() -> Golden:
    from tools.parity.tier0_semantics import recording_requests as rr

    return Golden(
        "export-padding-world-offset",
        rr.EXPORT_DOMAIN,
        "Item 2.7 unrecorded discriminator for the arithmetic of a far tap's rigid turn "
        "(decision 364): six exact folded seam pairs (flat or bent far island, Pythagorean "
        "folds), each copied at 27 world offsets from 0 to 200 cm across a mesh box whose "
        "normalisation scale and centre are not powers of two, turned 90 degrees, scaled 2 and "
        "3 times in 3D and translated to another UV slot; every position and UV exact in "
        "float32, so a double far turn gives every translated copy of a shape the same chain "
        "(taps relative to the slot, fractions) and float32 position arithmetic does not; no two "
        "copies share a 3D point "
        "(tools/parity/fit/padding_world_offset.py); predictions frozen before capture. "
        + rr.KERNEL_TAIL,
        MESH,
        [MESH, *rr.kernel_bitmaps(RESOLUTION)],
        rr.kernel_probe(MESH, RESOLUTION),
    )


def describe() -> dict[str, Any]:
    return {"copies": len(copies()), "shapes": [s.name for s in SHAPES]}
