"""The Tier 1 comparison step and its guard on synthetic data (phase1.25 items 2.5, 3.4, 3.5).

Every "recorded" map here is a 4x4 stand-in this test encodes itself and stores in a temporary
private store; nothing comes from Painter, no golden is invented in the repository and nothing
here claims parity. The scenarios: exact equality, a divergence with its diagnostics, an unstable
oracle, a missing oracle (`oracle_unavailable`), structural differences, a stale golden, and the
repository guard on the Wand v1 request and a report.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.adapters.assets3d.wand import Call
from tests.parity.tier1.wand_v1.runner import refusal
from tools.parity.envelope.registry import current_envelope
from tools.parity.feasibility import png
from tools.parity.guard.guard import Snapshot, run_guard
from tools.parity.schemas import REPO_ROOT, Schema, is_valid, load_json, validation_errors
from tools.parity.store.store import OracleStore
from tools.parity.tier1.compare import (
    FLIP_VERSION,
    FLIP_WHEEL_SHA256,
    CandidateRun,
    RunIdentity,
    Subject,
    compare,
    file_storage_format,
    flip_available,
    material_regions,
    write_report,
)
from tools.parity.verdict import ResolvedGolden

SET = "Wand"
BASE, ROUGH, NORMAL = "W_BaseColor", "W_Roughness", "W_Normal"
WAND_REQUEST = "parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/phase1/tier1/wand-v1.json"
REPORT_PATH = "parity/reports/phase1/tier1-wand-v1.json"
IDENTITY = RunIdentity("synthetic adapter", "0.0", "dx12", "0" * 64, ("1" * 64,))
LEFT = np.zeros((4, 4), np.bool_)
LEFT[:, :2] = True
REGIONS = {"M_left": LEFT, "M_right": ~LEFT}
MANIFEST: dict[str, Any] = {
    "golden_id": "phase1/tier1/synthetic",
    "tier": "1",
    "domain": "tier1/pilot/synthetic",
    "inputs": [],
    "instruction_sequence": {"interface": "synthetic"},
    "applied_settings": [],
    "software": {"painter": {"build_id": "12.1.5+js-api.1.1.20"}},
}


def maps() -> dict[str, np.ndarray]:
    """The stand-in exports: RGB colour, a grey channel and a +Z normal map, 16-bit codes."""
    codes = np.arange(48, dtype=np.uint16).reshape(4, 4, 3) * 1000
    normal = np.empty((4, 4, 3), np.uint16)
    normal[...] = (32768, 32768, 65535)
    return {BASE: codes, ROUGH: codes[..., :1] + 7, NORMAL: normal}


def write_maps(directory: Path, values: dict[str, np.ndarray], depth: int = 16) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, array in values.items():
        paths[name] = directory / f"{name}.png"
        png.write(paths[name], array, depth)
    return paths


def candidate(directory: Path, values: dict[str, np.ndarray], depth: int = 16) -> CandidateRun:
    files = write_maps(directory, values, depth)
    return CandidateRun({(SET, name): path for name, path in files.items()})


def put(store: OracleStore, path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    store.put_blob(path, sha)
    return {"sha256": sha, "size_bytes": len(data)}


def golden(
    tmp: Path,
    recordings: dict[str, dict[str, np.ndarray]],
    *,
    stored: bool = True,
    skip_blob_of: str | None = None,
    envelope_id: str | None = None,
) -> tuple[ResolvedGolden, OracleStore]:
    """A golden of `recordings` (id -> maps) in a temporary store, and its resolution."""
    store = OracleStore.init(tmp / "store")
    record: dict[str, Any] = {"recordings": []}
    for recording_id, values in recordings.items():
        outputs = []
        for name, path in write_maps(tmp / "oracle" / recording_id, values).items():
            blob = (
                {"sha256": "e" * 64, "size_bytes": 1}  # named by the record, never stored
                if skip_blob_of == recording_id
                else put(store, path)
            )
            outputs.append(
                {
                    "output_id": f"export/{name}",
                    "kind": "exported_map",
                    "texture_set": SET,
                    "map": name,
                    "blob": blob,
                    "storage_format": file_storage_format(path),
                }
            )
        record["recordings"].append(
            {"recording_id": recording_id, "condition": "same_session", "outputs": outputs}
        )
    record_file = tmp / "record.json"
    record_file.write_text(json.dumps(record), encoding="utf-8")
    ref = {"record_id": "golden-record", **put(store, record_file)}
    if not stored:
        ref["sha256"] = "f" * 64
    manifest = {**MANIFEST, "private_records": [ref]}
    path = tmp / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    current = str(current_envelope()["envelope_id"])
    envelope = envelope_id or current
    resolved = ResolvedGolden(MANIFEST["golden_id"], path, manifest, envelope, envelope != current)
    return resolved, store


def subject() -> Subject:
    return Subject(MANIFEST, "2" * 64, REGIONS, frozenset({NORMAL}))


def stable_golden(tmp: Path, **options: Any) -> tuple[ResolvedGolden, OracleStore]:
    return golden(tmp, {"r1": maps(), "r1-repeat": maps(), "r2": maps()}, **options)


def report_of(
    resolved: ResolvedGolden | None, store: OracleStore | None, runs: tuple[CandidateRun, ...]
) -> dict[str, Any]:
    report = compare(subject(), resolved, store, runs, IDENTITY, [])
    assert validation_errors(report, Schema.COMPARISON_REPORT) == []
    return report


def by_id(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {e["output_id"]: e for e in entries}


# --- equality -----------------------------------------------------------------------------------


def test_rebuilds_equal_to_a_stable_golden_pass_and_are_repeatable(tmp_path: Path) -> None:
    resolved, store = stable_golden(tmp_path)
    runs = (candidate(tmp_path / "a", maps()), candidate(tmp_path / "b", maps()))
    report = report_of(resolved, store, runs)
    equality = report["equality_to_painter"]
    assert (equality["outcome"], equality["structural"], equality["exceptions_relied_on"]) == (
        "pass",
        [],
        [],
    )
    assert report["oracle_stability"]["status"] == "stable"
    assert len(report["oracle_stability"]["maps"]) == 6  # 3 maps x (r1-repeat, r2)
    assert report["uzpainter_repeatability"]["status"] == "repeatable"
    entries = by_id(equality["maps"])
    assert sorted(entries) == [f"{SET}/{n}" for n in sorted((BASE, NORMAL, ROUGH))]
    base = entries[f"{SET}/{BASE}"]
    assert base["storage_format"] == {
        "container": "png",
        "sample_type": "uint",
        "bits_per_channel": 16,
        "channels": 3,
        "encoding": "undetermined",
    }
    assert base["differing"] == {"count": 0, "percent": 0.0, "total": 48}
    assert [r["region"] for r in base["regions"]] == ["M_left", "M_right"]
    assert entries[f"{SET}/{NORMAL}"]["normal"] == {
        "angular_max_deg": 0.0,
        "angular_mean_deg": 0.0,
        "non_finite_count": 0,
        "unnormalised_count": 0,
    }
    assert all("private_difference_map_sha256" not in e for e in entries.values())


# --- divergence ---------------------------------------------------------------------------------


def test_a_divergent_rebuild_fails_with_whole_region_and_normal_diagnostics(
    tmp_path: Path,
) -> None:
    resolved, store = stable_golden(tmp_path)
    changed = maps()
    changed[BASE][1, 3, 2] += 3  # one value, in the right region
    changed[NORMAL][0, 0] = (65535, 32768, 32768)  # +X instead of +Z: 90 degrees
    changed[NORMAL][0, 1] = (32768, 32768, 32768)  # length 1/65535: unnormalised
    runs = (candidate(tmp_path / "a", changed), candidate(tmp_path / "b", maps()))
    report = report_of(resolved, store, runs)
    equality = report["equality_to_painter"]
    assert equality["outcome"] == "fail" and equality["structural"] == []
    assert report["uzpainter_repeatability"]["status"] == "not_repeatable"
    entries = by_id(equality["maps"])
    base = entries[f"{SET}/{BASE}"]
    assert base["abs_diff"] == {"max": 3, "mean": 3 / 48, "p99": 3}  # nearest rank 48 of 48
    assert base["differing"]["count"] == 1
    regions = {r["region"]: r["differing"]["count"] for r in base["regions"]}
    assert regions == {"M_left": 0, "M_right": 1}
    difference = base["private_difference_map_sha256"]
    assert difference in store.index()  # the |Δ| image lives in the private store only
    assert png.decode(store.load(difference) or b"").max() == 3
    normal = entries[f"{SET}/{NORMAL}"]["normal"]
    assert normal["angular_max_deg"] == pytest.approx(90.0, abs=0.01)
    assert normal["unnormalised_count"] == 1 and normal["non_finite_count"] == 0
    assert "private_difference_map_sha256" not in entries[f"{SET}/{ROUGH}"]


# --- padding (decision 223) ---------------------------------------------------------------------

# One UV triangle pair covering the 2 x 2 texels at the tile's centre of the 4 x 4 maps.
ISLAND = np.array(
    [[[0.25, 0.25], [0.75, 0.25], [0.75, 0.75]], [[0.25, 0.25], [0.75, 0.75], [0.25, 0.75]]]
)


def scope_split(domain: str, version: int = 1) -> dict[str, Any]:
    """A version of EXC-007 over the synthetic golden's domain: 1 the terms of decision 223, 2 their
    withdrawal (decision 259)."""
    entries = load_json(REPO_ROOT / "parity" / "exceptions.json")["entries"]
    (entry,) = [e for e in entries if e["exception_id"] == "EXC-007" and e["version"] == version]
    return {**entry, "domain": {**entry["domain"], "selector": domain}}


def test_padding_texels_are_excepted_and_published_while_covered_texels_stay_exact(
    tmp_path: Path,
) -> None:
    """A subject with UV triangles: each map's padding block splits it by coverage. A padding
    difference passes under the owner scope split and shows in the published padding residuals;
    one covered value off by one code fails under the same entry. With the entry withdrawn
    (decision 259), the padding difference fails and is still published."""
    resolved, store = stable_golden(tmp_path)
    island = Subject(MANIFEST, "2" * 64, REGIONS, frozenset({NORMAL}), {SET: ISLAND})
    entry = scope_split(MANIFEST["domain"])
    padded = maps()
    padded[BASE][0, 0] += 900  # a padding texel, one texel from the island (diagonal)
    runs = (candidate(tmp_path / "a", padded), candidate(tmp_path / "b", padded))
    report = compare(island, resolved, store, runs, IDENTITY, [entry])
    assert validation_errors(report, Schema.COMPARISON_REPORT) == []
    equality = report["equality_to_painter"]
    assert equality["outcome"] == "pass"
    assert equality["exceptions_relied_on"] == [{"exception_id": "EXC-007", "version": 1}]
    base = by_id(equality["maps"])[f"{SET}/{BASE}"]
    padding = base["padding"]
    assert (padding["covered_texels"], padding["uncovered_texels"]) == (4, 12)
    assert padding["covered"]["differing"]["count"] == 0
    assert padding["uncovered"]["abs_diff"]["max"] == 900
    assert padding["uncovered"]["differing"] == {"count": 3, "percent": 100 * 3 / 36, "total": 36}
    assert [(b["within_texels"], b["texels"]) for b in padding["bands"]] == [
        (1, 12),
        (2, 12),
        (4, 12),
        (8, 12),
    ]
    assert padding["bands"][0]["abs_diff"]["max"] == 900
    rough = by_id(equality["maps"])[f"{SET}/{ROUGH}"]["padding"]
    assert rough["uncovered"]["differing"]["count"] == 0
    # The entry and its withdrawal: the padding difference fails, published the same way.
    withdrawn = [entry, scope_split(MANIFEST["domain"], 2)]
    report = compare(island, resolved, store, runs, IDENTITY, withdrawn)
    assert report["equality_to_painter"]["outcome"] == "fail"
    assert report["equality_to_painter"]["exceptions_relied_on"] == []
    base = by_id(report["equality_to_painter"]["maps"])[f"{SET}/{BASE}"]
    assert base["padding"]["uncovered"]["abs_diff"]["max"] == 900
    # The same entry, one covered value off by one code: a failure.
    covered = maps()
    covered[BASE][1, 1, 0] += 1
    runs = (candidate(tmp_path / "c", covered), candidate(tmp_path / "d", covered))
    report = compare(island, resolved, store, runs, IDENTITY, [entry])
    assert report["equality_to_painter"]["outcome"] == "fail"
    assert report["equality_to_painter"]["exceptions_relied_on"] == []
    base = by_id(report["equality_to_painter"]["maps"])[f"{SET}/{BASE}"]
    assert base["padding"]["covered"]["differing"]["count"] == 1
    # Without the subject's UV triangles there is no padding block and nothing is excepted.
    runs = (candidate(tmp_path / "e", padded), candidate(tmp_path / "f", padded))
    report = compare(subject(), resolved, store, runs, IDENTITY, [entry])
    assert report["equality_to_painter"]["outcome"] == "fail"
    assert all("padding" not in m for m in report["equality_to_painter"]["maps"])


def test_an_unstable_golden_without_an_entry_is_blocked(tmp_path: Path) -> None:
    moved = maps()
    moved[ROUGH][0, 0, 0] += 1
    resolved, store = golden(tmp_path, {"r1": maps(), "r1-repeat": maps(), "r2": moved})
    runs = (candidate(tmp_path / "a", maps()), candidate(tmp_path / "b", maps()))
    report = report_of(resolved, store, runs)
    assert report["oracle_stability"]["status"] == "unstable"
    unstable = by_id(report["oracle_stability"]["maps"])[f"{SET}/{ROUGH}@r2"]
    assert unstable["differing"]["count"] == 1
    assert report["equality_to_painter"]["outcome"] == "blocked"


@pytest.mark.parametrize("recording", ["r1-repeat", "r2"])
def test_a_map_only_another_recording_holds_makes_the_golden_unstable(
    tmp_path: Path, recording: str
) -> None:
    """r1 holds fewer maps than another recording: the oracle is unstable and the comparison is
    never a pass, though every map of r1 is equal everywhere and the rebuild equals r1."""
    extra = {**maps(), "W_Extra": maps()[NORMAL]}
    recordings = {"r1": maps(), "r1-repeat": maps(), "r2": maps()}
    recordings[recording] = extra
    resolved, store = golden(tmp_path, recordings)
    runs = (candidate(tmp_path / "a", maps()), candidate(tmp_path / "b", maps()))
    report = report_of(resolved, store, runs)
    assert report["oracle_stability"]["status"] == "unstable"
    assert report["equality_to_painter"]["outcome"] == "blocked"
    assert report["equality_to_painter"]["structural"] == []


@pytest.mark.skipif(not flip_available(), reason="flip-evaluator 1.7 is not installed")
def test_flip_is_reported_as_a_diagnostic_with_its_pinned_tool(tmp_path: Path) -> None:
    """Mean FLIP rides next to the numbers (0 for equal maps, above 0 for a divergence) and
    names the pinned tool; the outcome is the contract's alone."""
    resolved, store = stable_golden(tmp_path)
    changed = maps()
    changed[BASE][:, :, 0] = 65535
    runs = (candidate(tmp_path / "a", changed), candidate(tmp_path / "b", changed))
    report = report_of(resolved, store, runs)
    assert report["flip_tool"] == {"version": FLIP_VERSION, "sha256": FLIP_WHEEL_SHA256}
    entries = by_id(report["equality_to_painter"]["maps"])
    assert entries[f"{SET}/{BASE}"]["flip_mean"] > 0
    assert entries[f"{SET}/{ROUGH}"]["flip_mean"] == 0
    assert report["equality_to_painter"]["outcome"] == "fail"
    equal = report_of(resolved, store, (candidate(tmp_path / "c", maps()),) * 2)
    assert equal["equality_to_painter"]["outcome"] == "pass"
    assert all(m["flip_mean"] == 0 for m in equal["equality_to_painter"]["maps"])


