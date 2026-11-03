"""Preflight of the proposed padding probe `export-padding-turn-exact` (item 2.7, front A5).

Design and preflight only: no capture, no recording request, no production change. Authored
geometry, the committed kernel bitmaps and the frozen reference only; no Painter data, so stdout
and the return values hold no private value.

**Geometry** (`tier0_semantics/padding_turn_exact.py`). The world-offset probe's flat seam pairs
(`padding_world_offset.SHAPES` without a bend) and, per shape, an exact twin (`twin`): the same
shape with its far island folded at exactly 90 degrees, J's direction (a, b, c) -> (0, c, c). The UV
island, the band depth (from c) and every 3D length (|(a, b)| = c) are the oblique shape's, so the
intrinsic developed geometry is the same: in exact arithmetic the developed distance of every ring
texel's far tap is the same in both twins (invariant `developed_equal`). Both sets are built as the
world-offset copies (offsets, turns, scales, duplicates, z lanes; `copies`) in two meshes with
identical layouts and the same two box anchors (`mesh`), so that every exact copy sits in its
oblique twin's UV slot (the same kernel values) under the same mesh box and normalisation. The bent
shapes have no twin: a 90-degree J with the oblique J-K bend needs a K direction off the dyadic grid
(for b37-23v, (16, 63, 65)), whose band depth and positions are not exact.

**Held matched.** Each mesh runs the frozen reference (`padding_world_offset.FROZEN_REFERENCE`,
traced as `padding_world_offset_residual.traced_module`). A ring texel is compared only when it
is decided in both meshes, holds a far tap, and has the same chosen taps (texels, far flags, order)
and, per far tap, the same traced least-distance entries (kind, J, tau, K) in both (`matched`).
Each recipe keeps those taps and order. A far tap's stages and its exact geometry are compared
only on a `turn` tap (`tap_status`): the same gate outcomes in both twins, one least-distance
winner shared by every candidate, no tie, and the same winner in both twins. The other taps are
counted by status, and a texel all of whose far taps are `turn` taps is clean.

**Recipes** (`RECIPES`; far model of `padding_far32`, own taps). Candidates: the open turn
variants of hypothesis H (`docs/analysis/padding-world-offset-residuals/01-residual-diagnosis.md`
§7), each with decision 358's float32 own comparator in every chain (`own32`: in a chain with a
far tap, each own tap of tau's triangle takes `compare_distance` through tau, in world units).
Control: the production reference (`double`, no own32 in mixed chains). Stages (`STAGES`):

- `inputs`: q (tau) and P (K). Candidates: decision 273's `position32` of the box-normalised
  corners. Control: double barycentric world points.
- `frame` (normal, axis and origin): the float32 face normals of the raw corners (decision 278),
  unit; axis m x n over its length; the line's point by Cramer's rule through corner 0.
  `pos32n` in double; `rod32n` in float32 (GPU square root); `inv32n` as `rod32n` with the roles
  swapped (the axis negated).
- `turned`: `pos32n` P turned J -> tau by Rodrigues in double; `rod32n` the same in float32;
  `inv32n` q turned tau -> J in float32.
- `difference`: q - P' (`pos32n` double, `rod32n` float32); `inv32n` q' - P in float32.
- `norm`: `pos32n` the double square root; `rod32n` and `inv32n` decision 273's `distance32`
  (fma(d2, d2, fma(d1, d1, d0 d0)), GPU square root); divided by r in double.
- `fractions`: decision 268 over the chain's distances (own taps by own32); then the output bits.

Reports: (a) per stage and candidate pair, on the exact set and on the oblique twins, the
compared items that agree, differ or are unproved (`stage_agree`), and per recipe where a stage
rounds (`exact`). The entry stages compare rational values (value-exact; -0 equals +0); the
`fractions` and `output` stages compare uint32 bits. (b) Per recipe pair, the matched (and
clean) texels whose output bits differ on each set, and whether a recipe's bits differ between
twins. (c) Exact-arithmetic invariants (`Fraction`) and the coverage. Verdict per pair
(`verdict`): `mixed` when a stage provably differs or the downstream arithmetic differs
(`DOWNSTREAM`), `unknown` when a stage is unproved or a precondition fails (`preconditions`),
`turn_isolated` only otherwise. A discrimination of controlled recipes is never a causal
identification of Painter.

    python -m tools.parity.fit.padding_turn_exact_preflight [--jobs 2]
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import importlib
import itertools
import json
import math
import sys
import types
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.fit import padding_far32 as far32
from tools.parity.fit import padding_world_offset as fit
from tools.parity.fit import padding_world_offset_residual as res
from tools.parity.fit.padding_corpus import reference_text
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import padding_turn_exact as te
from tools.parity.tier0_semantics import padding_world_offset as wo
from tools.parity.tier0_semantics.padding_turn_exact import FLAT as FLAT
from tools.parity.tier0_semantics.padding_turn_exact import copies as copies
from tools.parity.tier0_semantics.padding_turn_exact import layout as layout
from tools.parity.tier0_semantics.padding_turn_exact import twin as twin

F32 = np.float32
Q = tuple[Fraction, ...]
Tap = tuple[int, int]
# Recipe -> (far model of `padding_far32`, own32).
RECIPES: dict[str, tuple[str, bool]] = {
    "pos32n+own32": ("pos32n", True),
    "rod32n+own32": ("rod32n", True),
    "inv32n+own32": ("inv32n", True),
    "double": ("double", False),
}
CANDIDATES = ("pos32n+own32", "rod32n+own32", "inv32n+own32")
STAGES = ("inputs", "frame", "turned", "difference", "norm", "fractions", "output")
# Per candidate: the arithmetic after the turn (difference, norm). A pair whose rows differ is
# never turn-isolated, whatever its stage agreement.
DOWNSTREAM = {
    "pos32n+own32": ("double q - P'", "double sqrt"),
    "rod32n+own32": ("float32 q - P'", "distance32 of (q - P')"),
    "inv32n+own32": ("float32 q' - P", "distance32 of (q' - P), components turned"),
}
OBJ_NAMES = {True: "turn-exact-preflight-exact.obj", False: "turn-exact-preflight-oblique.obj"}


# --- Geometry --------------------------------------------------------------------------------


def mesh(found: Sequence[wo.OffsetCopy]) -> bytes:
    """`padding_turn_exact.obj_bytes` of `found` under the preflight's own OBJ comment."""
    return te.obj_bytes(
        found, f"Turn-exact padding preflight: {len(found)} copies of flat seam pairs."
    )


