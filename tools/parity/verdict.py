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
- Diagnostics are computed and reported; they never grant a pass on their own.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    ORACLE_UNAVAILABLE = "oracle_unavailable"


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


@dataclass(frozen=True)
class Comparison:
    """One compared quantity: oracle values (None when the blob is unavailable) and candidate.

    `oracle_stable` is the oracle-stability result of the golden (its recordings are equal).
    """

    tier: str
    domain: str
    oracle: Sequence[float] | None
    candidate: Sequence[float]
    extra_metrics: Mapping[str, float] = field(default_factory=dict)
    region_metrics: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    oracle_stable: bool = True


def _equal(a: float, b: float) -> bool:
    return a == b or (math.isnan(a) and math.isnan(b))


def _abs_diff(a: float, b: float) -> float:
    if _equal(a, b):
        return 0.0
    difference = abs(a - b)
    return math.inf if math.isnan(difference) else difference


def diagnose(oracle: Sequence[float], candidate: Sequence[float]) -> Diagnostics:
    """Statistics of |candidate - oracle|; p99 is the nearest-rank 99th percentile."""
    if len(oracle) != len(candidate):
        raise ValueError(f"shape mismatch: {len(oracle)} oracle values, {len(candidate)} candidate")
    if not oracle:
        raise ValueError("nothing to compare")
    diffs = sorted(_abs_diff(a, b) for a, b in zip(oracle, candidate, strict=True))
    total = len(diffs)
    differing = sum(1 for d in diffs if d != 0.0)
    return Diagnostics(
        max_abs_diff=diffs[-1],
        mean_abs_diff=math.fsum(diffs) / total,
        p99_abs_diff=diffs[math.ceil(0.99 * total) - 1],
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
    regions = comparison.region_metrics
    return bool(regions) and all(
        metric in values and values[metric] <= limit for values in regions.values()
    )


def in_force(entries: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The highest version of each exception id; earlier versions are superseded."""
    latest: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        current = latest.get(entry["exception_id"])
        if current is None or entry["version"] > current["version"]:
            latest[entry["exception_id"]] = entry
    return list(latest.values())


_UNSTABLE_BASES = {False: {"oracle_instability"}, True: {"oracle_instability", "noise_floor"}}


def evaluate(comparison: Comparison, register_entries: Sequence[Mapping[str, Any]]) -> Verdict:
    """Apply the contract to one comparison, given the validated register's entries."""
    if comparison.oracle is None:
        return Verdict(Outcome.ORACLE_UNAVAILABLE, None, reason="oracle blob unavailable")
    if len(comparison.oracle) != len(comparison.candidate):
        return Verdict(Outcome.FAIL, None, reason="structural difference: shape mismatch")
    diagnostics = diagnose(comparison.oracle, comparison.candidate)
    stable = comparison.oracle_stable
    if diagnostics.differing_count == 0 and comparison.tier != "3" and stable:
        return Verdict(Outcome.PASS, diagnostics, reason="exact equality")
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
