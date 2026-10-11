# Proposal: phase0.7_render-reference-captures

## Why
Tier 3 compares UzPainter's path tracer with converged Iray references; Iray is stochastic, so each reference must be recorded twice in separate Painter sessions plus once at k·S samples to measure Iray's own run-to-run difference and Monte-Carlo error before any exception can be derived (Q1 decision 017, Q2 decision 018; `docs/architecture/07-preview-and-render-parity.md` §2.2 step 6, §2.3, §4 step 1; `14-parity-testing.md` §2–§3). The analytic fixture profile is proposed, not ratified: Q2 fixed the target renderer, not these values. PRD VIS-06, ARC-06, ARC-09, CLR-05. Child of `phase0.9_render-reference-capture` (`docs/dag.md` P0-FEAS-RENDER, implements D6).

Scope change (2026-10-11, decision 046 after the owner's decision 038): references are captured only under the fixed Assets3D render pipeline (OCIO with Default - sRGB, Studio White Soft for v2, the `ref_match` HDRI as a session resource at rotations 0 and 180, Save Render 16-bit at 1200x1200, 256 samples, k = 4). The Legacy `Linear` profile, the constant-colour, bright-patch and Poly Haven environments and the white furnace below are superseded; manifests are one per golden under the current envelope. The list below is the original proposal.

## What Changes
- UzmiGames-authored analytic fixtures of the proposed profile (`07-…` §2.3): meshes (sphere, plane, bevelled cube) with constant-parameter materials sweeping base colour, metallic and roughness, a white-furnace fixture and single-channel perturbations (normal, height, emissive, opacity) as listed in §3.3; environments (constant colour, a single bright patch, a Poly Haven CC0 HDRI) imported through the documented resource import; 1200×1200 override resolution; Min = Max Sample S = 256, Max Time 3600 s; Caustic Sampler and Firefly Filter off; denoiser off if a control exists; Infinite Sphere dome, exposure 0, rotation 0, no ground, shadows off, Clear Color background, post effects off; Legacy colour management with `Linear` tone mapping; `aperture = 0`.
- Public manifest `parity/manifests/phase0/iray-references.json`: fixture descriptions, settings sheets, procedure version, `uncontrolled` settings and the SHA-256 of every private record.
- Private references (store only): per fixture two converged references in separate Painter sessions (after a restart) and one at k·S samples with k fixed here; settings readbacks, panel evidence and operator entries.
- Iray noise terms per fixture and material region, numbers only, in `parity/reports/phase0/iray-references.md`: (a) run-to-run difference between the session-separated references (the oracle-stability result) and (b) Iray's Monte-Carlo error at S from the S reference against the k·S reference.
- The analytic fixture values proposed to the owner for ratification (recorded as a proposal in the report).

## Dependencies
- Prerequisites: `phase0.3_painter-oracle-recorder` (P0-RECORDER), `phase0.5_private-oracle-store` (P0-STORE), `phase0.6_render-reference-procedure` (qualified procedure).
- Parent: `phase0.9_render-reference-capture` (P0-FEAS-RENDER). Sibling that depends on this task: `phase0.8_render-reference-fits`.

## Acceptance
References admitted (blobs private, hashes public); Iray noise terms measured; fixture values proposed to the owner for ratification (`docs/dag.md`, P0-FEAS-RENDER clauses 2–4 in part; the noise floor completes in `phase0.8_render-reference-fits`).

## Impact
- Affected specs: render-parity
- Affected code: fixture assets and manifests under `parity/manifests/`, report under `parity/reports/phase0/`; private store contents
- Breaking change: NO
- User benefit: the Tier 3 oracle and its own uncertainty are known before the path tracer is built
