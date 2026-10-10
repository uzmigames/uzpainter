## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.2_parity-contract

## 2. Implementation
- [ ] 2.1 Store layout: SHA-256 content-addressed folder under `UZP_PARITY_STORE`, hash index, one corpus directory per Painter build, write-once records
- [ ] 2.2 `uzpainter parity record` prototype (owner's machine only): store recorded oracles, write their hashes into the public manifest
- [ ] 2.3 `uzpainter parity fetch <manifest>` prototype: resolve every blob a manifest names from the store
- [ ] 2.4 `uzpainter parity verify` prototype: recompute and compare hashes; report `oracle_unavailable` for a missing or unreadable blob
- [ ] 2.5 Register the owner's machine as the self-hosted GPU runner (GPU, licensed Painter 12.1.0, `UZP_PARITY_STORE`) and configure the hosted CPU lane without store access (`14-parity-testing.md` §7)

## 3. Tests
- [ ] 3.1 Round trip on the owner's machine: record an authored sample, remove the local copy, fetch by manifest, verify the hash
- [ ] 3.2 Missing blob: verify on a manifest naming an absent hash reports `oracle_unavailable`, never a pass
- [ ] 3.3 Immutability: recording a different blob under an existing record id is refused
- [ ] 3.4 Hosted lane: a job on a hosted runner has no `UZP_PARITY_STORE` and its oracle comparisons report `oracle_unavailable`

## 4. Acceptance
- [ ] 4.1 Acceptance (P0-STORE, first clause): fetch/verify round trip on the owner's machine

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
