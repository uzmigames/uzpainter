# Proposal: phase0.4_oracle-store-guard

## Why
No recorded Painter output may enter the public repository in any form — images, API readbacks serialised as JSON, default and template captures, Iray references, or anything derived pixel for pixel from them (PRD CLR-05, LIC-03; decision 002; `docs/licensing-and-clean-room.md` §1.6, §5.4). File-signature checks alone miss a JSON readback or a re-encoded image, so the guard must check content: hash membership in the private store index and validation against the public manifest schema (`docs/architecture/14-parity-testing.md` §6, §9). Child of `phase0.5_private-oracle-store` (`docs/dag.md` P0-STORE, implements D13 and CLR-05).

## What Changes
- Repository guard under `tools/parity/`, run as a pre-commit hook and as a CI check on every commit:
  - rejects any file whose SHA-256 appears in the private store's index (index of hashes available to the guard; blobs never needed);
  - rejects any JSON data file under `parity/` that does not validate against its public schema (`parity/schema/golden-public.json` for manifests; the contract's schemas for the exception register);
  - checks content, not only PNG/EXR or Adobe file signatures.
- Test fixtures: a recorded PNG and a recorded JSON readback (hash-indexed, kept outside the repository and fed to the guard in the test) and an authored fixture image plus an authored expectation JSON (committed).

## Dependencies
- Prerequisites: `phase0.2_parity-contract` (P0-CONTRACT), `phase0.3_oracle-store-cli` (store index).
- Parent: `phase0.5_private-oracle-store` (P0-STORE).

## Acceptance
Guard blocks a recorded PNG and a recorded JSON readback and passes an authored fixture image and an authored expectation JSON (`docs/dag.md`, P0-STORE, second clause).

## Impact
- Affected specs: oracle-store
- Affected code: `tools/parity/` guard, pre-commit hook configuration, CI check
- Breaking change: NO
- User benefit: an accidental commit of oracle data is stopped before it reaches history
