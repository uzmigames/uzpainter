"""Residual diagnostic of the recorded world-offset padding probe (item 2.7, front A4).

The frozen scorer (`padding_world_offset_score`) found that none of the eight frozen far-distance
models fits. This diagnostic reads the same admitted capture and the same frozen predictions,
changes neither, and asks why. Before any analysis it refuses unless the full predictions and the
compact file are the freeze's (`load_frozen`), the capture is the frozen request's and validates
(`load_capture`), and the trace reproduces every frozen model's fractions on every scored texel
(`require_frozen`).

- `Traced` runs the frozen reference (FROZEN_REFERENCE plus `padding_far32`'s `farhook`) once and
  records, per ring texel and chosen far tap, every distance its least distance is taken over:
  the plain frame distance or each rigid turn's arguments (q, P, J, tau, K). Calls made while
  decision 291's flipped windows are tried are not recorded: they never set a chosen distance.
- `evaluate` recomputes each chain with the chosen taps and their order held fixed, under a
  far-distance model, an own-tap mode and a fractions rule, and compares the 24 output bits with
  the recording: a weight diagnosis only. A rule becomes a candidate only through the full
  pipeline (`corpus_counts`: taps, order and fractions) with zero new misses, its own frozen
  discriminating probe and review.
- `decode_all` lists the level sets within a bounded window that reproduce the 24 recorded
  components on the fixed taps: local, not global, uniqueness; a failed search proves nothing.
- `characterize` gives the residuals' aggregates; `candidates` scores CONFIGS.

Stdout carries aggregates only, never coordinates or recorded values.

    python -m tools.parity.fit.padding_world_offset_residual --load FULL.json [--candidates]
        [--corpus MODEL ...]
"""

from __future__ import annotations

import argparse
import collections
import importlib
import itertools
import json
import sys
import types
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.fit import hwmath
from tools.parity.fit import padding_corpus as corpus
from tools.parity.fit import padding_far32 as far32
from tools.parity.fit import padding_world_offset as fit
from tools.parity.fit import padding_world_offset_score as wscore
from tools.parity.fit.padding_corpus import Probe, reference_text
from tools.parity.tier0_semantics import padding_world_offset as wo

F32 = np.float32
Tap = tuple[int, int]
Entry = tuple[Any, ...]
# Per ring texel, per chosen tap: the distances its least distance is taken over.
TRACE: dict[Tap, dict[Tap, list[Entry]]] | None = None

_SELF = "tools.parity.fit.padding_world_offset_residual"
_IMPORT = "from tools.parity.fit.padding_far32 import far_distance as _far_distance\n"
_PLAIN_OLD = (
    "                if self._turned_from is None:\n"
    "                    measured = norm(sub(q, framed))\n"
)
_PLAIN_NEW = (
    "                if self._turned_from is None:\n"
    "                    measured = _far_plain(self, (x, y), (tx, ty), norm(sub(q, framed)))\n"
)
_FLIP_OLD = "        T = self.tris[tau]\n        q = T.point(T.bary(x + 0.5, y + 0.5))\n"
_FLIP_NEW = _FLIP_OLD + "        self._flip = bool(flip)\n"


def traced_far(
    model: str,
    ref: dict[str, Any],
    ring: Any,
    q: tuple[float, float, float],
    p: tuple[float, float, float],
    j: int,
    tau: int,
    k: int,
    texel: Tap,
    tap: Tap,
) -> float:
    """The hook of `padding_far32.PATCHES['farhook']`: records the turn's arguments, then
    returns the frozen `double` distance (the reference's own)."""
    if TRACE is not None and not ring._flip:
        TRACE.setdefault(texel, {}).setdefault(tap, []).append(("turn", q, p, j, tau, k))
    return far32.far_distance("double", ref, ring, q, p, j, tau, k, texel, tap)


def traced_plain(ring: Any, texel: Tap, tap: Tap, value: float) -> float:
    """A far tap's frame distance that is not a rigid turn (model independent)."""
    if TRACE is not None and not ring._flip:
        TRACE.setdefault(texel, {}).setdefault(tap, []).append(("plain", value))
    return value


def traced_module() -> Any:
    """The frozen reference with `farhook` (model `double`) routed through the tracer."""
    text = reference_text(fit.FROZEN_REFERENCE)
    for old, new in far32.PATCHES["farhook"]:
        if text.count(old) != 1:
            raise ValueError("farhook does not apply")
        text = text.replace(old, new)
    for old, new in (
        (
            _IMPORT,
            f"from {_SELF} import traced_far as _far_distance\n"
            f"from {_SELF} import traced_plain as _far_plain\n",
        ),
        (_PLAIN_OLD, _PLAIN_NEW),
        (_FLIP_OLD, _FLIP_NEW),
    ):
        if text.count(old) != 1:
            raise ValueError("the tracer's patch does not apply")
        text = text.replace(old, new)
    m = types.ModuleType("world_offset_traced")
    exec(
        compile(text, f"padding_reference@{fit.FROZEN_REFERENCE}+farhook+trace", "exec"), m.__dict__
    )
    return m


class Traced:
    """The ring of the committed OBJ under the frozen reference, each texel's chosen taps (exact
    double distances, far flags, texels) and the trace of its far taps."""

    def __init__(self) -> None:
        # The patched reference imports the tracer by its package name, which is another module
        # object than this one when it runs as __main__.
        holder: Any = importlib.import_module(_SELF)
        self.module = traced_module()
        self.ref = self.module.__dict__
        holder.TRACE = {}
        try:
            self.ring = self.module.Ring(fit.MESH_PATH, wo.MATERIAL, wo.RESOLUTION, wo.RESOLUTION)
            self.ring._flip = False
            self.chosen: dict[Tap, list[tuple[float, bool, Tap]]] = {}
            for x, y, cands, count in self.ring.texels():
                self.chosen[(x, y)] = list(cands[:count])
            self.trace: dict[Tap, dict[Tap, list[Entry]]] = holder.TRACE
        finally:
            holder.TRACE = None
        self.source = fit.source()


