# 7. D5 Baking: Embree CPU bakers first, DXR later behind one baker contract

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Native high-poly bake is an owner requirement; UzEngine checks only DXR Tier 1.0 while RayQuery needs Tier 1.1/SM6.5; the tool must run on any Windows machine (05-resolution.md D5).

## Decision

Ten MeshMapUsage bakers behind IBaker; EmbreeBaker (upstream Embree 4.x, pinned build, deterministic sample addressing and reduction) is the v1 reference; DxrBaker is added later after capability checks and qualification. Painter's property model and parameter names are mirrored via the documented discovery API; current defaults are captured from a fresh Painter project. External mesh maps remain first-class; evidence maps (raw, hits, coverage, misses) never alter compatible maps; publication is atomic per input revision; linked-set settings are transactional. See docs/architecture/06-baking.md.

## Alternatives Considered

- DXR-only baking - rejected: Tier 1.1 hardware requirement
- Custom CPU BVH (Astra round 1) - rejected in favour of Embree
- Both backends from day one - deferred

## Consequences

New vendored dependency; cross-machine bit identity measured, not promised; Tier 2b against Painter's CPU baker.
