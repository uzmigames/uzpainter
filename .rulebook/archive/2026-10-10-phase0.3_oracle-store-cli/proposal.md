# Proposal: phase0.3_oracle-store-cli

## Why
Recorded Painter outputs must live only in a private, content-addressed store on the owner's machine, which is also the self-hosted GPU runner with the licensed Painter (Q9b, decision 022; PRD CLR-05, NFR-01; decision 002). Goldens become usable only when a manifest's hashes can be fetched and verified there, and when hosted CI fails cleanly as `oracle_unavailable` instead of passing (`docs/architecture/14-parity-testing.md` §6–§7, §9). Child of `phase0.5_private-oracle-store` (`docs/dag.md` P0-STORE, implements D13 and CLR-05).

## What Changes
- Store layout: a content-addressed folder addressed by SHA-256, configured through `UZP_PARITY_STORE`, with an index of stored hashes; one corpus directory per Painter build, records immutable; old corpora kept; backups are the owner's private copies and the store is never uploaded to a hosted service.
- Phase 0 prototype commands under `tools/parity/`: `uzpainter parity fetch <manifest>` (resolve the blobs a public manifest names), `uzpainter parity verify` (check hashes), `uzpainter parity record` (owner's machine only: store newly recorded oracles and write their hashes into the manifest per `parity/schema/golden-public.json`).
- `oracle_unavailable` result for any missing or unreadable blob.
- The owner's machine registered as the self-hosted GPU runner (GPU with DXR Tier 1.1 and Vulkan ray query, licensed Painter 12.1.0, `UZP_PARITY_STORE`); CI lanes per 14 §7: hosted runners without store access run only checks against independently authored public expectations.

## Dependencies
- Prerequisites: `phase0.2_parity-contract` (P0-CONTRACT).
- Parent: `phase0.5_private-oracle-store` (P0-STORE). Sibling that depends on this task: `phase0.4_oracle-store-guard` (uses the store index).

## Acceptance
Fetch/verify round trip on the owner's machine (`docs/dag.md`, P0-STORE, first clause).

## Impact
- Affected specs: oracle-store
- Affected code: `tools/parity/` store prototype, CI runner and lane configuration
- Breaking change: NO
- User benefit: private oracles are addressable by hash from public manifests, and nothing outside the owner's machine can read them
