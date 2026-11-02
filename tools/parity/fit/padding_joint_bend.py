"""Frozen predictions of the joint-bend padding probe (`tier0_semantics/padding_joint_bend.py`).

From the committed OBJ (float32 UVs, decision 281's snapped ownership), for every copy's ring
texel T, the chain and the eight kernel maps' values predicted by the reference under each
strip-end hypothesis: straight ends (`baseline`, the current reference), strip ends snapped to
1/256 texel (`snap256`), the strip's four quad corners snapped to 1/256 texel (`quadsnap256`), a
0.005-texel end tolerance (`eps005`) and mitred joins (`miter+msin1`), with the samples of T's
3 x 3 that e2 (A's seam edge from the corner V) owns in each. Authored geometry only; no Painter
data. Prints the discrimination table (`table`), which separates these fixed models only, and the
SHA-256 of the canonical predictions.

    python -m tools.parity.fit.padding_joint_bend [--out predictions.json]
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
import math
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.fit.padding_corpus import PATCHES, image, reference_text
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import padding_joint_bend as jb
from tools.parity.tier0_semantics.recording_requests import REQUEST_FIXTURES, kernel_bitmaps

# The committed fixture (`python -m tools.parity.tier0_semantics write`), checked against the
# generator before use.
MESH_PATH = REPO_ROOT / REQUEST_FIXTURES[jb.MESH][1]
# The reference the five models were frozen on (824d542f, before decision 368 made `snap256` the
# reference's strip rule): every model is that reference plus its patches.
FROZEN_REFERENCE = "824d542f"
HYPOTHESES = (
    "baseline",
    "baseline+snap256",
    "baseline+quadsnap256",
    "baseline+eps005",
    "baseline+miter+msin1",
)
NEIGHBOURS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def ring(policy: str, mesh: Path) -> tuple[Any, Any]:
    text = reference_text(FROZEN_REFERENCE)
    for name in policy.split("+")[1:]:
        for old, new in PATCHES[name]:
            if text.count(old) != 1:
                raise ValueError(f"patch {name} does not apply")
            text = text.replace(old, new)
    module = types.ModuleType(f"joint_{policy.replace('+', '_')}")
    exec(compile(text, f"padding_reference@{policy}", "exec"), module.__dict__)
    return module, module.Ring(mesh, jb.MATERIAL, jb.RESOLUTION, jb.RESOLUTION)


def own_of(r: Any, x: int, y: int) -> list[tuple[int, int]]:
    covered = r.owner >= 0
    return [
        ((x + dx) % r.width, y + dy)
        for dy, dx in NEIGHBOURS
        if 0 <= y + dy < r.height and covered[y + dy, (x + dx) % r.width]
    ]


def chain(
    ref: Any, r: Any, source: Any, x: int, y: int, winners: set[Any] | None = None
) -> dict[str, Any] | None:
    """T's taps in tap order (distance to 12 digits, far, texel) and the 24 predicted kernel
    components' float32 bits, with T's strip winners replaced by `winners` when given; None when
    T is not a ring texel."""
    own = own_of(r, x, y)
    if r.owner[y, x] >= 0 or not own:
        return None
    original = r.global_winners
    if winners is not None:
        r.global_winners = lambda xx, yy: winners
    try:
        cands, _ = r.candidates(x, y, own, r.tau(x, y, own))
    finally:
        r.global_winners = original
    taps = cands[: ref.tap_count(cands)]
    weights = r.chain_fractions(x, y, taps)
    values = np.asarray([source[ty, tx] for _, _, (tx, ty) in taps], np.float32)
    out = np.array([ref.chain(values[:, c], weights) for c in range(values.shape[1])], np.float32)
    return {
        "taps": [[round(d, 12), far, list(t)] for d, far, t in taps],
        "bits": [int(b) for b in out.view(np.uint32)],
    }


def sample_winners(m: Any, r: Any, x: int, y: int) -> dict[tuple[int, int], Any]:
    """The strip winner of each sample of T's 3 x 3, as the hypothesis's `global_winners` draws
    it (the last covering seam; under `miter`, the mitred owner of an uncovered sample)."""
    r.global_winners(x, y)
    grid = r.__dict__["_seam_grid"]
    out = {}
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            sx, sy = x + dx, y + dy
            winner = None
            for s in grid.get((sx, sy), []):
                t = r.tris[s[0]].t
                if m.strip_covers(t[(s[1] + 1) % 3], t[(s[1] + 2) % 3], sx + 0.5, sy + 0.5):
                    winner = s
            if winner is None and hasattr(r, "mitred"):
                winner = r.mitred(sx + 0.5, sy + 0.5, grid.get((sx, sy), []))
            out[(sx, sy)] = winner
    return out


def corner_v(copy: Any) -> tuple[tuple[float, float], tuple[float, float]]:
    """V and W2 in the copy's layout, whatever its turn: F1 = (V, W1, C) and F2 = (V, C, W2)
    share V and C, and a mirror reverses each triangle's corners. C - W2 is F2's border edge and
    V - W2 its seam e2, so V is the shared corner nearer T's centre (V is about one texel from T,
    C four)."""
    f1, f2 = copy.tris[0][1], copy.tris[1][1]
    shared = [c for c in f2 if c in f1]
    if len(shared) != 2:
        raise ValueError(f"{copy.name}: F1 and F2 share {len(shared)} corners")
    centre = (copy.target[0] + 0.5, copy.target[1] + 0.5)
    v = min(shared, key=lambda c: math.dist(c, centre))
    (w2,) = [c for c in f2 if c not in shared]
    return v, w2


def e2_of(
    r: Any, copy: Any, column: float, row: float
) -> tuple[tuple[int, int, int] | None, tuple[float, float]]:
    """The seam of A's triangle F2 = (V, C, W2) whose UV ends are V and W2, and V, in texel
    space."""
    (vc, vr), (wc, wr) = corner_v(copy)
    v, w2 = (vc + column, vr + row), (wc + column, wr + row)
    for lst in r.seams.values():
        for s in lst:
            t = r.tris[s[0]].t
            ends = (t[(s[1] + 1) % 3], t[(s[1] + 2) % 3])
            if all(min(abs(a[0] - b[0]) + abs(a[1] - b[1]) for b in ends) < 1e-3 for a in (v, w2)):
                return (int(s[0]), int(s[1]), int(s[2])), v
    return None, v


def predictions() -> dict[str, Any]:
    """Per copy: T, G (the sample of T's 3 x 3 nearest V), and per hypothesis T's chain and the
    samples of T's 3 x 3 that e2 owns; `decisive` when, under straight ends, e2 owns none of
    them, every hypothesis gives e2 at most G, and e2 owning G alone changes T's output bits."""
    if MESH_PATH.read_bytes() != jb.mesh():
        raise ValueError(f"{MESH_PATH} differs from its generator")
    source = np.concatenate(
        [
            image(REPO_ROOT / REQUEST_FIXTURES[name][1], jb.RESOLUTION)
            for name in kernel_bitmaps(jb.RESOLUTION)
        ],
        axis=-1,
    )
    rings = {policy: ring(policy, MESH_PATH) for policy in HYPOTHESES}
    ref, straight = rings["baseline"]
    placed, _ = jb.layout()
    rows = []
    for copy, (column, row), _ in placed:
        x, y = int(column + copy.target[0]), int(row + copy.target[1])
        e2, v = e2_of(straight, copy, column, row)
        g = min(
            ((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)),
            key=lambda s: math.dist((s[0] + 0.5, s[1] + 0.5), v),
        )
        entry: dict[str, Any] = {"copy": copy.name, "texel": [x, y], "g": list(g)}
        owned = {}
        for policy, (m, r) in rings.items():
            winners = sample_winners(m, r, x, y)
            owned[policy] = sorted(k for k, w in winners.items() if e2 is not None and w == e2)
            entry[policy] = chain(m, r, source, x, y)
            if entry[policy] is not None:
                entry[policy]["e2_samples"] = [list(k) for k in owned[policy]]
        decisive = False
        unique = all(set(o) <= {g} for o in owned.values())
        if e2 is not None and entry["baseline"] is not None and not owned["baseline"] and unique:
            others = {w for k, w in sample_winners(ref, straight, x, y).items() if k != g}
            forced = chain(ref, straight, source, x, y, {w for w in others if w} | {e2})
            decisive = forced is not None and forced["bits"] != entry["baseline"]["bits"]
        entry["decisive"] = decisive
        rows.append(entry)
    return {"mesh_sha256": hashlib.sha256(jb.mesh()).hexdigest(), "copies": rows}


def table(found: dict[str, Any]) -> dict[str, Any]:
    """Ring-valid and decisive copies; per hypothesis pair, the copies whose predicted output bits
    differ (this separates these fixed models only); and per hypothesis H of `snap256` and
    `quadsnap256`, the phase families (one bend, e1 kind and deficit at PHASES) holding a phase
    pair (i, j) where H's bits differ from straight ends at i and equal them at j while eps005's
    relation to straight ends is the same at i and j; `inside_loss`, those of them at a negative
    deficit where straight ends give G to e2 at both phases and H takes G from e2 at i."""
    rows = found["copies"]
    out: dict[str, Any] = {
        "copies": len(rows),
        "ring_valid": sum(all(row[p] is not None for p in HYPOTHESES) for row in rows),
        "decisive": sum(row["decisive"] for row in rows),
    }
    pairs = {}
    for a, b in itertools.combinations(HYPOTHESES, 2):
        name = f"{a.removeprefix('baseline+')}|{b.removeprefix('baseline+')}"
        pairs[name] = sum(
            1 for row in rows if row[a] and row[b] and row[a]["bits"] != row[b]["bits"]
        )
    out["values_differ"] = pairs
    families: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        family, _, phase = row["copy"].rpartition("-p")
        phased = row["copy"].startswith(("n-b1-", "n-b2.8-", "ge-b1-", "ge-b2.8-"))
        if phased and phase.isdigit() and all(row[p] is not None for p in HYPOTHESES):
            families[family].append(row)
    for h in ("baseline+snap256", "baseline+quadsnap256"):
        found_pairs, inside = phase_pairs(families, h)
        out[f"phase_pairs_{h.removeprefix('baseline+')}"] = found_pairs
        out[f"inside_loss_{h.removeprefix('baseline+')}"] = inside
    return out


def phase_pairs(families: dict[str, list[dict[str, Any]]], h: str) -> tuple[list[str], list[str]]:
    """The families holding a phase pair (i, j) for model `h`: its output bits differ from
    straight ends at i and equal them at j, while eps005's relation to straight ends is the same
    at both; and those holding such a pair at a negative deficit where straight ends give each
    copy's own G to e2 and `h` takes G from e2 at i. Every pair is examined (no order effect);
    each copy's G is its own (copies sit in different slots)."""

    def differs(row: dict[str, Any], model: str) -> bool:
        return bool(row[model]["bits"] != row["baseline"]["bits"])

    eps = "baseline+eps005"
    found_pairs, inside = [], []
    for family, members in sorted(families.items()):
        paired = lost = False
        for i, j in itertools.permutations(members, 2):
            if not (differs(i, h) and not differs(j, h) and differs(i, eps) == differs(j, eps)):
                continue
            paired = True
            if (
                "-d-" in family
                and i["g"] in i["baseline"]["e2_samples"]
                and j["g"] in j["baseline"]["e2_samples"]
                and i["g"] not in i[h]["e2_samples"]
            ):
                lost = True
                break
        if paired:
            found_pairs.append(family)
        if lost:
            inside.append(family)
    return found_pairs, inside


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    found = predictions()
    text = json.dumps(found, sort_keys=True)
    print(json.dumps(table(found), sort_keys=True))
    print(json.dumps({"predictions_sha256": hashlib.sha256(text.encode()).hexdigest()}))
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
