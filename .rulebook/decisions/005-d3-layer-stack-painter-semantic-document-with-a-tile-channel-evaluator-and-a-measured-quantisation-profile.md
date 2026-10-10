# 5. D3 Layer stack: Painter-semantic document with a tile/channel evaluator and a measured quantisation profile

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Output parity requires Painter's compositing semantics, which are documented only as names; formulas and quantisation points must be measured (05-resolution.md D3).

## Decision

Dedicated document model with the 12 node kinds, 32 blend modes, per-channel blend/opacity, content and mask effect lists, sources, projections, geometry masks, acyclic anchors, instances, smart presets expanded to subtrees, per-node content-hash bindings with aliases, persisted node ids and a tile dimension. Tile/channel DAG evaluator with VRAM admission, fp32/integer intermediates, quantisation at the boundaries Tier 0 measures; the evaluator profile is versioned in every project. Formulas come from public literature fitted black-box to Painter outputs. See docs/architecture/04-layer-stack-and-compositing.md.

## Alternatives Considered

- Reuse UzEngine's material graph as the document - rejected: RGBA8 prototype without texture inputs
- Flattened raster stack - rejected: not editable
- Whole-texture evaluation - rejected: 8K and multi-set memory

## Consequences

Kernels are frozen only after Tier 0 goldens pass; changing the profile later requires a new profile id and migration.