@pytest.mark.parametrize(("bound", "outcome"), [(1.0, "pass"), (1e-4, "fail")])
def test_a_register_bound_on_the_normal_angle_judges_a_normal_map(
    tmp_path: Path, bound: float, outcome: str
) -> None:
    """The normal diagnostics reach the register under its metric names (`normal_*`): a one-code
    difference (about 0.0017 degrees) passes an entry bounding `normal_angular_max_deg` by 1 and
    fails one bounding it by 1e-4."""
    resolved, store = stable_golden(tmp_path)
    changed = maps()
    changed[NORMAL][2, 2, 0] += 1
    runs = (candidate(tmp_path / "a", changed), candidate(tmp_path / "b", changed))
    entry = load_json(REPO_ROOT / "parity/schema/samples/exceptions/tier2b-bake-entry.json")
    entry = {
        **entry,
        "tier": "1",
        "domain": {**entry["domain"], "selector": MANIFEST["domain"]},
        # The golden is stable: an oracle-instability entry never covers it (SUP-036).
        "evidence": {**entry["evidence"], "basis": "irreducible_difference"},
        "bounds": [{"metric": "normal_angular_max_deg", "scope": "whole", "max": bound}],
    }
    report = compare(subject(), resolved, store, runs, IDENTITY, [entry])
    assert validation_errors(report, Schema.COMPARISON_REPORT) == []
    equality = report["equality_to_painter"]
    angle = by_id(equality["maps"])[f"{SET}/{NORMAL}"]["normal"]["angular_max_deg"]
    assert 1e-4 < angle < 1.0
    assert equality["outcome"] == outcome
    relied = [{"exception_id": entry["exception_id"], "version": entry["version"]}]
    assert equality["exceptions_relied_on"] == (relied if outcome == "pass" else [])


