"""The contract's decision rule for one comparison (`parity/CONTRACT.md` §3, §5, §8).

- A missing oracle is `oracle_unavailable`, never a pass.
- Exact equality of the native decoded values passes in Tiers 0-2b when the oracle is stable.
- Any non-zero difference passes only when an owner-approved entry of the exception register
  covers the comparison's tier and domain and every bound of that entry holds. An explanation
  is not an input: an explained difference without an entry fails.
- Tier 3 passes only through a covering entry, even when the values happen to be equal.
- An unstable oracle passes only through a covering entry whose evidence is the oracle
  instability or, in Tier 3, the noise floor (which includes Iray's run-to-run difference).
- Without a covering entry, Tier 3 and comparisons against an unstable oracle are `blocked`;
  every other difference `fail`s. A shape mismatch is structural and fails in every tier.
- Decision 032: against an unstable Painter oracle (Tiers 0-2b) the same-session recording r1 is
  the exact target. The comparison against r1 passes only when every value is equal and an
  instability entry names the domain; any difference from r1 `fail`s, whatever the register holds.
- Decision 223: an owner scope split (`owner_scope_split`) bounds only the texels the comparison's
  UV coverage mask marks covered (bound scope `covered`, `max_abs_diff` 0): the texels outside it
  are the ones the entry excepts. Without a mask, or with no covered texel, it covers nothing.
- Decision 259: a version that withdraws its id leaves nothing of it in force. The owner withdrew
  EXC-007, the only owner scope split, so a padding difference on the Wand fails.
- Diagnostics are computed and reported; they never grant a pass on their own.

Envelope (decisions 034, 037; CONTRACT.md §6.5):

- Goldens resolve through the current envelope's manifest root (`resolve_golden`), and verdicts
  judge against the current envelope only: a comparison against a golden of any other envelope
  is `stale`, never a pass, so an old-envelope pass never carries over. A Tier 3 reference is not
  re-recorded by a refresh; one recorded under an older envelope resolves `stale` until it is
  re-captured.
- UzPainter-to-golden comparisons never consult the live environment. Oracle-side comparisons
  (an oracle re-recording against a golden) compare the two environment records with
  `envelope_match`; anything but `match` ends in `out_of_envelope`, never `pass` or `fail`.
- No whole-product parity claim while any required verdict is not a pass against the current
  envelope (`whole_product_parity`).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.envelope.registry import (
    corpus_manifests,
    current_envelope,
    envelope,
    load_registry,
)
from tools.parity.recorder.environment import MATCH, envelope_match
from tools.parity.schemas import REPO_ROOT, load_json

ALL_TIERS = frozenset({"0", "1", "2a", "2b", "3"})

# Compared values: a sequence of numbers or an array of them (any shape; flattened in order).
Values = Sequence[float] | npt.NDArray[Any]


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    ORACLE_UNAVAILABLE = "oracle_unavailable"
    OUT_OF_ENVELOPE = "out_of_envelope"
    STALE = "stale"


@dataclass(frozen=True)
class Diagnostics:
    """Absolute-difference statistics over native decoded values (CONTRACT.md §8.1)."""

    max_abs_diff: float
    mean_abs_diff: float
    p99_abs_diff: float
    differing_count: int
    differing_percent: float
    total: int

    def metrics(self) -> dict[str, float]:
        return {
            "max_abs_diff": self.max_abs_diff,
            "mean_abs_diff": self.mean_abs_diff,
            "p99_abs_diff": self.p99_abs_diff,
            "differing_count": float(self.differing_count),
            "differing_percent": self.differing_percent,
        }


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    diagnostics: Diagnostics | None
    exceptions_relied_on: tuple[tuple[str, int], ...] = ()
    reason: str = ""
    envelope_id: str = ""


@dataclass(frozen=True)
class Comparison:
    """One compared quantity: oracle values (None when the blob is unavailable) and candidate.

    `oracle_stable` is the oracle-stability result of the golden (its recordings are equal).
    `exact_target` marks, for an unstable oracle, the comparison against the same-session
    recording r1 (decision 032). `covered` is the UV coverage mask of a texture map, rows by
    columns of its first two axes (`tools/parity/coverage.py`), for entries bounding the covered
    texels only (decision 223); None when the comparison has none.

    `envelope_id` is the envelope of the golden compared against (`ResolvedGolden.envelope_id`);
    None means the caller resolved the golden through the current envelope. `oracle_side` marks
    an oracle re-recording compared with the golden; `golden_environment` and
    `candidate_environment` are then the two environment records (`recorder/environment.py`).
    """

    tier: str
    domain: str
    oracle: Values | None
    candidate: Values
    extra_metrics: Mapping[str, float] = field(default_factory=dict)
    region_metrics: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    oracle_stable: bool = True
    exact_target: bool = False
    envelope_id: str | None = None
    oracle_side: bool = False
    golden_environment: Mapping[str, Any] | None = None
    candidate_environment: Mapping[str, Any] | None = None
    covered: npt.NDArray[np.bool_] | None = None


def _flat(values: Values) -> npt.NDArray[Any]:
    array = np.asarray(values)
    return (
        array.reshape(-1)
        if np.issubdtype(array.dtype, np.integer)
        else array.astype(np.float64).reshape(-1)
    )


_INT64_SAFE = 1 << 62  # |a - b| of two integers strictly within +-2**62 is below 2**63


def _int64_safe(values: npt.NDArray[Any]) -> bool:
    return not values.size or (int(values.min()) > -_INT64_SAFE and int(values.max()) < _INT64_SAFE)


def _abs_diffs(oracle: npt.NDArray[Any], candidate: npt.NDArray[Any]) -> npt.NDArray[np.float64]:
    """|candidate - oracle| per value: equal values (equal infinities included) and two NaNs are
    0, a NaN against anything else is inf. Integer values subtract exactly: in int64 when both
    lie strictly within +-2**62, else as Python integers (uint64 against int64 included)."""
    if np.issubdtype(oracle.dtype, np.integer) and np.issubdtype(candidate.dtype, np.integer):
        if _int64_safe(oracle) and _int64_safe(candidate):
            exact: npt.NDArray[np.float64] = np.abs(
                oracle.astype(np.int64) - candidate.astype(np.int64)
            ).astype(np.float64)
            return exact
        wide = np.abs(oracle.astype(object) - candidate.astype(object))  # Python integers
        return np.array([float(value) for value in wide], dtype=np.float64)
    a, b = oracle.astype(np.float64), candidate.astype(np.float64)
    with np.errstate(invalid="ignore", over="ignore"):
        diffs: npt.NDArray[np.float64] = np.abs(a - b)
    diffs[(a == b) | (np.isnan(a) & np.isnan(b))] = 0.0
    diffs[np.isnan(diffs)] = math.inf
    return diffs


def diagnose(oracle: Values, candidate: Values) -> Diagnostics:
    """Statistics of |candidate - oracle|; p99 is the nearest-rank 99th percentile, the mean an
    exactly rounded sum (`math.fsum`) over the count."""
    if np.shape(oracle) != np.shape(candidate):
        raise ValueError(
            f"shape mismatch: oracle {np.shape(oracle)}, candidate {np.shape(candidate)}"
        )
    left, right = _flat(oracle), _flat(candidate)
    if not left.size:
        raise ValueError("nothing to compare")
    diffs = np.sort(_abs_diffs(left, right))
    total = int(diffs.size)
    differing = int(np.count_nonzero(diffs))
    return Diagnostics(
        max_abs_diff=float(diffs[-1]),
        mean_abs_diff=math.fsum(diffs.tolist()) / total,
        p99_abs_diff=float(diffs[math.ceil(0.99 * total) - 1]),
        differing_count=differing,
        differing_percent=100.0 * differing / total,
        total=total,
    )


def _bound_holds(
    bound: Mapping[str, Any], comparison: Comparison, metrics: Mapping[str, float]
) -> bool:
    metric: str = bound["metric"]
    limit = float(bound["max"])
    if bound["scope"] == "whole":
        return metric in metrics and metrics[metric] <= limit
    if bound["scope"] == "covered":
        covered = comparison.covered
        oracle = np.asarray(comparison.oracle)
        if covered is None or covered.shape != oracle.shape[:2] or not covered.any():
            return False
        inside = diagnose(oracle[covered], np.asarray(comparison.candidate)[covered]).metrics()
        return metric in inside and inside[metric] <= limit
    regions = comparison.region_metrics
    return bool(regions) and all(
        metric in values and values[metric] <= limit for values in regions.values()
    )


def in_force(entries: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The highest version of each exception id; earlier versions are superseded, and an id whose
    highest version withdraws it (decision 259) has nothing in force."""
    latest: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        current = latest.get(entry["exception_id"])
        if current is None or entry["version"] > current["version"]:
            latest[entry["exception_id"]] = entry
    return [entry for entry in latest.values() if not entry.get("withdrawn")]


