## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model

## 2. Implementation
- [ ] 2.1 Vendor the SQLite amalgamation and zstd (BSD branch) with their licence files and origin records
- [ ] 2.2 Create the `meta`, `revision`, `blob`, `blob_meta`, `operation`, `cache` and `checkpoint` tables with `journal_mode = DELETE` and foreign keys enforced
- [ ] 2.3 Implement content-addressed blob storage with zstd payloads, SHA-256 deduplication and per-name `blob_meta`
- [ ] 2.4 Implement portable mode (every dependency embedded) and explicit non-portable locators `{path, sha256}` with missing-dependency reporting on open
- [ ] 2.5 Implement the mutation commit transaction: blobs, revision row with zstd canonical manifest and digest, operation row, `checkpoint('current')` update, with an extension point for plane rows
- [ ] 2.6 Apply the idempotency/precondition decision against stored operation rows and `meta.operation_horizon_revision` before executing a mutation
- [ ] 2.7 Implement `format_version` semver handling (refuse newer major, in-memory migration of older minors written on next commit) and unknown-key preservation
- [ ] 2.8 Implement open-time integrity checks and corrupted-blob reporting with the affected nodes
- [ ] 2.9 Add test-only fault hooks (kill during commit, disk full, kill after durable commit) excluded from release builds

## 3. Tests
- [ ] 3.1 Commit atomicity: a killed commit leaves the file at the previous revision; a completed one at the new revision with its operation row
- [ ] 3.2 Disk full during commit: explicit error, previous revision intact
- [ ] 3.3 Corrupt a blob: detected by SHA-256 on open/read and reported with the affected nodes; corrupt a manifest separately: detected by `manifest_sha256`
- [ ] 3.4 Commit-then-die: kill after the durable commit and before the result is returned; the same request returns the stored outcome and no second revision exists; a changed request with the same key returns `idempotency_conflict`
- [ ] 3.5 Unknown-key rules: missing precondition → `outcome_unknown`; precondition ≠ current → `stale_revision`; precondition = current → executes
- [ ] 3.6 Deduplication: two imports of identical bytes share one blob and keep two `blob_meta` names
- [ ] 3.7 Versioning: a file with a newer major is refused with an explicit error; an older minor opens, and the original file is unchanged until the next commit
- [ ] 3.8 Non-portable project with a missing locator target reports the missing dependency on open

## 4. Acceptance
- [ ] 4.1 All tests of this child green on the hosted CPU lane; results attached to `phase1.8_project-store` as part of its `09-…` §7 evidence

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