# --- Exact arithmetic --------------------------------------------------------------------------


def _q(v: Sequence[Any]) -> Q:
    return tuple(Fraction(float(c)) for c in v)


def _qsub(a: Q, b: Q) -> Q:
    return tuple(x - y for x, y in zip(a, b, strict=True))


def _qdot(a: Q, b: Q) -> Fraction:
    return sum((x * y for x, y in zip(a, b, strict=True)), Fraction(0))


def _qcross(a: Q, b: Q) -> Q:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _qscale(a: Q, s: Fraction) -> Q:
    return tuple(c * s for c in a)


def _qadd(a: Q, b: Q) -> Q:
    return tuple(x + y for x, y in zip(a, b, strict=True))


def _qsqrt(x: Fraction) -> Fraction | None:
    """The rational square root of `x`, None when it is irrational."""
    n, d = math.isqrt(x.numerator), math.isqrt(x.denominator)
    return Fraction(n, d) if n * n == x.numerator and d * d == x.denominator else None


def _qturn(frame: dict[str, Q | Fraction], p: Q) -> Q:
    """Rodrigues' formula evaluated exactly on the frame's own (rounded) values:
    origin + v cos + (axis x v) sin + axis (axis . v)(1 - cos), v = p - origin."""
    o, a = frame["origin"], frame["axis"]
    s, c = frame["sine"], frame["cosine"]
    assert isinstance(o, tuple) and isinstance(a, tuple)
    assert isinstance(s, Fraction) and isinstance(c, Fraction)
    v = _qsub(p, o)
    turned = _qadd(_qadd(o, _qscale(v, c)), _qscale(_qcross(a, v), s))
    return _qadd(turned, _qscale(a, _qdot(a, v) * (1 - c)))


def _canon(v: Q) -> Q:
    """`v` up to sign: its first nonzero component positive."""
    sign = next((1 if c > 0 else -1 for c in v if c != 0), 1)
    return tuple(c * sign for c in v)


def _axis_unit(v: Q) -> bool:
    """Whether `v` is exactly a signed coordinate unit vector."""
    return sorted(abs(c) for c in v) == [0, 0, 1]


def exact_point(tri: Any, texel: Tap, width: int, height: int) -> Q:
    """The exact 3D point of texel `texel`'s centre through `tri`'s float32 UVs (v up) and its
    raw float32 corners, in rationals."""
    u = [_q(c) for c in tri.uv]
    pu = (Fraction(texel[0]) + Fraction(1, 2)) / width
    pv = 1 - (Fraction(texel[1]) + Fraction(1, 2)) / height
    e0, e1 = _qsub(u[0], u[2]), _qsub(u[1], u[2])
    det = e0[0] * e1[1] - e0[1] * e1[0]
    du, dv = pu - u[2][0], pv - u[2][1]
    l0 = (e1[1] * du - e1[0] * dv) / det
    l1 = (e0[0] * dv - e0[1] * du) / det
    p = [_q(c) for c in tri.p]
    return tuple(l0 * p[0][i] + l1 * p[1][i] + (1 - l0 - l1) * p[2][i] for i in range(3))


def _exact_normal(tri: Any) -> Q | None:
    p = [_q(c) for c in tri.p]
    n = _qcross(_qsub(p[1], p[0]), _qsub(p[2], p[0]))
    length = _qsqrt(_qdot(n, n))
    return None if length is None else _qscale(n, 1 / length)


def developed(ring: Any, entry: Sequence[Any], texel: Tap, tap: Tap) -> Fraction | None:
    """The exact squared distance from q to P turned rigidly from J's plane onto tau's (decision
    364's turn in rationals, from the authored corners); None when a normal or the sine is
    irrational."""
    _, _, _, j, tau, k = entry
    J, T, K = ring.tris[j], ring.tris[tau], ring.tris[k]
    n, m = _exact_normal(T), _exact_normal(J)
    if n is None or m is None:
        return None
    axis = _qcross(m, n)
    sine = _qsqrt(_qdot(axis, axis))
    if sine is None or sine == 0:
        return None
    axis = _qscale(axis, 1 / sine)
    dn, dm = _qdot(n, _q(T.p[0])), _qdot(m, _q(J.p[0]))
    across = _qcross(m, axis)
    origin = _qscale(
        _qadd(_qscale(across, dn), _qscale(_qcross(axis, n), dm)), 1 / _qdot(n, across)
    )
    frame: dict[str, Q | Fraction] = {
        "origin": origin,
        "axis": axis,
        "sine": sine,
        "cosine": _qdot(m, n),
    }
    q = exact_point(T, texel, ring.width, ring.height)
    p = _qturn(frame, exact_point(K, tap, ring.width, ring.height))
    d = _qsub(q, p)
    return _qdot(d, d)


# --- Staged recipes ----------------------------------------------------------------------------


def _frame64(ref: dict[str, Any], source: Any, target: Any, sp0: Any, tp0: Any) -> list[Any]:
    """`padding_far32._rotate64`'s frame, operation for operation (n, m, axis, sine, cosine,
    origin)."""
    unit, cross, dot, norm = ref["unit"], ref["cross"], ref["dot"], ref["norm"]
    scale, add = ref["scale"], ref["add"]
    n = unit(tuple(float(c) for c in target.normal))
    m = unit(tuple(float(c) for c in source.normal))
    axis = cross(m, n)
    sine = norm(axis)
    cosine = dot(m, n)
    axis = scale(axis, 1.0 / sine)
    dn = dot(n, tuple(float(c) for c in tp0))
    dm = dot(m, tuple(float(c) for c in sp0))
    across = cross(m, axis)
    det = dot(n, across)
    origin = scale(add(scale(across, dn), scale(cross(axis, n), dm)), 1.0 / det)
    return [n, m, axis, sine, cosine, origin]


def _turn64(ref: dict[str, Any], frame: Sequence[Any], p: Any) -> Any:
    cross, dot, scale, add, sub = ref["cross"], ref["dot"], ref["scale"], ref["add"], ref["sub"]
    _, _, axis, sine, cosine, origin = frame
    v = sub(p, origin)
    turned = add(add(origin, scale(v, cosine)), scale(cross(axis, v), sine))
    return add(turned, scale(axis, dot(axis, v) * (1.0 - cosine)))


