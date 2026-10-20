"""Tests of phase3.2_proc-filter-families (`src/procedural/filters.h`, decision 328): the filter
families' certified editable domains, declared in the shipped asset library before any
calibration (item 2.6), the Sharpen and grayscale kernels (item 2.2), the Levels filter mapped
onto the native levels effect (item 2.3), the effect order of a filter effect (test 3.2), the
resolution-override restriction of a filter effect's source (item 2.4, test 3.3) and the refusals
just outside each declared domain (test 3.5).

The native cases run `uzp-proc-filter-tests.exe` (`tests/procedural/filters_test.cpp`).
`families`, `levels`, `effect-order`, `resolution-override` and `domain` run on the CPU, `kernels`
needs `dxcompiler.dll` (installed beside the executable), and `gpu` needs a DX12 hardware adapter:
it skips under `UZP_NO_GPU=1` or when the executable reports none (exit code 77). Only one GPU
run may be on the machine at a time.

None of these assets is certified: each record's parity status is `unavailable`, no alias of the
library names it (decision 324), and no case here compares against a Painter output.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.parity.proc_cert.batch import Domain

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED = REPO_ROOT / "assets/procedural"
FILTERS = {
    "uzasset://filter/sharpen@1": "records/filter.sharpen@1.json",
    "uzasset://filter/grayscale@1": "records/filter.grayscale@1.json",
    "uzasset://filter/levels@1": "records/filter.levels@1.json",
}


EXIT_SKIP = 77
NO_GPU = os.environ.get("UZP_NO_GPU") == "1"


@pytest.fixture(scope="session")
def filter_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-proc-filter-tests.exe` of a fresh `zig build proc-filter-tests` install."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-proc-filter-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("proc-filter-tests")
    build = subprocess.run(
        [zig, "build", "proc-filter-tests", "-j2", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-proc-filter-tests.exe"


def run_case(exe: Path, case: str, work: Path) -> set[str]:
    """Run one case; return its passed checks. Fails on any failed check."""
    if case == "gpu" and NO_GPU:
        pytest.skip("UZP_NO_GPU=1: the `gpu` case needs a DX12 hardware adapter")
    proc = subprocess.run(
        [str(exe), case, str(work), str(SHIPPED)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode == EXIT_SKIP:
        pytest.skip(f"no DX12 adapter for `{case}`: {output.strip()}")
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, output
    return {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}


def record(path: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((SHIPPED / path).read_text(encoding="utf-8"))
    return document


@pytest.mark.parametrize("asset", sorted(FILTERS))
def test_filter_domain_is_declared_before_calibration(asset: str) -> None:
    """2.6: the domain parses as the certification harness reads it; nothing is certified."""
    document = record(FILTERS[asset])
    assert document["asset"] == asset
    assert document["usage"] == "FILTER"
    domain = Domain(document["domain"])
    # Filters take layer content instead of seeds: one listed seed.
    assert domain.single_seed and domain.seeds == [0]
    # The content input is the layer content at the filter's position (05 §3).
    assert set(domain.inputs) == {"content"}
    content, output = domain.inputs["content"], domain.output
    assert content["resolutions"] == output["resolutions"] == [1024, 2048, 4096]
    assert content["channels"] == output["channels"]
    assert content["colour_spaces"] == output["colour_spaces"]
    assert output["formats"] == ["f32"]
    assert domain.ranges, "every family has a ranged parameter for the boundary sets"
    assert set(document["defaults"]) == set(domain.ranges) | set(domain.sets)
    assert domain.params_refusal(document["defaults"]) is None
    assert document["parity"]["status"] == "unavailable"
    assert document["corpus"] == {}


def test_no_alias_names_a_filter_family() -> None:
    """Decision 324: only an `exact` asset gets an alias; the filters are not certified."""
    library = json.loads((SHIPPED / "library.json").read_text(encoding="utf-8"))
    assert set(FILTERS.values()) <= set(library["records"])
    aliases = json.loads((SHIPPED / library["aliases"]).read_text(encoding="utf-8"))
    assert aliases["aliases"] == []


def test_shipped_library_loads_natively(procedural_tests: Path, tmp_path: Path) -> None:
    """The native loader (`AssetLibrary::Load`) admits every shipped record and no alias."""
    proc = subprocess.run(
        [str(procedural_tests), "library-load", str(tmp_path), str(SHIPPED)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    library = json.loads((SHIPPED / "library.json").read_text(encoding="utf-8"))
    assert proc.stdout.strip() == f"LOADED {len(library['records'])} 0", proc.stdout


def test_sharpen_and_grayscale_follow_their_published_formulas(
    filter_tests: Path, tmp_path: Path
) -> None:
    """2.2 (CPU): the Laplacian sharpening and the weighted grey sum, the joint rule, tiles, and
    the seam's refusal of the uncertified families."""
    passed = run_case(filter_tests, "families", tmp_path)
    assert len(passed) == 16, sorted(passed)
    for check in (
        "Sharpen equals f - amount x Laplacian(f) with wrap-around, amount 1.000000",
        "grayscale conversion equals the BT.709 luma sum on every channel at the defaults",
        "a content at another resolution than the output is refused, not resampled",
        "the seam refuses the uncertified family inside its domain (family not certified)",
    ):
        assert check in passed


