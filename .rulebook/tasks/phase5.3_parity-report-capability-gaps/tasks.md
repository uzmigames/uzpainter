## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase4.6_gate-g4, phase3.7_path-tracer, phase5.1_performance-budgets; frozen release build hash recorded

## 2. Implementation
- [ ] 2.1 Regenerate the capability manifest from the frozen build (`capabilities.json`, `uzpainter capabilities`, `uzpainter://capabilities`) with status, since, tier evidence, notes and evidence per entry
- [ ] 2.2 Evidence check: each `supported` entry names Tier 0 evidence present in the `phase5.2_parity-report-tiers` report; each `desktop-only-omitted` entry carries its per-symbol justification
- [ ] 2.3 Gap register `parity/reports/phase5/capability-gaps.json`: every `release-gap` entry and every `not_migratable` fixture with its owner scope decision id or the status `blocking`
- [ ] 2.4 For each gap or `not_migratable` fixture without a decision, raise `rulebook_task {action:"ask"}` to the owner; record each answer as a decision under `.rulebook/decisions/` and reference it from the manifest
- [ ] 2.5 Wording check over the manifest, release notes and `README.md`: no "full replacement" claim while a required gap is open

## 3. Tests
- [ ] 3.1 Generated manifest validates against its schema on the local CPU lane (decision 200) and lists the same symbols as the documented API inventory plus UzPainter additions
- [ ] 3.2 Every `release-gap` symbol raises `uzpainter.NotYetSupported` before any mutation; every `desktop-only-omitted` symbol raises `uzpainter.UnsupportedInUzPainter` with reason and alternative
- [ ] 3.3 Every `supported` entry's `tier_evidence` resolves to a passing comparison in the Phase 5 tier report
- [ ] 3.4 Gap register check: no in-scope gap without a decision id is reported as anything other than `blocking`

## 4. Acceptance
- [ ] 4.1 Every in-scope capability `supported` or covered by an owner scope decision; manifest and gap register attached to `phase5.4_parity-report`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
