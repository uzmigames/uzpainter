# Proposal: phase5.6_gate-g5

## Why
Gate G5 "Release" closes Phase 5 and the v1 roadmap (`docs/roadmap.md`, `docs/dag.md` gate rule): it joins every mandatory Phase 5 item, requires G4, and cannot be closed by any single work package carrying its evidence; because every gate requires the previous one, G5 cannot be reached without every mandatory node (optional `phase4.3_dxr-baker` is not a predecessor). G5 is the release criterion set of `docs/prd.md` §18 and the publication criteria of `docs/licensing-and-clean-room.md` §5: Tiers 0–2 green or covered by approved owner exceptions and Tier 3 passed through approved exceptions (ARC-10, decisions 017 and 018); every in-scope capability supported or covered by an explicit owner scope decision with no "full replacement" claim while a required gap is open (ARC-03, OWN-01, OWN-03, decision 019); full Python-disabled MCP conformance for every required operation family (ARC-14, decision 025); the one-folder distribution running offline without SDKs (OWN-08, decision 022); the size census against the 10 % candidate budget (OWN-07, NFR-04, decision 024); clean history verified against the released tree (decision 027); and the owner's signature. Implements D14 (`docs/roadmap.md`, `docs/dag.md`).

## What Changes
- Gate record `parity/reports/phase5/gate-g5.md` (numbers and hashes only): each joined item with its acceptance evidence, each G5 and `prd.md` §18 criterion with the report that proves it, the exception entries and owner scope decisions relied on, the `not_migratable` settling check, the frozen build hash and dependency lock, the regenerated capability manifest version and the owner's signature.
- Regenerated capability manifest at the gate (roadmap rule 3).
- After the owner signs and `phase5.5_clean-history` has passed, the repository `uzmigames/uzpainter` is made public under the owner's explicit authorisation, and the release is published from the verified build.

## Dependencies
- DAG inputs (joined items): `phase5.1_performance-budgets` (P5-PERF), `phase5.2_packaging` (P5-PACKAGE), `phase5.4_parity-report` (P5-REPORT), `phase5.5_clean-history` (P5-HISTORY).
- Previous gate reaching G5 through those inputs: `phase4.6_gate-g4` (G4), and through it every earlier gate.
- Children of `phase5.4_parity-report` reaching the gate through it: `phase5.2_parity-report-tiers`, `phase5.2_parity-report-mcp-conformance`, `phase5.3_parity-report-capability-gaps`.

## Acceptance
DAG gate G5: every in-scope capability supported or covered by an owner scope decision; no "full replacement" claim while a required gap is open (Q5); full Python-disabled MCP conformance accepted for every required operation family; owner signs. Roadmap G5 criteria, each evidenced in the gate record: Tiers 0–2 green or covered by approved owner exceptions and Tier 3 passed through approved exceptions; distribution runs offline without SDKs; size census vs matched `.spp` reported against the 10 % candidate budget; clean history verified against the released tree, with the private history replaced by an owner-authorised force push only at the moment the repository is made public.

## Impact
- Affected specs: `gates` (G5)
- Affected code: none; `parity/reports/phase5/gate-g5.md`, capability manifest regeneration, `.rulebook/` archive of the Phase 5 tasks, repository visibility
- Breaking change: NO
- User benefit: an owner-signed, evidence-backed v1 release and a public repository free of pre-sanitisation text and private oracle data