_UNSTABLE_BASES = {False: {"oracle_instability"}, True: {"oracle_instability", "noise_floor"}}


def _exact_target(
    comparison: Comparison, diagnostics: Diagnostics, register_entries: Sequence[Mapping[str, Any]]
) -> Verdict:
    """The comparison against r1 of an unstable Tiers 0-2b golden (decision 032)."""
    if diagnostics.differing_count:
        return Verdict(Outcome.FAIL, diagnostics, reason="divergence from the exact target r1")
    covering = [
        entry
        for entry in in_force(register_entries)
        if entry["tier"] == comparison.tier
        and entry["domain"]["selector"] == comparison.domain
        and entry["evidence"]["basis"] == "oracle_instability"
    ]
    if not covering:
        return Verdict(Outcome.BLOCKED, diagnostics, reason="unstable oracle without an entry")
    relied = tuple(sorted((e["exception_id"], e["version"]) for e in covering))
    return Verdict(Outcome.PASS, diagnostics, relied, reason="exact target r1 equal")


def evaluate(
    comparison: Comparison,
    register_entries: Sequence[Mapping[str, Any]],
    current_envelope_id: str | None = None,
) -> Verdict:
    """Apply the contract to one comparison, given the validated register's entries and the
    current envelope (default: the registry's); the verdict names that envelope."""
    current = current_envelope_id or str(current_envelope()["envelope_id"])
    verdict = _evaluate(comparison, register_entries, current)
    return Verdict(
        verdict.outcome, verdict.diagnostics, verdict.exceptions_relied_on, verdict.reason, current
    )


