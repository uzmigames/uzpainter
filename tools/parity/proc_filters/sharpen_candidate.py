"""The Sharpen filter candidate (`filter/sharpen@2`), for the certification harness
(`python -m tools.parity.proc_cert certify ... --fitter
tools.parity.proc_filters.sharpen_candidate:fit`).

Written from the Laplacian sharpening of Gonzalez and Woods (Digital Image Processing, 4th ed.,
§3.6: g = f - c Laplacian(f) with the four-neighbour kernel), Painter's parameter `intensity`
(item 2.1) as c, then fitted on the diagnostic golden and the calibration set of
`parity/manifests/phase3/proc-cert/filter__sharpen@2/` (2026-11-10):

- the content texel is a 16-bit code k of the layer's bitmap: the channel holds I(I(F(k))) with
  I(v) = float32(1 - v) and F the recording GPU's UNORM16 fetch (correctly rounded,
  `src/evaluator/tables/hw-unorm16.zlib`); every texel is read back to its code, and the content
  is refused when a texel is not I(I(F(k)));
- the filter computes y = x + intensity (4 x - ((n + s) + (e + w))) in float32 on x = F(k) and
  its four neighbours, the texture wrapping at its border, and writes the 16-bit code
  rint(clamp(y, 0, 1) 65535);
- the channel stores I(I(F(code))), as it stores the content.

Where intensity x (4 k - the neighbours' codes) falls exactly halfway between two codes (an
intensity of 0.25 does on a quarter of the texels with a non-zero Laplacian), Painter's code is not
the one this rounding gives: the candidate is not exact there (notes:
`docs/analysis/proc-filter-families/02-calibration-2026-11-10.md`).

Texels outside the compared coverage (decision 423 §1) are 0, as in the masked oracle.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from tools.parity.proc_filters.levels_candidate import content_codes, twice_inverted
from tools.parity.proc_generators.coverage import covered_texels
from tools.parity.vk_sampler_probe import unorm16

FAMILY = "filter/sharpen"
VERSION = 2
FORMULA = (
    "I(v) = f32(1 - v); k = 16-bit code of the content, content == I(I(F(k))); x = F(k); "
    "y = x + intensity (4 x - ((n + s) + (e + w))) in f32, wrapping; "
    "code = rint(f32(clamp01(y) 65535)); out = I(I(F(code))); 0 off coverage"
)
F32 = np.float32


def neighbour(x: np.ndarray[Any, Any], dy: int, dx: int) -> np.ndarray[Any, Any]:
    return np.roll(np.roll(x, dy, axis=0), dx, axis=1)


def sharpen_codes(codes: np.ndarray[Any, Any], intensity: float) -> np.ndarray[Any, Any]:
    x = unorm16.fetch(codes)
    n, s, e, w = (neighbour(x, dy, dx) for dy, dx in ((1, 0), (-1, 0), (0, -1), (0, 1)))
    laplacian = (F32(4.0) * x - ((n + s) + (e + w))).astype(F32)
    y = (x + (F32(intensity) * laplacian).astype(F32)).astype(F32)
    scaled = (np.clip(y, F32(0.0), F32(1.0)) * F32(65535.0)).astype(F32)
    out: np.ndarray[Any, Any] = np.rint(scaled).astype(np.int64)
    return out


class SharpenCandidate:
    def fingerprint(self) -> Mapping[str, Any]:
        return {"family": FAMILY, "version": VERSION, "formula": FORMULA, "fitted": {}}

    def evaluate(self, case: Any, inputs: Mapping[str, Any]) -> np.ndarray[Any, Any]:
        content = np.asarray(inputs["content"], dtype=F32)[..., 0]
        covered = covered_texels(np.asarray(inputs["WorldSpaceNormal"]))
        codes = sharpen_codes(content_codes(content), float(case.params["intensity"]))
        value = twice_inverted(unorm16.fetch(codes))
        out = np.where(covered, value, F32(0.0)).astype("<f4")
        return out[..., None]


def fit(access: Any) -> SharpenCandidate:
    """No constant is fitted: the formula has none. The calibration set is not read."""
    del access
    return SharpenCandidate()
