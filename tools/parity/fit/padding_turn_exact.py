"""Frozen predictions of the paired turn-exact padding probe (`tier0_semantics/padding_turn_exact`).

From the two committed OBJs (`x90` and `oblique`, float32 positions and UVs, decision 281's
snapped ownership), every ring texel's chain and the eight kernel maps' 24 float32 components,
predicted by the complete pipeline of each recipe of `padding_turn_exact_preflight.RECIPES`
(`selection`): the reference at `padding_world_offset.FROZEN_REFERENCE` (decision 368,
production) with `farhook` (`double`, the production control) or `farhook+fm<model>` for
`pos32n`, `rod32n` and `inv32n`, each candidate with `own32mix`. The recipe changes which taps
are kept, their order, the count, the undecided flags and the fractions. Authored geometry, the
committed kernel bitmaps and the frozen reference only; no Painter data.

**Pairs.** Both meshes share one layout, so a texel's pair is the same absolute texel in the same
copy slot (`copies`: the x90 and oblique copy of each slot, which must agree in role, offset,
turn, scale and slot).

**Primary mask** (`tau_same`, the preflight's declared universe, `masks`): ring texels whose
complete selection is the same under every recipe in both twins and decided, with a far tap
(`selection_mask`); the same chosen taps and traced entries in both twins (`matched`); every far
tap a `turn` tap (`coverage`); and tau's corners bit-identical in both twins. The fixed-support
recipes must equal the complete pipeline on every primary chain (`consistency`, zero). Its
exclusions are listed: the far texels outside `matched` per twin (`unmatched`), the matched
texels with another far-tap status (`not_clean`), and those with tau in island B (`tau_other`).

**Strata** (`strata`, declared before capture): per copy, the offset band (as the world-offset
freeze), the control kind (offset, yz, dup, turn y90 / z90, scale 2 / 3), the shape, and the
lane: `centre` for the copies at x = 54 (the normalised centre, the control lane), else `other`.

Prints the summary (`table`) and the SHA-256 of the canonical predictions. The summary separates
these controlled recipes only and is no causal identification of Painter's arithmetic.

    python -m tools.parity.fit.padding_turn_exact [--out predictions.json] [--compact path]
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from tools.parity.fit import padding_turn_exact_preflight as pf
from tools.parity.fit import padding_world_offset as fit
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import padding_turn_exact as te
from tools.parity.tier0_semantics.recording_requests import REQUEST_FIXTURES

MESH_PATHS = {twin: REPO_ROOT / REQUEST_FIXTURES[te.MESHES[twin]][1] for twin in te.TWINS}
RECIPES = tuple(pf.RECIPES)
FROZEN_REFERENCE = fit.FROZEN_REFERENCE
PAIRING = "the same absolute texel in the same copy slot of the shared layout"
MASKS = ("primary", "tau_other", "not_clean", "unmatched")


def _key(texel: tuple[int, int]) -> str:
    return f"{texel[0]},{texel[1]}"


def _texel(key: str) -> tuple[int, int]:
    x, y = (int(v) for v in key.split(","))
    return x, y


def band(offset: list[float]) -> str:
    """The world-offset freeze's offset band of a copy (`padding_world_offset.table`)."""
    x, y, z = offset
    reach = max(abs(x), abs(y), abs(z) if abs(z) > 10 else 0.0)
    return "lt8" if reach < 8 else "8-63" if reach < 64 else "ge64"


def copies() -> list[dict[str, Any]]:
    """Per slot of the shared layout: its x90 and oblique copies' names and their common role,
    kind, shape, offset, turn, scale, slot, band and lane."""
    placed = {twin: te.layout(te.copies(te.EXACT[twin]))[0] for twin in te.TWINS}
    rows = []
    for i, ((a, slot), (b, other)) in enumerate(zip(placed["x90"], placed["oblique"], strict=True)):
        same = (a.role, a.offset, a.turn, a.scale, slot) == (
            b.role,
            b.offset,
            b.turn,
            b.scale,
            other,
        )
        if not same or a.shape != te.twin(b.shape):
            raise ValueError("the twins' copies differ")
        row: dict[str, Any] = {
            "index": i,
            "x90": a.name,
            "oblique": b.name,
            "role": b.role,
            "shape": b.shape.name,
            "offset": list(b.offset),
            "turn": b.turn,
            "scale": b.scale,
            "slot": [int(slot[0]), int(slot[1])],
        }
        row["kind"] = fit.kind(row)
        row["band"] = band(row["offset"])
        row["lane"] = "centre" if b.offset[0] == 54.0 else "other"
        rows.append(row)
    return rows


def strata(row: dict[str, Any]) -> list[str]:
    """The declared strata of a copy's texels."""
    return [
        f"band:{row['band']}",
        f"kind:{row['kind']}",
        f"shape:{row['shape']}",
        f"lane:{row['lane']}",
    ]


