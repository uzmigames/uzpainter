# Proposal: phase3.7_path-tracer

## Why
VIS-06 and ARC-06 (`docs/prd.md`) make Painter's Iray output the render-parity target, reproduced by UzPainter's own clean-room path tracer `painter_iray` on DX12 DXR (primary) and Vulkan ray tracing (second backend); CLR-01 allows only public literature, the MDL specification and the BSD-3 MDL SDK as sources. Iray is stochastic, so pixel-exact equality is not achievable and every Tier 3 pass exists only as an owner-approved exception (decisions 017 and 018). This is DAG node P3-PATHTRACER (`docs/dag.md`), implementing D6 in `docs/architecture/07-preview-and-render-parity.md` §3–§5 and §8. It bundles transport, materials and the Tier 3 report, so under the DAG task decomposition rule it is split into child tasks; this parent is the integration and acceptance task.

## What Changes
- Integrates `painter_iray`: identical compute kernels with inline ray queries on DX12 (DXR Tier 1.1) and Vulkan (`VK_KHR_ray_query`), written from public literature, the MDL specification and the BSD-3 MDL SDK (nothing from Adobe or Iray internals); environment importance sampling; fixed seed (`07-…` §3).
- Collects the Tier 3 report per `07-…` §4 (noise floor, per-region statistics, cross-backend report) with exception proposals for the owner, under `parity/reports/phase3/` (numbers and hashes only).
- Capability manifest: `painter_iray` leaves the "explicit unavailable" state of P2-PREVIEW only for the fixtures and project configurations covered by owner-approved register entries; every other configuration stays a gap and VIS-06 is not claimed beyond the approved scope (`07-…` §4 step 5).

## Dependencies
- DAG inputs: `phase0.9_render-reference-capture` (P0-FEAS-RENDER), `phase1.4_render-core-layer` (P1-CORE), `phase2.10_pilot-tunic-recovery` (P2-TUNIC), `phase3.3_vulkan-backend-ray-tracing` (P3-VULKAN).
- Mandatory children: `phase3.4_path-tracer-transport`, `phase3.5_path-tracer-materials`, `phase3.6_path-tracer-tier3-report`.
- Downstream (DAG): `phase3.8_gate-g3` (G3), `phase5.4_parity-report` (P5-REPORT).

## Acceptance
DAG gate for P3-PATHTRACER: Tier 3 report produced; every Tier 3 pass and any cross-backend bound exists only as an owner-approved entry in the exception register (decision 017), otherwise Tier 3 is blocked. The parent closes only when all mandatory children pass.

## Impact
- Affected specs: path-tracer
- Affected code: `painter_iray` kernels and acceleration-structure builder on the render core, `display.capture` parity mode, `parity/semantics/iray.json`, Tier 3 comparison tooling, capability manifest
- Breaking change: NO
- User benefit: a headless render that matches Painter's Iray within owner-approved, evidence-backed bounds