def _frame32(ref: dict[str, Any], source: Any, target: Any, sp0: Any, tp0: Any) -> list[Any]:
    """`padding_far32._rodrigues32`'s frame, operation for operation."""
    f32, dot, cross = ref["f32"], ref["_dot32"], ref["_cross32"]
    add, scale, unit = ref["_add32"], ref["_scale32"], ref["_unit32"]
    n = unit([F32(c) for c in target.normal])
    m = unit([F32(c) for c in source.normal])
    axis = cross(m, n)
    sine = F32(ref["hwmath"].sqrt(np.array([dot(axis, axis)], F32))[0])
    cosine = dot(m, n)
    axis = [f32(c / sine) for c in axis]
    dn, dm = dot(n, tp0), dot(m, sp0)
    across = cross(m, axis)
    det = dot(n, across)
    origin = scale(add(scale(across, dn), scale(cross(axis, n), dm)), f32(F32(1) / det))
    return [n, m, axis, sine, cosine, origin]


def _turn32(ref: dict[str, Any], frame: Sequence[Any], p: Any) -> Any:
    f32, dot, cross = ref["f32"], ref["_dot32"], ref["_cross32"]
    sub, add, scale = ref["_sub32"], ref["_add32"], ref["_scale32"]
    _, _, axis, sine, cosine, origin = frame
    v = sub([F32(c) for c in p], origin)
    turned = add(add(origin, scale(v, cosine)), scale(cross(axis, v), sine))
    return add(turned, scale(axis, f32(dot(axis, v) * f32(F32(1) - cosine))))


def staged(
    recipe: str, ref: dict[str, Any], ring: Any, entry: Sequence[Any], texel: Tap, tap: Tap
) -> dict[str, Any]:
    """One turned far entry ("turn", q, p, J, tau, K) under `recipe`, stage by stage, in
    rationals of the computed values: `q` and `p` (inputs), `frame` (n, m, axis, sine, cosine,
    origin and the two plane points), `moved` (the point the recipe turns), `turned`, `fixed`
    (the other point), `difference`, `length` (before the division by r) and `distance` (world
    units, `padding_far32.far_distance`'s value, checked)."""
    _, q, p, j, tau, k = entry
    J, T, K = ring.tris[j], ring.tris[tau], ring.tris[k]
    model = RECIPES[recipe][0]
    w, h = ring.width, ring.height
    if model == "double":
        qi, pi, unit = q, p, 1.0
        frame = _frame64(ref, J, T, J.p[0], T.p[0])
        sp0, tp0 = J.p[0], T.p[0]
    else:
        pos = ref["position32"]
        qi = pos(T.uv, T.normalised, w, h, *texel)
        pi = pos(K.uv, K.normalised, w, h, *tap)
        unit = far32._scale(ref, ring)
        j0, t0 = J.normalised[0], T.normalised[0]
        if model == "pos32n":
            frame = _frame64(ref, J, T, j0, t0)
            sp0, tp0 = j0, t0
        elif model == "rod32n":
            frame = _frame32(ref, J, T, j0, t0)
            sp0, tp0 = j0, t0
        else:
            frame = _frame32(ref, T, J, t0, j0)
            sp0, tp0 = t0, j0
    if model in ("double", "pos32n"):
        moved = tuple(float(c) for c in pi)
        fixed = tuple(float(c) for c in qi)
        turned = _turn64(ref, frame, moved)
        d = ref["sub"](fixed, turned)
        length = float(ref["norm"](d))
    else:
        f32 = ref["f32"]
        moved, fixed = (pi, qi) if model == "rod32n" else (qi, pi)
        turned = _turn32(ref, frame, moved)
        a, b = (fixed, turned) if model == "rod32n" else (turned, fixed)
        d = [f32(a[c] - b[c]) for c in range(3)]
        length = float(ref["distance32"](a, b))
    distance = length / unit
    check = far32.far_distance(model, ref, ring, q, p, j, tau, k, texel, tap)
    if distance != check:
        raise ValueError(f"the staged {recipe} differs from padding_far32")
    n, m, axis, sine, cosine, origin = frame
    return {
        "q": _q(qi),
        "p": _q(pi),
        "frame": {
            "n": _q(n),
            "m": _q(m),
            "axis": _q(axis),
            "sine": Fraction(float(sine)),
            "cosine": Fraction(float(cosine)),
            "origin": _q(origin),
            "target_p0": _q(tp0),
            "source_p0": _q(sp0),
        },
        "moved": _q(moved),
        "turned": _q(turned),
        "fixed": _q(fixed),
        "forward": model != "inv32n",
        "difference": _q(d),
        "length": Fraction(length),
        "distance": distance,
    }


def stage_keys(s: dict[str, Any]) -> dict[str, Any]:
    """A staged entry's comparable keys (frame-independent where the recipes' frames differ) and
    its stage-local exactness flags."""
    fr = s["frame"]
    d = s["difference"]
    squared = _qdot(d, d)
    exact_d = _qsub(s["fixed"], s["turned"]) if s["forward"] else _qsub(s["turned"], s["fixed"])
    a = fr["axis"]
    return {
        "inputs": (s["q"], s["p"]),
        "frame": (
            tuple(sorted((fr["n"], fr["m"]))),
            _canon(a),
            fr["sine"],
            fr["cosine"],
            fr["origin"],
        ),
        "turn_exact": s["turned"] == _qturn(fr, s["moved"]),
        "turned": s["turned"] if s["forward"] else None,
        "difference": squared,
        "difference_exact": d == exact_d,
        "norm": s["length"],
        "norm_exact": s["length"] * s["length"] == squared,
        "d_abs": tuple(sorted(abs(c) for c in d)),
        # Invariants.
        "normals_exact": _axis_unit(fr["n"]) and _axis_unit(fr["m"]),
        "trig_exact": fr["cosine"] == 0 and fr["sine"] == 1,
        "origin_on_line": (
            _qdot(fr["n"], fr["origin"]) == _qdot(fr["n"], fr["target_p0"])
            and _qdot(fr["m"], fr["origin"]) == _qdot(fr["m"], fr["source_p0"])
            and _qdot(a, fr["origin"]) == 0
        ),
        "axial_kept": _qdot(a, s["turned"]) == _qdot(a, s["moved"]),
        "origin": fr["origin"],
        "axis": a,
        # The frame's Rodrigues map is exactly a rotation: unit axis and sin^2 + cos^2 = 1.
        "rotation": _qdot(a, a) == 1 and fr["sine"] ** 2 + fr["cosine"] ** 2 == 1,
    }


