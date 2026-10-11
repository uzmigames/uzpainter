"""Infinite-sphere environment of the fixed pipeline (07 §3.2, §3.4; decisions 038, 046).

The environment is a latitude-longitude radiance map in linear RGB, read from the file the
pipeline names by SHA-256 (Studio White Soft for `v2`, the `ref_match` HDRI for the preset;
both stay outside the repository and are read on the owner's machine only). Exposure is 0, so
the radiance is the file's value times 2^0.

Direction to texel mapping (Y up; fitted black-box on the mirror sphere `neutral-reflective`,
see `parity/semantics/iray.json` entry `environment-mapping`):
    u = frac(atan2(-x, z) / (2 pi) + 1/4 + rotation / 360),  v = acos(y) / pi
with u along the image row and v down the image (row 0 is +Y). Lookup is bilinear on texel
centres, wrapping in u and clamping in v.

Importance sampling follows PBRT 4th ed. §12.5 (P-PBRT): a piecewise-constant 2D distribution
over the texels with weight luminance x sin(theta), sampled by inverting the marginal CDF of
the rows and the conditional CDF of the chosen row; the solid-angle density is
p(u, v) / (2 pi^2 sin(theta)).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

F64 = npt.NDArray[np.float64]
LUMINANCE = np.array([0.2126, 0.7152, 0.0722])  # IEC 61966-2-1 (BT.709 primaries) Y row


def read_exr(path: Path) -> F64:
    """RGB of a scanline OpenEXR file as float64 (H, W, 3); owner's machine only."""
    import OpenEXR

    with OpenEXR.File(str(path)) as exr:
        channels = exr.parts[0].channels
        if "RGBA" in channels:
            pixels = channels["RGBA"].pixels[..., :3]
        elif "RGB" in channels:
            pixels = channels["RGB"].pixels
        else:
            pixels = np.stack([channels[c].pixels for c in ("R", "G", "B")], axis=-1)
    return np.asarray(pixels, dtype=np.float64)


@dataclass
class Environment:
    texels: F64
    rotation: float = 0.0

    def __post_init__(self) -> None:
        height, width, _ = self.texels.shape
        theta = (np.arange(height) + 0.5) / height * math.pi
        weight = np.maximum(self.texels @ LUMINANCE, 0.0) * np.sin(theta)[:, None]
        if not np.all(np.isfinite(weight)) or weight.sum() <= 0.0:
            raise ValueError("the environment has no finite positive radiance")
        row_sums = weight.sum(axis=1)
        self.marginal = np.concatenate([[0.0], np.cumsum(row_sums)]) / row_sums.sum()
        conditional = np.cumsum(weight, axis=1)
        safe = np.where(row_sums > 0.0, row_sums, 1.0)
        self.conditional = np.concatenate([np.zeros((height, 1)), conditional], axis=1)
        self.conditional /= safe[:, None]
        self.flat_cdf = (self.conditional + np.arange(height)[:, None]).ravel()
        # Piecewise-constant density over (u, v) in [0, 1)^2.
        self.density = weight / weight.sum() * (height * width)

    @property
    def shape(self) -> tuple[int, int]:
        height, width, _ = self.texels.shape
        return height, width

    def uv(self, direction: F64) -> tuple[F64, F64]:
        x, y, z = direction[..., 0], direction[..., 1], direction[..., 2]
        u = np.mod(np.arctan2(-x, z) / (2.0 * math.pi) + 0.25 + self.rotation / 360.0, 1.0)
        v = np.arccos(np.clip(y, -1.0, 1.0)) / math.pi
        return u, v

    def direction(self, u: F64, v: F64) -> F64:
        phi = (u - 0.25 - self.rotation / 360.0) * 2.0 * math.pi
        theta = v * math.pi
        sin_theta = np.sin(theta)
        # atan2(-x, z) = phi  =>  x = -sin(phi) sin(theta), z = cos(phi) sin(theta)
        return np.stack([-np.sin(phi) * sin_theta, np.cos(theta), np.cos(phi) * sin_theta], axis=-1)

    def radiance(self, direction: F64) -> F64:
        """Bilinear lookup of the radiance seen along each unit direction."""
        height, width = self.shape
        u, v = self.uv(direction)
        fx = u * width - 0.5
        fy = v * height - 0.5
        x0 = np.floor(fx).astype(np.int64)
        y0 = np.floor(fy).astype(np.int64)
        ax = (fx - x0)[..., None]
        ay = (fy - y0)[..., None]
        x1 = np.mod(x0 + 1, width)
        x0 = np.mod(x0, width)
        y1 = np.clip(y0 + 1, 0, height - 1)
        y0 = np.clip(y0, 0, height - 1)
        t = self.texels
        top = (1.0 - ax) * t[y0, x0] + ax * t[y0, x1]
        bottom = (1.0 - ax) * t[y1, x0] + ax * t[y1, x1]
        result: F64 = (1.0 - ay) * top + ay * bottom
        return result

    def sample(self, xi: F64) -> tuple[F64, F64]:
        """Directions and solid-angle densities for uniform pairs xi (N, 2)."""
        height, width = self.shape
        row = np.clip(np.searchsorted(self.marginal, xi[:, 1], side="right") - 1, 0, height - 1)
        low, high = self.marginal[row], self.marginal[row + 1]
        dv = np.where(high > low, (xi[:, 1] - low) / np.where(high > low, high - low, 1.0), 0.5)
        # Row r's conditional CDF shifted by r: one non-decreasing array for every row.
        position = np.searchsorted(self.flat_cdf, xi[:, 0] + row, side="right") - 1
        col = np.clip(position - row * (width + 1), 0, width - 1)
        c_low = self.conditional[row, col]
        c_high = self.conditional[row, col + 1]
        span = c_high - c_low
        du = np.where(span > 0, (xi[:, 0] - c_low) / np.where(span > 0, span, 1.0), 0.5)
        u = (col + du) / width
        v = (row + dv) / height
        directions = self.direction(u, v)
        return directions, self.pdf_uv(row, col, v)

    def pdf_uv(self, row: npt.NDArray[np.int64], col: npt.NDArray[np.int64], v: F64) -> F64:
        sin_theta = np.sin(v * math.pi)
        density = self.density[row, col]
        pdf: F64 = np.where(
            sin_theta > 0, density / (2.0 * math.pi * math.pi * np.maximum(sin_theta, 1e-12)), 0
        )
        return pdf

    def pdf(self, direction: F64) -> F64:
        """Solid-angle density of `sample` for each unit direction."""
        height, width = self.shape
        u, v = self.uv(direction)
        row = np.clip((v * height).astype(np.int64), 0, height - 1)
        col = np.clip((u * width).astype(np.int64), 0, width - 1)
        return self.pdf_uv(row, col, v)


def constant(radiance: float, height: int = 32, width: int = 64) -> Environment:
    """A uniform environment (the white furnace of task item 3.1)."""
    return Environment(np.full((height, width, 3), radiance, dtype=np.float64))
