"""Frozen predictions of the world-offset padding probe (`tier0_semantics/padding_world_offset.py`).

From the committed OBJ (float32 positions and UVs, decision 281's snapped ownership), every ring
texel's chain and the eight kernel maps' 24 float32 components, predicted by the reference at
FROZEN_REFERENCE (decision 368, production) with every rigidly turned far distance measured under
each fixed model of `padding_far32.MODELS`. Authored geometry only; no Painter data. Prints the
discrimination table (`table`), which separates these fixed models only, and the SHA-256 of the
canonical predictions.

    python -m tools.parity.fit.padding_world_offset [--out predictions.json]
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
import sys
import types
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.fit import padding_far32 as far32
from tools.parity.fit.padding_corpus import image, reference_text
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import padding_world_offset as wo
from tools.parity.tier0_semantics.recording_requests import REQUEST_FIXTURES, kernel_bitmaps

MESH_PATH = REPO_ROOT / REQUEST_FIXTURES[wo.MESH][1]
# The production reference the models were frozen on: decision 368 (a69b1434).
FROZEN_REFERENCE = "a69b1434"
MODELS = far32.MODELS
# A ring texel belongs to the copy whose UV slot, grown by SLOT_REACH texels, holds it.
SLOT_REACH = 2


def policy(model: str) -> str:
    return "farhook" if model == "double" else f"farhook+fm{model}"


def module(model: str) -> Any:
    text = reference_text(FROZEN_REFERENCE)
    for name in policy(model).split("+"):
        for old, new in far32.PATCHES[name]:
            if text.count(old) != 1:
                raise ValueError(f"patch {name} does not apply")
            text = text.replace(old, new)
    m = types.ModuleType(f"world_offset_{model}")
    exec(compile(text, f"padding_reference@{FROZEN_REFERENCE}+{policy(model)}", "exec"), m.__dict__)
    return m


def source() -> np.ndarray:
    return np.concatenate(
        [
            image(REPO_ROOT / REQUEST_FIXTURES[name][1], wo.RESOLUTION)
            for name in kernel_bitmaps(wo.RESOLUTION)
        ],
        axis=-1,
    )


def ring_chains(model: str) -> dict[str, Any]:
    """Every ring texel under `model`: taps (distance to 12 digits, far, texel), the chain
    fractions' float32 bits, the 24 output bits, and the reference's undecided flags."""
    m = module(model)
    ring = m.Ring(MESH_PATH, wo.MATERIAL, wo.RESOLUTION, wo.RESOLUTION)
    values_of = source()
    out = {}
    for x, y, cands, count in ring.texels():
        taps = cands[:count]
        weights = ring.chain_fractions(x, y, taps)
        values = np.asarray([values_of[ty, tx] for _, _, (tx, ty) in taps], np.float32)
        bits = np.array([m.chain(values[:, c], weights) for c in range(24)], np.float32)
        out[f"{x},{y}"] = {
            "taps": [[round(d, 12), far, list(t)] for d, far, t in taps],
            "fractions": [int(b) for b in np.asarray(weights, np.float32).view(np.uint32)],
            "bits": [int(b) for b in bits.view(np.uint32)],
            "undecided": sorted(ring.undecided.get((x, y), set())),
        }
    return out


def owner_copy(placed: list[Any]) -> dict[tuple[int, int], int]:
    """Texel -> index of the copy whose slot (grown by SLOT_REACH) holds it."""
    found: dict[tuple[int, int], int] = {}
    for i, (copy, (column, row)) in enumerate(placed):
        width, height = copy.size
        for x in range(int(column) - SLOT_REACH, int(column) + width + SLOT_REACH):
            for y in range(int(row) - SLOT_REACH, int(row) + height + SLOT_REACH):
                if (x, y) in found:
                    raise ValueError("copy slots overlap")
                found[(x, y)] = i
    return found


def predictions(jobs: int = len(MODELS)) -> dict[str, Any]:
    """Per copy: its name, offset, turn, scale, slot and every ring texel (relative to the slot)
    with each model's taps and bits. Ring texels outside every slot (the anchors') are dropped."""
    if MESH_PATH.read_bytes() != wo.mesh():
        raise ValueError(f"{MESH_PATH} differs from its generator")
    with ProcessPoolExecutor(jobs) as pool:
        rings = dict(zip(MODELS, pool.map(ring_chains, MODELS), strict=True))
    if len({tuple(sorted(r)) for r in rings.values()}) != 1:
        raise ValueError("the models' ring populations differ")
    placed, _ = wo.layout()
    owners = owner_copy(placed)
    rows: list[dict[str, Any]] = [
        {
            "copy": copy.name,
            "role": copy.role,
            "shape": copy.shape.name,
            "offset": list(copy.offset),
            "turn": copy.turn,
            "scale": copy.scale,
            "slot": [int(column), int(row)],
            "texels": {},
        }
        for copy, (column, row) in placed
    ]
    for key in sorted(rings["double"], key=lambda k: tuple(int(v) for v in k.split(","))):
        x, y = (int(v) for v in key.split(","))
        if (x, y) not in owners:
            continue
        row = rows[owners[(x, y)]]
        rel = f"{x - row['slot'][0]},{y - row['slot'][1]}"
        row["texels"][rel] = {
            "undecided": rings["double"][key]["undecided"],
            **{
                model: {k: rings[model][key][k] for k in ("taps", "fractions", "bits")}
                for model in MODELS
            },
        }
    return {
        "mesh_sha256": hashlib.sha256(wo.mesh()).hexdigest(),
        "topology": topology(placed),
        "reference": FROZEN_REFERENCE,
        "models": list(MODELS),
        "copies": rows,
    }


def topology(placed: list[Any]) -> dict[str, Any]:
    """Per copy, as the reference reads the OBJ (vertices welded by float32 position, decision
    288): its triangles, vertices, UV islands, planar faces and seam edges; and the vertices
    and islands shared with another copy (a weld). Every copy of a shape must have the same
    counts and no copy may share a vertex or an island."""
    ring = module("double").Ring(MESH_PATH, wo.MATERIAL, wo.RESOLUTION, wo.RESOLUTION)
    owner: list[int] = []
    for i, (copy, _) in enumerate(placed):
        owner += [i] * len(copy.tris)
    owner += [-1] * (len(ring.tris) - len(owner))  # the two box anchors
    per: list[dict[str, set[Any]]] = [
        {"tris": set(), "vertices": set(), "charts": set(), "faces": set(), "seams": set()}
        for _ in placed
    ]
    for t, tri in enumerate(ring.tris):
        if owner[t] < 0:
            continue
        row = per[owner[t]]
        row["tris"].add(t)
        row["vertices"] |= set(tri.vertex)
        row["charts"].add(tri.chart)
        row["faces"].add(tri.face)
    for seams in ring.seams.values():
        for e, edge, j in seams:
            per[owner[e]]["seams"].add((e, edge, j))
    shared = 0
    for key in ("vertices", "charts", "faces"):
        seen: dict[int, int] = {}
        for i, row in enumerate(per):
            for v in row[key]:
                shared += seen.setdefault(v, i) != i
    counts = [{k: len(v) for k, v in row.items()} for row in per]
    by_shape: dict[str, set[tuple[tuple[str, int], ...]]] = collections.defaultdict(set)
    for (copy, _), c in zip(placed, counts, strict=True):
        by_shape[copy.shape.name].add(tuple(sorted(c.items())))
    return {
        "shared": shared,
        "per_shape": {
            name: [dict(c) for c in sorted(found)] for name, found in sorted(by_shape.items())
        },
    }


def kind(row: dict[str, Any]) -> str:
    if row["role"] == "turn":
        return f"turn:{row['turn']}"
    if row["role"] == "scale":
        return f"scale:{row['scale']}"
    return "offset" if row["role"] in ("base", "offset") else str(row["role"])


def signature(row: dict[str, Any], texel: dict[str, Any], model: str) -> tuple[Any, ...]:
    """A ring texel's chain under `model` independent of the kernel bitmaps' slot phase: its
    taps relative to the copy's slot (far flag, texel) and its chain fractions' bits. Output bits
    are left out: the kernel codes differ between slots (period 3 and a 17 x 13 tile)."""
    column, row_ = row["slot"]
    return (
        tuple((far, t[0] - column, t[1] - row_) for _, far, t in texel[model]["taps"]),
        tuple(texel[model]["fractions"]),
    )


def translation_changed(found: dict[str, Any], model: str) -> dict[str, int]:
    """The ring texels of every translated copy (roles `offset`, `yz` and `dup`) whose chain under
    `model` differs from the same texel of its shape's `base` copy, by chain kind (`far`: a far
    tap under the double model, else `own`) and change: `taps` (other relative taps or order:
    decision 273's float32 comparators order exact ties by position, in every model) or
    `fractions` (the same taps, other fractions: what a far-distance model moves); `missing` when
    the base copy's ring lacks the texel."""
    base = {row["shape"]: row for row in found["copies"] if row["role"] == "base"}
    changed: collections.Counter[str] = collections.Counter()
    for row in found["copies"]:
        if row["role"] not in ("offset", "yz", "dup"):
            continue
        origin = base[row["shape"]]
        for rel, texel in row["texels"].items():
            same = origin["texels"].get(rel)
            if same is None:
                changed["missing"] += 1
                continue
            mine, theirs = signature(row, texel, model), signature(origin, same, model)
            chain = "far" if any(tap[1] for tap in texel["double"]["taps"]) else "own"
            if mine[0] != theirs[0]:
                changed[f"{chain}_taps"] += 1
            elif mine[1] != theirs[1]:
                changed[f"{chain}_fractions"] += 1
    return dict(sorted(changed.items()))


def stable(row: dict[str, Any], texel: dict[str, Any]) -> bool:
    """The scored set: a ring texel with a far tap, decided by the reference (no undecided
    flag), whose taps (relative texels, far flags, order) are the same under every model. Its
    models differ only in the far chain's fractions, so a recorded value tells the models'
    far-distance arithmetic apart and nothing else."""
    taps = [signature(row, texel, m)[0] for m in MODELS]
    return (
        not texel["undecided"]
        and any(t[1] for t in texel["double"]["taps"])
        and len(set(taps)) == 1
    )


def translation_pairs(found: dict[str, Any]) -> dict[str, Any]:
    """The predeclared translation mask: (translated texel, base texel) pairs of a translated
    copy (roles `offset`, `yz`, `dup`) and its shape's `base` copy at the same relative texel,
    both in the scored set (`stable`) and with the same relative taps in the same order. Per
    model, the pairs whose chain fractions differ: on this mask only a far distance can move
    them (no own chain, no tap change)."""
    base = {row["shape"]: row for row in found["copies"] if row["role"] == "base"}
    pairs = 0
    moved = dict.fromkeys(MODELS, 0)
    for row in found["copies"]:
        if row["role"] not in ("offset", "yz", "dup"):
            continue
        origin = base[row["shape"]]
        for rel, texel in row["texels"].items():
            same = origin["texels"].get(rel)
            if same is None or not stable(row, texel) or not stable(origin, same):
                continue
            if signature(row, texel, "double")[0] != signature(origin, same, "double")[0]:
                continue
            pairs += 1
            for m in MODELS:
                moved[m] += signature(row, texel, m)[1] != signature(origin, same, m)[1]
    return {"pairs": pairs, "fractions_differ": moved}


def table(found: dict[str, Any]) -> dict[str, Any]:
    """Ring texels and far-tap texels; per model pair, the ring texels whose predicted output
    bits differ (all, then by |offset| band and control kind); per model, the translated ring
    texels whose chain differs from the shape's base copy (`translation_changed`); and the
    topology check."""
    rows = found["copies"]
    texels = [(row, t) for row in rows for t in row["texels"].values()]
    out: dict[str, Any] = {
        "copies": len(rows),
        "ring_texels": len(texels),
        "far_texels": sum(any(tap[1] for tap in t["double"]["taps"]) for _, t in texels),
        "undecided_texels": sum(bool(t["undecided"]) for _, t in texels),
        "stable_texels": sum(stable(row, t) for row, t in texels),
    }

    def band(row: dict[str, Any]) -> str:
        # The z of a copy holds its shape's and duplicate's small gaps besides OFFSETS_YZ.
        x, y, z = row["offset"]
        reach = max(abs(x), abs(y), abs(z) if abs(z) > 10 else 0.0)
        return "lt8" if reach < 8 else "8-63" if reach < 64 else "ge64"

    pairs: dict[str, Any] = {}
    for a, b in itertools.combinations(MODELS, 2):
        counts: collections.Counter[str] = collections.Counter()
        for row, t in texels:
            if t[a]["bits"] != t[b]["bits"]:
                counts["all"] += 1
                counts["decided"] += not t["undecided"]
                if stable(row, t):
                    counts["stable"] += 1
                    counts[f"stable:kind:{kind(row)}"] += 1
                    counts[f"stable:shape:{row['shape']}"] += 1
                    counts[f"stable:band:{band(row)}"] += 1
                counts[f"band:{band(row)}"] += 1
                counts[f"kind:{kind(row)}"] += 1
        pairs[f"{a}|{b}"] = dict(sorted(counts.items()))
    out["bits_differ"] = pairs
    out["translation_changed"] = {m: translation_changed(found, m) for m in MODELS}
    out["translation_pairs"] = translation_pairs(found)
    out["topology"] = found["topology"]
    return out


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def compact(found: dict[str, Any]) -> dict[str, Any]:
    """The committed form of the predictions: the full predictions' SHA-256; per copy and model
    the SHA-256 of its ring's predicted output bits (texels in order); per copy its scored set
    (`stable`, relative texels: the frozen membership mask); and every ring texel
    where two models' output bits differ, with each model's fractions and output bits. The full
    predictions are reproduced by `predictions()` from the committed OBJ."""
    copies, texels = [], []
    for row in found["copies"]:
        copies.append(
            {
                "copy": row["copy"],
                "slot": row["slot"],
                "scored": [rel for rel, t in sorted(row["texels"].items()) if stable(row, t)],
                "bits_sha256": {
                    m: digest([[rel, t[m]["bits"]] for rel, t in sorted(row["texels"].items())])
                    for m in MODELS
                },
            }
        )
        for rel, t in sorted(row["texels"].items()):
            if len({tuple(t[m]["bits"]) for m in MODELS}) > 1:
                texels.append(
                    {
                        "copy": row["copy"],
                        "texel": rel,
                        "undecided": t["undecided"],
                        **{m: {k: t[m][k] for k in ("fractions", "bits")} for m in MODELS},
                    }
                )
    return {
        "predictions_sha256": digest(found),
        "mesh_sha256": found["mesh_sha256"],
        "reference": found["reference"],
        "models": found["models"],
        "copies": copies,
        "discriminating": texels,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="the full predictions (large; not committed)")
    parser.add_argument("--compact", type=Path, help="the committed compact predictions")
    parser.add_argument("--load", type=Path, help="read the full predictions instead")
    args = parser.parse_args(argv)
    found = predictions() if args.load is None else json.loads(args.load.read_text("utf-8"))
    text = json.dumps(found, sort_keys=True)
    print(json.dumps(table(found), sort_keys=True))
    print(json.dumps({"predictions_sha256": hashlib.sha256(text.encode()).hexdigest()}))
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
    if args.compact is not None:
        # Bytes, not text: the committed file keeps LF line ends on every platform (its SHA-256).
        args.compact.write_bytes((json.dumps(compact(found), sort_keys=True) + "\n").encode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
