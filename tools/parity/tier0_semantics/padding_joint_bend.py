"""Joint-bend padding probe (phase1.25_pilot-wand item 2.7): where the strip map's straight ends
leave a sample uncovered at a slightly bent UV joint of two seam edges. Authored geometry only; no
Painter data or fitted values.

Each copy is decision 298's island corner (`request_fixtures.CornerCopy`). Island A's edge e1 runs
up from the UV corner V: no seam (`n`), or a gated seam into a B1 that covers no texel (`ge`), so
that e1's strip competes for G but feeds T no tap. A's seam edge e2 runs from V, bent by `bend`
degrees, into B2 (A's plane, open). The ring texel T lies `across` texels beside e1. The sample G
one row from T toward V lies past V, `deficit` texels before e2's strip starts along e2, so that
e2 owns G only if its strip reaches that far past its end. G is the only sample of T's 3 x 3 that
e2's strip can own, so that T discovers e2 (and takes B2's taps through decision 294's corner
reach) only if e2 owns G. The deficit sweeps across the 1/256-texel snap of V's position
(decision 281's grid) and across a constant end tolerance, at several bends and across
distances, both bend signs, turned, mirrored, scaled and translated copies.
"""

from __future__ import annotations

import math
from typing import Any

from tools.parity.tier0_semantics import request_fixtures as rf
from tools.parity.tier0_semantics.corpus import Golden
from tools.parity.tier0_semantics.fixtures import obj

MESH = "padding-joint-bend"
MATERIAL = "uzp_joint_bend"
RESOLUTION = 512
# G's deficit before e2's strip start, in texels along e2: negative values put G inside the strip
# (controls), the positive ones straddle the 1/512 half step of the 1/256 snap and a constant end
# tolerance of up to 0.02 texel.
DEFICITS = (-0.004, -0.001, 0.0005, 0.001, 0.0015, 0.0017, 0.002, 0.0025, 0.003, 0.004, 0.006,
            0.0105, 0.015, 0.025)  # fmt: skip
BENDS = (1.0, 2.0, 2.8, 4.0, 6.0)  # degrees; |sin| 0.017 to 0.105, Wand's joint 0.049
ACROSS = (0.22, 0.3125)  # T's distance from e1 (texels)
TURNS = ("none", "r90", "mirror")
# V's row moved by these fractions of a texel (one 1/256 grid step in eight), by translating the
# whole copy perpendicular to e2 by phase / sin(bend): the deficit stays, T's distance from e1
# grows by phase / tan(bend).
PHASES = tuple(k / 2048 for k in range(8))


def border_margin(tris: list[rf.Tri]) -> float:
    """The smallest texel distance from a texel centre to a UV border edge of `tris` (an edge no
    other triangle of the copy shares in UV): `request_fixtures.side_margin` without the interior
    edges, whose two sides belong to one coplanar, isometric island."""
    count: dict[frozenset[tuple[float, float]], int] = {}
    for _, uvs in tris:
        for i in range(3):
            key = frozenset((uvs[i], uvs[(i + 1) % 3]))
            count[key] = count.get(key, 0) + 1
    low = math.inf
    for _, uvs in tris:
        cols, rows = [c for c, _ in uvs], [r for _, r in uvs]
        for i in range(3):
            p, q = uvs[i], uvs[(i + 1) % 3]
            if count[frozenset((p, q))] > 1:
                continue
            ex, ey = q[0] - p[0], q[1] - p[1]
            for x in range(math.floor(min(cols)) - 1, math.ceil(max(cols)) + 1):
                for y in range(math.floor(min(rows)) - 1, math.ceil(max(rows)) + 1):
                    t = ((x + 0.5 - p[0]) * ex + (y + 0.5 - p[1]) * ey) / (ex * ex + ey * ey)
                    t = min(max(t, 0.0), 1.0)
                    low = min(low, math.hypot(x + 0.5 - p[0] - t * ex, y + 0.5 - p[1] - t * ey))
    return low


