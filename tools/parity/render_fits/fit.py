"""Black-box lobe fits of the prototype against the admitted Iray references (task item 2.4).

Procedure (decision 050):

1. Pixels: the interior region of each golden, sampled on a grid of every `STEP`-th row and
   column. The 16 x 16 pixel blocks of the image are split like a chessboard: variants and
   constants are chosen on the `fit` half and every residual is reported on the `held-out`
   half, so the selection does not grade itself. The `ref_match` goldens (another environment)
   and the plane and cube (other geometry) are held out entirely.
2. Target: the k*S render (Iray's best estimate); residuals are also given against both S
   renders. Everything is compared in the reference's encoding (16-bit display codes,
   `display.to_codes`).
3. Variants: the discrete lobe choices of `bsdf.Variant` are rendered at `SPP` samples with one
   fixed seed; one global environment intensity scale is then fitted on the fit half by a
   golden-section search (the render is linear in the environment, so no re-render is needed).
   The metal variant is chosen on the metal goldens, the dielectric variant on the dielectric
   goldens, both with the shared roughness mapping and scale. The score is the RMS of the
   per-pixel display difference on the fit half; every variant's score is kept.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import os
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.render_fits import bsdf, display
from tools.parity.render_fits.environment import Environment
from tools.parity.render_fits.fixtures import by_name, scene_fixture
from tools.parity.render_fits.render import PixelFilter, Settings, render

F64 = npt.NDArray[np.float64]
I64 = npt.NDArray[np.int64]
STEP = 8
BLOCK = 16
SPP = 64
SEED = 1
METAL_GOLDENS = ("neutral-reflective", "metal1-rough010", "metal1-rough050", "metal1-rough090")
DIELECTRIC_GOLDENS = (
    "neutral-grey-diffuse",
    "base-light-grey",
    "base-saturated",
    "metal0-rough010",
    "metal0-rough050",
    "metal0-rough090",
)
FIT_GOLDENS = METAL_GOLDENS + DIELECTRIC_GOLDENS
HELD_OUT_GOLDENS = (
    "normal-ridges",
    "height-stripes",
    "emission",
    "opacity-stripes",
    "plane-mid-grey",
    "cube-mid-grey",
    "neutral-grey-diffuse--ref-match-000",
    "neutral-grey-diffuse--ref-match-180",
    "neutral-reflective--ref-match-000",
    "neutral-reflective--ref-match-180",
    "cube-saturated--ref-match-000",
    "cube-saturated--ref-match-180",
)


@dataclass
class Sample:
    """The sampled pixels of one golden and their reference codes."""

    name: str
    pixels: I64  # y * W + x
    fit: npt.NDArray[np.bool_]  # chessboard half used for fitting
    k: F64  # (N, 3) codes
    s: tuple[F64, F64]
    blocks: I64  # block index of each pixel (for standard errors)


def sample_pixels(
    name: str, mask: npt.NDArray[np.bool_], images: tuple[F64, F64, F64], step: int = STEP
) -> Sample:
    _, width = mask.shape
    ys, xs = np.nonzero(mask)
    keep = (ys % step == step // 2) & (xs % step == step // 2)
    ys, xs = ys[keep], xs[keep]
    by, bx = ys // BLOCK, xs // BLOCK
    s1, s2, k = images
    return Sample(
        name,
        (ys * width + xs).astype(np.int64),
        (by + bx) % 2 == 0,
        k[ys, xs],
        (s1[ys, xs], s2[ys, xs]),
        (by * (width // BLOCK + 1) + bx).astype(np.int64),
    )


def difference_statistics(delta: F64, blocks: I64) -> dict[str, Any]:
    """|delta| statistics in 16-bit codes and the mean signed delta with a block standard error
    (pixels sampled on a grid; blocks of 16 x 16 image pixels)."""
    magnitude = np.abs(delta)
    unique, inverse = np.unique(blocks, return_inverse=True)
    sums = np.zeros((len(unique), 3))
    np.add.at(sums, inverse, delta)
    counts = np.bincount(inverse, minlength=len(unique))[:, None]
    means = (sums / counts).mean(axis=1)
    error = float(np.std(means, ddof=1) / math.sqrt(len(means))) if len(means) > 1 else math.nan
    return {
        "pixels": len(delta),
        "max_abs": float(magnitude.max()),
        "mean_abs": float(magnitude.mean()),
        "p99_abs": float(np.percentile(magnitude, 99)),
        "rms": float(np.sqrt(np.mean(delta * delta))),
        "differing": int(np.any(delta != 0, axis=1).sum()),
        "differing_samples": int((delta != 0).sum()),
        "mean_signed": float(delta.mean()),
        "mean_signed_se": error,
        "mean_signed_per_channel": [float(v) for v in delta.mean(axis=0)],
    }


@dataclass(frozen=True)
class Job:
    name: str
    variant: bsdf.Variant
    pixels: tuple[int, ...]
    spp: int = SPP
    seed: int = SEED
    bump_strength: float = 0.0
    pixel_filter: PixelFilter = field(default_factory=PixelFilter)
    below_facet: str = "absorb"
    max_depth: int = 8
    rotation_offset: float = 0.0  # added to the preset's rotation (defect detection)
    environment_scale: float = 1.0
    drop_perturbation: bool = False  # defect detection: the perturbation channel is missing
    roughness_offset: float = 0.0  # defect detection: added to the golden's roughness
    environment_file: str = ""  # .npy texels replacing the preset's environment (spectral)
    base_override: tuple[float, float, float] | None = None  # linear base colour


def run_job(job: Job) -> F64:
    golden = by_name(job.name)
    if job.rotation_offset:
        golden = replace(golden, rotation=golden.rotation + job.rotation_offset)
    if job.drop_perturbation:
        golden = replace(golden, perturbation=None)
    if job.roughness_offset:
        golden = replace(golden, roughness=min(1.0, golden.roughness + job.roughness_offset))
    fixture = scene_fixture(golden, job.bump_strength)
    if job.environment_file:
        fixture.environment = Environment(np.load(job.environment_file), golden.rotation)
    if job.base_override is not None:
        fixture.base_color = job.base_override
    settings = Settings(
        variant=job.variant,
        pixel_filter=job.pixel_filter,
        below_facet=job.below_facet,
        max_depth=job.max_depth,
        environment_scale=job.environment_scale,
    )
    return render(fixture, np.asarray(job.pixels, dtype=np.int64), job.spp, job.seed, settings)


def job_key(job: Job) -> str:
    return hashlib.sha256(repr(job).encode("utf-8")).hexdigest()[:32]


def run_jobs(jobs: list[Job], workers: int | None = None, cache: Path | None = None) -> list[F64]:
    """Render every job, in parallel processes; with `cache`, finished renders are kept as
    .npy files named by the job's hash (UzPainter's own outputs, outside the repository)."""
    results: dict[int, F64] = {}
    todo: list[int] = []
    for i, job in enumerate(jobs):
        path = cache / f"{job_key(job)}.npy" if cache else None
        if path is not None and path.is_file():
            results[i] = np.load(path)
        else:
            todo.append(i)
    workers = workers or max(1, min(len(todo), (os.cpu_count() or 2) - 2))
    if todo and workers == 1:
        done = [run_job(jobs[i]) for i in todo]
    elif todo:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            done = list(pool.map(run_job, [jobs[i] for i in todo], chunksize=1))
    else:
        done = []
    for i, value in zip(todo, done, strict=True):
        results[i] = value
        if cache is not None:
            cache.mkdir(parents=True, exist_ok=True)
            np.save(cache / f"{job_key(jobs[i])}.npy", value)
    return [results[i] for i in range(len(jobs))]


def score(linear: F64, sample: Sample, scale: float, part: npt.NDArray[np.bool_]) -> float:
    delta = display.to_codes(linear[part] * scale) - sample.k[part]
    return float(np.sqrt(np.mean(delta * delta)))


def golden_section(
    func: Callable[[float], float], low: float, high: float, steps: int = 40
) -> float:
    ratio = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = low, high
    c, d = b - ratio * (b - a), a + ratio * (b - a)
    fc, fd = func(c), func(d)
    for _ in range(steps):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - ratio * (b - a)
            fc = func(c)
        else:
            a, c, fc = c, d, fd
            d = a + ratio * (b - a)
            fd = func(d)
    return (a + b) / 2.0


def joint_score(renders: Iterable[tuple[F64, Sample]], scale: float) -> float:
    total, count = 0.0, 0
    for linear, sample in renders:
        delta = display.to_codes(linear[sample.fit] * scale) - sample.k[sample.fit]
        total += float(np.sum(delta * delta))
        count += delta.size
    return math.sqrt(total / count)


def metal_variants() -> list[bsdf.Variant]:
    return [
        bsdf.Variant(roughness_map=r, multiscatter=m)
        for r in ("squared", "linear")
        for m in bsdf.MULTISCATTER
        if m != "tint_f0"
    ]


def dielectric_variants(roughness_map: str) -> list[bsdf.Variant]:
    return [
        bsdf.Variant(
            roughness_map=roughness_map,
            dielectric_fresnel=f,
            diffuse=d,
            layering=lay,
            dielectric_multiscatter=m,
        )
        for f, d, lay, m in itertools.product(
            ("exact", "schlick"),
            ("lambert", "burley"),
            bsdf.LAYERINGS,
            bsdf.MULTISCATTER,
        )
    ]


def variant_record(variant: bsdf.Variant) -> dict[str, Any]:
    return asdict(variant)
