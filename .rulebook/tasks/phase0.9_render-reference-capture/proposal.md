# Proposal: phase0.9_render-reference-capture

## Why
The owner made Painter's Iray the render-parity target (Q2, decision 018, superseding 008). Iray is stochastic and its seed is not exposed, so pixel-exact equality is not achievable; Tier 3 can pass only through an owner-approved exception derived from a measured noise floor (Q1, decision 017). Many Iray settings are not in the public Python API and are marked "not confirmed — Phase 0 probe" in `docs/architecture/07-preview-and-render-parity.md` §2.1; no render golden may be admitted before the capture procedure is qualified (`14-parity-testing.md` §2). PRD VIS-06, ARC-06, ARC-09, ARC-10, ACC-01, CLR-01, CLR-05; `07-…` §2, §4, §8; `docs/dag.md` P0-FEAS-RENDER, implements D6.

## What Changes
This parent is the integration and acceptance task for three children:
- `phase0.6_render-reference-procedure`: an evidence-backed answer for every "not confirmed" row of `07-…` §2.1 (and bump vs displacement, §3.3); the settings sheet and operator form; the capture procedure of §2.2 qualified, including readiness and current-frame verification, with Save Render or the named fallback.
- `phase0.7_render-reference-captures`: converged references per analytic fixture of the proposed §2.3 profile, recorded twice in separate Painter sessions plus once at k·S samples (blobs private, hashes public); the Iray-side noise terms (run-to-run difference; Monte-Carlo error at S); the analytic fixture values proposed to the owner for ratification.
- `phase0.8_render-reference-fits`: first clean-room lobe fits with residuals in `parity/semantics/iray.json`, written from the `07-…` §3.1 sources through a feasibility prototype evaluator (not the Phase 3 path tracer); UzPainter's own error at S; the noise-floor report; DXR Tier 1.1 and Vulkan ray-query probe results on the owner's GPU.

## Dependencies
- Prerequisites: `phase0.3_painter-oracle-recorder` (P0-RECORDER), `phase0.5_private-oracle-store` (P0-STORE).
- Children (must pass first): `phase0.6_render-reference-procedure`, `phase0.7_render-reference-captures`, `phase0.8_render-reference-fits`.
- Successors: `phase3.7_path-tracer` (P3-PATHTRACER) and gate `phase0.10_gate-g0` (G0). The DAG gives this node no edge to P0-TOOLCHAIN, so its GPU probe results are recorded independently and cross-checked against the `selftest` probe report at G0.

## Acceptance
Procedure qualified; references admitted; noise floor measured; fixture values proposed to the owner for ratification (`docs/dag.md`, P0-FEAS-RENDER). Contributes to G0: "Iray capture procedure qualified and references admitted with their noise floor" (`docs/roadmap.md`).

## Impact
- Affected specs: render-parity
- Affected code: recorder Iray path usage, feasibility prototype (not shipped), `parity/manifests/`, `parity/semantics/iray.json`, `parity/reports/phase0/`
- Breaking change: NO
- User benefit: Phase 3 builds the path tracer against qualified references and a known noise floor
