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

The `@1` records stay `unavailable`. `filter/sharpen@2` is `calibrated` and served only inside the
owner's exception EXC-015 (decision 430). Its record names the exception, and no alias names it
(an alias names an `exact` asset only). The `sharpen2` case checks the certified model and its
refusals. `test_sharpen_v2_passes_under_exc015_on_its_batch` compares its native CPU lane with the
private goldens of its batch through the verdict (skipped without the store).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.parity.proc_cert.batch import Domain, load_batch

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED = REPO_ROOT / "assets/procedural"
FILTERS = {
    "uzasset://filter/sharpen@1": "records/filter.sharpen@1.json",
    "uzasset://filter/grayscale@1": "records/filter.grayscale@1.json",
    "uzasset://filter/levels@1": "records/filter.levels@1.json",
}
SHARPEN2 = "uzasset://filter/sharpen@2"
SHARPEN2_RECORD = "records/filter.sharpen@2.json"
SHARPEN2_BATCH = REPO_ROOT / "parity/manifests/phase3/proc-cert/filter__sharpen@2/batch.json"
SHARPEN2_REPORT = "parity/reports/phase3/proc-cert/filter__sharpen@2/727f63f70a79abab.json"


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
    """Decision 324: only an `exact` asset gets an alias, and no filter is exact. Decision 430
    keeps the calibrated `filter/sharpen@2` without one."""
    library = json.loads((SHIPPED / "library.json").read_text(encoding="utf-8"))
    assert {*FILTERS.values(), SHARPEN2_RECORD} <= set(library["records"])
    aliases = json.loads((SHIPPED / library["aliases"]).read_text(encoding="utf-8"))
    assert not [a for a in aliases["aliases"] if a["asset"].startswith("uzasset://filter/")]
    assert not [a for a in aliases["aliases"] if a["usage"] == "FILTER"]


def test_sharpen_v2_record_is_calibrated_under_exc015() -> None:
    """Decision 430: the record is the batch's domain with `intensity` narrowed to EXC-015's
    tested set without 0.63 and 2.71, whose residuals are off the exact midpoints (decision 430
    amendment). It is `calibrated` with the report's pooled residual and names EXC-015, whose
    filter domain names this asset."""
    from tools.parity.schemas import REGISTER_PATH, load_json
    from tools.parity.verdict import in_force

    document = record(SHARPEN2_RECORD)
    assert (document["asset"], document["usage"]) == (SHARPEN2, "FILTER")
    batch = json.loads(SHARPEN2_BATCH.read_text(encoding="utf-8"))
    register = load_json(REGISTER_PATH)["entries"]
    (entry,) = [e for e in in_force(register) if e["exception_id"] == "EXC-015"]
    spec = entry["domain"]["procedural_filter"]
    assert spec["asset"] == SHARPEN2
    expected = json.loads(json.dumps(batch["domain"]))
    served = [v for v in spec["values"] if v not in (0.63, 2.71)]
    assert len(served) == 6
    expected["parameters"] = {"intensity": {"set": served}}
    assert document["domain"] == expected
    domain = Domain(document["domain"])
    assert domain.params_refusal(document["defaults"]) is None
    for value in served:
        assert domain.params_refusal({"intensity": value}) is None
    for value in (0.63, 2.71, 0.3, 0.5, 4.5):
        assert domain.params_refusal({"intensity": value}) is not None
    assert document["corpus"] == {
        "calibration": batch["calibration"]["corpus_id"],
        "held_out": batch["held_out"]["corpus_id"],
    }
    report = json.loads((REPO_ROOT / SHARPEN2_REPORT).read_text(encoding="utf-8"))
    cases = [c for s in ("calibration", "held_out") for c in report["sets"][s]["cases"]]
    pooled = {
        "unit": "ulp_f32",
        "max": max(c["residual"]["max_abs_diff"] for c in cases),
        "sum": sum(c["residual"]["sum_abs_diff"] for c in cases),
        "count": sum(c["residual"]["values"] for c in cases),
        "p99": report["parity_status"]["residuals"]["ulp_f32"]["p99_abs_diff"],
    }
    assert report["parity_status"]["kind"] == "calibrated"
    assert document["parity"] == {
        "status": "calibrated",
        "residuals": [pooled],
        "exception": "EXC-015",
        "report": SHARPEN2_REPORT,
    }


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
    aliases = json.loads((SHIPPED / library["aliases"]).read_text(encoding="utf-8"))["aliases"]
    assert proc.stdout.strip() == f"LOADED {len(library['records'])} {len(aliases)}", proc.stdout


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
    assert sum(check.startswith("compiles: ") for check in passed) == 6


def test_filter_kernels_equal_the_cpu_reference_on_dx12(filter_tests: Path, tmp_path: Path) -> None:
    """2.2 (DX12): each kernel equals its CPU reference bit for bit, whole and by tile."""
    passed = run_case(filter_tests, "gpu", tmp_path)
    assert sum(check.startswith("DX12 equals the CPU reference") for check in passed) == 8


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


