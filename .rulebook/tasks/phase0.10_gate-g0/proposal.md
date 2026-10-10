# Proposal: phase0.10_gate-g0

## Why
Every phase ends at an evidence gate that joins all mandatory acceptance items of the phase and that no single work package can close by itself (`docs/roadmap.md` rules 2–3; `docs/dag.md` gate rule; decision 016, D14). G0 "Contract frozen" is the first gate: Phase 1 may build the foundation only on a frozen parity contract, admitted Tier 0 goldens, a standalone vendored render core, a green hardware selftest and published feasibility reports (PRD ACC-01, G-04, ARC-07…ARC-10, CLR-05, OWN-02; `docs/dag.md` G0, implements D14).

## What Changes
- Gate record `parity/reports/phase0/gate-g0.md` (numbers and hashes only; oracle blobs stay in the private store) listing, for each joined item, its accepted task, evidence paths and hashes, and the roadmap G0 clauses:
  - approved-source index published;
  - Tier 0 goldens admitted (blobs private, hashes public); first `parity/semantics/*.json` fits with residuals;
  - vendored render core builds standalone;
  - hardware `selftest` green on the owner's machine; WARP probe completed and reported (WARP failure leaves that path unsupported and does not fail G0);
  - feasibility reports published (procedural; normal convention);
  - Iray capture procedure qualified and references admitted with their noise floor; analytic fixture values proposed to the owner.
- Cross-check of the DXR Tier 1.1 / Vulkan ray-query results recorded by `phase0.8_render-reference-fits` against the `selftest` probe report of `phase0.7_toolchain-probes`.
- `.rulebook` archive of every Phase 0 task (roadmap rule 3). No capability manifest exists before `phase1.3_document-model` delivers its generator; the gate record states this.
- Revision of the Phase 1 duration Hypothesis at the gate (owner Q14).

## Dependencies
- Joined items (must be accepted): `phase0.1_approved-source-index` (P0-SOURCES), `phase0.8_tier0-goldens` (P0-TIER0), `phase0.8_toolchain-slice` (P0-TOOLCHAIN), `phase0.6_procedural-feasibility` (P0-FEAS-PROC), `phase0.9_render-reference-capture` (P0-FEAS-RENDER), `phase0.9_normal-convention-fixture` (P0-NORMAL). The other Phase 0 items reach G0 through them: `phase0_owner-decisions`, `phase0.2_parity-contract`, `phase0.3_painter-oracle-recorder`, `phase0.5_private-oracle-store`, `phase0.5_vendor-render-core`.
- Previous gate: none (G0 is the first gate).
- Successor: `phase1.26_gate-g1` (G1 requires G0).

## Acceptance
All joined items accepted (`docs/dag.md`, G0), with every G0 clause of `docs/roadmap.md` evidenced in the gate record.

## Impact
- Affected specs: gates
- Affected code: `parity/reports/phase0/gate-g0.md`
- Breaking change: NO
- User benefit: Phase 1 starts on a frozen contract with recorded evidence; the evidence for the whole phase is in one record
