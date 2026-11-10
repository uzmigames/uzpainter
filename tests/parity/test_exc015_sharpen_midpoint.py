"""EXC-015 (decision 430): the Sharpen midpoint exception and the verdict's midpoint scope.

The content is synthetic: seeded uniform 16-bit codes stored as decision 426 §1's channel value
I(I(F(k))). No Painter value is read. The candidate is the certified model
(`tools/parity/proc_filters/sharpen_candidate.py`). The stand-in oracle is that model with Painter's
unreproduced tie-break played by moving midpoint texels one code up or down.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import numpy as np
import pytest

from tools.parity.midpoint import content_codes, exact_decimal, laplacian4_midpoints
from tools.parity.proc_filters.levels_candidate import twice_inverted
from tools.parity.proc_filters.sharpen_candidate import sharpen_codes
from tools.parity.schemas import REGISTER_PATH, Schema, is_valid, load_json, register_problems
from tools.parity.verdict import Comparison, FilterInputs, Outcome, evaluate, in_force
from tools.parity.vk_sampler_probe import unorm16

DOMAIN = "procedural_asset/filter/sharpen"
GOLDEN = "phase3/proc-filters/calibration-sharpen-sphere-1024"
ASSET = "uzasset://filter/sharpen@2"
SIZE = 96
TESTED = (0.0, 0.2, 0.25, 0.4, 0.63, 1.0, 2.71, 4.0)
EXACT = (0.0, 0.2, 0.4, 1.0, 4.0)


def exc015() -> dict[str, Any]:
    register = load_json(REGISTER_PATH)
    (entry,) = [e for e in in_force(register["entries"]) if e["exception_id"] == "EXC-015"]
    return dict(entry)


def codes_of(seed: int) -> np.ndarray[Any, Any]:
    return np.random.default_rng(seed).integers(0, 65536, size=(SIZE, SIZE), dtype=np.int64)


def stored(codes: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """The channel value of 16-bit codes (decision 426 §1)."""
    out: np.ndarray[Any, Any] = twice_inverted(unorm16.fetch(codes))
    return out


def comparison(
    content: np.ndarray[Any, Any],
    oracle_codes: np.ndarray[Any, Any],
    candidate: np.ndarray[Any, Any],
    intensity: float,
    *,
    stack: str = "content",
    golden: str = GOLDEN,
) -> Comparison:
    inputs = FilterInputs(ASSET, {"intensity": intensity}, content, "L32F_code_u16", stack)
    return Comparison(
        "2a", DOMAIN, stored(oracle_codes), candidate, golden_id=golden, filter_inputs=inputs
    )


def unwrapped_sharpen(codes: np.ndarray[Any, Any], intensity: float) -> np.ndarray[Any, Any]:
    """The model with clamp-to-edge neighbours in place of the texture wrap."""
    x = unorm16.fetch(codes)
    padded = np.pad(x, 1, mode="edge")
    n, s = padded[:-2, 1:-1], padded[2:, 1:-1]
    e, w = padded[1:-1, 2:], padded[1:-1, :-2]
    f32 = np.float32
    laplacian = (f32(4.0) * x - ((n + s) + (e + w))).astype(f32)
    y = (x + (f32(intensity) * laplacian).astype(f32)).astype(f32)
    out: np.ndarray[Any, Any] = np.rint(np.clip(y, f32(0), f32(1)) * f32(65535)).astype(np.int64)
    return out


def laplacian(codes: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    k = codes.astype(np.int64)
    rolled = sum(np.roll(k, d, axis=a) for a in (0, 1) for d in (1, -1))
    out: np.ndarray[Any, Any] = 4 * k - rolled
    return out


def first(mask: np.ndarray[Any, Any]) -> tuple[int, int]:
    rows, cols = np.nonzero(mask)
    assert rows.size, "the synthetic content has no such texel"
    return int(rows[0]), int(cols[0])


def test_the_register_holds_exc015_on_its_approved_terms() -> None:
    """Decision 430: EXC-015 version 1 is in force on decision 428 §2's terms and nothing wider."""
    register = load_json(REGISTER_PATH)
    assert is_valid(register, Schema.EXCEPTIONS) and register_problems(register) == []
    entry = exc015()
    assert entry["version"] == 1 and entry["tier"] == "2a"
    assert (entry["approved_by"], entry["approved_on"], entry["decision_id"]) == (
        "owner",
        "2026-11-10",
        "430",
    )
    domain = entry["domain"]
    assert (domain["kind"], domain["selector"]) == ("procedural_asset", DOMAIN)
    assert len(domain["goldens"]) == 11 and not any("diagnostic" in g for g in domain["goldens"])
    spec = domain["procedural_filter"]
    assert spec == {
        "asset": ASSET,
        "kernel": "laplacian4_wrap",
        "parameter": "intensity",
        "values": [0, 0.2, 0.25, 0.4, 0.63, 1, 2.71, 4],
        "content_format": "L32F_code_u16",
        "stack": "content",
    }
    assert entry["bounds"] == [
        {"metric": "max_abs_diff", "scope": "off_midpoint", "max": 0},
        {"metric": "max_abs_diff_code_u16", "scope": "midpoint", "max": 1},
    ]
    assert entry["evidence"]["basis"] == "owner_scope_split"
    # A midpoint scope outside a procedural filter domain, or the code metric off `midpoint`, is
    # not a valid entry.
    for change in ("no_filter", "code_metric_off_midpoint", "other_kind"):
        changed = json_copy(entry)
        if change == "no_filter":
            del changed["domain"]["procedural_filter"]
        elif change == "code_metric_off_midpoint":
            changed["bounds"][1]["scope"] = "off_midpoint"
        else:
            changed["domain"]["kind"] = "asset_map"
        assert not is_valid({"schema": register["schema"], "entries": [changed]}, Schema.EXCEPTIONS)


