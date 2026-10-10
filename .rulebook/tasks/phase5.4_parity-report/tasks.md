## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase4.6_gate-g4, phase3.7_path-tracer, phase5.1_performance-budgets; sanitisation items §2 of phase5.5_clean-history (paraphrase, release-tree scan) done (item-level); frozen release build hash and dependency lock recorded
- [ ] 1.2 Child accepted: phase5.2_parity-report-tiers
- [ ] 1.3 Child accepted: phase5.2_parity-report-mcp-conformance
- [ ] 1.4 Child accepted: phase5.3_parity-report-capability-gaps

## 2. Implementation
- [ ] 2.1 Budgets re-confirmed on the frozen build: `phase5.1_performance-budgets` measurements re-run on the frozen build hash and compared with the published budgets
- [ ] 2.2 Build identity check: the three child results, the budget re-confirmation and `phase5.2_packaging` name the same build hash and dependency lock
- [ ] 2.3 Release parity record `parity/reports/phase5/parity-report.json` (numbers and hashes only) referencing the child reports, the exception register, the capability manifest and the reopen rule

## 3. Tests
- [ ] 3.1 Build identity check fails when one child result names a different build hash or lock
- [ ] 3.2 Integration check fails when any child reports a failing tier, a blocked Tier 3 comparison without an approved entry, a failing conformance row or a `blocking` gap
- [ ] 3.3 Repository guard over `parity/reports/phase5/`: no file whose hash is in the private store index; schema validation on the hosted CPU lane

## 4. Acceptance
- [ ] 4.1 Tiers 0–2 green or covered by approved exceptions; Tier 3 passed through approved exceptions (blocked otherwise); full Python-disabled MCP conformance passes for every row of the requirement-to-typed-operation matrix; same build hash and lock as `phase5.2_packaging`; gate evidence attached to `phase5.6_gate-g5`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
