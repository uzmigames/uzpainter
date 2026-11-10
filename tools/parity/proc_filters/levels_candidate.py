"""The Levels filter candidate (`filter/levels@2`), for the certification harness
(`python -m tools.parity.proc_cert certify ... --fitter
tools.parity.proc_filters.levels_candidate:fit`).

The native levels effect as Tier 0 settled it (`parity/semantics/masks-levels.json` `levels` and
`levels-clamp`, `src/evaluator/arith.cpp` `Levels`), on a content channel:

- the content texel is a 16-bit code k of the layer's bitmap: the channel holds I(I(F(k))) with
  I(v) = float32(1 - v) and F(k) = float32(k / 65535) correctly rounded (the recording GPU's
  UNORM16 fetch, `src/evaluator/tables/hw-unorm16.zlib`), so k is read back from the content
  and the content is refused when it is not I(I(F(k)));
- the levels effect reads F(k): t = (F(k) - in_min) Rcp(in_max - in_min) with the GPU's
  reciprocal, clamped to [0, 1] when `clamp`, t = sign(t) pow(|t|, gamma) with the GPU's pow when
  gamma is not 1, then fma(t, out_max - out_min, out_min), every parameter a float32;
- the channel stores I(I(.)) of that value, as it stores the content.

No constant is fitted. Texels outside the compared coverage (decision 423 §1) are 0, as in the
masked oracle.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from tools.parity.fit import hwmath
from tools.parity.proc_generators.coverage import covered_texels
from tools.parity.vk_sampler_probe import unorm16

FAMILY = "filter/levels"
VERSION = 2
FORMULA = (
    "I(v) = f32(1 - v); k = 16-bit code of the content, content == I(I(F(k))); "
    "t = (F(k) - in_min) hw_rcp(in_max - in_min), clamp01 if clamp, sign(t) hw_pow(|t|, gamma) "
    "if gamma != 1; out = I(I(fma(t, out_max - out_min, out_min))); 0 off coverage"
)
F32 = np.float32


class ContentInputError(ValueError):
    """A content texel that is not the channel value of a 16-bit code."""


def twice_inverted(v: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    one = F32(1.0)
    return (one - (one - np.asarray(v, F32)).astype(F32)).astype(F32)


def content_codes(content: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """The 16-bit code k of each content texel; refuses a texel that is not I(I(F(k)))."""
    k = np.rint(content.astype(np.float64) * 65535.0)
    if np.any((k < 0) | (k > 65535)):
        raise ContentInputError("content outside [0, 1]")
    codes = k.astype(np.int64)
    if np.any(twice_inverted(unorm16.fetch(codes)) != content):
        raise ContentInputError("content is not the channel value of a 16-bit code")
    return codes


def levels(v: np.ndarray[Any, Any], params: Mapping[str, Any]) -> np.ndarray[Any, Any]:
    in_min, in_max, gamma, out_min, out_max = (
        F32(params[name])
        for name in ("input_min", "input_max", "gamma", "output_min", "output_max")
    )
    span = hwmath.rcp(np.array([F32(in_max - in_min)], F32))[0]
    t = ((v - in_min).astype(F32) * span).astype(F32)
    if int(params["clamp"]):
        t = np.clip(t, F32(0.0), F32(1.0))
    if gamma != F32(1.0):
        p = hwmath.pow(np.abs(t), np.full(t.shape, gamma, F32))
        t = np.where(t > 0, p, np.where(t < 0, -p, (t * p).astype(F32))).astype(F32)
    width = F32(out_max - out_min)
    out: np.ndarray[Any, Any] = (
        t.astype(np.float64) * np.float64(width) + np.float64(out_min)
    ).astype(F32)
    return out


class LevelsCandidate:
    def fingerprint(self) -> Mapping[str, Any]:
        return {"family": FAMILY, "version": VERSION, "formula": FORMULA, "fitted": {}}

    def evaluate(self, case: Any, inputs: Mapping[str, Any]) -> np.ndarray[Any, Any]:
        content = np.asarray(inputs["content"], dtype=F32)[..., 0]
        covered = covered_texels(np.asarray(inputs["WorldSpaceNormal"]))
        codes = content_codes(content)
        value = twice_inverted(levels(unorm16.fetch(codes), case.params))
        out = np.where(covered, value, F32(0.0)).astype("<f4")
        return out[..., None]


def fit(access: Any) -> LevelsCandidate:
    """No constant is fitted: the formula has none. The calibration set is not read."""
    del access
    return LevelsCandidate()
