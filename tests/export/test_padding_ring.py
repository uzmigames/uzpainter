"""Synthetic cases of the measured `infinite` padding ring (src/export/padding.h; phase1.25 item
2.7, decisions 267, 268, 270, 273, 275, 278 to 282, 285, 288 and 290 to 292), through
`uzp-export-tests ring`.

Each case pads random float32 values over a small OBJ written here, and compares UzPainter's ring
texels bit for bit with a reference of the rule: on a single island this file's own (the ring
point extrapolated through the island's affine map, the covered 8-neighbours, the 4 nearest, the
exact 1/d shares quantised to 10, 8 and 6 bits, the float32 FMA lerp chain and decision 206's
rounding; shares within decision 282's band ordered by decision 273's comparator, then decision
280's neighbour order); across a UV seam `padding_reference` (the far window of decision 275 in
padding.cpp's double arithmetic, decision 278's seam gate with tau's normal (decision 292),
decision 279's ring point, neighbours and reach, decision 280's tap count, decision 282's hinge
gate and far tie order, decisions 285 and 288's distances, reach and welding, the windows that
decisions 288 and 290 close, decision 291's window side), and the gutter's clamped jump flood
(decision 285). The coverage snaps vertices to 1/256 texel (decision 281). No Painter data is
read.
"""

from __future__ import annotations

import itertools
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.export.padding_reference import (
    F32,
    FLOOD,
    NEIGHBOURS,
    OWN_ORDER,
    REACH_CAP,
    Ring,
    box_normalised,
    chain,
    compare_distance,
    fractions,
    hinge,
    segment_distance,
    tap_count,
    unfold,
)
from tools.parity.feasibility import png

Quad = tuple[list[tuple[float, float, float]], list[tuple[float, float]]]  # positions, UVs


