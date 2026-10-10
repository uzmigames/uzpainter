# Proposal: phase0.8_tier0-goldens

## Why
The compositor kernels, baking defaults and facade quirks cannot be frozen until Painter's undocumented semantics are observed: `docs/architecture/04-layer-stack-and-compositing.md` §9 lists what Tier 0 must settle before the kernels are frozen, `06-baking.md` §2 requires the baking defaults to be captured on a fresh Painter 12.1.0 project, and `10-python-api.md` §3–§4 makes every `supported` symbol and every output-changing quirk depend on a Tier 0 probe. Exact equality is the rule (Q1, decision 017), so oracle stability must be measured before a golden is admitted (`14-parity-testing.md` §1–§3, §9). PRD: ARC-04, ARC-13, LAY-01, LAY-04, LAY-05, LAY-10, MAT-05, PRJ-05, BAK-02, G-04, CLR-01, CLR-05; `docs/dag.md` P0-TIER0, implements D3, D5, D9, D13.

## What Changes
This parent is the integration and acceptance task for four children:
- `phase0.6_tier0-semantics-goldens`: private goldens for the `04-…` §9 list on UzmiGames synthetic meshes.
- `phase0.6_tier0-defaults-templates`: private captures of the baking defaults and of per-template channel sets and storage formats.
- `phase0.6_tier0-api-probes`: private API-probe goldens (set→get readback, mask `None`, insertion rules, active-channel reset, event order).
- `phase0.7_tier0-stability-fits`: the oracle-stability report and the first `parity/semantics/*.json` fits with residuals (public numbers).
Blobs live in the private store; only their hashes enter `parity/manifests/`. Tier 0 reference capture is separate from the acceptance of the Phase 1 compositor subset: each later package names the Tier 0 tests it owns (`docs/dag.md`, task decomposition rule).

## Dependencies
- Prerequisites: `phase0.3_painter-oracle-recorder` (P0-RECORDER), `phase0.5_private-oracle-store` (P0-STORE).
- Children (must pass first): `phase0.6_tier0-semantics-goldens`, `phase0.6_tier0-defaults-templates`, `phase0.6_tier0-api-probes`, `phase0.7_tier0-stability-fits`.
- Successors: `phase1.14_compositor-core` (P1-COMPOSITOR) and gate `phase0.10_gate-g0` (G0).

## Acceptance
Each golden recorded ≥ 2×; stability classified; fits published (`docs/dag.md`, P0-TIER0). Contributes to G0: "Tier 0 goldens admitted (blobs private, hashes public); first `parity/semantics/*.json` fits with residuals" (`docs/roadmap.md`).

## Impact
- Affected specs: tier0
- Affected code: `parity/manifests/` (hashes), `parity/semantics/` (fits), `parity/reports/phase0/` (stability); private store contents
- Breaking change: NO
- User benefit: Phase 1 kernels are written against measured Painter semantics instead of guesses
