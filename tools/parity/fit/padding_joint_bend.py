"""Frozen predictions of the joint-bend padding probe (`tier0_semantics/padding_joint_bend.py`).

From the committed OBJ (float32 UVs, decision 281's snapped ownership), for every copy's ring
texel T, the chain and the eight kernel maps' values predicted by the reference under each
strip-end hypothesis: straight ends (`baseline`, the current reference), strip ends snapped to
1/256 texel (`snap256`), the strip's four quad corners snapped to 1/256 texel (`quadsnap256`), a
0.005-texel end tolerance (`eps005`) and mitred joins (`miter+msin1`). Also, under straight ends:
whether T is a ring texel, and whether e2 (A's seam edge from the corner V) reaches T only through
G (absent from T's strip winners, and T's chain changes when e2 owns G). Authored geometry only;
no Painter data. Prints the discrimination table (copies whose predicted values differ, per
hypothesis pair), the phase pairs, and the SHA-256 of the canonical predictions.

    python -m tools.parity.fit.padding_joint_bend [--out predictions.json]
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
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
HYPOTHESES = (
    "baseline",
    "baseline+snap256",
    "baseline+quadsnap256",
    "baseline+eps005",
    "baseline+miter+msin1",
)
NEIGHBOURS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def ring(policy: str, mesh: Path) -> tuple[Any, Any]:
    text = reference_text(None)
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


def chain(ref: Any, r: Any, source: Any, x: int, y: int) -> dict[str, Any] | None:
    """T's taps in tap order (distance to 12 digits, far, texel) and the 24 predicted kernel
    components' float32 bits; None when T is not a ring texel."""
    own = own_of(r, x, y)
    if r.owner[y, x] >= 0 or not own:
        return None
    cands, _ = r.candidates(x, y, own, r.tau(x, y, own))
    taps = cands[: ref.tap_count(cands)]
    weights = r.chain_fractions(x, y, taps)
    values = np.asarray([source[ty, tx] for _, _, (tx, ty) in taps], np.float32)
    out = np.array([ref.chain(values[:, c], weights) for c in range(values.shape[1])], np.float32)
    return {
        "taps": [[round(d, 12), far, list(t)] for d, far, t in taps],
        "bits": [int(b) for b in out.view(np.uint32)],
    }


def e2_of(r: Any, copy: Any, column: float, row: float) -> tuple[int, int, int] | None:
    """The seam of A's triangle F2 = (V, C, W2) whose UV ends are V and W2, in texel space."""
    uvs = copy.tris[1][1]
    v, w2 = (uvs[0][0] + column, uvs[0][1] + row), (uvs[2][0] + column, uvs[2][1] + row)
    for lst in r.seams.values():
        for s in lst:
            t = r.tris[s[0]].t
            ends = (t[(s[1] + 1) % 3], t[(s[1] + 2) % 3])
            if all(min(abs(a[0] - b[0]) + abs(a[1] - b[1]) for b in ends) < 1e-3 for a in (v, w2)):
                return (int(s[0]), int(s[1]), int(s[2]))
    return None


def decisive(ref: Any, r: Any, x: int, y: int, e2: tuple[int, int, int] | None) -> bool:
    """Under straight ends: e2 owns no sample of T's 3 x 3, and T's chain changes when it does."""
    if e2 is None or e2 in r.global_winners(x, y):
        return False
    own = own_of(r, x, y)
    tau = r.tau(x, y, own)
    plain, _ = r.candidates(x, y, own, tau)
    original = r.global_winners
    r.global_winners = lambda xx, yy: original(xx, yy) | {e2}
    try:
        forced, _ = r.candidates(x, y, own, tau)
    finally:
        r.global_winners = original
    return bool(plain[: ref.tap_count(plain)] != forced[: ref.tap_count(forced)])


def predictions() -> dict[str, Any]:
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
        rows.append(
            {
                "copy": copy.name,
                "texel": [x, y],
                "decisive": decisive(ref, straight, x, y, e2_of(straight, copy, column, row)),
                **{p: chain(m, r, source, x, y) for p, (m, r) in rings.items()},
            }
        )
    return {"mesh_sha256": hashlib.sha256(jb.mesh()).hexdigest(), "copies": rows}


def table(found: dict[str, Any]) -> dict[str, Any]:
    """Valid and decisive copies, the copies whose predicted values differ per hypothesis pair,
    and per phase family (copy name without its phase) whether `snap256` and `quadsnap256` take
    e2 (T's chain differs from straight ends) at some phases and not at others."""
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
    families: dict[str, dict[str, set[bool]]] = collections.defaultdict(
        lambda: {"snap256": set(), "quadsnap256": set()}
    )
    for row in rows:
        if not row["copy"].startswith(("n-b1-", "n-b2.8-", "ge-b1-", "ge-b2.8-")):
            continue
        family = row["copy"].rsplit("-p", 1)[0]
        for h in ("snap256", "quadsnap256"):
            families[family][h].add(row[f"baseline+{h}"] != row["baseline"])
    out["phase_flips"] = {
        h: sorted(f for f, v in families.items() if len(v[h]) == 2)
        for h in ("snap256", "quadsnap256")
    }
    return out


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
