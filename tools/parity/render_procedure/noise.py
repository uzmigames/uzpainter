"""Iray noise terms of the admitted references (task `phase0.7_render-reference-captures`
item 2.6; `07-preview-and-render-parity.md` §4 step 1).

For every admitted reference golden (two `separate_session` recordings from different Painter
processes and one `k_times_samples` recording, `admission_problems`), the renders are read from
the private store and compared in their own encoding: Save Render's 16-bit display-referred PNG,
RGB channels, as fractions of full scale (code / 65535). Two terms:

- (a) `run_to_run`: the two session-separated references against each other (the oracle-stability
  result; zero when Iray repeats exactly);
- (b) `mc_error_at_s`: each S reference against the k*S reference (Iray's Monte-Carlo error at S;
  the k*S reference keeps 1/k of the S variance, so this term includes it).

Regions come from the fixture projected from the recorded camera (`projection.silhouette_mask`):
`interior` (object pixels), `edge` (the 2-pixel band around the outline, where the pixel filter
and sub-pixel geometry act) and `background` (the clear colour). Each fixture has one material,
so the object regions are its material regions.

Per region and pair: pixel count, differing-pixel count (any channel), max, mean, p99 and rms of
|delta| over the channel samples, mean signed delta with a standard error taken over 16 x 16
pixel blocks (noise is spatially correlated by the pixel filter, so per-sample errors would
understate it), and max, mean, p99 of |delta| after 2x, 4x and 8x box averaging over blocks that
lie wholly inside the region. Per region the estimate of one S render's noise is also given:
rms(a) / sqrt(2) and rms(b) / sqrt(1 + 1/k).

Only numbers leave this module; the renders stay in the store.
"""

from __future__ import annotations

import json
import math
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.recorder.capture import decode_png
from tools.parity.recorder.iray import K_TIMES_SAMPLES, SEPARATE_SESSION
from tools.parity.render_procedure.projection import (
    BACKGROUND,
    BAND,
    OBJECT,
    Camera,
    load_obj,
    silhouette_mask,
)
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, load_oracle

Array = npt.NDArray[np.float64]
REGIONS = {"interior": OBJECT, "edge": BAND, "background": BACKGROUND}
BLOCK = 16
DOWNSAMPLES = (2, 4, 8)
FULL_SCALE = 65535.0
GOLDEN_RECORD = "golden-record"


class NoiseError(Exception):
    """A reference golden cannot be measured (not admitted, or a record is missing)."""


def admission_problems(record: dict[str, Any], samples: int, k: int) -> list[str]:
    """Item 3.1: two session-separated recordings plus one k*S recording, each verified."""
    problems: list[str] = []
    recordings = record.get("recordings", [])
    separate = [r for r in recordings if r["condition"] == SEPARATE_SESSION]
    k_runs = [r for r in recordings if r["condition"] == K_TIMES_SAMPLES]
    if len({r["session_id"] for r in separate}) < 2:
        problems.append("fewer than two separate_session recordings from different sessions")
    if len(k_runs) != 1:
        problems.append(f"{len(k_runs)} k_times_samples recordings, expected one")
    if len({r["session_id"] for r in recordings}) != len(recordings):
        problems.append("two recordings share a Painter session")
    for recording in recordings:
        render = reference_output(recording)
        wanted = k * samples if recording["condition"] == K_TIMES_SAMPLES else samples
        if render.get("samples") != wanted:
            problems.append(
                f"{recording['recording_id']}: {render.get('samples')} samples, expected {wanted}"
            )
        if render.get("current_frame_verified") is not True:
            problems.append(f"{recording['recording_id']}: not current-frame verified")
        convergence = render.get("convergence", {})
        if convergence.get("status") != "Done" or convergence.get("iterations") != wanted:
            problems.append(f"{recording['recording_id']}: not converged on the sample count")
    return problems


def reference_output(recording: dict[str, Any]) -> dict[str, Any]:
    (render,) = [o for o in recording["outputs"] if o["kind"] == "iray_reference"]
    return dict(render)