FarModel = Callable[[Any, Entry, Tap, Tap], float]
Fractions = Callable[[Sequence[float]], list[np.float32]]


def frozen_model(name: str) -> FarModel:
    """One of the eight frozen models of `padding_far32`, unchanged."""

    def model(t: Traced, entry: Entry, texel: Tap, tap: Tap) -> float:
        _, q, p, j, tau, k = entry
        return far32.far_distance(name, t.ref, t.ring, q, p, j, tau, k, texel, tap)

    return model


class _Normal:
    """A triangle stand-in whose face normal is another one (`normal32n`)."""

    def __init__(self, normal: Sequence[np.float32]) -> None:
        self.normal = normal


def _seam(t: Traced, tau: int, j: int, q: tuple[float, float, float]) -> tuple[int, int] | None:
    """The seam (E, edge) of tau's island whose far triangle is `j`, nearest `q` in 3D (the
    first on a tie, as `Ring.frame`); None when j is no seam's far triangle (decision 365's
    hop stages)."""
    best, nearest = None, float("inf")
    for e, edge, jj in t.ring.seams.get(t.ring.tris[tau].chart, []):
        if jj != j:
            continue
        E = t.ring.tris[e]
        gap = t.ref["segment_gap"](E.p[(edge + 1) % 3], E.p[(edge + 2) % 3], q)
        if gap < nearest:
            best, nearest = (e, edge), gap
    return best


def candidate_model(name: str) -> FarModel:
    """Hypotheses outside the freeze (diagnostic only), in box-normalised float32 positions
    (decision 273's `position32`), returned in world units as the frozen `n` models are:

    - `jpos32n`: as `pos32n`, but P interpolated through J (the turn's source triangle, the
      seam's far triangle), not through its own triangle K;
    - `normal32n`: as `pos32n`, but the turn's normals are decision 278's face normals of the
      box-normalised corners (the gate stays the raw normals', as in every frozen model);
    - `fold32n`: q through the seam's own triangle E, folded in float32 about E's seam edge into
      J (`Ring.fold32`, decision 282's fold), measured to P through K by `distance32`;
    - `fold32nj`: the same with P through J;
    - `fold32nc`: in the own comparator's convention (`compare_distance`): q through tau and P
      through K with the fused UV determinant, q folded by `Ring.fold32` into J, and the
      comparator's length (`_compare_length`);
    - `edge32n`, `edge32nf`: q through tau turned about the seam edge onto J's plane
      (`_edge_fold`, the model panel's recipe), measured to P through K by `distance32`.

    A tap the frozen gate does not turn keeps the double distance; a turn from a J that is no
    seam's far triangle of tau's island (`_seam` None) falls back to `pos32n` (counted by
    `FALLBACKS`). The fold models also count (`<name>:offplane`, the result unchanged) turns
    whose seam triangle E is not in tau's planar face: there the seam edge is not the line where
    J's and tau's planes meet, so a fold about it is another geometry, not another float32
    order."""
    pos32n = frozen_model("pos32n")

    def model(t: Traced, entry: Entry, texel: Tap, tap: Tap) -> float:
        _, q, p, j, tau, k = entry
        ref, ring = t.ref, t.ring
        J, T, K = ring.tris[j], ring.tris[tau], ring.tris[k]
        if not far32.turns(ref, J, T):
            return far32.far_distance("double", ref, ring, q, p, j, tau, k, texel, tap)
        pos, w, h = ref["position32"], ring.width, ring.height
        unit = far32._scale(ref, ring)
        if name in ("jpos32n", "normal32n"):
            qf = pos(T.uv, T.normalised, w, h, *texel)
            through = J if name == "jpos32n" else K
            pf = pos(through.uv, through.normalised, w, h, *tap)
            qd = (float(qf[0]), float(qf[1]), float(qf[2]))
            pd = (float(pf[0]), float(pf[1]), float(pf[2]))
            src, dst = J, T
            if name == "normal32n":
                src = _Normal(ref["face_normal"](J.normalised))
                dst = _Normal(ref["face_normal"](T.normalised))
            turned = far32._rotate64(ref, pd, src, dst, J.normalised[0], T.normalised[0])
            return float(ref["norm"](ref["sub"](qd, turned))) / unit
        if name in ("fold32n", "fold32nj"):
            seam = _seam(t, tau, j, q)
            if seam is None:
                FALLBACKS[name] += 1
                return pos32n(t, entry, texel, tap)
            e, edge = seam
            if ring.tris[e].face != T.face:
                FALLBACKS[f"{name}:offplane"] += 1
            E = ring.tris[e]
            qf = ring.fold32(pos(E.uv, E.normalised, w, h, *texel), e, edge, j)
            P = J if name == "fold32nj" else K
            pf = pos(P.uv, P.normalised, w, h, *tap)
            return float(ref["distance32"](qf, pf)) / unit
        if name == "fold32nc":
            seam = _seam(t, tau, j, q)
            if seam is None:
                FALLBACKS[name] += 1
                return pos32n(t, entry, texel, tap)
            e, edge = seam
            if ring.tris[e].face != T.face:
                FALLBACKS[f"{name}:offplane"] += 1
            qc = pos(T.uv, T.normalised, w, h, *texel, fused_determinant=True)
            qf = ring.fold32(qc, e, edge, j)
            pf = pos(K.uv, K.normalised, w, h, *tap, fused_determinant=True)
            return float(_compare_length(ref, qf, pf)) / unit
        if name in ("edge32n", "edge32nf"):
            seam = _seam(t, tau, j, q)
            if seam is None:
                FALLBACKS[name] += 1
                return pos32n(t, entry, texel, tap)
            e, edge = seam
            if ring.tris[e].face != T.face:
                FALLBACKS[f"{name}:offplane"] += 1
            E = ring.tris[e]
            a, b = E.normalised[(edge + 1) % 3], E.normalised[(edge + 2) % 3]
            qf = pos(T.uv, T.normalised, w, h, *texel)
            pf = pos(K.uv, K.normalised, w, h, *tap)
            folded = _edge_fold(ref, qf, a, b, T.normalised, J.normalised, name == "edge32nf")
            return float(ref["distance32"](folded, pf)) / unit
        raise ValueError(f"unknown candidate {name}")

    return model


