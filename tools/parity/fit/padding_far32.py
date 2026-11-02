"""Fixed candidate arithmetic models of a far padding tap's rigidly turned distance (item 2.7).

Decision 364 measures a far tap P (a texel centre of triangle K) from the ring texel's point q (of
tau) after turning P rigidly from the plane of a far triangle J into tau's plane
(`padding_reference.plane_rotation`), in double precision. Front A2 found the Wand's other new
texel of the `island` rule 0.065 bins past a rounding boundary, about one float32 position step
of the Wand's scale. These models are the arithmetic the probe `export-padding-world-offset`
discriminates, fixed before its capture; claims are limited to them.

- `double`: the reference (q and P barycentric in double, `plane_rotation`, the double norm).
- `store32w`: q and P rounded to float32 world positions, then the double turn and norm (front
  A2 refuted it on the Wand texel; kept as a control).
- `pos32w`, `pos32n`: q and P by decision 273's float32 texel-centre interpolation
  (`position32`) of the raw float32 world positions (`w`) or of the box-normalised ones (`n`),
  then the double turn and norm.
- `rod32w`, `rod32n`: the same positions, then `plane_rotation`'s Rodrigues turn and decision
  273's distance (FMA squared length, GPU square root), every float32 operation rounded.
- `inv32w`, `inv32n`: the same positions, q turned the other way (tau's plane onto J's) in
  float32, measured to P.

Normalised distances are returned in world units (divided in double by decision 273's scale r;
no float32 rounding is added). The turn's gate (parallel planes, or a dot product above
FOLD_GATE: `turns`) is the double reference's for every model, so that no model changes which
taps turn; a tap on the turn's axis is turned like any other.
Authored arithmetic only; no Painter data.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

F32 = np.float32
MODELS = ("double", "store32w", "pos32w", "pos32n", "rod32w", "rod32n", "inv32w", "inv32n")


def _positions(ring: Any, tri: Any, space: str) -> np.ndarray:
    if space == "n":
        return np.asarray(tri.normalised, F32)
    return np.asarray(tri.p, F32)


def _scale(ref: dict[str, Any], ring: Any) -> float:
    """Decision 273's r = 1 / (max(ext) / 2) of the ring's mesh box (`box_normalised`)."""
    lo, hi = ring.box
    ext = (hi.astype(F32) - lo.astype(F32)).astype(F32)
    return float(F32(F32(1) / F32(ext.max() * F32(0.5))))


def _rotate64(
    ref: dict[str, Any],
    p: tuple[float, float, float],
    source: Any,
    target: Any,
    source_p0: Sequence[np.float32],
    target_p0: Sequence[np.float32],
) -> tuple[float, float, float]:
    """`plane_rotation` in double with the line's point solved through `source_p0` and
    `target_p0` (the corner 0 of source and target in the model's space)."""
    unit, cross, dot, norm = ref["unit"], ref["cross"], ref["dot"], ref["norm"]
    scale, add, sub = ref["scale"], ref["add"], ref["sub"]
    n = unit(tuple(float(c) for c in target.normal))
    m = unit(tuple(float(c) for c in source.normal))
    axis = cross(m, n)
    sine = norm(axis)
    cosine = dot(m, n)
    axis = scale(axis, 1.0 / sine)
    dn = dot(n, tuple(float(c) for c in target_p0))
    dm = dot(m, tuple(float(c) for c in source_p0))
    across = cross(m, axis)
    det = dot(n, across)
    origin = scale(add(scale(across, dn), scale(cross(axis, n), dm)), 1.0 / det)
    v = sub(p, origin)
    turned = add(add(origin, scale(v, cosine)), scale(cross(axis, v), sine))
    out: tuple[float, float, float] = add(turned, scale(axis, dot(axis, v) * (1.0 - cosine)))
    return out


def _rodrigues32(
    ref: dict[str, Any],
    p: Sequence[np.float32],
    source: Any,
    target: Any,
    source_p0: Sequence[np.float32],
    target_p0: Sequence[np.float32],
) -> list[np.float32]:
    """`plane_rotation` in float32, operation for operation: n and m the float32 unit normals of
    target and source, axis m x n over its length, the line's point by Cramer's rule, then
    origin + v cos + (axis x v) sin + axis (axis . v)(1 - cos)."""
    f32, dot, cross = ref["f32"], ref["_dot32"], ref["_cross32"]
    sub, add, scale, unit = ref["_sub32"], ref["_add32"], ref["_scale32"], ref["_unit32"]
    n = unit([F32(c) for c in target.normal])
    m = unit([F32(c) for c in source.normal])
    axis = cross(m, n)
    sine = F32(ref["hwmath"].sqrt(np.array([dot(axis, axis)], F32))[0])
    cosine = dot(m, n)
    axis = [f32(c / sine) for c in axis]
    dn, dm = dot(n, target_p0), dot(m, source_p0)
    across = cross(m, axis)
    det = dot(n, across)
    origin = scale(add(scale(across, dn), scale(cross(axis, n), dm)), f32(F32(1) / det))
    v = sub([F32(c) for c in p], origin)
    turned = add(add(origin, scale(v, cosine)), scale(cross(axis, v), sine))
    out: list[np.float32] = add(turned, scale(axis, f32(dot(axis, v) * f32(F32(1) - cosine))))
    return out


def turns(ref: dict[str, Any], source: Any, target: Any) -> bool:
    """`plane_rotation`'s own condition for turning (in double): the unit face normals are not
    parallel (sine at least PARALLEL) and meet at a dot product of at most FOLD_GATE. A point on
    the turn's axis is still turned (it is a fixed point only in exact arithmetic)."""
    unit, cross, dot, norm = ref["unit"], ref["cross"], ref["dot"], ref["norm"]
    n = unit(tuple(float(c) for c in target.normal))
    m = unit(tuple(float(c) for c in source.normal))
    return bool(norm(cross(m, n)) >= ref["PARALLEL"] and dot(m, n) <= float(ref["FOLD_GATE"]))


def far_distance(
    model: str,
    ref: dict[str, Any],
    ring: Any,
    q: tuple[float, float, float],
    p: tuple[float, float, float],
    j: int,
    tau: int,
    k: int,
    texel: tuple[int, int],
    tap: tuple[int, int],
) -> float:
    """Far tap `tap` (of triangle k, point p) of ring texel `texel` (of tau, point q), turned
    from the plane of triangle j, under `model`."""
    J, T, K = ring.tris[j], ring.tris[tau], ring.tris[k]
    rotate, norm, sub = ref["plane_rotation"], ref["norm"], ref["sub"]
    exact = rotate(p, J, T)
    if model == "double" or not turns(ref, J, T):
        return float(norm(sub(q, exact)))
    if model == "store32w":
        q32 = tuple(float(F32(c)) for c in q)
        p32 = tuple(float(F32(c)) for c in p)
        return float(norm(sub(q32, rotate(p32, J, T))))
    space = model[-1]
    w, h = ring.width, ring.height
    pos = ref["position32"]
    qf = pos(T.uv, _positions(ring, T, space), w, h, *texel)
    pf = pos(K.uv, _positions(ring, K, space), w, h, *tap)
    unit = 1.0 if space == "w" else _scale(ref, ring)
    j0 = _positions(ring, J, space)[0]
    t0 = _positions(ring, T, space)[0]
    if model.startswith("pos32"):
        qd = (float(qf[0]), float(qf[1]), float(qf[2]))
        pd = (float(pf[0]), float(pf[1]), float(pf[2]))
        return float(norm(sub(qd, _rotate64(ref, pd, J, T, j0, t0)))) / unit
    if model.startswith("rod32"):
        return float(ref["distance32"](qf, _rodrigues32(ref, pf, J, T, j0, t0))) / unit
    if model.startswith("inv32"):
        back = _rodrigues32(ref, qf, T, J, t0, j0)
        return float(ref["distance32"](back, pf)) / unit
    raise ValueError(f"unknown far model {model}")


# Text patches of `tests/export/padding_reference.py` (`padding_corpus.PATCHES`): `farhook`
# routes every rigidly turned far distance through `far_distance` under the module's FAR_MODEL
# (`double` by default, which leaves the reference unchanged); `farisland` does the same for
# the `island` rule's turns (apply after `island`); `fm<model>` selects a model (after
# `farhook`).
HOOK_CALL = "_far_distance(FAR_MODEL, globals(), self, q, {p}, {j}, tau, {k}, (x, y), {tap})"
PATCHES: dict[str, list[tuple[str, str]]] = {
    "farhook": [
        (
            "        found, lo, hi = obj_mesh(path, material)\n",
            "        found, lo, hi = obj_mesh(path, material)\n        self.box = (lo, hi)\n",
        ),
        (
            "        target = self.tris[tau]\n        if self.tris[k].chart != target.chart:\n",
            "        target = self.tris[tau]\n        self._turned_from = None\n"
            "        if self.tris[k].chart != target.chart:\n",
        ),
        (
            "                return plane_rotation(p, self.tris[source], target)\n",
            "                self._turned_from = source\n"
            "                return plane_rotation(p, self.tris[source], target)\n",
        ),
        (
            "                pool[(tx, ty)] = [norm(sub(q, self.frame(p, k, tau, q, window))),"
            " outside, False]\n",
            "                framed = self.frame(p, k, tau, q, window)\n"
            "                if self._turned_from is None:\n"
            "                    measured = norm(sub(q, framed))\n"
            "                else:\n"
            "                    measured = "
            + HOOK_CALL.format(p="p", j="self._turned_from", k="k", tap="(tx, ty)")
            + "\n"
            "                pool[(tx, ty)] = [measured, outside, False]\n",
        ),
        (
            "                    turned = plane_rotation(P, self.tris[window_js[w]], T)\n"
            "                    pool[texel][0] = min(pool[texel][0], norm(sub(q, turned)))\n",
            "                    kk = int(self.owner[texel[1], texel[0]])\n"
            "                    measured = "
            + HOOK_CALL.format(p="P", j="window_js[w]", k="kk", tap="texel")
            + "\n"
            "                    pool[texel][0] = min(pool[texel][0], measured)\n",
        ),
        (
            "def obj_mesh(\n",
            "FAR_MODEL = 'double'\n"
            "from tools.parity.fit.padding_far32 import far_distance as _far_distance\n\n\n"
            "def obj_mesh(\n",
        ),
    ],
    "farisland": [
        (
            "                        norm(sub(q, plane_rotation(P, self.tris[window_js[w]], T)))\n",
            "                        "
            + HOOK_CALL.format(
                p="P", j="window_js[w]", k="int(self.owner[texel[1], texel[0]])", tap="texel"
            )
            + "\n",
        )
    ],
    **{
        f"fm{name}": [("FAR_MODEL = 'double'\n", f"FAR_MODEL = '{name}'\n")]
        for name in MODELS
        if name != "double"
    },
}
PATCH_AFTER: dict[str, str] = {
    "farisland": "island",
    **{f"fm{name}": "farhook" for name in MODELS if name != "double"},
}
