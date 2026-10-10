# 18. D6 Render parity: Painter's Iray as the target through a clean-room path tracer on DXR and Vulkan ray tracing

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Supersedes decision 008, which made a clean-room realtime painter_viewport pass the render-parity target while owner question Q2 (viewport or Iray) was open. Owner answer of 2026-10-10 (Q2): Painter's Iray output is the render-parity target. The implementation route stays clean room (decision 002), and UzPainter has no UzEngine dependency (decision 021).

## Decision

The render-parity target is Painter's Iray, not the realtime viewport. UzPainter implements a clean-room path tracer (painter_iray) from public path-tracing literature, the NVIDIA MDL specification and the open-source MDL SDK (BSD-3-Clause), with lobe definitions from the OpenPBR and glTF 2.0 PBR specifications; nothing is taken from Adobe or Iray internals. Backends: DX12 DXR (primary) and Vulkan ray tracing (second backend on Windows), running the same kernels. References are captured from Painter's Iray on the owner's machine into the private oracle store, with scene, camera, environment, sample count and seed fixed wherever Painter exposes them; only converged references count. Iray is stochastic, so pixel-exact equality is not achievable: Tier 3 compares against converged references and the measured oracle noise floor, and passes only through an owner-approved exception in the Q1 register (decision 017); without one it is blocked. The realtime painter_viewport pass stays as the human preview and a fast check, never as parity evidence. The UzEngine export preset is validated by an external UzEngine consumer fixture, not by a linked renderer. See docs/architecture/07-preview-and-render-parity.md.

## Alternatives Considered

- Realtime painter_viewport pass as the parity target (decision 008) - rejected by the owner (Q2)
- Port of Adobe's shader library or anything from Iray internals - rejected (decision 002)
- UzEngine SceneRenderer as target or preview - rejected: different post chain and zero engine dependency (decision 021)

## Consequences

Phase 0 qualifies the Iray capture procedure and publishes a noise-floor report; Phase 3 builds the path tracer on both ray-tracing backends and produces the Tier 3 report with the exception proposals the owner must approve. The parity render needs a ray-tracing GPU. Texture tiers 0-2 stay exact; a render exception never relaxes them.