class Mesh:
    """Quads (two triangles each, (0, 1, 2) and (0, 2, 3)) on a W x H tile: the OBJ, the coverage
    and the per-island maps the reference reads."""

    def __init__(self, quads: list[Quad], size: int) -> None:
        self.quads = quads
        self.size = size
        self.triangles: list[
            tuple[np.ndarray, np.ndarray]
        ] = []  # (3D (3, 3) float32, UV (3, 2) float32)
        self.island: list[int] = []
        for i, (p, uv) in enumerate(quads):
            for idx in ((0, 1, 2), (0, 2, 3)):
                self.triangles.append(
                    (np.array([p[j] for j in idx], F32), np.array([uv[j] for j in idx], F32))
                )
                self.island.append(i)
        allp = np.array([v for p, _ in quads for v in p], F32)
        lo, hi = allp.min(0), allp.max(0)
        self.normalised = [box_normalised(t, lo, hi) for t, _ in self.triangles]
        self.owner = -np.ones((size, size), int)
        for k, (_, tuv) in enumerate(self.triangles):
            # Vertices snapped to 1/256 texel (decision 281), v down, centres at + 1/2.
            t = [
                (round(float(u) * size * 256) / 256, round((1 - float(v)) * size * 256) / 256)
                for u, v in tuv
            ]
            for row in range(size):
                for col in range(size):
                    w = [
                        (t[(i + 1) % 3][0] - t[i][0]) * (row + 0.5 - t[i][1])
                        - (t[(i + 1) % 3][1] - t[i][1]) * (col + 0.5 - t[i][0])
                        for i in range(3)
                    ]
                    if (all(x >= 0 for x in w) or all(x <= 0 for x in w)) and self.owner[
                        row, col
                    ] < 0:
                        self.owner[row, col] = k

    def obj(self, path: Path) -> Path:
        lines = ["usemtl m"]
        for p, uv in self.quads:
            lines += [f"v {float(F32(a))!r} {float(F32(b))!r} {float(F32(c))!r}" for a, b, c in p]
            lines += [f"vt {float(F32(u))!r} {float(F32(v))!r}" for u, v in uv]
        for i in range(len(self.quads)):
            b = 4 * i
            lines += [
                f"f {b + 1}/{b + 1} {b + 2}/{b + 2} {b + 3}/{b + 3}",
                f"f {b + 1}/{b + 1} {b + 3}/{b + 3} {b + 4}/{b + 4}",
            ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def point(self, island: int, x: float, y: float) -> np.ndarray:
        """The 3D point of texel-space (x, y) through `island`'s affine map."""
        p, uv = self.quads[island]
        t = np.array(
            [
                [u * self.size, (1 - v) * self.size, 1.0]
                for u, v in np.array(uv, F32).astype(np.float64)
            ]
        )
        m = np.linalg.solve(t[:3], np.array(p, F32).astype(np.float64)[:3])
        result: np.ndarray = np.array([x, y, 1.0]) @ m
        return result

    def compare(self, ring: tuple[int, int], tap: tuple[int, int]) -> np.float32:
        """Decision 273's comparator distance of `tap` in its own triangle."""
        k = int(self.owner[tap[1], tap[0]])
        return compare_distance(
            self.triangles[k][1], self.normalised[k], self.size, self.size, ring, tap
        )


def reference(
    mesh: Mesh, values: np.ndarray, ring: tuple[int, int]
) -> tuple[list[tuple[int, int]], np.ndarray]:
    """The taps (tap order) and value of ring texel `ring` = (x, y) of an island without seams."""
    x, y = ring
    size = mesh.size
    own = [
        (x + dx, y + dy)
        for dy, dx in NEIGHBOURS
        if 0 <= y + dy < size and 0 <= x + dx < size and mesh.owner[y + dy, x + dx] >= 0
    ]
    island = mesh.island[max(int(mesh.owner[ty, tx]) for tx, ty in own)]
    q = mesh.point(island, x + 0.5, y + 0.5)
    cands = [
        (float(np.linalg.norm(q - mesh.point(island, tx + 0.5, ty + 0.5))), False, (tx, ty))
        for tx, ty in own
    ]

    def key(c: tuple[float, bool, tuple[int, int]]) -> tuple[Any, ...]:
        return (float(mesh.compare(ring, c[2])), OWN_ORDER.index((c[2][0] - x, y - c[2][1])))

    cands.sort(key=lambda c: c[0])
    ordered: list[tuple[float, bool, tuple[int, int]]] = []
    while cands:
        group = [c for c in cands if c[0] <= cands[0][0] * (1 + 1e-5)]
        cands = cands[len(group) :]
        ordered += sorted(group, key=key) if len(group) > 1 else group
    taps = ordered[:1] if ordered[0][0] <= 1e-6 * min(c[0] for c in ordered) else ordered[:4]
    t = fractions([c[0] for c in taps])
    out = np.array(
        [
            chain([F32(values[ty, tx, c]) for _, _, (tx, ty) in taps], t)
            for c in range(values.shape[2])
        ],
        F32,
    )
    return [c[2] for c in taps], out


def run(
    exe: Path, tmp: Path, mesh: Mesh | Triangles, name: str, seed: int
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    size = mesh.size
    values = np.random.default_rng(seed).random((size, size, 3)).astype(F32)
    (tmp / f"{name}.f32").write_bytes(values.tobytes())
    case = {
        "mesh": str(mesh.obj(tmp / f"{name}.obj")),
        "material": "m",
        "width": size,
        "height": size,
        "channels": 3,
        "values": str(tmp / f"{name}.f32"),
        "out": str(tmp / f"{name}.out"),
    }
    (tmp / f"{name}.json").write_text(json.dumps([case]), encoding="utf-8")
    proc = subprocess.run(
        [str(exe), "ring", str(tmp / f"{name}.json")],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = np.frombuffer((tmp / f"{name}.out").read_bytes(), F32).reshape(size, size, 3)
    return values, out, json.loads(proc.stdout)["ring"]


def flat_square(lo: float, hi: float, scale: float) -> Quad:
    """A UV square [lo, hi]^2 on the plane y = 0, x and z = (uv - 1/2) scale."""
    corners = [(lo, lo), (hi, lo), (hi, hi), (lo, hi)]
    return [((u - 0.5) * scale, 0.0, (v - 0.5) * scale) for u, v in corners], corners


def bits(x: Any) -> int:
    return int(np.array([x], F32).view(np.uint32)[0])


def test_straight_edge_ring_is_decision_273s_chain(export_tests: Path, tmp_path: Path) -> None:
    """A dyadic square island: each straight-edge ring texel takes its side tap (code 224 of 1023,
    t = 0x3ED41505) and the two diagonals (code 64 of 255, t = 0x3F002AD6; the shares tie exactly,
    so the strong diagonal is +x on horizontal edges, -row on vertical ones), each outer corner
    copies its diagonal (through decision 206's rounding), and every ring value equals the
    reference bit for bit."""
    mesh = Mesh([flat_square(0.25, 0.75, 4.0)], 16)
    values, out, ring = run(export_tests, tmp_path, mesh, "square", 1)
    assert len(ring) == 4 * 8 + 4
    edges = 0
    for r in ring:
        x, y = r["x"], r["y"]
        taps = [(c[0], c[1]) for c in r["candidates"][: r["taps"]]]
        expected_taps, expected = reference(mesh, values, (x, y))
        assert taps == expected_taps, (x, y)
        assert out[y, x].view(np.uint32).tolist() == expected.view(np.uint32).tolist(), (x, y)
        if 5 <= x <= 10 and y in (3, 12):
            side = 4 if y == 3 else 11
            assert taps == [(x, side), (x + 1, side), (x - 1, side)]
        elif 5 <= y <= 10 and x in (3, 12):
            side = 4 if x == 3 else 11
            assert taps == [(side, y), (side, y - 1), (side, y + 1)]
        elif x in (3, 12) and y in (3, 12):
            copied = (F32(1) - (F32(1) - values[taps[0][1], taps[0][0]])).astype(
                F32
            )  # decision 206's rounding
            assert r["taps"] == 1 and out[y, x].tolist() == copied.tolist()
            continue
        else:
            continue
        edges += 1
        assert r["fractions"] == [0x3ED41505, 0x3F002AD6]
    assert edges == 4 * 6


def test_equal_diagonal_shares_follow_the_comparator(export_tests: Path, tmp_path: Path) -> None:
    """A square island on non-dyadic UVs and positions: the two diagonals' shares are equal, and the
    strong one is decision 273's comparator's nearer one (an exact float32 tie: decision 280's
    neighbour order)."""
    mesh = Mesh([flat_square(0.15, 0.85, 2.9)], 20)
    values, out, ring = run(export_tests, tmp_path, mesh, "square-odd", 2)
    away = 0
    for r in ring:
        x, y = r["x"], r["y"]
        taps = [(c[0], c[1]) for c in r["candidates"][: r["taps"]]]
        expected_taps, expected = reference(mesh, values, (x, y))
        assert taps == expected_taps, (x, y)
        assert out[y, x].view(np.uint32).tolist() == expected.view(np.uint32).tolist(), (x, y)
        if r["taps"] == 3 and taps[1][0] != taps[2][0]:
            away += taps[1][0] < taps[2][0]
        elif r["taps"] == 3:
            away += taps[1][1] > taps[2][1]
    assert away > 0  # the comparator, not the fixed direction, decided some


@pytest.mark.parametrize("offset", [0.0, 0.3])
def test_seam_ring_reads_the_far_island(export_tests: Path, tmp_path: Path, offset: float) -> None:
    """Two islands A and B, 4 x 4 texels each, sharing a 3D edge (a UV seam). The ring of A
    beyond the seam takes the 4 nearest of its covered neighbours and the far window of B
    (decision 275: B's covered texels in the 3 x 3 block of columns floor(f_u - 1/2) +- 1, rows
    ceil(f_v - 1/2) +- 1 around the ring point f folded into B), equal to `padding_reference` on
    every seam texel: with B aligned (offset 0) each such ring texel copies the B texel at
    distance 0; offset by 0.3 texel it blends far and own taps. Folding B by 90 degrees about the
    edge gives the same ring there (decision 270's unfolding)."""
    s = 1 / 32
    a_uv = [(4 * s, 16 * s), (8 * s, 16 * s), (8 * s, 20 * s), (4 * s, 20 * s)]
    b_uv = [
        (16 * s, (16 + offset) * s),
        (20 * s, (16 + offset) * s),
        (20 * s, (20 + offset) * s),
        (16 * s, (20 + offset) * s),
    ]
    a = ([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)], a_uv)
    flat = Mesh(
        [a, ([(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 0.0, 1.0), (1.0, 0.0, 1.0)], b_uv)], 32
    )
    folded = Mesh(
        [a, ([(1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (1.0, 1.0, 1.0), (1.0, 0.0, 1.0)], b_uv)], 32
    )
    values, out, ring = run(export_tests, tmp_path, flat, f"seam-{offset}", 3)
    _, out_folded, ring_folded = run(export_tests, tmp_path, folded, f"seam-folded-{offset}", 3)
    for name, outcome, texels in (("seam", out, ring), ("seam-folded", out_folded, ring_folded)):
        expected = {
            (x, y): (cands, taps)
            for x, y, cands, taps in Ring(tmp_path / f"{name}-{offset}.obj", "m", 32, 32).texels()
        }
        assert sorted(expected) == sorted((r["x"], r["y"]) for r in texels)
        for r in texels:
            x, y = r["x"], r["y"]
            cands, n = expected[(x, y)]
            assert [(c[0], c[1]) for c in r["candidates"][: r["taps"]]] == [
                c[2] for c in cands[:n]
            ], (name, x, y)
            t = fractions([c[0] for c in cands[:n]])
            chosen = [values[ty, tx] for _, _, (tx, ty) in cands[:n]]
            value = [chain([v[c] for v in chosen], t) for c in range(3)]
            assert (
                outcome[y, x].view(np.uint32).tolist()
                == np.array(value, F32).view(np.uint32).tolist()
            ), (name, x, y)
    seam = [r for r in ring if r["x"] == 8]
    assert len(seam) == 6
    for r in seam:
        x, y = r["x"], r["y"]
        taps = [(c[0], c[1]) for c in r["candidates"][: r["taps"]]]
        assert out_folded[y, x].view(np.uint32).tolist() == out[y, x].view(np.uint32).tolist(), (
            x,
            y,
        )
        if offset == 0.0 and 12 <= y <= 15:
            assert r["taps"] == 1 and taps == [(16, y)] and r["candidates"][0][3] is True
        if offset != 0.0 and 12 <= y <= 15:
            assert r["taps"] == 4 and any(c[3] for c in r["candidates"][:4])
            assert any(not c[3] for c in r["candidates"][:4])


def _matches_reference(
    tmp: Path, name: str, values: np.ndarray, out: np.ndarray, ring: list[dict[str, Any]]
) -> None:
    """UzPainter's ring texels, their taps, values and undecided gate flags equal
    `padding_reference`'s over the OBJ `name`."""
    reference = Ring(tmp / f"{name}.obj", "m", 32, 32)
    expected = {(x, y): (cands, taps) for x, y, cands, taps in reference.texels()}
    assert sorted(expected) == sorted((r["x"], r["y"]) for r in ring), name
    for r in ring:
        x, y = r["x"], r["y"]
        cands, n = expected[(x, y)]
        assert [(c[0], c[1]) for c in r["candidates"][: r["taps"]]] == [c[2] for c in cands[:n]], (
            name,
            x,
            y,
        )
        assert [(c[0], c[1]) for c in r["candidates"]] == [c[2] for c in cands], (name, x, y)
        assert set(r["undecided"]) == reference.undecided[(x, y)], (name, x, y)
        t = fractions([c[0] for c in cands[:n]])
        chosen = [values[ty, tx] for _, _, (tx, ty) in cands[:n]]
        value = [chain([v[c] for v in chosen], t) for c in range(3)]
        assert (
            out[y, x].view(np.uint32).tolist() == np.array(value, F32).view(np.uint32).tolist()
        ), (
            name,
            x,
            y,
        )


def _folded_pair(angle: float, *, wide: bool = False, top: bool = False) -> Mesh:
    """Island A, 4 x 4 texels on the plane y = 0 (face normal -y, its seam line the texel column
    boundary 8), and island B, 4 x 4 texels beyond A's edge x = 1 (its seam line at texel column
    16.25, offset 0.3 texel in v, so that no far point falls on a window boundary), turned about
    that edge by `angle` degrees: positive is concave (B rises on A's normal side), negative convex.
    `wide` widens A by half a texel, so that its seam line passes through the centre of ring texel
    (8, 11); `top` adds a flat island C beyond A's edge z = 1 (rows 4 to 7)."""
    s = 1 / 32
    c, n = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    x0, u0, u1 = (-0.125, 4.5 * s, 8.5 * s) if wide else (0.0, 4 * s, 8 * s)
    a = (
        [(x0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (x0, 0.0, 1.0)],
        [(u0, 16 * s), (u1, 16 * s), (u1, 20 * s), (u0, 20 * s)],
    )
    b = (
        [(1.0, 0.0, 0.0), (1.0 + c, -n, 0.0), (1.0 + c, -n, 1.0), (1.0, 0.0, 1.0)],
        [
            (16.25 * s, 16.3 * s),
            (20.25 * s, 16.3 * s),
            (20.25 * s, 20.3 * s),
            (16.25 * s, 20.3 * s),
        ],
    )
    quads = [a, b]
    if top:
        quads.append(
            (
                [(0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 0.0, 2.0), (0.0, 0.0, 2.0)],
                [(4 * s, 24 * s), (8 * s, 24 * s), (8 * s, 28 * s), (4 * s, 28 * s)],
            )
        )
    return Mesh(quads, 32)


def test_seam_gate_follows_the_fold_and_the_far_plane(export_tests: Path, tmp_path: Path) -> None:
    """Decision 278: a ring texel takes no far taps across a seam edge when the two faces' float32
    unit normals meet at a dot product of at most 0.985 (a fold of about 9.94 degrees) and its ring
    point lies behind the far face's plane. Islands A and B share an edge (`_folded_pair`):
    - folded 9.5 degrees either way, decision 275's far taps stay, on the ring texels beyond each
      island's seam line and on corners on its own side;
    - concave by 10.5 degrees, the texels beyond the seam line (behind the far face) take no far
      candidates, and the own-side corners (in front of it) keep theirs; convex by 10.5, the
      reverse;
    - at 9.935 degrees (normal dot 0.985004, inside Painter's bracket (0.98498905, 0.98501915]),
      the taps are the 0.985 rule's (kept), and the texels whose far taps the bracket decides
      (beyond the seam line when concave, own-side corners when convex) are flagged "fold-bracket";
    - a ring point on the far plane (A half a texel wider, its seam line through the centre of
      ring texel (8, 11)) keeps its far taps and is flagged "on-far-plane";
    - with B concave by 10.5 degrees and a flat island C beyond A's other edge z = 1, a ring texel
      whose taps come across B's gated edge and C's kept one is flagged "mixed-gates", and takes
      C's taps and none of B's.
    Every case equals `padding_reference` bit for bit, candidates and flags included."""
    rings: dict[str, dict[tuple[int, int], dict[str, Any]]] = {}
    for label, angle, wide, top in (
        ("p9.5", 9.5, False, False),
        ("p10.5", 10.5, False, False),
        ("m9.5", -9.5, False, False),
        ("m10.5", -10.5, False, False),
        ("p9.935", 9.935, False, False),
        ("m9.935", -9.935, False, False),
        ("wide-p10.5", 10.5, True, False),
        ("top-p10.5", 10.5, False, True),
    ):
        name = f"gate-{label}"
        values, out, ring = run(
            export_tests, tmp_path, _folded_pair(angle, wide=wide, top=top), name, 278
        )
        _matches_reference(tmp_path, name, values, out, ring)
        rings[label] = {(r["x"], r["y"]): r for r in ring}

    def far_taps(label: str) -> set[tuple[int, int]]:
        return {
            k for k, r in rings[label].items() if any(c[3] for c in r["candidates"][: r["taps"]])
        }

    def far_candidates(label: str) -> set[tuple[int, int]]:
        return {k for k, r in rings[label].items() if any(c[3] for c in r["candidates"])}

    def flagged(label: str, flag: str) -> set[tuple[int, int]]:
        return {k for k, r in rings[label].items() if flag in r["undecided"]}

    def beyond(k: tuple[int, int]) -> bool:
        """Whether ring texel `k`'s centre lies beyond its island's seam line."""
        return k[0] + 0.5 > 8 if k[0] <= 8 else k[0] + 0.5 < 16.25

    for label in ("p9.5", "m9.5"):
        assert {k for k in far_taps(label) if beyond(k)} >= {(8, y) for y in range(12, 16)}, label
        assert any(not beyond(k) for k in far_taps(label)), label
    behind = {"p10.5": True, "m10.5": False}
    for label, ungated in (("p10.5", "p9.5"), ("m10.5", "m9.5")):
        assert not any(beyond(k) == behind[label] for k in far_candidates(label)), label
        assert {k for k in far_taps(ungated) if beyond(k) != behind[label]} <= far_taps(label), (
            label
        )
    for label, ungated, side in (("p9.935", "p9.5", True), ("m9.935", "m9.5", False)):
        assert far_taps(label) == far_taps(ungated), label
        assert flagged(label, "fold-bracket") == {k for k in far_taps(ungated) if beyond(k) == side}
    for label in ("p9.5", "p10.5", "m9.5", "m10.5"):
        assert all(r["undecided"] == [] for r in rings[label].values()), label
    assert flagged("wide-p10.5", "on-far-plane") >= {(8, 11)}
    assert (8, 11) in far_taps("wide-p10.5")
    mixed = flagged("top-p10.5", "mixed-gates")
    assert mixed and mixed <= far_taps("top-p10.5")
    for k in mixed:
        assert all(c[0] < 9 for c in rings["top-p10.5"][k]["candidates"]), k  # none of B's


def _quad(
    x: tuple[float, float],
    u: tuple[float, float],
    rows: tuple[float, float],
    base: float,
    scale: float = 0.25,
) -> Quad:
    """A flat quad on y = 0 over UV columns `u` and rows `rows` (texels, top first), at 3D x in `x`
    and z = (base - row) `scale`."""
    (x0, x1), (u0, u1), (w0, w1) = x, u, rows
    z0, z1 = (base - w1) * scale, (base - w0) * scale
    return (
        [(x0, 0.0, z0), (x1, 0.0, z0), (x1, 0.0, z1), (x0, 0.0, z1)],
        [
            (u0 / 32, 1 - w1 / 32),
            (u1 / 32, 1 - w1 / 32),
            (u1 / 32, 1 - w0 / 32),
            (u0 / 32, 1 - w0 / 32),
        ],
    )


def test_ring_point_neighbours_and_reach_follow_decision_279(
    export_tests: Path, tmp_path: Path
) -> None:
    """Decision 279, against `padding_reference` bit for bit, candidates and flags included:
    - two islands one texel column apart in UV and apart in 3D (A 4 x 4 texels at 1 unit per 4,
      D 4 x 4 at 1.25 per 4, half a texel lower): the ring texels between them take own taps from
      both, the other island's at min(|q_k - P|, |q - P|), and their ring point comes from the
      triangle of the neighbour nearest under decision 273's comparator, which on some of them is
      not the highest-index triangle;
    - a seam edge that ends 1.7768 texels from a ring texel (A's right edge along its upper part,
      shared with B's upper quad), with a collinear seam neighbour to B below it (A's right edge
      along its lower part, shared with B's lower quad, which narrows to x = 1.2 at its bottom, so
      its far window lies two columns right of the upper edge's): the neighbour's strip owns the
      ring texel (8, 15)'s samples, so the run's 1.7768 edge is discovered (decision 339), as in
      decision 285's recorded basis, bevelled-cube-256 (4, 234), whose 1.772004 endpoint edge is
      found through its collinear seam neighbour to the same far island. (8, 15) takes B's texel
      (16, 15) through that edge's window (decision 285's cap, 1.78 texels), and is flagged
      "reach-bracket", since a cap at the bracket's low end, 1.772004 texels, would drop it;
    - the same mesh without A's lower right quad, so the 1.7768 edge is a lone endpoint edge (no
      seam of its run owns a sample of (8, 15)'s 3x3): it is not discovered, (8, 15) takes no far
      candidate and no texel is flagged "reach-bracket", as Painter drops that edge class on the
      recorded window-side texel (28, 82) and 77 more window texels. The rule before decision 339
      (decisions 279 and 285, no strip) discovers it: `padding_reference` at d9d04233's parent
      gives (8, 15) B's far candidates (17, 15) and (16, 15) and flags it "reach-bracket"."""
    from tests.export.padding_reference import Ring

    vgap = Mesh(
        [
            _quad((0.0, 1.0), (4.0, 8.0), (12.0, 16.0), 16.0),
            _quad((3.0, 4.25), (9.0, 13.0), (11.5, 15.5), 15.5, 0.3125),
        ],
        32,
    )
    values, out, ring = run(export_tests, tmp_path, vgap, "vgap", 279)
    _matches_reference(tmp_path, "vgap", values, out, ring)
    reference = Ring(tmp_path / "vgap.obj", "m", 32, 32)
    both = [r for r in ring if {c[0] < 8 for c in r["candidates"][: r["taps"]]} == {True, False}]
    assert both and all(r["triangles"] > 1 for r in both)
    covered = reference.owner >= 0
    switched = 0
    for r in both:
        x, y = r["x"], r["y"]
        own = [
            ((x + dx) % 32, y + dy)
            for dy, dx in NEIGHBOURS
            if 0 <= y + dy < 32 and covered[y + dy, (x + dx) % 32]
        ]
        switched += reference.tau(x, y, own) != max(int(reference.owner[ty, tx]) for tx, ty in own)
    assert switched > 0

    # B's lower quad, its bottom-right corner moved to x = 1.2 and its corners rotated so that the
    # triangle on its left (seam) edge holds that corner.
    p, uv = _quad((1.0, 2.0), (16.25, 20.25), (14.095, 16.3), 16.3)
    narrowed: Quad = ([(1.2, 0.0, 0.0), p[2], p[3], p[0]], [uv[1], uv[2], uv[3], uv[0]])
    reach = Mesh(
        [
            _quad((0.0, 0.875), (4.0, 7.5), (12.0, 13.795), 16.0),
            _quad((0.875, 1.0), (7.5, 8.0), (12.0, 13.795), 16.0),
            _quad((0.0, 0.875), (4.0, 7.5), (13.795, 16.0), 16.0),
            _quad((0.875, 1.0), (7.5, 8.0), (13.795, 16.0), 16.0),
            _quad((1.0, 2.0), (16.25, 20.25), (12.3, 14.095), 16.3),
            narrowed,
        ],
        32,
    )
    values, out, ring = run(export_tests, tmp_path, reach, "reach", 279)
    _matches_reference(tmp_path, "reach", values, out, ring)
    flagged = {(r["x"], r["y"]): r for r in ring if "reach-bracket" in r["undecided"]}
    assert list(flagged) == [(8, 15)]
    assert (16, 15) in [(c[0], c[1]) for c in flagged[(8, 15)]["candidates"] if c[3]]

    lone = Mesh(reach.quads[:3] + reach.quads[4:], 32)
    values, out, ring = run(export_tests, tmp_path, lone, "lone", 279)
    _matches_reference(tmp_path, "lone", values, out, ring)
    assert not [r for r in ring if "reach-bracket" in r["undecided"]]
    texel = next(r for r in ring if (r["x"], r["y"]) == (8, 15))
    assert not [c for c in texel["candidates"] if c[3]]


class Triangles:
    """Single triangles on a W x H tile, each written with its own vertices (the ring welds them by
    value): the OBJ that `run` pads."""

    def __init__(self, triangles: list[Quad], size: int) -> None:
        self.triangles = triangles
        self.size = size

    def obj(self, path: Path) -> Path:
        lines = ["usemtl m"]
        for p, uv in self.triangles:
            lines += [f"v {float(F32(a))!r} {float(F32(b))!r} {float(F32(c))!r}" for a, b, c in p]
            lines += [f"vt {float(F32(u))!r} {float(F32(v))!r}" for u, v in uv]
        for i in range(len(self.triangles)):
            b = 3 * i
            lines.append(f"f {b + 1}/{b + 1} {b + 2}/{b + 2} {b + 3}/{b + 3}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


def _fan(last_centre_x: float) -> Triangles:
    """Three triangles around a raised centre at UV (1/2, 1/2), spanning 0 to 100, 100 to 200 and
    200 to 300 degrees: one island with a V-gap between its first and last triangles. The last
    triangle writes the centre's x as `last_centre_x` (0.0 or -0.0), the others as 0.0."""
    rim = [math.radians(a) for a in (0, 100, 200, 300)]
    tris: list[Quad] = []
    for i in range(3):
        a, b = rim[i], rim[i + 1]
        tris.append(
            (
                [
                    (last_centre_x if i == 2 else 0.0, 0.3, 0.0),
                    (math.cos(a), 0.0, math.sin(a)),
                    (math.cos(b), 0.0, math.sin(b)),
                ],
                [
                    (0.5, 0.5),
                    (0.5 + 0.25 * math.cos(a), 0.5 + 0.25 * math.sin(a)),
                    (0.5 + 0.25 * math.cos(b), 0.5 + 0.25 * math.sin(b)),
                ],
            )
        )
    return Triangles(tris, 32)


def test_own_tap_across_a_uv_edge_is_measured_through_its_triangle(
    export_tests: Path, tmp_path: Path
) -> None:
    """Decision 285: on a quad folded about its diagonal (two faces of one island sharing that UV
    edge), an own tap in the triangle K that is not tau is at |q_K - P|, the ring texel's centre
    extrapolated through K, not at its distance unfolded into tau's face (which differs on some).
    Against `padding_reference` bit for bit, candidates and flags included."""
    s = 1 / 32
    folded = Mesh(
        [
            (
                [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.4, 1.0)],
                [(8 * s, 12 * s), (20 * s, 12 * s), (20 * s, 24 * s), (8 * s, 24 * s)],
            )
        ],
        32,
    )
    values, out, ring = run(export_tests, tmp_path, folded, "folded", 285)
    _matches_reference(tmp_path, "folded", values, out, ring)
    reference = Ring(tmp_path / "folded.obj", "m", 32, 32)
    covered = reference.owner >= 0
    checked = differing = 0
    for r in ring:
        x, y = r["x"], r["y"]
        own = [
            ((x + dx) % 32, y + dy)
            for dy, dx in NEIGHBOURS
            if 0 <= y + dy < 32 and covered[y + dy, (x + dx) % 32]
        ]
        tau = reference.tau(x, y, own)
        T = reference.tris[tau]
        q = T.point(T.bary(x + 0.5, y + 0.5))
        for tx, ty, d, far in r["candidates"][: r["taps"]]:
            k = int(reference.owner[ty, tx])
            if far or k == tau:
                continue
            K = reference.tris[k]
            assert K.face != T.face and len(set(K.corner) & set(T.corner)) == 2
            p = K.point(K.bary(tx + 0.5, ty + 0.5))
            through = float(np.linalg.norm(np.subtract(K.point(K.bary(x + 0.5, y + 0.5)), p)))
            unfolded = float(np.linalg.norm(np.subtract(q, reference.frame(p, k, tau, q))))
            assert math.isclose(d, through, rel_tol=1e-12), (x, y, tx, ty)
            checked += 1
            differing += abs(through - unfolded) > 1e-6 * through
    assert checked > 0 and differing > 0, (checked, differing)


def test_vertices_weld_by_value(export_tests: Path, tmp_path: Path) -> None:
    """Decision 288: a fan whose last triangle writes the shared centre as x = -0.0 is one island,
    padded exactly as the same fan written with 0.0 everywhere (bit for bit, ring candidates
    included), and equal to `padding_reference`."""
    _, out_zero, ring_zero = run(export_tests, tmp_path, _fan(0.0), "fan-zero", 288)
    values, out_signed, ring_signed = run(export_tests, tmp_path, _fan(-0.0), "fan-signed", 288)
    assert "v -0.0 0.30000001192092896 0.0" in (tmp_path / "fan-signed.obj").read_text()
    _matches_reference(tmp_path, "fan-signed", values, out_signed, ring_signed)
    assert ring_signed == ring_zero
    assert out_signed.view(np.uint32).tolist() == out_zero.view(np.uint32).tolist()
    reference = Ring(tmp_path / "fan-signed.obj", "m", 32, 32)
    assert len({t.chart for t in reference.tris}) == 1


def _flood(seed: np.ndarray, clamp: bool) -> tuple[np.ndarray, np.ndarray]:
    """Decision 197's jump flood over `seed` (rows top first): each texel's seed (row, column),
    reads outside the tile clamped to its edge (decision 285) or skipped (decision 197)."""
    height, width = seed.shape
    ys, xs = np.mgrid[0:height, 0:width]
    sy, sx = np.where(seed, ys, -1), np.where(seed, xs, -1)
    big = np.iinfo(np.int64).max
    k = max(width, height) // 2
    while k >= 1:
        by, bx = sy.copy(), sx.copy()
        best = np.where(by >= 0, (by - ys) ** 2 + (bx - xs) ** 2, big)
        for dy, dx in FLOOD:
            rows, cols = np.arange(height) + dy * k, np.arange(width) + dx * k
            cy = sy[np.clip(rows, 0, height - 1)][:, np.clip(cols, 0, width - 1)]
            cx = sx[np.clip(rows, 0, height - 1)][:, np.clip(cols, 0, width - 1)]
            if not clamp:
                inside = ((rows >= 0) & (rows < height))[:, None] & ((cols >= 0) & (cols < width))
                cy, cx = np.where(inside, cy, -1), np.where(inside, cx, -1)
            d = np.where(cy >= 0, (cy - ys) ** 2 + (cx - xs) ** 2, big)
            better = d < best
            by, bx = np.where(better, cy, by), np.where(better, cx, bx)
            best = np.where(better, d, best)
        sy, sx = by, bx
        k //= 2
    return sy, sx


def test_gutter_flood_clamps_reads_to_the_tile_edge(export_tests: Path, tmp_path: Path) -> None:
    """Decision 285: the gutter's jump flood reads a neighbour outside the tile at the nearest edge
    texel and takes its seed, where decision 197 skipped the read. Two rectangular islands (columns
    23 to 25, rows 10 to 14; columns 16 and 17, rows 22 to 26): some gutter texels find a strictly
    nearer seed through a clamped read, every gutter texel copies its clamped flood seed, and the
    whole tile equals `padding_reference.padding` bit for bit."""
    from tests.export.padding_reference import padding

    mesh = Mesh(
        [
            _quad((0.0, 0.75), (23.0, 26.0), (10.0, 15.0), 16.0),
            _quad((2.0, 2.5), (16.0, 18.0), (22.0, 27.0), 28.0),
        ],
        32,
    )
    values, out, ring = run(export_tests, tmp_path, mesh, "flood", 285)
    expected = padding(values, tmp_path / "flood.obj", "m")
    assert out.view(np.uint32).tolist() == expected.view(np.uint32).tolist()
    seed = mesh.owner >= 0
    for r in ring:
        seed[r["y"], r["x"]] = True
    (cy, cx), (sy, sx) = _flood(seed, True), _flood(seed, False)
    ys, xs = np.nonzero(~seed)
    nearer = (cy[ys, xs] - ys) ** 2 + (cx[ys, xs] - xs) ** 2 < (sy[ys, xs] - ys) ** 2 + (
        sx[ys, xs] - xs
    ) ** 2
    assert nearer.any()
    assert np.array_equal(out[ys, xs].view(np.uint32), out[cy[ys, xs], cx[ys, xs]].view(np.uint32))


def _source_table(path: str, name: str) -> list[int]:
    """The integer table `name` of the C++ source `path` (repo root relative)."""
    text = (Path(__file__).resolve().parents[2] / path).read_text(encoding="utf-8")
    body = text[text.index(name) :]
    body = body[body.index("{") + 1 : body.index("};")]
    return [int(x.rstrip("uU"), 0) for x in re.findall(r"0x[0-9A-Fa-f]+u?|\d+u?", body)]


def _unorm_write(v: np.ndarray, bits: int) -> np.ndarray:
    """arith::WriteUnorm: v clamped to [0, 1], j = floor(v 2^(n+4)), then
    (j (2^n - 1) + 2^(n+3) - 1) >> (n+4)."""
    c = np.clip(np.nan_to_num(v.astype(F32)), 0, 1).astype(F32)
    j = (c * F32(1 << (bits + 4))).astype(np.int64)
    return (j * ((1 << bits) - 1) + (1 << (bits + 3)) - 1) >> (bits + 4)


def _half_toward_zero(v: np.ndarray) -> np.ndarray:
    h = v.astype(np.float16)
    over = np.abs(h.astype(F32)) > np.abs(v)
    h[over] = np.nextafter(h[over], np.float16(0))
    return h.astype(F32)


@pytest.mark.parametrize("domain", ["L8", "sRGB8-ocio", "L16F-height"])
def test_padding_runs_in_the_document_format(
    export_tests: Path, tmp_path: Path, domain: str
) -> None:
    """Decision 274: a documentMap channel is padded on its document operands, each filled texel
    stored as its format stores it (L8: the 8-bit UNORM write; sRGB8: the GPU's float-to-sRGB8
    conversion; L16F: the half toward zero) and then written as the file writes the channel (PNG
    16: the UNORM write, the OCIO sRGB8 code table, a Height's v * 0.5 + 0.5). Synthetic codes over
    two islands sharing a seam: `process` with `document_format` equals `ring`'s padding of the
    operands passed through that store and write on every texel; the same codes padded as UNORM
    operands of the file's codes (decision 223's domain) differ from it."""
    s = 1 / 32
    a = (
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)],
        [(4 * s, 16 * s), (8 * s, 16 * s), (8 * s, 20 * s), (4 * s, 20 * s)],
    )
    b = (
        [(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 0.0, 1.0), (1.0, 0.0, 1.0)],
        [(16 * s, 16.3 * s), (20 * s, 16.3 * s), (20 * s, 20.3 * s), (16 * s, 20.3 * s)],
    )
    mesh = Mesh([a, b], 32)
    rng = np.random.default_rng(274)
    channels = 3 if domain == "sRGB8-ocio" else 1
    shape = (32, 32, channels)
    case: dict[str, Any] = {"format": "png", "bit_depth": "16"}
    if domain == "L8":
        k = rng.integers(0, 256, shape)
        operands = (k / 255.0).astype(F32)
        codes = k * 257

        def store_and_write(p: np.ndarray) -> np.ndarray:
            return _unorm_write(p, 8) * 257

        case["document_format"] = "L8"
    elif domain == "sRGB8-ocio":
        arith = "src/evaluator/arith.cpp"
        decode = np.array(_source_table(arith, "kSrgb8DecodeBits[256]"), np.uint32).view(F32)
        thresholds = np.array(_source_table(arith, "kSrgb8ThresholdBits[255]"), np.uint32)
        thresholds = thresholds.view(F32).astype(np.float64)
        table = np.array(_source_table("src/export/encode.cpp", "kOcioSrgbPng16[256]"), np.int64)
        k = rng.integers(0, 256, shape)
        operands = decode[k]
        codes = table[k]

        def store_and_write(p: np.ndarray) -> np.ndarray:
            c = np.clip(np.nan_to_num(p.astype(F32)), 0, 1).astype(np.float64)
            return table[np.searchsorted(thresholds, c, side="right")]

        case.update(document_format="sRGB8", srgb8_material=True, ocio=True)
    else:
        operands = _half_toward_zero(rng.uniform(0.5, 1.0, shape).astype(F32))
        codes = _unorm_write((operands * F32(0.5) + F32(0.5)).astype(F32), 16)

        def store_and_write(p: np.ndarray) -> np.ndarray:
            return _unorm_write((_half_toward_zero(p) * F32(0.5) + F32(0.5)).astype(F32), 16)

        case.update(document_format="L16F", height=True)
    obj = mesh.obj(tmp_path / "mesh.obj")
    (tmp_path / "operands.f32").write_bytes(operands.astype(F32).tobytes())
    ring_case = {
        "mesh": str(obj),
        "material": "m",
        "width": 32,
        "height": 32,
        "channels": channels,
        "values": str(tmp_path / "operands.f32"),
        "out": str(tmp_path / "padded.f32"),
    }
    (tmp_path / "ring.json").write_text(json.dumps([ring_case]), encoding="utf-8")
    proc = subprocess.run(
        [str(export_tests), "ring", str(tmp_path / "ring.json")],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    padded = np.frombuffer((tmp_path / "padded.f32").read_bytes(), F32).reshape(shape)
    covered = mesh.owner >= 0
    expected = np.where(covered[..., None], codes, store_and_write(padded))

    source = tmp_path / "source.png"
    png.write(source, codes.astype(np.int64), 16)
    common = {"source": str(source), "target": str(source), "mesh": str(obj), "material": "m"}
    cases = [
        dict(case, **common, out=str(tmp_path / "document.png")),
        {
            **common,
            "format": "png",
            "bit_depth": "16",
            "out": str(tmp_path / "codes.png"),
            **({"height": True} if domain == "L16F-height" else {}),
        },
    ]
    (tmp_path / "process.json").write_text(json.dumps(cases), encoding="utf-8")
    proc = subprocess.run(
        [str(export_tests), "process", str(tmp_path / "process.json")],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    document = png.read(tmp_path / "document.png").astype(np.int64).reshape(shape)
    by_codes = png.read(tmp_path / "codes.png").astype(np.int64).reshape(shape)
    assert 0 < covered.sum() < covered.size
    assert np.array_equal(document, expected)
    assert not np.array_equal(by_codes[~covered], expected[~covered])


def test_far_ties_follow_the_window_order_and_all_far_lists_are_not_copies(
    export_tests: Path, tmp_path: Path
) -> None:
    """Decision 280, against `padding_reference` bit for bit, candidates and flags included: island
    A (4 x 4 texels, a quarter unit each) and island B beyond its edge x = 1 (16 x 16 texels, a
    sixteenth each) share that edge. A's ring texels beyond the seam fold into B two B texels from
    its edge, on a B texel corner: the 4 texels of the window's 2 x 2 block tie exactly (float32
    |q_E - P| included) and are taken in the window order (0, 0), (+1, 0), (0, +1), (+1, +1) from
    the base (floor(f_u - 1/2), ceil(f_v - 1/2)), v up, not toward +u, +v; and the 8 kept candidates
    are all far texels, which no longer makes the chain a copy (finding 4)."""
    mesh = Mesh(
        [
            _quad((0.0, 1.0), (1.0, 5.0), (12.0, 16.0), 16.0),
            _quad((1.0, 2.0), (8.0, 24.0), (0.0, 16.0), 16.0, 1 / 16),
        ],
        32,
    )
    values, out, ring = run(export_tests, tmp_path, mesh, "far-ties", 280)
    _matches_reference(tmp_path, "far-ties", values, out, ring)
    seam = {r["y"]: r for r in ring if r["x"] == 5 and 12 <= r["y"] <= 15}
    assert sorted(seam) == [12, 13, 14, 15]
    for y, r in seam.items():
        assert len(r["candidates"]) == 8 and all(c[3] for c in r["candidates"]), y
        assert r["taps"] == 4, y
        row = 4 * y - 46
        assert [(c[0], c[1]) for c in r["candidates"][:4]] == [
            (9, row),
            (10, row),
            (9, row - 1),
            (10, row - 1),
        ], y
        assert r["undecided"] == [], y


def test_own_ties_follow_the_neighbour_order(export_tests: Path, tmp_path: Path) -> None:
    """Decision 280: at the inner corner of an L-shaped island, ring texel (8, 11) ties its side
    along u (-1, 0) and its side along v (0, -1) exactly: the side along u comes first, where
    toward +u, +v took the other. Its tied diagonals hold the open pair (+1, -1) / (-1, +1), which
    is flagged "own-order". Equal to `padding_reference` bit for bit, flags included."""
    mesh = Mesh(
        [
            _quad((1.0, 2.0), (4.0, 8.0), (8.0, 12.0), 16.0),
            _quad((1.0, 2.0), (4.0, 8.0), (12.0, 16.0), 16.0),
            _quad((2.0, 3.0), (8.0, 12.0), (12.0, 16.0), 16.0),
        ],
        32,
    )
    values, out, ring = run(export_tests, tmp_path, mesh, "own-ties", 280)
    _matches_reference(tmp_path, "own-ties", values, out, ring)
    corner = next(r for r in ring if (r["x"], r["y"]) == (8, 11))
    assert [(c[0], c[1]) for c in corner["candidates"][:2]] == [(7, 11), (8, 12)]
    assert corner["taps"] == 4
    assert "own-order" in corner["undecided"]


def test_coverage_snaps_vertices_to_a_256th_of_a_texel(export_tests: Path, tmp_path: Path) -> None:
    """Decision 281: a texel centre 1/1000 texel outside an island's edge is covered (the edge
    snaps onto it), one 3/1000 texel outside is not, in UzPainter's coverage, `padding_reference`'s
    and tools/parity/coverage's alike."""
    from tools.parity.coverage import coverage, obj_triangles

    mesh = Mesh(
        [
            _quad((1.0, 2.12475), (4.0, 8.499), (12.0, 16.0), 16.0),
            _quad((1.0, 2.12425), (4.0, 8.497), (20.0, 24.0), 16.0),
        ],
        32,
    )
    values, out, ring = run(export_tests, tmp_path, mesh, "snap", 281)
    _matches_reference(tmp_path, "snap", values, out, ring)
    reference = Ring(tmp_path / "snap.obj", "m", 32, 32)
    covered = coverage(obj_triangles(tmp_path / "snap.obj", "m"), 32, 32)
    assert np.array_equal(covered, reference.owner >= 0)
    assert np.array_equal(covered, mesh.owner >= 0)
    assert covered[12:16, 8].all() and not covered[12:16, 9].any()
    assert not covered[20:24, 8].any()
    ring_texels = {(r["x"], r["y"]) for r in ring}
    assert {(9, y) for y in range(12, 16)} <= ring_texels
    assert {(8, y) for y in range(20, 24)} <= ring_texels


def _own(reference: Ring, x: int, y: int) -> list[tuple[int, int]]:
    """Ring texel (x, y)'s covered 8-neighbours (x wraps)."""
    covered = reference.owner >= 0
    return [
        ((x + dx) % 32, y + dy)
        for dy, dx in NEIGHBOURS
        if 0 <= y + dy < 32 and covered[y + dy, (x + dx) % 32]
    ]


def test_shallow_hinge_is_not_unfolded(export_tests: Path, tmp_path: Path) -> None:
    """Decision 282: a far tap across a hinge is rotated into tau's plane only when the two faces'
    float32 unit normals meet at a dot product of at most 0.985. Islands A and B of `_folded_pair`,
    folded convex by 9.9 degrees (dot 0.98511) and by 10.0 degrees (dot 0.98481): on the ring
    texels beyond A's seam line, each far chain tap is at its raw 3D distance |q - P| at 9.9
    degrees and at its unfolded one at 10.0 degrees, which differ. Against `padding_reference` bit
    for bit, candidates and flags included."""
    for label, angle, unfolded in (("m9.9", -9.9, False), ("m10.0", -10.0, True)):
        name = f"hinge-{label}"
        values, out, ring = run(export_tests, tmp_path, _folded_pair(angle), name, 282)
        _matches_reference(tmp_path, name, values, out, ring)
        reference = Ring(tmp_path / f"{name}.obj", "m", 32, 32)
        assert reference.folded(0, 2) == unfolded, label
        checked = 0
        for r in ring:
            x, y = r["x"], r["y"]
            if x != 8:
                continue
            T = reference.tris[reference.tau(x, y, _own(reference, x, y))]
            q = T.point(T.bary(x + 0.5, y + 0.5))
            for tx, ty, d, far in r["candidates"][: r["taps"]]:
                if not far:
                    continue
                K = reference.tris[int(reference.owner[ty, tx])]
                p = K.point(K.bary(tx + 0.5, ty + 0.5))
                h = reference._hinge(T.face, K.face)
                assert h is not None
                raw = float(np.linalg.norm(np.subtract(q, p)))
                rotated = float(np.linalg.norm(np.subtract(q, unfold(h[1], p))))
                assert abs(raw - rotated) > 1e-6 * raw, (label, x, y, tx, ty)
                assert math.isclose(d, rotated if unfolded else raw, rel_tol=1e-12), (label, x, y)
                checked += 1
        assert checked > 0, label


def _flat_pair(a_u: float, b_dv: float) -> Mesh:
    """Islands A (4 x 4 texels from texel column `a_u`, rows 12 to 15, on the plane y = 0 at 3D
    x in [0, 1]) and B (4 x 4 texels from column 16.25, `b_dv` texel lower, flat beyond A's 3D
    edge x = 0, at x in [-1, 0]): a UV seam between A's left edge and B's right edge."""
    s = 1 / 32
    a = (
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)],
        [(a_u * s, 16 * s), ((a_u + 4) * s, 16 * s), ((a_u + 4) * s, 20 * s), (a_u * s, 20 * s)],
    )
    b0, b1 = (16 - b_dv) * s, (20 - b_dv) * s
    b = (
        [(-1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (-1.0, 0.0, 1.0)],
        [(16.25 * s, b0), (20.25 * s, b0), (20.25 * s, b1), (16.25 * s, b1)],
    )
    return Mesh([a, b], 32)


def test_seam_edge_on_the_tile_border_opens_no_window(export_tests: Path, tmp_path: Path) -> None:
    """Decision 290: a seam edge whose two UV ends both lie on u = 0 opens no window. With A's seam
    edge on the tile's left border, no ring texel of A takes a far tap of B, not even (0, 11)
    above the edge's upper end, 0.71 texel from it, whose ring point folds across the edge to
    within B's window, while B's own seam edge, inside the tile, still opens A's window to B's
    ring texels. With A one texel to the right, the same ring texel (1, 11) and the ring texels
    of column 0 take B's far taps. Against `padding_reference` bit for bit, candidates and flags
    included."""
    for name, a_u in (("border", 0.0), ("inside", 1.0)):
        values, out, ring = run(export_tests, tmp_path, _flat_pair(a_u, 0.3), name, 290)
        _matches_reference(tmp_path, name, values, out, ring)
        of_a = {
            (r["x"], r["y"]): r for r in ring if all(c[0] < 8 for c in r["candidates"] if not c[3])
        }
        assert (int(a_u), 11) in of_a, name
        reaching = {k for k, r in of_a.items() if any(c[3] for c in r["candidates"])}
        if name == "border":
            assert reaching == set()
        else:
            assert {(1, 11)} | {(0, y) for y in range(11, 16)} <= reaching
        b_side = [r for r in ring if r["x"] == 20 and 12 <= r["y"] <= 15]
        assert len(b_side) == 4 and all(any(c[3] for c in r["candidates"]) for r in b_side), name


def _pole_fan(segments: int) -> Triangles:
    """A pyramid's apex fan of `segments` quarter turns over a band of quads, one UV island laid
    out as a strip: each apex triangle has its own apex UV (V-gaps between them, joined in UV
    through the band below, as on a sphere's pole), so neighbouring apex triangles share their
    spoke in 3D across a UV seam inside the island."""
    w, rim, low, top = 0.2, 0.6, 0.35, 0.85
    tris: list[Quad] = []
    for i in range(segments):
        a, b = math.radians(90 * i), math.radians(90 * (i + 1))
        r0, r1 = (math.cos(a), 0.5, math.sin(a)), (math.cos(b), 0.5, math.sin(b))
        l0, l1 = (math.cos(a), 0.0, math.sin(a)), (math.cos(b), 0.0, math.sin(b))
        u0, u1 = 0.1 + w * i, 0.1 + w * (i + 1)
        tris.append(([l0, l1, r1], [(u0, low), (u1, low), (u1, rim)]))
        tris.append(([l0, r1, r0], [(u0, low), (u1, rim), (u0, rim)]))
        tris.append(([r0, r1, (0.0, 1.0, 0.0)], [(u0, rim), (u1, rim), ((u0 + u1) / 2, top)]))
    return Triangles(tris, 32)


def test_seam_edge_folding_back_into_tau_opens_no_window(
    export_tests: Path, tmp_path: Path
) -> None:
    """Decision 288: a seam edge whose far triangle is the ring texel's own triangle tau opens no
    window. In the V-gaps of `_pole_fan`, ring texels reach the neighbouring apex triangle's
    spoke, whose far triangle is tau, and take no far tap in tau. Against `padding_reference` bit
    for bit, candidates and flags included."""
    values, out, ring = run(export_tests, tmp_path, _pole_fan(3), "pole-fan", 288)
    _matches_reference(tmp_path, "pole-fan", values, out, ring)
    reference = Ring(tmp_path / "pole-fan.obj", "m", 32, 32)
    assert len({t.chart for t in reference.tris}) == 1
    reached = 0
    for r in ring:
        x, y = r["x"], r["y"]
        tau = reference.tau(x, y, _own(reference, x, y))
        tris = reference.tris
        if any(
            j == tau
            and segment_distance(tris[e].t[(k + 1) % 3], tris[e].t[(k + 2) % 3], x + 0.5, y + 0.5)
            <= REACH_CAP
            for e, k, j in reference.seams.get(tris[tau].chart, [])
        ):
            reached += 1
            owners = {int(reference.owner[c[1], c[0]]) for c in r["candidates"] if c[3]}
            assert tau not in owners, (x, y)
    assert reached > 0


def test_far_point_on_a_window_boundary_is_flagged(export_tests: Path, tmp_path: Path) -> None:
    """Decision 291: a ring texel whose far point f lies within 1e-4 texel of a window boundary
    (f_v - 1/2 integral: B's rows aligned with A's), where the window on the other side gives
    another chain, is flagged "window-side"; its taps stay those of the window based at
    (floor(f_u - 1/2), ceil(f_v - 1/2)). With B 0.3 texel lower no far point is near a boundary,
    and none is flagged. Against `padding_reference` bit for bit, candidates and flags included."""
    flagged: dict[str, set[tuple[int, int]]] = {}
    for name, dv in (("aligned", 0.0), ("offset", 0.3)):
        values, out, ring = run(export_tests, tmp_path, _flat_pair(1.0, dv), name, 291)
        _matches_reference(tmp_path, name, values, out, ring)
        flagged[name] = {(r["x"], r["y"]) for r in ring if "window-side" in r["undecided"]}
        far = {(r["x"], r["y"]) for r in ring if any(c[3] for c in r["candidates"])}
        assert flagged[name] <= far, name
    assert flagged["offset"] == set()
    assert {(0, y) for y in range(13, 16)} <= flagged["aligned"]


def _corner(vrow: float, bend: float, fold: float) -> Mesh:
    """Island A: A1 (texel columns 4 to 8, rows `vrow` to 16, on the plane y = 0) and A2 above it
    (rows 8 to `vrow`, its right edge from (8, vrow) to (8 + `bend`, 8)), turned 5 degrees about
    their shared edge: two planar faces meeting at A's UV corner V = (8, vrow). Island B1 (columns
    16 to 20, 0.3 row lower) beyond A1's right edge, turned concave by `fold` degrees about it;
    island B (columns 24 to 28, rows 8 to 16) beyond A2's right edge, in A2's plane. A quarter unit
    per texel."""
    s = 1 / 32
    h = (16 - vrow) * 0.25
    sa, ca = math.sin(math.radians(5.0)), math.cos(math.radians(5.0))
    sb, cb = math.sin(math.radians(fold)), math.cos(math.radians(fold))

    def a1(col: float, row: float) -> tuple[float, float, float]:
        return ((col - 4) * 0.25, 0.0, (16 - row) * 0.25)

    def a2(col: float, row: float) -> tuple[float, float, float]:
        d = (vrow - row) * 0.25
        return ((col - 4) * 0.25, d * sa, h + d * ca)

    def b1(col: float, row: float) -> tuple[float, float, float]:
        w = (col - 16) * 0.25
        return (1.0 + w * cb, -w * sb, (16.3 - row) * 0.25)

    def b(col: float, row: float) -> tuple[float, float, float]:
        d = (vrow - row) * 0.25
        return (1.0 + (col - 24) * 0.25, d * sa, h + d * ca)

    def quad(f: Any, corners: list[tuple[float, float]]) -> Quad:
        return [f(c, r) for c, r in corners], [(c * s, 1 - r * s) for c, r in corners]

    return Mesh(
        [
            quad(a1, [(4, 16), (8, 16), (8, vrow), (4, vrow)]),
            quad(a2, [(4, vrow), (8, vrow), (8 + bend, 8), (4, 8)]),
            quad(b1, [(16, 16.3), (20, 16.3), (20, vrow + 0.3), (16, vrow + 0.3)]),
            quad(b, [(24, vrow), (28, vrow), (28, 8), (24 + bend, 8)]),
            quad(b, [(24, 16), (28, 16), (28, vrow), (24, vrow)]),
        ],
        32,
    )


def test_corner_edge_reach_uses_raster_strip(export_tests: Path, tmp_path: Path) -> None:
    """A corner participates when its seam owns a sample in the 3x3 lookup.

    The bend at row 12.52 reaches B even with the other seam gated. At row 12.2,
    both bent and collinear variants miss B's strip; analytic endpoint caps no
    longer decide eligibility. Native candidates and diagnostic flags must agree
    with the independent reference for the whole tile.
    """
    cases = {
        "gated": (12.52, 1.0, 30.0),
        "bracket": (12.52, 1.0, 0.0),
        "open": (12.2, 1.0, 0.0),
        "collinear": (12.2, 0.0, 0.0),
    }
    for label, (vrow, bend, fold) in cases.items():
        name = f"corner-{label}"
        values, out, ring = run(export_tests, tmp_path, _corner(vrow, bend, fold), name, 294)
        _matches_reference(tmp_path, name, values, out, ring)
        texel = next(r for r in ring if (r["x"], r["y"]) == (8, 13))
        has_b = any(c[0] >= 24 for c in texel["candidates"][: texel["taps"]])
        assert has_b == (label in {"gated", "bracket"})


def test_seam_strip_last_draw_owns_uncovered_samples(tmp_path: Path) -> None:
    """Overlapping seam IDs obey draw order even without covered texels."""
    mesh = _corner(12.52, 1.0, 0.0)
    ring = Ring(mesh.obj(tmp_path / "strip.obj"), "m", 32, 32)
    chart, seams = next(iter(ring.seams.items()))
    e, edge, j = seams[0]
    triangle = ring.tris[e]
    a, b = triangle.t[(edge + 1) % 3], triangle.t[(edge + 2) % 3]
    x, y = math.floor((a[0] + b[0]) / 2), math.floor((a[1] + b[1]) / 2)
    first, last = (e, edge, j), (e, edge, j + 1)
    ring.owner[:] = -1
    ring.seams[chart] = [first, last]
    assert ring.strip_winners(chart, x, y) == {last}
    ring.seams[chart] = [last, first]
    assert ring.strip_winners(chart, x, y) == {first}


def test_own_comparator_keeps_tau_and_far_roles_separate(
    export_tests: Path, tmp_path: Path
) -> None:
    """Own-order correction must not leak its fused determinant into tau or far ordering."""
    mesh = (
        Path(__file__).resolve().parents[2]
        / "parity/fixtures/tier0-semantics/meshes/corner-reach.obj"
    )
    expected = {
        (34, 38): [(33, 38), (34, 37), (33, 39), (33, 37)],
        (185, 37): [(173, 36), (172, 37), (186, 37), (185, 38)],
        (266, 104): [(260, 103), (259, 104), (266, 105), (267, 104)],
    }
    values = np.random.default_rng(303).random((512, 512, 3)).astype(F32)
    raw, result = tmp_path / "values.f32", tmp_path / "result.f32"
    raw.write_bytes(values.tobytes())
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            [
                dict(
                    mesh=str(mesh),
                    material="uzp_corner",
                    width=512,
                    height=512,
                    channels=3,
                    values=str(raw),
                    out=str(result),
                )
            ]
        )
    )
    process = subprocess.run(
        [str(export_tests), "ring", str(cases)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    native = {(r["x"], r["y"]): r for r in json.loads(process.stdout)["ring"]}
    reference = Ring(mesh, "uzp_corner", 512, 512)
    for (x, y), taps in expected.items():
        own = [
            ((x + dx) % 512, y + dy)
            for dy, dx in NEIGHBOURS
            if 0 <= y + dy < 512 and reference.owner[y + dy, (x + dx) % 512] >= 0
        ]
        tau = reference.tau(x, y, own)
        if (x, y) == (185, 37):
            assert tau == 148
        candidates, _ = reference.candidates(x, y, own, tau)
        assert [c[2] for c in candidates[:4]] == taps
        assert [tuple(c[:2]) for c in native[(x, y)]["candidates"][:4]] == taps


def test_far_tap_keeps_its_own_chart_rigid(export_tests: Path, tmp_path: Path) -> None:
    """Decision 342: a far tap reached along a face path is not rotated about the hinges inside
    its own chart; the seam hinge and the hinges in tau's chart keep decision 282's gate. On the
    hinge-far fixture (512 x 512), ring texels (20, 27) and (20, 60) take two far taps each from a
    far chart folded past the gate one and two hinges beyond its flat seam hinge. Each far tap's
    distance is |q - P| with P as is (all of the path's hinges are in the far chart or ungated),
    and differs from the development that unfolds every gated hinge (decision 282 alone).
    UzPainter's taps, their distances and the ring values equal `padding_reference`'s."""
    mesh = (
        Path(__file__).resolve().parents[2] / "parity/fixtures/tier0-semantics/meshes/hinge-far.obj"
    )
    size = 512
    values = np.random.default_rng(342).random((size, size, 3)).astype(F32)
    raw, result = tmp_path / "values.f32", tmp_path / "result.f32"
    raw.write_bytes(values.tobytes())
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            [
                dict(
                    mesh=str(mesh),
                    material="uzp_hinge",
                    width=size,
                    height=size,
                    channels=3,
                    values=str(raw),
                    out=str(result),
                )
            ]
        )
    )
    process = subprocess.run(
        [str(export_tests), "ring", str(cases)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    native = {(r["x"], r["y"]): r for r in json.loads(process.stdout)["ring"]}
    out = np.frombuffer(result.read_bytes(), F32).reshape(size, size, 3)
    reference = Ring(mesh, "uzp_hinge", size, size)
    tris = reference.tris
    for x, y, depth in ((20, 27, 1), (20, 60, 2)):
        own = [
            ((x + dx) % size, y + dy)
            for dy, dx in NEIGHBOURS
            if 0 <= y + dy < size and reference.owner[y + dy, (x + dx) % size] >= 0
        ]
        tau = reference.tau(x, y, own)
        cands, _ = reference.candidates(x, y, own, tau)
        n = tap_count(cands)
        r = native[(x, y)]
        assert r["taps"] == n == 4, (x, y)
        assert [tuple(c[:2]) for c in r["candidates"][:n]] == [c[2] for c in cands[:n]], (x, y)
        T = tris[tau]
        q = T.point(T.bary(x + 0.5, y + 0.5))
        far = 0
        for (tx, ty, d, is_far), c in zip(r["candidates"][:n], cands[:n], strict=True):
            assert math.isclose(d, c[0], rel_tol=1e-12), (x, y, tx, ty)
            if not is_far:
                continue
            k = int(reference.owner[ty, tx])
            K = tris[k]
            assert K.chart != T.chart and reference._hinge(T.face, K.face) is None
            (path,) = reference._paths(K.face, T.face)
            links = [reference.links[b][a] for a, b in itertools.pairwise(path)]
            inside = [(i, j) for i, j, _, _ in links if tris[i].chart == K.chart == tris[j].chart]
            assert len(inside) == depth and all(reference.folded(i, j) for i, j in inside)
            p = K.point(K.bary(tx + 0.5, ty + 0.5))
            developed = p
            for i, j, va, vb in links:
                if reference.folded(i, j):
                    developed = unfold(hinge(tris[i], tris[j], va, vb), developed)
            rigid = float(np.linalg.norm(np.subtract(q, p)))
            unfolded = float(np.linalg.norm(np.subtract(q, developed)))
            assert math.isclose(d, rigid, rel_tol=1e-12), (x, y, tx, ty)
            assert abs(rigid - unfolded) > 1e-4 * rigid, (x, y, tx, ty)
            far += 1
        assert far == 2, (x, y)
        t = fractions([c[0] for c in cands[:n]])
        chosen = [values[ty, tx] for _, _, (tx, ty) in cands[:n]]
        value = [chain([v[c] for v in chosen], t) for c in range(3)]
        assert out[y, x].view(np.uint32).tolist() == np.array(value, F32).view(np.uint32).tolist()


def test_far_window_takes_taus_own_island(export_tests: Path, tmp_path: Path) -> None:
    """Decision 356: one strip map is shared by every island, and a seam's far window also takes
    tau's own island. On the tie-sweep-seams-centred fixture (512 x 512), ring texel (22, 50) of
    island 124 takes its three own neighbours of row 49 and, as a far tap at its frame distance,
    (22, 48) of its own island, which J's island alone (decision 275) left out. UzPainter's taps,
    their distances and the ring value equal `padding_reference`'s."""
    mesh = (
        Path(__file__).resolve().parents[2]
        / "parity/fixtures/tier0-semantics/meshes/tie-sweep-seams-centred.obj"
    )
    size = 512
    values = np.random.default_rng(356).random((size, size, 3)).astype(F32)
    raw, result = tmp_path / "values.f32", tmp_path / "result.f32"
    raw.write_bytes(values.tobytes())
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            [
                dict(
                    mesh=str(mesh),
                    material="uzp_tie_sweep",
                    width=size,
                    height=size,
                    channels=3,
                    values=str(raw),
                    out=str(result),
                )
            ]
        )
    )
    process = subprocess.run(
        [str(export_tests), "ring", str(cases)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    native = {(r["x"], r["y"]): r for r in json.loads(process.stdout)["ring"]}
    out = np.frombuffer(result.read_bytes(), F32).reshape(size, size, 3)
    reference = Ring(mesh, "uzp_tie_sweep", size, size)
    x, y = 22, 50
    own = [
        ((x + dx) % size, y + dy)
        for dy, dx in NEIGHBOURS
        if 0 <= y + dy < size and reference.owner[y + dy, (x + dx) % size] >= 0
    ]
    tau = reference.tau(x, y, own)
    cands, undecided = reference.candidates(x, y, own, tau)
    n = tap_count(cands)
    expected = [((22, 49), False), ((23, 49), False), ((21, 49), False), ((22, 48), True)]
    assert [(c[2], c[1]) for c in cands[:n]] == expected and not undecided
    assert reference.tris[int(reference.owner[48, 22])].chart == reference.tris[tau].chart
    r = native[(x, y)]
    assert r["taps"] == n == 4 and not r["undecided"]
    assert [((c[0], c[1]), bool(c[3])) for c in r["candidates"][:n]] == expected
    for c, ref_c in zip(r["candidates"][:n], cands[:n], strict=True):
        assert math.isclose(c[2], ref_c[0], rel_tol=1e-12)
    t = fractions([c[0] for c in cands[:n]])
    chosen = [values[ty, tx] for _, _, (tx, ty) in cands[:n]]
    value = [chain([v[c] for v in chosen], t) for c in range(3)]
    assert out[y, x].view(np.uint32).tolist() == np.array(value, F32).view(np.uint32).tolist()
