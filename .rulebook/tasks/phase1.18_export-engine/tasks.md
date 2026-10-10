## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.14_compositor-core

## 2. Children (each accepted before this parent closes)
- [ ] 2.1 `phase1.15_export-plan-compiler` accepted
- [ ] 2.2 `phase1.16_export-processing-encoders` accepted
- [ ] 2.3 `phase1.17_export-presets` accepted
- [ ] 2.4 `phase1.17_export-publication-receipts` accepted

## 3. Tests
- [ ] 3.1 Run the union of the children's Tier 0 export goldens (padding, dithering, resize, bit depth, virtual maps) in a local run on the owner's machine (decision 028) and publish the comparison numbers in the local run report used as evidence
- [ ] 3.2 Determinism lane: export the same project with the same config twice in separate processes and compare every file byte for byte and every receipt hash
- [ ] 3.3 Publication interruption suite end to end (each file, the receipt, the pointer, each fixed-name copy)

## 4. Acceptance
- [ ] 4.1 Acceptance (P1-EXPORT gate): Tier 0 export goldens exact, byte determinism and publication interruption tests green; report written to `parity/reports/phase1/` for the G1 gate record

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