def json_copy(entry: dict[str, Any]) -> dict[str, Any]:
    import json

    copied: dict[str, Any] = json.loads(json.dumps(entry))
    return copied


@pytest.mark.parametrize("intensity", TESTED)
def test_midpoints_are_the_exact_half_integers_between_two_codes(intensity: float) -> None:
    """The predicate, from the inputs: intensity x L exactly a half-integer, k + intensity x L
    strictly inside (0, 65535). The exact intensities never give one; 0.25, 0.63 and 2.71 do."""
    codes = codes_of(7)
    mask = laplacian4_midpoints(codes, exact_decimal(intensity))
    exact = exact_decimal(intensity) * 1
    expected = np.zeros_like(mask)
    lap = laplacian(codes)
    for (r, c), value in np.ndenumerate(lap):
        t = exact * int(value)
        k = int(codes[r, c])
        expected[r, c] = t.denominator == 2 and 0 < k + t < 65535
    assert np.array_equal(mask, expected)
    assert mask.any() == (intensity not in EXACT)
    assert exact_decimal(0.63) == Fraction(63, 100) and exact_decimal(2.71) == Fraction(271, 100)


def test_the_certified_model_passes_under_exc015_with_painter_s_tie_breaks() -> None:
    """The baseline each defect starts from: the candidate equals the stand-in oracle off the
    midpoints and is one code away on some midpoint texels, at 0.25, 0.63 and 2.71."""
    entry = exc015()
    register: list[dict[str, Any]] = load_json(REGISTER_PATH)["entries"]
    for seed, intensity in ((1, 0.25), (2, 0.63), (3, 2.71)):
        codes = codes_of(seed)
        content = stored(codes)
        model = sharpen_codes(codes, intensity)
        midpoints = laplacian4_midpoints(codes, exact_decimal(intensity))
        oracle = model.copy()
        flip = midpoints & (np.arange(model.size).reshape(model.shape) % 3 == 0)
        assert flip.any()
        oracle[flip] = np.where(oracle[flip] > 0, oracle[flip] - 1, 1)
        for entries in ([entry], register):
            verdict = evaluate(comparison(content, oracle, stored(model), intensity), entries)
            assert verdict.outcome is Outcome.PASS, (intensity, verdict.reason)
            assert verdict.exceptions_relied_on == (("EXC-015", 1),)
        exact = evaluate(comparison(content, model, stored(model), intensity), [entry])
        assert exact.outcome is Outcome.PASS and exact.exceptions_relied_on == ()


