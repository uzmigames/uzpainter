"""The contract's decision rule (`tools.parity.verdict`) and the spec scenarios of P0-CONTRACT."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, TypedDict

import numpy as np
import pytest

from tools.parity.envelope.registry import current_envelope, initial_registry, save_registry
from tools.parity.schemas import (
    REGISTER_PATH,
    REPO_ROOT,
    SCHEMA_DIR,
    Schema,
    is_valid,
    load_json,
    register_problems,
)
from tools.parity.verdict import (
    Comparison,
    Outcome,
    Verdict,
    diagnose,
    evaluate,
    in_force,
    resolve_golden,
    whole_product_parity,
)

ENTRIES = SCHEMA_DIR / "samples" / "exceptions"
TIER1_DOMAIN = "tier1/wand_v1/Wand/BaseColor"
# The display state of a Tier 3 candidate's captured revision in the comparison standard's state.
PARITY = {"parity": True}


def bake_entry() -> dict[str, Any]:
    entry: dict[str, Any] = load_json(ENTRIES / "tier2b-bake-entry.json")
    return entry


def render_entry() -> dict[str, Any]:
    entry: dict[str, Any] = load_json(ENTRIES / "tier3-render-entry.json")
    return entry


def test_exact_equality_passes_without_exceptions() -> None:
    values = [0.0, 1.0, 65535.0, math.nan]
    verdict = evaluate(Comparison("1", TIER1_DOMAIN, values, list(values)), [])
    assert verdict.outcome is Outcome.PASS
    assert verdict.exceptions_relied_on == ()


def test_explained_difference_without_exception_fails() -> None:
    """Scenario: one differing texel with a documented explanation and no register entry."""
    oracle = [100.0] * 1000
    candidate = list(oracle)
    candidate[500] = 101.0  # documented cause elsewhere; the contract takes no explanation
    verdict = evaluate(Comparison("1", TIER1_DOMAIN, oracle, candidate), [bake_entry()])
    assert verdict.outcome is Outcome.FAIL
    assert verdict.diagnostics is not None
    assert verdict.diagnostics.differing_count == 1
    assert verdict.diagnostics.max_abs_diff == 1.0


def test_missing_oracle_blob_is_oracle_unavailable_not_a_pass() -> None:
    """Scenario: the public manifest's private blob is unavailable."""
    verdict = evaluate(Comparison("0", "tier0/blend/multiply/BaseColor", None, [1.0]), [])
    assert verdict.outcome is Outcome.ORACLE_UNAVAILABLE


def test_covering_entry_passes_and_is_listed() -> None:
    entry = bake_entry()
    domain = entry["domain"]["selector"]
    oracle = [10.0] * 1000
    candidate = list(oracle)
    candidate[0] = 12.0
    verdict = evaluate(Comparison("2b", domain, oracle, candidate), [entry])
    assert verdict.outcome is Outcome.PASS
    assert verdict.exceptions_relied_on == (("EXC-001", 1),)


def test_entry_whose_bound_does_not_hold_fails() -> None:
    entry = bake_entry()
    oracle = [10.0] * 1000
    candidate = list(oracle)
    candidate[0] = 14.0  # max |delta| 4 > bound 3
    verdict = evaluate(Comparison("2b", entry["domain"]["selector"], oracle, candidate), [entry])
    assert verdict.outcome is Outcome.FAIL


def test_entry_never_covers_another_tier_or_domain() -> None:
    entry = bake_entry()
    oracle, candidate = [10.0] * 1000, [10.0] * 999 + [11.0]
    same = evaluate(Comparison("2b", entry["domain"]["selector"], oracle, candidate), [entry])
    assert same.outcome is Outcome.PASS
    other_tier = evaluate(Comparison("1", entry["domain"]["selector"], oracle, candidate), [entry])
    other_domain = evaluate(Comparison("2b", "tier2b/wand/curvature", oracle, candidate), [entry])
    assert other_tier.outcome is Outcome.FAIL
    assert other_domain.outcome is Outcome.FAIL


def test_tier3_without_entry_is_blocked() -> None:
    verdict = evaluate(
        Comparison(
            "3",
            "tier3/analytic/sphere-constant-material",
            [0.5, 0.5],
            [0.5, 0.51],
            candidate_display_state=PARITY,
        ),
        [],
    )
    assert verdict.outcome is Outcome.BLOCKED


def test_tier3_entry_applies_per_region_bounds() -> None:
    entry = render_entry()
    domain = entry["domain"]["selector"]
    oracle, candidate = [0.5, 0.5], [0.5, 0.51]
    within = {"metal": {"abs_mean_signed_diff_in_se": 1.0, "p99_abs_diff": 0.01}}
    outside = {**within, "plastic": {"abs_mean_signed_diff_in_se": 5.0, "p99_abs_diff": 0.01}}
    passed = evaluate(
        Comparison(
            "3", domain, oracle, candidate, region_metrics=within, candidate_display_state=PARITY
        ),
        [entry],
    )
    blocked = evaluate(
        Comparison(
            "3", domain, oracle, candidate, region_metrics=outside, candidate_display_state=PARITY
        ),
        [entry],
    )
    no_regions = evaluate(
        Comparison("3", domain, oracle, candidate, candidate_display_state=PARITY), [entry]
    )
    assert passed.outcome is Outcome.PASS
    assert blocked.outcome is Outcome.BLOCKED
    assert no_regions.outcome is Outcome.BLOCKED


def test_structural_difference_fails_even_in_tier3() -> None:
    entry = render_entry()
    verdict = evaluate(
        Comparison(
            "3", entry["domain"]["selector"], [0.5, 0.5], [0.5], candidate_display_state=PARITY
        ),
        [entry],
    )
    assert verdict.outcome is Outcome.FAIL
    assert verdict.reason == "structural difference: shape mismatch"