def region_masks(
    manifest: dict[str, Any], key: dict[str, Any], size: tuple[int, int]
) -> dict[str, npt.NDArray[np.bool_]]:
    """The expected-silhouette regions of the fixture seen from the recorded camera."""
    (mesh_input,) = [i for i in manifest["inputs"] if i["kind"] == "mesh"]
    mesh = load_obj(REPO_ROOT / mesh_input["path"])
    camera = Camera.from_render_state(key["render_state"])
    if any(angle != 0.0 for angle in camera.rotation):
        raise NoiseError("only unrotated cameras are measured (no Euler order is involved)")
    width, height = size
    rows = silhouette_mask(mesh, camera, width, height)
    codes = np.frombuffer(b"".join(rows), dtype=np.uint8).reshape(height, width)
    return {name: codes == code for name, code in REGIONS.items()}


def rgb(png: bytes) -> Array:
    """RGB of a 16-bit PNG as fractions of full scale, shape (height, width, 3)."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "render.png"
        path.write_bytes(png)
        image = decode_png(path)
    if image.channels < 3:
        raise NoiseError("the render is not RGB")
    pixels = np.asarray(image.pixels, dtype=np.float64).reshape(image.height, image.width, -1)
    return pixels[:, :, :3] / FULL_SCALE


def finite(value: float) -> float | None:
    return None if math.isnan(value) else float(value)


def block_means(delta: Array, mask: npt.NDArray[np.bool_], block: int) -> list[float]:
    height, width = mask.shape
    means: list[float] = []
    for y in range(0, height - height % block, block):
        for x in range(0, width - width % block, block):
            inside = mask[y : y + block, x : x + block]
            if inside.any():
                means.append(float(delta[y : y + block, x : x + block][inside].mean()))
    return means


def downsampled(delta: Array, mask: npt.NDArray[np.bool_], factor: int) -> dict[str, Any]:
    """|delta| box-averaged over factor x factor blocks wholly inside the region."""
    height, width = mask.shape
    h, w = height - height % factor, width - width % factor
    shape = (h // factor, factor, w // factor, factor)
    inside = mask[:h, :w].reshape(shape).all(axis=(1, 3))
    averaged = delta[:h, :w].reshape(*shape, 3).mean(axis=(1, 3))[inside]
    if averaged.size == 0:
        return {"blocks": 0, "max_abs": None, "mean_abs": None, "p99_abs": None}
    magnitude = np.abs(averaged)
    return {
        "blocks": int(inside.sum()),
        "max_abs": float(magnitude.max()),
        "mean_abs": float(magnitude.mean()),
        "p99_abs": float(np.percentile(magnitude, 99)),
    }


def region_statistics(delta: Array, mask: npt.NDArray[np.bool_]) -> dict[str, Any]:
    samples = delta[mask]
    pixels = int(mask.sum())
    if pixels == 0:
        return {"pixels": 0}
    magnitude = np.abs(samples)
    changed: npt.NDArray[np.bool_] = np.any(delta != 0.0, axis=2)
    means = block_means(delta, mask, BLOCK)
    error = float(np.std(means, ddof=1) / math.sqrt(len(means))) if len(means) > 1 else float("nan")
    return {
        "pixels": pixels,
        "differing_pixels": int(changed[mask].sum()),
        "max_abs": float(magnitude.max()),
        "mean_abs": float(magnitude.mean()),
        "p99_abs": float(np.percentile(magnitude, 99)),
        "rms": float(np.sqrt(np.mean(samples * samples))),
        "mean_signed": float(samples.mean()),
        "mean_signed_se": finite(error),
        "blocks": len(means),
        "downsampled": {str(f): downsampled(delta, mask, f) for f in DOWNSAMPLES},
    }


def pair_statistics(a: Array, b: Array, masks: dict[str, npt.NDArray[np.bool_]]) -> dict[str, Any]:
    delta = a - b
    return {name: region_statistics(delta, mask) for name, mask in masks.items()}


def noise_terms(
    images: dict[str, Array],
    conditions: dict[str, str],
    masks: dict[str, npt.NDArray[np.bool_]],
    k: int,
) -> dict[str, Any]:
    """Terms (a) and (b) from renders keyed by recording id."""
    separate = sorted(r for r, c in conditions.items() if c == SEPARATE_SESSION)
    (k_run,) = [r for r, c in conditions.items() if c == K_TIMES_SAMPLES]
    first, second = separate[:2]
    run_to_run = pair_statistics(images[first], images[second], masks)
    mc = {r: pair_statistics(images[r], images[k_run], masks) for r in (first, second)}
    sigma: dict[str, Any] = {}
    for region in masks:
        a_rms = run_to_run[region].get("rms")
        b_rms = [mc[r][region].get("rms") for r in (first, second)]
        sigma[region] = {
            "from_run_to_run": None if a_rms is None else a_rms / math.sqrt(2.0),
            "from_mc_error": None
            if None in b_rms
            else float(np.sqrt(np.mean(np.square(b_rms)))) / math.sqrt(1.0 + 1.0 / k),
        }
    return {
        "pairs": {
            "run_to_run": [first, second],
            "mc_error_at_s": [[first, k_run], [second, k_run]],
        },
        "run_to_run": run_to_run,
        "mc_error_at_s": mc,
        "s_render_sigma": sigma,
        "bit_identical_run_to_run": all(
            run_to_run[r].get("differing_pixels", 0) == 0 for r in masks
        ),
    }


def private_record(store: OracleStore | None, manifest: dict[str, Any]) -> dict[str, Any]:
    refs = {r["record_id"]: r for r in manifest["private_records"]}
    if GOLDEN_RECORD not in refs:
        raise NoiseError(f"{manifest['golden_id']}: not admitted (no private records)")
    data = load_oracle(store, refs[GOLDEN_RECORD])
    if data is None:
        raise NoiseError(f"{manifest['golden_id']}: the golden record is not in the store")
    record: dict[str, Any] = json.loads(data.decode("utf-8"))
    return record


def measure(
    store: OracleStore | None, manifest: dict[str, Any], samples: int, k: int
) -> dict[str, Any]:
    record = private_record(store, manifest)
    problems = admission_problems(record, samples, k)
    if problems:
        raise NoiseError(f"{manifest['golden_id']}: not admissible: {'; '.join(problems)}")
    by_hash = {r["sha256"]: r for r in manifest["private_records"]}
    images: dict[str, Array] = {}
    conditions: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for recording in record["recordings"]:
        render = reference_output(recording)
        digest = render["blob"]["sha256"]
        data = load_oracle(store, by_hash[digest]) if digest in by_hash else None
        if data is None:
            raise NoiseError(f"{recording['recording_id']}: render {digest} is not in the store")
        images[recording["recording_id"]] = rgb(data)
        conditions[recording["recording_id"]] = recording["condition"]
        hashes[recording["recording_id"]] = digest
    size = next(iter(images.values())).shape[1::-1]
    masks = region_masks(manifest, record["key"], (int(size[0]), int(size[1])))
    return {
        "golden_id": manifest["golden_id"],
        "renders": hashes,
        "conditions": conditions,
        "golden_record_sha256": next(
            r["sha256"] for r in manifest["private_records"] if r["record_id"] == GOLDEN_RECORD
        ),
        **noise_terms(images, conditions, masks, k),
    }


def summary_rows(results: Iterable[dict[str, Any]]) -> list[str]:
    """Markdown rows: per fixture and region, (a) and (b) in 1e-4 of full scale."""

    def scaled(value: float | None) -> str:
        return "-" if value is None else f"{value * 1e4:.2f}"

    rows = [
        "| Golden | Region | Pixels | (a) differing | (a) mean abs | (a) p99 abs | (a) max abs "
        "| (a) mean signed ± se | (b) mean abs | (b) p99 abs | (b) mean signed ± se | sigma S |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        name = result["golden_id"].rsplit("/", 1)[-1]
        first, second = result["pairs"]["run_to_run"]
        for region in REGIONS:
            a = result["run_to_run"][region]
            if not a.get("pixels"):
                continue
            b = [result["mc_error_at_s"][r][region] for r in (first, second)]
            b_mean = sum(x["mean_abs"] for x in b) / 2
            b_p99 = max(x["p99_abs"] for x in b)
            b_signed = " / ".join(
                f"{scaled(x['mean_signed'])} ± {scaled(x['mean_signed_se'])}" for x in b
            )
            sigma = result["s_render_sigma"][region]["from_run_to_run"]
            rows.append(
                f"| `{name}` | {region} | {a['pixels']} | {a['differing_pixels']} | "
                f"{scaled(a['mean_abs'])} | {scaled(a['p99_abs'])} | {scaled(a['max_abs'])} | "
                f"{scaled(a['mean_signed'])} ± {scaled(a['mean_signed_se'])} | {scaled(b_mean)} | "
                f"{scaled(b_p99)} | {b_signed} | {scaled(sigma)} |"
            )
    return rows
