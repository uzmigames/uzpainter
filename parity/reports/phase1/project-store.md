# P1-STORE gate — `phase1.8_project-store`

Task `phase1.8_project-store` is the parent and acceptance task of P1-STORE (`docs/dag.md`). Its evidence feeds gate G1 directly (`docs/roadmap.md`: "project save/reopen/revert verified with fault injection including commit-then-die retry"). It implements the settling evidence of `docs/architecture/09-project-file-format.md` §7. The scope is decision 045.

**Result:**
- The complete §7 suite passes end to end on one store build: commit and `VACUUM INTO` interruption, blob and manifest corruption, recovery equality, two planes on one channel and tile, commit-then-die, pruned-key replay, and edit → revert → edit → reopen → compact with a protected checkpoint. The census was rerun on that same build for tunic v10, hat v8 and body v5/v6/v6b.
- The gate is not recorded as met yet. Children `phase1.6_store-save-retention` and `phase1.7_store-inspect-census` (and these settle tests) still need their hosted CPU lane run, which needs the owner's push.

## 1. Children and prerequisite

| Item | State |
|---|---|
| Prerequisite `phase1.3_document-model` | archived 2026-10-10 |
| `phase1.4_store-container-operations` | archived 2026-10-10 |
| `phase1.5_store-planes` | archived 2026-10-11; hosted run 38095977466 on `6fb4a16`, `tests/store` 23/23 |
| `phase1.6_store-save-retention` | complete locally (26/27); waits for the hosted CPU lane |
| `phase1.7_store-inspect-census` | complete locally (12/13); waits for the hosted CPU lane |

## 2. The §7 suite on one store build (items 3.1-3.5)

`zig build uzp-store-settle-tests` builds `uzp-store-settle-tests.exe` from `tests/store/settle_test.cpp`. It holds the store sources with the test-only fault hooks, compiled once, and `tests/store/test_store_settle.py` drives it.

All five cases share one content: a 300 KB resource bound to a fill layer, plus two paint layers. The two layers have 2048×2048 sRGB8 planes (2×2 chunks) on the same set, stack, BaseColor channel and UV tile 1001.

Recovery is checked as whole-file equality. Per revision this covers the manifest bytes, the SHA-256 of the pixels of each bound plane and of each named resource, and the checkpoint and operation rows. After each fault, the file is compared with the snapshot taken just before that fault. Strokes that commit after a recovery are compared with pixels computed independently of the store.

| Item | Case | What ran and what held |
|---|---|---|
| 3.1 | `interruptions` | One project goes through every fault in turn: 1 protected checkpoint, 55 fills, one stroke per plane, then a save. A worker killed during `COMMIT` of a stroke leaves a hot journal and a torn file. One killed between the plane rows and the revision row, one during `VACUUM INTO` of `compact`, and one before its rename. Then `VACUUM INTO` and the rename each fail with an I/O error in process, and the error names the step. After every fault the reopened file (full verification, clean) equals its state before the fault, and its bytes are unchanged. The killed strokes then commit exactly once each, with the expected pixels. `compact` collapses the revisions outside retention, shrinks the file, keeps every retained state byte-identical, and leaves every plane, version and blob reachable. Corruption is applied to byte copies: a resource blob is reported with its fill layer; a chunk blob with its plane and paint layer (the other plane and the resource still read exactly); an older manifest is reported with its revision (the current state still reads exactly); a corrupt current manifest refuses to open. The project itself stays unchanged. |
| 3.2 | `two_layers` | The project is reopened and A is edited. A stroke on B killed during `COMMIT` is recovered, and B is edited. Then it is reverted to the saved checkpoint, compacted and reopened. Each plane reads its own pixels at the saved, edited, reverted and current revisions. Every retained revision binds two distinct versions whose chunk hashes never overlap. The file holds two `plane` rows on one set/stack/channel/tile. |
| 3.3 | `commit_then_die` | A worker commits a stroke durably and is killed before the acknowledgement. Retrying the same request (key, arguments, original precondition) returns the stored outcome without executing. A changed stroke under the same key gets `idempotency_conflict`. Neither adds a revision or plane version, nor changes a pixel. The same holds after the current revision advances and after a reopen. |
| 3.4 | `pruned_key_replay` | A non-idempotent stroke `k1` is pruned by retention and `compact`. Replaying it with its original precondition, and with none, gives `outcome_unknown`: not executed, no revision, no version. `k2`, inside the window, returns its stored outcome at a newer current revision. The plane holds `k1` exactly once. The same holds after a reopen and after a second (empty) compaction. |
| 3.5 | `revert_edit_reopen_compact` | Sequence: approved (protected) at revision 2 → two strokes → 80 fills → revert to approved → stroke → reopen → compact. The retained set is exactly {2, 37..86}. Every retained state equals its value before compaction, byte for byte. The approved chunks of both planes stay; they were first written at revision 2, outside the mutation window. A version that only collapsed revision 3 bound is collected, and the version revision 4 wrote stays. After a reopen, the protected checkpoint still reverts to its exact pixels. |

Cases 3.2 and 3.3 deepen scenarios the children already test (`planes_no_alias`, `commit_then_die`) with richer content and whole-file equality. Cases 3.1, 3.4 and 3.5 chain the faults, replays and compaction on one file. The child suites are unchanged and still pass.