def test_tier3_rejects_a_candidate_without_the_parity_display_state() -> None:
    """Decision 196 (amendment of 2026-10-19): a Tier 3 candidate render is evidence only when
    the display state of the revision it captured has `parity` true. A non-parity state (such as
    a stored `double_sided` true) or an unknown one is rejected before anything is compared, even
    when the values are equal and an entry would cover them."""
    entry = render_entry()
    domain = entry["domain"]["selector"]
    regions = {"metal": {"abs_mean_signed_diff_in_se": 0.0, "p99_abs_diff": 0.0}}
    for state, found in (
        ({"parity": False}, "parity False"),
        (None, "unknown"),
        ({}, "parity None"),
    ):
        comparison = Comparison(
            "3",
            domain,
            [0.5, 0.5],
            [0.5, 0.5],
            region_metrics=regions,
            candidate_display_state=state,
        )
        verdict = evaluate(comparison, [entry])
        assert verdict.outcome is Outcome.FAIL, state
        assert verdict.diagnostics is None and verdict.exceptions_relied_on == ()
        assert verdict.reason == (
            f"rejected as render evidence: the candidate's display state is {found} (decision 196)"
        )
    admitted = Comparison(
        "3", domain, [0.5, 0.5], [0.5, 0.5], region_metrics=regions, candidate_display_state=PARITY
    )
    assert evaluate(admitted, [entry]).outcome is Outcome.PASS
    # The other tiers compare exported maps, not renders: the display state plays no part.
    assert evaluate(Comparison("1", TIER1_DOMAIN, [1.0], [1.0]), []).outcome is Outcome.PASS


def test_superseded_version_is_not_in_force() -> None:
    v1 = bake_entry()
    v2 = bake_entry()
    v2["version"] = 2
    v2["bounds"] = [{"metric": "max_abs_diff", "scope": "whole", "max": 1}]
    register = {"schema": "uzpainter/parity/exceptions/1", "entries": [v1, v2]}
    assert is_valid(register, Schema.EXCEPTIONS)
    assert in_force([v1, v2]) == [v2]
    oracle, candidate = [10.0] * 1000, [12.0] + [10.0] * 999
    verdict = evaluate(Comparison("2b", v1["domain"]["selector"], oracle, candidate), [v1, v2])
    assert verdict.outcome is Outcome.FAIL


def test_diagnostics_report_max_mean_p99_and_counts() -> None:
    oracle = [0.0] * 200
    candidate = [0.0] * 197 + [1.0, 2.0, 8.0]
    d = diagnose(oracle, candidate)
    assert d.max_abs_diff == 8.0
    assert d.mean_abs_diff == pytest.approx(11.0 / 200)
    assert d.p99_abs_diff == 1.0  # nearest rank: the 198th of 200 sorted values
    assert (d.differing_count, d.total) == (3, 200)
    assert d.differing_percent == pytest.approx(1.5)
    assert set(d.metrics()) == {
        "max_abs_diff",
        "mean_abs_diff",
        "p99_abs_diff",
        "differing_count",
        "differing_percent",
    }


def test_nan_against_a_number_is_an_unbounded_difference() -> None:
    d = diagnose([1.0, math.nan], [1.0, 1.0])
    assert d.differing_count == 1
    assert math.isinf(d.max_abs_diff)


def test_diagnose_rejects_mismatched_or_empty_input() -> None:
    with pytest.raises(ValueError, match="shape mismatch"):
        diagnose([1.0], [1.0, 2.0])
    with pytest.raises(ValueError, match="nothing to compare"):
        diagnose([], [])


def test_arrays_are_judged_as_their_values_with_the_same_statistics() -> None:
    """Decoded maps go in as arrays (any shape, flattened in order): the statistics equal those of
    the same values as lists, infinities and NaNs included."""
    oracle = [0.0, 1.0, math.inf, math.nan, -math.inf, 5.0]
    candidate = [0.0, 2.0, math.inf, math.nan, math.inf, math.nan]
    listed = diagnose(oracle, candidate)
    arrayed = diagnose(np.array(oracle).reshape(2, 3), np.array(candidate).reshape(2, 3))
    assert arrayed == listed
    assert (listed.differing_count, listed.max_abs_diff) == (3, math.inf)
    codes = np.arange(12, dtype=np.int64).reshape(2, 2, 3)
    changed = codes.copy()
    changed[1, 1, 2] = 65535
    assert diagnose(codes, changed).max_abs_diff == 65535 - 11
    with pytest.raises(ValueError, match="shape mismatch"):
        diagnose(codes, codes.reshape(2, 3, 2))
    verdict = evaluate(Comparison("1", TIER1_DOMAIN, codes, codes.reshape(2, 3, 2)), [])
    assert verdict.outcome is Outcome.FAIL and "shape mismatch" in verdict.reason


def test_integer_differences_are_exact_beyond_int64() -> None:
    """uint64 2**64-1 against int64 -1 differs (an int64 cast would wrap both to -1)."""
    oracle = np.array([2**64 - 1, 7], dtype=np.uint64)
    candidate = np.array([-1, 7], dtype=np.int64)
    d = diagnose(oracle, candidate)
    assert (d.differing_count, d.max_abs_diff) == (1, float(2**64))
    assert evaluate(Comparison("1", TIER1_DOMAIN, oracle, candidate), []).outcome is Outcome.FAIL
    wide = np.array([np.iinfo(np.int64).max], dtype=np.int64)
    low = np.array([np.iinfo(np.int64).min], dtype=np.int64)
    assert diagnose(wide, low).max_abs_diff == float(2**64 - 1)
    edge = diagnose(np.array([2**62]), np.array([-(2**62)]))  # 2**63 overflows int64
    assert (edge.max_abs_diff, edge.mean_abs_diff, edge.p99_abs_diff) == (float(2**63),) * 3
    assert diagnose([2**62 - 1], [-(2**62) + 1]).max_abs_diff == float(2**63 - 2)