def _compare_length(
    ref: dict[str, Any], q: Sequence[np.float32], p: Sequence[np.float32]
) -> np.float32:
    """`compare_distance`'s length of q - p: fma(d2, d2, fma(d0, d0, d1 d1)), the GPU sqrt."""
    f32, fma = ref["f32"], ref["fma"]
    d = [f32(q[c] - p[c]) for c in range(3)]
    squared = fma(d[2], d[2], fma(d[0], d[0], f32(d[1] * d[1])))
    return F32(hwmath.sqrt(np.array([squared], F32))[0])


def _edge_fold(
    ref: dict[str, Any],
    q: Sequence[np.float32],
    a: Sequence[np.float32],
    b: Sequence[np.float32],
    tau: np.ndarray,
    j: np.ndarray,
    fused: bool,
) -> list[np.float32]:
    """q turned in float32 about the seam edge (axis e = unit(B - A), anchor A) by the angle
    that takes tau's plane onto J's: cos c = nt . nj, sin s = e . (nt x nj), then
    A + e h + (e x v) s + v c with v = q - A and h = (1 - c)(e . v). Normals of the
    box-normalised corners. Not fused: the reference's float32 primitives (`face_normal`,
    `_unit32`, `_dot32`, `_cross32`, separately rounded sums). `fused`: the panel's order, dot
    = fma(z, z, fma(x, x, y y)), cross = fma(a1, b2, -(a2 b1)), unit = v rcp(sqrt(v . v)) and
    A + fma(e, h, fma(e x v, s, v c))."""
    f32, sub = ref["f32"], ref["_sub32"]
    fma = ref["fma"]
    if fused:

        def dot(x: Sequence[np.float32], y: Sequence[np.float32]) -> np.float32:
            return fma(x[2], y[2], fma(x[0], y[0], f32(x[1] * y[1])))  # type: ignore[no-any-return]

        def cross(x: Sequence[np.float32], y: Sequence[np.float32]) -> list[np.float32]:
            return [
                fma(x[1], y[2], -f32(x[2] * y[1])),
                fma(x[2], y[0], -f32(x[0] * y[2])),
                fma(x[0], y[1], -f32(x[1] * y[0])),
            ]

        def unit(v: Sequence[np.float32]) -> list[np.float32]:
            length = F32(hwmath.sqrt(np.array([dot(v, v)], F32))[0])
            inv = _gpu_rcp(length)
            return [f32(c * inv) for c in v]

        nt = unit(cross(sub(tau[1], tau[0]), sub(tau[2], tau[0])))
        nj = unit(cross(sub(j[1], j[0]), sub(j[2], j[0])))
    else:
        dot, cross, unit = ref["_dot32"], ref["_cross32"], ref["_unit32"]
        nt = ref["face_normal"](tau)
        nj = ref["face_normal"](j)
    e = unit(sub(b, a))
    c = dot(nt, nj)
    s = dot(e, cross(nt, nj))
    v = sub(q, a)
    hh = f32(f32(F32(1) - c) * dot(e, v))
    u = cross(e, v)
    if fused:
        return [f32(a[i] + fma(e[i], hh, fma(u[i], s, f32(v[i] * c)))) for i in range(3)]
    return [f32(a[i] + f32(f32(f32(e[i] * hh) + f32(u[i] * s)) + f32(v[i] * c))) for i in range(3)]


FALLBACKS: collections.Counter[str] = collections.Counter()
CANDIDATES = ("jpos32n", "normal32n", "fold32n", "fold32nj", "fold32nc", "edge32n", "edge32nf")


def own_tau32(t: Traced, texel: Tap, mode: str = "tau") -> list[bool]:
    """Per chosen tap, whether `chain_distances` measures it through tau in float32: an own
    tap of tau's own triangle (`tau`), or any own tap of tau's island (`chart`)."""
    x, y = texel
    ring = t.ring
    own = [
        ((x + dx) % ring.width, y + dy)
        for dy, dx in t.ref["NEIGHBOURS"]
        if 0 <= y + dy < ring.height and ring.owner[y + dy, (x + dx) % ring.width] >= 0
    ]
    tau = ring.tau(x, y, own)
    chart = ring.tris[tau].chart
    return [
        not far
        and (
            int(ring.owner[ty, tx]) == tau
            if mode == "tau"
            else ring.tris[int(ring.owner[ty, tx])].chart == chart
        )
        for _, far, (tx, ty) in t.chosen[texel]
    ]


