"""The contract's decision rule (`tools.parity.verdict`) and the spec scenarios of P0-CONTRACT."""

from __future__ import annotations

import math
from typing import Any

import pytest

from tools.parity.schemas import REGISTER_PATH, SCHEMA_DIR, Schema, is_valid, load_json
from tools.parity.verdict import Comparison, Outcome, diagnose, evaluate, in_force

ENTRIES = SCHEMA_DIR / "samples" / "exceptions"
TIER1_DOMAIN = "tier1/wand_v1/Wand/BaseColor"


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
        Comparison("3", "tier3/analytic/sphere-constant-material", [0.5, 0.5], [0.5, 0.51]), []
    )
    assert verdict.outcome is Outcome.BLOCKED


def test_tier3_entry_applies_per_region_bounds() -> None:
    entry = render_entry()
    domain = entry["domain"]["selector"]
    oracle, candidate = [0.5, 0.5], [0.5, 0.51]
    within = {"metal": {"abs_mean_signed_diff_in_se": 1.0, "p99_abs_diff": 0.01}}
    outside = {**within, "plastic": {"abs_mean_signed_diff_in_se": 5.0, "p99_abs_diff": 0.01}}
    passed = evaluate(Comparison("3", domain, oracle, candidate, region_metrics=within), [entry])
    blocked = evaluate(Comparison("3", domain, oracle, candidate, region_metrics=outside), [entry])
    no_regions = evaluate(Comparison("3", domain, oracle, candidate), [entry])
    assert passed.outcome is Outcome.PASS
    assert blocked.outcome is Outcome.BLOCKED
    assert no_regions.outcome is Outcome.BLOCKED


def test_structural_difference_fails_even_in_tier3() -> None:
    entry = render_entry()
    verdict = evaluate(Comparison("3", entry["domain"]["selector"], [0.5, 0.5], [0.5]), [entry])
    assert verdict.outcome is Outcome.FAIL


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


def test_tier3_equal_values_still_need_an_entry() -> None:
    entry = render_entry()
    domain = entry["domain"]["selector"]
    regions = {"metal": {"abs_mean_signed_diff_in_se": 0.0, "p99_abs_diff": 0.0}}
    without = evaluate(Comparison("3", domain, [0.5, 0.5], [0.5, 0.5]), [])
    covered = evaluate(
        Comparison("3", domain, [0.5, 0.5], [0.5, 0.5], region_metrics=regions), [entry]
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
    )
    verdict = evaluate(comparison, [entry])
    assert verdict.outcome is Outcome.PASS
    assert verdict.exceptions_relied_on == (("EXC-002", 1),)


# --- decision 032: unstable Painter oracle, r1 the exact target ---------------------------------


def decision_032_entries() -> list[dict[str, Any]]:
    register: dict[str, Any] = load_json(REGISTER_PATH)
    entries = [e for e in register["entries"] if e["decision_id"] == "032"]
    assert {e["domain"]["selector"] for e in entries} == {
        "tier0/quantisation/thirds",
        "tier0/blend/inputs",
    }
    return entries


def golden_verdicts(
    entry: dict[str, Any], r1: list[float], r2: list[float], candidate: list[float]
) -> tuple[Outcome, Outcome]:
    """The candidate against both recordings of an unstable golden, with the published register."""
    register: list[dict[str, Any]] = load_json(REGISTER_PATH)["entries"]
    domain = entry["domain"]["selector"]
    tier = entry["tier"]
    exact = Comparison(tier, domain, r1, candidate, oracle_stable=False, exact_target=True)
    other = Comparison(tier, domain, r2, candidate, oracle_stable=False)
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
