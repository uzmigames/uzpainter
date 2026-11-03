"""Preflight of H1 (`padding_develop32`) on the committed turn-exact twins (item 2.7, A7b).

Authored geometry, the committed OBJs and kernel bitmaps and the frozen reference only: no
Painter data, no oracle store, no score. Stdout holds counts only.

**Frozen recipes.** The four frozen recipes (`double`, `pos32n+own32`, `rod32n+own32`,
`inv32n+own32`) are recomputed by `padding_turn_exact.predictions()`, which must hash to the
freeze and equal the committed compact predictions (`padding_turn_exact_score.frozen_problems`),
or nothing is compared.

**Masks** (fixed as declared, `masks`): the frozen primary mask (`tau_same`, 1,722 texels) of
the compact predictions and its 42-texel centre lane (copies at x = 54). H1 selects no subset:
where its selection differs, it is reported, never dropped.

**Reports** (`report`):
- `proof`: two separate claims. (1) The general identity: a rigid turn is affine and exact
  barycentrics sum to 1, so turning K's corners and then combining them is the turned point
  (decision 364's `developed()`); argued here and pinned by the authored tests. (2) Branch
  coverage: on both twins, every turned branch H1's complete selection computes
  (`padding_develop32.exercised`: frame and window turns, flip-window trials included,
  distinct by (texel, tap, J, tau, K), which are all the inputs of H1's turned distance) is
  checked in exact rationals (`identity`). Its counts cover those branches only. `status` is
  `invalid` on any rational difference (the preflight and its conclusion are void, the line
  stops and the exit code is 1), `uncertified` when a branch is inconclusive (an irrational
  frame; no epsilon) or none was checked, else `branches_equal`.
- `selection`: H1's complete pipeline (`padding_develop32.selection`) against each frozen
  recipe: kept taps and order, count, decided status.
- `bits` and `twins`: per frozen recipe, the masked texels whose predicted output bits differ
  from H1's on each twin and the joint patterns (A agree, D differ; x90 first); per recipe
  (H1 included), the masked texels whose predicted bits differ between twins.
- `stop`: the frozen recipes H1 is bit-indistinguishable from on the primary mask (both twins,
  every texel); any such recipe, or an `invalid` proof, stops the line.
- `reading`: zero predicted primary twin differences reject only this complete, fixed H1
  candidate against Painter's 31 observed (`padding-turn-exact-score.md`), not the whole
  double-development family. No A6 score is computed. While the proof is `uncertified`, the
  reading says so and certifies nothing.
- `receipt`: the SHA-256 of every input the run consumes (`receipt`), taken before and after the
  CPU work; the run refuses when one changed. The requests are not consumed and not validated
  here: their pins belong to the A6 freeze (`padding-turn-exact-freeze.md`).

    python -m tools.parity.fit.padding_develop_preflight [--jobs 5] [--out path]
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.fit import padding_develop32 as dev
from tools.parity.fit import padding_far32 as far32
from tools.parity.fit import padding_turn_exact as tefit
from tools.parity.fit import padding_turn_exact_preflight as pf
from tools.parity.fit import padding_turn_exact_score as scorer
from tools.parity.fit import padding_world_offset as fit
from tools.parity.fit import padding_world_offset_residual as res
from tools.parity.fit.padding_corpus import reference_text
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import padding_turn_exact as te
from tools.parity.tier0_semantics import padding_world_offset as wo
from tools.parity.tier0_semantics.recording_requests import REQUEST_FIXTURES, kernel_bitmaps

F32 = np.float32
Q = tuple[Fraction, ...]
Tap = tuple[int, int]
RECIPES = tefit.RECIPES
H1 = dev.RECIPE
# Painter's observed primary twin differences, from the committed aggregate report
# (`parity/reports/phase1/padding-turn-exact-score.md`); read, never recomputed here.
OBSERVED_PRIMARY_TWIN_DIFFERENCES = 31
SETS = ("primary", "centre")


# --- Exact affine identity -----------------------------------------------------------------


def barycentrics(tri: Any, texel: Tap, width: int, height: int) -> tuple[Fraction, ...]:
    """The exact barycentrics of texel `texel`'s centre in `tri`'s float32 UVs (v up), as
    `padding_turn_exact_preflight.exact_point` takes them: they sum to 1 and reproduce the
    centre exactly (checked). They are not decision 273's float32 weights."""
    u = [pf._q(c) for c in tri.uv]
    pu = (Fraction(texel[0]) + Fraction(1, 2)) / width
    pv = 1 - (Fraction(texel[1]) + Fraction(1, 2)) / height
    e0, e1 = pf._qsub(u[0], u[2]), pf._qsub(u[1], u[2])
    det = e0[0] * e1[1] - e0[1] * e1[0]
    du, dv = pu - u[2][0], pv - u[2][1]
    l0 = (e1[1] * du - e1[0] * dv) / det
    l1 = (e0[0] * dv - e0[1] * du) / det
    out = (l0, l1, 1 - l0 - l1)
    centre = tuple(
        sum((w * c[i] for w, c in zip(out, u, strict=True)), Fraction(0)) for i in (0, 1)
    )
    if sum(out) != 1 or centre != (pu, pv):
        raise ValueError("the exact barycentrics are wrong")
    return out


