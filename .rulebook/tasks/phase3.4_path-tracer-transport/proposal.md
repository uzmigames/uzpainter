# Proposal: phase3.4_path-tracer-transport

## Why
VIS-06 and ARC-06 (`docs/prd.md`; owner Q2, decision 018) make Painter's Iray output the render-parity target, reproduced by UzPainter's clean-room path tracer `painter_iray` on DX12 DXR and Vulkan ray tracing; VIS-02 and NFR-01 require headless, window-independent capture with explicit camera, resolution and convergence; CLR-01…CLR-03 require implementation from public literature only. Until this node, `painter_iray` is an explicit unavailable capability (`phase2.3_realtime-preview`). This child of P3-PATHTRACER (`phase3.7_path-tracer`) implements the light-transport, scene, camera, display and capture part of D6 (`docs/architecture/07-preview-and-render-parity.md` §3.1, §3.2, §3.4, §3.5, §5, §7).

## What Changes
- Path-tracing compute kernels with inline ray queries, one HLSL source compiled to DXIL (DXR Tier 1.1, SM 6.6) and SPIR-V (`VK_KHR_ray_query`); no shader tables and no ray-tracing pipeline.
- Unidirectional transport written from Kajiya 1986, Veach 1997, PBRT 4th ed. and Burley 2020 (entries of the approved-source index): next-event estimation, multiple importance sampling between BSDF and environment sampling, environment importance sampling from a piecewise-constant 2D distribution, Russian roulette after a fixed minimum depth, maximum path depth from the Phase 0 fit; Owen-scrambled Sobol indexed by (pixel, sample, dimension) under a fixed seed; RGB fp32; per-pixel accumulation in fixed order without floating-point atomics.
- A Lambert lobe as the transport-verification BSDF (the layered material model is `phase3.5_path-tracer-materials`).
- Scene acceleration structures through the backend-neutral builder of `phase3.2_vulkan-ray-tracing`: one BLAS per texture-set mesh, rebuilt only when geometry changes, one TLAS for the scene.
- Painter's documented camera model in its Y-up scene space with the VIS-05 coordinate conversions; environments stored as bytes plus SHA-256 with exposure, rotation and dome from the display preset (a missing environment is an explicit error, RES-03); display transform preserving the project's configuration: Legacy `Linear` and `ACES` tone mapping, OCIO through OpenColorIO with the pinned config and recorded view; an unsupported configuration fails before rendering.
- `display.capture(mode=painter_iray, camera, size, samples, seed, preset)` (`07-…` §5): offscreen RGBA32F accumulation of exactly `samples` samples per pixel, display transform, `TextureReadback`, PNG plus linear EXR, receipt `{revision, evaluator_profile, render_state_digest, mode, backend, adapter, driver, samples, seed, camera, size, display_configuration, hashes}`.
- Feature detection at startup and in `selftest`: a missing feature yields `PathTracerUnavailable{backend, missing}` before any work; no fallback to `painter_viewport`, no software path tracer, WARP never Tier 3 evidence. Transport parameters and their public sources recorded in `parity/semantics/iray.json`.

## Dependencies
- Prerequisites: `phase0.9_render-reference-capture` (P0-FEAS-RENDER: noise floor, first fits, ray-query probes), `phase1.4_render-core-layer` (P1-CORE), `phase2.10_pilot-tunic-recovery` (P2-TUNIC), `phase3.3_vulkan-backend-ray-tracing` (P3-VULKAN).
- Parent: `phase3.7_path-tracer`. Unblocks `phase3.5_path-tracer-materials` and `phase3.6_path-tracer-tier3-report`.

## Acceptance
`painter_iray` captures run headless on DX12 and Vulkan with identical kernels; transport verification fixtures with the Lambert lobe are unbiased against their analytic values; repeatability (same build, adapter, driver, seed and sample count) is measured and reported; DXR and Vulkan outputs of the transport fixtures are compared with every difference reported; a missing feature yields `PathTracerUnavailable` before any work.

## Impact
- Affected specs: path-tracer
- Affected code: path-tracer kernels and host, scene acceleration structures, camera, environment sampling, display transform, `painter_iray` capture and receipts, selftest feature detection, `parity/semantics/iray.json`
- Breaking change: NO
- User benefit: `painter_iray` renders become available headlessly on both GPU backends
