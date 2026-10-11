"""P0-TIER0 acceptance gate (phase0.8_tier0-goldens, `docs/dag.md`).

The whole Tier 0 corpus of the current envelope (every manifest under `tier0/` of its manifest
root in `parity/envelopes/registry.json`, decision 037: all four children plus the recorder
sample): each golden names its private record, the record holds at least two recordings (same
session; after save/reopen), every listed hash verifies in the store, and the stability report
classifies every golden. Checks that need the owner's private store skip,
saying so, on a machine without one (hosted CI, decision 028); the local oracle run is their
evidence (`parity/reports/phase0/tier0-goldens.md`). The published fits are checked by
`tests/parity/fit/test_stability_and_publication.py`.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.cli import REPORT
from tools.parity.schemas import REPO_ROOT, Schema, load_json, record_problems, validation_errors
from tools.parity.store.manifest import verify
from tools.parity.store.store import OracleStore, Status, locate

TIER0 = manifest_root(current_envelope()) / "tier0"
CONDITIONS = {"same_session", "after_save_reopen"}


def manifest_paths() -> list[Path]:
    return sorted(TIER0.rglob("*.json"))


def golden_id(path: Path) -> str:
    return "tier0/" + path.relative_to(TIER0).with_suffix("").as_posix()


def needs_store() -> OracleStore:
    store = locate()
    if store is None:
        pytest.skip("no private oracle store on this machine (hosted CI, decision 028)")
    return store


def private_record(store: OracleStore, manifest: dict[str, Any]) -> dict[str, Any]:
    ref = next(r for r in manifest["private_records"] if r["record_id"] == "golden-record")
    data = store.load(ref["sha256"])
    assert data is not None, f"{manifest['golden_id']}: private record unavailable"
    record: dict[str, Any] = json.loads(data)
    return record


def admission_problems(record: dict[str, Any]) -> list[str]:
    """Why a Tier 0 private record is not admitted: schema and cross-field rules (two
    recordings or more), plus both recording conditions of Tiers 0-2b."""
    problems = record_problems(record)
    conditions = {r["condition"] for r in record.get("recordings", [])}
    if not conditions >= CONDITIONS:
        problems.append(f"recording conditions {sorted(conditions)} lack {sorted(CONDITIONS)}")
    return problems


def test_corpus_covers_every_child() -> None:
    families = {path.relative_to(TIER0).parts[0] for path in manifest_paths()}
    assert families == {"api-probes", "defaults-templates", "recorder-sample", "semantics"}


@pytest.mark.parametrize("path", manifest_paths(), ids=golden_id)
def test_manifest_names_its_private_record_by_hash_only(path: Path) -> None:
    manifest = load_json(path)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["golden_id"] == golden_id(path)
    assert manifest["tier"] == "0"
    ids = [r["record_id"] for r in manifest["private_records"]]
    assert ids.count("golden-record") == 1


def test_every_golden_is_recorded_at_least_twice() -> None:
    """Gate item 1 and task 3.1: every record resolves and holds two recordings or more."""
    store = needs_store()
    for path in manifest_paths():
        manifest = load_json(path)
        record = private_record(store, manifest)
        assert record["golden_id"] == manifest["golden_id"]
        assert admission_problems(record) == [], manifest["golden_id"]
        assert len(record["recordings"]) >= 2


def test_a_golden_with_one_recording_is_not_admitted() -> None:
    store = needs_store()
    record = private_record(store, load_json(manifest_paths()[0]))
    single = copy.deepcopy(record)
    single["recordings"] = single["recordings"][:1]
    assert admission_problems(single) != []


def test_every_listed_hash_verifies_in_the_store() -> None:
    """Task 3.1: `uzpainter parity verify` over the Tier 0 manifests (owner's machine)."""
    store = needs_store()
    for path in manifest_paths():
        results = verify(store, load_json(path))
        assert results and all(r.status == Status.AVAILABLE for r in results), path.name


def stability_rows() -> dict[str, list[str]]:
    """Section 3 of the stability report: golden id -> table cells."""
    text = (REPO_ROOT / REPORT).read_text(encoding="utf-8")
    section = text.split("## 3. Per-golden recording comparison", 1)[1].split("\n## ", 1)[0]
    rows: dict[str, list[str]] = {}
    for line in section.splitlines():
        match = re.match(r"\| `(tier0/[^`]+)` \|", line)
        if match:
            rows[match.group(1)] = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return rows


def test_stability_report_classifies_every_golden() -> None:
    """Gate item 2: one classification per golden of the corpus, from at least two recordings."""
    rows = stability_rows()
    assert set(rows) == {golden_id(path) for path in manifest_paths()}
    for gid, cells in rows.items():
        recordings, classification, admission = cells[2], cells[6], cells[7]
        assert len(re.findall(r"\br\d+ ", recordings)) >= 2, gid
        assert classification in {"stable", "unstable"}, gid
        expected = "exact golden" if classification == "stable" else "not admitted (§4)"
        assert admission == expected, gid
