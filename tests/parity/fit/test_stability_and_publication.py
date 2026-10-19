"""Tier 0 stability classification and the published fits (phase0.7_tier0-stability-fits).

3.1 schema, 3.2 guard, 3.3 reproduction on the owner's machine, 3.4 classification. Hosted
tests use synthetic arrays and the committed files only; the reproduction test re-runs every fit
against the private store and needs it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tools.parity.envelope.registry import (
    current_envelope,
    initial_registry,
    load_registry,
    manifest_root,
    save_registry,
)
from tools.parity.fit.cli import FITS, REPORT, recheck_problems, reproduction_problems
from tools.parity.fit.common import Context
from tools.parity.fit.decode import Decoded
from tools.parity.fit.oracle import Golden, Recording
from tools.parity.fit.report import ITEMS
from tools.parity.fit.stability import (
    STABLE,
    UNSTABLE,
    channel_types,
    compare_maps,
    golden_stability,
    storage_key,
)
from tools.parity.fit.stats import difference
from tools.parity.guard.guard import Snapshot, run_guard
from tools.parity.recorder.script_run import R1, R1_REPEAT, R2
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors
from tools.parity.store.store import locate
from tools.parity.tier0_semantics.corpus import COVERAGE, OWNED_ELSEWHERE

SEMANTICS = REPO_ROOT / "parity" / "semantics"
APPROVED = (REPO_ROOT / "docs" / "approved-sources.md").read_text(encoding="utf-8")
PNG16 = {"container": "png", "sample_type": "uint", "bits_per_channel": 16, "channels": 3}


def published() -> list[Path]:
    return [SEMANTICS / file for file in FITS.values()]


# --- 3.4 classification ------------------------------------------------------------------------


def test_identical_recordings_are_stable() -> None:
    a = np.arange(4 * 4 * 3, dtype=np.int64).reshape(4, 4, 3)
    classification, diff = compare_maps(a, a.copy())
    assert classification == STABLE
    assert (diff.max, diff.differing, diff.affected_texels, diff.texels) == (0, 0, 0, 16)


def test_recordings_differing_in_one_texel_are_unstable_with_count_one() -> None:
    a = np.zeros((4, 4, 3), np.int64)
    b = a.copy()
    b[2, 1, 0] = 257
    classification, diff = compare_maps(a, b)
    assert classification == UNSTABLE
    assert (diff.max, diff.differing, diff.affected_texels, diff.total) == (257, 1, 1, 48)
    assert diff.mean == pytest.approx(257 / 48)


def test_float_maps_compare_as_numbers_and_nan_matches_only_nan() -> None:
    a = np.array([[[0.5, np.nan, 1.0]]])
    assert compare_maps(a, a.copy())[0] == STABLE
    b = np.array([[[0.5, 0.0, np.nextafter(1.0, 2.0)]]])
    diff = difference(a, b)
    assert diff.differing == 2
    assert diff.max == np.inf


def _golden(maps: dict[str, tuple[Any, Any]], readbacks: dict[str, tuple[Any, Any]]) -> Golden:
    decoded: dict[str, Decoded] = {}
    recordings = {}
    for index, (rid, condition) in enumerate((("r1", "same_session"), ("r2", "after_save_reopen"))):
        outputs: dict[str, dict[str, Any]] = {}
        for output_id, pair in maps.items():
            sha = f"{output_id}-{rid}"
            decoded[sha] = Decoded(np.asarray(pair[index]), True, 16)
            outputs[output_id] = {
                "kind": "exported_map",
                "blob": {"sha256": sha, "size_bytes": 1},
                "storage_format": {**PNG16, "encoding": "linear"},
            }
        for output_id, pair in readbacks.items():
            outputs[output_id] = {"kind": "api_readback", "value": pair[index]}
        recordings[rid] = Recording(rid, condition, outputs)
    path = manifest_root(current_envelope()) / "tier0" / "synthetic" / "golden.json"
    return Golden("tier0/synthetic/golden", path, {}, "0" * 64, recordings, None, decoded)


def test_golden_with_one_differing_texel_is_unstable_and_lists_the_map() -> None:
    a = np.zeros((2, 2, 3), np.int64)
    b = a.copy()
    b[0, 0, 2] = 1
    golden = _golden({"s0/user0": (a, b), "s0/user1": (a, a)}, {})
    result = golden_stability(golden, REPO_ROOT)
    assert result.classification == UNSTABLE
    assert [m.output_id for m in result.unstable_maps()] == ["s0/user0"]
    assert result.unstable_maps()[0].difference.differing == 1
    types = channel_types([result])
    assert [(t.storage, t.maps, t.unstable_maps, t.differing) for t in types] == [
        ("png/uint16/3ch/linear", 2, 1, 1)
    ]


def test_readbacks_ignore_only_the_resource_context_counter() -> None:
    url = "resource://project20/grey-a?version=1.image"
    golden = _golden(
        {},
        {
            "readback/a": ({"url": url}, {"url": url.replace("project20", "project21")}),
            "readback/b": ({"name": "Untitled"}, {"name": "probe"}),
        },
    )
    result = golden_stability(golden, REPO_ROOT)
    by_id = {o.output_id: o for o in result.outputs}
    assert by_id["readback/a"].equal and not by_id["readback/a"].equal_raw
    assert not by_id["readback/b"].equal
    assert result.classification == UNSTABLE


def test_storage_key_names_every_measured_field() -> None:
    assert storage_key({**PNG16, "encoding": "srgb"}) == "png/uint16/3ch/srgb"
    exr = {"container": "exr", "sample_type": "float", "bits_per_channel": 32, "channels": 1}
    assert storage_key({**exr, "encoding": None}) == "exr/float32/1ch/unspecified"


# --- 3.1 schema and sources --------------------------------------------------------------------


@pytest.mark.parametrize("path", sorted(SEMANTICS.glob("*.json")), ids=lambda p: p.name)
def test_fits_validate_and_name_a_public_source_and_a_residual(path: Path) -> None:
    document = load_json(path)
    assert validation_errors(document, Schema.SEMANTICS) == []
    builds = {e["painter_build"] for e in load_registry()["envelopes"]}
    assert document["painter_build_id"] in builds
    ids = [e["entry_id"] for e in document["entries"]]
    assert len(ids) == len(set(ids))
    for entry in document["entries"]:
        for source in entry["public_sources"]:
            assert f"| {source['source_id']} |" in APPROVED, source
        if entry["status"] == "gap":
            continue
        assert entry["residuals"], entry["entry_id"]
        # r1 and r2 always; a Tier 1 golden's same-session repeat (`r1-repeat`) may add its own.
        recordings = {r["compared_against"] for r in entry["residuals"]}
        assert {R1, R2} <= recordings <= {R1, R1_REPEAT, R2}, entry["entry_id"]
        zero = all(r["difference"]["differing"] == 0 for r in entry["residuals"])
        assert (entry["status"] == "exact") == zero, entry["entry_id"]
        for r in entry["residuals"]:
            assert r["golden_id"] in document["corpus"]


# --- decision 037: fits and the current envelope -------------------------------------------------


def test_fits_of_an_older_envelope_are_listed_for_recheck() -> None:
    """A fit measured on an older build is never counted as checked against the current one."""
    assert recheck_problems(REPO_ROOT) == []


def test_an_older_fit_missing_from_fits_to_recheck_is_reported(tmp_path: Path) -> None:
    document = initial_registry("1.0.0", "1.0.0", "parity/manifests", "2026-01-01")
    old = document["envelopes"][0]
    drift = "parity/reports/phase0/oracle-envelope-drift-corpus-painter-2.0.0.json"
    new = {
        **old,
        "envelope_id": "painter-2.0.0",
        "painter_build": "2.0.0",
        "painter_version": "2.0.0",
        "manifest_root": "parity/envelopes/painter-2.0.0/manifests",
        "previous": "painter-1.0.0",
        "promoted_on": "2026-02-01",
        "drift_report": drift,
    }
    old.update(status="superseded", superseded_on="2026-02-01")
    save_registry({**document, "current": "painter-2.0.0", "envelopes": [old, new]}, tmp_path)
    semantics = tmp_path / "parity" / "semantics"
    semantics.mkdir(parents=True)
    for name, build in (("listed", "1.0.0"), ("unlisted", "1.0.0"), ("current", "2.0.0")):
        (semantics / f"{name}.json").write_text(json.dumps({"painter_build_id": build}), "utf-8")
    (semantics / "unknown.json").write_text(json.dumps({"painter_build_id": "9.9.9"}), "utf-8")
    listed = [{"semantics": "parity/semantics/listed.json", "reason": "new_envelope"}]
    (tmp_path / drift).parent.mkdir(parents=True)
    (tmp_path / drift).write_text(json.dumps({"fits_to_recheck": listed}), "utf-8")
    problems = recheck_problems(tmp_path)
    assert len(problems) == 2
    assert problems[0].startswith("parity/semantics/unknown.json: Painter build 9.9.9")
    assert problems[1].startswith("parity/semantics/unlisted.json: published against 1.0.0")


# --- 3.2 guard ---------------------------------------------------------------------------------


def test_guard_rejects_a_recorded_readback_pasted_into_a_fits_file() -> None:
    document = load_json(published()[0])
    document["entries"][0]["parameters"].append(
        {"name": "readback", "value": {"uniform_color_working": [0.2, 0.7]}, "origin": "fitted"}
    )
    data = json.dumps(document).encode("utf-8")
    path = "parity/semantics/blend-modes.json"
    snapshot = Snapshot((path,), (path,), lambda _: data)
    findings = run_guard(REPO_ROOT, snapshot, None)
    assert findings and all(f.rule == "public-schema" for f in findings)


def test_guard_accepts_the_published_fits_and_report() -> None:
    paths = (*(f"parity/semantics/{file}" for file in FITS.values()), REPORT)
    snapshot = Snapshot(paths, paths, lambda p: (REPO_ROOT / p).read_bytes())
    assert run_guard(REPO_ROOT, snapshot, None) == []


@pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine")
def test_local_guard_with_the_store_index_finds_nothing() -> None:
    paths = ["parity/semantics", "parity/reports", "tools/parity/fit", "tests/parity/fit"]
    result = subprocess.run(
        [sys.executable, "-m", "tools.parity.guard", *paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "store-hash rule against store" in result.stdout


# --- settlement and report ---------------------------------------------------------------------


def test_settlement_covers_every_section_9_item() -> None:
    assert {item.name for item in ITEMS} == set(COVERAGE) | set(OWNED_ELSEWHERE)
    text = (REPO_ROOT / REPORT).read_text(encoding="utf-8")
    section = text.split("## 6.", 1)[1]
    for item in ITEMS:
        row = next(line for line in section.splitlines() if line.startswith(f"| {item.name} |"))
        assert re.search(r"\| (\*\*settled\*\*|not settled) \|", row)


def test_report_lists_every_published_fit_and_entry() -> None:
    text = (REPO_ROOT / REPORT).read_text(encoding="utf-8")
    for path in published():
        for entry in load_json(path)["entries"]:
            assert f"| `{path.name}` | `{entry['entry_id']}` |" in text


def test_a_calibrated_fit_is_never_reported_as_settled() -> None:
    text = (REPO_ROOT / REPORT).read_text(encoding="utf-8")
    section = text.split("## 6.", 1)[1]
    for line in section.splitlines():
        if "**settled**" in line:
            assert line.rstrip().endswith("| — |")


# --- 3.3 reproduction (owner's machine) --------------------------------------------------------


@pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine")
@pytest.mark.parametrize("name", list(FITS))
def test_rerunning_each_fit_reproduces_the_published_residuals(name: str) -> None:
    """Each fit reproduces against the envelope it was published on. One published on an older
    envelope stays history until re-checked: `recheck_problems` keeps it listed for re-check."""
    build = load_json(SEMANTICS / FITS[name])["painter_build_id"]
    published_on = [e for e in load_registry()["envelopes"] if e["painter_build"] == build]
    assert published_on, build
    assert reproduction_problems(Context(locate(), REPO_ROOT, published_on[-1]), name) == []
