"""Every measurement of task `phase0.8_render-reference-fits`, as numbers (decision 050).

`run(store, work)` loads the admitted references from the private store, renders the
prototype (renders cached under `work`, outside the repository) and returns one JSON-able
dictionary that `semantics.py` and `report.py` turn into `parity/semantics/iray.json` and
`parity/reports/phase0/iray-noise-floor.md`. No pixel, crop or difference map leaves it.

Parts (task items): `display` (2.3), `fits` and `held_out` (2.4), `pixel_filter` (2.3),
`transport` (2.5), `noise` with terms (a), (b), (c) per region (2.6, 2.7), `stability` (the
run-to-run structure), `defects` (3.2) and `repeatability` (3.3).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.render_fits import bsdf, display, fit, spectral, stability
from tools.parity.render_fits.fixtures import by_name, scene_fixture
from tools.parity.render_fits.oracle import References, load
from tools.parity.render_fits.render import PixelFilter
from tools.parity.render_procedure.noise import (
    DOWNSAMPLES,
    FULL_SCALE,
    pair_statistics,
    region_statistics,
)
from tools.parity.store.store import OracleStore

F64 = npt.NDArray[np.float64]
Mask = npt.NDArray[np.bool_]
ALL_GOLDENS = fit.FIT_GOLDENS + fit.HELD_OUT_GOLDENS
FACE_GOLDENS = (
    "plane-mid-grey",
    "cube-mid-grey",
    "cube-saturated--ref-match-000",
    "cube-saturated--ref-match-180",
)
CROP = 256
S_SAMPLES, K_FACTOR = 256, 4
PROTOTYPE_SEEDS = (1, 2)
HELD_OUT_SPP = 256
FILTERS = (
    PixelFilter("box"),
    PixelFilter("gaussian", 0.3, 2.0),
    PixelFilter("gaussian", 0.5, 2.0),
    PixelFilter("gaussian", 0.8, 2.0),
)
FILTER_GOLDENS = ("neutral-grey-diffuse", "plane-mid-grey", "cube-mid-grey")
DEFECT_GOLDENS = {
    "missing_channel": "normal-ridges",
    "wrong_lobe": "metal0-rough050",
    "roughness_offset": "metal1-rough050",
    "environment_rotation": "cube-saturated--ref-match-000",
}


def as_fraction(image: npt.NDArray[np.uint16]) -> F64:
    result: F64 = image.astype(np.float64) / FULL_SCALE
    return result


def references(store: OracleStore | None) -> dict[str, References]:
    return {name: load(store, name) for name in ALL_GOLDENS}


def display_part(refs: dict[str, References]) -> dict[str, Any]:
    images: list[F64] = []
    for ref in refs.values():
        mask = ref.regions["interior"]
        for image in (*ref.s, ref.k):
            images.append(image[mask].astype(np.float64))
    return {"interior": display.lattice_statistics(images)}


def stability_part(refs: dict[str, References]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, ref in refs.items():
        s1, s2 = (x.astype(np.float64) for x in ref.s)
        k = ref.k.astype(np.float64)
        entry: dict[str, Any] = {}
        for region in ("interior", "edge"):
            mask = ref.regions[region]
            entry[region] = {
                "half_steps": stability.half_steps(s1, s2, mask),
                "sequence": stability.sequence_test(s1, k, mask, K_FACTOR),
            }
            seq = entry[region]["sequence"]
            entry[region]["jensen_predicted"] = stability.jensen_bias(
                k, seq["sigma_s"], seq["sigma_k"], mask
            )
            observed = [float((s - k)[mask].mean()) for s in (s1, s2)]
            entry[region]["mean_signed_s_minus_k"] = observed
        if name in FACE_GOLDENS:
            golden = by_name(name)
            scene = scene_fixture(golden)
            faces = stability.face_regions(scene.mesh, scene.camera, ref.regions["interior"])
            entry["faces"] = {
                label: {
                    "pixels": int(mask.sum()),
                    "run_to_run": region_statistics((s1 - s2)[..., :] / FULL_SCALE, mask),
                    "half_steps": stability.half_steps(s1, s2, mask),
                    "mc_error_at_s": region_statistics((s1 - k) / FULL_SCALE, mask),
                }
                for label, mask in faces.items()
            }
        out[name] = entry
    return out


def noise_ab(refs: dict[str, References]) -> dict[str, Any]:
    """Terms (a) and (b) per region, as `noise.pair_statistics` computes them (fractions of
    full scale)."""
    out: dict[str, Any] = {}
    for name, ref in refs.items():
        s1, s2, k = (as_fraction(x) for x in (*ref.s, ref.k))
        masks = {r: ref.regions[r] for r in ("interior", "edge", "background")}
        out[name] = {
            "run_to_run": pair_statistics(s1, s2, masks),
            "mc_error_at_s": [pair_statistics(s, k, masks) for s in (s1, s2)],
        }
    return out


def samples(refs: dict[str, References], names: tuple[str, ...]) -> dict[str, fit.Sample]:
    out = {}
    for name in names:
        ref = refs[name]
        images = (
            ref.s[0].astype(np.float64),
            ref.s[1].astype(np.float64),
            ref.k.astype(np.float64),
        )
        out[name] = fit.sample_pixels(name, ref.regions["interior"], images)
    return out


def block_score(items: list[tuple[F64, fit.Sample]], scale: float) -> float:
    """RMS over 64 x 64-pixel blocks of the mean display difference on the fit half (the
    prototype's own noise averages out within a block; a lobe mismatch does not)."""
    total, count = 0.0, 0
    for linear, sample in items:
        part = sample.fit
        delta = display.to_codes(linear[part] * scale) - sample.k[part]
        ys, xs = sample.pixels[part] // 1200, sample.pixels[part] % 1200
        blocks = (ys // 64) * 100 + xs // 64
        unique, inverse = np.unique(blocks, return_inverse=True)
        sums = np.zeros((len(unique), 3))
        np.add.at(sums, inverse, delta)
        means = sums / np.bincount(inverse)[:, None]
        total += float(np.sum(means * means))
        count += means.size
    return math.sqrt(total / count)


def fits_part(refs: dict[str, References], work: Path) -> dict[str, Any]:
    fit_samples = samples(refs, fit.FIT_GOLDENS)
    jobs: list[fit.Job] = []
    keys: list[tuple[str, int, str]] = []
    metal = fit.metal_variants()
    for i, variant in enumerate(metal):
        for name in fit.METAL_GOLDENS:
            jobs.append(fit.Job(name, variant, tuple(fit_samples[name].pixels.tolist())))
            keys.append(("metal", i, name))
    dielectric = [v for rm in ("squared", "linear") for v in fit.dielectric_variants(rm)]
    for i, variant in enumerate(dielectric):
        for name in fit.DIELECTRIC_GOLDENS:
            jobs.append(fit.Job(name, variant, tuple(fit_samples[name].pixels.tolist())))
            keys.append(("dielectric", i, name))
    renders = fit.run_jobs(jobs, cache=work / "renders")
    by_key = dict(zip(keys, renders, strict=True))
    candidates: list[dict[str, Any]] = []
    for mi, mv in enumerate(metal):
        for di, dv in enumerate(dielectric):
            if dv.roughness_map != mv.roughness_map:
                continue
            pairs = [(by_key[("metal", mi, n)], fit_samples[n]) for n in fit.METAL_GOLDENS]
            pairs += [
                (by_key[("dielectric", di, n)], fit_samples[n]) for n in fit.DIELECTRIC_GOLDENS
            ]
            candidates.append(
                {
                    "metal": mi,
                    "dielectric": di,
                    "items": pairs,
                    "score_unit_scale": block_score(pairs, 1.0),
                }
            )
    candidates.sort(key=lambda c: c["score_unit_scale"])
    ranked = []
    for candidate in candidates[:12]:
        items: list[tuple[F64, fit.Sample]] = candidate["items"]

        def objective(value: float, it: list[tuple[F64, fit.Sample]] = items) -> float:
            return block_score(it, value)

        scale = fit.golden_section(objective, 0.8, 1.25)
        ranked.append({**candidate, "scale": scale, "score": block_score(items, scale)})
    ranked.sort(key=lambda c: c["score"])
    best = ranked[0]
    chosen = replace(
        dielectric[best["dielectric"]],
        multiscatter=metal[best["metal"]].multiscatter,
    )
    table = [
        {
            "metal": fit.variant_record(metal[c["metal"]]),
            "dielectric": fit.variant_record(dielectric[c["dielectric"]]),
            "score_unit_scale": c["score_unit_scale"],
            "scale": c.get("scale"),
            "score": c.get("score"),
        }
        for c in ranked + candidates[12:]
    ]
    return {
        "variant": fit.variant_record(chosen),
        "environment_scale": best["scale"],
        "score": best["score"],
        "candidates": len(candidates),
        "ranking": table[:16],
        "_variant": chosen,
    }


def bump_part(
    refs: dict[str, References], variant: bsdf.Variant, scale: float, work: Path
) -> dict[str, Any]:
    sample = samples(refs, ("height-stripes",))["height-stripes"]
    pixels = tuple(sample.pixels.tolist())
    grid = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
    jobs = [
        fit.Job("height-stripes", variant, pixels, bump_strength=k, environment_scale=scale)
        for k in grid
    ]
    renders = fit.run_jobs(jobs, cache=work / "renders")
    scores = [block_score([(r, sample)], 1.0) for r in renders]
    rms = [
        float(np.sqrt(np.mean((display.to_codes(r[sample.fit]) - sample.k[sample.fit]) ** 2)))
        for r in renders
    ]
    best = int(np.argmin(rms))
    return {"grid": list(grid), "block_scores": scores, "rms": rms, "strength": grid[best]}


def residual_entry(delta: F64, sample: fit.Sample, part: npt.NDArray[np.bool_]) -> dict[str, Any]:
    stats = fit.difference_statistics(delta[part], sample.blocks[part])
    return stats


def held_out_part(
    refs: dict[str, References], variant: bsdf.Variant, scale: float, bump: float, work: Path
) -> dict[str, Any]:
    all_samples = samples(refs, ALL_GOLDENS)
    jobs = [
        fit.Job(
            name,
            variant,
            tuple(all_samples[name].pixels.tolist()),
            spp=HELD_OUT_SPP,
            bump_strength=bump,
            environment_scale=scale,
        )
        for name in ALL_GOLDENS
    ]
    renders = fit.run_jobs(jobs, cache=work / "renders")
    out: dict[str, Any] = {}
    for name, linear in zip(ALL_GOLDENS, renders, strict=True):
        sample = all_samples[name]
        codes = display.to_codes(linear)
        part = ~sample.fit if name in fit.FIT_GOLDENS else np.ones_like(sample.fit)
        out[name] = {
            "held_out": "chessboard half" if name in fit.FIT_GOLDENS else "whole golden",
            "k": residual_entry(codes - sample.k, sample, part),
            "s1": residual_entry(codes - sample.s[0], sample, part),
            "s2": residual_entry(codes - sample.s[1], sample, part),
        }
    return out


def filter_part(
    refs: dict[str, References], variant: bsdf.Variant, scale: float, work: Path
) -> dict[str, Any]:
    jobs: list[fit.Job] = []
    meta: list[tuple[str, PixelFilter, F64]] = []
    for name in FILTER_GOLDENS:
        ref = refs[name]
        ys, xs = np.nonzero(ref.regions["edge"])
        pixels = tuple((ys * 1200 + xs).tolist())
        for pf in FILTERS:
            jobs.append(
                fit.Job(
                    name, variant, pixels, spp=S_SAMPLES, pixel_filter=pf, environment_scale=scale
                )
            )
            meta.append((name, pf, ref.k[ys, xs].astype(np.float64)))
    renders = fit.run_jobs(jobs, cache=work / "renders")
    rows: list[dict[str, Any]] = []
    for (name, pf, k), linear in zip(meta, renders, strict=True):
        delta = display.to_codes(linear) - k
        rows.append(
            {
                "golden": name,
                "filter": pf.kind if pf.kind == "box" else f"gaussian sigma {pf.sigma:g} px",
                "edge_mean_abs": float(np.abs(delta).mean()),
                "edge_rms": float(np.sqrt(np.mean(delta * delta))),
                "edge_mean_signed": float(delta.mean()),
            }
        )
    totals: dict[str, float] = {}
    for row in rows:
        label = str(row["filter"])
        totals[label] = totals.get(label, 0.0) + float(row["edge_mean_abs"])
    return {"rows": rows, "chosen": min(totals, key=lambda f: totals[f])}


def crop_pixels(ref: References) -> tuple[npt.NDArray[np.int64], tuple[int, int]]:
    """A CROP x CROP window from the interior's centroid toward the lower right, so it holds
    interior, edge band and background."""
    ys, xs = np.nonzero(ref.regions["interior"])
    y0 = int(np.clip(int(ys.mean()), 0, 1200 - CROP))
    x0 = int(np.clip(int(xs.mean()), 0, 1200 - CROP))
    yy, xx = np.mgrid[y0 : y0 + CROP, x0 : x0 + CROP]
    return (yy * 1200 + xx).ravel().astype(np.int64), (y0, x0)


def crop(image: npt.NDArray[Any], origin: tuple[int, int]) -> npt.NDArray[Any]:
    y0, x0 = origin
    return image[y0 : y0 + CROP, x0 : x0 + CROP]


def chunks(pixels: npt.NDArray[np.int64], size: int = 8192) -> list[tuple[int, ...]]:
    return [tuple(pixels[i : i + size].tolist()) for i in range(0, len(pixels), size)]


def render_crops(
    requests: list[tuple[str, npt.NDArray[np.int64], dict[str, Any]]], work: Path
) -> list[F64]:
    """Render several CROP x CROP windows in one process pool; each request is
    (golden, pixel indices, Job keyword arguments)."""
    jobs: list[fit.Job] = []
    owners: list[int] = []
    for index, (name, pixels, kw) in enumerate(requests):
        for part in chunks(pixels):
            jobs.append(fit.Job(name, pixels=part, **kw))
            owners.append(index)
    renders = fit.run_jobs(jobs, cache=work / "renders")
    images: list[F64] = []
    for index in range(len(requests)):
        parts = [r for r, o in zip(renders, owners, strict=True) if o == index]
        images.append(np.concatenate(parts).reshape(CROP, CROP, 3))
    return images


def flip_regions(reference: F64, test: F64, masks: dict[str, Mask]) -> dict[str, float]:
    """Mean FLIP (LDR, inputs in the display encoding) per region; diagnostic only."""
    import flip_evaluator

    error, _, _ = flip_evaluator.evaluate(
        reference.astype(np.float32),
        test.astype(np.float32),
        "LDR",
        applyMagma=False,
        computeMeanError=False,
    )
    flip_map = np.asarray(error)
    return {r: float(flip_map[m].mean()) for r, m in masks.items() if m.any()}


def noise_c_part(
    refs: dict[str, References],
    variant: bsdf.Variant,
    scale: float,
    bump: float,
    work: Path,
    flip: bool,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    common = {"variant": variant, "environment_scale": scale, "bump_strength": bump}
    requests: list[tuple[str, npt.NDArray[np.int64], dict[str, Any]]] = []
    for name in ALL_GOLDENS:
        pixels, _ = crop_pixels(refs[name])
        for seed in PROTOTYPE_SEEDS:
            requests.append((name, pixels, {**common, "spp": S_SAMPLES, "seed": seed}))
        requests.append(
            (name, pixels, {**common, "spp": S_SAMPLES * K_FACTOR, "seed": PROTOTYPE_SEEDS[0]})
        )
    images = render_crops(requests, work)
    for index, name in enumerate(ALL_GOLDENS):
        ref = refs[name]
        _, origin = crop_pixels(ref)
        renders = images[3 * index : 3 * index + 3]
        to_frac = [display.to_codes(x) / FULL_SCALE for x in renders]
        masks = {r: crop(ref.regions[r], origin) for r in ("interior", "edge", "background")}
        iray_k = crop(as_fraction(ref.k), origin)
        iray_s = [crop(as_fraction(s), origin) for s in ref.s]
        entry: dict[str, Any] = {
            "crop_origin": list(origin),
            "crop_size": CROP,
            "c_seeds": list(PROTOTYPE_SEEDS),
            "c": [pair_statistics(to_frac[i], to_frac[2], masks) for i in range(2)],
            "c_seed_to_seed": pair_statistics(to_frac[0], to_frac[1], masks),
            "b_crop": [pair_statistics(s, iray_k, masks) for s in iray_s],
            "fit_vs_iray_k": pair_statistics(to_frac[0], iray_k, masks),
            "fit_vs_iray_s": [pair_statistics(to_frac[0], s, masks) for s in iray_s],
        }
        if flip:
            entry["flip"] = {
                "iray_s_vs_k": flip_regions(iray_k, iray_s[0], masks),
                "prototype_s_vs_iray_k": flip_regions(iray_k, to_frac[0], masks),
                "prototype_s_vs_prototype_k": flip_regions(to_frac[2], to_frac[0], masks),
            }
        out[name] = entry
    return out


def defects_part(
    refs: dict[str, References], variant: bsdf.Variant, scale: float, bump: float, work: Path
) -> dict[str, Any]:
    """Item 3.2: each defect rendered at S on the golden's crop, compared with Iray's k*S like
    the fitted model."""
    defects: dict[str, dict[str, Any]] = {
        "missing_channel": {"drop_perturbation": True},
        "wrong_lobe": {"variant": replace(variant, diffuse="burley", layering="none")},
        "roughness_offset": {"roughness_offset": 0.2},
        "environment_rotation": {"rotation_offset": 90.0},
    }
    out: dict[str, Any] = {}
    common: dict[str, Any] = {
        "variant": variant,
        "environment_scale": scale,
        "bump_strength": bump,
        "spp": S_SAMPLES,
        "seed": PROTOTYPE_SEEDS[0],
    }
    requests: list[tuple[str, npt.NDArray[np.int64], dict[str, Any]]] = []
    for defect, change in defects.items():
        name = DEFECT_GOLDENS[defect]
        pixels, _ = crop_pixels(refs[name])
        requests.append((name, pixels, dict(common)))
        requests.append((name, pixels, {**common, **change}))
    images = render_crops(requests, work)
    for index, defect in enumerate(defects):
        name = DEFECT_GOLDENS[defect]
        ref = refs[name]
        _, origin = crop_pixels(ref)
        masks = {r: crop(ref.regions[r], origin) for r in ("interior", "edge")}
        iray_k = crop(as_fraction(ref.k), origin)
        fitted, broken = images[2 * index], images[2 * index + 1]
        out[defect] = {
            "golden": name,
            "fitted": pair_statistics(display.to_codes(fitted) / FULL_SCALE, iray_k, masks),
            "defect": pair_statistics(display.to_codes(broken) / FULL_SCALE, iray_k, masks),
            "defect_vs_fitted": pair_statistics(
                display.to_codes(broken) / FULL_SCALE,
                display.to_codes(fitted) / FULL_SCALE,
                masks,
            ),
        }
    return out


def transport_part(
    refs: dict[str, References], variant: bsdf.Variant, scale: float, bump: float, work: Path
) -> dict[str, Any]:
    """Item 2.5: below-facet handling and path depth, and the spectral sensitivity."""
    out: dict[str, Any] = {"below_facet": {}, "spectral": {}}
    goldens = ("normal-ridges", "height-stripes", "plane-mid-grey", "neutral-grey-diffuse")
    picked = samples(refs, goldens)
    for name in goldens:
        sample = picked[name]
        pixels = tuple(sample.pixels.tolist())
        runs: dict[str, dict[str, Any]] = {
            "absorb_depth1": {"below_facet": "absorb", "max_depth": 1},
            "absorb_depth8": {"below_facet": "absorb", "max_depth": 8},
            "trace_depth1": {"below_facet": "trace", "max_depth": 1},
            "trace_depth8": {"below_facet": "trace", "max_depth": 8},
        }
        jobs = [
            fit.Job(
                name,
                variant,
                pixels,
                spp=HELD_OUT_SPP,
                bump_strength=bump,
                environment_scale=scale,
                **kw,
            )
            for kw in runs.values()
        ]
        renders = dict(zip(runs, fit.run_jobs(jobs, cache=work / "renders"), strict=True))
        base = display.to_codes(renders["absorb_depth8"])
        out["below_facet"][name] = {
            label: {
                "vs_absorb_depth8": fit.difference_statistics(
                    display.to_codes(linear) - base, sample.blocks
                ),
                "vs_iray_k": fit.difference_statistics(
                    display.to_codes(linear) - sample.k, sample.blocks
                ),
            }
            for label, linear in renders.items()
        }
    for name in (
        "base-saturated",
        "cube-saturated--ref-match-000",
        "cube-saturated--ref-match-180",
    ):
        out["spectral"][name] = spectral.sensitivity(name, refs[name], variant, scale, work)
    return out


def repeatability_part(variant: bsdf.Variant, scale: float, work: Path) -> dict[str, Any]:
    """Item 3.3: two runs of the same job (no cache) give identical bytes."""
    pixels = tuple(range(600 * 1200 + 500, 600 * 1200 + 700))
    job = fit.Job("base-saturated", variant, pixels, spp=64, environment_scale=scale)
    first, second = fit.run_jobs([job, job], workers=2)
    digests = [
        hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest() for x in (first, second)
    ]
    return {
        "pixels": len(pixels),
        "samples": 64,
        "sha256": digests,
        "identical": digests[0] == digests[1],
    }


def run(store: OracleStore | None, work: Path, flip: bool = True) -> dict[str, Any]:
    refs = references(store)
    result: dict[str, Any] = {"display": display_part(refs)}
    fits = fits_part(refs, work)
    variant: bsdf.Variant = fits.pop("_variant")
    scale = float(fits["environment_scale"])
    result["fits"] = fits
    bump = bump_part(refs, variant, scale, work)
    result["bump"] = bump
    strength = float(bump["strength"])
    result["held_out"] = held_out_part(refs, variant, scale, strength, work)
    result["pixel_filter"] = filter_part(refs, variant, scale, work)
    result["stability"] = stability_part(refs)
    result["noise_ab"] = noise_ab(refs)
    result["noise_c"] = noise_c_part(refs, variant, scale, strength, work, flip)
    result["defects"] = defects_part(refs, variant, scale, strength, work)
    result["transport"] = transport_part(refs, variant, scale, strength, work)
    result["repeatability"] = repeatability_part(variant, scale, work)
    result["downsamples"] = list(DOWNSAMPLES)
    return result