def test_tier3_equal_values_still_need_an_entry() -> None:
    entry = render_entry()
    domain = entry["domain"]["selector"]
    regions = {"metal": {"abs_mean_signed_diff_in_se": 0.0, "p99_abs_diff": 0.0}}
    without = evaluate(
        Comparison("3", domain, [0.5, 0.5], [0.5, 0.5], candidate_display_state=PARITY), []
    )
    covered = evaluate(
        Comparison(
            "3",
            domain,
            [0.5, 0.5],
            [0.5, 0.5],
            region_metrics=regions,
            candidate_display_state=PARITY,
        ),
        [entry],
    )
    assert without.outcome is Outcome.BLOCKED
    assert covered.outcome is Outcome.PASS
    assert covered.exceptions_relied_on == (("EXC-002", 1),)


def test_unstable_oracle_is_blocked_without_an_instability_entry() -> None:
    entry = bake_entry()
    domain = entry["domain"]["selector"]
    equal = evaluate(Comparison("2b", domain, [1.0], [1.0], oracle_stable=False), [])
    assert equal.outcome is Outcome.BLOCKED
    covered = evaluate(Comparison("2b", domain, [1.0], [1.0], oracle_stable=False), [entry])
    assert covered.outcome is Outcome.PASS
    irreducible = bake_entry()
    irreducible["evidence"]["basis"] = "irreducible_difference"
    other = evaluate(Comparison("2b", domain, [1.0], [1.0], oracle_stable=False), [irreducible])
    assert other.outcome is Outcome.BLOCKED


def test_tier3_noise_floor_entry_covers_an_unstable_iray_oracle() -> None:
    entry = render_entry()
    within = {"metal": {"abs_mean_signed_diff_in_se": 1.0, "p99_abs_diff": 0.01}}
    comparison = Comparison(
        "3",
        entry["domain"]["selector"],
        [0.5, 0.5],
        [0.5, 0.51],
        region_metrics=within,
        oracle_stable=False,
        candidate_display_state=PARITY,
    )
    verdict = evaluate(comparison, [entry])
    assert verdict.outcome is Outcome.PASS
    assert verdict.exceptions_relied_on == (("EXC-002", 1),)


# --- decision 032: unstable Painter oracle, r1 the exact target ---------------------------------


def decision_032_entries() -> list[dict[str, Any]]:
    """The in-force entries of decision 032 in the published register."""
    register: dict[str, Any] = load_json(REGISTER_PATH)
    entries = [dict(e) for e in in_force(register["entries"]) if e["decision_id"] == "032"]
    assert {e["domain"]["selector"] for e in entries} == {
        "tier0/quantisation/thirds",
        "tier0/blend/inputs",
        "tier0/height-normal/method",
        "tier0/height-normal/combination",
        "tier0/height-normal/resolution",
        "tier0/colour/ocio-encode",
        "tier0/colour/srgb-bitmaps",
    }
    return entries


class Case(TypedDict):
    golden_id: str | None
    output_id: str | None


def case_of(entry: dict[str, Any]) -> Case:
    """A golden and output the entry covers (decision 307: its first listed ones; none when the
    entry covers its whole domain), as `Comparison` keywords."""
    domain = entry["domain"]
    return {
        "golden_id": domain.get("goldens", [None])[0],
        "output_id": domain.get("outputs", [None])[0],
    }


def golden_verdicts(
    entry: dict[str, Any], r1: list[float], r2: list[float], candidate: list[float]
) -> tuple[Outcome, Outcome]:
    """The candidate against both recordings of an unstable golden, with the published register."""
    register: list[dict[str, Any]] = load_json(REGISTER_PATH)["entries"]
    domain = entry["domain"]["selector"]
    tier = entry["tier"]
    case = case_of(entry)
    exact = Comparison(tier, domain, r1, candidate, oracle_stable=False, exact_target=True, **case)
    other = Comparison(tier, domain, r2, candidate, oracle_stable=False, **case)
    return evaluate(exact, register).outcome, evaluate(other, register).outcome


def recordings(entry: dict[str, Any]) -> tuple[list[float], list[float]]:
    """r1 and an r2 that differs from it within the entry's bounds (one value at the max)."""
    r1 = [float(1000 + i) for i in range(64)]
    r2 = list(r1)
    r2[7] += max(b["max"] for b in entry["bounds"] if b["metric"] == "max_abs_diff")
    return r1, r2


def test_decision_032_r1_equality_passes_through_the_entry() -> None:
    for entry in decision_032_entries():
        r1, r2 = recordings(entry)
        assert golden_verdicts(entry, r1, r2, list(r1)) == (Outcome.PASS, Outcome.PASS)
        exact = Comparison(
            entry["tier"],
            entry["domain"]["selector"],
            r1,
            list(r1),
            oracle_stable=False,
            exact_target=True,
            **case_of(entry),
        )
        verdict = evaluate(exact, [entry])
        assert verdict.exceptions_relied_on == ((entry["exception_id"], entry["version"]),)
        assert evaluate(exact, []).outcome is Outcome.BLOCKED


def test_decision_032_entries_catch_injected_defects() -> None:
    """Every injected defect fails one of the golden's comparisons (the entries' defect test)."""
    for entry in decision_032_entries():
        r1, r2 = recordings(entry)
        defects: dict[str, list[float]] = {}
        one = list(r1)
        one[30] += 1.0
        defects["one_value_off_by_one_code"] = one
        defects["uniform_offset_one_code"] = [v + 1.0 for v in r1]
        region = list(r1)
        for i in range(16, 32):
            region[i] += 4096.0
        defects["one_wrong_texel_region"] = region
        floats = [float(i) / 64.0 for i in range(64)]
        last_place = list(floats)
        last_place[5] += 2.0**-24  # the RGB32F residual of phase1.10: never a pass
        assert set(defects) | {"float32_last_place_residual"} == set(
            entry["defect_detection_test"]["injected_defects"]
        )
        for name, candidate in defects.items():
            exact, other = golden_verdicts(entry, r1, r2, candidate)
            assert exact is Outcome.FAIL, name
            if name == "one_wrong_texel_region":
                assert other is not Outcome.PASS, name
        exact, _ = golden_verdicts(entry, floats, list(floats), last_place)
        assert exact is Outcome.FAIL
        assert entry["defect_detection_test"]["outcome"] == "every_injected_defect_fails"


