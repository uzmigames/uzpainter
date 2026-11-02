"""Joint-gap census of the strip map (item 2.7, `padding-joint-bend-freeze.md`), CPU only.

A joint-gap sample is a texel centre that no straight seam strip covers (`strip_covers`) but that
lies within half a texel of the line of a seam that ends at a UV corner shared with another seam
of its island, at most half a texel past that end. For every ring texel whose 3 x 3 holds such
samples, each owner of each sample (none, or one of the seams ending there) is tried in the strip
winners, and the chain is compared with the recording. Classes: `all-ok` (no owner changes the
outcome), `none-ok-only` / `other-ok-only` (only the unowned / only one owned choice reproduces
Painter), `none-ok` / `other-ok` (several do), `none-fits`. Each class is reported with the least
UV |sin| of the joint's two seams. Stdout carries counts only; coordinates go to the optional
private `--out` file.

    python -m tools.parity.fit.padding_joint_gaps --probe kernel-wand-2048 [--policy ...]
"""

from __future__ import annotations

import argparse
import collections
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.fit.padding_corpus import Probe, probes

type Seam = tuple[int, int, int]


def census(probe: str, policy: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    p = Probe(probe)
    r = p.ring(policy)
    ref = p.patched.get(policy, p.ref)
    r.global_winners(0, 0)
    grid = r.__dict__["_seam_grid"]
    ends: dict[tuple[int, tuple[float, float]], list[Seam]] = {}
    for s in sorted(s for lst in r.seams.values() for s in lst):
        t = r.tris[s[0]]
        for k in (1, 2):
            ends.setdefault((t.chart, t.t[(s[1] + k) % 3]), []).append(s)

    def seg(s: Seam) -> tuple[tuple[float, float], tuple[float, float]]:
        t = r.tris[s[0]].t
        return t[(s[1] + 1) % 3], t[(s[1] + 2) % 3]

    gaps: dict[tuple[int, int], tuple[list[Seam], float]] = {}
    for (_, v), lst in ends.items():
        if len(lst) < 2:
            continue
        for gx in range(math.floor(v[0]) - 1, math.floor(v[0]) + 2):
            for gy in range(math.floor(v[1]) - 1, math.floor(v[1]) + 2):
                px, py = gx + 0.5, gy + 0.5
                if any(ref.strip_covers(*seg(s), px, py) for s in grid.get((gx, gy), [])):
                    continue
                owners = []
                for s in lst:
                    a, b = seg(s)
                    ex, ey = b[0] - a[0], b[1] - a[1]
                    length = math.hypot(ex, ey)
                    along = ((px - a[0]) * ex + (py - a[1]) * ey) / length
                    perp = ((px - a[0]) * ey - (py - a[1]) * ex) / length
                    if abs(perp) <= 0.5 and -0.5 <= along <= length + 0.5:
                        owners.append(s)
                if owners:
                    far = [seg(s)[1] if seg(s)[0] == v else seg(s)[0] for s in lst[:2]]
                    u = [
                        ((w[0] - v[0]) / math.dist(w, v), (w[1] - v[1]) / math.dist(w, v))
                        for w in far
                    ]
                    gaps[(gx, gy)] = (owners, abs(u[0][0] * u[1][1] - u[0][1] * u[1][0]))
    covered = r.owner >= 0
    original = r.global_winners
    rows: list[dict[str, Any]] = []
    for y in range(r.height):
        for x in range(r.width):
            here = [(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
            here = [g for g in here if g in gaps]
            if covered[y, x] or not here:
                continue
            own = [
                ((x + dx) % r.width, y + dy)
                for dy, dx in ref.NEIGHBOURS
                if 0 <= y + dy < r.height and covered[y + dy, (x + dx) % r.width]
            ]
            if not own:
                continue
            tau = r.tau(x, y, own)
            results = {}
            for choice in itertools.product(*[[None, *gaps[g][0]] for g in here]):
                extra = {c for c in choice if c is not None}
                r.global_winners = lambda xx, yy, extra=extra: original(xx, yy) | extra
                try:
                    cands, _ = r.candidates(x, y, own, tau)
                finally:
                    r.global_winners = original
                taps = cands[: ref.tap_count(cands)]
                values = np.asarray([p.source[ty, tx] for _, _, (tx, ty) in taps], np.float32)
                weights = r.chain_fractions(x, y, taps)
                results[choice] = not p.missed((x, y), p.chain(values, weights))
            fits = [c for c, ok in results.items() if ok]
            if len(fits) == len(results):
                label = "all-ok"
            elif not fits:
                label = "none-fits"
            else:
                unowned = results[tuple(None for _ in here)]
                label = "none-ok" if unowned else "other-ok"
                label += "-only" if len(fits) == 1 else ""
            rows.append({"texel": [x, y], "class": label, "sin": min(gaps[g][1] for g in here)})
    classes: dict[str, list[float]] = collections.defaultdict(list)
    for row in rows:
        classes[str(row["class"])].append(float(row["sin"]))
    summary = {
        "probe": probe,
        "policy": policy,
        "gap_samples": len(gaps),
        "classes": {
            k: {"texels": len(v), "least_sin": round(min(v), 4)} for k, v in classes.items()
        },
    }
    return summary, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="append")
    parser.add_argument("--policy", default="baseline+island")
    parser.add_argument("--out", type=Path, help="private JSON file for coordinates")
    args = parser.parse_args(argv)
    dump = {}
    for name in args.probe or [*probes(), "kernel-wand-2048"]:
        summary, rows = census(name, args.policy)
        print(json.dumps(summary, sort_keys=True), flush=True)
        dump[name] = rows
    if args.out is not None:
        args.out.write_text(json.dumps(dump), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
