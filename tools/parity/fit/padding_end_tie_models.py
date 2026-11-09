"""Float32 far-point models against Painter's window side at exact far ties (item 2.1). CPU only,
from the private store through `padding_corpus.sides`; counts only.

The inputs are the `--sides` rows of `padding_corpus` for `end-overhang` and `fold-tie` (a private
JSON file, `python -m tools.parity.fit.padding_corpus --sides --probe end-overhang --probe fold-tie
--out <file>`), restricted to the dyadic copies whose one near axis has exactly one reproducing
side. Painter's side gives the sign of its far coordinate minus the exact tie (rows: the exact side
is <= 0; columns: >= 0). Each model computes the far point in float32 from decision 273's position
of the texel centre (through the seam triangle E or tau):

- `fold32`: `Ring.fold32` (the reference's float32 fold about the seam);
- (q, pivot, form, angle, bary): a Rodrigues turn about the float32 unit seam direction k, pivoted
  at the closest seam point clamped to the segment (`clamp`), unclamped (`line`), or either end
  vertex (`a`, `b`); `form` R1 v c + (k x v) s + k ((k.v)(1 - c)), R2 the same with (k (k.v))
  (1 - c), R3 nested FMAs, R4 the parallel part kept and the perpendicular part turned, R5 v + s
  (k x v) + (1 - c) k x (k x v); the angle from the fold's float32 across directions (`basis`) or
  from the faces' float32 unit normals (`normals`); J's barycentrics by the float32 normal
  equations (`f32`) or in double (`f64`), then J's float32 UVs.

    python -m tools.parity.fit.padding_end_tie_models <sides.json>
"""

from __future__ import annotations

import collections
import itertools
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.fit.plane_transform_diagnostic import load_module
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import padding_end_overhang as eo
from tools.parity.tier0_semantics import padding_fold_tie as ft

ref = load_module(REPO_ROOT / "tests/export/padding_reference.py", "ref_end_tie_models")
F32 = np.float32
Vec32 = list[np.float32]
MESHES = REPO_ROOT / "parity/fixtures/tier0-semantics/meshes"
PROBES: dict[str, tuple[Any, Path, str, int]] = {
    "end-overhang": (eo, MESHES / f"{eo.MESH}.obj", eo.MATERIAL, eo.RESOLUTION),
    "fold-tie": (ft, MESHES / f"{ft.MESH}.obj", ft.MATERIAL, ft.RESOLUTION),
}
PIVOTS = ("clamp", "line", "a", "b")
FORMS = ("R1", "R2", "R3", "R4", "R5")


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(a[i] * b[i] for i in range(3))


def texel_of(J: Any, p: Sequence[np.float32], size: int, bary: str) -> tuple[float, float]:
    """Float32 point `p` (box-normalised) in J's texel space."""
    n = J.normalised.astype(F32)
    if bary == "f64":
        e1 = [float(n[1][i] - n[0][i]) for i in range(3)]
        e2 = [float(n[2][i] - n[0][i]) for i in range(3)]
        v = [float(p[i]) - float(n[0][i]) for i in range(3)]
        a, b, c = _dot(e1, e1), _dot(e1, e2), _dot(e2, e2)
        det = a * c - b * b
        l1 = (c * _dot(e1, v) - b * _dot(e2, v)) / det
        l2 = (a * _dot(e2, v) - b * _dot(e1, v)) / det
        lam = (1.0 - l1 - l2, l1, l2)
        return (
            sum(lam[i] * J.t[i][0] for i in range(3)),
            sum(lam[i] * J.t[i][1] for i in range(3)),
        )
    f32, d32, s32 = ref.f32, ref._dot32, ref._sub32
    e1, e2, w = s32(n[1], n[0]), s32(n[2], n[0]), s32(p, n[0])
    a, b, c = d32(e1, e1), d32(e1, e2), d32(e2, e2)
    det = f32(f32(a * c) - f32(b * b))
    l1 = f32(f32(f32(c * d32(e1, w)) - f32(b * d32(e2, w))) / det)
    l2 = f32(f32(f32(a * d32(e2, w)) - f32(b * d32(e1, w))) / det)
    l0 = f32(f32(F32(1) - l1) - l2)
    uv = J.uv.astype(F32)
    u = f32(f32(f32(l0 * uv[0][0]) + f32(l1 * uv[1][0])) + f32(l2 * uv[2][0]))
    t = f32(f32(f32(l0 * uv[0][1]) + f32(l1 * uv[1][1])) + f32(l2 * uv[2][1]))
    return float(f32(u * F32(size))), float(f32(f32(F32(1) - t) * F32(size)))