def chain_distances(t: Traced, texel: Tap, model: FarModel, own32: str = "") -> list[float]:
    """`distances`, and in a chain with a far tap the own taps `own_tau32` selects (`own32`:
    `tau` or `chart`; '' none) measured as decision 358 measures single-triangle own chains:
    `compare_distance` through tau in box-normalised float32, converted to world units (the
    mixed-chain diagnostic's cycle-2 hypothesis)."""
    ds = distances(t, texel, model)
    if own32 and any(far for _, far, _ in t.chosen[texel]):
        x, y = texel
        ring = t.ring
        mask = own_tau32(t, texel, own32)
        own = [
            ((x + dx) % ring.width, y + dy)
            for dy, dx in t.ref["NEIGHBOURS"]
            if 0 <= y + dy < ring.height and ring.owner[y + dy, (x + dx) % ring.width] >= 0
        ]
        T = ring.tris[ring.tau(x, y, own)]
        unit = far32._scale(t.ref, ring)  # compare_distance is in box-normalised units
        for i, (_, _, tap) in enumerate(t.chosen[texel]):
            if mask[i]:
                measured = t.ref["compare_distance"](
                    T.uv, T.normalised, ring.width, ring.height, texel, tap
                )
                ds[i] = float(measured) / unit
    return ds


def evaluate(
    t: Traced,
    texels: Iterable[Tap],
    recorded: Callable[[Tap], list[int]],
    model: FarModel,
    own32: str = "",
    fractions: str = "double",
) -> dict[Tap, bool]:
    """Per texel (chains with a far tap), whether the chain under `model` with the chosen taps
    and order fixed reproduces the 24 recorded bits. `fractions`: `double` (decision 268 as the
    reference computes it), `f32` or `f32gpu` (`fractions_f32`)."""
    out = {}
    for texel in texels:
        ds = chain_distances(t, texel, model, own32)
        if fractions == "double":
            fr = t.module.fractions(ds)
        else:
            fr = fractions_f32(ds, gpu=fractions == "f32gpu")
        out[texel] = chain_bits(t, texel, fr) == recorded(texel)
    return out


def distances(t: Traced, texel: Tap, model: FarModel) -> list[float]:
    """The chosen taps' distances, in the chosen order, with each far tap's least distance taken
    again under `model` over its traced entries."""
    out = []
    for d, far, tap in t.chosen[texel]:
        entries = t.trace.get(texel, {}).get(tap) if far else None
        if not entries:
            out.append(d)
            continue
        values = [e[1] if e[0] == "plain" else model(t, e, texel, tap) for e in entries]
        out.append(min(values))
    return out


def chain_bits(t: Traced, texel: Tap, fractions: Sequence[np.float32]) -> list[int]:
    taps = t.chosen[texel]
    values = np.asarray([t.source[ty, tx] for _, _, (tx, ty) in taps], F32)
    out = np.array([t.module.chain(values[:, c], list(fractions)) for c in range(24)], F32)
    return [int(b) for b in out.view(np.uint32)]


def fractions_double(t: Traced) -> Fractions:
    """Decision 268's fractions as the reference computes them (double shares)."""
    return t.module.fractions  # type: ignore[no-any-return]


def _gpu_rcp(x: np.float32) -> np.float32:
    return F32(hwmath.rcp(np.array([x], F32))[0])


def fractions_f32(ds: Sequence[float], gpu: bool = False) -> list[np.float32]:
    """Decision 268's fractions with the reciprocal 1/d, the sequential tail sum and the share
    in float32 (each distance rounded to float32 first). `gpu`: the recording GPU's reciprocal
    for 1/d and the share as inv * rcp(total); else correctly rounded divisions. The
    quantisation (in double from the float32 share), the levels and the constants are decision
    268's, unchanged."""
    out: list[np.float32] = []
    if len(ds) < 2:
        return out
    inv = [_gpu_rcp(F32(d)) if gpu else F32(F32(1) / F32(d)) for d in ds]
    for level in range(len(ds) - 1):
        k, levels = LEVELS[level]
        total = F32(0)
        for v in inv[level:]:
            total = F32(total + v)
        share = F32(inv[level] * _gpu_rcp(total)) if gpu else F32(inv[level] / total)
        u = min(max(round((float(share) - 1 / k) * k / (k - 1) * levels), 0), levels)
        out.append(F32(float(Fraction(levels + (k - 1) * u, k * levels))))
    return out


LEVELS = ((4, 1023), (3, 255), (2, 63))


def raw_levels(ds: Sequence[float]) -> list[float]:
    """Decision 268's unrounded level arguments (share - 1/k) k / (k - 1) L, in double."""
    inv = [1.0 / d for d in ds]
    out = []
    for level in range(len(ds) - 1):
        k, levels = LEVELS[level]
        total = 0.0
        for v in inv[level:]:
            total += v
        out.append((inv[level] / total - 1 / k) * k / (k - 1) * levels)
    return out


def levels_of(fractions: Sequence[np.float32]) -> list[int]:
    out = []
    for level, value in enumerate(fractions):
        k, levels = LEVELS[level]
        out.append(round((float(value) * k * levels - levels) / (k - 1)))
    return out


def fraction_of(level: int, u: int) -> np.float32:
    k, levels = LEVELS[level]
    return F32(float(Fraction(levels + (k - 1) * u, k * levels)))


