## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.3_document-model

## 2. Children (each accepted before this parent closes)
- [x] 2.1 `phase1.4_store-container-operations` accepted
- [x] 2.2 `phase1.5_store-planes` accepted
- [ ] 2.3 `phase1.6_store-save-retention` accepted
- [ ] 2.4 `phase1.7_store-inspect-census` accepted

## 3. Tests
- [x] 3.1 Run the complete `docs/architecture/09-project-file-format.md` §7 suite end to end on one store build: commit/`VACUUM INTO` interruption, blob and manifest corruption, recovery equality of manifests and pixels
- [x] 3.2 Two paint layers with separate planes on the same channel and tile: save, reopen, edit and recover without aliasing or flattening
- [x] 3.3 Commit-then-die retry: kill the process after the durable commit and before the result is returned, retry the same request (stored outcome, no second revision) and a changed request with the same key (`idempotency_conflict`)
- [x] 3.4 Pruned-key replay after retention and compaction with and without the original precondition; known-key replay inside the window after the revision advanced
- [x] 3.5 Edit → revert → edit → reopen → compact against the exact raster contents of every retained state, including a protected checkpoint with chunks first written outside the retained mutation window
- [x] 3.6 Instrumentation run on tunic v10, hat v8 and body content producing the Phase 1 census report

Items 3.1-3.5: `uzp-store-settle-tests` (`tests/store/settle_test.cpp`, decision 045), 5 cases green
locally on commit `a39594a`; `python -m pytest tests/store` 56 passed. Item 3.6: the census rerun
on the same build reproduces the dependency, project and per-edit sizes of `parity/reports/phase1/store-census.json`. Results:
`parity/reports/phase1/project-store.md`.

## 4. Acceptance
- [ ] 4.1 Acceptance (P1-STORE gate): `09-…` §7 tests pass; results and census numbers recorded in `parity/reports/phase1/` for the G1 gate record
  - Recorded locally in `parity/reports/phase1/project-store.md`. Open: the hosted CPU lane run (owner's push) showing children 2.3/2.4 and `tests/store/test_store_settle.py` green.

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
