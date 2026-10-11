# 1. Acceptance criterion: output parity with Substance Painter

**Status**: accepted
**Date**: 2026-10-10

## Context

Stated by the product owner (André) on 2026-10-10 while the docs foundation was being written. UzPainter must fully replace Substance in the Assets3D pipeline, whose painting recipes (Docs/Library; `Docs/Biblioteca` when recorded, renamed by the Assets3D reorganization of 2026-10-11) and the Painter × Blender render comparison standard were tuned against Painter's output.

## Decision

UzPainter is considered satisfactory only when, given the same sequence of instructions, it produces the same texture result and the same render result as Adobe Substance 3D Painter. Output parity, not merely feature parity, is the bar.

## Alternatives Considered

- Feature parity only (same API surface, free to differ in output) — rejected: would force re-tuning every recipe and break the render comparison standard
- Approximate parity with documented tolerances — deferred: tolerances may be defined later per map type, but the target remains identical output

## Consequences

Every design choice (layer compositing math, blend modes, color management/OCIO, baker algorithms, generators and smart materials, export channel packing, preview lighting and tone mapping) is judged by whether it reproduces Painter's result. Acceptance tests replay a recorded instruction sequence in both tools and compare textures (per-channel diff) and renders (perceptual metric). Divergence is a bug, not a style choice.
