"""Measurements of the render fits (task `phase0.8_render-reference-fits` items 2.4-2.7, 3.2 and
3.4; decisions 050-052): run-to-run structure, statistics, spectral sensitivity, the public
fits file and the report. Synthetic data only; the oracle runs stay on the owner's machine."""

from __future__ import annotations

import json
import math
import re

import numpy as np
import pytest

from tools.parity.render_fits import (
    display,
    fit,
    pipeline,
    report,
    semantics,
    spectral,
    stability,
)
from tools.parity.render_fits.fixtures import (
    QUALIFICATION,
    QUALIFICATION_EXPORT_CODE,
    by_name,
    qualification_base,
    srgb_to_linear,
    unorm8,
)
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.sources.check import INDEX_PATH
from tools.sources.index import parse_index

RNG = np.random.default_rng(11)


def smooth_image(size: int = 64) -> np.ndarray:
    y, x = np.mgrid[0:size, 0:size] / size
    base = 30000.0 + 2000.0 * x + 1000.0 * y
    return np.repeat(base[..., None], 3, axis=2)


# --- run-to-run structure (item 2.7) ----------------------------------------------------------


def test_one_binary16_step_is_recognised() -> None:
    lattice = display.lattice()
    a = np.full((8, 8, 3), float(lattice[9000]))
    b = a.copy()
    b[2, 3, 1] = lattice[9001]
    b[5, 5, 0] = lattice[9004]
    steps = stability.half_steps(a, b, np.ones((8, 8), dtype=bool))
    assert steps["differing_samples"] == 2
    assert steps["steps"]["1"] == 1
    assert steps["more_than_3"] == 1
    assert steps["max_steps"] == 4


def test_highpass_sigma_recovers_white_noise() -> None:
    noise = RNG.normal(0.0, 150.0, (128, 128, 3))
    image = smooth_image(128) + noise
    sigma = stability.highpass_sigma(image, np.ones((128, 128), dtype=bool))
    assert sigma == pytest.approx(150.0, rel=0.03)


def test_sequence_test_tells_nested_from_independent() -> None:
    size = 128
    clean = smooth_image(size)
    samples = RNG.normal(0.0, 600.0, (8, size, size, 3))
    s = clean + samples[:2].mean(axis=0)
    nested_k = clean + samples.mean(axis=0)
    independent_k = clean + RNG.normal(0.0, 600.0, (8, size, size, 3)).mean(axis=0)
    mask = np.ones((size, size), dtype=bool)
    nested = stability.sequence_test(s, nested_k, mask)
    independent = stability.sequence_test(s, independent_k, mask)
    assert abs(nested["rms_s_minus_k"] - nested["nested_prediction"]) < abs(
        nested["rms_s_minus_k"] - nested["independent_prediction"]
    )
    assert abs(independent["rms_s_minus_k"] - independent["independent_prediction"]) < abs(
        independent["rms_s_minus_k"] - independent["nested_prediction"]
    )
    assert nested["variance_ratio"] == pytest.approx(0.25, abs=0.03)


def test_jensen_bias_of_the_concave_encoding_is_negative_and_matches_simulation() -> None:
    sigma = 0.003  # linear, about the S renders' noise at 18% grey
    nodes, weights = np.polynomial.hermite_e.hermegauss(60)
    expected = np.sum(weights * display.encode(0.18 + sigma * nodes)) / weights.sum()
    observed = (expected - display.encode(np.array(0.18))) * display.FULL_SCALE
    k = np.full((1, 1, 3), np.round(display.encode(np.array(0.18)) * display.FULL_SCALE))
    slope = (1.055 / 2.4) * 0.18 ** (-7.0 / 12.0)
    sigma_codes = sigma * slope * display.FULL_SCALE
    predicted = stability.jensen_bias(k, sigma_codes, 0.0, np.ones((1, 1), dtype=bool))
    assert predicted < 0
    assert predicted == pytest.approx(observed, rel=0.05)


# --- statistics (items 2.4, 2.7) --------------------------------------------------------------


def test_difference_statistics_on_a_known_offset() -> None:
    delta = np.full((256, 3), 5.0)
    blocks = np.repeat(np.arange(16), 16)
    stats = fit.difference_statistics(delta, blocks)
    assert stats["mean_signed"] == 5.0
    assert stats["mean_signed_se"] == 0.0
    assert stats["differing"] == 256
    assert stats["differing_samples"] == 768
    assert stats["max_abs"] == stats["p99_abs"] == 5.0


