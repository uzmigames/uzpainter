"""Painter's far-window side on the folded-seam tie probe, per twin, fold and seam position
(phase3.1_export-island-padding item 2.1). CPU only, from the private store; counts only.

Every labelled ring texel of `export-padding-fold-tie` has exactly one near window-boundary axis
(decision 291), and exactly one of the two sides reproduces the recording (`padding_corpus.sides`).
The texel is counted by its copy's twin (`dyadic`, `offset`), its fold (`flat` and `x90`, whose
float32 rotation entries are exact, or the Pythagorean ones), whether its centre projects inside
the seam edge E of its window (`mid`) or past one of its ends (`end`), and the side Painter takes:
`exact` (the window of the exact tie, the reference's floor/ceil) or `other`.

    python -m tools.parity.fit.padding_fold_tie_sides
"""

from __future__ import annotations

import collections
import json
import sys

from tools.parity.fit import padding_corpus
from tools.parity.tier0_semantics import padding_fold_tie as ft

PROBE = "fold-tie"
EXACT_FOLDS = ("flat", "x90")


def counts() -> collections.Counter[tuple[str, str, str, str]]:
    """(twin, fold class, seam position, Painter's side) -> labelled ring texels."""
    rows = padding_corpus.sides(PROBE)
    probe = padding_corpus.Probe(PROBE)
    ring = probe.ring("baseline")
    ring.texels()
    placed, _ = ft.layout()
    out: collections.Counter[tuple[str, str, str, str]] = collections.Counter()
    for row in rows:
        x, y = row["texel"]
        (copy,) = [
            c
            for c, (sc, sr), _ in placed
            if sc - 2 <= x < sc + c.size[0] + 2 and sr - 2 <= y < sr + c.size[1] + 2
        ]
        ((_, _, _, e, edge, _),) = ring.near[(x, y)]
        a, b = ring.tris[e].t[(edge + 1) % 3], ring.tris[e].t[(edge + 2) % 3]
        ex, ey = b[0] - a[0], b[1] - a[1]
        along = ((x + 0.5 - a[0]) * ex + (y + 0.5 - a[1]) * ey) / (ex * ex + ey * ey)
        exact = row["exact"]
        if sum(bool(v) for v in exact.values()) != 1:
            raise ValueError(f"texel {x, y}: not exactly one side reproduces the recording")
        out[
            (
                copy.twin,
                "exact-rotation" if copy.fold in EXACT_FOLDS else "pythagorean",
                "mid" if 0.0 <= along <= 1.0 else "end",
                "exact" if exact["none"] else "other",
            )
        ] += 1
    return out


def main() -> int:
    for key, n in sorted(counts().items()):
        print(json.dumps({"twin": key[0], "fold": key[1], "seam": key[2], "side": key[3], "n": n}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