# --- decision 307: entries scoped to goldens and outputs of their domain -----------------------

OCIO_DOMAIN = "tier0/colour/ocio-encode"
SRGB_BITMAPS = "tier0/colour/srgb-bitmaps"
LEGACY_GOLDEN = "tier0/semantics/export-ocio-encode-legacy"
OCIO_GOLDEN = "tier0/semantics/export-ocio-encode"
VARIANTS_GOLDEN = "tier0/semantics/srgb-bitmap-variants-v2"


def test_scoped_entries_cover_only_their_golden_and_outputs() -> None:
    """SUP-027 (decision 307): with the published register, the r2 comparisons of the Legacy and
    OCIO twins pass only through their own entries (EXC-006 version 2 and EXC-008), each within
    its own measured bounds; the s5 r2 comparisons of srgb-bitmap-variants-v2 pass through EXC-009
    only. None of them covers a comparison that names no golden, another golden of the domain,
    or an output it does not list, so the stable golden srgb-bitmap-minification and the stable
    maps of the covered goldens still fail on any difference."""
    register: list[dict[str, Any]] = load_json(REGISTER_PATH)["entries"]
    r1 = [float(1000 + i) for i in range(64)]

    def judge(
        selector: str, golden: str | None, output: str | None, delta: float, *, stable: bool = False
    ) -> Verdict:
        oracle = list(r1)
        oracle[7] += delta
        comparison = Comparison(
            "0",
            selector,
            oracle,
            list(r1),
            oracle_stable=stable,
            golden_id=golden,
            output_id=output,
        )
        return evaluate(comparison, register)

    legacy_png16 = (OCIO_DOMAIN, LEGACY_GOLDEN, "s5/basecolor/step46")
    ocio_png16 = (OCIO_DOMAIN, OCIO_GOLDEN, "s5/basecolor/step46")
    ocio_probe = (OCIO_DOMAIN, OCIO_GOLDEN, "probe/s50/s5_basecolor_sRGB.png")
    variants_png16 = (SRGB_BITMAPS, VARIANTS_GOLDEN, "s5/basecolor/step78")
    for case, delta, relied in (
        (legacy_png16, 619, ("EXC-006", 2)),
        (ocio_png16, 619, ("EXC-008", 1)),
        (ocio_png16, 620, ("EXC-008", 1)),
        (ocio_probe, 620, ("EXC-008", 1)),
        (variants_png16, 334, ("EXC-009", 1)),
    ):
        verdict = judge(*case, delta)
        assert verdict.outcome is Outcome.PASS, (case, delta)
        assert verdict.exceptions_relied_on == (relied,), (case, delta)
    # Each golden keeps its own bounds: the OCIO max does not pass on the Legacy golden.
    assert judge(*legacy_png16, 620).outcome is Outcome.BLOCKED
    assert judge(*ocio_png16, 621).outcome is Outcome.BLOCKED
    assert judge(*variants_png16, 335).outcome is Outcome.BLOCKED
    # Unnamed, other goldens and unlisted outputs are outside the scoped entries.
    assert judge(OCIO_DOMAIN, None, None, 1).outcome is Outcome.BLOCKED
    assert judge(OCIO_DOMAIN, OCIO_GOLDEN, None, 1).outcome is Outcome.BLOCKED
    assert judge(OCIO_DOMAIN, OCIO_GOLDEN, "s3/basecolor/step46", 1).outcome is Outcome.BLOCKED
    stable_cases: tuple[tuple[str, str | None, str | None], ...] = (
        (OCIO_DOMAIN, OCIO_GOLDEN, "s3/basecolor/step46"),
        (SRGB_BITMAPS, VARIANTS_GOLDEN, "s0/basecolor/step78"),
        (SRGB_BITMAPS, "tier0/semantics/srgb-bitmap-minification", "s4/basecolor/step36"),
        (SRGB_BITMAPS, None, None),
    )
    for stable_case in stable_cases:
        assert judge(*stable_case, 1, stable=True).outcome is Outcome.FAIL, stable_case


