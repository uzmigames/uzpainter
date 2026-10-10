# 6. D4 Procedural content: certified UzPainter families plus project-private snapshots; no Adobe runtime or content

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Painter's generators, grunges and smart materials run on Adobe's proprietary engine; locked and delivered recipes depend on them. The owner closed the legal route on 2026-10-10 (decision 002: clean room, Apache-2.0).

## Decision

IProceduralBackend seam with two backends: UzPainter's own HLSL resource families written from public literature and calibrated black-box against private Painter oracles (mesh-map generators, Sharpen, grunges, materials, the six smart masks and two smart materials used by the recipes; smart-preset structures observed through the documented API and re-authored), and project-private frozen snapshots with a full output signature for migrating approved assets (never shipped, never editable). A licensed Substance runtime adapter and shipping Painter-derived captures were considered and rejected by the owner. Painter asset names survive only as an internal alias table. See docs/architecture/05-procedural-content.md.

## Alternatives Considered

- Licensed Substance runtime adapter - rejected by the owner
- Shipping captured Adobe procedural outputs - rejected by the owner
- 3D masks only, no procedurals - rejected: fails same-functionality and the locked bracer recipe

## Consequences

Calibration cost per asset; a non-zero residual needs an owner exception; arbitrary .sbsar stays unsupported.
