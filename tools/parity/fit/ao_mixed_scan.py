"""`AO_Mixed` operand/quantizer diagnostic (item 2.10 of `phase3.2_unreal-ue56-packed-preset`).

The current best model of Painter's `AO_Mixed` on r1, as measured on the admitted R-131
controls (decisions 131 and 321):

- quantizer: `v` is rounded to the absolute 2^-23 grid (round half to even, i.e. float32
  `1 + v`), truncated to 12 fractional bits `j`, and written as the nearest 8-bit code with ties
  down, `(j * 255 + 2047) >> 12` (`quantize`);
- channel operand of an L16 AO channel in the session that built it: not the stored L16 code,
  but the unquantized Normal blend over the white base, `float32(C * al) + float32(1 - al)`,
  with the opacity `al` stored as an L16 code, ties down (`l16_opacity`, `normal_over_white`);
- an L32F channel or a mesh-map operand: its exported float32 value;
- `v = float32(a * c)`, one correctly rounded product.

That model still differs from r1 at a few operand pairs, where Painter's product lands one to
three float32 ulps below `float32(a * c)`; no correctly rounded expression of the operands
explains it. `allowed_shifts` measures, per operand value, the ulp shifts of that operand that
remove every miss of its row, which is how a candidate operand transform is checked.

`python -m tools.parity.fit.ao_mixed_scan` prints miss counts per golden and texture set only:
no recorded value or location leaves the private store.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.feasibility import png
from tools.parity.fit.oracle import Golden, OracleUnavailable, load
from tools.parity.store.store import locate
from tools.parity.tier0_semantics import fixtures
from tools.parity.verdict import resolve_golden

Array = npt.NDArray[Any]
F32 = np.float32

# Texture set -> layer opacity of the AO fill (decision 321 §1; L16 and L32F grids alike).
GRID_OPACITY = {"s0": 0.5, "s1": 0.75, "s2": 1.0, "s3": 0.5}
GRID = "tier0/semantics/ao-mixed-grid"
FLOAT_GOLDENS = (
    "tier0/semantics/ao-mixed-grid-l32f",
    "tier0/semantics/ao-mixed-mesh-float-product",
    "tier0/semantics/ao-mixed-precomposed-half-y-l32f",
)


def quantize(v: npt.ArrayLike) -> Array:
    """8-bit `AO_Mixed` codes of float32 `v` in [0, 1] (round to 2^-23, 12 bits, ties down)."""
    w = (F32(1) + np.asarray(v, F32)).astype(F32)
    j = np.floor((w.astype(np.float64) - 1.0) * 4096.0).astype(np.int64)
    result: Array = (j * 255 + 2047) >> 12
    return result


def l16_opacity(opacity: float) -> F32:
    """The layer opacity as Painter applies it to an L16 channel: its L16 code, ties down."""
    scaled = opacity * 65535
    code = np.floor(scaled) if scaled % 1 == 0.5 else np.rint(scaled)
    return F32(code / 65535)


def normal_over_white(source: npt.ArrayLike, opacity: float) -> Array:
    """`float32(C * al) + float32(1 - al)`: a Normal fill of `source` over the white AO base."""
    alpha = l16_opacity(opacity)
    c = np.asarray(source, F32)
    result: Array = ((c * alpha).astype(F32) + (F32(1) - alpha)).astype(F32)
    return result


def product(a: npt.ArrayLike, c: npt.ArrayLike) -> Array:
    """`float32(a * c)`, one correctly rounded float32 multiplication."""
    result: Array = (np.asarray(a, F32) * np.asarray(c, F32)).astype(F32)
    return result


def shift_ulps(x: npt.ArrayLike, k: int) -> Array:
    """Non-negative float32 `x` moved by `k` units in the last place (bit-pattern step)."""
    bits = np.asarray(x, F32).view(np.int32).astype(np.int64) + k
    result: Array = bits.astype(np.int32).view(F32)
    return result


def allowed_shifts(
    a: npt.ArrayLike, c: npt.ArrayLike, codes: npt.ArrayLike, side: str, span: int = 6
) -> dict[float, list[int]]:
    """Per value of operand `side` ('a' or 'c'): the ulp shifts in [-span, span] of that
    operand under which `quantize(product)` equals `codes` on every texel holding the value.
    Values whose unshifted row already matches and allows every shift are omitted."""
    av, cv, kv = (np.asarray(x).ravel() for x in (a, c, codes))
    key = av if side == "a" else cv
    values = np.unique(key)
    ok: dict[float, list[int]] = {float(v): [] for v in values}
    for k in range(-span, span + 1):
        moved = product(shift_ulps(av, k), cv) if side == "a" else product(av, shift_ulps(cv, k))
        bad = set(np.unique(key[quantize(moved) != kv]).tolist())
        for v in values:
            if float(v) not in bad:
                ok[float(v)].append(k)
    return {v: s for v, s in ok.items() if len(s) != 2 * span + 1}


def _plane(data: bytes) -> Array:
    codes = png.decode(data).astype(np.int64)
    result: Array = codes[:, :, 0] if codes.ndim == 3 else codes
    return result


def _maps(golden: Golden, recording: str) -> dict[tuple[str, str, int], tuple[Array, str, int]]:
    out = {}
    for output_id, output in golden.recordings[recording].outputs.items():
        if "export_settings" not in output:
            continue
        storage = output["storage_format"]
        key = (output["texture_set"], output["map"], output["export_settings"]["step"])
        out[key] = (
            golden.map(recording, output_id).values[..., 0],
            storage["container"],
            storage["bits_per_channel"],
        )
    return out


def _codes(values: Array, container: str, bits: int) -> Array:
    if container == "exr":
        result: Array = np.rint(values.astype(np.float64) * 255).astype(np.int64)
    elif bits == 16:
        result = values.astype(np.int64) // 257
    else:
        result = values.astype(np.int64)
    return result


def _scan(golden: Golden, recording: str, l16: bool) -> dict[str, list[int]]:
    """Misses of the model per texture set, one count per export step (step order)."""
    maps = _maps(golden, recording)
    steps = sorted({key[2] for key in maps})
    sets = sorted({key[0] for key in maps})
    exr = next(s for s in steps if maps[(sets[0], "AO_Mixed", s)][1] == "exr")
    source = _plane(fixtures.grey_b()) / 65535.0
    result = {}
    for texture_set in sets:
        a = maps[(texture_set, "ambient_occlusion", exr)][0].astype(F32)
        if l16:
            c = normal_over_white(source, GRID_OPACITY[texture_set])
        else:
            c = maps[(texture_set, "ambientOcclusion", exr)][0].astype(F32)
        predicted = quantize(product(a, c))
        result[texture_set] = [
            int(np.count_nonzero(predicted != _codes(*maps[(texture_set, "AO_Mixed", s)])))
            for s in steps
        ]
    return result


def main() -> int:
    store = locate()
    report: dict[str, Any] = {}
    for golden_id, l16 in ((GRID, True), *((g, False) for g in FLOAT_GOLDENS)):
        resolved = resolve_golden(golden_id)
        if resolved is None:
            report[golden_id] = "oracle_unavailable"
            continue
        try:
            golden = load(store, resolved.manifest_path)
            report[golden_id] = {"r1": _scan(golden, "r1", l16)}
        except OracleUnavailable:
            report[golden_id] = "oracle_unavailable"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