# Stable outputs (r1 = r2, measured on the private records with tools/parity/fit/stability.py) of
# each decision 032 domain: of the scoped goldens, and of every other golden of the domain.
STABLE_OUTPUTS: dict[str, tuple[tuple[str, str], ...]] = {
    "tier0/quantisation/thirds": (
        ("tier0/semantics/quantisation-thirds", "s0/user0"),
        ("tier0/semantics/quantisation-thirds", "s2/user1"),
    ),
    "tier0/blend/inputs": (
        ("tier0/semantics/blend-inputs", "s2/user0"),
        ("tier0/semantics/blend-inputs", "s0/user2"),
    ),
    "tier0/height-normal/method": (
        ("tier0/semantics-ui/height-normal-sharp-plane-strength", "s1/normal"),
        ("tier0/semantics-ui/height-normal-sharp-plane-strength", "s0/Normal_OpenGL"),
        ("tier0/semantics-ui/height-normal-sobel-plane-strength", "s4/normal"),
        ("tier0/semantics-ui/height-normal-sharp-sphere", "uzp_sphere/Normal_OpenGL"),
        ("tier0/semantics-ui/height-normal-sobel-bevelled-cube", "uzp_bevelled_cube/height"),
    ),
    "tier0/height-normal/combination": (
        ("tier0/semantics/height-normal-channel-coverage", "s2/height"),
        ("tier0/semantics/height-normal-channel-coverage", "s1/Normal_OpenGL"),
        ("tier0/semantics/height-normal-mesh-map", "s2/Normal_OpenGL"),
        ("tier0/semantics/height-normal-mesh-map-directx", "s2/Normal_DirectX"),
    ),
    "tier0/height-normal/resolution": (
        ("tier0/semantics/height-normal-resolution-2048", "s2/height"),
        ("tier0/semantics/height-normal-resolution-2048", "s0/Normal_OpenGL"),
        ("tier0/semantics/height-normal-resolution-512", "s2/Normal_OpenGL"),
        ("tier0/semantics/height-normal-resolution-1024", "s2/Normal_DirectX"),
        ("tier0/semantics/height-normal-resolution-1024-sobel", "s2/Normal_OpenGL"),
    ),
    OCIO_DOMAIN: (
        (LEGACY_GOLDEN, "probe/s50/s0_basecolor_.png"),
        (OCIO_GOLDEN, "probe/s50/s0_basecolor_sRGB.png"),
    ),
    SRGB_BITMAPS: (
        (VARIANTS_GOLDEN, "s0/basecolor/step78"),
        ("tier0/semantics/srgb-bitmap-minification", "s0/basecolor/step36"),
    ),
}


def test_decision_032_entries_cover_no_stable_comparison() -> None:
    """Decision 307 amendment: every in-force decision 032 entry is scoped to the goldens and
    outputs its evidence measured unstable. With the published register, a stable comparison of
    each domain fails on a one-code difference, whether it names no golden, a stable output of a
    scoped golden, or another golden of the domain (also under a listed output id); each listed
    output still passes against r2 at the entry's max, through that entry alone."""
    register: list[dict[str, Any]] = load_json(REGISTER_PATH)["entries"]
    r1 = [float(1000 + i) for i in range(64)]

    def judge(
        selector: str, golden: str | None, output: str | None, delta: float, *, stable: bool
    ) -> Verdict:
        oracle = list(r1)
        oracle[7] += delta
        comparison = Comparison(
            "0",
            selector,
            oracle,
            list(r1),
            oracle_stable=stable,
            golden_id=golden,
            output_id=output,
        )
        return evaluate(comparison, register)

    entries = decision_032_entries()
    assert {e["domain"]["selector"] for e in entries} == set(STABLE_OUTPUTS)
    unstable = {
        (e["domain"]["selector"], g, o)
        for e in entries
        for g in e["domain"].get("goldens", [])
        for o in e["domain"].get("outputs", [])
    }
    for entry in entries:
        domain = entry["domain"]
        selector = domain["selector"]
        assert domain.get("goldens") and domain.get("outputs"), entry["exception_id"]
        stable_cases: list[tuple[str | None, str | None]] = [(None, None)]
        stable_cases += list(STABLE_OUTPUTS[selector])
        others = sorted({g for g, _ in STABLE_OUTPUTS[selector]} - set(domain["goldens"]))
        # The same output ids under another golden of the domain, unless that golden's own
        # entry lists them (the OCIO twins share their unstable outputs).
        stable_cases += [
            (g, o) for g in others for o in domain["outputs"] if (selector, g, o) not in unstable
        ]
        for golden, output in stable_cases:
            assert (selector, golden, output) not in unstable, (golden, output)
            verdict = judge(selector, golden, output, 1, stable=True)
            assert verdict.outcome is Outcome.FAIL, (entry["exception_id"], golden, output)
        top = max(b["max"] for b in entry["bounds"] if b["metric"] == "max_abs_diff")
        relied = ((entry["exception_id"], entry["version"]),)
        for golden in domain["goldens"]:
            for output in domain["outputs"]:
                verdict = judge(selector, golden, output, top, stable=False)
                assert verdict.outcome is Outcome.PASS, (entry["exception_id"], golden, output)
                assert verdict.exceptions_relied_on == relied, (golden, output)


def test_register_scopes_name_current_goldens_of_their_domain() -> None:
    """Decision 307: `outputs` needs `goldens`, and every listed golden resolves through the
    current envelope with the entry's domain (`register_problems`)."""
    register: dict[str, Any] = load_json(REGISTER_PATH)
    assert register_problems(register) == []
    entry = next(e for e in register["entries"] if e["exception_id"] == "EXC-009")
    for goldens, expected in (
        ([OCIO_GOLDEN], f"golden {OCIO_GOLDEN} is not a current golden of {SRGB_BITMAPS}"),
        (["tier0/semantics/no-such-golden"], "no-such-golden is not a current golden"),
    ):
        changed = json.loads(json.dumps(register))
        target = next(e for e in changed["entries"] if e["exception_id"] == "EXC-009")
        target["domain"]["goldens"] = goldens
        problems = register_problems(changed)
        assert len(problems) == 1 and expected in problems[0], problems
    unscoped = json.loads(json.dumps(entry))
    del unscoped["domain"]["goldens"]
    assert not is_valid({"schema": register["schema"], "entries": [unscoped]}, Schema.EXCEPTIONS)


# --- decision 223: an owner scope split excepts the uncovered texels only ---------------------
# EXC-007 version 1 holds the terms; version 2 withdraws them (decision 259).


def exc007(version: int) -> dict[str, Any]:
    register = load_json(REGISTER_PATH)
    (entry,) = [
        e for e in register["entries"] if e["exception_id"] == "EXC-007" and e["version"] == version
    ]
    return dict(entry)


def scope_split_entry() -> dict[str, Any]:
    """EXC-007 version 1's terms, the mechanism of decision 223 (withdrawn, decision 259)."""
    return exc007(1)


