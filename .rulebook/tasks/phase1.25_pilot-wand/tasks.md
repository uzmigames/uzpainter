## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.24_python-api-facade

## 2. Implementation
- [ ] 2.1 Author `parity/manifests/phase1/wand-v1.json` with the independently authored inputs, instruction sequence, settings and software identities
- [ ] 2.2 Record the Wand v1 Tier 1 goldens in Painter 12.1.0 through the oracle recorder (documented API rebuild from the same inputs), twice per golden (same session; after save/reopen), and store the blobs in `UZP_PARITY_STORE` with their hashes in the manifest
- [ ] 2.3 Classify oracle stability per map; record any content that cannot be migrated through the documented API as `not_migratable` with the reason
- [ ] 2.4 Write the Tier 1 runner that rebuilds Wand v1 through the pipeline adapter (`painter_create`, `sync`, `painter_export` unchanged, pinned by SHA-256) on DX12 with the same external mesh maps
- [ ] 2.5 Write the comparison step: decode both sides at native depth, classify channels by measured storage format, compute the `docs/architecture/14-parity-testing.md` §4 diagnostics and write `parity/reports/phase1/tier1-wand-v1.json`

## 3. Tests
- [ ] 3.1 Tier 1 equality: every exported Wand v1 map per set equal to its private golden in a local DX12 run on the owner's machine (decision 028; the local run report is the evidence)
- [ ] 3.2 Repeatability: run the rebuild and export twice in separate processes; every file byte-identical
- [ ] 3.3 Save/reopen: save the rebuilt project, reopen it and export again; maps equal to the first export
- [ ] 3.4 Oracle availability: a missing golden blob fails the comparison as `oracle_unavailable`, never as a pass
- [ ] 3.5 Guard: the repository guard passes on the manifest and report and rejects a planted copy of a recorded golden

## 4. Acceptance
- [ ] 4.1 Acceptance (P1-WAND gate): maps equal and byte-stable across two runs; report published for the G1 gate record, listing any exceptions relied on (none expected)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
