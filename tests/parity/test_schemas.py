"""Schema, separation and register tests of the parity contract (phase0.2_parity-contract §3)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.parity.schemas import (
    REGISTER_PATH,
    SCHEMA_DIR,
    Schema,
    is_valid,
    load_json,
    load_schema,
    record_problems,
    register_problems,
    validation_errors,
)
from tools.sources.check import INDEX_PATH
from tools.sources.index import load_index

SAMPLES = SCHEMA_DIR / "samples"
PUBLIC_SAMPLES = sorted((SAMPLES / "public").glob("*.json"))
PRIVATE_SAMPLES = sorted((SAMPLES / "private").glob("*.json"))
EXCEPTION_SAMPLES = sorted((SAMPLES / "exceptions").glob("*.json"))
REPORT_SAMPLES = sorted((SAMPLES / "reports").glob("*.json"))
REPO_ROOT = SCHEMA_DIR.parents[1]


def ids(paths: list[Path]) -> list[str]:
    return [p.stem for p in paths]


def register_of(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"schema": "uzpainter/parity/exceptions/1", "entries": list(entries)}


def output_kinds(record: dict[str, Any]) -> set[str]:
    return {o["kind"] for rec in record["recordings"] for o in rec["outputs"]}


# --- schemas ---------------------------------------------------------------------------------


@pytest.mark.parametrize("schema", list(Schema))
def test_schema_is_valid_draft_2020_12(schema: Schema) -> None:
    document = load_schema(schema)
    assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_sample_sets_are_present() -> None:
    assert len(PUBLIC_SAMPLES) >= 3
    kinds = set().union(*(output_kinds(load_json(p)) for p in PRIVATE_SAMPLES))
    assert {
        "exported_map",
        "api_readback",
        "effective_default_capture",
        "template_capture",
        "iray_reference",
        "operator_recorded_settings",
        "settings_panel_evidence",
    } <= kinds
    assert EXCEPTION_SAMPLES and REPORT_SAMPLES


# --- 3.1 every sample validates against its schema -------------------------------------------


@pytest.mark.parametrize("path", PUBLIC_SAMPLES, ids=ids(PUBLIC_SAMPLES))
def test_public_sample_validates(path: Path) -> None:
    assert validation_errors(load_json(path), Schema.GOLDEN_PUBLIC) == []


@pytest.mark.parametrize("path", PRIVATE_SAMPLES, ids=ids(PRIVATE_SAMPLES))
def test_private_sample_validates(path: Path) -> None:
    assert validation_errors(load_json(path), Schema.GOLDEN_PRIVATE) == []
    assert record_problems(load_json(path)) == []


@pytest.mark.parametrize("path", REPORT_SAMPLES, ids=ids(REPORT_SAMPLES))
def test_report_sample_validates(path: Path) -> None:
    assert validation_errors(load_json(path), Schema.COMPARISON_REPORT) == []


def test_public_expectations_cite_approved_public_documentation() -> None:
    index = load_index(REPO_ROOT / INDEX_PATH)
    approved = {e.entry_id: e for e in index.approved()}
    cited = [x["source_id"] for p in PUBLIC_SAMPLES for x in load_json(p)["expectations"]]
    assert cited
    for source_id in cited:
        assert source_id in approved, source_id


def test_public_schema_rejects_black_box_observation_as_a_source() -> None:
    manifest = load_json(SAMPLES / "public" / "tier0-blend-multiply.json")
    manifest["expectations"][0]["source_id"] = "A-OBSERVE"
    assert not is_valid(manifest, Schema.GOLDEN_PUBLIC)


def test_private_record_needs_two_recordings() -> None:
    record = load_json(SAMPLES / "private" / "exported-map-record.json")
    record["recordings"] = record["recordings"][:1]
    assert not is_valid(record, Schema.GOLDEN_PRIVATE)


def test_private_texture_record_needs_a_save_reopen_recording() -> None:
    record = load_json(SAMPLES / "private" / "exported-map-record.json")
    for recording in record["recordings"]:
        recording["condition"] = "same_session"
    assert not is_valid(record, Schema.GOLDEN_PRIVATE)


def test_private_iray_record_needs_two_sessions_and_a_k_times_recording() -> None:
    record = load_json(SAMPLES / "private" / "iray-reference-record.json")
    one_session = copy.deepcopy(record)
    one_session["recordings"] = [r for r in record["recordings"] if r["recording_id"] != "s2"]
    assert not is_valid(one_session, Schema.GOLDEN_PRIVATE)
    no_k = copy.deepcopy(record)
    no_k["recordings"] = [r for r in record["recordings"] if r["condition"] != "k_times_samples"]
    assert not is_valid(no_k, Schema.GOLDEN_PRIVATE)


def test_private_iray_reference_must_be_converged() -> None:
    record = load_json(SAMPLES / "private" / "iray-reference-record.json")
    record["recordings"][0]["outputs"][0]["convergence"]["status"] = "Rendering"
    assert not is_valid(record, Schema.GOLDEN_PRIVATE)


def iray_record() -> dict[str, Any]:
    record: dict[str, Any] = load_json(SAMPLES / "private" / "iray-reference-record.json")
    return record


def _set(path: tuple[Any, ...], value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(record: dict[str, Any]) -> None:
        target: Any = record
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


REFERENCE = ("recordings", 0, "outputs", 0)


@pytest.mark.parametrize(
    ("expected", "mutate"),
    [
        ("iterations", _set((*REFERENCE, "convergence", "iterations"), 7)),
        ("Max Time", _set((*REFERENCE, "convergence", "rendering_time_s"), 3600)),
        ("share a session_id", _set(("recordings", 1, "session_id"), "synthetic-session-1")),
        ("not k*256", _set(("recordings", 2, "outputs", 0, "samples"), 256)),
        ("disagree on S", _set(("recordings", 1, "outputs", 0, "samples"), 128)),
        ("operator settings", _set((*REFERENCE, "operator_settings_output_id"), "none")),
        ("not an ISO 8601", _set(("recordings", 0, "recorded_at"), "not a date")),
        ("no UTC offset", _set(("recordings", 0, "recorded_at"), "2026-10-10T12:00:00")),
    ],
)
def test_record_problems_catch_unconverged_or_mislabelled_references(
    expected: str, mutate: Callable[[dict[str, Any]], None]
) -> None:
    record = iray_record()
    mutate(record)
    problems = record_problems(record)
    assert any(expected in p for p in problems), problems


def test_storage_format_requires_the_measured_encoding() -> None:
    record = load_json(SAMPLES / "private" / "exported-map-record.json")
    del record["recordings"][0]["outputs"][0]["storage_format"]["encoding"]
    assert not is_valid(record, Schema.GOLDEN_PRIVATE)


# --- 3.2 no private-shaped record validates against the public schema ------------------------


@pytest.mark.parametrize("path", PRIVATE_SAMPLES, ids=ids(PRIVATE_SAMPLES))
def test_private_sample_is_rejected_by_public_schema(path: Path) -> None:
    assert not is_valid(load_json(path), Schema.GOLDEN_PUBLIC)


@pytest.mark.parametrize("path", PRIVATE_SAMPLES, ids=ids(PRIVATE_SAMPLES))
def test_relabelled_private_sample_is_still_rejected(path: Path) -> None:
    """A re-serialised record claiming the public class still fails on its content."""
    record = load_json(path)
    record["schema"] = "uzpainter/parity/golden-public/1"
    record["record_class"] = "public_manifest"
    assert not is_valid(record, Schema.GOLDEN_PUBLIC)


@pytest.mark.parametrize("path", PRIVATE_SAMPLES, ids=ids(PRIVATE_SAMPLES))
def test_recorded_outputs_do_not_fit_any_public_slot(path: Path) -> None:
    """Each recorded output, grafted into a valid public manifest, is rejected."""
    base = load_json(SAMPLES / "public" / "tier0-blend-multiply.json")
    record = load_json(path)
    outputs = [o for rec in record["recordings"] for o in rec["outputs"]]
    for payload in [*outputs, record]:
        for slot in ("inputs", "applied_settings", "expectations", "private_records"):
            manifest = copy.deepcopy(base)
            manifest[slot].append(payload)
            assert not is_valid(manifest, Schema.GOLDEN_PUBLIC), slot
        for name, put in graft_points(payload):
            manifest = copy.deepcopy(base)
            put(manifest)
            assert not is_valid(manifest, Schema.GOLDEN_PUBLIC), name


def graft_points(payload: Any) -> list[tuple[str, Callable[[dict[str, Any]], None]]]:
    def args(m: dict[str, Any]) -> None:
        m["instruction_sequence"]["steps"][0]["args"]["x"] = payload

    def setting(m: dict[str, Any]) -> None:
        m["applied_settings"][0]["value"] = payload

    def expectation(m: dict[str, Any]) -> None:
        m["expectations"][0]["value"] = payload

    def expectation_list(m: dict[str, Any]) -> None:
        m["expectations"][0]["value"] = [payload]

    def description(m: dict[str, Any]) -> None:
        m["description"] = payload

    def outputs(m: dict[str, Any]) -> None:
        m["outputs"] = [payload]

    return [
        ("args", args),
        ("setting", setting),
        ("expectation", expectation),
        ("expectation_list", expectation_list),
        ("description", description),
        ("outputs", outputs),
    ]


def test_public_scalars_cannot_carry_a_serialized_blob() -> None:
    base = load_json(SAMPLES / "public" / "tier0-blend-multiply.json")
    for name, put in graft_points("A" * 4096):
        manifest = copy.deepcopy(base)
        put(manifest)
        assert not is_valid(manifest, Schema.GOLDEN_PUBLIC), name


def test_public_manifest_is_rejected_by_private_schema() -> None:
    for path in PUBLIC_SAMPLES:
        assert not is_valid(load_json(path), Schema.GOLDEN_PRIVATE)


# --- 3.3 register ----------------------------------------------------------------------------


def test_published_register_is_valid() -> None:
    assert register_problems(load_json(REGISTER_PATH)) == []


@pytest.mark.parametrize("path", EXCEPTION_SAMPLES, ids=ids(EXCEPTION_SAMPLES))
def test_sample_exception_entry_validates(path: Path) -> None:
    assert validation_errors(register_of(load_json(path)), Schema.EXCEPTIONS) == []


@pytest.mark.parametrize("path", EXCEPTION_SAMPLES, ids=ids(EXCEPTION_SAMPLES))
@pytest.mark.parametrize(
    "missing", ["evidence", "defect_detection_test", "decision_id", "bounds", "version", "domain"]
)
def test_incomplete_exception_entry_is_rejected(path: Path, missing: str) -> None:
    entry = load_json(path)
    del entry[missing]
    assert not is_valid(register_of(entry), Schema.EXCEPTIONS)


@pytest.mark.parametrize("path", EXCEPTION_SAMPLES, ids=ids(EXCEPTION_SAMPLES))
def test_exception_without_private_evidence_or_uncontrolled_list_is_rejected(path: Path) -> None:
    for field in ("private_evidence", "uncontrolled_settings"):
        entry = load_json(path)
        del entry["evidence"][field]
        assert not is_valid(register_of(entry), Schema.EXCEPTIONS), field
    entry = load_json(path)
    entry["evidence"]["private_evidence"] = []
    assert not is_valid(register_of(entry), Schema.EXCEPTIONS)


def test_tier3_entry_needs_noise_floor_and_render_defect_injections() -> None:
    base = load_json(SAMPLES / "exceptions" / "tier3-render-entry.json")
    no_floor = copy.deepcopy(base)
    del no_floor["evidence"]["noise_floor"]
    assert not is_valid(register_of(no_floor), Schema.EXCEPTIONS)
    explained_only = copy.deepcopy(base)
    explained_only["evidence"]["basis"] = "irreducible_difference"
    assert not is_valid(register_of(explained_only), Schema.EXCEPTIONS)
    for defect in base["defect_detection_test"]["injected_defects"]:
        partial = copy.deepcopy(base)
        partial["defect_detection_test"]["injected_defects"].remove(defect)
        assert not is_valid(register_of(partial), Schema.EXCEPTIONS), defect


def test_tier3_entry_never_covers_a_texture_domain_or_a_structural_check() -> None:
    base = load_json(SAMPLES / "exceptions" / "tier3-render-entry.json")
    texture = copy.deepcopy(base)
    texture["domain"]["kind"] = "asset_map"
    assert not is_valid(register_of(texture), Schema.EXCEPTIONS)
    structural = copy.deepcopy(base)
    structural["bounds"].append({"metric": "id_label_differing_count", "scope": "whole", "max": 1})
    assert not is_valid(register_of(structural), Schema.EXCEPTIONS)


def test_noise_floor_keys_are_metrics_and_downsampling_is_tier3_only() -> None:
    render = load_json(SAMPLES / "exceptions" / "tier3-render-entry.json")
    render["evidence"]["noise_floor"] = {"not_a_metric": 0.1}
    assert not is_valid(register_of(render), Schema.EXCEPTIONS)
    bake = load_json(SAMPLES / "exceptions" / "tier2b-bake-entry.json")
    bake["bounds"].append({"metric": "p99_abs_diff_down2", "scope": "whole", "max": 1})
    assert not is_valid(register_of(bake), Schema.EXCEPTIONS)
    render = load_json(SAMPLES / "exceptions" / "tier3-render-entry.json")
    render["bounds"].append({"metric": "p99_abs_diff_down2", "scope": "each_region", "max": 0.01})
    assert is_valid(register_of(render), Schema.EXCEPTIONS)


def test_register_rejects_duplicates_and_unrecorded_decisions(tmp_path: Path) -> None:
    entry = load_json(SAMPLES / "exceptions" / "tier2b-bake-entry.json")
    problems = register_problems(register_of(entry, entry), decisions_dir=tmp_path)
    assert any("duplicate EXC-001 version 1" in p for p in problems)
    assert any("decision 999 is not recorded" in p for p in problems)
    (tmp_path / "999-sample-decision.md").write_text("# sample\n", encoding="utf-8")
    assert register_problems(register_of(entry), decisions_dir=tmp_path) == []


# --- comparison report: the comparison-tool specification in machine form -------------------


def report() -> dict[str, Any]:
    document: dict[str, Any] = load_json(SAMPLES / "reports" / "tier0-exact-pass.json")
    return document


@pytest.mark.parametrize("field", ["max", "p99"])
def test_mean_is_never_reported_without_max_and_percentile(field: str) -> None:
    document = report()
    del document["equality_to_painter"]["maps"][0]["abs_diff"][field]
    assert not is_valid(document, Schema.COMPARISON_REPORT)


@pytest.mark.parametrize("field", ["count", "percent"])
def test_statistics_are_never_reported_without_the_differing_count(field: str) -> None:
    document = report()
    del document["equality_to_painter"]["maps"][0]["differing"][field]
    assert not is_valid(document, Schema.COMPARISON_REPORT)
    region = report()
    del region["equality_to_painter"]["maps"][0]["regions"][0]["differing"]
    assert not is_valid(region, Schema.COMPARISON_REPORT)


def test_report_pass_with_a_difference_needs_an_exception() -> None:
    document = report()
    m = document["equality_to_painter"]["maps"][0]
    m["abs_diff"] = {"max": 1, "mean": 1 / 65536, "p99": 0}
    m["differing"] = {"count": 1, "percent": 100 / 65536, "total": 65536}
    assert not is_valid(document, Schema.COMPARISON_REPORT)
    document["equality_to_painter"]["outcome"] = "fail"
    assert is_valid(document, Schema.COMPARISON_REPORT)


def test_report_tier3_pass_needs_an_exception_even_when_equal() -> None:
    document = report()
    document["tier"] = "3"
    assert not is_valid(document, Schema.COMPARISON_REPORT)


def test_report_oracle_unavailable_is_not_a_pass() -> None:
    document = report()
    document["oracle_stability"] = {"status": "oracle_unavailable", "maps": []}
    assert not is_valid(document, Schema.COMPARISON_REPORT)
    document["equality_to_painter"]["outcome"] = "oracle_unavailable"
    assert not is_valid(document, Schema.COMPARISON_REPORT)
    document["equality_to_painter"]["maps"] = []
    assert is_valid(document, Schema.COMPARISON_REPORT)


def test_report_flip_value_needs_the_pinned_tool() -> None:
    document = report()
    del document["flip_tool"]
    assert not is_valid(document, Schema.COMPARISON_REPORT)


def test_report_pass_ignores_no_region_or_exact_check_difference() -> None:
    document = report()
    document["equality_to_painter"]["maps"][0]["regions"][0]["differing"]["count"] = 5
    assert not is_valid(document, Schema.COMPARISON_REPORT)
    document = report()
    document["equality_to_painter"]["maps"][0]["exact_checks"] = [
        {"check": "alpha", "equal": False, "differing_count": 1, "edge_coverage_differing_count": 0}
    ]
    assert not is_valid(document, Schema.COMPARISON_REPORT)


def test_report_unstable_oracle_never_passes_without_an_exception() -> None:
    document = report()
    document["oracle_stability"]["status"] = "unstable"
    assert not is_valid(document, Schema.COMPARISON_REPORT)
    document["equality_to_painter"]["outcome"] = "blocked"
    assert is_valid(document, Schema.COMPARISON_REPORT)


def test_report_tier3_evidence_never_comes_from_warp() -> None:
    document = report()
    document["tier"] = "3"
    document["equality_to_painter"]["outcome"] = "blocked"
    assert is_valid(document, Schema.COMPARISON_REPORT)
    document["run"]["backend"] = "warp"
    assert not is_valid(document, Schema.COMPARISON_REPORT)


@pytest.mark.parametrize("result", ["oracle_stability", "uzpainter_repeatability"])
def test_report_flip_anywhere_needs_the_pinned_tool(result: str) -> None:
    document = report()
    del document["flip_tool"]
    del document["equality_to_painter"]["maps"][0]["flip_mean"]
    assert is_valid(document, Schema.COMPARISON_REPORT)
    document[result]["maps"][0]["flip_mean"] = 0.0
    assert not is_valid(document, Schema.COMPARISON_REPORT)