def scope_split_case() -> tuple[np.ndarray, np.ndarray]:
    """An 8 x 8 PNG 16 map with a 4 x 4 island: the oracle, and its coverage."""
    oracle = np.arange(64, dtype=np.int64).reshape(8, 8) * 512
    covered = np.zeros((8, 8), dtype=bool)
    covered[2:6, 2:6] = True
    return oracle, covered


def test_owner_scope_split_excepts_only_the_uncovered_texels() -> None:
    """EXC-007 version 1 (decision 223) on its own: any padding difference passes and names the
    entry; the comparison is still exact where it is exact; another tier or domain is not
    covered."""
    entry = scope_split_entry()
    assert is_valid(load_json(REGISTER_PATH), Schema.EXCEPTIONS)
    assert entry["evidence"]["basis"] == "owner_scope_split"
    assert entry["bounds"] == [{"metric": "max_abs_diff", "scope": "covered", "max": 0}]
    domain = entry["domain"]["selector"]
    oracle, covered = scope_split_case()
    padded = oracle.copy()
    padded[~covered] = 65535 - padded[~covered]  # every padding texel wrong, by up to 65535
    verdict = evaluate(Comparison("1", domain, oracle, padded, covered=covered), [entry])
    assert verdict.outcome is Outcome.PASS
    assert verdict.exceptions_relied_on == (("EXC-007", 1),)
    assert verdict.diagnostics is not None and verdict.diagnostics.max_abs_diff > 0
    exact = evaluate(Comparison("1", domain, oracle, oracle.copy(), covered=covered), [entry])
    assert exact.outcome is Outcome.PASS and exact.exceptions_relied_on == ()
    for tier, selector in (("0", domain), ("1", TIER1_DOMAIN)):
        other = evaluate(Comparison(tier, selector, oracle, padded, covered=covered), [entry])
        assert other.outcome is Outcome.FAIL, (tier, selector)


def test_owner_scope_split_catches_injected_defects() -> None:
    """EXC-007 version 1's defect test: every injected defect on the covered texels fails, and so
    does any padding difference when the comparison has no usable coverage mask."""
    entry = scope_split_entry()
    domain = entry["domain"]["selector"]
    oracle, covered = scope_split_case()
    padding = oracle.copy()
    padding[~covered] += 7  # an excepted difference, present in every case below
    defects: dict[str, tuple[np.ndarray, np.ndarray | None]] = {}
    one = padding.copy()
    one[3, 3] += 1
    defects["one_covered_value_off_by_one_code"] = (one, covered)
    defects["uniform_offset_one_code"] = (padding + 1, covered)
    region = padding.copy()
    region[2:4, 2:6] += 4096
    defects["one_wrong_covered_region"] = (region, covered)
    defects["no_coverage_mask"] = (padding, None)
    defects["coverage_mask_of_another_size"] = (padding, np.ones((4, 4), dtype=bool))
    assert set(defects) == set(entry["defect_detection_test"]["injected_defects"])
    for name, (candidate, mask) in defects.items():
        verdict = evaluate(Comparison("1", domain, oracle, candidate, covered=mask), [entry])
        assert verdict.outcome is Outcome.FAIL, name
        assert verdict.exceptions_relied_on == (), name
    nothing = evaluate(
        Comparison("1", domain, oracle, padding, covered=np.zeros((8, 8), dtype=bool)), [entry]
    )
    assert nothing.outcome is Outcome.FAIL  # no covered texel: the entry covers nothing
    assert entry["defect_detection_test"]["outcome"] == "every_injected_defect_fails"


def test_an_owner_scope_split_must_hold_the_covered_texels_exact() -> None:
    """The schema admits `owner_scope_split` only with covered-scope bounds including max |delta|
    0 on the covered texels, and the `covered` scope only for it."""
    entry = scope_split_entry()
    register = {"schema": "uzpainter/parity/exceptions/1", "entries": [entry]}
    assert is_valid(register, Schema.EXCEPTIONS)
    loose = {**entry, "bounds": [{"metric": "max_abs_diff", "scope": "covered", "max": 1}]}
    whole = {**entry, "bounds": [{"metric": "max_abs_diff", "scope": "whole", "max": 0}]}
    other = load_json(REGISTER_PATH)["entries"][0]
    stray = {**other, "bounds": [{"metric": "max_abs_diff", "scope": "covered", "max": 0}]}
    for bad in (loose, whole, stray):
        assert not is_valid({**register, "entries": [bad]}, Schema.EXCEPTIONS)


# --- decision 259: the owner withdrew EXC-007 ---------------------------------------------------


def test_withdrawn_exc007_fails_every_padding_difference() -> None:
    """EXC-007 version 2 withdraws the id, so nothing of it is in force: with the published
    register, every injected difference on the Wand v1 Tier 1 domain fails, padding texels
    included, and relies on no entry; an exact map still passes."""
    register: list[dict[str, Any]] = load_json(REGISTER_PATH)["entries"]
    withdrawal = exc007(2)
    assert withdrawal["withdrawn"] is True and withdrawal["decision_id"] == "259"
    assert [e for e in in_force(register) if e["exception_id"] == "EXC-007"] == []
    domain = withdrawal["domain"]["selector"]
    oracle, covered = scope_split_case()
    defects: dict[str, np.ndarray] = {}
    one = oracle.copy()
    one[0, 0] += 1  # a padding texel
    defects["one_padding_value_off_by_one_code"] = one
    every = oracle.copy()
    every[~covered] = 65535 - every[~covered]
    defects["every_padding_texel_wrong"] = every
    inside = oracle.copy()
    inside[3, 3] += 1
    defects["one_covered_value_off_by_one_code"] = inside
    defects["uniform_offset_one_code"] = oracle + 1
    assert set(defects) == set(withdrawal["defect_detection_test"]["injected_defects"])
    for name, candidate in defects.items():
        verdict = evaluate(Comparison("1", domain, oracle, candidate, covered=covered), register)
        assert verdict.outcome is Outcome.FAIL, name
        assert verdict.exceptions_relied_on == (), name
    exact = evaluate(Comparison("1", domain, oracle, oracle.copy(), covered=covered), register)
    assert exact.outcome is Outcome.PASS and exact.exceptions_relied_on == ()
    assert withdrawal["defect_detection_test"]["outcome"] == "every_injected_defect_fails"


