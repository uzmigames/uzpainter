# 20. Q6 Migration: rebuild through Painter's documented API, proven by output equality; no .spp reader

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Owner question Q6 asked whether existing Assets3D projects migrate by a verified rebuild from recipe and resources (hidden layers, raster state, bindings, render settings) or by reading .spp files natively. Decision 002 forbids decoding Adobe binary formats for implementation. Owner answer of 2026-10-10 (docs/open-questions.md Q6).

## Decision

Existing projects migrate by rebuilding them in UzPainter from their recipes and resources, with the state they need read through Painter's documented Python API while Painter is installed on the owner's machine. A migration counts only when the rebuilt project's outputs equal Painter's under the Q1 contract (decision 017). UzPainter has no .spp reader or writer. Project-private frozen snapshots (decision 006) preserve approved procedural states during migration only and never ship.

## Alternatives Considered

- Native .spp reader - rejected: decoding Adobe binary formats is off-limits (decision 002)
- Recipe replay without output verification - rejected: a migration must be proven by output equality

## Consequences

Migration needs a licensed Painter installation until the corpus is migrated; Tunic v10 recovery (decision 016) is the first binding proof. Painter-derived state stays private oracle data or project-private data.