def test_exc015_catches_injected_defects() -> None:
    """EXC-015's defect test (decision 428 §2): each injected defect fails and relies on nothing,
    against EXC-015 alone and against the published register."""
    entry = exc015()
    codes = codes_of(11)
    content = stored(codes)
    intensity = 0.25
    model = sharpen_codes(codes, intensity)
    exact_value = exact_decimal(intensity)
    midpoints = laplacian4_midpoints(codes, exact_value)
    lap = laplacian(codes)
    k_plus = codes * 4 + lap  # 4 (k + 0.25 L)
    inside = (k_plus > 4) & (k_plus < 4 * 65535 - 4)
    candidate = stored(model)

    def shifted(where: tuple[int, int], by: int, base: np.ndarray[Any, Any] = model) -> Any:
        out = base.copy()
        out[where] = out[where] + by if out[where] + by <= 65535 else out[where] - by
        return out

    defects: dict[str, Comparison] = {}
    at_midpoint = first(midpoints)
    defects["two_code_error_at_a_midpoint"] = comparison(
        content, shifted(at_midpoint, 2), candidate, intensity
    )
    off = first(~midpoints & inside & (lap % 4 == 0))
    defects["one_code_error_off_a_midpoint"] = comparison(
        content, shifted(off, 1), candidate, intensity
    )
    # A detector that takes any fractional intensity x L for a midpoint (0.25 or 0.75 too).
    wrong_detector = (lap % 4 != 0) & ~midpoints & inside
    defects["wrong_midpoint_detection"] = comparison(
        content, shifted(first(wrong_detector), 1), candidate, intensity
    )
    defects["wrong_wrap"] = comparison(
        content, model, stored(unwrapped_sharpen(codes, intensity)), intensity
    )
    defects["wrong_clamp"] = comparison(content, model, stored(np.clip(model, 0, 65534)), intensity)
    assert (model == 65535).any()
    clamped_half = (lap % 4 == 2) & ((k_plus < 0) | (k_plus > 4 * 65535))
    defects["one_code_error_on_a_half_integer_the_clamp_decides"] = comparison(
        content, shifted(first(clamped_half), 1), candidate, intensity
    )
    for exact in EXACT:
        exact_model = sharpen_codes(codes, exact)
        assert not laplacian4_midpoints(codes, exact_decimal(exact)).any()
        name = f"one_code_change_at_exact_intensity_{exact:g}"
        defects[name] = comparison(
            content, shifted((5, 9), 1, exact_model), stored(exact_model), exact
        )
    outside = 0.5
    outside_model = sharpen_codes(codes, outside)
    outside_mid = laplacian4_midpoints(codes, exact_decimal(outside))
    defects["intensity_outside_the_set"] = comparison(
        content, shifted(first(outside_mid), 1, outside_model), stored(outside_model), outside
    )
    tie = shifted(at_midpoint, 1)
    defects["filter_in_a_mask_stack"] = comparison(content, tie, candidate, intensity, stack="mask")
    off_grid = content.copy()
    off_grid[0, 0] = np.nextafter(off_grid[0, 0], np.float32(1))
    defects["content_off_the_16_bit_code_grid"] = comparison(off_grid, tie, candidate, intensity)
    halfway = candidate.copy()
    halfway[at_midpoint] = np.float32((int(model[at_midpoint]) + 0.5) / 65535)
    defects["candidate_value_off_the_code_grid"] = comparison(content, model, halfway, intensity)
    diagnostic = "phase3/proc-filters/diagnostic-mixed-rounded-cube-1024"
    defects["golden_outside_the_batch"] = comparison(
        content, tie, candidate, intensity, golden=diagnostic
    )
    assert set(defects) == set(entry["defect_detection_test"]["injected_defects"])
    register: list[dict[str, Any]] = load_json(REGISTER_PATH)["entries"]
    for name, compared in defects.items():
        for entries in ([entry], register):
            verdict = evaluate(compared, entries)
            assert verdict.outcome is Outcome.FAIL, name
            assert verdict.exceptions_relied_on == (), name
    # The same one-code tie at a midpoint passes: each defect fails for its defect alone.
    assert evaluate(comparison(content, tie, candidate, intensity), [entry]).outcome is Outcome.PASS
    assert entry["defect_detection_test"]["outcome"] == "every_injected_defect_fails"


def test_content_codes_refuse_values_off_the_grid() -> None:
    codes = codes_of(5)
    assert np.array_equal(content_codes(stored(codes)), codes)
