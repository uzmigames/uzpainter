"""The Ambient Occlusion generator candidate (`generator/occlusion@2`), for the certification
harness (`python -m tools.parity.proc_cert ... --fitter
tools.parity.proc_generators.occlusion_candidate:fit`).

Written from the parameter semantics the documented `Property` API names (item 2.1: `ao_invert`
"Invert" of the AO section, `global_invert` "Invert" of the global section) and the documented
AO mesh-map encoding (A-HELP-BAKING: 1 where unoccluded), then fitted on the calibration set of
`parity/manifests/phase3/proc-cert/generator__occlusion@2/` (2026-11-09). With I(v) the float32
subtraction 1 - v:

- defaults, or both inverts: I(I(ao)). Exact on every calibration case of those two sets: the
  generator computes the occlusion I(ao) and inverts it back, so the result is not `ao` itself.
- one invert (`ao_invert` or `global_invert` alone): I(ao). Not exact: Painter's value is
  1 - x(k), a deterministic function of the AO map's 16-bit code k, where x(k) is a float32 of
  k / 65535 that differs from the correctly rounded one on about one code in six by one ulp
  (`docs/analysis/proc-generator-families/02-occlusion-calibration.md`). No conversion tried
  reproduces x(k), so the candidate keeps the plain I(ao) and the residual stands.

Texels outside the compared coverage (`coverage.py`) are 0, as in the masked oracle.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from tools.parity.proc_generators.coverage import covered_texels

FAMILY = "generator/occlusion"
VERSION = 2
FORMULA = "I(v) = f32(1 - v); I(I(ao)) when ao_invert == global_invert, else I(ao); 0 off coverage"


class OcclusionCandidate:
    def fingerprint(self) -> Mapping[str, Any]:
        return {"family": FAMILY, "version": VERSION, "formula": FORMULA, "fitted": {}}

    def evaluate(self, case: Any, inputs: Mapping[str, Any]) -> np.ndarray[Any, Any]:
        one = np.float32(1.0)
        ao = np.asarray(inputs["AO"], dtype=np.float32)[..., 0]
        value = (one - ao).astype(np.float32)
        if int(case.params["ao_invert"]) == int(case.params["global_invert"]):
            value = (one - value).astype(np.float32)
        covered = covered_texels(np.asarray(inputs["WorldSpaceNormal"]))
        out = np.where(covered, value, np.float32(0.0)).astype("<f4")
        return out[..., None]


def fit(access: Any) -> OcclusionCandidate:
    """No constant is fitted: the formula has none. The calibration set is not read."""
    del access
    return OcclusionCandidate()
