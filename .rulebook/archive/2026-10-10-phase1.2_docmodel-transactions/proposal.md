# Proposal: phase1.2_docmodel-transactions

## Why
UzPainter's durability and retry semantics depend on a document that changes only through transactions, each producing an immutable revision and an operation record `{project_uuid, idempotency_key, request_hash, outcome, committed_revision}` that is committed atomically with it (ARC-02), and on name addressing that is idempotent within an explicit scope (LAY-06). Requirements: LAY-06, INT-07, QG-03, ARC-02, NFR-06 (`docs/prd.md`). Implements the document part of D3 (decision 005) in `docs/architecture/03-project-model.md` and `docs/architecture/04-layer-stack-and-compositing.md` §1, the operation records of D1/ARC-02 (decision 003) in `docs/architecture/02-runtime-topology.md` §3 and `docs/architecture/09-project-file-format.md` §4, and the capability manifest of D2 (decision 004, amended by decision 019: brush strokes out of scope) in `docs/architecture/10-python-api.md` §3. Child of `phase1.3_document-model` (P1-DOCMODEL).

## What Changes
- `src/uzp_core/document/`: persistent copy-on-write document; cheap immutable revision snapshots; `revision` incremented per committed transaction; `current`/`previous` checkpoint pointers in the model (persisted by P1-STORE).
- `src/uzp_core/transaction/`: one call = one transaction under the document lock; composite operations build a detached subtree and attach it in one step (on failure nothing is attached and the result lists what would have changed); results enumerate created/modified/removed/hidden node ids and imported/skipped resource hashes (QG-03); explicit native `Transaction` for atomic multi-call execution.
- `src/uzp_core/operation/`: operation-record type; `request_hash` = SHA-256 of the canonical tool name and arguments; the idempotency decision function used by the store and the worker: known key + same hash → stored outcome even when the current revision is newer; known key + different hash → `idempotency_conflict`; unknown key with missing or expired original precondition → `outcome_unknown` with the current revision; unknown key with unexpired precondition ≠ current revision → `stale_revision`; otherwise execute.
- `src/uzp_core/naming/`: name lookups return all matches; name-addressed mutations are scoped to `{project, set, stack, parent}`; an ambiguous match fails before mutation listing the candidate ids; repeating the same named operation creates no duplicate node (LAY-06).

## Dependencies
- DAG input of the parent: `phase0.2_parity-contract`.
- Sibling prerequisite: `phase1.1_docmodel-types-manifest`.
- Parent: `phase1.3_document-model`. Consumers: `phase1.4_store-container-operations` (persists operation rows atomically), `phase1.19_pyapi-native-module`.

## Acceptance
Part of the P1-DOCMODEL gate: round-trip tests over transaction-built documents pass; the idempotency decision table, transaction atomicity and name-addressing tests pass.

## Impact
- Affected specs: `document-model`
- Affected code: `src/uzp_core/document/`, `src/uzp_core/transaction/`, `src/uzp_core/operation/`, `src/uzp_core/naming/`, `tests/uzp_core/`
- Breaking change: NO
- User benefit: Retries never duplicate a mutation, failed calls leave the document untouched, and named operations are safe to repeat.
