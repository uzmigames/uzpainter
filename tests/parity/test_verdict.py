"""The contract's decision rule (`tools.parity.verdict`) and the spec scenarios of P0-CONTRACT."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from tools.parity.envelope.registry import current_envelope, initial_registry, save_registry
from tools.parity.schemas import REGISTER_PATH, REPO_ROOT, SCHEMA_DIR, Schema, is_valid, load_json
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
        "tier0/height-normal/method",
        "tier0/height-normal/combination",
        "tier0/height-normal/resolution",
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
    older = Comparison(tier, selector, [0.5], [0.5], region_metrics=regions, envelope_id=OLDER)
    verdict = evaluate(older, [entry, bake_entry()], CURRENT)
    assert verdict.outcome is Outcome.STALE
    assert verdict.diagnostics is not None and verdict.diagnostics.differing_count == 0
    assert verdict.exceptions_relied_on == ()
    current = Comparison(tier, selector, [0.5], [0.5], region_metrics=regions, envelope_id=CURRENT)
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
        tier, selector = entry["tier"], entry["domain"]["selector"]
        moved = [v + 1.0 for v in r1]
        exact = Comparison(
            tier, selector, r1, moved, oracle_stable=False, exact_target=True, envelope_id=CURRENT
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
        )
        assert evaluate(equal, [entry], CURRENT).outcome is Outcome.PASS
        older = Comparison(
            tier, selector, r1, list(r1), oracle_stable=False, exact_target=True, envelope_id=OLDER
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
    comparison = Comparison("3", domain, [0.5], [0.5], envelope_id=golden.envelope_id)
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
