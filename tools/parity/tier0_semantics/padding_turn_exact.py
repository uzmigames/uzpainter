"""Turn-exact padding probe (phase1.25_pilot-wand item 2.7): a pair of requests, one mesh each,
that hold the world-offset probe's flat seam pairs with the far island folded at exactly 90
degrees (`x90`) and at its oblique Pythagorean angle (`oblique`). Authored geometry only; no
Painter data or fitted values. The design and its preflight are
`docs/analysis/padding-world-offset-residuals/01-residual-diagnosis.md` §7 and §9.

**Twins.** The oblique twins are the world-offset shapes without a bend
(`padding_world_offset.SHAPES`). The exact twin of a shape (`twin`) folds J's direction
(a, b, c) to (0, c, c): the UV island, the band depth (from c) and every 3D edge length
(|(a, b)| = c) are the oblique shape's, so the intrinsic developed geometry is the same. The bent
shapes have no twin: a 90-degree J with the oblique J-K bend needs a K direction off the dyadic
grid, whose band depth and positions are not exact.

**Copies.** Both meshes hold the same 123 copies (`copies`): the world-offset copies of the
three flat shapes at their offsets, turns, scales, duplicates and z lanes, each shape replaced by
its twin in the exact mesh. Both share the shelf layout (`layout`) and the world-offset probe's
two box anchors, so every exact copy sits in its oblique twin's UV slot (the same kernel values)
under the same mesh box and normalisation: a texel's pair is the same absolute texel in the same
slot. Every position and UV is exact in float32 and no two copies share a 3D point
(`obj_bytes`). Both use the world-offset material.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from tools.parity.tier0_semantics import padding_world_offset as wo
from tools.parity.tier0_semantics import request_fixtures as rf
from tools.parity.tier0_semantics.corpus import Golden
from tools.parity.tier0_semantics.fixtures import obj

TWINS = ("x90", "oblique")
EXACT = {"x90": True, "oblique": False}
MESHES = {twin: f"padding-turn-exact-{twin}" for twin in TWINS}
GOLDENS = {twin: f"export-{MESHES[twin]}" for twin in TWINS}
MATERIAL = wo.MATERIAL
RESOLUTION = wo.RESOLUTION
FLAT = tuple(s for s in wo.SHAPES if s.bend is None)


def twin(shape: wo.Shape) -> wo.Shape:
    """`shape` with J folded at exactly 90 degrees: (a, b, c) -> (0, c, c), c and the rest kept."""
    c = shape.fold[2]
    return shape._replace(name=f"{shape.name}-x90", fold=(0, c, c))


def copies(exact: bool, shapes: Sequence[wo.Shape] = FLAT) -> list[wo.OffsetCopy]:
    """`padding_world_offset.copies` restricted to `shapes` (each at its index in SHAPES, so its
    z lanes are the world-offset copies'), each shape replaced by its `twin` when `exact`."""
    out = []
    for i, base in enumerate(wo.SHAPES):
        if base not in shapes:
            continue
        shape = twin(base) if exact else base
        sep = wo._separated
        out += [
            wo.OffsetCopy(shape, sep(i, (x, 0.0, 0.0)), role="base" if x == 0 else "offset")
            for x in wo.OFFSETS_X
        ]
        out += [wo.OffsetCopy(shape, sep(i, o), role="yz") for o in wo.OFFSETS_YZ]
        out += [
            wo.OffsetCopy(shape, sep(i, (x, 0.0, 0.0), turn), turn, role="turn")
            for turn in ("y90", "z90")
            for x in wo.CONTROL_X
        ]
        out += [
            wo.OffsetCopy(shape, sep(i, (x, 0.0, 0.0), f"s{s}"), scale=s, role="scale")
            for s in wo.SCALES[1:]
            for x in wo.CONTROL_X
        ]
        out += [
            wo.OffsetCopy(shape, sep(i, (x, 0.0, 0.0), "dup"), tag="-dup", role="dup")
            for x in wo.CONTROL_X[1:]
        ]
    return out


def layout(
    found: Sequence[wo.OffsetCopy],
) -> tuple[list[tuple[wo.OffsetCopy, tuple[float, float]]], tuple[float, float]]:
    """`padding_world_offset.layout`'s shelves over `found`, and the anchors' slot."""
    limit = wo.RESOLUTION - rf.SWEEP_MARGIN
    column, row, shelf = rf.SWEEP_MARGIN, rf.SWEEP_MARGIN, 0
    placed = []
    for copy in found:
        width, height = copy.size
        if column + width > limit:
            column, row, shelf = rf.SWEEP_MARGIN, row + shelf + wo.UV_GAP, 0
        placed.append((copy, (float(column), float(row))))
        column += width + wo.UV_GAP
        shelf = max(shelf, height)
    anchors = (float(rf.SWEEP_MARGIN), float(row + shelf + wo.UV_GAP))
    if anchors[1] + 1 > limit:
        raise ValueError("the copies do not fit their tile")
    return placed, anchors


def obj_bytes(found: Sequence[wo.OffsetCopy], description: str) -> bytes:
    """The OBJ of `found` at its `layout`, with the world-offset probe's box anchors (box
    x in [-96, 204], y in [-64, 64], z in [-150, 150] cm); refused unless every position and UV is
    exact and no two copies share 3D space."""
    placed, anchors = layout(found)
    tris: list[rf.Tri] = []
    for copy, (oc, orow) in placed:
        tris += [(ps, [(c + oc, r + orow) for c, r in uvs]) for ps, uvs in copy.tris]
    if not wo.exact(tris):
        raise ValueError("a position or UV is not exact")
    if wo.overlaps(list(found)):
        raise ValueError("two copies share 3D space")
    data, faces = rf._sweep_obj_lines(tris, anchors, wo.HALF, wo.SHIFT)
    return obj(MATERIAL, description, [(MATERIAL, faces)], "".join(data))


def mesh(name: str) -> bytes:
    """The probe's OBJ of twin `name` (`x90` or `oblique`)."""
    found = copies(EXACT[name])
    fold = "folded at exactly 90 degrees" if EXACT[name] else "folded at its oblique angle"
    return obj_bytes(
        found,
        f"Turn-exact padding probe, {name} twin: {len(found)} copies of {len(FLAT)} flat seam "
        f"pairs, the far island {fold}.",
    )


def generator(name: str) -> Callable[[], bytes]:
    return lambda: mesh(name)


def request(name: str) -> Golden:
    from tools.parity.tier0_semantics import recording_requests as rr

    other = next(t for t in TWINS if t != name)
    fold = (
        "folded at exactly 90 degrees (J along (0, c, c))"
        if EXACT[name]
        else "folded along its oblique Pythagorean direction"
    )
    return Golden(
        GOLDENS[name],
        rr.EXPORT_DOMAIN,
        f"Item 2.7 unrecorded paired discriminator for the arithmetic of a far tap's rigid turn "
        f"(decision 364), the {name} twin of {GOLDENS[name]} and {GOLDENS[other]}: the "
        f"world-offset probe's {len(FLAT)} flat convex seam pairs at their 123 copies (world "
        "offsets, 90-degree turns, 3D scales and UV-slot duplicates), the far island "
        f"{fold}; both twins have the same layout, box anchors and UV slots, and the same UVs, "
        "band depths and 3D edge lengths, so a texel's pair is the same texel in the other "
        "twin; every position and UV exact in float32 and no two copies share a 3D point "
        "(tools/parity/fit/padding_turn_exact.py); predictions frozen before capture. "
        + rr.KERNEL_TAIL,
        MESHES[name],
        [MESHES[name], *rr.kernel_bitmaps(RESOLUTION)],
        rr.kernel_probe(MESHES[name], RESOLUTION),
    )
