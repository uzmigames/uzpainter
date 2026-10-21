"""CPU tests of the `painter_iray` path tracer's sampling foundations (rulebook task
phase3.4_path-tracer-transport items 2.4, 2.6 (CPU distribution and density), 2.8, 3.2
(sampling density part) and 3.3): `uzp-pathtracer-tests.exe` (`tests/render/pathtracer_test.cpp`,
`src/render/pathtracer/`), built once per session with `zig build pathtracer-tests`. No GPU.

The native cases check hand-derived values, exact stratification and documented bounds; the
comparison with the Phase 0 render prototype (`tools/parity/render_fits/sampler.py`, a separate
implementation of Burley 2020) checks that both give the same sample bits.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from tools.parity.render_fits import sampler

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def pathtracer_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-pathtracer-tests.exe` of a fresh `zig build pathtracer-tests` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-pathtracer-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("pathtracer-tests")
    build = subprocess.run(
        [zig, "build", "pathtracer-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-pathtracer-tests.exe"


def run_case(exe: Path, case: str) -> tuple[set[str], str]:
    """Run one case; return its passed checks and its output. Fails on any failed check."""
    proc = subprocess.run(
        [str(exe), case],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    output = proc.stdout + proc.stderr
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, output
    passed = {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}
    return passed, output


def test_sobol_owen_sampler(pathtracer_tests: Path) -> None:
    """2.4, 3.3: direction numbers and first points as derived by hand, nested scrambling,
    stratification per dimension and of (0, 2) pairs, the seed reproduces and changes the
    sequence."""
    passed, _ = run_case(pathtracer_tests, "sobol")
    for check in (
        "Sobol direction numbers match the hand-derived m_i of components 0-3",
        "unscrambled Sobol points 0-7 equal the hand-derived eighths",
        "Owen scrambling keeps shared top bits and permutes aligned blocks",
        "the same seed and pixel reproduce every value",
        "another render seed changes the sequence",
        "another pixel changes the sequence",
        "another 4D set changes the sequence",
    ):
        assert check in passed
    assert any(c.startswith("every dimension 0-15 is stratified") for c in passed)
    assert any(c.startswith("components 0 and 1 of sets 0-3 form a (0,2)-sequence") for c in passed)


def test_sobol_matches_the_phase0_prototype(pathtracer_tests: Path) -> None:
    """3.3: the native sampler and the prototype (an implementation written separately, in
    numpy) give the same pixel seeds and sample bits on a grid of 3 seeds x 5 pixels x 66
    sample indices x 12 dimensions."""
    _, output = run_case(pathtracer_tests, "sobol-dump")
    line = next(x for x in output.splitlines() if x.startswith("VALUES "))
    dump = json.loads(line[len("VALUES ") :])
    pixels = np.asarray(dump["pixels"], dtype=np.int64)
    native_bits = np.asarray(dump["bits"], dtype=np.uint64).reshape(
        len(dump["seeds"]), len(pixels), len(dump["indices"]), dump["dimensions"]
    )
    native_seeds = np.asarray(dump["pixel_seeds"], dtype=np.uint64).reshape(
        len(dump["seeds"]), len(pixels)
    )
    for s, seed in enumerate(dump["seeds"]):
        seeds = sampler.pixel_seeds(pixels, seed)
        assert np.array_equal(seeds.astype(np.uint64), native_seeds[s])
        for i, index in enumerate(dump["indices"]):
            for dim_set in range(dump["dimensions"] // 4):
                values = sampler.samples(index, seeds, dim_set, 4)
                bits = np.round(values * 4294967296.0).astype(np.uint64)
                assert np.array_equal(bits, native_bits[s, :, i, dim_set * 4 : dim_set * 4 + 4]), (
                    seed,
                    index,
                    dim_set,
                )


def test_lambert_lobe(pathtracer_tests: Path) -> None:
    """2.8: f = R / pi in the hemisphere of wo, cosine-weighted sampling with consistent Pdf and
    Evaluate, f cos / pdf = R per sample, the density integrates to 1."""
    passed, _ = run_case(pathtracer_tests, "lambert")
    for check in (
        "Evaluate is albedo / pi in the hemisphere of wo",
        "Evaluate and Pdf are 0 across the surface",
        "Pdf is cos(theta_i) / pi",
        "Sample returns unit wi in the hemisphere of wo with Pdf and Evaluate",
        "f cos(theta_i) / pdf = albedo for every sample (white furnace)",
        "sampled directions are cosine-distributed (chi-square below 30.58)",
        "Pdf integrates to 1 over the hemisphere",
    ):
        assert check in passed


def test_environment_distribution(pathtracer_tests: Path) -> None:
    """2.6 (CPU distribution and density), 3.2 (density part): the iray.json orientation,
    texel probabilities, Pdf(direction) equal to the sampled density, counts against N p, and
    the density integrates to 1 over the sphere."""
    passed, _ = run_case(pathtracer_tests, "environment")
    for check in (
        "texel coordinates map to the directions of the iray.json environment mapping",
        "an empty, black or non-finite map is refused",
        "texel probabilities of a 2 x 2 map are L / 12",
        "a single lit texel takes every sample with pdf_uv = W H",
        "Pdf(direction) equals the density of the sample that produced it",
        "row counts are within 2 of N p",
        "texel counts are within 3 sigma + 1 of N p",
        "Pdf integrates to 1 over the sphere",
    ):
        assert check in passed


def test_bright_patch_irradiance_estimators(pathtracer_tests: Path) -> None:
    """3.2 (CPU density part): environment sampling, Lambert sampling and their power-heuristic
    combination estimate the analytic reflected radiance of a single bright patch within 4
    standard errors."""
    passed, _ = run_case(pathtracer_tests, "env-mis")
    for name in ("environment sampling", "Lambert sampling", "power-heuristic MIS"):
        assert f"{name} estimate of Lo is within 4 standard errors of the analytic value" in passed
