"""Painter's far window along the seam past a seam end, on the seam-end overhang sweep
(`export-padding-end-overhang`, phase3.1_export-island-padding item 2.1). CPU only, from the
private store; counts only on stdout, per-texel rows only to the optional private `--out` file.

Every ring texel whose centre projects past an end of the seam edge E of its far window is
evaluated with that window moved by -1, 0 and +1 texel along the seam's axis in J's UV (rows: B
sits at turn 0, and A's far window is in B, B's in A, both along rows), and labelled by the
moves that reproduce the recording on every component. A move `m` means Painter's far
coordinate along the axis, f - 1/2, lies in (R + m - 1, R + m] for the reference's window row
R = ceil(f - 1/2), so the texel brackets Painter's offset from the reference's far coordinate,
delta = f_Painter - f_reference (rows), by (R + m - 1 - (f - 1/2), R + m - (f - 1/2)]. The copies'
shifts move f in 1/64-texel steps, so each class's brackets intersect to 1/64 texel.

A class is (fold, island, which end, the texel's overhang past that end, its signed distance
across the seam line, positive away from its own island), in texels of its own island's UV.

    python -m tools.parity.fit.padding_end_overhang [--out private.json]
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.fit import padding_corpus
from tools.parity.tier0_semantics import padding_end_overhang as eo

PROBE = "end-overhang"
HOOK = "        col0, row0 = math.floor(fu - 0.5), math.ceil(fv - 0.5)\n"
# The window's row moved by `self.moves[(x, y, e, edge)]`, and every window's far point seen.
WINDOW_HOOK = """    def window_move(self, x, y, e, edge, fu, fv, col0, row0):
        self.seen.setdefault((x, y), []).append((e, edge, fu, fv))
        move = self.moves.get((x, y, e, edge), 0)
        return col0, row0 + move