# --- One mesh ----------------------------------------------------------------------------------


def traced(path: Path, source: np.ndarray) -> Any:
    """`padding_world_offset_residual.Traced` of the OBJ at `path` (the frozen reference with
    `farhook`, model double, traced) over the kernel `source`."""
    holder: Any = importlib.import_module(res._SELF)
    module = res.traced_module()
    holder.TRACE = {}
    try:
        ring = module.Ring(path, wo.MATERIAL, wo.RESOLUTION, wo.RESOLUTION)
        ring._flip = False
        chosen = {(x, y): list(cands[:count]) for x, y, cands, count in ring.texels()}
        trace = holder.TRACE
    finally:
        holder.TRACE = None
    t: Any = object.__new__(res.Traced)
    t.module, t.ref, t.ring, t.chosen, t.trace, t.source = (
        module,
        module.__dict__,
        ring,
        chosen,
        trace,
        source,
    )
    return t


def _tau(t: Any, texel: Tap) -> int:
    """Decision 279's tau of ring texel `texel` (`Ring.tau` over its covered neighbours)."""
    x, y = texel
    ring = t.ring
    own = [
        ((x + dx) % ring.width, y + dy)
        for dy, dx in t.ref["NEIGHBOURS"]
        if 0 <= y + dy < ring.height and ring.owner[y + dy, (x + dx) % ring.width] >= 0
    ]
    return int(ring.tau(x, y, own))


def _entry_key(entry: Sequence[Any]) -> tuple[Any, ...]:
    """A traced entry's identity: its kind and arguments (the plain distance, or q, P, J, tau,
    K of a turn)."""
    return tuple(entry)


def _bits(values: Sequence[Any]) -> list[int]:
    return [int(b) for b in np.asarray(values, F32).view(np.uint32)]


def analyse(path: Path, source: np.ndarray | None = None) -> dict[str, Any]:
    """Every ring texel of the OBJ at `path` that holds a far tap: its taps, undecided flag,
    traced entry structure, tau's corners, own-tap distances, and per recipe the fractions and
    output bits; per far tap the least-distance branch and, on a turned entry, each recipe's
    `stage_keys`, the seam anchor and the exact `developed` distance."""
    t = traced(path, fit.source() if source is None else source)
    ref, ring = t.ref, t.ring
    production_check = 0
    texels: dict[Tap, dict[str, Any]] = {}
    for texel, chosen in t.chosen.items():
        if not any(far for _, far, _ in chosen):
            continue
        entries = {tap: t.trace.get(texel, {}).get(tap, []) for _, far, tap in chosen if far}
        tau = _tau(t, texel)
        T = ring.tris[tau]
        own_mask = res.own_tau32(t, texel, "tau")
        row: dict[str, Any] = {
            "taps": [(far, tap) for _, far, tap in chosen],
            "undecided": bool(ring.undecided.get(texel)),
            "entries": {
                tap: [(e[0],) if e[0] == "plain" else ("turn", e[3], e[4], e[5]) for e in es]
                for tap, es in entries.items()
            },
            "tau_corners": T.normalised.astype(F32).tobytes(),
            "own": [
                Fraction(
                    float(
                        ref["compare_distance"](
                            T.uv, T.normalised, ring.width, ring.height, texel, tap
                        )
                    )
                )
                for (_, _, tap), own in zip(chosen, own_mask, strict=True)
                if own
            ],
            "far": {},
            "recipes": {},
        }
        values: dict[str, dict[Tap, float]] = {r: {} for r in RECIPES}
        for tap, es in entries.items():
            per: dict[str, list[float]] = {r: [] for r in RECIPES}
            stages: dict[str, list[dict[str, Any] | None]] = {r: [] for r in RECIPES}
            for e in es:
                if e[0] == "plain":
                    for r in RECIPES:
                        per[r].append(e[1])
                        stages[r].append(None)
                    continue
                _, q, p, j, tau_e, k = e
                if not far32.turns(ref, ring.tris[j], ring.tris[tau_e]):
                    d = far32.far_distance("double", ref, ring, q, p, j, tau_e, k, texel, tap)
                    for r in RECIPES:
                        per[r].append(d)
                        stages[r].append(None)
                    continue
                for r in RECIPES:
                    s = staged(r, ref, ring, e, texel, tap)
                    per[r].append(s["distance"])
                    stages[r].append(s)
            # A tie is ambiguous only between distinct entries: a window that repeats the same
            # turn (the same q, P, J, tau, K) repeats its entry, not its branch.
            keys = [_entry_key(e) for e in es]
            ties = {
                r: tuple(
                    n for n, v in enumerate(per[r]) if v == min(per[r]) and keys.index(keys[n]) == n
                )
                for r in RECIPES
            }
            winner = {r: ties[r][0] if ties[r] else -1 for r in RECIPES}
            for r in RECIPES:
                if per[r]:
                    values[r][tap] = per[r][winner[r]]
            gates = tuple(
                "plain" if e[0] == "plain" else "turn" if stages[CANDIDATES[0]][n] else "flat"
                for n, e in enumerate(es)
            )
            common: int | None = winner[CANDIDATES[0]]
            if common is None or common < 0 or len({winner[r] for r in CANDIDATES}) != 1:
                common = None
            info: dict[str, Any] = {
                "gates": gates,
                "winner": winner,
                "ties": ties,
                "common": common,
                "kind": "none" if common is None else gates[common],
                "stages": {},
            }
            if common is not None and gates[common] == "turn":
                entry = es[common]
                info["stages"] = {
                    r: stage_keys(stages[r][common])  # type: ignore[arg-type]
                    for r in CANDIDATES
                }
                seam = res._seam(t, entry[4], entry[3], entry[1])
                info["anchor"] = (
                    None if seam is None else _q(ring.tris[seam[0]].normalised[(seam[1] + 1) % 3])
                )
                info["developed"] = developed(ring, entry, texel, tap)
            row["far"][tap] = info
        unit = far32._scale(ref, ring)
        for r, (_, own32) in RECIPES.items():
            ds = [values[r].get(tap, d) if far else d for d, far, tap in chosen]
            if own32:
                own_values = iter(row["own"])
                for n, own in enumerate(own_mask):
                    if own:
                        ds[n] = float(next(own_values)) / unit
            fr = t.module.fractions(ds)
            row["recipes"][r] = {"fractions": _bits(fr), "bits": res.chain_bits(t, texel, fr)}
        production = _bits(ring.chain_fractions(*texel, chosen))
        if row["recipes"]["double"]["fractions"] != production:
            production_check += 1
        texels[texel] = row
    if production_check:
        raise ValueError(f"the trace differs from the reference on {production_check} texels")
    lo, hi = ring.box
    return {
        "box": (lo.astype(F32).tobytes(), hi.astype(F32).tobytes()),
        "scale": far32._scale(ref, ring),
        "texels": texels,
    }