def test_a_withdrawal_leaves_nothing_in_force_and_needs_a_version_to_withdraw() -> None:
    """A withdrawing version hides its id until a higher version restates terms; one with no
    lower version of its id is a register problem."""
    v1 = {**bake_entry(), "decision_id": "259"}  # a recorded decision
    v2 = {**v1, "version": 2, "withdrawn": True}
    v3 = {**v1, "version": 3}
    assert in_force([v1, v2]) == []
    assert in_force([v1, v2, v3]) == [v3]
    schema = "uzpainter/parity/exceptions/1"
    assert register_problems({"schema": schema, "entries": [v1, v2]}) == []
    lone = {"schema": schema, "entries": [{**v1, "withdrawn": True}]}
    assert any("withdraws no earlier version" in p for p in register_problems(lone))
    assert register_problems(load_json(REGISTER_PATH)) == []


# --- decisions 034 and 037: the envelope -------------------------------------------------------

CURRENT = "painter-12.1.5+js-api.1.1.20"
OLDER = "painter-12.1.0+js-api.1.1.20"
DOMAIN = "tier0/blend/multiply/BaseColor"


def environment(**changes: str) -> dict[str, str]:
    record = {
        "painter_build": "12.1.5+js-api.1.1.20",
        "gpu_model": "synthetic GPU",
        "driver_version": "1.0",
        "os_build": "10.0.1.1",
        "colour_configuration_sha256": "0" * 64,
    }
    return {**record, **changes}


def test_verdict_names_the_current_envelope_of_the_registry() -> None:
    verdict = evaluate(Comparison("0", DOMAIN, [1.0], [1.0]), [])
    assert verdict.outcome is Outcome.PASS
    assert verdict.envelope_id == current_envelope()["envelope_id"]
    named = evaluate(Comparison("0", DOMAIN, [1.0], [1.0]), [], CURRENT)
    assert named.envelope_id == CURRENT


@pytest.mark.parametrize("tier", ["0", "2b", "3"])
def test_a_golden_of_an_older_envelope_is_stale_never_a_pass(tier: str) -> None:
    """Decision 037 §4, §6: an old-envelope pass never carries over, whatever the register."""
    entry = render_entry()
    regions = {"metal": {"abs_mean_signed_diff_in_se": 0.0, "p99_abs_diff": 0.0}}
    selector = entry["domain"]["selector"]
    older = Comparison(
        tier,
        selector,
        [0.5],
        [0.5],
        region_metrics=regions,
        envelope_id=OLDER,
        candidate_display_state=PARITY,
    )
    verdict = evaluate(older, [entry, bake_entry()], CURRENT)
    assert verdict.outcome is Outcome.STALE
    assert verdict.diagnostics is not None and verdict.diagnostics.differing_count == 0
    assert verdict.exceptions_relied_on == ()
    current = Comparison(
        tier,
        selector,
        [0.5],
        [0.5],
        region_metrics=regions,
        envelope_id=CURRENT,
        candidate_display_state=PARITY,
    )
    assert evaluate(current, [entry], CURRENT).outcome is Outcome.PASS


def test_uzpainter_comparisons_ignore_the_live_environment() -> None:
    """Scenario: driver update does not invalidate UzPainter verdicts."""
    comparison = Comparison(
        "0",
        DOMAIN,
        [1.0, 2.0],
        [1.0, 2.0],
        golden_environment=environment(driver_version="A"),
        candidate_environment=environment(driver_version="B"),
    )
    assert evaluate(comparison, [], CURRENT).outcome is Outcome.PASS


@pytest.mark.parametrize(
    "candidate_environment",
    [
        environment(driver_version="2.0"),
        environment(painter_build="12.1.6+js-api.1.1.20"),
        environment(gpu_model="unknown"),
        None,
    ],
    ids=["driver", "build", "unknown-field", "no-record"],
)
@pytest.mark.parametrize(
    "candidate", [[1.0, 2.0], [1.0, 3.0], [1.0]], ids=["equal", "different", "shape"]
)
def test_oracle_side_comparison_outside_the_envelope_is_out_of_envelope(
    candidate_environment: dict[str, str] | None, candidate: list[float]
) -> None:
    """Scenario: re-recording under a new driver is out of envelope, never pass or fail."""
    comparison = Comparison(
        "0",
        DOMAIN,
        [1.0, 2.0],
        candidate,
        oracle_side=True,
        golden_environment=environment(),
        candidate_environment=candidate_environment,
    )
    verdict = evaluate(comparison, [], CURRENT)
    assert verdict.outcome is Outcome.OUT_OF_ENVELOPE
    assert (verdict.diagnostics is None) == (len(candidate) != 2)


def test_oracle_rerecording_against_an_older_envelope_golden_is_out_of_envelope() -> None:
    """The canary's case: a re-recording under 12.1.5 against a 12.1.0 golden."""
    comparison = Comparison(
        "0",
        DOMAIN,
        [1.0],
        [1.0],
        envelope_id=OLDER,
        oracle_side=True,
        golden_environment=environment(painter_build="12.1.0+js-api.1.1.20"),
        candidate_environment=environment(),
    )
    assert evaluate(comparison, [], CURRENT).outcome is Outcome.OUT_OF_ENVELOPE