# --- oracle_unavailable (3.4) -------------------------------------------------------------------


def test_a_golden_not_admitted_is_oracle_unavailable_and_compares_nothing(tmp_path: Path) -> None:
    runs = (candidate(tmp_path / "a", maps()), candidate(tmp_path / "b", maps()))
    report = report_of(None, None, runs)
    assert report["oracle_stability"] == {"status": "oracle_unavailable", "maps": []}
    assert report["equality_to_painter"] == {
        "outcome": "oracle_unavailable",
        "exceptions_relied_on": [],
        "maps": [],
        "structural": [],
    }
    assert report["uzpainter_repeatability"]["status"] == "repeatable"
    assert report["envelope_id"] == current_envelope()["envelope_id"]


@pytest.mark.parametrize("missing", ["record", "r2 blob", "no store"])
def test_a_missing_golden_blob_is_oracle_unavailable_never_a_pass(
    tmp_path: Path, missing: str
) -> None:
    """3.4: the rebuild equals r1 exactly, yet a missing record or blob (or no store) leaves the
    comparison `oracle_unavailable`."""
    resolved, store = stable_golden(
        tmp_path,
        stored=missing != "record",
        skip_blob_of="r2" if missing == "r2 blob" else None,
    )
    runs = (candidate(tmp_path / "a", maps()), candidate(tmp_path / "b", maps()))
    report = report_of(resolved, None if missing == "no store" else store, runs)
    assert report["equality_to_painter"]["outcome"] == "oracle_unavailable"
    assert report["equality_to_painter"]["maps"] == []
    assert report["oracle_stability"]["status"] == "oracle_unavailable"