def _corners(tri: Any, similarity: tuple[Q, Fraction] | None) -> list[Q]:
    """`tri`'s raw float32 corners in rationals, or their exact image (p - c) r under the
    box normalisation's similarity (c, r) taken without rounding."""
    raw = [pf._q(c) for c in tri.p]
    if similarity is None:
        return raw
    c, r = similarity
    return [pf._qscale(pf._qsub(p, c), r) for p in raw]


def _unit_normal(corners: list[Q]) -> Q | None:
    n = pf._qcross(pf._qsub(corners[1], corners[0]), pf._qsub(corners[2], corners[0]))
    length = pf._qsqrt(pf._qdot(n, n))
    return None if length is None or length == 0 else pf._qscale(n, 1 / length)


def exact_frame(jc: list[Q], tc: list[Q]) -> dict[str, Q | Fraction] | None:
    """Decision 364's turn J -> tau in rationals (`developed`'s frame) from J's and tau's
    corners; None when a normal or the sine is irrational (or zero)."""
    n, m = _unit_normal(tc), _unit_normal(jc)
    if n is None or m is None:
        return None
    axis = pf._qcross(m, n)
    sine = pf._qsqrt(pf._qdot(axis, axis))
    if sine is None or sine == 0:
        return None
    axis = pf._qscale(axis, 1 / sine)
    dn, dm = pf._qdot(n, tc[0]), pf._qdot(m, jc[0])
    across = pf._qcross(m, axis)
    origin = pf._qscale(
        pf._qadd(pf._qscale(across, dn), pf._qscale(pf._qcross(axis, n), dm)),
        1 / pf._qdot(n, across),
    )
    return {"origin": origin, "axis": axis, "sine": sine, "cosine": pf._qdot(m, n)}


def _combine(weights: tuple[Fraction, ...], corners: list[Q]) -> Q:
    return tuple(
        sum((w * c[i] for w, c in zip(weights, corners, strict=True)), Fraction(0))
        for i in range(3)
    )


def developed_corners(
    ring: Any,
    entry: tuple[Any, ...],
    texel: Tap,
    tap: Tap,
    similarity: tuple[Q, Fraction] | None = None,
) -> Fraction | None:
    """H1's ideal geometry: the exact squared distance from q to P', with K's corners turned
    exactly J -> tau and P' their combination by the tap's exact barycentrics; in world space,
    or under the exact normalisation `similarity`. None when the frame is irrational."""
    _, _, _, j, tau, k = entry
    J, T, K = ring.tris[j], ring.tris[tau], ring.tris[k]
    tc = _corners(T, similarity)
    frame = exact_frame(_corners(J, similarity), tc)
    if frame is None:
        return None
    turned = [pf._qturn(frame, c) for c in _corners(K, similarity)]
    p = _combine(barycentrics(K, tap, ring.width, ring.height), turned)
    q = _combine(barycentrics(T, texel, ring.width, ring.height), tc)
    d = pf._qsub(q, p)
    return pf._qdot(d, d)


