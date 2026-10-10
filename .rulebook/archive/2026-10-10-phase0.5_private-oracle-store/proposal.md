# Proposal: phase0.5_private-oracle-store

## Why
Every Painter output recorded as an oracle — exported maps, API readbacks, default and template captures, Iray references — is private test data that must never enter the public repository (PRD CLR-05, LIC-03; decision 002). The owner decided under Q9b that his machine (GPU, licensed Painter 12.1.0) holds the private oracle store (decision 022), and that there is no GPU CI on GitHub: oracle and GPU checks run locally on that machine and the local run report is the evidence, while hosted CI skips them with an explicit reason (decision 028). Without the store, its `fetch/verify/record` commands and a content guard, no golden can be admitted and nothing stops a recorded PNG or JSON readback from being committed (`docs/architecture/14-parity-testing.md` §6–§7, §9; `docs/dag.md` P0-STORE, implements D13 and CLR-05).

## What Changes
This parent is the integration and acceptance task for two children:
- `phase0.3_oracle-store-cli`: the `UZP_PARITY_STORE` content-addressed (SHA-256) store on the owner's machine; prototype commands `uzpainter parity fetch <manifest>`, `uzpainter parity verify`, `uzpainter parity record` (owner's machine only); the local oracle run procedure on the owner's machine with GPU, licensed Painter 12.1.0 and the store (decision 028); hosted CI without store access; a missing blob reported as `oracle_unavailable`; one corpus directory per Painter build, immutable.
- `phase0.4_oracle-store-guard`: the repository guard run as a pre-commit hook and in CI, rejecting any file whose hash appears in the store index or that does not validate against the public manifest schema (content checks, not only file signatures).

## Dependencies
- Prerequisites: `phase0.2_parity-contract` (P0-CONTRACT).
- Children (must pass first): `phase0.3_oracle-store-cli`, `phase0.4_oracle-store-guard`.
- Successors: `phase0.8_tier0-goldens` (P0-TIER0), `phase0.6_procedural-feasibility` (P0-FEAS-PROC), `phase0.9_render-reference-capture` (P0-FEAS-RENDER), `phase0.9_normal-convention-fixture` (P0-NORMAL).

## Acceptance
Fetch/verify round trip on the owner's machine; guard blocks a recorded PNG and a recorded JSON readback and passes an authored fixture image and an authored expectation JSON (`docs/dag.md`, P0-STORE). Closes only when both children pass.

## Impact
- Affected specs: oracle-store
- Affected code: `tools/parity/` store prototype and guard, local oracle run procedure (`parity/STORE.md` §5)
- Breaking change: NO
- User benefit: goldens become usable while oracle data stays private by construction
