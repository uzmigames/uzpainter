# 8. D6 Render parity: clean-room painter_viewport pass as the target; engine_preview as consumer test

**Status**: superseded
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Iray is out of reach; UzEngine's deferred renderer has its own post chain. The owner chose the clean-room implementation route (decision 002); the render reference (viewport vs Iray) is still owner question Q2.

## Decision

A UzPainter-owned forward painter_viewport pass on UzEngine RHI implemented from public literature (OpenPBR, glTF 2.0 PBR, split-sum or importance-sampled GGX, Smith masking, Schlick, Burley, SH irradiance) and calibrated black-box against private Painter captures is the render-parity target; shader identity, environment hash, display state and camera are captured from the pilot projects through the documented API. engine_preview (UzEngine SceneRenderer) validates the UzEngine preset only. A direct port of Adobe's shipped shader library was rejected by the owner. See docs/architecture/07-preview-and-render-parity.md.

## Alternatives Considered

- UzEngine SceneRenderer as the parity target - rejected: different post chain
- Path-traced preview comparable to Cycles/Iray - rejected: not the reference
- Direct GLSL-to-HLSL port - rejected by the owner (decision 002)

## Consequences

Residuals per lobe measured in Phase 0/2; if the owner requires Iray equality the gate is reported unresolved. Proposed until Q2 confirms the viewport reference.
