## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.2_parity-contract

## 2. Implementation
- [x] 2.1 Store layout: SHA-256 content-addressed folder under `UZP_PARITY_STORE`, hash index, one corpus directory per Painter build, write-once records
- [x] 2.2 `uzpainter parity record` prototype (owner's machine only): store recorded oracles, write their hashes into the public manifest
- [x] 2.3 `uzpainter parity fetch <manifest>` prototype: resolve every blob a manifest names from the store
- [x] 2.4 `uzpainter parity verify` prototype: recompute and compare hashes; report `oracle_unavailable` for a missing or unreadable blob
- [x] 2.5 Register the owner's machine as the self-hosted GPU runner (GPU, licensed Painter 12.1.0, `UZP_PARITY_STORE`) and configure the hosted CPU lane without store access (`14-parity-testing.md` §7) — lanes configured in `.github/workflows/parity.yml` and the procedure documented in `parity/STORE.md` §5.1; registration moved to phase0.5_private-oracle-store per owner answer q1 2026-10-10

## 3. Tests
- [x] 3.1 Round trip on the owner's machine: record an authored sample, remove the local copy, fetch by manifest, verify the hash
- [x] 3.2 Missing blob: verify on a manifest naming an absent hash reports `oracle_unavailable`, never a pass
- [x] 3.3 Immutability: recording a different blob under an existing record id is refused
- [x] 3.4 Hosted lane: a job on a hosted runner has no `UZP_PARITY_STORE` and its oracle comparisons report `oracle_unavailable`

## 4. Acceptance
- [x] 4.1 Acceptance (P0-STORE, first clause): fetch/verify round trip on the owner's machine

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