def selection_module(recipe: str) -> Any:
    """The frozen reference with the recipe's far model in the whole pipeline (`farhook`, then
    `fm<model>` as the freeze's `padding_world_offset.module`), so that it changes which taps
    are kept, their order, the tap count and the undecided flags; and for a candidate
    `own32mix` (`padding_world_offset_residual.own32_mixed`), which changes fractions only."""
    model, own32 = RECIPES[recipe]
    text = reference_text(fit.FROZEN_REFERENCE)
    names = fit.policy(model).split("+")
    for name in names:
        for old, new in far32.PATCHES[name]:
            if text.count(old) != 1:
                raise ValueError(f"patch {name} does not apply")
            text = text.replace(old, new)
    if own32:
        if text.count(res._OWN_OLD) != 1:
            raise ValueError("own32mix does not apply")
        text = text.replace(res._OWN_OLD, res._OWN_NEW)
    module = types.ModuleType(f"turn_exact_{model}")
    label = f"padding_reference@{fit.FROZEN_REFERENCE}+{fit.policy(model)}"
    exec(compile(text, label, "exec"), module.__dict__)
    return module


def selection(job: tuple[str, str]) -> dict[Tap, dict[str, Any]]:
    """The complete pipeline of `recipe` on the OBJ at `path`: per ring texel, its kept taps
    (far flags, texels, in order), the tap count, whether it is decided, and its fractions and
    24 output bits over the kernel bitmaps."""
    path, recipe = job
    m = selection_module(recipe)
    ring = m.Ring(Path(path), wo.MATERIAL, wo.RESOLUTION, wo.RESOLUTION)
    values_of = fit.source()
    out: dict[Tap, dict[str, Any]] = {}
    for x, y, cands, count in ring.texels():
        taps = cands[:count]
        weights = ring.chain_fractions(x, y, taps)
        values = np.asarray([values_of[ty, tx] for _, _, (tx, ty) in taps], F32)
        bits = np.array([m.chain(values[:, c], weights) for c in range(24)], F32)
        out[(x, y)] = {
            "taps": [(far, tap) for _, far, tap in taps],
            "count": count,
            "decided": not ring.undecided.get((x, y)),
            "fractions": _bits(weights),
            "bits": [int(b) for b in bits.view(np.uint32)],
        }
    return out


Selections = dict[tuple[bool, str], dict[Tap, dict[str, Any]]]


def selection_mask(selections: Selections) -> set[Tap]:
    """The ring texels whose complete selection is the same under every recipe in both meshes:
    the same kept taps (far flags, texels, order), the same count, decided everywhere, and a far
    tap."""
    rings = [set(v) for v in selections.values()]
    common = set.intersection(*rings)
    out = set()
    for texel in common:
        rows = [v[texel] for v in selections.values()]
        first = rows[0]
        if not first["decided"] or not any(far for far, _ in first["taps"]):
            continue
        if all(
            r["decided"] and r["taps"] == first["taps"] and r["count"] == first["count"]
            for r in rows
        ):
            out.add(texel)
    return out


def selection_report(selections: Selections) -> dict[str, Any]:
    """Per mesh and recipe, the ring texels with a far tap under some recipe whose selection
    (taps, order, count, decided) differs from the production control's; and per mesh and
    recipe pair, the texels whose complete-pipeline output bits differ, split by whether the
    selection is the same (`support_same`) or not."""
    out: dict[str, Any] = {"ring_equal": len({frozenset(v) for v in selections.values()}) == 1}
    for exact in (True, False):
        name = "exact" if exact else "oblique"
        rows = {r: selections[(exact, r)] for r in RECIPES}
        texels = set.intersection(*(set(v) for v in rows.values()))
        far = {t for t in texels if any(any(f for f, _ in rows[r][t]["taps"]) for r in RECIPES)}

        def key(r: str, t: Tap, rows: dict[str, Any] = rows) -> tuple[Any, ...]:
            row = rows[r][t]
            return (row["taps"], row["count"], row["decided"])

        out[name] = {
            "far_texels": len(far),
            "selection_differs_from_double": {
                r: sum(key(r, t) != key("double", t) for t in far) for r in CANDIDATES
            },
            "bits_differ": {
                _pair(a, b): {
                    "support_same": sum(
                        key(a, t) == key(b, t) and rows[a][t]["bits"] != rows[b][t]["bits"]
                        for t in far
                    ),
                    "support_differs": sum(
                        key(a, t) != key(b, t) and rows[a][t]["bits"] != rows[b][t]["bits"]
                        for t in far
                    ),
                }
                for a, b in itertools.combinations(RECIPES, 2)
            },
        }
    return out


def consistency(
    found: dict[bool, dict[str, Any]], selections: Selections, texels: Sequence[Tap]
) -> int:
    """The compared texels whose fixed-support fractions and output bits (`analyse`) differ
    from the complete pipeline's under the same recipe (must be zero)."""
    bad = 0
    for exact, data in found.items():
        for texel in texels:
            for r in RECIPES:
                mine = data["texels"][texel]["recipes"][r]
                full = selections[(exact, r)][texel]
                bad += mine["fractions"] != full["fractions"] or mine["bits"] != full["bits"]
    return bad


# --- Both sets ---------------------------------------------------------------------------------


def matched(
    exact: dict[str, Any], oblique: dict[str, Any], mask: set[Tap] | None = None
) -> list[Tap]:
    """The ring texels compared: in `mask` (`selection_mask`: the same complete selection under
    every recipe in both meshes) when given, decided in both sets, a far tap, the same chosen
    taps (texels, far flags, order) and the same traced entries per far tap (kind, J, tau,
    K)."""
    out = []
    for texel, a in exact["texels"].items():
        b = oblique["texels"].get(texel)
        if b is None or a["undecided"] or b["undecided"]:
            continue
        if mask is not None and texel not in mask:
            continue
        if a["taps"] == b["taps"] and a["entries"] == b["entries"]:
            out.append(texel)
    return sorted(out)