def similarity_of(ring: Any) -> tuple[Q, Fraction]:
    """The box normalisation's centre c and scale r (decision 273's float32 values), taken as
    an exact similarity."""
    lo, hi = (np.asarray(v).astype(F32) for v in ring.box)
    ext = (hi - lo).astype(F32)
    c = (lo + (ext * F32(0.5)).astype(F32)).astype(F32)
    return pf._q(c.tolist()), Fraction(far32._scale({}, ring))


def identity(
    ring: Any, entry: tuple[Any, ...], texel: Tap, tap: Tap, similarity: tuple[Q, Fraction]
) -> str:
    """`equal` when H1's ideal geometry equals `developed()` in world space and r^2 times it
    under the exact normalisation; `differ` otherwise; `inconclusive` when either side is
    irrational."""
    d = pf.developed(ring, entry, texel, tap)
    world = developed_corners(ring, entry, texel, tap)
    normalised = developed_corners(ring, entry, texel, tap, similarity)
    if d is None or world is None or normalised is None:
        return "inconclusive"
    r = similarity[1]
    return "equal" if world == d and normalised == r * r * d else "differ"


def proof(ring: Any, branches: dict[dev.Branch, int]) -> dict[str, dict[str, int]]:
    """Per ring texel key: the turned branches H1's complete selection computed on `ring`
    (`padding_develop32.exercised`: distinct (texel, tap, J, tau, K), every input of H1's
    turned distance, and their calls) by `identity` outcome. This checks the branches H1
    exercised on this mesh only; the general affine identity is the module's argument and the
    authored tests'."""
    sim = similarity_of(ring)
    out: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for (texel, tap, j, tau, k), calls in branches.items():
        c = out[tefit._key(texel)]
        c["calls"] += calls
        c["branches"] += 1
        c[identity(ring, ("turn", None, None, j, tau, k), texel, tap, sim)] += 1
    return {key: dict(c) for key, c in sorted(out.items())}


def proof_status(totals: dict[str, int]) -> str:
    """`invalid` on any rational difference (it voids the preflight and its conclusion);
    else `uncertified` when a branch is inconclusive or none was checked; else
    `branches_equal` (every exercised branch equal; no epsilon anywhere)."""
    if totals.get("differ", 0):
        return "invalid"
    if totals.get("inconclusive", 0) or not totals.get("branches", 0):
        return "uncertified"
    return "branches_equal"


# --- Comparison ----------------------------------------------------------------------------


def masks(found: dict[str, Any]) -> dict[str, list[str]]:
    """The frozen primary mask and its centre lane, as declared (no subset is selected)."""
    primary = list(found["mask"]["primary"])
    rows = found["copies"]
    centre = [k for k in primary if rows[found["texels"][k]["copy"]]["lane"] == "centre"]
    return {"primary": primary, "centre": centre}


def _support(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row["taps"], row["count"])