# --- structural differences -------------------------------------------------------------------


def test_a_refused_export_fails_naming_the_refusal_once(tmp_path: Path) -> None:
    """Decision 255: a refused export wrote nothing and nothing is compared, so it is the one
    structural failure; its maps are not listed again as missing. An export that finished without
    writing a map still lists each map r1 holds as missing."""
    resolved, store = stable_golden(tmp_path)
    refused = CandidateRun(refused=True, refusal="export: ... (decision 245)")
    report = report_of(resolved, store, (refused, refused))
    equality = report["equality_to_painter"]
    assert equality == {
        "outcome": "fail",
        "exceptions_relied_on": [],
        "maps": [],
        "structural": [{"output_id": "export", "reason": "candidate_export_refused"}],
    }
    assert report["uzpainter_repeatability"] == {"status": "not_measured", "maps": []}
    assert report["oracle_stability"]["status"] == "stable"
    empty = report_of(resolved, store, (CandidateRun(), CandidateRun()))["equality_to_painter"]
    assert empty["outcome"] == "fail" and empty["maps"] == []
    assert empty["structural"] == [
        {"output_id": f"{SET}/{name}", "reason": "missing_from_candidate"}
        for name in sorted((BASE, NORMAL, ROUGH))
    ]
    unavailable = report_of(None, None, (refused, refused))["equality_to_painter"]
    assert unavailable["outcome"] == "oracle_unavailable"
    assert unavailable["structural"] == [
        {"output_id": "export", "reason": "candidate_export_refused"}
    ]


