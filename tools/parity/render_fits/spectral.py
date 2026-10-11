"""Spectral-versus-RGB sensitivity of the prototype (task item 2.5, decision 050).

A sensitivity bound for UzPainter's own transport, not evidence about Iray's internals: how
much a fixture's render would change if the products of environment radiance and base colour
were taken per wavelength instead of per RGB channel.

- Observer: the CIE 1931 2-degree colour-matching functions in the multi-lobe Gaussian fit of
  Wyman, Sloan and Shirley 2013 (P-WYMAN), 380-780 nm in 5 nm steps; XYZ to linear sRGB by the
  IEC 61966-2-1 matrix (S-SRGB). The channel responses are normalised so that the flat
  spectrum is RGB (1, 1, 1), i.e. the white of this comparison is the equal-energy spectrum.
- Upsampling: the sigmoid-polynomial spectra of Jakob and Hanika 2019 (P-JAKOB, as PBRT 4th ed.
  §4.6.6 uses them, P-PBRT), s(lambda) = 1/2 + z / (2 sqrt(1 + z^2)), z a quadratic in the
  normalised wavelength, solved per colour by Gauss-Newton so that the spectrum's RGB is the
  colour. An illuminant texel of RGB e is upsampled as 2m s(e / 2m), m = max(e).
- For one fixture with base colour rho (constant), the single-bounce render is linear in the
  environment, so the per-wavelength product only changes the diffuse part: the environment
  texel e is replaced, for the diffuse lobe, by e'_c = int r_c s_e s_rho / rho_c. The spectral
  part's change is [R(rho, env') - R(0, env')] - [R(rho, env) - R(0, env)] (R(0, .) is the white
  specular part), both under the environment box-averaged 8 x 8 (the diffuse lobe integrates
  it), added to the full-resolution RGB render; same seed, so the prototype's noise cancels.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.render_fits import bsdf, display, fit
from tools.parity.render_fits.fixtures import by_name, environment, srgb8
from tools.parity.render_fits.oracle import References

F64 = npt.NDArray[np.float64]
WAVELENGTHS = np.arange(380.0, 781.0, 5.0)
XYZ_TO_SRGB = np.array(
    [[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]]
)
LOBES = {
    "x": ((1.056, 599.8, 37.9, 31.0), (0.362, 442.0, 16.0, 26.7), (-0.065, 501.1, 20.4, 26.2)),
    "y": ((0.821, 568.8, 46.9, 40.5), (0.286, 530.9, 16.3, 31.1)),
    "z": ((1.217, 437.0, 11.8, 36.0), (0.681, 459.0, 26.0, 13.8)),
}


def piecewise_gaussian(lam: F64, mu: float, left: float, right: float) -> F64:
    sigma = np.where(lam < mu, left, right)
    result: F64 = np.exp(-0.5 * ((lam - mu) / sigma) ** 2)
    return result


def cmf(lam: F64 = WAVELENGTHS) -> F64:
    """x-bar, y-bar, z-bar (3, L)."""
    return np.stack(
        [sum(a * piecewise_gaussian(lam, m, s1, s2) for a, m, s1, s2 in LOBES[c]) for c in "xyz"]
    )


def response() -> F64:
    """RGB response per wavelength (3, L), quadrature weights included, flat spectrum -> 1."""
    raw = XYZ_TO_SRGB @ cmf()
    result: F64 = raw / raw.sum(axis=1, keepdims=True)
    return result


RESPONSE = response()
X = (WAVELENGTHS - WAVELENGTHS[0]) / (WAVELENGTHS[-1] - WAVELENGTHS[0])
DOWNSAMPLE = 8


def sigmoid_spectrum(coefficients: F64) -> F64:
    """(N, 3) coefficients -> (N, L) reflectance spectra."""
    z = coefficients[:, :1] * X**2 + coefficients[:, 1:2] * X + coefficients[:, 2:3]
    result: F64 = 0.5 + z / (2.0 * np.sqrt(1.0 + z * z))
    return result


def upsample(rgb: F64, iterations: int = 12) -> F64:
    """Sigmoid-polynomial spectra (N, L) whose RGB under RESPONSE is `rgb` (N, 3) in (0, 1)."""
    target = np.clip(rgb, 1e-4, 1.0 - 1e-4)
    coefficients = np.zeros((len(target), 3))
    for _ in range(iterations):
        spectrum = sigmoid_spectrum(coefficients)
        residual = spectrum @ RESPONSE.T - target
        jacobian = np.empty((len(target), 3, 3))
        for j in range(3):
            step = np.zeros(3)
            step[j] = 1e-4
            moved = sigmoid_spectrum(coefficients + step) @ RESPONSE.T
            jacobian[:, :, j] = (moved - (residual + target)) / 1e-4
        delta = np.linalg.solve(jacobian + 1e-9 * np.eye(3), -residual[..., None])[..., 0]
        coefficients += np.clip(delta, -50.0, 50.0)
    return sigmoid_spectrum(coefficients)


def downsample(texels: F64, factor: int = DOWNSAMPLE) -> F64:
    """Box average of factor x factor texels (the diffuse lobe integrates the environment)."""
    height, width, _ = texels.shape
    result: F64 = texels.reshape(height // factor, factor, width // factor, factor, 3).mean(
        axis=(1, 3)
    )
    return result


def spectral_environment(
    texels: F64, rho: tuple[float, float, float], chunk: int = 65536
) -> tuple[F64, float]:
    """The environment the diffuse lobe sees under per-wavelength products (H, W, 3), and the
    largest RGB round-trip error of the texel spectra."""
    rho_spectrum = upsample(np.asarray([rho]))[0]
    flat = texels.reshape(-1, 3)
    out = np.empty_like(flat)
    worst = 0.0
    for start in range(0, len(flat), chunk):
        part = np.maximum(flat[start : start + chunk], 0.0)
        scale = 2.0 * np.maximum(part.max(axis=1, keepdims=True), 1e-8)
        spectra = upsample(part / scale)
        worst = max(worst, float(np.abs(spectra @ RESPONSE.T - part / scale).max()))
        out[start : start + chunk] = (spectra * scale * rho_spectrum) @ RESPONSE.T
    rho_arr = np.maximum(np.asarray(rho), 1e-8)
    result: F64 = (out / rho_arr).reshape(texels.shape)
    return result, worst


def sensitivity(
    name: str, ref: References, variant: bsdf.Variant, scale: float, work: Path
) -> dict[str, Any]:
    """Spectral minus RGB for the diffuse part, both under the box-averaged environment."""
    golden = by_name(name)
    rho = tuple(srgb8(c) for c in golden.base_srgb)
    tag = f"{golden.preset}-{DOWNSAMPLE}-{'-'.join(f'{c:.6f}' for c in rho)}"
    folder = work / "spectral"
    rgb_path, spectral_path = folder / f"rgb-{tag}.npy", folder / f"spectral-{tag}.npy"
    texels = downsample(environment(golden.preset, 0.0).texels)
    round_trip = 0.0
    if not spectral_path.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        effective, round_trip = spectral_environment(texels, (rho[0], rho[1], rho[2]))
        np.save(rgb_path, texels)
        np.save(spectral_path, effective)
    mask = ref.regions["interior"]
    images = (ref.s[0].astype(np.float64), ref.s[1].astype(np.float64), ref.k.astype(np.float64))
    sample = fit.sample_pixels(name, mask, images)
    pixels = tuple(sample.pixels.tolist())
    common: dict[str, Any] = {"variant": variant, "environment_scale": scale, "spp": 256}
    black = (0.0, 0.0, 0.0)
    jobs = [
        fit.Job(name, pixels=pixels, **common),
        fit.Job(name, pixels=pixels, environment_file=str(spectral_path), **common),
        fit.Job(
            name, pixels=pixels, environment_file=str(spectral_path), base_override=black, **common
        ),
        fit.Job(name, pixels=pixels, environment_file=str(rgb_path), **common),
        fit.Job(name, pixels=pixels, environment_file=str(rgb_path), base_override=black, **common),
    ]
    full, spec_rho, spec_zero, rgb_rho, rgb_zero = fit.run_jobs(jobs, cache=work / "renders")
    change = (spec_rho - spec_zero) - (rgb_rho - rgb_zero)
    rgb_codes = display.to_codes(full)
    spectral_codes = display.to_codes(full + change)
    chroma = texels / np.maximum(texels.mean(axis=2, keepdims=True), 1e-8)
    return {
        "base_color_linear": list(rho),
        "environment_chroma_spread": float(np.percentile(np.abs(chroma - 1.0), 99)),
        "spectral_minus_rgb": fit.difference_statistics(spectral_codes - rgb_codes, sample.blocks),
        "rgb_vs_iray_k": fit.difference_statistics(rgb_codes - sample.k, sample.blocks),
        "spectral_vs_iray_k": fit.difference_statistics(spectral_codes - sample.k, sample.blocks),
        "upsampling_round_trip_max": max(
            round_trip,
            float(np.abs(upsample(np.asarray([rho]))[0] @ RESPONSE.T - np.asarray(rho)).max()),
        ),
        "environment_downsample": DOWNSAMPLE,
        "wavelengths": [float(WAVELENGTHS[0]), float(WAVELENGTHS[-1]), 5.0],
        "note": "sensitivity of the prototype, not evidence about Iray",
    }
