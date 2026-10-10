## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store

## 2. Implementation
- [ ] 2.1 Write the probe instruction sequences and `parity/manifests/phase0/tier0-api-probes.json` with stable probe ids
- [ ] 2.2 Set→get probes through a freshly resolved handle and after save/reopen for the properties the Phase 1 facade subset uses
- [ ] 2.3 Mask-stack context probes: channel and source mode `None` rules and the errors otherwise
- [ ] 2.4 Active-channel reset probe: `active_channels` assigned after `set_source`, with readback and exported output
- [ ] 2.5 `set_source(None, …)` on a multichannel fill: exception class and message recorded
- [ ] 2.6 `insert_*` position-rule probes and the errors they raise
- [ ] 2.7 Event-order probes for create/open, save and close, with `is_busy()` and `is_in_edition_state()` transitions
- [ ] 2.8 Record every probe twice (same session; after save/reopen) and admit the records to the store

## 3. Tests
- [ ] 3.1 Admission check: every probe id has two recordings whose hashes are in the manifest and resolve with `uzpainter parity verify`
- [ ] 3.2 Provenance check: every symbol a probe calls is documented in `python-doc`
- [ ] 3.3 Guard run: no readback JSON is in the repository

## 4. Acceptance
- [ ] 4.1 Acceptance (P0-TIER0, API probes): each probe golden recorded ≥ 2× and admitted

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