def report(
    found: dict[str, Any],
    h1: dict[str, dict[str, dict[str, Any]]],
    proofs: dict[str, dict[str, dict[str, int]]],
) -> dict[str, Any]:
    """The preflight's report (module docstring) from the frozen predictions `found`, H1's
    plain selections per twin (`padding_turn_exact._plain`) and the per-twin proofs."""
    sets = masks(found)
    keys = list(found["texels"])
    missing = {tw: sum(k not in h1[tw] for k in keys) for tw in te.TWINS}
    if any(missing.values()):
        raise ValueError(f"H1's ring lacks copy-slot texels: {missing}")
    universes = {**sets, "slots": keys}
    out: dict[str, Any] = {
        "masks": {name: len(v) for name, v in universes.items()},
        "proof": {},
        "selection": {},
        "bits": {},
        "twins": {},
    }
    primary = set(sets["primary"])
    totals: collections.Counter[str] = collections.Counter()
    for tw in te.TWINS:
        c: collections.Counter[str] = collections.Counter()
        for key, counts in proofs[tw].items():
            for outcome, n in counts.items():
                c[outcome] += n
                totals[outcome] += n
                if key in primary:
                    c[f"primary:{outcome}"] += n
        out["proof"][tw] = dict(sorted(c.items()))
    out["proof"]["status"] = proof_status(totals)
    for name, u in universes.items():
        sel: dict[str, Any] = {}
        for tw in te.TWINS:
            mine = [h1[tw][k] for k in u]
            row: dict[str, Any] = {"h1_undecided": sum(not m["decided"] for m in mine)}
            for r in RECIPES:
                theirs = [found["texels"][k][tw][r] for k in u]
                row[r] = {
                    "support_differs": sum(
                        _support(a) != _support(b) for a, b in zip(mine, theirs, strict=True)
                    ),
                    "decided_differs": sum(
                        a["decided"] != b["decided"] for a, b in zip(mine, theirs, strict=True)
                    ),
                }
            sel[tw] = row
        sel["h1_twins_support_differ"] = sum(
            _support(h1["x90"][k]) != _support(h1["oblique"][k])
            or h1["x90"][k]["decided"] != h1["oblique"][k]["decided"]
            for k in u
        )
        out["selection"][name] = sel
        bits: dict[str, dict[str, int]] = {}
        for r in RECIPES:
            pc: collections.Counter[str] = collections.Counter()
            for k in u:
                d = [h1[tw][k]["bits"] != found["texels"][k][tw][r]["bits"] for tw in te.TWINS]
                pc["x90"] += d[0]
                pc["oblique"] += d[1]
                pc[f"pattern:{''.join('D' if x else 'A' for x in d)}"] += 1
            bits[r] = dict(sorted(pc.items()))
        out["bits"][name] = bits
        twins = {H1: sum(h1["x90"][k]["bits"] != h1["oblique"][k]["bits"] for k in u)}
        for r in RECIPES:
            twins[r] = sum(
                found["texels"][k]["x90"][r]["bits"] != found["texels"][k]["oblique"][r]["bits"]
                for k in u
            )
        out["twins"][name] = twins
    out["stop"] = stop(out)
    out["reading"] = reading(out)
    return out


def stop(out: dict[str, Any]) -> dict[str, Any]:
    """The frozen recipes H1 is bit-indistinguishable from on the primary mask (every texel,
    both twins); on the copy slots too, descriptively. An `invalid` proof stops as well."""
    same = {
        name: [
            r for r in RECIPES if out["bits"][name][r]["x90"] + out["bits"][name][r]["oblique"] == 0
        ]
        for name in ("primary", "slots")
    }
    return {
        "indistinguishable": same["primary"],
        "slots_indistinguishable": same["slots"],
        "stop": bool(same["primary"]) or out["proof"]["status"] == "invalid",
    }