def turned(
    ring: Any, e: int, edge: int, j: int, q: Vec32, pivot: str, form: str, angle: str
) -> Vec32:
    """`q` turned in float32 about seam edge `edge` of E into J's plane (see the module)."""
    f32, fma = ref.f32, ref.fma
    d32, c32, u32 = ref._dot32, ref._cross32, ref._unit32
    s32, a32, k32 = ref._sub32, ref._add32, ref._scale32
    E, J = ring.tris[e], ring.tris[j]
    va, vb = E.vertex[(edge + 1) % 3], E.vertex[(edge + 2) % 3]
    ia, ib = E.vertex.index(va), E.vertex.index(vb)
    ja, jb = J.vertex.index(va), J.vertex.index(vb)
    n0, n1 = E.normalised.astype(F32), J.normalised.astype(F32)
    a, b = list(n0[ia]), list(n0[ib])
    k = u32(s32(b, a))

    def across(to: Sequence[np.float32]) -> Vec32:
        v = s32(to, a)
        out: Vec32 = u32(s32(v, k32(k, d32(v, k))))
        return out

    toward = k32(across(n0[3 - ia - ib]), F32(-1))
    in_other = across(n1[3 - ja - jb])
    s = d32(c32(toward, in_other), k)
    if angle == "basis":
        c = d32(toward, in_other)
    else:
        c = d32(u32(ref.face_normal(n0)), u32(ref.face_normal(n1)))
        s = f32(F32(math.copysign(math.sqrt(max(0.0, 1.0 - float(c) ** 2)), float(s))))
    length = F32(math.sqrt(float(d32(s32(b, a), s32(b, a)))))
    t = d32(s32(q, a), k)
    if pivot == "clamp":
        C = a if t <= 0 else b if t >= length else a32(a, k32(k, t))
    elif pivot == "line":
        C = a32(a, k32(k, t))
    else:
        C = a if pivot == "a" else b
    v = s32(q, C)
    kv, cr, one_c = d32(k, v), c32(k, v), f32(F32(1) - c)
    if form == "R1":
        r = a32(a32(k32(v, c), k32(cr, s)), k32(k, f32(kv * one_c)))
    elif form == "R2":
        r = a32(a32(k32(v, c), k32(cr, s)), k32(k32(k, kv), one_c))
    elif form == "R3":
        r = [fma(v[i], c, fma(cr[i], s, f32(k[i] * f32(kv * one_c)))) for i in range(3)]
    elif form == "R4":
        par = k32(k, kv)
        r = a32(par, a32(k32(s32(v, par), c), k32(cr, s)))
    else:
        r = a32(a32(v, k32(cr, s)), k32(c32(k, cr), one_c))
    out: Vec32 = a32(C, r)
    return out


def cases(sides: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The labelled dyadic ties: geometry, Painter's sign and the texel's seam position."""
    out = []
    for probe, (mod, mesh, material, size) in PROBES.items():
        ring = ref.Ring(mesh, material, size, size)
        covered = ring.owner >= 0
        placed, _ = mod.layout()
        for row in sides[probe]:
            truth = [key for key, ok in row["exact"].items() if ok]
            if len(truth) != 1 or len(row["axes"]) != 1:
                continue
            x, y = row["texel"]
            (copy,) = [
                c
                for c, (sc, sr), _ in placed
                if sc - 2 <= x < sc + c.size[0] + 2 and sr - 2 <= y < sr + c.size[1] + 2
            ]
            if getattr(copy, "twin", "dyadic") != "dyadic":
                continue
            ((_, axis, m, e, edge, j),) = row["axes"]
            own = [
                ((x + dx) % size, y + dy)
                for dy, dx in ref.NEIGHBOURS
                if 0 <= y + dy < size and covered[y + dy, (x + dx) % size]
            ]
            E = ring.tris[e]
            pa, pb = E.t[(edge + 1) % 3], E.t[(edge + 2) % 3]
            ex, ey = pb[0] - pa[0], pb[1] - pa[1]
            along = ((x + 0.5 - pa[0]) * ex + (y + 0.5 - pa[1]) * ey) / (ex * ex + ey * ey)
            flipped = truth[0] != "none"
            out.append(
                {
                    "probe": probe,
                    "ring": ring,
                    "texel": (x, y),
                    "seam": (e, edge, j),
                    "tau": ring.tau(x, y, own),
                    "axis": axis,
                    "tie": round(m),
                    "size": size,
                    "want": (1 if flipped else -1) if axis == 1 else (-1 if flipped else 1),
                    "where": "mid" if 0.0 <= along <= 1.0 else "end",
                }
            )
    return out


def error(case: dict[str, Any], model: tuple[str, ...]) -> float:
    """The model's far coordinate on the case's axis minus the exact tie (texels)."""
    if model == ("exact",):
        return 0.0
    ring, (x, y), (e, edge, j) = case["ring"], case["texel"], case["seam"]
    source = ring.tris[e if model[1 if model[0] == "fold32" else 0] == "E" else case["tau"]]
    q = ref.position32(source.uv, source.normalised, case["size"], case["size"], x, y)
    if model[0] == "fold32":
        p, bary = ring.fold32(q, e, edge, j), model[2]
    else:
        p, bary = turned(ring, e, edge, j, q, *model[1:4]), model[4]
    coordinate = texel_of(ring.tris[j], p, case["size"], bary)[case["axis"]]
    return float(coordinate - 0.5 - case["tie"])


def models() -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = [("exact",)]
    out += [
        (q, pivot, form, angle, bary)
        for q, pivot, form, angle, bary in itertools.product(
            ("E", "tau"), PIVOTS, FORMS, ("basis", "normals"), ("f32", "f64")
        )
    ]
    out += [("fold32", q, bary) for q in ("E", "tau") for bary in ("f32", "f64")]
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    found = cases(json.loads(Path(args[0]).read_text("utf-8")))
    labels = collections.Counter((c["probe"], c["where"], c["want"]) for c in found)
    print(json.dumps({"cases": len(found), "labels": {str(k): v for k, v in labels.items()}}))
    for model in models():
        score: collections.Counter[str] = collections.Counter()
        nonzero = 0
        for case in found:
            err = error(case, model)
            nonzero += err != 0.0
            got = (1 if err > 0 else -1) if case["axis"] == 1 else (-1 if err < 0 else 1)
            score[f"{case['probe']}/{case['where']}/{'ok' if got == case['want'] else 'miss'}"] += 1
        print(json.dumps({"model": list(model), "nonzero": nonzero, **dict(sorted(score.items()))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
