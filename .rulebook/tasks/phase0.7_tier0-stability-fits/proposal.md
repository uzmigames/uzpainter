# Proposal: phase0.7_tier0-stability-fits

## Why
Exact equality with Painter is the acceptance rule (decision 017, owner Q1), so before any compositor kernel is frozen two things must be known: whether Painter reproduces itself (oracle stability, always reported separately from equality — `docs/architecture/14-parity-testing.md` §1) and which formulas reproduce the recorded Tier 0 goldens (`04-layer-stack-and-compositing.md` §3, §4, §6, §9). Under the clean-room policy the formulas are written from public sources and their parameters fitted black-box to the goldens; only the fitted formula, its public source and its residual are published, never the recorded values (`docs/licensing-and-clean-room.md` §1.6, §2 procedure; PRD CLR-01, CLR-05). G0 requires "first `parity/semantics/*.json` fits with residuals" and the P0-TIER0 gate requires "stability classified; fits published" (`docs/roadmap.md`, `docs/dag.md`). Child of `phase0.8_tier0-goldens` (implements D3, D5, D9, D13).

## What Changes
- Oracle-stability report `parity/reports/phase0/tier0-stability.md` (numbers and hashes only): for every Tier 0 golden of `phase0.6_tier0-semantics-goldens`, `phase0.6_tier0-defaults-templates` and `phase0.6_tier0-api-probes`, the comparison of its ≥ 2 recordings (same session; after save/reopen), aggregated per channel type classified by measured storage format (not by name); classification `stable` (byte-identical recordings, or equal readbacks) or `unstable` with max |Δ|, mean |Δ| and differing-texel count; unstable goldens are not admitted as exact goldens and their statistics become exception evidence (`14-…` §5).
- First clean-room fits under `parity/semantics/`, each entry `{formula, parameters, colour space, clamping, public source (title, section), golden hashes used, residual (max |Δ|, mean |Δ|, differing-texel count at storage precision), evaluator_profile}`:
  - `blend-modes.json`: the 32 documented `BlendingMode` members fitted from the value/opacity sweeps, candidates from W3C Compositing and Blending Level 1, the PDF 1.7 reference and Barré-Brisebois and Hill 2012 for the normal-map modes.
  - `evaluator-profile.json`: the evaluator profile `painter-12.1-<profile-id>` settled by the three-1/3-opacity-fills experiment (per-layer vs end quantisation; encoded vs linear blending of sRGB8 channels).
  - `srgb-transfer.json`: the transfer function fitted to the Tier 0 ramps against IEC 61966-2-1, with any deviation recorded.
  - `height-to-normal.json`: both height→normal methods (kernel footprint, scaling, edge handling, strength) fitted from the height ramps.
  - `resampling.json` (the `BilinearHQ` kernel) and `ao-mixed.json` (the `AO_Mixed` operator), the two other formula fits named by `04-…` §4 and §6.
- Settlement table in the stability report: every item of `04-…` §9 marked settled or not settled, with the golden hashes and residual that decide it; a fit that does not reproduce its goldens exactly is reported as an open item (release gap or exception proposal), never as settled.
- Fitting scripts under `tools/parity/fit/` run on the owner's machine against the private store; published files pass the repository guard and the public schema.

## Dependencies
- Prerequisites: `phase0.3_painter-oracle-recorder` (P0-RECORDER), `phase0.5_private-oracle-store` (P0-STORE), `phase0.6_tier0-semantics-goldens`, `phase0.6_tier0-defaults-templates`, `phase0.6_tier0-api-probes`.
- Parent: `phase0.8_tier0-goldens` (P0-TIER0) closes only when this child passes.
- Successors: `phase0.10_gate-g0` (fits published), `phase1.14_compositor-core` (P1-COMPOSITOR freezes kernels from these fits).

## Acceptance
Every Tier 0 golden's recordings compared and its stability classified per channel type; the first fits published in `parity/semantics/` with public source and residual; the settlement table covers every `04-…` §9 item; no recorded Painter value appears in any published file (guard and schema pass). Contributes to the P0-TIER0 gate "stability classified; fits published" (`docs/dag.md`) and G0 "first `parity/semantics/*.json` fits with residuals" (`docs/roadmap.md`).

## Impact
- Affected specs: tier0
- Affected code: `tools/parity/fit/` (new), `parity/semantics/*.json`, `parity/reports/phase0/tier0-stability.md`
- Breaking change: NO
- User benefit: compositor kernels are written against formulas proven on Painter's own outputs, and Painter's own instability is known before any difference is judged
