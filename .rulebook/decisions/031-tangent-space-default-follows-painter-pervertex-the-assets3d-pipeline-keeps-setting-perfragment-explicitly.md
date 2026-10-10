# 31. Tangent-space default follows Painter (PerVertex); the Assets3D pipeline keeps setting PerFragment explicitly

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase0.9_normal-convention-fixture

## Context

P0-NORMAL (phase0.9_normal-convention-fixture, 2026-10-10) measured Painter's default as PerVertex, while 12-mesh-import.md stated a PerFragment default taken from the pipeline's explicit setting. Decision 001 (same instructions give the same output as Painter) settles it: an instruction sequence that omits the mode must produce Painter's default.

## Decision

When a project does not set the normal-map tangent-space mode, UzPainter uses PerVertex, which is Painter 12.1.0's observed default (an unset project exports byte-identical to an explicit PerVertex project). PerFragment is used whenever the caller sets it, as the Assets3D pipeline does. docs/architecture/12-mesh-import.md is corrected to say so.

## Consequences

phase1 mesh-loader/tangent tasks implement PerVertex as the unset default and PerFragment on request; both modes are calibrated against Painter within 1 code at 16 bits (parity/semantics/tangent-frame.json). Green channel is OpenGL +v; Painter's DirectX bake equals 65535 - green.