def test_storage_format_shape_and_unpaired_maps_are_structural_failures(tmp_path: Path) -> None:
    resolved, store = stable_golden(tmp_path)
    values = maps()
    eight = {BASE: (values.pop(BASE) // 257).astype(np.uint8)}  # same map, measured 8-bit
    values[ROUGH] = np.zeros((2, 2, 1), np.uint16)
    values["W_Extra"] = values[NORMAL]
    files = {**write_maps(tmp_path / "a", values), **write_maps(tmp_path / "a8", eight, depth=8)}
    run = CandidateRun({(SET, name): path for name, path in files.items()})
    equality = report_of(resolved, store, (run, run))["equality_to_painter"]
    assert equality["outcome"] == "fail"
    assert {(s["output_id"], s["reason"]) for s in equality["structural"]} == {
        (f"{SET}/W_Extra", "missing_from_oracle"),
        (f"{SET}/{BASE}", "storage_format_differs"),
        (f"{SET}/{ROUGH}", "shape_differs"),
    }
    assert [m["output_id"] for m in equality["maps"]] == [f"{SET}/{NORMAL}"]


def test_a_golden_of_another_envelope_is_stale(tmp_path: Path) -> None:
    resolved, store = stable_golden(tmp_path, envelope_id="painter-12.1.0+js-api.1.1.20")
    runs = (candidate(tmp_path / "a", maps()), candidate(tmp_path / "b", maps()))
    equality = report_of(resolved, store, runs)["equality_to_painter"]
    assert equality["outcome"] == "stale" and equality["exceptions_relied_on"] == []
    refused = CandidateRun(refused=True)
    equality = report_of(resolved, store, (refused, refused))["equality_to_painter"]
    assert equality["outcome"] == "stale" and equality["structural"][0]["reason"] == (
        "candidate_export_refused"
    )


def test_a_golden_recorded_from_another_job_is_refused(tmp_path: Path) -> None:
    resolved, store = stable_golden(tmp_path)
    other = Subject({**MANIFEST, "applied_settings": [{"name": "x"}]}, "2" * 64)
    with pytest.raises(ValueError, match="applied_settings"):
        compare(other, resolved, store, (CandidateRun(), CandidateRun()), IDENTITY, [])


def test_a_pass_never_lists_a_structural_difference_even_with_an_exception() -> None:
    sample = REPO_ROOT / "parity/schema/samples/reports/tier0-exact-pass.json"
    report = load_json(sample)
    assert is_valid(report, Schema.COMPARISON_REPORT)
    report["equality_to_painter"]["structural"] = [
        {"output_id": "missing-map", "reason": "missing_from_candidate"}
    ]
    assert not is_valid(report, Schema.COMPARISON_REPORT)
    report["equality_to_painter"]["exceptions_relied_on"] = [
        {"exception_id": "EXC-001", "version": 1}
    ]
    assert not is_valid(report, Schema.COMPARISON_REPORT)


def test_material_regions_are_the_stack_group_masks(tmp_path: Path) -> None:
    mask = np.zeros((4, 4), np.uint16)
    mask[0, 0] = 1
    png.write(tmp_path / "M_a.png", mask)
    stack = {"groups": [{"name": "a", "mask": "M_a"}, {"name": "b", "mask": None}], "layers": []}
    regions = material_regions(stack, tmp_path)
    assert list(regions) == ["M_a"] and int(regions["M_a"].sum()) == 1


# --- guard (3.5) --------------------------------------------------------------------------------


def wand_report(tmp_path: Path) -> dict[str, Any]:
    """The report of the admitted R9 manifest's job with no golden loaded and the export refused
    (phase1.25 items 2.6, 2.7)."""
    request = REPO_ROOT / WAND_REQUEST
    manifest = load_json(request)
    digest = hashlib.sha256(request.read_bytes()).hexdigest()
    refused = CandidateRun(refused=True)
    report = compare(Subject(manifest, digest), None, None, (refused, refused), IDENTITY, [])
    write_report(report, tmp_path / "tier1-wand-v1.json")
    return report


def guard(files: dict[str, bytes], index: frozenset[str] | None) -> set[tuple[str, str]]:
    snapshot = Snapshot(tuple(sorted(files)), tuple(sorted(files)), files.__getitem__)
    return {(f.path, f.rule) for f in run_guard(REPO_ROOT, snapshot, index)}


def test_the_guard_passes_the_wand_request_and_its_report(tmp_path: Path) -> None:
    report = wand_report(tmp_path)
    assert report["equality_to_painter"]["outcome"] == "oracle_unavailable"
    files = {
        WAND_REQUEST: (REPO_ROOT / WAND_REQUEST).read_bytes(),
        REPORT_PATH: (tmp_path / "tier1-wand-v1.json").read_bytes(),
    }
    assert guard(files, frozenset()) == set()


def test_the_guard_rejects_a_planted_golden_and_an_invalid_report(tmp_path: Path) -> None:
    """A recorded golden blob copied into the repository (as a map or under the report's name)
    matches the store index; a report that breaks its schema fails the public schema."""
    _, store = stable_golden(tmp_path)
    recorded = store.load(load_json(tmp_path / "manifest.json")["private_records"][0]["sha256"])
    blob = (tmp_path / "oracle" / "r1" / f"{BASE}.png").read_bytes()
    assert recorded is not None
    report = wand_report(tmp_path)
    report["equality_to_painter"]["outcome"] = "pass"
    files = {
        "parity/reports/phase1/W_BaseColor.png": blob,
        "tests/parity/tier1/planted.png": blob,
        REPORT_PATH: recorded,
        "parity/reports/phase1/tier1-other.json": json.dumps(report).encode("utf-8"),
    }
    found = guard(files, frozenset(store.index()))
    assert ("parity/reports/phase1/W_BaseColor.png", "store-hash") in found
    assert ("tests/parity/tier1/planted.png", "store-hash") in found
    assert (REPORT_PATH, "store-hash") in found
    assert ("parity/reports/phase1/tier1-other.json", "public-schema") in found


# --- the runner's refusal message (decision 255) ------------------------------------------------


@pytest.mark.parametrize("cut", [False, True])
def test_the_refusal_message_is_read_from_a_whole_or_cut_reply(cut: bool) -> None:
    """The pinned `painter_layer_stack.py` raises with the client's reply cut to its last 3000
    characters (`text[-3000:]`), so a long reply is not JSON; the message is then the last line
    of its traceback, unescaped."""
    message = 'export: W map "W_Normal" (W_Normal.png): ... (owner X; decision 245)'
    traceback = "Traceback (most recent call last):\n" + "  File ...\n" * 400
    reply = json.dumps(
        {
            "success": False,
            "error": {
                "message": message,
                "traceback": f"{traceback}uzpainter.exception.NotYetSupported: {message}\n",
                "type": "NotYetSupported",
            },
            "session": {"project": "C:/work/W.spp"},
        }
    )
    text = reply[-3000:] if cut else reply
    assert cut == (not text.startswith("{"))
    stderr = f"Traceback ...\nRuntimeError: Painter MCP call failed:\n{text}\n\n"
    assert refusal(Call(1, "", stderr)) == message
