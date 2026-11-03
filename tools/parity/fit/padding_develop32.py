"""H1: a far padding tap's distance with the far chart's corners turned first (item 2.7, A7b).

Hypothesis H1 of front A7 (Codex root's GO; H2 is out). Decision 364 turns a far tap's point P
(of triangle K) rigidly from the plane of a far triangle J into tau's plane, and `rod32n`
(`padding_far32`) turns the float32 position of P in float32. H1 develops the chart instead, then
interpolates, through each counted window's J (decision 366):

1. each of K's three box-normalised float32 corners is turned J -> tau by ONE fixed turn, the
   frozen `rod32n` one: `padding_far32._rodrigues32` with the same frame (source J, target tau,
   the line's point through J's and tau's normalised corner 0);
2. P' = decision 273's `position32` of the tap's texel centre over K's float32 UVs and the
   turned corners (the split UV determinant, as for every far tap);
3. the distance is decision 273's `distance32(q, P')` with q = `position32` of the ring texel
   through tau's normalised corners, divided in double by the box scale r (world units, as the
   frozen models); own taps of tau's triangle take decision 358's comparator (`own32mix`).

Everything else is the frozen pipeline's: the turn's gate (`padding_far32.turns`) and its
fallback (the double reference's `plane_rotation` distance), the least distance over open
windows (decision 366), selection, ordering, quantization and flags.

**Patching.** `selection_module` applies the frozen reference's `farhook` (`padding_far32`)
unchanged, then `devhook`: it redirects farhook's far-distance import from `padding_far32` to
this module and sets FAR_MODEL to `dev32n`, then `own32mix`. No existing helper, request or
prediction is edited. Authored geometry and the committed kernel bitmaps only; no Painter data.
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.fit import padding_far32 as far32
from tools.parity.fit import padding_world_offset as fit
from tools.parity.fit import padding_world_offset_residual as res
from tools.parity.fit.padding_corpus import reference_text
from tools.parity.tier0_semantics import padding_world_offset as wo

F32 = np.float32
Tap = tuple[int, int]
MODEL = "dev32n"
RECIPE = "dev32n+own32"
FAR32_IMPORT = "from tools.parity.fit.padding_far32 import far_distance as _far_distance\n"
DEVELOP_IMPORT = "from tools.parity.fit.padding_develop32 import far_distance as _far_distance\n"
# Applied after `padding_far32.PATCHES['farhook']`.
PATCHES: dict[str, list[tuple[str, str]]] = {
    "devhook": [
        (FAR32_IMPORT, DEVELOP_IMPORT),
        ("FAR_MODEL = 'double'\n", f"FAR_MODEL = '{MODEL}'\n"),
    ]
}
POLICY = "farhook+devhook+own32mix"
Branch = tuple[Tap, Tap, int, int, int]
# When not None (`exercised`): every turned branch H1 computes, (texel, tap, J, tau, K) -> the
# number of calls. These are all the inputs H1's turned distance depends on.
BRANCHES: dict[Branch, int] | None = None


def turned_corners(ref: dict[str, Any], ring: Any, j: int, tau: int, k: int) -> np.ndarray:
    """K's box-normalised float32 corners, each turned J -> tau by `rod32n`'s float32
    Rodrigues sequence and frame (`padding_far32._rodrigues32`)."""
    J, T, K = ring.tris[j], ring.tris[tau], ring.tris[k]
    j0, t0 = J.normalised[0], T.normalised[0]
    return np.asarray(
        [far32._rodrigues32(ref, K.normalised[i], J, T, j0, t0) for i in range(3)], F32
    )


def far_distance(
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
    """`padding_far32.far_distance`'s hook signature under H1: far tap `tap` (of triangle k)
    of ring texel `texel` (of tau), through the plane of triangle j."""
    if model != MODEL:
        raise ValueError(f"unknown far model {model}")
    J, T, K = ring.tris[j], ring.tris[tau], ring.tris[k]
    if not far32.turns(ref, J, T):
        return float(ref["norm"](ref["sub"](q, ref["plane_rotation"](p, J, T))))
    if BRANCHES is not None:
        branch = (texel, tap, j, tau, k)
        BRANCHES[branch] = BRANCHES.get(branch, 0) + 1
    pos = ref["position32"]
    w, h = ring.width, ring.height
    qf = pos(T.uv, T.normalised, w, h, *texel)
    pf = pos(K.uv, turned_corners(ref, ring, j, tau, k), w, h, *tap)
    return float(ref["distance32"](qf, pf)) / far32._scale(ref, ring)


def module_text() -> str:
    """The frozen reference's text under `POLICY`, each patch applied exactly once."""
    text = reference_text(fit.FROZEN_REFERENCE)
    for name, patches in (
        ("farhook", far32.PATCHES["farhook"]),
        ("devhook", PATCHES["devhook"]),
        ("own32mix", [(res._OWN_OLD, res._OWN_NEW)]),
    ):
        for old, new in patches:
            if text.count(old) != 1:
                raise ValueError(f"patch {name} does not apply")
            text = text.replace(old, new)
    return text


def selection_module() -> Any:
    """The frozen reference with H1 in the whole pipeline (it changes which taps are kept,
    their order, the count and the undecided flags) and `own32mix` (fractions only)."""
    m = types.ModuleType(f"develop_{MODEL}")
    label = f"padding_reference@{fit.FROZEN_REFERENCE}+{POLICY}"
    exec(compile(module_text(), label, "exec"), m.__dict__)
    return m


def selection(path: str) -> dict[Tap, dict[str, Any]]:
    """H1's complete pipeline on the OBJ at `path`, in the form of
    `padding_turn_exact_preflight.selection`: per ring texel, its kept taps (far flags, texels,
    in order), the count, whether it is decided, and its fractions and 24 output bits."""
    return _run(path)[1]


def exercised(path: str) -> tuple[Any, dict[Tap, dict[str, Any]], dict[Branch, int]]:
    """`selection` on the OBJ at `path` with every turned branch H1 computes recorded (frame
    and window turns, flip-window trials included): its ring, the selection and the branches
    with their call counts. Recording changes no value."""
    global BRANCHES
    BRANCHES = {}
    try:
        ring, out = _run(path)
        branches = BRANCHES
    finally:
        BRANCHES = None
    return ring, out, branches


def _run(path: str) -> tuple[Any, dict[Tap, dict[str, Any]]]:
    m = selection_module()
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
            "fractions": [int(b) for b in np.asarray(weights, F32).view(np.uint32)],
            "bits": [int(b) for b in bits.view(np.uint32)],
        }
    return ring, out
