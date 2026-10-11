# Proposal: phase1.8_project-store

## Why
UzPainter must save progress in a self-contained, portable project file far more compact than `.spp`, never lose the last committed revision, never overwrite an approved baseline, and never replay a mutation twice after a crash. Requirements: OWN-07, SAV-01, SAV-02, SAV-05, RES-01, RES-02, NFR-04, NFR-06, NFR-08, QG-05, ARC-02, ARC-12, INT-22 (`docs/prd.md`). Implements D8 (decision 010) and owner answer Q11 (decision 024: self-contained portable file, 10 % candidate budget measured by the census, retention of current and previous checkpoints plus the last 50 mutation revisions) in `docs/architecture/09-project-file-format.md`, the durability contract of D1 (decision 003) in `docs/architecture/02-runtime-topology.md` §3, §5 and §6 (operation record committed atomically with its revision; autosave by commit), and owner answer Q6 (decision 020: no `.spp` reader). DAG node P1-STORE (`docs/dag.md`); its evidence is joined directly by gate G1 (`docs/roadmap.md`: "project save/reopen/revert verified with fault injection including commit-then-die retry").

This is the parent integration and acceptance task, split per the `docs/dag.md` task decomposition rule into four independently reviewable children.

## What Changes
Integration of the four children into the `.uzp` project store (DAG Outputs of P1-STORE) under `src/store/`, tests in `tests/store/`:
- `phase1.4_store-container-operations`: SQLite container (`meta`, `revision`, `blob`, `blob_meta`, `operation`, `cache`, `checkpoint`), zstd payloads, the mutation commit transaction with the operation record committed atomically with its revision, versioning, integrity checks, store-level fault injection including commit-then-die retry.
- `phase1.5_store-planes`: `plane` with persistent `plane_id`, `plane_version`, `plane_chunk`, copy-on-write chunks bound by manifests.
- `phase1.6_store-save-retention`: checkpoints, `save`/`save(Full)`/`compact`/`save_as`/`save_as_copy`, revert, retention (Q11), protected checkpoints, dirty flag, lock sidecar.
- `phase1.7_store-inspect-census`: `uzpainter inspect`, `export-bundle`, census instrumentation.

## Dependencies
- DAG input: `phase1.3_document-model` (P1-DOCMODEL: manifest, revisions, transactions, operation records).
- Children (all mandatory): `phase1.4_store-container-operations`, `phase1.5_store-planes`, `phase1.6_store-save-retention`, `phase1.7_store-inspect-census`.
- Downstream: `phase1.24_python-api-facade` (P1-PYAPI) and gate `phase1.26_gate-g1` (G1 joins P1-STORE directly); `phase2.4_supervisor-worker` reconciles its ledger from the operation rows.

## Acceptance
DAG gate of P1-STORE: the settling-evidence tests of `docs/architecture/09-project-file-format.md` §7 pass — instrumentation on tunic, hat and body content (first save, repeated one-parameter edits, raster-plane edit, reopen time, bytes written per edit, compaction time, retained-history size); interruption during commit and during `VACUUM INTO`; blob and manifest corrupted separately; identical manifests and pixels after recovery; two paint layers with separate planes on one channel and tile neither alias nor flatten; commit-then-die retry (stored outcome, no second revision) and changed request with the same key (`idempotency_conflict`); a pruned non-idempotent mutation cannot be replayed with or without its original precondition while a known-key replay inside the window returns the stored result; edit → revert → edit → reopen → compact reproduces the exact raster contents of every retained state, including a protected checkpoint whose chunks were first written outside the retained window. The parent closes only when all four children are accepted.

## Impact
- Affected specs: `project-store`
- Affected code: `src/store/`, `tests/store/`, vendored SQLite amalgamation and zstd under `thirdparty/`
- Breaking change: NO
- User benefit: A compact, portable, crash-safe project file whose history, retries and approved baselines behave exactly as specified.

## Child evidence

- phase1.5_store-planes: hosted run 38095977466 on 6fb4a16, `tests/store` 23/23 passed.