def decode_all(
    t: Traced, texel: Tap, recorded: Sequence[int], guess: Sequence[int], radius: int = 4
) -> list[list[int]]:
    """Every level set within `radius` of `guess` per level (the whole range for a 2-tap chain)
    whose chain over the chosen taps reproduces the 24 recorded bits."""
    taps = t.chosen[texel]
    n = len(taps)
    if n < 2:
        return []
    values = np.asarray([t.source[ty, tx] for _, _, (tx, ty) in taps], F32)
    ranges = []
    for level in range(n - 1):
        top = LEVELS[level][1]
        reach = top if n == 2 else radius
        ranges.append(range(max(0, guess[level] - reach), min(top, guess[level] + reach) + 1))
    found = []
    order = sorted(range(24), key=lambda c: -float(np.ptp(values[:, c])))
    for combo in itertools.product(*ranges):
        fr = [fraction_of(level, u) for level, u in enumerate(combo)]
        ok = True
        for c in order:
            got = int(np.array([t.module.chain(values[:, c], fr)], F32).view(np.uint32)[0])
            if got != recorded[c]:
                ok = False
                break
        if ok:
            found.append(list(combo))
    return found


def check_frozen(t: Traced, found: dict[str, Any]) -> dict[str, int]:
    """Per frozen model, the scored texels whose fractions recomputed from the trace differ from
    the frozen predictions' (must be zero for every model)."""
    bad: collections.Counter[str] = collections.Counter()
    for row, rel, texel in scored_texels(found):
        key = absolute(row, rel)
        for m in fit.MODELS:
            fr = fractions_double(t)(distances(t, key, frozen_model(m)))
            if [int(b) for b in np.asarray(fr, F32).view(np.uint32)] != texel[m]["fractions"]:
                bad[m] += 1
    return {m: bad[m] for m in fit.MODELS}


def absolute(row: dict[str, Any], rel: str) -> Tap:
    dx, dy = (int(v) for v in rel.split(","))
    return (row["slot"][0] + dx, row["slot"][1] + dy)


def scored_texels(found: dict[str, Any]) -> Iterable[tuple[dict[str, Any], str, dict[str, Any]]]:
    for row in found["copies"]:
        for rel, texel in row["texels"].items():
            if fit.stable(row, texel):
                yield row, rel, texel


def load_frozen(path: Path) -> dict[str, Any]:
    """The full predictions at `path` (`padding_world_offset --out`), refused (ValueError) unless
    they and the committed compact predictions are the freeze's (`frozen_problems`)."""
    found: dict[str, Any] = json.loads(path.read_text("utf-8"))
    problems = wscore.frozen_problems(found)
    if problems:
        raise ValueError("; ".join(problems))
    return found


Recorded = Callable[[Tap], list[int]]


def load_capture(found: dict[str, Any]) -> Recorded:
    """The admitted capture's 24 `infinite` component bits per ring texel, refused (ValueError)
    unless it is the frozen request's and validates as the scorer requires
    (`validate_capture`), with the four `infinite` exports identical."""
    problems = wscore.validate_capture(found)
    if problems:
        raise ValueError("; ".join(problems))
    probe = Probe(wscore.PROBE)
    if probe.unstable != 0 or len(probe.recorded) != 4:
        raise ValueError("the infinite exports differ or are incomplete")
    first = next(iter(probe.recorded.values()))

    def recorded(texel: Tap) -> list[int]:
        return [int(b) for b in first[probe.index[texel]].view(np.uint32)]

    return recorded


def require_frozen(t: Traced, found: dict[str, Any]) -> None:
    """Refuses (ValueError) unless the trace reproduces every frozen model's fractions on every
    scored texel (`check_frozen`)."""
    bad = {m: n for m, n in check_frozen(t, found).items() if n}
    if bad:
        raise ValueError(f"the trace differs from the freeze: {bad}")


class Scored:
    """The scored set (`padding_world_offset.stable`) with its frozen hits, its discriminating
    texels and the texels every frozen model misses (`shared`)."""

    def __init__(self, found: dict[str, Any], recorded: Recorded) -> None:
        self.rows: list[tuple[dict[str, Any], str, dict[str, Any], Tap]] = []
        self.hits: dict[str, set[Tap]] = {m: set() for m in fit.MODELS}
        self.discriminating: set[Tap] = set()
        for row, rel, texel in scored_texels(found):
            key = absolute(row, rel)
            self.rows.append((row, rel, texel, key))
            bits = recorded(key)
            if len({tuple(texel[m]["bits"]) for m in fit.MODELS}) > 1:
                self.discriminating.add(key)
            for m in fit.MODELS:
                if texel[m]["bits"] == bits:
                    self.hits[m].add(key)
        self.texels = [key for *_, key in self.rows]
        self.shared = set(self.texels) - set().union(*self.hits.values())


def _band(row: dict[str, Any]) -> str:
    return wscore.band(row)


# Relative steps of one tap's distance tried by `smallest_step` (a grid, not a minimum).
STEPS = tuple(sorted({s * 10.0**e for e in range(-8, 0) for s in (1, 2, 5)}))


def _levels(ds: Sequence[float]) -> list[int]:
    return [min(max(round(v), 0), LEVELS[i][1]) for i, v in enumerate(raw_levels(ds))]


def smallest_step(ds: Sequence[float], target: Sequence[int], far: Sequence[bool]) -> str:
    """The smallest STEPS value by which changing one tap's distance alone (up or down) gives
    the `target` levels, and that tap's kind (`far` or `own`); `none` when no tested step
    does. Per-texel sensitivity only: no rule or admissible correction follows from it."""
    for step in STEPS:
        for i in range(len(ds)):
            for sign in (1, -1):
                moved = list(ds)
                moved[i] = ds[i] * (1 + sign * step)
                if _levels(moved) == list(target):
                    return f"{'far' if far[i] else 'own'}<={step:.0e}"
    return "none"