def reading(out: dict[str, Any]) -> str:
    """The declared reading of H1's predicted primary twin differences, voided by an `invalid`
    proof and never a certification while the proof is `uncertified`."""
    status = out["proof"]["status"]
    if status == "invalid":
        return (
            "invalid: H1's ideal geometry differs from developed() on an exercised branch; the "
            "preflight and its conclusion are void"
        )
    caveat = "" if status == "branches_equal" else "; proof uncertified: not certified"
    if out["stop"]["indistinguishable"]:
        same = ", ".join(out["stop"]["indistinguishable"])
        return f"stop: H1 is bit-indistinguishable from {same}{caveat}"
    n = out["twins"]["primary"][H1]
    if n == 0:
        return (
            "zero predicted primary twin differences: rejects only this complete, fixed H1 "
            f"candidate against Painter's observed {OBSERVED_PRIMARY_TWIN_DIFFERENCES}, not the "
            f"double-development family{caveat}"
        )
    return f"H1 predicts {n} primary twin differences; no score taken{caveat}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def receipt() -> dict[str, dict[str, str]]:
    """The SHA-256 (exact bytes) of every input the run consumes, by repo-relative path: the
    code closure (every `tools/` module loaded once every patched module the workers build has
    been built here), the frozen reference's text at its revision, both committed OBJs, the
    kernel bitmaps and the committed compact predictions."""
    dev.selection_module()
    for r in RECIPES:
        pf.selection_module(r)
    res.traced_module()
    tools = REPO_ROOT / "tools"
    code = {}
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if f and Path(f).resolve().is_relative_to(tools.resolve()):
            path = Path(f).resolve()
            code[path.relative_to(REPO_ROOT.resolve()).as_posix()] = _sha256(path.read_bytes())
    fixtures = [REQUEST_FIXTURES[name][1] for name in kernel_bitmaps(wo.RESOLUTION)]
    return {
        "code": dict(sorted(code.items())),
        "reference": {
            f"{fit.FROZEN_REFERENCE}:tests/export/padding_reference.py": _sha256(
                reference_text(fit.FROZEN_REFERENCE).encode("utf-8")
            )
        },
        "meshes": {
            Path(tefit.MESH_PATHS[tw]).relative_to(REPO_ROOT).as_posix(): _sha256(
                tefit.MESH_PATHS[tw].read_bytes()
            )
            for tw in te.TWINS
        },
        "kernel": {
            Path(f).as_posix(): _sha256((REPO_ROOT / f).read_bytes()) for f in sorted(fixtures)
        },
        "predictions": {
            scorer.COMPACT_PATH.relative_to(REPO_ROOT).as_posix(): _sha256(
                scorer.COMPACT_PATH.read_bytes()
            )
        },
    }


def changed(before: dict[str, dict[str, str]], after: dict[str, dict[str, str]]) -> list[str]:
    """The inputs whose hash differs, or that appear or vanish, between two receipts."""
    out = []
    for group in sorted(set(before) | set(after)):
        a, b = before.get(group, {}), after.get(group, {})
        out += [f"{group}:{k}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    return out


def h1_job(path: str) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, int]]]:
    """H1's plain selection on the OBJ at `path` and the proof of its exercised branches."""
    ring, found, branches = dev.exercised(path)
    return tefit._plain(found), proof(ring, branches)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=5)
    parser.add_argument("--out", type=Path, help="the report as JSON (counts only)")
    args = parser.parse_args(argv)
    before = receipt()
    problems = scorer.compact_problems()
    if problems:
        raise SystemExit("; ".join(problems))
    found = tefit.predictions(args.jobs)
    problems = scorer.frozen_problems(found)
    if problems:
        raise SystemExit("; ".join(problems))
    paths = [str(tefit.MESH_PATHS[tw]) for tw in te.TWINS]
    with ProcessPoolExecutor(max(1, args.jobs)) as pool:
        jobs = list(pool.map(h1_job, paths))
        h1 = {tw: job[0] for tw, job in zip(te.TWINS, jobs, strict=True)}
        proved = {tw: job[1] for tw, job in zip(te.TWINS, jobs, strict=True)}
    after = receipt()
    moved = changed(before, after)
    if moved:
        raise SystemExit("inputs changed during the run: " + ", ".join(moved))
    out = report(found, h1, proved)
    out["receipt"] = before
    out["h1_sha256"] = tefit.digest(h1)
    out["frozen_predictions_sha256"] = tefit.digest(found)
    text = json.dumps(out, sort_keys=True)
    print(text)
    if args.out is not None:
        args.out.write_bytes((text + "\n").encode())
    return 1 if out["proof"]["status"] == "invalid" else 0


if __name__ == "__main__":
    sys.exit(main())