## 3. Local run (owner's machine, 2026-10-11)

| Item | Value |
|---|---|
| Machine | Windows 11 Pro 10.0.26200, NVIDIA GeForce RTX 4090 (no GPU used: the store is CPU only) |
| Toolchain | Zig 0.15.2 (Debug), Python 3.13 |
| Tree | branch `wt/phase1.8-project-store`, commit `a39594a` (store sources as on `main` `c3708d3`) |
| Builds | `zig build uzp-store uzp-store-tests uzp-store-save-tests uzp-store-inspect-tests painter`, and `zig build uzp-store-settle-tests`: exit 0, no warnings (`-Wall -Wextra -Werror` on own sources) |
| `uzp-store-settle-tests run` | 5 cases, 0 failed |
| `python -m pytest tests/store` | 56 passed in 13 min 4 s: store 23, save 12, inspect 14, settle 7 |
| `ruff check`, `ruff format --check`, `mypy` on `tests/store/test_store_settle.py` | clean |
| `python -m tools.parity.guard` | 2544 files checked, 0 blocked |

## 4. Census on the same build (item 3.6)

`UzPainter.exe store-census --inputs src/store/census_inputs.json --assets-root E:/UzmiGames/Assets3D --work <temp> --edits 20` was run on the Debug build of §3 (the same store sources). The procedure is in `src/store/STORE.md` §11.

No Painter was involved: the census reads only the size of each `.spp`. The machine-readable report stays `parity/reports/phase1/store-census.json`, phase1.7's run, because the guard admits one census report per phase.

This rerun reproduces every size in that report exactly: dependency bytes, project bytes, ratio, file growth, bytes written per edit, and stored chunk bytes. The exceptions are a few dozen bytes of compressed manifest size, because manifests carry the run's timestamps, and 1 byte of first-save I/O. Only the timings differ.

| Project | `.spp` bytes | Measured dependencies | Project bytes | Ratio | ≤ 10 % |
|---|---|---|---|---|---|
| tunic v10 | 408,723,056 | 2 files, 35,324,928 B | 25,464,832 | 0.062 | yes |
| hat v8 | 578,029,285 | 48 files, 307,122,093 B | 307,261,440 | 0.532 | no |
| body v5 | 879,248,615 | 4 files, 153,201,033 B | 153,677,824 | 0.175 | no |
| body v6 | 1,087,438,533 | 4 files, 156,016,983 B | 154,865,664 | 0.142 | no |
| body v6b | 1,190,431,812 | 4 files, 155,798,219 B | 154,648,576 | 0.130 | no |

| Measurement | tunic v10 | hat v8 | body v5 | body v6 | body v6b |
|---|---|---|---|---|---|
| First save (s) | 8.08 | 63.48 | 30.22 | 29.13 | 32.98 |
| One-parameter edit, file growth (mean B) | 2,048 | 4,915 | 2,662 | 2,662 | 2,662 |
| One-parameter edit, bytes written (mean B) | 43,572 | 46,439 | 44,186 | 44,186 | 44,186 |
| One-parameter edit (mean s) | 0.0127 | 0.0217 | 0.0111 | 0.0122 | 0.0106 |
| Stored manifest per edit (mean B) | 1,246 | 4,235 | 1,583 | 1,591 | 1,589 |
| Plane create (4096², sRGB8), stored chunk bytes | 188,829 | 188,829 | 188,829 | 188,829 | 188,829 |
| One-chunk plane edit, stored chunk bytes | 29,113 | 29,113 | 29,113 | 29,113 | 29,113 |
| Reopen (s) | 1.18 | 1.28 | 1.40 | 2.75 | 1.10 |
| Compaction (s) | 0.39 | 4.17 | 2.39 | 5.24 | 1.87 |
| Retained history: 23 revisions (B) | 48,726 | 117,490 | 56,506 | 56,696 | 56,653 |

Content not available as files is listed as `not_measured`:
- tunic v10: `imported_masks_packed_in_blend` and `painter_baked_mesh_maps`
- hat v8: `high_poly_mesh` and `painter_baked_mesh_maps`
- the bodies: `imported_masks`, `high_poly_mesh` and `painter_baked_mesh_maps`

The reasons are in `store-inspect-census.md` §3. The ratios therefore measure the dependency content that exists today. They are not the ratification evidence for the 10 % candidate budget, which is still the owner's call under 09 §3. The census on full, matched content is `phase4.1_coverage-body-v6b`.

What the numbers say about the store:
- An edit costs what it changes: 2–5 KB of file growth and about 44 KB written, including the rollback journal.
- A plane edit stores only the chunk it touched.
- Reopening takes about a second.
- 23 retained revisions cost 49–117 KB.

## 5. What remains before the gate closes

| Item | Needs |
|---|---|
| 2.3, 2.4 | The hosted CPU lane (`parity.yml`, `python -m pytest`) green on the commit carrying children `phase1.6` and `phase1.7`. Owner action: push. |
| 4.1 | The same hosted run showing `tests/store/test_store_settle.py` 7 passed (no skip: zig on PATH). Then the run id is recorded here and the parent is archived. |
