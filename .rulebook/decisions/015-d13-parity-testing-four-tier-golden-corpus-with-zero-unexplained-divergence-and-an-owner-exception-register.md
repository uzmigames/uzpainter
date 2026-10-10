# 15. D13 Parity testing: four-tier golden corpus with zero unexplained divergence and an owner exception register

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Decision 001 demands output parity; Painter's own 16F channels drift across sessions; the community bridge's defects make bridge-recorded recipes untrustworthy (05-resolution.md D13).

## Decision

Goldens recorded only through Painter's documented API by UzmiGames recorder scripts and stored privately (hashes in-repo, blobs in a private store); Tier 0 semantics, Tier 1 recipes, Tier 2 procedurals/bakes, Tier 3 renders. Acceptance: equal native decoded values and the agreed render output; every divergence fails unless an owner-approved, versioned exception covers that domain and metric; explained differences still fail without one; diagnostics never grant exceptions. Oracle stability, UzPainter repeatability and equality are reported separately; goldens change only with reviewed provenance; CPU and GPU CI lanes; failure injections. See docs/architecture/14-parity-testing.md.

## Alternatives Considered

- Tolerance values as default gates (Claude round 1) - rejected: tolerances need owner approval
- Image-similarity-only tests - rejected
- Recording goldens through the community MCP bridge - rejected: known defects

## Consequences

Phase 0 records the Tier 0 corpus twice and measures oracle stability before any exception is proposed.
