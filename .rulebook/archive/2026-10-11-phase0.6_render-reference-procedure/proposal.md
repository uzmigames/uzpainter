# Proposal: phase0.6_render-reference-procedure

## Why
Painter's Python API exposes only part of Iray's state: camera, environment resource, colour LUT, tone mapping and Iray mode are documented, while sample limits, convergence state, environment and dome settings, MDL material parameters, denoiser, seed and the Save Render encoding are "not confirmed — Phase 0 probe" in `docs/architecture/07-preview-and-render-parity.md` §2.1 (also bump vs displacement, §3.3). No render golden may be admitted before the capture procedure, including readiness and current-frame verification, is qualified (`14-parity-testing.md` §2; PRD ARC-09, VIS-06, CLR-05; decisions 018, 022). A setting that cannot be fixed or read must be recorded as `uncontrolled` and named by any exception that relies on it (07 §2.1, §4). Child of `phase0.9_render-reference-capture` (`docs/dag.md` P0-FEAS-RENDER, implements D6).

Scope change (owner, 2026-10-11, decision 038): the procedure covers only the fixed Assets3D render pipeline (`Render-Comparison-Standard.json`); settings outside it are pinned and answered `not_required`.

## What Changes
- Probe evidence (private, hashes public) and an answer per "not confirmed" row of `07-…` §2.1: where Iray applies the colour LUT; the colour-management display/view transform; whether Min/Max Sample, Max Time, Caustic Sampler, Firefly Filter and the resolution override persist or can be read back; a programmatic readiness check; the Viewer and MDL Settings; which display settings change the Iray image; the default-MDL material parameters; the denoiser; seed repeatability; the Save Render format, bit depth and whether the display transform is baked in; height as bump or displacement (§3.3). Unfixable or unreadable settings marked `uncontrolled`.
- The settings sheet format and the operator form used by the recorder's Iray path.
- The qualified capture procedure (versioned), executing `07-…` §2.2 steps 1–7: documented settings applied and read back; operator panel entries with panel images; convergence with Min = Max Sample = S and Max Time above the time S samples take, captured only when Status is Done, Iterations equals S and time is below Max Time; Save Render at the override resolution, or the named fallback (external 1:1 observation of the displayed frame, overlays excluded, display-referred 8-bit) if Save Render proves unusable; current-frame verification (saved image postdates the last settings change and convergence; silhouette matches the fixture projected from the recorded camera); storage per 14 §6.
- Procedure and answers documented in `parity/reports/phase0/iray-capture-procedure.md` (no Painter pixels; settings evidence stays private).

## Dependencies
- Prerequisites: `phase0.3_painter-oracle-recorder` (P0-RECORDER), `phase0.5_private-oracle-store` (P0-STORE).
- Parent: `phase0.9_render-reference-capture` (P0-FEAS-RENDER). Sibling that depends on this task: `phase0.7_render-reference-captures`.

## Acceptance
Every "not confirmed" row answered with evidence; procedure qualified (`docs/dag.md`, P0-FEAS-RENDER first clause; `07-…` §8).

## Impact
- Affected specs: render-parity
- Affected code: recorder Iray path configuration, `parity/reports/phase0/iray-capture-procedure.md`
- Breaking change: NO
- User benefit: every render reference is captured the same documented way, with known blind spots
