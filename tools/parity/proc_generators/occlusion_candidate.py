"""The Ambient Occlusion generator candidate (`generator/occlusion@2`), for the certification
harness (`python -m tools.parity.proc_cert ... --fitter
tools.parity.proc_generators.occlusion_candidate:fit`).

Written from the parameter semantics the documented `Property` API names (item 2.1: `ao_invert`
"Invert" of the AO section, `global_invert` "Invert" of the global section) and the documented
AO mesh-map encoding (A-HELP-BAKING: 1 where unoccluded), then fitted on the calibration set of
`parity/manifests/phase3/proc-cert/generator__occlusion@2/` (2026-11-09, 2026-11-10). The AO map
holds 16-bit codes k: its float32 input is float32(k / 65535). With I(v) the float32 subtraction
1 - v and F(c) the recording GPU's float32 of the 16-bit UNORM code c (the measured table
`src/evaluator/tables/hw-unorm16.zlib`, `tools.parity.vk_sampler_probe.unorm16`):

- c = k when `ao_invert` == `global_invert`, else 65535 - k: one invert inverts the 16-bit code;
- the value is I(I(F(c))) in every set: the generator computes the occlusion I(F(c)) and inverts
  it back, so the result is not F(c) itself.

On the GPU, F(c) is float32(c / 65535) correctly rounded for all 65 536 codes (measured
2026-11-10, Vulkan, RTX 4090, driver 617.14), so the single-invert sets differ from I(ao) where
1 - float32(k / 65535) and I(I(float32((65535 - k) / 65535))) round apart.

Texels outside the compared coverage (`coverage.py`) are 0, as in the masked oracle.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from tools.parity.proc_generators.coverage import covered_texels
from tools.parity.vk_sampler_probe import unorm16

FAMILY = "generator/occlusion"
VERSION = 2
FORMULA = (
    "I(v) = f32(1 - v); k = 16-bit code of ao; c = k if ao_invert == global_invert else "
    "65535 - k; I(I(F(c))) with F the measured hw-unorm16 fetch; 0 off coverage"
)


class AoInputError(ValueError):
    """An AO input texel that is not the float32 of a 16-bit code."""


def ao_codes(ao: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """The 16-bit code k of each AO texel; refuses a texel that is not float32(k / 65535)."""
    k = np.rint(ao.astype(np.float64) * 65535.0)
    if np.any((k < 0) | (k > 65535)):
        raise AoInputError("AO input outside [0, 1]")
    codes = k.astype(np.int64)
    if np.any(unorm16.correct(codes) != ao):
        raise AoInputError("AO input is not the float32 of a 16-bit code")
    return codes


class OcclusionCandidate:
    def fingerprint(self) -> Mapping[str, Any]:
        return {"family": FAMILY, "version": VERSION, "formula": FORMULA, "fitted": {}}

    def evaluate(self, case: Any, inputs: Mapping[str, Any]) -> np.ndarray[Any, Any]:
        one = np.float32(1.0)
        ao = np.asarray(inputs["AO"], dtype=np.float32)[..., 0]
        covered = covered_texels(np.asarray(inputs["WorldSpaceNormal"]))
        codes = np.where(covered, ao_codes(np.where(covered, ao, np.float32(0.0))), 0)
        if int(case.params["ao_invert"]) != int(case.params["global_invert"]):
            codes = 65535 - codes
        occlusion = (one - unorm16.fetch(codes)).astype(np.float32)
        value = (one - occlusion).astype(np.float32)
        out = np.where(covered, value, np.float32(0.0)).astype("<f4")
        return out[..., None]


def fit(access: Any) -> OcclusionCandidate:
    """No constant is fitted: the formula has none. The calibration set is not read."""
    del access
    return OcclusionCandidate()