def tap_status(a: dict[str, Any], b: dict[str, Any]) -> str:
    """A far tap's coverage across the twins (`a` exact, `b` oblique): `gates_differ` (the turn
    gate decides another entry list), `branch_within` (the candidates' least-distance winners
    differ within a set), `tie` (a candidate's least distance is reached by several entries),
    `branch_twins` (the twins' common winners differ), else the winner's kind (`turn`, `plain`
    or `flat`, the same in both). Stages and geometry are compared on `turn` taps only."""
    if a["gates"] != b["gates"]:
        return "gates_differ"
    if a["common"] is None or b["common"] is None:
        return "branch_within"
    if any(len(info["ties"][r]) > 1 for info in (a, b) for r in CANDIDATES):
        return "tie"
    if a["common"] != b["common"]:
        return "branch_twins"
    return str(a["kind"])


Status = dict[tuple[Tap, Tap], str]


def coverage(
    exact: dict[str, Any], oblique: dict[str, Any], texels: Sequence[Tap]
) -> tuple[Status, set[Tap]]:
    """Every matched far tap's `tap_status`, and the clean texels (every far tap `turn`)."""
    status = {
        (texel, tap): tap_status(info, oblique["texels"][texel]["far"][tap])
        for texel in texels
        for tap, info in exact["texels"][texel]["far"].items()
    }
    clean = {
        texel
        for texel in texels
        if all(status[(texel, tap)] == "turn" for tap in exact["texels"][texel]["far"])
    }
    return status, clean


PAIRS = tuple(itertools.combinations(CANDIDATES, 2))


def _pair(a: str, b: str) -> str:
    return f"{a.split('+')[0]}|{b.split('+')[0]}"


def stage_agree(stage: str, a: dict[str, Any], b: dict[str, Any]) -> str:
    """Two candidates' `stage_keys` at `stage`: `agree`, `differ` or `unproved`. `inputs`,
    `frame`, `difference` (the exact squared length of the computed difference) and `norm` (the
    computed length) compare rational values: value-exact, with -0 equal to +0, not bitwise.
    `turned`: two forward turns compare their turned points (both in tau's frame); a forward and
    an inverse turn agree only when the inverse is proved: equal canonical frames, opposite
    axes, each frame's map an exact rotation (`rotation`), and both turns exact (no rounding).
    Otherwise (other frames, no proof, or a rounded turn on either side) the stage is
    `unproved`, not a cause: no discrepancy is proved in a common frame."""
    if stage != "turned":
        return "agree" if a[stage] == b[stage] else "differ"
    if a["turned"] is not None and b["turned"] is not None:
        return "agree" if a["turned"] == b["turned"] else "differ"
    opposite = a["axis"] == tuple(-c for c in b["axis"])
    if a["frame"] != b["frame"] or not (opposite and a["rotation"] and b["rotation"]):
        return "unproved"
    # A rounded turn on either side is no proved discrepancy: the two rounding errors are not
    # compared in a common frame and can line up.
    return "agree" if a["turn_exact"] and b["turn_exact"] else "unproved"


def stage_table(
    found: dict[str, Any], texels: Sequence[Tap], status: Status, clean: set[Tap]
) -> dict[str, Any]:
    """(a) on one set: per stage and candidate pair, the compared items that `agree`, `differ`
    or are `unproved` (`stage_agree`), and `all` (every pair agrees). Entry stages count the
    `turn` taps; `fractions` and `output` (bitwise, uint32) count the clean texels. Per
    candidate, how many of its `turned`, `difference` and `norm` stages are exact (no
    rounding)."""
    counts: dict[str, collections.Counter[str]] = {s: collections.Counter() for s in STAGES}
    exact: dict[str, collections.Counter[str]] = {r: collections.Counter() for r in CANDIDATES}
    for texel in texels:
        row = found["texels"][texel]
        for tap, info in row["far"].items():
            if status[(texel, tap)] != "turn":
                continue
            keys = info["stages"]
            for stage in STAGES[:5]:
                results = [stage_agree(stage, keys[a], keys[b]) for a, b in PAIRS]
                counts[stage]["compared"] += 1
                counts[stage]["all"] += all(r == "agree" for r in results)
                for (a, b), result in zip(PAIRS, results, strict=True):
                    counts[stage][f"{_pair(a, b)}:{result}"] += 1
            for r in CANDIDATES:
                for flag in ("turn_exact", "difference_exact", "norm_exact"):
                    exact[r][flag] += keys[r][flag]
        if texel not in clean:
            continue
        for stage, key in (("fractions", "fractions"), ("output", "bits")):
            results = [
                "agree" if row["recipes"][a][key] == row["recipes"][b][key] else "differ"
                for a, b in PAIRS
            ]
            counts[stage]["compared"] += 1
            counts[stage]["all"] += all(r == "agree" for r in results)
            for (a, b), result in zip(PAIRS, results, strict=True):
                counts[stage][f"{_pair(a, b)}:{result}"] += 1
    return {
        "stages": {s: dict(sorted(counts[s].items())) for s in STAGES},
        "equivalent": {
            s: counts[s]["compared"] > 0 and counts[s]["all"] == counts[s]["compared"]
            for s in STAGES
        },
        "exact": {r: dict(sorted(c.items())) for r, c in exact.items()},
    }