def test_chessboard_halves_split_blocks_evenly() -> None:
    mask = np.zeros((1200, 1200), dtype=bool)
    mask[300:900, 300:900] = True
    images = (np.zeros((1200, 1200, 3)),) * 3
    sample = fit.sample_pixels("x", mask, images)
    assert 0.45 < sample.fit.mean() < 0.55
    ys, xs = sample.pixels // 1200, sample.pixels % 1200
    assert np.all(((ys // 16 + xs // 16) % 2 == 0) == sample.fit)


def test_golden_section_finds_a_minimum() -> None:
    assert fit.golden_section(lambda s: (s - 1.0137) ** 2, 0.8, 1.25) == pytest.approx(
        1.0137, abs=1e-6
    )


def test_job_keys_follow_every_setting() -> None:
    from tools.parity.render_fits import bsdf

    a = fit.Job("neutral-grey-diffuse", bsdf.Variant(), (1, 2, 3))
    assert fit.job_key(a) == fit.job_key(fit.Job("neutral-grey-diffuse", bsdf.Variant(), (1, 2, 3)))
    assert fit.job_key(a) != fit.job_key(
        fit.Job("neutral-grey-diffuse", bsdf.Variant(), (1, 2, 3), seed=2)
    )


# --- spectral sensitivity (item 2.5) ----------------------------------------------------------


def test_flat_spectrum_is_white_and_upsampling_round_trips() -> None:
    assert np.allclose(spectral.RESPONSE.sum(axis=1), 1.0)
    colours = np.array([[0.604, 0.033, 0.010], [0.5, 0.5, 0.5], [0.2, 0.7, 0.4]])
    spectra = spectral.upsample(colours)
    assert np.allclose(spectra @ spectral.RESPONSE.T, colours, atol=1e-6)
    assert np.all((spectra > 0) & (spectra < 1))


def test_white_environment_leaves_the_diffuse_product_unchanged() -> None:
    texels = np.full((4, 8, 3), 3.0)
    effective, round_trip = spectral.spectral_environment(texels, (0.6, 0.03, 0.01))
    assert round_trip < 1e-9
    assert np.allclose(effective, texels, rtol=1e-3)


# --- public files (items 2.4, 2.7, 3.4) ----------------------------------------------------------


def test_iray_semantics_validate_and_cite_approved_sources() -> None:
    document = json.loads(semantics.PATH.read_text(encoding="utf-8"))
    assert validation_errors(document, Schema.SEMANTICS) == []
    index = parse_index((REPO_ROOT / INDEX_PATH).read_text(encoding="utf-8"))
    approved = {e.entry_id for e in index.entries if e.status == "approved"}
    cited = {s["source_id"] for e in document["entries"] for s in e["public_sources"]}
    assert cited <= approved, cited - approved
    assert all(e["status"] == "calibrated" for e in document["entries"])
    assert any(e["residuals"] for e in document["entries"])


def test_noise_floor_report_has_every_generated_block() -> None:
    text = report.REPORT.read_text(encoding="utf-8")
    for name in (
        "display",
        "half-steps",
        "faces",
        "sequence",
        "noise-floor",
        "flip",
        "fits",
        "ranking",
        "filter",
        "transport",
        "defects",
        "repeatability",
        "probes",
    ):
        body = re.search(rf"<!-- {name}:begin -->\n(.*?)<!-- {name}:end -->", text, re.DOTALL)
        assert body is not None and body.group(1).strip(), name


def test_report_formats_fractions_as_codes() -> None:
    assert report.c(1e-4, 2) == "6.55"
    assert report.c(math.nan) == "-"
    assert report.c(None) == "-"


def test_noise_floor_covers_every_admitted_analytic_fixture() -> None:
    """Item 3.2 of phase0.9 (decisions 063, 068): the 22 fixtures and the qualification sphere
    each have (a), (b) and the prototype's (c) in the noise-floor table."""
    text = report.REPORT.read_text(encoding="utf-8")
    body = re.search(r"<!-- noise-floor:begin -->\n(.*?)<!-- noise-floor:end -->", text, re.DOTALL)
    assert body is not None
    rows = [line.split(" | ") for line in body.group(1).splitlines()[2:]]
    covered = {row[0].strip("| `") for row in rows if row[1] == "interior" and row[8] != "-"}
    assert covered == {*fit.FIT_GOLDENS, *fit.HELD_OUT_GOLDENS, QUALIFICATION.name}


def test_qualification_scene_takes_the_read_back_material() -> None:
    """Decision 068: BaseColor is the export's linear value (off the sRGB8 lattice), metalness
    L8 code 0, roughness L8 code 76; the fixture is found by name like the others."""
    assert by_name(QUALIFICATION.name) is QUALIFICATION
    assert QUALIFICATION_EXPORT_CODE % 257 != 0
    assert qualification_base() == (srgb_to_linear(QUALIFICATION_EXPORT_CODE / 65535.0),) * 3
    assert abs(qualification_base()[0] - 0.8) < 2e-5
    assert (unorm8(QUALIFICATION.metalness), unorm8(QUALIFICATION.roughness)) == (0.0, 76 / 255)
    assert QUALIFICATION.perturbation is None
    assert pipeline.SCENE_OVERRIDES[QUALIFICATION.name] == {"base_override": qualification_base()}


def test_noise_rows_add_the_qualification_sphere_once_measured() -> None:
    assert report.noise_goldens({"noise_c": {}}) == fit.FIT_GOLDENS + fit.HELD_OUT_GOLDENS
    measured = report.noise_goldens({"noise_c": {QUALIFICATION.name: {}}})
    assert measured[-1] == QUALIFICATION.name and len(measured) == 23
