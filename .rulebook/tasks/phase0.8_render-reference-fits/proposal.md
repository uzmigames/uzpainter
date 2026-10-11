# Proposal: phase0.8_render-reference-fits

## Why
The noise floor that any Tier 3 exception is derived from has two parts: Iray's Monte-Carlo error at S and UzPainter's own error at S (`docs/architecture/07-preview-and-render-parity.md` §4 step 1), and Phase 0 must publish the first clean-room lobe fits with residuals so Phase 3 knows which material variants and transport features (fp32 RGB, spectral, caustics, path depth) matching Iray needs (`07-…` §3.2–§3.3, §8). The path tracer needs DXR Tier 1.1 and Vulkan ray queries on the owner's GPU (§3.5). Sources are public literature, the MDL specification and the BSD-3 MDL SDK only (Q2, decision 018; decision 002). PRD VIS-06, ARC-06, ARC-10, CLR-01. Child of `phase0.9_render-reference-capture` (`docs/dag.md` P0-FEAS-RENDER, implements D6).

## What Changes
- A feasibility prototype evaluator (not the Phase 3 `painter_iray` deliverable, not shipped) written from the `07-…` §3.1 sources: unidirectional path tracing with next-event estimation and MIS, environment importance sampling, Russian roulette, Owen-scrambled Sobol under a fixed seed; the layered BSDF of §3.3 (GGX with height-correlated Smith and VNDF sampling, Schlick or conductor Fresnel, Lambert or Burley diffuse, coat, sheen, emission, opacity) on the analytic fixtures of `phase0.7_render-reference-captures`.
- First clean-room lobe fits: black-box calibration against the admitted Iray references; every formula choice and fitted constant with its public source and residual in `parity/semantics/iray.json` (independently derived, public); first evidence for spectral vs RGB transport, caustic paths and maximum path depth.
- UzPainter's own error at S (term c): renders at several seeds against the prototype's own k·S render.
- Noise-floor report `parity/reports/phase0/iray-noise-floor.md` (numbers only): per fixture and material region, terms (a), (b) and (c), mean signed Δ with its standard error, statistics after 2×, 4× and 8× downsampling, FLIP as a diagnostic.
- DXR Tier 1.1 (`D3D12_FEATURE_D3D12_OPTIONS5`) and Vulkan ray-query (`VK_KHR_acceleration_structure`, `VK_KHR_deferred_host_operations`, `VK_KHR_ray_query`) support recorded for the owner's GPU in the same report; cross-checked against the `selftest` probe report at G0 because the DAG gives this node no edge to P0-TOOLCHAIN.

## Dependencies
- Prerequisites: `phase0.3_painter-oracle-recorder` (P0-RECORDER), `phase0.5_private-oracle-store` (P0-STORE), `phase0.7_render-reference-captures` (admitted references and Iray noise terms).
- Parent: `phase0.9_render-reference-capture` (P0-FEAS-RENDER).

## Acceptance
Noise floor measured; first clean-room lobe fits published with residuals; ray-tracing probes on the owner's GPU recorded (`docs/dag.md`, P0-FEAS-RENDER; `07-…` §8 Phase 0 evidence).

## Impact
- Affected specs: render-parity
- Affected code: feasibility prototype evaluator (not shipped), `parity/semantics/iray.json`, `parity/reports/phase0/iray-noise-floor.md`
- Breaking change: NO
- User benefit: Phase 3 starts from fitted, sourced lobe models and a measured noise floor instead of assumptions

## Scope change (2026-10-11, decision 050)
The task predates decision 038. Under the fixed render pipeline the prototype renders the admitted references of decision 046 (OCIO Default - sRGB, Save Render 16-bit, the pipeline's two environments), not the analytic profile's Legacy `Linear`; it is a CPU program under `tools/parity/render_fits/`, never shipped and never Tier 3 evidence. Term (c) is measured on the prototype; phase3.6 measures the shipped `painter_iray`'s (c) with the same statistics. Spectral transport is reported as the prototype's sensitivity, and the fixed pipeline's convex fixtures cannot identify caustics or a maximum path depth.