def characterize(t: Traced, found: dict[str, Any], recorded: Recorded) -> dict[str, Any]:
    """Aggregates of the residuals (no coordinates or recorded values):

    - the set sizes, every frozen model's misses and the overlaps of the best ones;
    - the bounded decode (`decode_all`, radius 3 around pos32n's levels) of every scored texel
      some model misses: how many solutions the bounded search finds (local, not global
      uniqueness);
    - the shared misses by tap count, far pattern, differing level, role, band and shape, and
      per class `smallest_step` under double and pos32n;
    - representative levels (the bounded search's solution where a model misses, else the
      double levels, which reproduce the recording; no uniqueness searched there) compared on
      the predeclared translation mask and on the exploratory turn and scale subsets, and how
      far each model's own level changes co-vary with them."""
    s = Scored(found, recorded)
    out: dict[str, Any] = {
        "scored": len(s.texels),
        "discriminating": len(s.discriminating),
        "shared": len(s.shared),
        "shared_discriminating": len(s.shared & s.discriminating),
        "misses": {m: len(s.texels) - len(s.hits[m]) for m in fit.MODELS},
    }
    miss = {m: set(s.texels) - s.hits[m] for m in fit.MODELS}
    out["overlap"] = {
        f"{a}|{b}": [len(miss[a] & miss[b]), len(miss[a] - miss[b]), len(miss[b] - miss[a])]
        for a, b in (("pos32n", "inv32n"), ("pos32n", "rod32n"), ("pos32n", "double"))
    }
    solutions: dict[Tap, list[list[int]]] = {}
    levels: dict[Tap, dict[str, list[int]]] = {}
    for _, _, texel, key in s.rows:
        levels[key] = {
            m: levels_of([np.uint32(b).view(F32) for b in texel[m]["fractions"]])
            for m in fit.MODELS
        }
        if all(key in s.hits[m] for m in fit.MODELS):
            continue
        solutions[key] = decode_all(t, key, recorded(key), levels[key]["pos32n"], radius=3)
    out["decoded"] = {
        "texels": len(solutions),
        "of_discriminating": len(set(solutions) & s.discriminating),
        "of_shared_outside": len((set(solutions) - s.discriminating) & s.shared),
        "one_solution": sum(len(v) == 1 for v in solutions.values()),
        "several": sum(len(v) > 1 for v in solutions.values()),
        "none": sum(not v for v in solutions.values()),
    }
    strata: collections.Counter[str] = collections.Counter()
    by_key = {key: (row, texel) for row, _, texel, key in s.rows}
    for key in s.shared:
        row, _ = by_key[key]
        chosen = t.chosen[key]
        far = [c[1] for c in chosen]
        strata[f"taps:{len(chosen)}"] += 1
        strata["far:" + "".join("F" if f else "o" for f in far)] += 1
        strata[f"role:{fit.kind(row)}"] += 1
        strata[f"band:{_band(row)}"] += 1
        strata[f"shape:{row['shape']}"] += 1
        if len(solutions[key]) == 1:
            target = solutions[key][0]
            for m in ("double", "pos32n"):
                pairs = zip(target, levels[key][m], strict=True)
                differ = [i for i, (a, b) in enumerate(pairs) if a != b]
                strata[f"{m}:level:{differ}"] += 1
                ds = distances(t, key, frozen_model(m))
                strata[f"{m}:step:{smallest_step(ds, target, far)}"] += 1
    out["shared_strata"] = dict(sorted(strata.items()))
    for m in ("pos32n",):
        steps: collections.Counter[str] = collections.Counter()
        for key in miss[m] - s.shared:
            if len(solutions[key]) == 1:
                far = [c[1] for c in t.chosen[key]]
                ds = distances(t, key, frozen_model(m))
                steps[smallest_step(ds, solutions[key][0], far)] += 1
        out[f"{m}_selective_steps"] = dict(sorted(steps.items()))
    # The bounded search's one solution where a model misses, else the double levels (all eight
    # models reproduce the recording there). A key with no or several solutions has no
    # representative and its pairs are left out (`unresolved_pairs`).
    rep = {
        key: solutions[key][0] if key in solutions else levels[key]["double"]
        for key in s.texels
        if key not in solutions or len(solutions[key]) == 1
    }
    out["representatives_unresolved"] = len(s.texels) - len(rep)
    out["invariance"] = invariance(s, levels, rep)
    return out


def invariance(
    s: Scored, levels: dict[Tap, dict[str, list[int]]], rep: dict[Tap, list[int]]
) -> dict[str, Any]:
    """Per control set, pairs (copy texel, its shape's base texel at the same relative texel)
    with the same relative taps under double: how many have other representative levels than
    their base, the level differences, and per model the pairs whose own levels change, split
    by whether the representatives change. `translation` is the freeze's predeclared mask (both
    texels scored); `turn` and `scale` are exploratory."""
    base: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any], Tap]] = {}
    for row, rel, texel, key in s.rows:
        if row["role"] == "base":
            base[(row["shape"], rel)] = (row, texel, key)
    out: dict[str, Any] = {}
    for label, roles in (
        ("translation", ("offset", "yz", "dup")),
        ("turn", ("turn",)),
        ("scale", ("scale",)),
    ):
        c: collections.Counter[str] = collections.Counter()
        for row, rel, texel, key in s.rows:
            if row["role"] not in roles or (row["shape"], rel) not in base:
                continue
            brow, btexel, bkey = base[(row["shape"], rel)]
            if fit.signature(row, texel, "double")[0] != fit.signature(brow, btexel, "double")[0]:
                continue
            if key not in rep or bkey not in rep:
                c["unresolved_pairs"] += 1
                continue
            c["pairs"] += 1
            changed = rep[key] != rep[bkey]
            c["representatives_differ"] += changed
            if changed:
                delta = [a - b for a, b in zip(rep[key], rep[bkey], strict=True)]
                c[f"delta:{delta}"] += 1
                c[f"differ:{fit.kind(row)}:{_band(row)}"] += 1
            for m in fit.MODELS:
                moved = levels[key][m] != levels[bkey][m]
                kind = {(True, True): "both", (True, False): "model_only"}.get(
                    (moved, changed), "rep_only" if changed else "neither"
                )
                c[f"{m}:{kind}"] += 1
        out[label] = dict(sorted(c.items()))
    return out


