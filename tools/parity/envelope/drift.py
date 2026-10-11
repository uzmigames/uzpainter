"""Drift of a re-recorded golden against the previous envelope (decisions 034 (d), 037).

Each recording of the new run is compared exactly with the recording of the same id in the
previous envelope's record (`r1` with `r1`, `r2` with `r2`, ...). A golden is `unchanged` only
when every paired recording is equal and both records hold the same recording ids; otherwise
`changed` (a divergence candidate: UzPainter's verdicts against the new envelope must be
re-established), or `unavailable` when the previous record or a blob cannot be read.

Consequences derived here, never decided here:

- `fits_to_recheck`: every `parity/semantics/*.json` fit is re-checked against a new envelope
  (decision 037 §4); fits whose `corpus` names a changed golden are listed `corpus_changed`;
- `new_evaluator_profile_needed`: true when any Tier 0 semantics golden changed (decision 037 §5);
- `stale_tier3`: Tier 3 references of the previous envelope (decision 037 §6).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from tools.parity.envelope.compare import (
    DIFFERS,
    EQUAL,
    UNAVAILABLE,
    RecordSource,
    SourceUnavailable,
    compare_recordings,
)
from tools.parity.schemas import REPO_ROOT, load_json

DRIFT_SCHEMA = "uzpainter/parity/oracle-envelope-drift/1"
SEMANTICS_GOLDENS = "tier0/semantics/"
UNCHANGED, CHANGED, NEW, MISSING = "unchanged", "changed", "new", "missing"


@dataclass(frozen=True)
class DriftInput:
    """One golden: its tier, the previous envelope's record (None when it cannot be read or the
    golden is new) and the new run's record (None when it was not re-recorded)."""

    golden_id: str
    tier: str
    previous: RecordSource | None
    current: RecordSource | None
    previous_error: str | None = None


def golden_drift(item: DriftInput) -> dict[str, Any]:
    result: dict[str, Any] = {
        "golden_id": item.golden_id,
        "tier": item.tier,
        "status": UNCHANGED,
        "changed_recordings": [],
        "pairs": [],
        "differing_outputs": [],
    }
    if item.current is None:
        result["status"] = MISSING
        return result
    result["record_sha256"] = item.current.record_sha256
    if item.previous is None:
        result["status"] = UNAVAILABLE if item.previous_error else NEW
        return result
    result["previous_record_sha256"] = item.previous.record_sha256
    old_ids, new_ids = item.previous.recording_ids(), item.current.recording_ids()
    changed: list[str] = sorted(set(old_ids) ^ set(new_ids))
    unavailable = False
    for recording_id in [r for r in old_ids if r in new_ids]:
        try:
            pair = compare_recordings(
                item.previous, recording_id, item.current, recording_id, "envelope_drift"
            )
        except SourceUnavailable:
            unavailable = True
            continue
        label = f"previous.{recording_id}~new.{recording_id}"
        summary = pair.summary()
        summary["left"], summary["right"] = f"previous.{recording_id}", f"new.{recording_id}"
        result["pairs"].append(summary)
        result["differing_outputs"] += [{"pair": label, **o} for o in pair.differing_outputs()]
        if pair.status == DIFFERS or pair.unpaired:
            changed.append(recording_id)
        elif pair.status == UNAVAILABLE:
            unavailable = True
    result["changed_recordings"] = sorted(set(changed))
    if result["changed_recordings"]:
        result["status"] = CHANGED
    elif unavailable:
        result["status"] = UNAVAILABLE
    return result


def fits_to_recheck(changed: set[str], repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    fits: list[dict[str, Any]] = []
    for path in sorted((repo_root / "parity" / "semantics").glob("*.json")):
        document = load_json(path)
        corpus = [str(g) for g in document.get("corpus", [])]
        hit = sorted(set(corpus) & changed)
        fits.append(
            {
                "semantics": path.relative_to(repo_root).as_posix(),
                "reason": "corpus_changed" if hit else "new_envelope",
                "changed_goldens": hit,
            }
        )
    return fits


def tier3_goldens(manifests: Sequence[Path]) -> list[str]:
    return sorted(
        str(d["golden_id"]) for d in (load_json(p) for p in manifests) if d.get("tier") == "3"
    )


def drift_document(
    scope: str,
    new_envelope: Mapping[str, Any],
    previous_envelope: Mapping[str, Any],
    items: Sequence[DriftInput],
    stale_tier3: Sequence[str],
    today: date,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """The published drift report (`oracle-envelope.json`, `drift`); numbers and hashes only.

    `new_envelope` holds `envelope_id`, `painter_build` and `envelope_sha256`."""
    goldens = [golden_drift(item) for item in sorted(items, key=lambda i: i.golden_id)]
    changed = {g["golden_id"] for g in goldens if g["status"] == CHANGED}
    summary: dict[str, int] = {"goldens": len(goldens)}
    for status in (UNCHANGED, CHANGED, UNAVAILABLE, NEW, MISSING):
        summary[status] = sum(g["status"] == status for g in goldens)
    summary["equal_pairs"] = sum(p["status"] == EQUAL for g in goldens for p in g["pairs"])
    return {
        "schema": DRIFT_SCHEMA,
        "scope": scope,
        "envelope_id": new_envelope["envelope_id"],
        "painter_build": new_envelope["painter_build"],
        "envelope_sha256": new_envelope["envelope_sha256"],
        "previous_envelope_id": previous_envelope["envelope_id"],
        "previous_painter_build": previous_envelope["painter_build"],
        "generated_on": today.isoformat(),
        "goldens": goldens,
        "divergence_candidates": sorted(changed),
        "fits_to_recheck": fits_to_recheck(changed, repo_root),
        "new_evaluator_profile_needed": any(g.startswith(SEMANTICS_GOLDENS) for g in changed),
        "stale_tier3": sorted(stale_tier3),
        "summary": summary,
    }
