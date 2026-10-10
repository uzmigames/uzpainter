"""Feasibility prototypes (not shipped) of the evaluated procedural families.

Every formula is written from public sources only (provenance per formula below and in
`parity/semantics/procedural-feasibility.json`): Adobe's public generator help pages for the
parameter semantics (A-HELP-GUIDE), Painter's public baking documentation for what the mesh maps
mean (A-HELP-BAKING), and the published noise literature (P-NOISE). Constants the public sources
do not give are free parameters fitted black-box to the private oracles (`fit.py`); no Painter
resource, `.sbsar`, shader or observed preset structure is an input.

All prototypes work on the fixture's authored mesh maps as 16-bit code values and return 16-bit
code values of the exported map, so they compare with the oracle at native depth.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache

import numpy as np
import numpy.typing as npt

Codes = npt.NDArray[np.int64]
Floats = npt.NDArray[np.float64]
FULL = 65535


class UnsupportedParameters(ValueError):
    """The prototype has no calibrated behaviour for these parameter values (05 §2: refuse)."""


def to_codes(values: Floats) -> Codes:
    """Unit values to 16-bit codes (round half up, clamped)."""
    codes: Codes = np.floor(np.clip(values, 0.0, 1.0) * FULL + 0.5).astype(np.int64)
    return codes


def unit(codes: Codes) -> Floats:
    values: Floats = codes.astype(np.float64) / FULL
    return values


# ------------------------------------------------------------------ public operators


def gaussian_blur(image: Floats, sigma: float) -> Floats:
    """Gaussian blur (standard image-processing operator), evaluated in the frequency domain
    with periodic borders: the transfer function exp(-2 pi^2 sigma^2 f^2) per axis."""
    if sigma <= 0.0:
        return image
    fy = np.fft.fftfreq(image.shape[0])[:, None]
    fx = np.fft.rfftfreq(image.shape[1])[None, :]
    transfer = np.exp(-2.0 * np.pi**2 * sigma**2 * (fx**2 + fy**2))
    blurred: Floats = np.fft.irfft2(np.fft.rfft2(image) * transfer, s=image.shape)
    return blurred


def perlin_noise(shape: tuple[int, int], period: int, seed: int) -> Floats:
    """Tileable 2D gradient noise in [-1, 1] (Perlin 2002 *Improving Noise*: quintic fade,
    hashed gradients), `period` cells across the image, permutation drawn from `seed`."""
    rng = np.random.default_rng(seed)
    angles = rng.uniform(0.0, 2.0 * np.pi, (period, period))
    gradients = np.stack([np.cos(angles), np.sin(angles)], axis=-1)
    height, width = shape
    y = (np.arange(height) + 0.5) / height * period
    x = (np.arange(width) + 0.5) / width * period
    xx, yy = np.meshgrid(x, y)
    x0, y0 = np.floor(xx).astype(int), np.floor(yy).astype(int)
    fx, fy = xx - x0, yy - y0

    def corner(dx: int, dy: int) -> Floats:
        g = gradients[(y0 + dy) % period, (x0 + dx) % period]
        dot: Floats = g[..., 0] * (fx - dx) + g[..., 1] * (fy - dy)
        return dot

    def fade(t: Floats) -> Floats:
        faded: Floats = t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
        return faded

    u, v = fade(fx), fade(fy)
    top = corner(0, 0) + u * (corner(1, 0) - corner(0, 0))
    bottom = corner(0, 1) + u * (corner(1, 1) - corner(0, 1))
    noise: Floats = (top + v * (bottom - top)) * np.sqrt(2.0)
    return noise


@cache
def fbm(shape: tuple[int, int], period: int, seed: int, octaves: int = 4) -> Floats:
    """Fractional Brownian motion of `perlin_noise` (lacunarity 2, gain 1/2), mapped to [0, 1]."""
    total = np.zeros(shape)
    amplitude, norm = 1.0, 0.0
    for octave in range(octaves):
        total += amplitude * perlin_noise(shape, period * 2**octave, seed + 7919 * octave)
        norm += amplitude
        amplitude *= 0.5
    result: Floats = np.clip(0.5 + 0.5 * total / norm, 0.0, 1.0)
    result.flags.writeable = False  # cached: shared by every caller
    return result


# ------------------------------------------------------------------ Position generator

POSITION_DEFAULTS: Mapping[str, float] = {
    "position_direction_rightleft_opacity": 0.0,
    "position_direction_topbottom_opacity": 1.0,
    "position_direction_frontback_opacity": 0.0,
    "position_direction_rightleft_invert": 0,
    "position_direction_topbottom_invert": 0,
    "position_direction_frontback_invert": 0,
    "position_direction_rightleft_blendmode": 1,
    "position_direction_topbottom_blendmode": 1,
    "position_direction_frontback_blendmode": 1,
    "position_invert": 0,
    "position_balance": 0.5,
    "position_contrast": 0.0,
    "position_brightness": 0.0,
    "global_invert": 0,
    "global_blur": 0.0,
    "global_balance": 0.5,
    "global_contrast": 0.0,
    "visibleifTexture": 0,
}
LINEAR_DODGE = 1  # the documented "Linear Dodge (Add)" entry of the blending-mode list


@dataclass(frozen=True)
class StepCurve:
    """A balance/contrast setting calibrated as a hard step: out = clamp(1/2 + (x - T) g)."""

    threshold: float  # in summed 16-bit code units
    gain: float  # unit output per code unit


def position_generator(
    position: Codes,
    parameters: Mapping[str, float],
    curves: Mapping[tuple[float, float], StepCurve],
) -> Codes:
    """Painter's Position generator (A-HELP-GUIDE, *Position* generator page).

    Per the page: three directional gradients taken from the Position mesh map (Right to Left
    from its X channel, Top to Bottom from Y, Front to Back from Z), each with an opacity, an
    invert toggle and a blending mode, combined from black; then the section's invert, balance
    and contrast. The page names the axes, the invert, the "Linear Dodge (Add)" combination and
    the balance/contrast controls; the black-box calibration fixed the axis signs and showed
    that the default balance and contrast leave the gradient unchanged. Balance/contrast
    settings other than the default are served only at calibrated points (`curves`), as a
    hard step; others raise `UnsupportedParameters`.
    """
    values = {**POSITION_DEFAULTS, **parameters}
    for name in ("global_invert", "global_blur", "global_contrast", "visibleifTexture"):
        if values[name] != POSITION_DEFAULTS[name]:
            raise UnsupportedParameters(f"{name} = {values[name]} is not calibrated")
    if values["global_balance"] != 0.5 or values["position_brightness"] != 0.0:
        raise UnsupportedParameters("global balance and brightness are not calibrated")
    accumulated = np.zeros(position.shape[:2], np.float64)
    for axis, channel in (("rightleft", 0), ("topbottom", 1), ("frontback", 2)):
        opacity = float(values[f"position_direction_{axis}_opacity"])
        if opacity == 0.0:
            continue
        if values[f"position_direction_{axis}_blendmode"] != LINEAR_DODGE:
            raise UnsupportedParameters(f"{axis} blending mode is not calibrated")
        gradient = position[..., channel].astype(np.float64)
        if values[f"position_direction_{axis}_invert"]:
            gradient = FULL - gradient
        accumulated += opacity * gradient
    if values["position_invert"]:
        accumulated = FULL - accumulated
    key = (float(values["position_balance"]), float(values["position_contrast"]))
    if key == (0.5, 0.0):
        result: Codes = np.clip(np.floor(accumulated + 0.5), 0, FULL).astype(np.int64)
        return result
    if key not in curves:
        raise UnsupportedParameters(f"balance/contrast {key} is not calibrated")
    curve = curves[key]
    return to_codes(0.5 + (accumulated - curve.threshold) * curve.gain)


# ------------------------------------------------------------------ Metal Edge Wear generator

MEW_DEFAULTS: Mapping[str, float] = {
    "$randomseed": 0,
    "Wear_Level": 0.75,
    "Wear_Contrast": 0.5,
    "Grunge_Amount": 0.30000001192092896,
    "grunge_scale": 4,
    "Edges_Smoothness": 1.0,
    "Curvature_Weight": 1.0,
    "Ambient_Occlusion_Masking": 0.5,
}
MEW_FIT_NAMES = ("edge_gain", "blur_sigma", "grunge_gain", "bias", "contrast_gain")


def metal_edge_wear(
    curvature: Codes,
    ambient_occlusion: Codes,
    parameters: Mapping[str, float],
    fitted: Mapping[str, float],
) -> Codes:
    """Painter's Metal Edge Wear generator (A-HELP-GUIDE, *Metal Edge Wear* page).

    Per the page: edges come from the Curvature mesh map weighted by Curvature Weight and
    softened by Edges Smoothness; grunge of Grunge Amount at Grunge Scale (seeded) breaks them
    up; Wear Level sets the amount and Wear Contrast the sharpness of the result; Ambient
    Occlusion Masking keeps occluded areas clean. Convex curvature is the part of the map above
    its neutral 1/2 (A-HELP-BAKING); the grunge is fBm gradient noise (P-NOISE); the softening
    is a Gaussian blur. The gains, blur scale and bias are fitted constants.
    """
    values = {**MEW_DEFAULTS, **parameters}
    convex = np.maximum(unit(curvature[..., 0]) - 0.5, 0.0) * 2.0
    edges = gaussian_blur(convex, fitted["blur_sigma"] * float(values["Edges_Smoothness"]))
    grunge = fbm(convex.shape, int(values["grunge_scale"]), int(values["$randomseed"]))
    wear = (
        fitted["edge_gain"] * float(values["Curvature_Weight"]) * edges
        + fitted["grunge_gain"] * float(values["Grunge_Amount"]) * (grunge - 0.5)
        + fitted["bias"]
    )
    slope = 1.0 + fitted["contrast_gain"] * float(values["Wear_Contrast"])
    out = (wear - (1.0 - float(values["Wear_Level"]))) * slope + 0.5
    occlusion = unit(ambient_occlusion[..., 0])
    masking = float(values["Ambient_Occlusion_Masking"])
    return to_codes(np.clip(out, 0.0, 1.0) * (1.0 - masking + masking * occlusion))[..., None]


# ------------------------------------------------------------------ Leather Damaged

LEATHER_CHANNELS = ("basecolor", "specularroughness", "basemetalness", "height", "normal")


def leather_damaged(
    curvature: Codes, fitted: Mapping[str, Mapping[str, list[float]]], shape: tuple[int, int]
) -> dict[str, Codes]:
    """An independently designed leather recipe standing in for the Leather Damaged smart
    material (05 §3 publication rule: Painter's preset structure is never reproduced).

    Each exported channel is a fitted base value, plus a fitted share of leather grain (fBm
    gradient noise, P-NOISE) and of convex-edge wear from the Curvature mesh map
    (A-HELP-BAKING). Normal stays the flat tangent-space normal unless a fitted grain share
    says otherwise.
    """
    convex = np.maximum(unit(curvature[..., 0]) - 0.5, 0.0) * 2.0
    grain = fbm(shape, 16, 0, 5) - 0.5
    outputs: dict[str, Codes] = {}
    for channel in LEATHER_CHANNELS:
        terms = fitted[channel]
        base = np.array(terms["base"], np.float64)
        grain_share = np.array(terms["grain"], np.float64)
        edge_share = np.array(terms["edge"], np.float64)
        value = (
            base[None, None, :]
            + grain_share[None, None, :] * grain[..., None]
            + edge_share[None, None, :] * convex[..., None]
        )
        outputs[channel] = to_codes(value)
    return outputs
