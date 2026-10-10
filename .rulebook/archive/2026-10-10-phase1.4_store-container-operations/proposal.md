# Proposal: phase1.4_store-container-operations

## Why
The `.uzp` file is a SQLite container whose public schema is the canonical JSON manifest; every committed mutation must land in one SQLite transaction together with its operation record, so the file at rest always holds the last committed revision and a lost acknowledgement can be resolved from the file alone (ARC-02). Requirements: OWN-07, SAV-01, RES-01, RES-02, NFR-06, NFR-08, ARC-02, ARC-12, INT-22 (`docs/prd.md`). Implements D8 (decision 010) and owner answer Q11 (decision 024: self-contained portable file, 10 % candidate budget measured by the census, retention of current and previous checkpoints plus the last 50 mutation revisions) in `docs/architecture/09-project-file-format.md`, the durability contract of D1 (decision 003) in `docs/architecture/02-runtime-topology.md` §3, §5 and §6 (operation record committed atomically with its revision; autosave by commit), and owner answer Q6 (decision 020: no `.spp` reader). Child of `phase1.8_project-store` (P1-STORE).

## What Changes
- `src/store/container.{h,cpp}`: SQLite container (vendored public-domain amalgamation) with the `meta`, `revision`, `blob`, `blob_meta`, `operation`, `cache` and `checkpoint` tables of `docs/architecture/09-project-file-format.md` §1 (the `plane*` tables belong to `phase1.5_store-planes`); `journal_mode = DELETE`; `PRAGMA foreign_keys = ON`; zstd (BSD licence branch) compression of every payload.
- `src/store/blobs.{h,cpp}`: content-addressed blobs (SHA-256), deduplicated by content with separate `blob_meta` names; original resource bytes stored unmodified; portable mode (default) embeds every dependency, an explicitly non-portable project keeps `{path, sha256}` locators and reports missing dependencies on open.
- `src/store/commit.{h,cpp}`: the mutation commit: one SQLite transaction inserting new blobs (and, through the planes child, plane versions and chunk rows), the `revision` row (`kind = mutation`, zstd canonical manifest + `manifest_sha256`), the request's `operation` row `{project_uuid, idempotency_key, request_hash, outcome, committed_revision}`, and the update of `checkpoint('current')`; idempotency and precondition decisions from `phase1.2_docmodel-transactions` evaluated against the stored rows and `meta.operation_horizon_revision`.
- `src/store/versioning.{h,cpp}`: semver `format_version`; a newer major is refused with an explicit error; older minors migrate in memory and are written only on the next commit; unknown manifest keys preserved.
- `src/store/integrity.{h,cpp}`: open-time checks (foreign keys, `manifest_sha256`, blob SHA-256); a corrupted blob is reported with the affected nodes.
- Test-only fault hooks (excluded from release builds): kill during commit, disk full, kill after the durable commit before the result is returned.

## Dependencies
- DAG input of the parent: `phase1.3_document-model` (manifest, operation-record type, idempotency decision function).
- Parent: `phase1.8_project-store`. Siblings building on this child: `phase1.5_store-planes`, `phase1.6_store-save-retention`, `phase1.7_store-inspect-census`.

## Acceptance
The `docs/architecture/09-project-file-format.md` §7 items owned by this child pass: interruption during commit leaves the previous or the new state; a corrupted blob and a corrupted manifest are each detected and reported; commit-then-die retry returns the stored outcome with no second revision; a changed request with the same key is rejected with `idempotency_conflict`.

## Impact
- Affected specs: `project-store`
- Affected code: `src/store/container.*`, `src/store/blobs.*`, `src/store/commit.*`, `src/store/versioning.*`, `src/store/integrity.*`, `tests/store/`, `thirdparty/sqlite/`, `thirdparty/zstd/`
- Breaking change: NO
- User benefit: Every committed edit is durable on its own, deduplicated, and resolvable after a crash without a second editable record.
