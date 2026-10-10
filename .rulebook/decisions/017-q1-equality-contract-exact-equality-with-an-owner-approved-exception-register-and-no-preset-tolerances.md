# 17. Q1 Equality contract: exact equality with an owner-approved exception register and no preset tolerances

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Owner question Q1 (docs/analysis/architecture-discussion/05-resolution.md §4) asked for the comparison domains, the reference machine and who may approve a bounded exception on what evidence. Decision 001 states output parity as the acceptance criterion but left per-map tolerances as a deferred alternative; D13 (decision 015) defines the four-tier corpus and the exception mechanism. Owner answer of 2026-10-10 (docs/open-questions.md Q1).

## Decision

Exact equality is the rule in every comparison domain: native decoded texture values, API readbacks, encoded bytes where a contract names them, and reference renders. A divergence passes only through an owner-approved, versioned exception backed by evidence (domain, metric and bound; proof that the oracle itself is unstable or the difference irreducible; a defect-detection test showing the bound still catches intentional errors), recorded in the exception register (.rulebook/decisions/ plus parity/exceptions.json; docs/architecture/14-parity-testing.md §5). There are no preset tolerances: the round-1 numbers are proposals only, and diagnostic metrics (FLIP, mean, p99) never grant an exception. Oracle stability, UzPainter repeatability and equality to Painter are reported separately. The reference machine is the owner's machine (decision 022). This refines decision 001, which stays accepted, and closes its deferred-tolerance alternative.

## Alternatives Considered

- Preset tolerances per map type (decision 001's deferred alternative; Claude round-1 numbers) - rejected by the owner
- Perceptual or image-similarity gates - rejected: diagnostics only
- Explained differences passing without an approved exception - rejected (closes the loophole named in D13)

## Consequences

A comparison without exact equality or a covering exception fails; it is reported blocked when the oracle is unavailable or unstable, never passed. Tier 3 renders against Painter's stochastic Iray (decision 018) can pass only through an exception derived from the measured noise floor. Every parity report lists the exceptions it relied on.