def _evaluate(
    comparison: Comparison, register_entries: Sequence[Mapping[str, Any]], current: str
) -> Verdict:
    if comparison.oracle is None:
        return Verdict(Outcome.ORACLE_UNAVAILABLE, None, reason="oracle blob unavailable")
    same_shape = np.shape(comparison.oracle) == np.shape(comparison.candidate)
    shaped = same_shape and np.size(comparison.oracle) > 0
    if comparison.oracle_side:  # judged by the two environment records alone
        match = envelope_match(comparison.golden_environment, comparison.candidate_environment)
        if match != MATCH:
            diagnostics = diagnose(comparison.oracle, comparison.candidate) if shaped else None
            reason = f"oracle environments {match}: not comparable"
            return Verdict(Outcome.OUT_OF_ENVELOPE, diagnostics, reason=reason)
    elif comparison.envelope_id is not None and comparison.envelope_id != current:
        diagnostics = diagnose(comparison.oracle, comparison.candidate) if shaped else None
        reason = f"golden of envelope {comparison.envelope_id}, not the current {current}"
        return Verdict(Outcome.STALE, diagnostics, reason=reason)
    if not same_shape:
        return Verdict(Outcome.FAIL, None, reason="structural difference: shape mismatch")
    diagnostics = diagnose(comparison.oracle, comparison.candidate)
    stable = comparison.oracle_stable
    if diagnostics.differing_count == 0 and comparison.tier != "3" and stable:
        return Verdict(Outcome.PASS, diagnostics, reason="exact equality")
    if not stable and comparison.exact_target and comparison.tier != "3":
        return _exact_target(comparison, diagnostics, register_entries)
    metrics = {**diagnostics.metrics(), **comparison.extra_metrics}
    covering = [
        entry
        for entry in in_force(register_entries)
        if entry["tier"] == comparison.tier
        and entry["domain"]["selector"] == comparison.domain
        and (stable or entry["evidence"]["basis"] in _UNSTABLE_BASES[comparison.tier == "3"])
        and all(_bound_holds(bound, comparison, metrics) for bound in entry["bounds"])
    ]
    if covering:
        relied = tuple(sorted((e["exception_id"], e["version"]) for e in covering))
        return Verdict(Outcome.PASS, diagnostics, relied, reason="covered by the register")
    if not stable:
        return Verdict(Outcome.BLOCKED, diagnostics, reason="unstable oracle without an entry")
    if comparison.tier == "3":
        return Verdict(Outcome.BLOCKED, diagnostics, reason="no register entry covers Tier 3")
    return Verdict(Outcome.FAIL, diagnostics, reason="difference not covered by the register")