def test_sharpen_v2_follows_the_certified_model(filter_tests: Path, tmp_path: Path) -> None:
    """Decision 430 (CPU): `filter/sharpen@2` is the certified candidate bit for bit. The seam
    serves it inside its served domain only (EXC-015's without 0.63 and 2.71); outside it, or
    with content off the 16-bit codes, nothing is evaluated."""
    passed = run_case(filter_tests, "sharpen2", tmp_path)
    assert len(passed) == 24, sorted(passed)
    for check in (
        "sharpen@2 carries its record's status: calibrated under EXC-015",
        "sharpen@2 at intensity 0.25 is I(I(F(rint(clamp(y) 65535)))) of the wrapped Laplacian",
        "sharpen@2 at intensity 4 is I(I(F(rint(clamp(y) 65535)))) of the wrapped Laplacian",
        "a content texel off the 16-bit codes fails evaluation loudly (CPU lane)",
        "a content texel off the 16-bit codes fails before any GPU work (candidate lane)",
        "the seam serves sharpen@2 inside its served domain",
        "outside the served domain, refused before evaluation: intensity 0.63",
        "outside the served domain, refused before evaluation: intensity 2.71",
        "outside the served domain, refused before evaluation: intensity 0.3",
        "a calibrated record that names no exception is refused (family not certified)",
        "sharpen@1 stays refused (family not certified)",
    ):
        assert check in passed


def test_sharpen_v2_passes_under_exc015_on_its_batch(filter_tests: Path, tmp_path: Path) -> None:
    """Decision 430 (CPU, private store): the native CPU lane of `filter/sharpen@2`, judged by the
    verdict on every compared texel (decision 423 §1) of the 54 calibration and 8 held-out cases
    of its batch. It is exact on the 47 cases the harness found exact and "pass under EXC-015" on
    the 11 cases at intensity 0.25. The 4 interior cases (0.63, 2.71) fail: their residuals are
    off the exact midpoints, so the record does not serve those intensities (decision 430
    amendment). The goldens stay in the store and pytest's own temporary folder; only counts
    print."""
    import numpy as np

    from tools.parity.proc_cert.raster import decode
    from tools.parity.proc_filters.sharpen_candidate import SharpenCandidate
    from tools.parity.proc_generators.coverage import covered_texels
    from tools.parity.schemas import REGISTER_PATH, load_json
    from tools.parity.store.store import locate
    from tools.parity.verdict import Comparison, FilterInputs, Outcome, evaluate

    store = locate()
    if store is None:
        pytest.skip("no private store on this machine: the goldens are unavailable")
    register = load_json(REGISTER_PATH)["entries"]
    batch = load_batch(SHARPEN2_BATCH)
    sets = (("calibration", batch.calibration), ("held-out", batch.held_out))
    cases = [(name, case) for name, corpus in sets for case in batch.cases(corpus)]
    assert len(cases) == 62
    outcomes: dict[str, tuple[str, tuple[tuple[str, int], ...]]] = {}
    for set_name, case in cases:
        rasters = {}
        for usage, (spec, ref) in [*case.inputs.items(), ("oracle", (case.output, case.oracle))]:
            data = store.load(ref.sha256, ref.size_bytes)
            assert data is not None, f"{case.case_id} {usage}: oracle_unavailable"
            rasters[usage] = np.asarray(decode(spec, ref.encoding, data), np.float32)
        resolution = case.output.resolution
        content_path, wsn_path, out_path = (tmp_path / n for n in ("c.f32", "wsn.f32", "out.f32"))
        content_path.write_bytes(np.ascontiguousarray(rasters["content"], "<f4").tobytes())
        wsn_path.write_bytes(np.ascontiguousarray(rasters["WorldSpaceNormal"], "<f4").tobytes())
        intensity = float(case.params["intensity"])
        served = intensity not in (0.63, 2.71)
        proc = subprocess.run(
            [
                *(str(filter_tests), "evaluate-sharpen", str(tmp_path), str(SHIPPED)),
                *(str(content_path), str(wsn_path), str(out_path), str(resolution)),
                repr(intensity),
            ],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        covered = covered_texels(rasters["WorldSpaceNormal"])
        if served:
            assert proc.returncode == 0, case.case_id + ": " + proc.stdout + proc.stderr
            out = np.fromfile(out_path, "<f4").reshape(resolution, resolution)
            candidate = np.where(covered, out, np.float32(0)).astype(np.float32)
        else:
            # Not served: the native lane refuses it before any work, and the certified
            # candidate (bit for bit the kernel on the served intensities) is what is judged.
            assert proc.returncode != 0 and "outside certified domain" in proc.stdout, proc.stdout
            candidate = SharpenCandidate().evaluate(case, rasters)[..., 0]
        golden = f"phase3/proc-filters/{set_name}-sharpen-{case.mesh_id}-{resolution}"
        content = rasters["content"][..., 0]
        inputs = FilterInputs(
            SHARPEN2, {"intensity": intensity}, content, "L32F_code_u16", "content"
        )
        comparison = Comparison(
            "2a",
            "procedural_asset/filter/sharpen",
            rasters["oracle"][..., 0],
            candidate,
            golden_id=golden,
            filter_inputs=inputs,
        )
        verdict = evaluate(comparison, register)
        outcomes[case.case_id] = (verdict.outcome.value, verdict.exceptions_relied_on)
    failed = sorted(k for k, v in outcomes.items() if v[0] != Outcome.PASS.value)
    assert failed == sorted(k for k in outcomes if k.startswith("interior-")), failed
    assert all(outcomes[k] == (Outcome.FAIL.value, ()) for k in failed)
    under = sorted(k for k, v in outcomes.items() if v[1] == (("EXC-015", 2),))
    print(f"exact {len(outcomes) - len(under) - len(failed)}, pass under EXC-015 {len(under)}, ")
    print(f"not covered {len(failed)} (0.63, 2.71: not served)")
    assert len(failed) == 4 and len(under) == 11, under
    assert all(k.startswith("recipe-hat-v8-mask-a--") for k in under)
