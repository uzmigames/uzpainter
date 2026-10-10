## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase5.1_performance-budgets, phase5.2_packaging, phase5.4_parity-report, phase5.5_clean-history

## 2. Joined items
- [ ] 2.1 G4 accepted and its gate record present in `parity/reports/phase4/gate-g4.md` (reached through phase5.1_performance-budgets)
- [ ] 2.2 P5-PERF accepted (`phase5.1_performance-budgets`): budgets published before the release build was frozen
- [ ] 2.3 P5-PACKAGE accepted (`phase5.2_packaging`): release folder runs offline without SDKs on a clean Windows 10/11 x64 machine
- [ ] 2.4 P5-REPORT accepted (`phase5.4_parity-report`) with its children `phase5.2_parity-report-tiers`, `phase5.2_parity-report-mcp-conformance`, `phase5.3_parity-report-capability-gaps`
- [ ] 2.5 P5-HISTORY accepted (`phase5.5_clean-history`): clean history verified against the released tree

## 3. Criteria evidence
- [ ] 3.1 Tiers 0–2 green or covered by approved owner exceptions; Tier 3 passed through approved exceptions only; exception register published
- [ ] 3.2 Every in-scope capability `supported` or covered by an explicit owner scope decision; no `blocking` gap in the gap register; no "full replacement" claim while a required gap is open
- [ ] 3.3 Full Python-disabled MCP conformance accepted for every row of the requirement-to-typed-operation matrix
- [ ] 3.4 The three pipeline scripts run unchanged under `UzPainter.exe run` on the frozen build; worker-fault recovery, lost-acknowledgement retry and project-store fault injection pass on the frozen build
- [ ] 3.5 Export presets validated by their consumers (INT-11 matrix, Unreal Engine 5.6, external UzEngine fixture, glTF) with SpecularWeight and other consumer gaps reported
- [ ] 3.6 Size census vs the matched `.spp` reported per project against the 10 % candidate budget, and the budget ratified by the owner with the census in hand
- [ ] 3.7 Build identity: `phase5.2_packaging`, `phase5.4_parity-report` and `phase5.5_clean-history` name the same build hash, dependency lock and released tree
- [ ] 3.8 Publication criteria of `docs/licensing-and-clean-room.md` §5 hold: clean history, inventory and attribution complete, no Adobe-derived content, private oracle store excluded
- [ ] 3.9 Settling check: no gate fixture marked `not_migratable` without an owner scope decision in the capability manifest and gate record
- [ ] 3.10 Assets3D governance amendment of `phase3.1_assets3d-cutover` signed and referenced

## 4. Gate record
- [ ] 4.1 Capability manifest regenerated and its version recorded
- [ ] 4.2 Gate record written to `parity/reports/phase5/gate-g5.md` (numbers and hashes only)
- [ ] 4.3 Owner signs the gate record
- [ ] 4.4 Owner authorisation to make `uzmigames/uzpainter` public recorded (explicit, at execution time, naming the verified tree hash)
- [ ] 4.5 Repository made public and the release published from the verified build, only after 4.3 and 4.4
- [ ] 4.6 Every other Phase 5 task archived in `.rulebook` (roadmap rule 3)

## 5. Acceptance
- [ ] 5.1 DAG gate G5 met: all joined items accepted; every in-scope capability supported or covered by an owner scope decision; no full-replacement claim with an open required gap; full Python-disabled MCP conformance accepted; owner signs

## 6. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 6.1 Update or create documentation covering the implementation
- [ ] 6.2 Write tests covering the new behavior
- [ ] 6.3 Run tests and confirm they pass