def _plain(found: dict[tuple[int, int], dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """`padding_turn_exact_preflight.selection`'s rows in JSON form."""
    return {
        _key(texel): {
            "taps": [[bool(far), [int(tap[0]), int(tap[1])]] for far, tap in row["taps"]],
            "count": int(row["count"]),
            "decided": bool(row["decided"]),
            "fractions": row["fractions"],
            "bits": row["bits"],
        }
        for texel, row in found.items()
    }


def masks(analysed: dict[bool, dict[str, Any]], selections: pf.Selections) -> dict[str, Any]:
    """The primary mask (`tau_same`) and its listed exclusions (sorted texel keys); refused
    unless the fixed-support recipes equal the complete pipeline on every primary chain."""
    exact, oblique = analysed[True], analysed[False]
    texels = pf.matched(exact, oblique, pf.selection_mask(selections))
    status, clean = pf.coverage(exact, oblique, texels)
    same = {
        t for t in clean if exact["texels"][t]["tau_corners"] == oblique["texels"][t]["tau_corners"]
    }
    if pf.consistency(analysed, selections, sorted(same)) != 0:
        raise ValueError("the fixed-support recipes differ from the complete pipeline")
    matched = set(texels)
    return {
        "primary": sorted(_key(t) for t in same),
        "tau_other": sorted(_key(t) for t in clean - same),
        "not_clean": sorted(_key(t) for t in matched - clean),
        "unmatched": {
            twin: sorted(_key(t) for t in set(analysed[te.EXACT[twin]]["texels"]) - matched)
            for twin in te.TWINS
        },
        "far_texels": {twin: len(analysed[te.EXACT[twin]]["texels"]) for twin in te.TWINS},
        "status": dict(sorted(collections.Counter(status.values()).items())),
    }


def predictions(jobs: int = 5) -> dict[str, Any]:
    """Per ring texel of a copy slot (absolute texel key): its copy index and, per twin, its
    selection under every recipe (taps, count, decided, fractions, output bits); the copies,
    the masks and the meshes' hashes. Ring texels outside every slot (the anchors') are
    dropped."""
    for twin, path in MESH_PATHS.items():
        if path.read_bytes() != te.mesh(twin):
            raise ValueError(f"{path} differs from its generator")
    paths = {te.EXACT[twin]: str(path) for twin, path in MESH_PATHS.items()}
    keys = [(exact, r) for exact in (True, False) for r in RECIPES]
    with ProcessPoolExecutor(max(1, jobs)) as pool:
        traces = pool.map(pf._analyse_set, [paths[True], paths[False]])
        chosen = pool.map(pf.selection, [(paths[exact], r) for exact, r in keys])
        analysed = dict(zip((True, False), traces, strict=True))
        selections: pf.Selections = dict(zip(keys, chosen, strict=True))
    rings = {k: _plain(v) for k, v in selections.items()}
    if len({tuple(sorted(v)) for v in rings.values()}) != 1:
        raise ValueError("the recipes' or twins' ring populations differ")
    rows = copies()
    placed = te.layout(te.copies(True))[0]
    owners = fit.owner_copy(placed)
    texels: dict[str, Any] = {}
    for key in sorted(rings[(True, "double")], key=_texel):
        owner = owners.get(_texel(key))
        if owner is None:
            continue
        texels[key] = {
            "copy": owner,
            **{twin: {r: rings[(te.EXACT[twin], r)][key] for r in RECIPES} for twin in te.TWINS},
        }
    mask = masks(analysed, selections)
    if any(k not in texels for name in ("primary", "tau_other") for k in mask[name]):
        raise ValueError("a masked texel lies outside every copy slot")
    return {
        "reference": FROZEN_REFERENCE,
        "recipes": list(RECIPES),
        "pairing": PAIRING,
        "meshes": {
            twin: {
                "golden": te.GOLDENS[twin],
                "mesh": te.MESHES[twin],
                "mesh_sha256": hashlib.sha256(te.mesh(twin)).hexdigest(),
            }
            for twin in te.TWINS
        },
        "copies": rows,
        "mask": mask,
        "texels": texels,
    }


def membership(found: dict[str, Any]) -> dict[str, str]:
    """Texel key -> its mask (`primary`, `tau_other`, `not_clean`, `unmatched`), else `ring`."""
    mask = found["mask"]
    out = dict.fromkeys(found["texels"], "ring")
    for twin in te.TWINS:
        out.update(dict.fromkeys((k for k in mask["unmatched"][twin] if k in out), "unmatched"))
    for name in ("not_clean", "tau_other", "primary"):
        out.update(dict.fromkeys(mask[name], name))
    return out


def table(found: dict[str, Any]) -> dict[str, Any]:
    """The mask sizes and exclusions; the primary and tau_other strata sizes; per recipe pair,
    the masked texels whose predicted output bits differ on each twin and the joint patterns (A
    agree, D differ; x90 first); per recipe, the masked texels whose predicted bits differ
    between twins, in all and per stratum."""
    sets = membership(found)
    rows = found["copies"]
    mask = found["mask"]
    out: dict[str, Any] = {
        "copies": len(rows),
        "ring_texels": len(found["texels"]),
        "far_texels": mask["far_texels"],
        "masks": {
            "primary": len(mask["primary"]),
            "tau_other": len(mask["tau_other"]),
            "not_clean": len(mask["not_clean"]),
            "unmatched": {twin: len(mask["unmatched"][twin]) for twin in te.TWINS},
        },
        "far_status": mask["status"],
    }
    sizes: collections.Counter[str] = collections.Counter()
    pairs: dict[str, collections.Counter[str]] = {
        f"{a}|{b}": collections.Counter() for a, b in itertools.combinations(RECIPES, 2)
    }
    twin_differs: dict[str, collections.Counter[str]] = {r: collections.Counter() for r in RECIPES}
    for key, texel in found["texels"].items():
        name = sets[key]
        if name not in ("primary", "tau_other"):
            continue
        labels = [name, *(f"{name}:{s}" for s in strata(rows[texel["copy"]]))]
        for label in labels:
            sizes[label] += 1
        x90, oblique = texel["x90"], texel["oblique"]
        for a, b in itertools.combinations(RECIPES, 2):
            de, do = x90[a]["bits"] != x90[b]["bits"], oblique[a]["bits"] != oblique[b]["bits"]
            c = pairs[f"{a}|{b}"]
            c[f"{name}:x90"] += de
            c[f"{name}:oblique"] += do
            c[f"{name}:pattern:{'D' if de else 'A'}{'D' if do else 'A'}"] += 1
        for r in RECIPES:
            if x90[r]["bits"] != oblique[r]["bits"]:
                for label in labels:
                    twin_differs[r][label] += 1
    out["strata"] = dict(sorted(sizes.items()))
    out["bits_differ"] = {p: dict(sorted(c.items())) for p, c in pairs.items()}
    out["twin_differs"] = {r: dict(sorted(c.items())) for r, c in twin_differs.items()}
    out["discriminating"] = len(discriminating(found))
    return out


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _predicted(texel: dict[str, Any]) -> set[tuple[int, ...]]:
    return {tuple(texel[twin][r]["bits"]) for twin in te.TWINS for r in RECIPES}


def discriminating(found: dict[str, Any]) -> list[str]:
    """The ring texels where two (twin, recipe) predictions' output bits differ."""
    return [key for key, texel in found["texels"].items() if len(_predicted(texel)) > 1]


def compact(found: dict[str, Any]) -> dict[str, Any]:
    """The committed form of the predictions (predicted values only): the full predictions'
    SHA-256; the meshes, recipes, reference and pairing; per copy pair its slot, role and strata
    and, per twin and recipe, the SHA-256 of its ring's predicted output bits (texels in
    order); the masks (the frozen membership); and every discriminating ring texel with each
    twin's and recipe's fractions and output bits. The full predictions are reproduced by
    `predictions()` from the committed OBJs."""
    sets = membership(found)
    by_copy: dict[int, list[str]] = collections.defaultdict(list)
    for key, texel in found["texels"].items():
        by_copy[texel["copy"]].append(key)
    copies_out = []
    for row in found["copies"]:
        keys = sorted(by_copy[row["index"]], key=_texel)
        copies_out.append(
            {
                **row,
                "bits_sha256": {
                    twin: {
                        r: digest([[k, found["texels"][k][twin][r]["bits"]] for k in keys])
                        for r in RECIPES
                    }
                    for twin in te.TWINS
                },
            }
        )
    texels = [
        {
            "texel": key,
            "copy": found["texels"][key]["copy"],
            "mask": sets[key],
            **{
                twin: {
                    r: {k: found["texels"][key][twin][r][k] for k in ("fractions", "bits")}
                    for r in RECIPES
                }
                for twin in te.TWINS
            },
        }
        for key in sorted(discriminating(found), key=_texel)
    ]
    mask = found["mask"]
    return {
        "predictions_sha256": digest(found),
        "reference": found["reference"],
        "recipes": found["recipes"],
        "pairing": found["pairing"],
        "meshes": found["meshes"],
        "copies": copies_out,
        "mask": {k: mask[k] for k in ("primary", "tau_other", "not_clean", "unmatched")},
        "discriminating": texels,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=5)
    parser.add_argument("--out", type=Path, help="the full predictions (large; not committed)")
    parser.add_argument("--compact", type=Path, help="the committed compact predictions")
    args = parser.parse_args(argv)
    found = predictions(args.jobs)
    print(json.dumps(table(found), sort_keys=True))
    print(json.dumps({"predictions_sha256": digest(found)}))
    if args.out is not None:
        args.out.write_text(json.dumps(found, sort_keys=True), encoding="utf-8")
    if args.compact is not None:
        # Bytes, not text: the committed file keeps LF line ends on every platform (its SHA-256).
        args.compact.write_bytes((json.dumps(compact(found), sort_keys=True) + "\n").encode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