def whole_product_parity(verdicts: Iterable[Verdict], current_envelope_id: str) -> bool:
    """A whole-product parity claim holds only when every required comparison passed against
    the current envelope: one `stale` Tier 3 reference, or any other outcome, withholds it."""
    found = list(verdicts)
    return bool(found) and all(
        v.outcome is Outcome.PASS and v.envelope_id == current_envelope_id for v in found
    )


@dataclass(frozen=True)
class ResolvedGolden:
    """A golden's public manifest and the envelope it belongs to (`stale` when not current)."""

    golden_id: str
    manifest_path: Path
    manifest: dict[str, Any]
    envelope_id: str
    stale: bool


def _find(
    entry: Mapping[str, Any], golden_id: str, repo_root: Path
) -> tuple[Path, dict[str, Any]] | None:
    for path in corpus_manifests(entry, repo_root, ALL_TIERS):
        manifest: dict[str, Any] = load_json(path)
        if manifest["golden_id"] == golden_id:
            return path, manifest
    return None


def _recorded_under(
    document: Mapping[str, Any], entry: Mapping[str, Any], manifest: Mapping[str, Any]
) -> str:
    """The envelope a manifest was recorded under: its root's envelope when the recorded Painter
    build is that envelope's, else the newest envelope of that build (`painter-<build>` when
    none is registered)."""
    build = str(manifest["software"]["painter"]["build_id"])
    if build == entry["painter_build"]:
        return str(entry["envelope_id"])
    same = [e["envelope_id"] for e in document["envelopes"] if e["painter_build"] == build]
    return str(same[-1]) if same else f"painter-{build}"


def resolve_golden(golden_id: str, repo_root: Path = REPO_ROOT) -> ResolvedGolden | None:
    """The golden through the current envelope's manifest root, or None (`oracle_unavailable`).

    An older envelope never stands in for a texture-tier golden the current envelope lacks. A
    Tier 3 reference is not re-recorded by a refresh, so one found only in an older envelope
    (newest first, along `previous`) resolves `stale`; so does any golden whose recorded Painter
    build is not the current envelope's."""
    document = load_registry(repo_root)
    current = envelope(document, document["current"])
    entry: Mapping[str, Any] | None = current
    while entry is not None:
        found = _find(entry, golden_id, repo_root)
        if found is not None and (entry is current or found[1]["tier"] == "3"):
            path, manifest = found
            recorded = _recorded_under(document, entry, manifest)
            stale = recorded != current["envelope_id"]
            return ResolvedGolden(golden_id, path, manifest, recorded, stale)
        previous = entry["previous"]
        entry = None if previous is None else envelope(document, previous)
    return None