def test_filter_kernels_compile(filter_tests: Path, tmp_path: Path) -> None:
    """2.2: each family's kernel compiles to DXIL and SPIR-V through the render core."""
    passed = run_case(filter_tests, "kernels", tmp_path)
    assert sum(check.startswith("compiles: ") for check in passed) == 4


def test_filter_kernels_equal_the_cpu_reference_on_dx12(filter_tests: Path, tmp_path: Path) -> None:
    """2.2 (DX12): each kernel equals its CPU reference bit for bit, whole and by tile."""
    passed = run_case(filter_tests, "gpu", tmp_path)
    assert sum(check.startswith("DX12 equals the CPU reference") for check in passed) == 5


def test_levels_filter_maps_onto_the_native_levels_effect(
    filter_tests: Path, tmp_path: Path
) -> None:
    """2.3: the parameters reach one native levels component; the lane is the native effect's
    arithmetic (its Tier 0 semantics); refusals evaluate nothing."""
    passed = run_case(filter_tests, "levels", tmp_path)
    assert len(passed) == 14, sorted(passed)
    for check in (
        "the Levels filter at its defaults is the identity, bit for bit",
        "the Levels filter equals the native levels effect's arithmetic on every texel, clamp 1",
        "the seam serves no Levels filter (no snapshot and no certified family)",
    ):
        assert check in passed


def test_resolution_override_on_a_filter_source_raises(filter_tests: Path, tmp_path: Path) -> None:
    """2.4 / 3.3: `SourceSubstance.resolution` raises ValueError for a source used by a
    FilterEffectNode (python-doc): the edit commits nothing; a generator keeps its override."""
    passed = run_case(filter_tests, "resolution-override", tmp_path)
    assert len(passed) == 8, sorted(passed)
    for check in (
        "a resolution override on a filter effect's source raises ValueError",
        "the refused edit commits nothing: the revision and the project are unchanged",
        "a generator effect's source accepts a resolution override",
        "SetEffectProcedural with an override on a filter effect raises ValueError and commits "
        "nothing",
    ):
        assert check in passed


def test_filter_effect_reads_the_content_below_and_blends_with_its_own_mode(
    filter_tests: Path, tmp_path: Path
) -> None:
    """3.2: a filter computes from the content produced by the effects below it and blends with
    its own mode and opacity (the CPU candidate lane; the evaluator still refuses filter
    effects until a family is certified)."""
    passed = run_case(filter_tests, "effect-order", tmp_path)
    assert len(passed) == 8, sorted(passed)
    for check in (
        "a grayscale filter above a fill effect computes from the content after the fill and "
        "blends with its own Normal mode at opacity 0.75",
        "the same filter blends with its own Multiply mode at opacity 1",
        "the filter below the fill gives another result than the filter above it",
        "a content raster other than the one the request names is refused",
    ):
        assert check in passed


def test_requests_just_outside_the_domain_are_refused_before_mutation(
    filter_tests: Path, tmp_path: Path
) -> None:
    """3.5: a parameter, a seed, a mesh-map input, a content input and a resolution just outside
    the declared domain raise `UnsupportedProcedural{reason: "outside certified domain"}` before
    mutation, naming the requested value: nothing is clamped or substituted."""
    passed = run_case(filter_tests, "domain", tmp_path)
    outside = [c for c in passed if c.startswith("outside the domain, refused before mutation")]
    assert len(outside) == 11, sorted(passed)
    assert sum(c.startswith("the candidate lane evaluates nothing: ") for c in passed) == 11
    assert sum(c.startswith("the Levels filter refuses outside its domain: ") for c in passed) == 5
    for check in (
        "outside the domain, refused before mutation with nothing clamped: a parameter one ulp "
        "above its range",
        "outside the domain, refused before mutation with nothing clamped: a seed outside the "
        "listed seed",
        "outside the domain, refused before mutation with nothing clamped: a mesh-map input the "
        "domain does not declare",
        "outside the domain, refused before mutation with nothing clamped: an output resolution "
        "of 8192",
        "inside the domain the uncertified Sharpen is refused before mutation (family not "
        "certified)",
    ):
        assert check in passed
