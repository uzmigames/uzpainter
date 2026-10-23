"""Fresh authored endpoint-plane controls; no Painter data or fitted values."""

from __future__ import annotations

import itertools
import math
from typing import Any

from tools.parity.tier0_semantics import request_fixtures as rf
from tools.parity.tier0_semantics.corpus import Golden
from tools.parity.tier0_semantics.fixtures import obj

MESH = "padding-plane-control"
MATERIAL = "uzp_padding_plane_control"


class PlaneCopy:
    """A truncated corner changes hinge count while preserving both end planes."""

    def __init__(self, hinges: int, width: float, tilt: str, split: int) -> None:
        self.name = f"h{hinges}-w{width:g}-{tilt}-q{split}"
        self.size = (13, 5)
        self.hinges = hinges
        self.width = width
        self.tilt = tilt
        angle = math.radians(12.0)

        def point(s: float, q: float) -> rf.Vec3:
            if s <= 0.25:
                return (-s, 0.0, -q * width / 4.0)
            return (
                -0.25 - (s - 0.25) * math.cos(angle),
                (s - 0.25) * math.sin(angle),
                -q * width / 4.0,
            )

        # The two-hinge bevel joins equal distances on either side of the old
        # corner. Its end planes coincide with the one-hinge version exactly.
        cuts = (0.0, 0.25, 4.0) if hinges == 1 else (0.0, 0.125, 0.375, 4.0)
        tris: list[rf.Tri] = []
        for lo, hi in itertools.pairwise(cuts):
            pq = [(hi, 0.0), (lo, 0.0), (lo, 4.0), (hi, 4.0)]
            tris += rf._quad_tris(
                [point(s, q) for s, q in pq],
                [(4.21875 - s, 4.125 - q) for s, q in pq],
                split,
            )
        seam = math.radians(-6.0)
        pq = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
        tris += rf._quad_tris(
            [(s * math.cos(seam), s * math.sin(seam), -q * width / 4.0) for s, q in pq],
            [(12.21875 - q, 4.125 - s) for s, q in pq],
            split,
        )
        axis, degrees = rf.FOLD_TILTS[tilt]
        self.tris = [([rf._turned(p, axis, degrees) for p in ps], uv) for ps, uv in tris]

    def bounds(self) -> tuple[rf.Vec3, rf.Vec3]:
        points = [p for ps, _ in self.tris for p in ps]
        return (
            rf._vec3([min(p[i] for p in points) for i in range(3)]),
            rf._vec3([max(p[i] for p in points) for i in range(3)]),
        )


def copies() -> list[PlaneCopy]:
    """2x2 core, both diagonals, translated and rigidly rotated duplicates."""
    return [
        PlaneCopy(hinges, width, tilt, split)
        for tilt in ("flat", "flat", "x90", "oblique")
        for split in (0, 1)
        for width in (4.0, 16.0)
        for hinges in (1, 2)
    ]


def layout() -> tuple[list[tuple[Any, tuple[float, float], rf.Vec3]], tuple[float, float]]:
    return rf._pack(copies())


def mesh() -> bytes:
    placed, anchors = layout()
    data, faces = rf._packed_obj_lines(placed, anchors)
    return obj(
        MATERIAL,
        "Fresh direct-plane control: one/two tau hinges, regular/slender aspect, "
        "matched endpoint planes, rigid duplicates, fixed box anchors.",
        [(MATERIAL, faces)],
        "".join(data),
    )


def request() -> Golden:
    # Local import keeps fixture registration free of a module import cycle.
    from tools.parity.tier0_semantics import recording_requests as rr

    return Golden(
        "export-padding-plane-control",
        rr.EXPORT_DOMAIN,
        "Decision 358 fresh unrecorded discriminator: 32 independently authored copies; "
        "one 12-degree tau hinge versus two 6-degree hinges obtained by truncating "
        "the same corner, preserving endpoint supporting planes. Width 4/16 cm "
        "changes triangle aspect at fixed UVs. Both diagonals, translated duplicate, "
        "90-degree and oblique rigid duplicates; fixed mesh box anchors; 512 px. "
        "Freeze baseline, generic J/tau and conservative J/tau predictions before "
        "capture; first 12 channels discovery, other 12 verification. " + rr.KERNEL_TAIL,
        MESH,
        [MESH, *rr.kernel_bitmaps(512)],
        rr.kernel_probe(MESH, 512),
    )
