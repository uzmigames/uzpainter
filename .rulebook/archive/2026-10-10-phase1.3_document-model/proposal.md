# Proposal: phase1.3_document-model

## Why
Every subsystem (store, mesh, compositor, export, Python API) reads and mutates one typed document; without the `uzp_core` model, its canonical manifest and its revision/transaction/operation-record contract, nothing else in Phase 1 can be built or tested. Requirements: PRJ-02, PRJ-03, PRJ-05, PRJ-06, RES-01…RES-04, BAK-06, LAY-06, LAY-13, NFR-08, INT-07, QG-03, ARC-02, ARC-03, ARC-11 (`docs/prd.md`). Implements the document part of D3 (decision 005) in `docs/architecture/03-project-model.md` and `docs/architecture/04-layer-stack-and-compositing.md` §1, the operation records of D1/ARC-02 (decision 003) in `docs/architecture/02-runtime-topology.md` §3 and `docs/architecture/09-project-file-format.md` §4, and the capability manifest of D2 (decision 004, amended by decision 019: brush strokes out of scope) in `docs/architecture/10-python-api.md` §3. DAG node P1-DOCMODEL (`docs/dag.md`), Phase 1 of `docs/roadmap.md`.

This is the parent integration and acceptance task, split per the `docs/dag.md` task decomposition rule into three independently reviewable children.

## What Changes
Integration of the three children (DAG Outputs of P1-DOCMODEL):
- `phase1.1_docmodel-types-manifest`: `uzp_core` types, canonical JSON manifest and its schema (`src/uzp_core/`, `src/uzp_core/schema/manifest.schema.json`).
- `phase1.2_docmodel-transactions`: revisions, transactions, operation records `{project_uuid, idempotency_key, request_hash, outcome, committed_revision}` (`src/uzp_core/`).
- `phase1.2_docmodel-capability-manifest`: capability manifest generator (`tools/capabilities/`, build output `capabilities.json`).
Tests in `tests/uzp_core/` and `tests/capabilities/`.

## Dependencies
- DAG input: `phase0.2_parity-contract` (P0-CONTRACT: parity contract and public/private golden schemas the manifest and capability evidence fields refer to).
- Children (all mandatory): `phase1.1_docmodel-types-manifest`, `phase1.2_docmodel-transactions`, `phase1.2_docmodel-capability-manifest`.
- Downstream: `phase1.8_project-store`, `phase1.7_mesh-loader`, `phase1.14_compositor-core`, `phase1.24_python-api-facade`.

## Acceptance
DAG gate of P1-DOCMODEL: round-trip tests pass; the manifest digest is stable. The parent closes only when all three children are accepted.

## Impact
- Affected specs: `document-model`
- Affected code: `src/uzp_core/`, `tools/capabilities/`, `tests/uzp_core/`, `tests/capabilities/`
- Breaking change: NO
- User benefit: One typed, canonically serialised document with a stable digest and a durable mutation contract that every later subsystem shares.
