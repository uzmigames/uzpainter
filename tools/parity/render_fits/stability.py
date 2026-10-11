"""Structure of Iray's run-to-run difference (a) and of its Monte-Carlo error (b)
(task item 2.7; decision 050). Numbers only; the renders stay in the store.

- `half_steps`: each differing RGB sample of (a) expressed in binary16 steps of the linear
  value (codes mapped back through `display.lattice`), to separate rounding flips (one step)
  from different samples (many steps).
- `face_regions`: for a flat-faced mesh, the interior pixels grouped by the facet orientation
  of the triangle seen at the pixel centre, so (a) can be reported per face.
- `highpass_sigma`: the per-pixel noise of one render from its own pixels,
  d = x - mean(4 neighbours), sigma^2 = var(d) / 1.25 for spatially white noise (a smooth
  image adds its curvature, so it is an upper bound on textured fixtures).
- `sequence_test`: whether the k*S render continues the S render's samples (nested) or is
  independent: rms(S - K) against sqrt(sigma_S^2 - sigma_K^2) and sqrt(sigma_S^2 + sigma_K^2),
  and the variance ratio sigma_K^2 / sigma_S^2 against 1/k for independent samples.
- `jensen_bias`: the mean signed (S - K) that the concave display encoding alone predicts,
  1/2 g''(x) / g'(x)^2 (sigma_S^2 - sigma_K^2) per pixel (g the sRGB encoding, x the linear
  value of K), averaged over the region's unclamped pixels.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.render_fits import display
from tools.parity.render_fits.scene import Camera, Mesh, intersect, pixel_candidates

F64 = npt.NDArray[np.float64]
Mask = npt.NDArray[np.bool_]
FULL = display.FULL_SCALE


def half_index(codes: F64) -> npt.NDArray[np.int64]:
    """For each 16-bit code, the binary16 bit pattern of the nearest lattice point."""
    halves = np.arange(0, 0x3C01, dtype=np.uint16)
    values = np.round(display.encode(halves.view(np.float16).astype(np.float64)) * FULL)
    order = np.argsort(values, kind="stable")
    ordered = values[order]
    position = np.clip(np.searchsorted(ordered, codes), 1, len(ordered) - 1)
    left = ordered[position - 1]
    right = ordered[position]
    pick = np.where(np.abs(left - codes) <= np.abs(right - codes), position - 1, position)
    result: npt.NDArray[np.int64] = halves[order[pick]].astype(np.int64)
    return result


def half_steps(a: F64, b: F64, mask: Mask) -> dict[str, Any]:
    """Histogram of |(a) - (b)| in binary16 steps over the differing samples of a region."""
    differ = (a != b) & mask[..., None]
    steps = np.abs(half_index(a[differ]) - half_index(b[differ]))
    total = int(differ.sum())
    counts = {str(s): int((steps == s).sum()) for s in (1, 2, 3)}
    return {
        "differing_samples": total,
        "steps": counts,
        "more_than_3": int((steps > 3).sum()),
        "max_steps": int(steps.max()) if total else 0,
        "one_step_fraction": float(counts["1"] / total) if total else 0.0,
    }


def face_regions(mesh: Mesh, camera: Camera, interior: Mask) -> dict[str, Mask]:
    """Interior pixels grouped by the facet normal seen at the pixel centre (rounded to 0.01)."""
    _, width = interior.shape
    ys, xs = np.nonzero(interior)
    pixels = (ys * width + xs).astype(np.int64)
    candidates = pixel_candidates(mesh, camera, pixels, 0.5)
    origins, directions = camera.rays(xs.astype(np.float64) + 0.5, ys.astype(np.float64) + 0.5)
    hits = intersect(mesh, origins, directions, candidates)
    normals = np.round(mesh.face_normals[np.where(hits.valid, hits.triangle, 0)], 2)
    keys = [tuple(n) for n in normals]
    groups: dict[str, Mask] = {}
    for key in sorted(set(keys)):
        pick = np.array([k == key for k in keys]) & hits.valid
        if pick.sum() < 0.02 * len(keys):
            continue
        mask = np.zeros_like(interior)
        mask[ys[pick], xs[pick]] = True
        label = "face n=(" + ", ".join(f"{v:+.2f}" for v in key) + ")"
        groups[label] = mask
    return groups


def highpass_sigma(image: F64, mask: Mask) -> float:
    """Per-pixel noise sigma (16-bit codes, green channel) from the image's own pixels."""
    x = image[..., 1]
    centre = x[1:-1, 1:-1]
    neighbours = (x[:-2, 1:-1] + x[2:, 1:-1] + x[1:-1, :-2] + x[1:-1, 2:]) / 4.0
    inside = mask[1:-1, 1:-1] & mask[:-2, 1:-1] & mask[2:, 1:-1] & mask[1:-1, :-2] & mask[1:-1, 2:]
    d = (centre - neighbours)[inside]
    return float(math.sqrt(np.mean(d * d) / 1.25)) if d.size else math.nan


def sequence_test(s: F64, k: F64, mask: Mask, factor: int = 4) -> dict[str, float]:
    sigma_s = highpass_sigma(s, mask)
    sigma_k = highpass_sigma(k, mask)
    delta = (s - k)[..., 1][mask]
    rms = float(np.sqrt(np.mean(delta * delta)))
    return {
        "sigma_s": sigma_s,
        "sigma_k": sigma_k,
        "variance_ratio": sigma_k**2 / sigma_s**2 if sigma_s > 0 else math.nan,
        "independent_ratio": 1.0 / factor,
        "rms_s_minus_k": rms,
        "nested_prediction": math.sqrt(max(sigma_s**2 - sigma_k**2, 0.0)),
        "independent_prediction": math.sqrt(sigma_s**2 + sigma_k**2),
    }


def jensen_bias(k: F64, sigma_s: float, sigma_k: float, mask: Mask) -> float:
    """Predicted mean signed (S - K) in 16-bit codes from the encoding's curvature."""
    codes = k[mask].ravel()
    usable = (codes > 0.04045 * FULL) & (codes < FULL - 1)
    x = display.to_linear(codes[usable])
    if x.size == 0:
        return math.nan
    first = (1.055 / 2.4) * np.power(x, -7.0 / 12.0)
    second = -(7.0 / 12.0) * (1.055 / 2.4) * np.power(x, -19.0 / 12.0)
    variance = (sigma_s / FULL) ** 2 - (sigma_k / FULL) ** 2
    bias = 0.5 * second / (first * first) * variance
    return float(np.mean(bias) * FULL)