"""
padding_corpus.PATCHES["endmove"] = [
    (
        "    def tau(self, x: int, y: int, own",
        WINDOW_HOOK + "    def tau(self, x: int, y: int, own",
    ),
    (
        "        " + HOOK,
        "        "
        + HOOK
        + " " * 16
        + "col0, row0 = self.window_move(x, y, e_index, edge, fu, fv, col0, row0)\n",
    ),
]
NO_FLIP = frozenset({(-1, -1)})  # matches no window: `candidates` returns before its analysis


def void_problems(manifest: dict[str, Any], record: dict[str, Any]) -> list[str]:
    """Decision 266's template void rule: every recording's template capture shows User0-User7
    as RGB32F (the covered-source rule is `padding_corpus.exports`', on every export)."""
    problems = []
    for recording in record["recordings"]:
        outputs = {o["output_id"]: o for o in recording["outputs"]}
        sets = outputs["template/texture-sets"]["values"]["texture_sets"]
        stack = {n.lower(): v for n, v in sets[eo.MATERIAL]["stacks"][""].items()}
        if any(stack[f"user{i}"]["format"] != "RGB32F" for i in range(8)):
            problems.append(f"{recording['recording_id']}: a User channel is not RGB32F")
    return problems


def _copy_of(placed: list[Any], x: int, y: int) -> Any:
    (copy,) = [
        c
        for c, (sc, sr), _ in placed
        if sc - 2 <= x < sc + c.size[0] + 2 and sr - 2 <= y < sr + c.size[1] + 2
    ]
    return copy


def rows() -> list[dict[str, Any]]:
    """One row per end texel: its copy, class, the reference's far coordinate and the moves that
    reproduce the recording. Private data."""
    p = padding_corpus.Probe(PROBE, void_problems)
    if p.unstable:
        raise ValueError("the infinite exports differ across steps or recordings")
    ring = p.ring("baseline+endmove")
    ring.moves, ring.seen = {}, {}
    ref = p.ref
    placed, _ = eo.layout()
    out = []
    for x, y, _cands, _count in ring.texels():
        # The first call is the texel's own; decision 291's side trials repeat its window.
        windows = ring.seen.get((x, y), [])
        if len({w[:2] for w in windows}) != 1:
            continue
        e, edge, _fu, fv = windows[0]
        E = ring.tris[e]
        a, b = E.t[(edge + 1) % 3], E.t[(edge + 2) % 3]
        ex, ey = b[0] - a[0], b[1] - a[1]
        length = math.hypot(ex, ey)
        px, py = x + 0.5, y + 0.5
        along = ((px - a[0]) * ex + (py - a[1]) * ey) / (length * length)
        if 0.0 <= along <= 1.0:
            continue
        # Signed distance across the seam line, positive away from E's island (E's third corner).
        c = E.t[edge]
        side = ex * (c[1] - a[1]) - ey * (c[0] - a[0])
        across = (ex * (py - a[1]) - ey * (px - a[0])) / length
        across = -across if side > 0 else across
        end_v = a if along < 0.0 else b
        over = abs((px - end_v[0]) * ex + (py - end_v[1]) * ey) / length
        own = [
            ((x + dx) % p.size, y + dy)
            for dy, dx in ref.NEIGHBOURS
            if 0 <= y + dy < p.size and p.covered[y + dy, (x + dx) % p.size]
        ]
        tau = ring.tau(x, y, own)
        reproduce, taps = [], []
        for move in (-1, 0, 1):
            ring.moves = {(x, y, e, edge): move}
            cands, _ = ring.candidates(x, y, own, tau, NO_FLIP)
            n = ref.tap_count(cands)
            chosen = cands[:n]
            taps.append([t[2] for t in chosen])
            values = np.asarray([p.source[ty, tx] for _, _, (tx, ty) in chosen], np.float32)
            if not p.missed((x, y), p.chain(values, ring.chain_fractions(x, y, chosen))):
                reproduce.append(move)
        ring.moves = {}
        copy = _copy_of(placed, x, y)
        out.append(
            {
                "texel": [x, y],
                "copy": copy.name,
                "fold": copy.fold,
                "overhang": copy.overhang,
                "shift": copy.shift,
                "island": "A" if px < _slot_of(placed, copy)[0] + eo.B_COLUMN - 2 else "B",
                "end": "low" if along < 0.0 else "high",
                "over": round(over * 64) / 64,
                "across": round(across * 64) / 64,
                "fv": fv,
                "reproduce": reproduce,
                "sensitive": taps[0] != taps[1] or taps[1] != taps[2],
            }
        )
    return out


def _slot_of(placed: list[Any], copy: Any) -> tuple[float, float]:
    slot: tuple[float, float] = next(slot for c, slot, _ in placed if c is copy)
    return slot


def brackets(found: list[dict[str, Any]]) -> dict[tuple[Any, ...], dict[str, Any]]:
    """Per class: texels, the labelled ones, the ambiguous ones (more or fewer than one move
    reproduces), and the intersection of delta's brackets (rows), as fractions."""
    out: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in found:
        key = (row["fold"], row["island"], row["end"], row["over"], row["across"])
        cls = out.setdefault(
            key,
            {"n": 0, "labelled": 0, "ambiguous": 0, "moved": 0, "low": None, "high": None},
        )
        cls["n"] += 1
        if len(row["reproduce"]) != 1 or not row["sensitive"]:
            cls["ambiguous"] += 1
            continue
        (move,) = row["reproduce"]
        cls["labelled"] += 1
        cls["moved"] += move != 0
        m = Fraction(row["fv"]) - Fraction(1, 2)
        r = math.ceil(m)
        lo, hi = r + move - 1 - m, r + move - m
        cls["low"] = lo if cls["low"] is None else max(cls["low"], lo)
        cls["high"] = hi if cls["high"] is None else min(cls["high"], hi)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="private JSON file for per-texel rows")
    args = parser.parse_args(argv)
    found = rows()
    if args.out is not None:
        args.out.write_text(json.dumps(found), encoding="utf-8")
    totals = collections.Counter(
        (r["island"], len(r["reproduce"]) == 1 and r["sensitive"], r["reproduce"] == [0])
        for r in found
    )
    print(json.dumps({"end_texels": len(found), "by": {str(k): v for k, v in totals.items()}}))
    for key, cls in sorted(brackets(found).items()):
        low, high = cls["low"], cls["high"]
        print(
            json.dumps(
                {
                    "fold": key[0],
                    "island": key[1],
                    "end": key[2],
                    "over": key[3],
                    "across": key[4],
                    **{k: cls[k] for k in ("n", "labelled", "ambiguous", "moved")},
                    "delta_low": None if low is None else float(low),
                    "delta_high": None if high is None else float(high),
                    "consistent": None if low is None else low < high,
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