# The hypotheses `candidates()` scores by default: (label, far model, own-tap mode of
# `chain_distances` ('' double, `tau`, `chart`), fractions of `evaluate`).
CONFIGS: tuple[tuple[str, str, str, str], ...] = (
    ("double", "double", "", "double"),
    ("pos32n", "pos32n", "", "double"),
    ("inv32n", "inv32n", "", "double"),
    ("double+f32", "double", "", "f32"),
    ("double+f32gpu", "double", "", "f32gpu"),
    ("pos32n+f32", "pos32n", "", "f32"),
    ("pos32n+f32gpu", "pos32n", "", "f32gpu"),
    ("normal32n", "normal32n", "", "double"),
    ("jpos32n", "jpos32n", "", "double"),
    ("fold32n", "fold32n", "", "double"),
    ("fold32nj", "fold32nj", "", "double"),
    ("edge32n", "edge32n", "", "double"),
    ("edge32nf", "edge32nf", "", "double"),
    ("pos32n+own32", "pos32n", "tau", "double"),
    ("inv32n+own32", "inv32n", "tau", "double"),
    ("fold32n+own32", "fold32n", "tau", "double"),
    ("edge32n+own32", "edge32n", "tau", "double"),
    ("fold32n+own32chart", "fold32n", "chart", "double"),
    ("edge32n+own32chart", "edge32n", "chart", "double"),
    ("fold32nc", "fold32nc", "", "double"),
    ("fold32nc+own32", "fold32nc", "tau", "double"),
)


def candidates(
    t: Traced,
    s: Scored,
    recorded: Recorded,
    configs: Sequence[tuple[str, str, str, str]] = CONFIGS,
) -> list[dict[str, Any]]:
    """Per configuration, the scored texels matched with taps and order fixed (a weight
    diagnosis only, not a candidate's score: a candidate needs the full pipeline), split into
    the shared misses, the discriminating texels and the rest, and fixed/new against pos32n and
    double."""
    rest = set(s.texels) - s.discriminating - s.shared
    out = []
    for label, name, own32, fractions in configs:
        model = frozen_model(name) if name in fit.MODELS else candidate_model(name)
        FALLBACKS.clear()
        ok = evaluate(t, s.texels, recorded, model, own32=own32, fractions=fractions)
        got = {k for k, v in ok.items() if v}
        out.append(
            {
                "config": label,
                "scored": len(got),
                "shared_fixed": len(got & s.shared),
                "discriminating": len(got & s.discriminating),
                "rest": len(got & rest),
                "rest_of": len(rest),
                "pos32n_fixed": len(got - s.hits["pos32n"]),
                "pos32n_new": len(s.hits["pos32n"] - got),
                "double_fixed": len(got - s.hits["double"]),
                "double_new": len(s.hits["double"] - got),
                "fallbacks": dict(sorted(FALLBACKS.items())),
            }
        )
    return out


# Corpus policies of `candidates`' far models (padding_corpus): `fc<name>` after `farhook`.
_CORPUS_IMPORT = f"from {_SELF} import corpus_far as _far_distance\n"


_OWN_OLD = "        distances = [c[0] for c in chosen]\n"
_OWN_NEW = (
    _OWN_OLD
    + f"        from {_SELF} import own32_mixed as _own32_mixed\n"
    + "        distances = _own32_mixed(globals(), self, x, y, chosen, distances)\n"
)


def register_corpus_patches() -> None:
    """Adds to `padding_corpus.PATCHES` (in this process only, files unchanged): `fc<name>`,
    after `farhook`, whose hook calls `corpus_far` with model `name`; and `own32mix`, which
    measures the own taps of tau's triangle in a chain with a far tap as `chain_distances`'
    `tau` mode does (`own32_mixed`)."""
    for name in CANDIDATES:
        corpus.PATCHES[f"fc{name}"] = [
            ("FAR_MODEL = 'double'\n", f"FAR_MODEL = '{name}'\n"),
            (_IMPORT, _CORPUS_IMPORT),
        ]
        corpus.PATCH_AFTER[f"fc{name}"] = "farhook"
    corpus.PATCHES["own32mix"] = [(_OWN_OLD, _OWN_NEW)]


def own32_mixed(
    ref: dict[str, Any],
    ring: Any,
    x: int,
    y: int,
    chosen: Sequence[tuple[float, bool, Tap]],
    distances: list[float],
) -> list[float]:
    """`own32mix`: in a chain with a far tap, each own tap of tau's own triangle takes decision
    358's `compare_distance` through tau (box-normalised float32), divided by the box scale
    (world units, as the other distances); every other distance is kept."""
    if len(chosen) < 2 or not any(c[1] for c in chosen):
        return distances
    own = [
        ((x + dx) % ring.width, y + dy)
        for dy, dx in ref["NEIGHBOURS"]
        if 0 <= y + dy < ring.height and ring.owner[y + dy, (x + dx) % ring.width] >= 0
    ]
    tau = ring.tau(x, y, own)
    T = ring.tris[tau]
    unit = far32._scale(ref, ring)
    out = list(distances)
    for i, (_, far, (tx, ty)) in enumerate(chosen):
        if not far and int(ring.owner[ty, tx]) == tau:
            d = ref["compare_distance"](
                T.uv, T.normalised, ring.width, ring.height, (x, y), (tx, ty)
            )
            out[i] = float(d) / unit
    return out