def test_oracle_side_comparison_inside_the_envelope_follows_the_rules() -> None:
    def oracle_side(candidate: list[float]) -> Outcome:
        comparison = Comparison(
            "0",
            DOMAIN,
            [1.0, 2.0],
            candidate,
            oracle_side=True,
            golden_environment=environment(),
            candidate_environment=environment(),
        )
        return evaluate(comparison, [], CURRENT).outcome

    assert oracle_side([1.0, 2.0]) is Outcome.PASS
    assert oracle_side([1.0, 3.0]) is Outcome.FAIL


def test_decision_032_exact_target_holds_within_the_current_envelope() -> None:
    for entry in decision_032_entries():
        r1, _ = recordings(entry)
        tier, selector, case = entry["tier"], entry["domain"]["selector"], case_of(entry)
        moved = [v + 1.0 for v in r1]
        exact = Comparison(
            tier,
            selector,
            r1,
            moved,
            oracle_stable=False,
            exact_target=True,
            envelope_id=CURRENT,
            **case,
        )
        assert evaluate(exact, [entry], CURRENT).outcome is Outcome.FAIL
        equal = Comparison(
            tier,
            selector,
            r1,
            list(r1),
            oracle_stable=False,
            exact_target=True,
            envelope_id=CURRENT,
            **case,
        )
        assert evaluate(equal, [entry], CURRENT).outcome is Outcome.PASS
        older = Comparison(
            tier,
            selector,
            r1,
            list(r1),
            oracle_stable=False,
            exact_target=True,
            envelope_id=OLDER,
            **case,
        )
        assert evaluate(older, [entry], CURRENT).outcome is Outcome.STALE


def test_no_whole_product_parity_while_a_tier3_reference_is_stale() -> None:
    passed = Verdict(Outcome.PASS, None, envelope_id=CURRENT)
    stale = Verdict(Outcome.STALE, None, envelope_id=CURRENT)
    assert whole_product_parity([passed, passed], CURRENT)
    assert not whole_product_parity([passed, stale], CURRENT)
    assert not whole_product_parity([Verdict(Outcome.PASS, None, envelope_id=OLDER)], CURRENT)
    assert not whole_product_parity([], CURRENT)


# --- golden resolution through the registry -----------------------------------------------------


def test_goldens_resolve_through_the_current_envelope() -> None:
    current = current_envelope()
    golden = resolve_golden("tier0/semantics/height-normal-sphere")
    assert golden is not None and not golden.stale
    assert golden.envelope_id == current["envelope_id"]
    assert golden.manifest_path.is_relative_to(REPO_ROOT / current["manifest_root"])
    assert golden.manifest["software"]["painter"]["build_id"] == current["painter_build"]
    assert resolve_golden("tier0/semantics/no-such-golden") is None


def test_a_tier3_reference_of_an_older_envelope_resolves_stale() -> None:
    golden = resolve_golden("tier3/render-procedure/qualification-sphere")
    assert golden is not None
    if not golden.stale:
        assert golden.envelope_id == current_envelope()["envelope_id"]
        return
    assert golden.envelope_id != current_envelope()["envelope_id"]
    domain = golden.manifest["domain"]
    comparison = Comparison(
        "3", domain, [0.5], [0.5], envelope_id=golden.envelope_id, candidate_display_state=PARITY
    )
    assert evaluate(comparison, [render_entry()]).outcome is Outcome.STALE


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def synthetic_manifest(golden_id: str, tier: str, build: str) -> dict[str, Any]:
    painter = {"product": "Adobe Substance 3D Painter", "version": "1.0.0", "build_id": build}
    return {"golden_id": golden_id, "tier": tier, "software": {"painter": painter}}


OLD_ROOT = "parity/manifests"
NEW_ROOT = "parity/envelopes/painter-2.0.0/manifests"


def two_envelope_repository(root: Path) -> None:
    """A registry where `painter-1.0.0` is superseded by `painter-2.0.0` (current)."""
    document = initial_registry("1.0.0", "1.0.0", OLD_ROOT, "2026-01-01")
    old = document["envelopes"][0]
    new = {
        **old,
        "envelope_id": "painter-2.0.0",
        "painter_build": "2.0.0",
        "painter_version": "2.0.0",
        "manifest_root": NEW_ROOT,
        "previous": "painter-1.0.0",
        "promoted_on": "2026-02-01",
    }
    old.update(status="superseded", superseded_on="2026-02-01")
    save_registry({**document, "current": "painter-2.0.0", "envelopes": [old, new]}, root)
    write_json(root / OLD_ROOT / "t0.json", synthetic_manifest("tier0/a", "0", "1.0.0"))
    write_json(root / OLD_ROOT / "t0b.json", synthetic_manifest("tier0/only-old", "0", "1.0.0"))
    write_json(root / OLD_ROOT / "t3.json", synthetic_manifest("tier3/ref", "3", "1.0.0"))
    write_json(root / NEW_ROOT / "t0.json", synthetic_manifest("tier0/a", "0", "2.0.0"))
    write_json(root / NEW_ROOT / "mixed.json", synthetic_manifest("tier0/mixed", "0", "1.0.0"))


def test_resolution_never_carries_a_texture_golden_over_from_an_older_envelope(
    tmp_path: Path,
) -> None:
    two_envelope_repository(tmp_path)
    current = resolve_golden("tier0/a", tmp_path)
    assert current is not None
    assert (current.envelope_id, current.stale) == ("painter-2.0.0", False)
    assert current.manifest_path == tmp_path / NEW_ROOT / "t0.json"
    assert resolve_golden("tier0/only-old", tmp_path) is None
    tier3 = resolve_golden("tier3/ref", tmp_path)
    assert tier3 is not None and (tier3.envelope_id, tier3.stale) == ("painter-1.0.0", True)
    mixed = resolve_golden("tier0/mixed", tmp_path)
    assert mixed is not None and (mixed.envelope_id, mixed.stale) == ("painter-1.0.0", True)