def discrimination(
    exact: dict[str, Any], oblique: dict[str, Any], texels: Sequence[Tap], clean: set[Tap]
) -> dict[str, Any]:
    """(b) per recipe pair (candidates and the control), the matched texels whose output bits
    differ on the exact set, on the oblique set, and the four joint patterns (A agree, D differ;
    exact set first), in all and on the clean texels (`clean:`), also split by whether tau's
    corners are bit-identical in both twins (`tau_same`: tau in island A) or not (`tau_other`:
    q and the own taps move too); per recipe, the texels whose bits differ between twins (the
    same taps and kernel values: a rounding-driven change), in all and clean."""
    pairs: dict[str, dict[str, int]] = {}
    for a, b in itertools.combinations(RECIPES, 2):
        c: collections.Counter[str] = collections.Counter()
        for texel in texels:
            ex = exact["texels"][texel]["recipes"]
            ob = oblique["texels"][texel]["recipes"]
            de, do = ex[a]["bits"] != ex[b]["bits"], ob[a]["bits"] != ob[b]["bits"]
            same = exact["texels"][texel]["tau_corners"] == oblique["texels"][texel]["tau_corners"]
            pattern = f"{'D' if de else 'A'}{'D' if do else 'A'}"
            side = "tau_same" if same else "tau_other"
            for prefix in ("", "clean:") if texel in clean else ("",):
                c[f"{prefix}exact"] += de
                c[f"{prefix}oblique"] += do
                c[f"{prefix}pattern:{pattern}"] += 1
                c[f"{prefix}{side}:{pattern}"] += 1
        pairs[_pair(a, b)] = dict(sorted(c.items()))
    twins: dict[str, dict[str, int]] = {}
    for r in RECIPES:
        differs = [
            t
            for t in texels
            if exact["texels"][t]["recipes"][r]["bits"]
            != oblique["texels"][t]["recipes"][r]["bits"]
        ]
        twins[r] = {"all": len(differs), "clean": sum(t in clean for t in differs)}
    return {"pairs": pairs, "twin_differs": twins}


def invariants(
    exact: dict[str, Any],
    oblique: dict[str, Any],
    texels: Sequence[Tap],
    status: Status,
    clean: set[Tap],
) -> dict[str, Any]:
    """(c) exact-arithmetic invariants (rationals of the computed values) on the `turn` taps,
    per set: the nominal normals are exact signed unit vectors; cos = 0 and sin = 1 exactly;
    each frame's map is an exact rotation; the Cramer origin lies exactly on both planes with
    zero axial component; the Cramer origin differs from the seam edge's vertex (the edge fold's
    anchor); the turned point keeps the moved point's axial component; inv32n's difference is a
    signed permutation of rod32n's and, then, whether their lengths still differ; on taps whose
    Cramer origin is the normalised centre (`origin_zero`), which candidate pairs agree at every
    entry stage. Across twins, on the same winner only: the exact developed distance is equal;
    own taps through a bit-identical tau give equal distances (clean texels). Also the box and
    scale, and the coverage (`tap_status` counts, clean texels)."""
    out: dict[str, Any] = {
        "box_equal": exact["box"] == oblique["box"] and exact["scale"] == oblique["scale"],
        "coverage": dict(sorted(collections.Counter(status.values()).items())),
        "clean_texels": len(clean),
    }
    for name, found in (("exact", exact), ("oblique", oblique)):
        c: collections.Counter[str] = collections.Counter()
        for texel in texels:
            for tap, info in found["texels"][texel]["far"].items():
                if status[(texel, tap)] != "turn":
                    continue
                c["turned_entries"] += 1
                for r in CANDIDATES:
                    k = info["stages"][r]
                    for flag in (
                        "normals_exact",
                        "trig_exact",
                        "rotation",
                        "origin_on_line",
                        "axial_kept",
                    ):
                        c[f"{flag}:{r}"] += k[flag]
                rod, inv = info["stages"]["rod32n+own32"], info["stages"]["inv32n+own32"]
                if info.get("anchor") is not None:
                    c["seam_found"] += 1
                    c["anchor_differs"] += rod["origin"] != info["anchor"]
                if rod["d_abs"] == inv["d_abs"]:
                    c["inv_permutes_rod"] += 1
                    c["inv_permutes_rod:norm_differs"] += rod["norm"] != inv["norm"]
                if rod["origin"] == (0, 0, 0):
                    # The Cramer origin at the normalised centre: the turn is a signed
                    # permutation (Codex root's control); which pairs agree at every stage.
                    c["origin_zero"] += 1
                    for a, b in PAIRS:
                        ka, kb = info["stages"][a], info["stages"][b]
                        c[f"origin_zero:all_stages:{_pair(a, b)}"] += all(
                            stage_agree(s, ka, kb) == "agree" for s in STAGES[:5]
                        )
        out[name] = dict(sorted(c.items()))
    across: collections.Counter[str] = collections.Counter()
    for texel in texels:
        a, b = exact["texels"][texel], oblique["texels"][texel]
        for tap, info in a["far"].items():
            if status[(texel, tap)] != "turn":
                continue
            da, db = info["developed"], b["far"][tap]["developed"]
            if da is None or db is None:
                across["developed_irrational"] += 1
            else:
                across["developed_compared"] += 1
                across["developed_equal"] += da == db
        if texel not in clean:
            continue
        key = "own_same_tau" if a["tau_corners"] == b["tau_corners"] else "own_other_tau"
        across[f"{key}:chains"] += 1
        across[f"{key}:equal"] += a["own"] == b["own"]
    out["twins"] = dict(sorted(across.items()))
    return out


def preconditions(
    inv: dict[str, Any], universe: Sequence[Tap], inconsistent: int | None
) -> dict[str, bool]:
    """What an isolation certificate of a declared, non-empty universe needs besides stage
    agreement: the same box and scale; every included chain with the same complete selection
    under every recipe in both meshes and the fixed-support recipes equal to it (`support`;
    `inconsistent` is None when no selection ran); every included far tap a `turn` tap with one
    winner in both twins (gates and branch); every developed distance rational and equal across
    twins; the own-tap distances of every included chain equal across twins, whether tau's
    corners are bit-identical (`own_same_tau`) or not (`own_other_tau`): no stratum passes
    vacuously, and an own tap through a moved tau fails it."""
    tw = inv["twins"]
    compared = tw.get("developed_compared", 0)
    return {
        "box": bool(inv["box_equal"]),
        "support": bool(universe) and inconsistent == 0,
        "gates_and_branch": bool(universe) and set(inv["coverage"]) <= {"turn"},
        "developed": tw.get("developed_irrational", 0) == 0
        and compared > 0
        and tw.get("developed_equal", 0) == compared,
        "own": sum(tw.get(f"{k}:chains", 0) for k in ("own_same_tau", "own_other_tau")) > 0
        and all(
            tw.get(f"{k}:equal", 0) == tw.get(f"{k}:chains", 0)
            for k in ("own_same_tau", "own_other_tau")
        ),
    }