class JointCopy:
    """A `CornerCopy` placed so that G lies `deficit` texels before e2's strip start, then turned
    90 degrees or mirrored in UV about T (3D kept; a mirror also reverses each triangle)."""

    def __init__(
        self,
        bend: float,
        across: float,
        deficit: float,
        turn: str = "none",
        gate: str = "n",
        scale: float = 1.0,
        phase: float = 0.0,
    ) -> None:
        self.name = f"{gate}-b{bend:g}-a{across:g}-d{deficit:g}-{turn}-s{scale:g}-p{phase * 2048:g}"
        self.bend, self.across, self.deficit, self.turn = bend, across, deficit, turn
        self.gate, self.scale, self.phase = gate, scale, phase
        t = math.radians(bend)
        # G = (across, -below) from V (y up); its along-e2 coordinate is -deficit:
        # -across sin t + below cos t = -deficit.
        below = (across * math.sin(t) - deficit) / math.cos(t)
        reach = math.hypot(across, 1.0 - below)
        # The phase moves every UV against e2's unit normal (cos t, sin t) in the layout (e2 runs
        # from V down, bent to -x), so that V's row falls by `phase`.
        move = -phase / math.sin(t) if phase else 0.0
        nc, nr = move * math.cos(t), move * math.sin(t)
        # The B islands' diagonal and sub-texel shift: the first that keeps every texel centre
        # SIDE_MARGIN from every border edge (as `request_fixtures.corner_copy`).
        for split, shift in [(sp, sh) for sp in (1, 0) for sh in rf.CORNER_SHIFTS]:
            corner = rf.CornerCopy(
                self.name, bend, reach, gate, facet=0.0, across=across, split=split, shift=shift
            )
            moved_tris = [(ps, [(c + nc, r + nr) for c, r in uvs]) for ps, uvs in corner.tris]
            self.valid = border_margin(moved_tris) >= rf.SIDE_MARGIN
            if self.valid:
                break
        self.target = corner.target
        tris = [(ps if scale == 1.0 else [rf._vec3([c * scale for c in p]) for p in ps], uvs)
                for ps, uvs in moved_tris]  # fmt: skip
        if turn != "none":
            tc, tr = self.target[0] + 0.5, self.target[1] + 0.5

            def moved(c: float, r: float) -> tuple[float, float]:
                if turn == "r90":
                    return (tc - (r - tr), tr + (c - tc))
                return (2 * tc - c, r)

            tris = [
                (ps, [moved(c, r) for c, r in uvs]) if turn == "r90"
                else (ps[::-1], [moved(c, r) for c, r in uvs[::-1]])
                for ps, uvs in tris
            ]  # fmt: skip
            low_c = math.floor(min(c for _, us in tris for c, _ in us)) - 1
            low_r = math.floor(min(r for _, us in tris for _, r in us)) - 1
            tris = [(ps, [(c - low_c, r - low_r) for c, r in us]) for ps, us in tris]
            self.target = (self.target[0] - low_c, self.target[1] - low_r)
        self.tris = tris
        uvs = [uv for _, us in tris for uv in us]
        self.size = (math.ceil(max(c for c, _ in uvs)) + 1, math.ceil(max(r for _, r in uvs)) + 1)

    def bounds(self) -> tuple[rf.Vec3, rf.Vec3]:
        points = [p for ps, _ in self.tris for p in ps]
        low = tuple(min(p[i] for p in points) for i in range(3))
        high = tuple(max(p[i] for p in points) for i in range(3))
        return rf._vec3(low), rf._vec3(high)


def copies() -> list[JointCopy]:
    """With e1 no seam (`n`): every bend (both signs) x across x deficit; the Wand-like bend
    turned 90 degrees and mirrored, and with its 3D doubled. With e1 a gated seam whose B1 covers
    no texel (`ge`, so that e1's strip competes for G but feeds T no tap): every positive bend
    at the first across. The phase pairs: bends 1 and 2.8 degrees, both e1 kinds, G inside the
    strip (-0.0015) and outside it (0.001, 0.0017), at every PHASES. Copies that cannot keep
    SIDE_MARGIN are left out. Then the first 28 copies again, a translate (another UV slot and 3D
    offset)."""
    out = [
        JointCopy(sign * bend, across, deficit)
        for sign in (1.0, -1.0)
        for bend in BENDS
        for across in ACROSS
        for deficit in DEFICITS
    ]
    out += [
        JointCopy(2.8, across, deficit, turn)
        for turn in TURNS[1:]
        for across in ACROSS
        for deficit in DEFICITS
    ]
    out += [JointCopy(2.8, ACROSS[0], deficit, scale=2.0) for deficit in DEFICITS]
    out += [
        JointCopy(bend, ACROSS[0], deficit, gate="ge") for bend in BENDS for deficit in DEFICITS
    ]
    out += [
        JointCopy(bend, ACROSS[0], deficit, gate=gate, phase=phase)
        for gate in ("n", "ge")
        for bend in (1.0, 2.8)
        for deficit in (-0.0015, 0.001, 0.0017)
        for phase in PHASES
    ]
    out = [c for c in out if c.valid]
    return out + [
        JointCopy(c.bend, c.across, c.deficit, c.turn, c.gate, c.scale, c.phase)
        for c in out[: len(DEFICITS) * 2]
    ]


def layout() -> tuple[list[tuple[Any, tuple[float, float], rf.Vec3]], tuple[float, float]]:
    return rf._pack(copies())


def mesh() -> bytes:
    placed, anchors = layout()
    data, faces = rf._packed_obj_lines(placed, anchors)
    return obj(
        MATERIAL,
        f"Joint-bend padding probe: {len(placed)} island corners whose seam edge leaves its UV "
        "corner bent 1 to 6 degrees, the ring texel's sample toward the corner a swept fraction "
        "of a texel before the seam strip's start.",
        [(MATERIAL, faces)],
        "".join(data),
    )


def request() -> Golden:
    from tools.parity.tier0_semantics import recording_requests as rr

    return Golden(
        "export-padding-joint-bend",
        rr.EXPORT_DOMAIN,
        "Item 2.7 unrecorded discriminator for the strip map's end rule at a bent UV joint: "
        "island corners whose seam edge leaves its corner bent 1 to 6 degrees (both signs), the "
        "ring texel's sample toward the corner -0.004 to 0.025 texel before the seam strip's "
        "start, across 0.22 and 0.3125 texel, the corner's row moved through one 1/256-texel "
        "step at fixed deficits, e1 no seam or a gated seam, turned 90 degrees, mirrored, "
        "3D-scaled and translated duplicates; fixed mesh box anchors; 512 px. Straight strip "
        "ends, ends or quad corners snapped to 1/256 texel, a constant end tolerance and mitred "
        "joins predict different kernel values (tools/parity/fit/padding_joint_bend.py); "
        "predictions frozen before capture. " + rr.KERNEL_TAIL,
        MESH,
        [MESH, *rr.kernel_bitmaps(RESOLUTION)],
        rr.kernel_probe(MESH, RESOLUTION),
    )