def corpus_far(
    model: str,
    ref: dict[str, Any],
    ring: Any,
    q: tuple[float, float, float],
    p: tuple[float, float, float],
    j: int,
    tau: int,
    k: int,
    texel: Tap,
    tap: Tap,
) -> float:
    """The `farhook` hook for the corpus: a frozen model as `padding_far32`, else a candidate."""
    if model in far32.MODELS:
        return far32.far_distance(model, ref, ring, q, p, j, tau, k, texel, tap)
    view = types.SimpleNamespace(ref=ref, ring=ring)
    return candidate_model(model)(view, ("turn", q, p, j, tau, k), texel, tap)


def chain_kind(taps: Sequence[tuple[float, bool, Tap]]) -> str:
    """`copy` (one tap), `own` (own taps only), `far` (far taps only) or `mixed`."""
    if len(taps) < 2:
        return "copy"
    far = [c[1] for c in taps]
    return "far" if all(far) else "mixed" if any(far) else "own"


def corpus_score(probe: str, policies: tuple[str, ...]) -> dict[str, Any]:
    """As `padding_corpus.score` (every ring texel, all 24 components against every recorded
    `infinite` export), with each miss's chain kind under its policy (`chain_kind`)."""
    register_corpus_patches()
    p = Probe(probe)
    out: dict[str, Any] = {"probe": probe, "ring": len(p.points), "kinds": {}}
    for policy in policies:
        chains = p.taps(p.ring(policy))
        if {point for point, *_ in chains} != set(p.points):
            raise ValueError("ring population differs")
        out["kinds"][policy] = {
            point: chain_kind(taps)
            for point, taps, w, values in chains
            if p.missed(point, p.chain(values, w))
        }
    return out


def corpus_counts(
    names: Sequence[str], policies: tuple[str, ...], jobs: int, against: int = 2
) -> dict[str, Any]:
    """The full pipeline (taps, order and fractions) of `policies` on the recorded probes
    `names`: ring texels differing from Painter per policy, and for each later policy the
    texels fixed and new against each of the first `against` policies, by chain kind (a fixed
    texel's kind under the reference policy, a new one's under the policy), with the probes
    holding new ones."""
    with ProcessPoolExecutor(jobs) as pool:
        results = list(pool.map(corpus_score, names, [policies] * len(names)))
    totals = dict.fromkeys(policies, 0)
    against_rows: dict[str, dict[str, Any]] = {}
    for result in results:
        kinds = result["kinds"]
        for policy in policies:
            totals[policy] += len(kinds[policy])
        for i, reference in enumerate(policies[:against]):
            for policy in policies[i + 1 :]:
                row = against_rows.setdefault(
                    f"{policy} vs {reference}",
                    {
                        "fixed": 0,
                        "new": 0,
                        "fixed_by_kind": {},
                        "new_by_kind": {},
                        "new_by_probe": [],
                    },
                )
                fixed = set(kinds[reference]) - set(kinds[policy])
                new = set(kinds[policy]) - set(kinds[reference])
                row["fixed"] += len(fixed)
                row["new"] += len(new)
                for point in fixed:
                    kind = kinds[reference][point]
                    row["fixed_by_kind"][kind] = row["fixed_by_kind"].get(kind, 0) + 1
                for point in new:
                    kind = kinds[policy][point]
                    row["new_by_kind"][kind] = row["new_by_kind"].get(kind, 0) + 1
                if new:
                    row["new_by_probe"].append(f"{result['probe']}:{len(new)}")
    return {"totals": totals, "against": against_rows}


def corpus_policies(specs: Sequence[str]) -> tuple[str, ...]:
    """Production (`baseline`), the freeze's corpus base (`island` with `farhook` and
    `farisland`), then per spec `model[+patch...]` that base with the model's far hook (`fm`
    for a frozen model, `fc` for a candidate) and the named patches (`own32mix`)."""
    base = "baseline+island+farhook+farisland"
    out = ["baseline", base]
    for spec in specs:
        name, *extra = spec.split("+")
        hook = f"fm{name}" if name in fit.MODELS else f"fc{name}"
        out.append("+".join([base, hook, *extra]))
    return tuple(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--load", type=Path, required=True, help="full frozen predictions")
    parser.add_argument("--candidates", action="store_true", help="score CONFIGS too")
    parser.add_argument("--corpus", action="append", help="model[+own32mix] on the corpus")
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args(argv)
    try:
        found = load_frozen(args.load)
        recorded = load_capture(found)
        t = Traced()
        require_frozen(t, found)
    except ValueError as error:
        print(json.dumps({"refused": str(error)}))
        return 1
    print(json.dumps({"characterize": characterize(t, found, recorded)}, sort_keys=True))
    if args.candidates:
        for line in candidates(t, Scored(found, recorded), recorded):
            print(json.dumps(line, sort_keys=True), flush=True)
    if args.corpus:
        register_corpus_patches()
        policies = corpus_policies(args.corpus)
        names = [*corpus.probes(), "kernel-wand-2048"]
        print(json.dumps({"corpus": corpus_counts(names, policies, args.jobs)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