def verdict(table: dict[str, Any], disc: dict[str, Any], gates: dict[str, bool]) -> dict[str, Any]:
    """Per candidate pair and overall, on the exact set: `mixed` when a stage provably differs
    or the downstream arithmetic differs (`DOWNSTREAM`); else `unknown` when a stage is
    unproved or a precondition fails; else `turn_isolated`. And whether a capture would
    discriminate the controlled candidates: their output bits differ on some clean texel (a
    controlled-recipe discrimination only, never a causal identification of Painter)."""
    stages = table["exact"]["stages"]
    out: dict[str, Any] = {"preconditions": gates, "pairs": {}}
    for a, b in PAIRS:
        name = _pair(a, b)
        differ = [s for s in STAGES if stages[s].get(f"{name}:differ", 0)]
        unproved = [s for s in STAGES if stages[s].get(f"{name}:unproved", 0)]
        downstream = DOWNSTREAM[a] == DOWNSTREAM[b]
        if differ or not downstream:
            kind = "mixed"
        elif unproved or not all(gates.values()):
            kind = "unknown"
        else:
            kind = "turn_isolated"
        d = disc["pairs"][name]
        out["pairs"][name] = {
            "verdict": kind,
            "differing_stages": differ,
            "unproved_stages": unproved,
            "downstream_same": downstream,
            "clean_output_differs": {
                "exact": d.get("clean:exact", 0),
                "oblique": d.get("clean:oblique", 0),
                "exact_agree_oblique_differ": d.get("clean:pattern:AD", 0),
            },
        }
    kinds = {v["verdict"] for v in out["pairs"].values()}
    if kinds == {"turn_isolated"}:
        out["verdict"] = "turn_isolated"
    else:
        out["verdict"] = "mixed" if "mixed" in kinds else "unknown"
    out["discriminates"] = any(
        v["clean_output_differs"]["exact"] + v["clean_output_differs"]["oblique"] > 0
        for v in out["pairs"].values()
    )
    return out


# The declared universes certified separately (`report`): every matched texel, and the clean
# matched texels whose tau corners are bit-identical in both twins (tau in island A).
UNIVERSES = ("matched", "tau_same")


def report(
    exact: dict[str, Any], oblique: dict[str, Any], selections: Selections | None = None
) -> dict[str, Any]:
    """The selection report, the explicit exclusions and, per declared universe (`UNIVERSES`),
    (a), (b), (c) and the verdict. With `selections` (every recipe's complete pipeline on both
    meshes), a texel is matched only where the selection is the same everywhere, and the
    consistency of the fixed-support recipes is checked on every included chain."""
    mask = None if selections is None else selection_mask(selections)
    texels = matched(exact, oblique, mask)
    status, clean = coverage(exact, oblique, texels)
    same = {
        t for t in clean if exact["texels"][t]["tau_corners"] == oblique["texels"][t]["tau_corners"]
    }
    far = {n: set(f["texels"]) for n, f in (("exact", exact), ("oblique", oblique))}
    out: dict[str, Any] = {
        "far_texels": {n: len(v) for n, v in far.items()},
        "matched": len(texels),
        "excluded": {
            "unmatched:exact": len(far["exact"] - set(texels)),
            "unmatched:oblique": len(far["oblique"] - set(texels)),
            "not_clean": len(texels) - len(clean),
            "tau_other": len(clean) - len(same),
        },
        "universes": {},
    }
    if selections is not None:
        out["selection"] = selection_report(selections)
        out["selection"]["mask"] = len(mask or ())
    universes = {"matched": list(texels), "tau_same": sorted(same)}
    for name in UNIVERSES:
        u = universes[name]
        members = set(u)
        st = {k: v for k, v in status.items() if k[0] in members}
        cl = clean & members
        table = {
            "exact": stage_table(exact, u, st, cl),
            "oblique": stage_table(oblique, u, st, cl),
        }
        disc = discrimination(exact, oblique, u, cl)
        inv = invariants(exact, oblique, u, st, cl)
        inconsistent = (
            None
            if selections is None
            else consistency({True: exact, False: oblique}, selections, u)
        )
        out["universes"][name] = {
            "texels": len(u),
            "selection_inconsistent": inconsistent,
            "stages": table,
            "discrimination": disc,
            "invariants": inv,
            "verdict": verdict(table, disc, preconditions(inv, u, inconsistent)),
        }
    return out


def _analyse_set(path: str) -> dict[str, Any]:
    return analyse(Path(path))


def write_meshes(directory: Path, meshes: dict[bool, bytes]) -> list[Path]:
    """Writes each mesh to the existing `directory` under OBJ_NAMES, each file created
    exclusively. Refuses (FileExistsError) before any write when one of the paths exists, and
    creates no directory. On a failed write, removes only the files this call created, then
    re-raises. Returns the created paths."""
    paths = [directory / OBJ_NAMES[exact] for exact in meshes]
    existing = [str(p) for p in paths if p.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite {existing}")
    created: list[Path] = []
    try:
        for path, data in zip(paths, meshes.values(), strict=True):
            with path.open("xb") as handle:
                created.append(path)
                handle.write(data)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=5)
    parser.add_argument(
        "--obj-dir",
        type=Path,
        default=REPO_ROOT / "tmp" / "scratch",
        help="an existing folder for the two authored OBJs of the run (removed after it)",
    )
    args = parser.parse_args(argv)
    found_copies = {exact: copies(exact) for exact in (True, False)}
    slots = {e: [slot for _, slot in layout(c)[0]] for e, c in found_copies.items()}
    if slots[True] != slots[False]:
        raise ValueError("the twins' layouts differ")
    meshes = {exact: mesh(c) for exact, c in found_copies.items()}
    created = write_meshes(args.obj_dir, meshes)
    try:
        jobs = [(str(path), r) for path in created for r in RECIPES]
        with ProcessPoolExecutor(max(1, args.jobs)) as pool:
            traces = pool.map(_analyse_set, [str(p) for p in created])
            chosen = pool.map(selection, jobs)
            results = list(traces)
            selections = {
                (path == str(created[0]), r): v for (path, r), v in zip(jobs, chosen, strict=True)
            }
    finally:
        for path in created:
            path.unlink(missing_ok=True)
    out = report(results[0], results[1], selections)
    out["mesh_sha256"] = {
        ("exact" if e else "oblique"): hashlib.sha256(d).hexdigest() for e, d in meshes.items()
    }
    out["copies"] = len(found_copies[True])
    print(json.dumps(out, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
