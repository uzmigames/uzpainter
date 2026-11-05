# G1 "Foundation green" — gate record (draft)

Task `phase1.26_gate-g1` (`docs/dag.md` G1, D14; `docs/roadmap.md` Phase 1 gate, rules 2, 3 and 6). **Draft, pre-verified 2026-10-19** on the owner's machine (Windows 11 Pro 10.0.26200, NVIDIA GeForce RTX 4090, Zig 0.15.2, Python 3.13.9) on a clean checkout of `main` `39d8d7b`. Every check below is CPU only: no GPU run was made for this draft. Numbers and hashes only: every recorded Painter output stays in the private store. SHA-256 values are of the committed file bytes at `39d8d7b` (`git show 39d8d7b:<path>`), as in the G0 record.

Task-status reconciliation, 2026-10-20: sections 3.6 and 5 reflect completed checklist items and the compositor-colour-fits archive. Historical check results and hashes remain unchanged; this reconciliation records no new acceptance run.

Pre-gate re-run, 2026-10-21, on a clean checkout of `main` `8709033adf6f644337df3842dd361a91595dd923` (same machine, Zig 0.15.2, Python 3.13.9; CPU only, no GPU run): §3.6, §4.1, §5 and §6.1. `8709033a` is not the gate commit. Logs: `tmp/scratch/g1-offline/` (untracked).

Gate run, 2026-11-05, after every Phase 1 feature task was archived (decision 397): the guard and `store verify` (§4.2), the capability manifest (§6.2) and the full local gate of decision 200 (§8), run once on the shared checkout at `072756c0ce7d2efc73e836f869d3bb087e12b1dd`. Logs under `tmp/scratch/g1-*` (untracked).

Second gate run, 2026-11-05 evening, on `58f7260ba745f2051808dbb56f67c59b2187f74e` after the repairs of §8.4, on a quiet checkout with the native lock held for the whole run (§4.3, §6.3, §9).

**Result: G1 open.** Every clause of the roadmap is evidenced (§2), the Wand's under EXC-010 and not exactly, and every other Phase 1 task is archived (§5). The first full gate was red, 96 failed and 3 errors (§8). The second (§9) has 10 failures: 3 were fixed at their root after the run and pass on re-run, and 7 are known failures owned elsewhere (two need new Painter recordings, one a root decision on the R-322 TGA gap, one the owner's OK to remove a leftover folder). G1 closes on a gate commit where the full gate is green, with the guard, `store verify` and the capability manifest re-run on that commit.

## 1. Oracle envelope used by this gate (decision 037)

`parity/envelopes/registry.json` (SHA-256 `361bd5262722c43fd4aaa274726e1ec4cfeb6f05ed88afc296f287e01f342762`): current envelope `painter-12.1.5+js-api.1.1.20` (envelope SHA-256 `1497f6497fd984cadeb5a136ce73fc41c7c601b7a6652c76fa6670be7bc4e406`), superseded `painter-12.1.0+js-api.1.1.20` (`0f0c8d5fec0381271fa5df51b448311b6a2e322cc96372fb97b999cb15fd119c`). No candidate, no quarantine.

| Manifest root | Envelope | Manifests | Listed blobs | `verify` |
|---|---|---|---|---|
| `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests` | current | 300 | 21856, all `available` | exit 0 |
| `parity/manifests` | superseded | 82 | 2686, all `available` | exit 0 |

The one manifest of `parity/manifests` without blobs is still `tier3/render-procedure/qualification-sphere.json` (G0 record §1). Whole store: `python -m tools.parity.store verify` exit 0 (`store ... parity-store: ok`).

## 2. Clauses of `docs/roadmap.md` G1

| Clause | Task | Evidence | Verdict |
|---|---|---|---|
| Requires G0 | `phase0.10_gate-g0` | §3.1 | met |
| Wand v1 maps equal to the private Painter goldens (Tier 1) | `phase1.25_pilot-wand` | §3.5 | met **under EXC-010, not exact** (decision 395) |
| Wand v1 maps byte-stable across two runs | `phase1.25_pilot-wand` | §3.5 | met (rebuilds `repeatable`, save/reopen export byte-identical) |
| The three pipeline scripts run unchanged through the adapter | `phase1.24_python-api-facade` | §3.6 | met (task archived 2026-10-21 on the coordinated full suite at `1103f00c`) |
| Project save/reopen/revert verified with fault injection, including commit-then-die retry | `phase1.8_project-store` | §3.2 | met (re-run at this draft) |
| Certificate and reload fixtures pass | `phase1.7_mesh-loader` | §3.3 | met (re-run at this draft) |

## 3. Joined items

### 3.1 G0 — `phase0.10_gate-g0`

Archived `.rulebook/archive/2026-10-13-phase0.10_gate-g0/` (commit `0fffb00`, closed on the owner's order 2026-10-13); every item of its `tasks.md` checked, 4.1 included.

| Evidence | SHA-256 |
|---|---|
| `parity/reports/phase0/gate-g0.md` | `25ceb2fef26142af693c1fee02217147a55f524c1808c3efc24bf9384b575baf` |

### 3.2 P1-STORE — `phase1.8_project-store`

Archived `.rulebook/archive/2026-10-13-phase1.8_project-store/` with its children `phase1.4_store-container-operations`, `phase1.5_store-planes` (2026-10-10, 2026-10-11), `phase1.6_store-save-retention` and `phase1.7_store-inspect-census` (2026-10-13). Its acceptance evidence is the `docs/architecture/09-project-file-format.md` §7 suite.

Re-run at this draft: `python -m pytest -p no:cacheprovider -rA tests/store/test_store_settle.py` exit 0, 7 passed in 461.75 s, on a fresh `zig build uzp-store-settle-tests`. The five native cases: `interruptions` (commit and `VACUUM INTO` interruption, blob and manifest corruption, recovery equality), `two_layers`, `commit_then_die`, `pruned_key_replay`, `revert_edit_reopen_compact`. The other two cases are `test_native_case_list_is_complete` and `test_child_refuses_an_unknown_action`.

| Evidence | SHA-256 |
|---|---|
| `parity/reports/phase1/project-store.md` | `f531808db1018c463f0d251dcbd3dd3fb938d9a8d5332b9cf4fb622465fe1667` |
| `parity/reports/phase1/store-census.json` | `0712350bf0d105c7cc7f8a8f392cf3ece5fb46c1a0de052445569d9c4ad0b1dd` |
| `docs/architecture/09-project-file-format.md` | `ee6c3f5394b2fece3c6b687d1959867caabab9388e303c93aeaf97f63d3bab86` |
| `tests/store/test_store_settle.py` | `577f3b1cdf610472c54a7d1afba48903bc2d614a50fb911761d1b914949a38f6` |
| `tests/store/settle_test.cpp` | `7346ca2edead33e59a9c4a34675c82ed4ae799764110488806435cbdb33b6081` |

### 3.3 P1-MESH — `phase1.7_mesh-loader`

Archived `.rulebook/archive/2026-10-11-phase1.7_mesh-loader/` with its children `phase1.4_mesh-importers` (2026-10-10), `phase1.5_mesh-tangents-certificate` and `phase1.6_mesh-reload` (2026-10-11). Its acceptance evidence is the `docs/architecture/12-mesh-import.md` §9 fixtures, mapped to their tests in `mesh-loader.md`.

Re-run at this draft: `python -m pytest -p no:cacheprovider -rA tests/mesh` exit 0, 30 passed, 0 skipped, in 361.96 s, on fresh `zig build mesh-tests` builds. Certificate: `test_certificate_of_every_format[obj|gltf|fbx]` and the native certificate cases in `test_native_cases`. Reload: `test_reload_case` for `identical_reload`, `moved_vertices`, `uv_change_replaced`, `added_and_removed_sets` and `gltf_external_buffer` (bindings kept), and `rename_fixture`, `split_fixture`, `merge_fixture` and `failure_mid_reload` (refused, project unchanged). Normal convention: `test_production_frames_bake_as_the_prototype`, and `test_normal_convention_rerun_reproduces_the_verdict` (ran against the store, not skipped). Isolation: `test_mesh_build_references_no_uzengine_artifact`.

| Evidence | SHA-256 |
|---|---|
| `parity/reports/phase1/mesh-loader.md` | `0ba346be8fe71a01bcb229b42ae17d3930f764fe4c38d0c619381d5b4883c795` |
| `docs/architecture/12-mesh-import.md` | `9fa0b5c722e212ecb4ab43ec6920585214307124c59acb33915131ecdbf64448` |
| `tests/mesh/test_mesh_import.py` | `2829b75bc5e95e1992f56b7ff0c663d666c48a4f44b5311d5aa9e584629679de` |
| `tests/mesh/test_mesh_certificate.py` | `724574a9b403c8a9e2c0cb233424e92574e93d0428731a247efaf33e8dd894a6` |
| `tests/mesh/test_mesh_reload.py` | `b77a0c4c2b98867cdb7aaf7f5893f9d61945c9179d2764607a2a6f147b375c6f` |
| `tests/mesh/test_mesh_loader.py` | `957bab4143c43dd0e3906708b64f0d776c37438309b0b8557052c50d1d376ce2` |
| `tests/mesh/mesh_test.cpp` | `57ce3cfa087ab0aff583f3e86a1b05b60c11a382097ce582f2255c385f6d033c` |
| `tests/mesh/reload_test.cpp` | `211721373829588700c8890fab85b9029b3c2ad1e9a62d8cce0ea2036dec8808` |

### 3.4 Items reaching G1 through the joined items, accepted

| Task | Archived | Evidence | SHA-256 |
|---|---|---|---|
| `phase1.4_render-core-layer` | `.rulebook/archive/2026-10-10-phase1.4_render-core-layer/` | `parity/reports/phase1/render-core-layer.md` | `e8183dfb8bc746cf4a734fb1ed7cde8dc2ef70f58cd1cf4f14913e9320736766` |
| `phase1.3_document-model` | `.rulebook/archive/2026-10-10-phase1.3_document-model/` | `parity/reports/phase1/document-model.md` | `904da403a4d2a032ca37061d5d5f6b4f9abb1edf2825fc4567d814709aa93486` |
| `phase1.14_compositor-core` | `.rulebook/archive/2026-10-12-phase1.14_compositor-core/` | `parity/reports/phase1/compositor-core.md` | `5af3af916afdee7207fc6681cf13a790cb2ef0e2d09b6432ec988fa62d121a44` |
| `phase1.18_export-engine` | `.rulebook/archive/2026-10-12-phase1.18_export-engine/` | `parity/reports/phase1/export-engine.md` | `69875eea8e5d9379d7549b726528f42c910b222fcd1c128ceb435b7785df4815` |
| `phase1.24_python-api-facade` | `.rulebook/archive/2026-10-21-phase1.24_python-api-facade/` | `parity/reports/phase1/python-api-facade.md` | `972b0c706add74c825364e325b0eab7519a9c56610d70223e98f0b56c135d3f3` (at `8709033a`) |

All their children are archived (§5). Checked 2026-10-21 on `8709033a`: the `tasks.md` of each of the five archives has no unchecked item.

### 3.5 P1-WAND — `phase1.25_pilot-wand` (accepted under EXC-010, not exact)

Archived `.rulebook/archive/2026-11-03-phase1.25_pilot-wand/` (`9e83774d`, decisions 395 and 396). Item 2.7 (the exact `infinite` padding) moved to `phase3.1_export-island-padding`; every other item is checked. The gate clause reads "maps equal to the private Painter goldens and byte-stable across two runs"; what is evidenced is a **pass under EXC-010 version 1, not equality**:

- Tier 1 report `parity/reports/phase1/tier1-wand-v1.json`: outcome `pass`, `exceptions_relied_on` EXC-010 version 1, no structural item, oracle `stable` (r1-repeat and r2 equal to r1 on all five maps), envelope `painter-12.2.0+js-api.1.1.20-env-a981b586eae7`.
- Covered interior texels differing: 0 on all five maps. Covered texels differing: 0 on BaseColor, Roughness, Metallic and Height; 42 values on the Normal, all on its island-edge texels. Padding values differ on every map (per band in the report). These are the counts of the DX12 run of 2026-11-03 on `e50844ee` (archive item 3.1).
- Byte stability: the two rebuilds of the run are `repeatable` (0 differing values on all five maps), and the export after save and reopen is byte-identical to the first (archive items 3.2 and 3.3). Dump-and-rebuild: `parity/reports/phase2/recipe-rebuild-wand.json`, recipe digests equal and the five exports byte-identical (`phase2.2_recipe-and-diagnostics`, `434c1f32`).
- The maps are written by the diagnostic measure export (decision 286). Production still refuses both islanded cases (decisions 245, 259), owned by `phase3.1_export-island-padding`.
- The report's run block was refreshed by `f1c2b21a` (the Sash run of 2026-11-03 on `7d35eb99`): only the build hash changed, the verdict and counts did not.

| Evidence | SHA-256 (at `b0265f97`) |
|---|---|
| `.rulebook/archive/2026-11-03-phase1.25_pilot-wand/tasks.md` | `0364ac26dc7f267d7eb368e787c8a5900769529d8cee81d72a3345956284f6b6` |
| `parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/manifests/phase1/tier1/wand-v1.json` | `432f9b14fb28489527ccdea6cdf19324c995939526866541c51596bcf4581c1a` |
| `parity/reports/phase1/tier1-wand-v1.json` | `5711b4a6e7185da6066d41c6601f136d10eae83b509726e6b7e35bc52782a942` |
| `parity/reports/phase2/recipe-rebuild-wand.json` | `14e5db08ad23d3af012dd43b50b18bdb318d9f9298740e06f632e51aab4e4989` |
| `.rulebook/decisions/395-the-owner-approves-exc-010-…` | `3558a12d178c766fc4c577546d661f9f81dd4ef0bb48c234f698935ef1556af7` |

### 3.6 P1-PYAPI — `phase1.24_python-api-facade` (accepted)

Archived `.rulebook/archive/2026-10-21-phase1.24_python-api-facade/` with its children `phase1.19_pyapi-native-module` to `phase1.23_pyapi-pipeline-adapter` (2026-10-12); every item of its `tasks.md` checked, 4.1 included. Accepted on the coordinated full suite at `1103f00c`: 3781 passed, 4 skipped, 1 xfailed, wrapper exit 0 (`tmp/scratch/fullsuite/`, untracked). The skips and the xfail are outside that task; the xfail is the Wand five-map export, refused on `infinite` padding (`phase1.25_pilot-wand` item 2.7).

The pipeline-script clause is the task's item 3.2 and acceptance 4.1: `painter_create.py`, `painter_layer_stack.py sync` and `painter_export.py`, pinned by SHA-256, run unchanged through the adapter. In that full suite all 55 `tests/adapters` cases passed with none skipped (`tests/adapters/assets3d/test_pipeline_adapter.py` 20, `test_adapter_units.py` 35), `test_wand_create_sync_and_export_run_unchanged` among them. The parity of the Wand's exported maps is not part of this clause (§3.5).

| Evidence | SHA-256 (at `8709033a`) |
|---|---|
| `.rulebook/archive/2026-10-21-phase1.24_python-api-facade/tasks.md` | `4386dd6c4f034ed1a0cceb24991e7ea512b669f72dc17151b7510d636b3e793d` |
| `parity/reports/phase1/python-api-facade.md` | `972b0c706add74c825364e325b0eab7519a9c56610d70223e98f0b56c135d3f3` |
| `parity/reports/phase1/pyapi-pipeline-adapter.md` | `02f0fccb38464071a128bba128e7c426884e83983a3f0c9cbc106e56346cf730` |

### 3.7 Exceptions relied on

`parity/exceptions.json` (SHA-256 `f4ef87337725330216ffd0c676eca96987592984ab45f3abb54a1f3b874c6633`) holds EXC-001 to EXC-006 (Tier 0, basis `oracle_instability`) and EXC-007 (Tier 1, `tier1/pilot/wand-v1`), which is withdrawn in version 2 (decision 259). The Wand's own list of exceptions relied on is pending (§3.5, item 4.1).

At `8709033a` the file's SHA-256 is `cbb999ae888dbdd7a9bb2843f6adc7fb0b92c53796966001c1d0d818869ea722`: EXC-001 to EXC-006 each have a version 2 (decision 307) that narrows version 1 to the outputs whose r2 differs from r1, EXC-007 stays withdrawn (decision 259), and EXC-008 and EXC-009 are new Tier 0 entries under decision 032 (decision 307).

**At the gate run (2026-11-05)** the register's SHA-256 is `1678b0f2635c69110cba47ae0c6d7520d53fc36bdb7ea351fb5b0693052d4815` (unchanged from `072756c0` to `b0265f97`). Exceptions G1 relies on:

| Exception | Version | Tier | Domain | Decision, approval | Relied on by |
|---|---|---|---|---|---|
| EXC-010 | 1 | 1 | `tier1/pilot/wand-v1`, golden `phase1/tier1/wand-v1`: covered interior exact; the covered bound excepts only the Normal's island edge; padding free | 395, owner 2026-11-03 | the Wand clauses (§3.5) |
| EXC-001 | 2 | 0 | `tier0/semantics/quantisation-thirds`, 16 outputs | 032, owner 2026-10-11 | Tier 0 evidence of `supported` capabilities (§6.2) |
| EXC-002 | 2 | 0 | `tier0/semantics/blend-inputs`, 3 outputs | 032, owner 2026-10-11 | same |
| EXC-006 | 2 | 0 | `tier0/semantics/export-ocio-encode-legacy`, 5 outputs | 032, owner 2026-10-11 | same |
| EXC-008 | 1 | 0 | `tier0/semantics/export-ocio-encode`, 5 outputs | 032, owner 2026-10-11 | same |
| EXC-009 | 1 | 0 | `tier0/semantics/srgb-bitmap-variants-v2`, 6 outputs | 032, owner 2026-10-11 | same |

The five Tier 0 entries are oracle-instability exceptions (r2 differs from r1 in Painter itself, decision 032) on goldens that the `supported` entries of the capability manifest cite as evidence; no G1 clause compares UzPainter output under them. Not relied on: EXC-003 to EXC-005 (their goldens are not cited by a `supported` entry), EXC-007 (withdrawn, decision 259), EXC-011 and EXC-012 (the Tunic and the Sash, Phase 2 pilots for G2).

## 4. Checks on the draft tree (`39d8d7b`)

| Check | Result |
|---|---|
| `python -m tools.parity.guard` | exit 0; store-hash rule against the store (3881 hashes); 3775 files checked, 0 blocked |
| `python -m tools.parity.store verify parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests` | exit 0; 300 manifests, 21856 blobs `available` |
| `python -m tools.parity.store verify parity/manifests` | exit 0; 82 manifests, 2686 blobs `available` |
| `python -m tools.parity.store verify` | exit 0; store ok |
| `python -m pytest tests/store/test_store_settle.py` | exit 0; 7 passed (§3.2) |
| `python -m pytest tests/mesh` | exit 0; 30 passed (§3.3) |
| `zig build painter -j4` | exit 0; no warnings |
| `python -m pytest tests/python/test_capability_conformance.py::test_supported_entries_equal_the_tier0_trace tests/capabilities/test_capabilities.py -k "tier0_trace or tier_evidence or compositor_entries_state or supported_entry or unsupported_claim or every_entry_validates"` | exit 0; 8 passed |

These checks must run again on the gate commit.

### 4.1 Pre-gate checks on `8709033a` (2026-10-21, not the gate commit)

Each command ran once from the root of a clean checkout of `8709033adf6f644337df3842dd361a91595dd923`. Store: `%LOCALAPPDATA%\UzPainter\parity-store`, read only. Logs under `tmp/scratch/g1-offline/`.

| Check | Exit | Result | Log |
|---|---|---|---|
| `python -m tools.parity.guard` | 0 | store-hash rule against the store (4061 hashes); 4186 files checked, 0 blocked | `guard.log` |
| `python -m tools.parity.store verify parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests` | 0 | 333 manifests, 22578 blobs, all `available` | `verify-current.log` |
| `python -m tools.parity.store verify parity/manifests` | **1** | refused before any hash: `parity/manifests/consumers/gltf/wand-v1.json` is not a golden public manifest (schema `uzpainter/parity/golden-public/1` expected). The file is the glTF consumer fixture added by `a34143c8` (`phase3.1_unreal-gltf-pbr-preset`) | `verify-superseded.log` |
| `python -m tools.parity.store verify parity/manifests/phase0 parity/manifests/phase1 parity/manifests/tier0 parity/manifests/tier3` | 0 | the golden subdirectories of that root: 82 manifests, 2686 blobs, all `available` (the same counts as §1) | `verify-superseded-golden-dirs.log` |
| `python -m tools.parity.store verify` | 0 | whole store: `parity-store: ok` | `verify-store.log` |
| `zig build painter -j2` | 0 | §6.1 | `build-painter.log` |
| `python -m pytest tests/python/test_capability_conformance.py::test_supported_entries_equal_the_tier0_trace tests/capabilities/test_capabilities.py -k "<§4 selection>"` | 0 | 8 passed, 21 deselected | `pytest-capabilities.log` |
| `python tmp/scratch/g1-offline/cap_evidence.py tmp/scratch/g1-offline/verify-current.log` | 0 | §6.1: 0 problems | `cap-evidence.log` |

Every hash the golden manifests name resolves in the store. The directory-wide `verify parity/manifests` of §4 is refused on this tree, so on the gate commit either the consumer fixture lives outside the golden manifest root or the check is run per golden subdirectory as above. That is an open point of item 3.1, independent of the Wand. Fixed the same day: a directory `verify` now leaves out the glTF consumer fixture, which names no store blob and which the guard validates under its own schema. Any other non-golden JSON is still refused (`tests/parity/test_store.py::test_verify_of_a_directory_leaves_out_the_gltf_consumer_fixture_only`). After the fix, `verify parity/manifests` exits 0 (`tmp/scratch/g1-offline/verify-manifests-after.log`).

### 4.2 Gate run, 2026-11-05

Store: `%LOCALAPPDATA%\UzPainter\parity-store`, read only. Each command ran once on `072756c0` and once more on `b0265f97` (after the two fixes of §8.2); the results are the same apart from the file count.

| Check | Exit | Result |
|---|---|---|
| `python -m tools.parity.guard` (before the fix below, on `fa25190d`) | **1** | `BLOCKED parity/fixtures/meshes/plane.obj: [store-hash]`; 5321 files checked, 1 blocked |
| `python -m tools.parity.guard` (`072756c0`, `b0265f97`) | 0 | store-hash rule against the store (4800 hashes); 5321 and 5329 files checked, 0 blocked |
| `python -m tools.parity.store verify parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/manifests` | 0 | current envelope: 426 manifests, 24144 blobs, all `available` |
| `python -m tools.parity.store verify parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests` | 0 | 333 manifests, 22578 blobs, all `available` |
| `python -m tools.parity.store verify parity/manifests` | 0 | 82 manifests, 2686 blobs, all `available` (the glTF consumer fixture left out, §4.1) |
| `python -m tools.parity.store verify` | 0 | whole store: `parity-store: ok` |

**The blocked `plane.obj` was a false positive, fixed in the guard (`072756c0`).** `parity/fixtures/meshes/plane.obj` (371 bytes, SHA-256 `7d3c5f616c2abf4b06050434fa943d19dcb15ec998245a211d1d4ca7e95197fe`) is an authored fixture: its header says it is authored by UzmiGames (Apache-2.0), it was committed in `6a2f26cc` on 2026-10-10, and current-envelope Tier 0 manifests declare it as an input by path and hash. On 2026-10-26 the private store kept a copy of it as an authored input (`inputs/7d3c5f61….json`, schema `uzpainter/parity/store-input/1`, `path` `parity/fixtures/meshes/plane.obj`; decision 144), and the blob joined the store index. The guard's `store-hash` rule read every index hash as a recorded Painter output. It now leaves out, when it reads the owner's store, the blobs kept only as authored inputs; a blob that a corpus record also names stays blocked. On the owner's store: 152 input entries, 2 of them also named by a corpus record, so 150 hashes leave the rule (4950 to 4800). `plane.obj` is the only stored input that is also a repository file. Test: `tests/parity/test_guard.py::test_cli_passes_an_authored_input_the_store_keeps_and_blocks_a_recorded_one`; `parity/GUARD.md` §1.

### 4.3 Second gate run, 2026-11-05 evening (`58f7260b`)

| Check | Exit | Result |
|---|---|---|
| `python -m tools.parity.guard` | 0 | store-hash rule against the store (4800 hashes); 5344 files checked, 0 blocked |
| `python -m tools.parity.store verify` on the current envelope's manifests | 0 | 426 manifests, 24144 blobs, all `available` |
| the same on `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests` | 0 | 333 manifests, 22578 blobs, all `available` |
| the same on `parity/manifests` | 0 | 82 manifests, 2686 blobs, all `available` |
| `python -m tools.parity.store verify` | 0 | whole store: `parity-store: ok` |

## 5. Phase 1 tasks (roadmap rule 3)

Checked 2026-11-05 on `072756c0`: `docs/task-index.md` names 43 Phase 1 tasks. 42 are archived under `.rulebook/archive/`, the last being `2026-11-03-phase1.25_pilot-wand`. The only `phase1.*` task under `.rulebook/tasks/` is this gate, `phase1.26_gate-g1`.

## 6. Capability manifest (roadmap rule 3)

Regenerated by `zig build painter -j4` at `39d8d7b`: `zig-out/bin/capabilities.json`, SHA-256 `4a52afe92dd75cc6bb69e1f6a3b6ee39f950cad58536cc67ddbc91e5682a557a` (1 095 027 bytes). It is byte-identical to a by-hand run of `tools/capabilities/generate_capabilities.py` with the build's arguments. `UzPainter.exe capabilities` (SHA-256 of that Debug exe: `4906ab99189f82f1567066dfedd7829bb533b5f96ad99a44984e7ad71fb837c9`) prints the same manifest. Profile `painter-12.1-api-0.3.7`.

| Status | Entries |
|---|---|
| `supported` | 546 (485 `any`, 61 `compositor`) |
| `pending-evidence` | 656 |
| `release-gap` | 364 |
| `desktop-only-omitted` | 15 |

Every `supported` entry has `since` and a non-empty `tier_evidence`. Every golden it names is a Tier 0 public manifest of the current envelope: 68 distinct goldens out of 243, all `available` in the store (§1). None is missing. The `any` entries cite exactly the goldens of `tools/capabilities/tier0-trace.json` (`test_supported_entries_equal_the_tier0_trace`).

| Input | SHA-256 |
|---|---|
| `tools/capabilities/generate_capabilities.py` | `2b8a0503237014dd6bb9b2b692a906aeb1f42e69f07edf88fbbdd697c039272f` |
| `tools/capabilities/compositor-capabilities.json` | `2433b6bbc19a40bd1ea6e87fdafd3ebc93da6adce9a46fe00e87e817ec898e08` |
| `tools/capabilities/uzpainter-additions.json` | `fbb340f8a0825ef543c813130cb133c7779d4c9a275e2176dfdd46e668791df9` |
| `tools/capabilities/tier0-trace.json` | `ba5d4e30686622005773f748d26975059e4e09e6e6ba4722cdf1f5a5412db761` |

The manifest hash recorded at the gate is the one from the Phase 1 build of the gate commit. The Wand's padding work and phase1.24 item 4.1 can still change it.

### 6.1 Pre-gate regeneration on `8709033a` (2026-10-21, not the gate commit)

`zig build painter -j2` exit 0 on a clean checkout of `8709033a`: `zig-out/bin/capabilities.json`, SHA-256 `4b0a7c47d58d7cf52b43e3c034d920e3fc336f0fad2757606b0561752be8f40a` (1 441 105 bytes). Profile `painter-12.1-api-0.3.7`, current envelope `painter-12.1.5+js-api.1.1.20`.

| Status | Entries |
|---|---|
| `supported` | 926 (864 `any`, 60 `compositor`, 2 `mesh-map`) |
| `pending-evidence` | 309 |
| `release-gap` | 365 |
| `desktop-only-omitted` | 15 |

Every `supported` entry has `since` and a non-empty `tier_evidence`. Every golden it names is a Tier 0 manifest of the current envelope: 99 distinct goldens out of 274, and every blob of each is `available` in `verify-current.log` (§4.1). None is missing (`cap-evidence.log`). The `any` entries cite exactly the goldens of `tools/capabilities/tier0-trace.json` (`test_supported_entries_equal_the_tier0_trace`, §4.1).

| Input | SHA-256 (at `8709033a`) |
|---|---|
| `tools/capabilities/generate_capabilities.py` | `0bf8f2e8a307947d7d27c845bab6502b7ac7c646a1137dd85a9fb6a517db5791` |
| `tools/capabilities/painter-api-inventory.json` | `65ede9fa0177200cf7dcb2006ec66cb45ed1390c3797ef6f8a2688c2f73c44ea` |
| `tools/capabilities/uzpainter-additions.json` | `e9c5d640227d7a4402ba649f580cf8528c2f4e73e2154279cdb367f8ca5000ef` |
| `tools/capabilities/compositor-capabilities.json` | `f25e670c28c15f9aa173984d98623e9c9d8558465a3fcbee5e36675ef98aea56` |
| `tools/capabilities/tier0-trace.json` | `069a302020616218f339c15dad1b88a04ed0015aacea257456b0ab19d5574130` |
| `tools/capabilities/mcp-tools.json` | `a12b5178004e4e857baaac6a35032e4d0d0396ee300aec69f553f93431f718a5` |
| `tools/capabilities/operation-matrix.json` | `d41203bfff77523f87747c35b1cce34d45017970b3cf2b7037933f60644eaa5c` |
| `parity/envelopes/registry.json` | `361bd5262722c43fd4aaa274726e1ec4cfeb6f05ed88afc296f287e01f342762` |

The Wand's padding work (item 2.7) can still change this manifest, so the gate records the hash from the gate commit's build.

### 6.2 Regeneration at the gate run (2026-11-05, `072756c0`)

`zig build painter -j4` exit 0 on the shared checkout at `072756c0`, no warning: `zig-out/bin/capabilities.json`, SHA-256 `005c916800adf812a15c0cac8069cde5a8558acc5991e5ae8d88b43aeeea5b8b` (1 558 752 bytes); `UzPainter.exe` SHA-256 `acdaf661e28d43487da71a1cd9d3da1628bcd471003bfc8db15181ad029f3118`. Current envelope `painter-12.2.0+js-api.1.1.20-env-a981b586eae7`.

| Status | Entries |
|---|---|
| `supported` | 974 (910 `any`, 52 `compositor`, 2 `backend:vulkan`, 2 `compositor:height`, 2 `compositor:minification`, 2 `mesh-map`, 1 each `compositor:ocio`, `compositor:mask-stack`, `compositor:content-stack`, `compositor:normal-directx`) |
| `pending-evidence` | 328 |
| `release-gap` | 338 |
| `desktop-only-omitted` | 15 |

Every `supported` entry has `since` and a non-empty `tier_evidence`, and the generator refuses one that names anything but a Tier 0 public manifest of the current envelope. The entries cite 111 distinct goldens of the envelope's 333 Tier 0 manifests; every one of their 8660 listed blobs is `available` in the `store verify` of §4.2 (0 problems). The check ran inline over the build's manifest, the registry and the verify log (`tmp/scratch/g1-cap-evidence.log`).

| Input | SHA-256 (at `072756c0`) |
|---|---|
| `tools/capabilities/generate_capabilities.py` | `0bf8f2e8a307947d7d27c845bab6502b7ac7c646a1137dd85a9fb6a517db5791` |
| `tools/capabilities/painter-api-inventory.json` | `85bffd3fe35f08dd166bb6fe009afae963b6cb1e865ed6474de741b15b59d129` |
| `tools/capabilities/uzpainter-additions.json` | `a349c4afa0d88b1ab8e71ba66aab6089932e492732761149584ca208185b832d` |
| `tools/capabilities/compositor-capabilities.json` | `f25e670c28c15f9aa173984d98623e9c9d8558465a3fcbee5e36675ef98aea56` |
| `tools/capabilities/tier0-trace.json` | `d0bddebd23c337a38d79666903a623f91c436a277aece54c4e0a50e7e8a99026` |
| `tools/capabilities/mcp-tools.json` | `0867ed6eff10d20a5118bff9bb6ad85225f6801fe79b2572d8e5e9d50fa77b51` |
| `tools/capabilities/operation-matrix.json` | `70c87ac6f7aa89da6a45f00d10f297da372ebb7b8a8fef694f97e0c6d451971c` |
| `parity/envelopes/registry.json` | `721a547d493a38224c5ed5aaf2206b5b100956d07e5bbe51fc911d15e6f71377` |

This is not yet the gate's manifest: `b0265f97` changes the inventory (`resource.Usage.FILTER` becomes a release gap, §8.2; inventory SHA-256 `924534c9…5f21`), and the trace fixes of §8.3 will change the evidence. The hash recorded at closure comes from the build of the gate commit. The untracked `capabilities.json` at the repository root (2026-10-23, SHA-256 `f982572f…8967`) is not this gate's: the build writes only `zig-out/bin/capabilities.json`, and the generator writes elsewhere only when called by hand with `--output`.

### 6.3 Regeneration at the second gate run (`58f7260b`)

`zig build painter -Doptimize=ReleaseFast -j4` exit 0 on `58f7260b`: product `zig-out/bin/UzPainter.exe` SHA-256 `4c5788b0f5885198be92222a75460a01206e96d16a7f2792c733b2e27d9eb62c` (18 036 224 bytes); `zig-out/bin/capabilities.json` SHA-256 **`ecbbfa8d94e5fe0f9ae5de2eb4efb2e536d6c6d93f60ce1353363eacef7f6b64`** (1 562 797 bytes).

| Status | Entries |
|---|---|
| `supported` | 985 (921 `any`, 52 `compositor`, 2 each `backend:vulkan`, `compositor:height`, `compositor:minification`, `mesh-map`, 1 each `compositor:ocio`, `compositor:mask-stack`, `compositor:content-stack`, `compositor:normal-directx`) |
| `pending-evidence` | 327 |
| `release-gap` | 328 |
| `desktop-only-omitted` | 15 |

Every `supported` entry has `since` and a non-empty `tier_evidence`; they cite 111 distinct goldens of the current envelope's 333 Tier 0 manifests, and all 8660 of their listed blobs are `available` in that run's `store verify` (§4.3): 0 problems (`tmp/scratch/g1r2-cap-evidence.log`). The commits after `58f7260b` in this record (§9.2) change tests only, so the manifest inputs below are those of the commit that holds this record.

| Input | SHA-256 (at `58f7260b`) |
|---|---|
| `tools/capabilities/generate_capabilities.py` | `0bf8f2e8a307947d7d27c845bab6502b7ac7c646a1137dd85a9fb6a517db5791` |
| `tools/capabilities/painter-api-inventory.json` | `64ded30f5612e6cade1291370563e2bd0af01bcc8d74d360d235eef720427409` |
| `tools/capabilities/uzpainter-additions.json` | `ad9296e575586992e026ab9d0ebe7379ccdc0c4d8b93afc66cbc97dea73c879a` |
| `tools/capabilities/compositor-capabilities.json` | `f25e670c28c15f9aa173984d98623e9c9d8558465a3fcbee5e36675ef98aea56` |
| `tools/capabilities/tier0-trace.json` | `9a11291a8e043afe2f3d082dfca8ef9c591a79852c3736e575a55f006930b92e` |
| `tools/capabilities/mcp-tools.json` | `0867ed6eff10d20a5118bff9bb6ad85225f6801fe79b2572d8e5e9d50fa77b51` |
| `tools/capabilities/operation-matrix.json` | `70c87ac6f7aa89da6a45f00d10f297da372ebb7b8a8fef694f97e0c6d451971c` |
| `parity/envelopes/registry.json` | `721a547d493a38224c5ed5aaf2206b5b100956d07e5bbe51fc911d15e6f71377` |

## 7. Phase 2 duration Hypothesis (owner Q14, roadmap rule 6)

Revised at this gate run, 2026-11-05, from the Wand checkpoint of `docs/roadmap.md` (decision 035) and the Phase 2 archive dates.

- **Measured.** Every Phase 2 feature task is archived: 14 of 18 by 2026-10-20 (supervisor, MCP, preview, recipe children), `phase2.2_recipe-and-diagnostics` and `phase2.9_pilot-belt` on 2026-11-03, `phase2.10_pilot-tunic-recovery` on 2026-11-05. Only `phase2.11_gate-g2` is open. Each islanded pilot passes under its own owner exception, not exactly: the Sash (Belt v5) under EXC-012 (decision 399), the Tunic under EXC-011 version 2 (decisions 398, 401). Phase 2 feature work took 26 calendar days from the task's creation on 2026-10-10 to the Tunic's archive.
- **Revised Hypothesis for the rest of Phase 2:** G2's record only, under 1 week once G1 is accepted, plus the repair of the full gate. This gate run shows what that repair costs: the features archived on their affected tests (CLAUDE.md, 2026-10-12) left a full-suite backlog of about 20 root causes in 5 h of suite time (§8). G2's own gate run is expected to start from that backlog, so its duration is extrapolated, not measured.
- **Unchanged:** the exact `infinite` padding and island edges of all three pilots stay with `phase3.1_export-island-padding`, which has no estimate (`docs/roadmap.md`).

## 8. Full local gate (decision 200)

Run once, 2026-11-05, on the shared checkout at `072756c0ce7d2efc73e836f869d3bb087e12b1dd` (Windows 11 Pro 10.0.26200, NVIDIA GeForce RTX 4090, Zig 0.15.2, Python 3.13.9), under `python -m tools.native_lock` as owner `g1-gate`. The checkout is shared (`AGENTS.override.md`: no worktrees), so the tested tree is that commit plus other sessions' uncommitted files, of which the three parked decision-245 test files were left out of every check below by path (`tests/parity/test_normal_empty_height_gate.py`, `tests/parity/test_normal_empty_height_native.py`, and `tests/export/test_normal_empty_height_prediction.py`, whose working copy is another session's edit; its committed version passes mypy and ruff).

| Step | Command | Result |
|---|---|---|
| Type-check | `python -m mypy <the 701 committed .py files of the configured roots>` | exit 0, no issues. The configured `python -m mypy` over the working tree finds 9 errors, all in two untracked parked files (`tests/parity/test_normal_empty_height_gate.py`, `tools/parity/tier0_semantics/normal_empty_height_gate.py`) |
| Lint | `python -m ruff check . --extend-exclude <the parked files>` | exit 0. Over the whole working tree: 1 error (RUF043), in the untracked `tests/parity/test_normal_empty_height_gate.py` |
| Selftest | `zig build painter -j4`, then `zig-out/bin/UzPainter.exe selftest` | exit 0: 18 checks PASS, DX12 hardware slice passed, Vulkan slice passed |
| Vendoring check | `python -m tools.vendoring.vendor_check --no-build` | exit 0: 97 vendored files; the build-path rule runs in the suite (`test_full_check_with_build_passes`, row 8.3) |
| Guard | `python -m tools.parity.guard` | exit 0 (§4.2) |
| Full suite | `python -m pytest -p no:cacheprovider -q -rfEsxX --junitxml=… --ignore=<the three parked files>` | **exit 1**: 7461 collected; **96 failed, 3 errors**, 7328 passed, 32 skipped, 2 xfailed, in 17 000.65 s (4 h 43 min) |

### 8.1 What moved under the suite

The run was not isolated. Other sessions committed five commits during it (`6aa7f141` to `1d16098b`, phase3.1 work), added an untracked decision 402, and edited `docs/`, `parity/semantics/height-to-normal.json`, `tools/parity/fit/normal.py` and evaluator tests. The native lock's 5400 s stale rule let another owner (`height-magnification`) take it over after 90 min, so native builds and GPU runs of that session overlapped the suite. Failures that this movement explains are marked *moved tree* below; they are still failures of this run.

### 8.2 Fixed and re-run

| Failed node ids | Root cause | Fix | Re-run |
|---|---|---|---|
| 20 Tier 0 replays whose only trace difference was `project.get_uuid` (of the 71 below) | `2daad902` made `painter_side.py` read `project.get_uuid()` after `project.create` (the ownership check for guarded cleanup); the compared-replay trace credited it to `setup`, although no recorded output holds that value | `1f830aca`: the check moves to `own_project_identity()`, whose calls the trace attributes to `bookkeeping` (left out of `exercised`); test `tests/python/test_capability_trace.py::test_the_project_identity_check_is_bookkeeping_not_compared`. `tier0-trace.json` unchanged | the 71 node ids once, under the native lock: `get_uuid` gone from all; 20 pass |
| `tests/python/test_capability_conformance.py::test_every_public_symbol_has_an_entry` | `6a8923c3` inventoried `substance_painter.resource.Usage.FILTER` as `pending-evidence` (implemented); the facade has no such member (reading it raises `NotYetSupported`) | `b0265f97`: the entry is a `release-gap` owned by `phase3.2_proc-filter-families`; `tests/capabilities/test_capabilities.py` 28 passed | passes |

### 8.3 Still failing (75 failed, 3 errors after §8.2)

| Node ids | Cause found | Owner |
|---|---|---|
| 51 Tier 0 replays in `tests/python/test_pyapi_*_tier0.py`, `test_pyapi_baking.py`, `test_pyapi_backend_tier0.py` (`check_trace`) | Their committed traces predate `ae45b4bc` (2026-10-25, the trace records successful native property reads), which regenerated only some replays. They now also exercise event fields (`BusyStatusChanged.busy` 41, `ProjectAboutToSave.file_path` 7, export, engine, texture-state and shelf event fields), `UVProjectionParams.uv_transformation` (37) and `Stack.get_channel`/`has_channel`, and no longer credit `FillLayerNode.set_source` (7) or `FillEffectNode.set_source` (4). The recorder's serialisers compare these fields; the fix is a decision-112 regeneration of these traces and the matching `tier_evidence`, not done here | coordinator (capability evidence) |
| `tests/python/test_pyapi_lifecycle_tier0.py::test_observed_probe_events_equal_painter[phase1-reload-mesh]` | Output difference: Painter 12.2.0 records `LayerStacksModelDataChanged` at s9 and s11; the facade emits none | facade events (`phase1.24` area) |
| `tests/python/test_pyapi_reload_order_tier0.py`, 4 ids (`zam`, `mza` × two tests) | The current envelope's `p22b-reload-order-*-all-origins` goldens hold 2 recordings; the tests (decision 338) need 6 from 3 sessions, as the 12.1.5 envelope had | recording batch (Painter session) |
| `tests/evaluator/test_compositor_core.py::test_excluded_features_raise_not_yet_supported_before_any_mutation` | A procedural source now fails with `evaluator:missing_resource … no procedural snapshot provider` instead of a `NotYetSupported` kind | `phase3.1_proc-backend-seam` |
| `tests/export/test_export_encoders.py::test_published_export_processing_reproduces` | `parity/semantics/export-processing.json` no longer equals what the comparisons derive (its `corpus` and `entries` differ) | `phase3.1_export-island-padding` (padding goldens) |
| `tests/parity/test_padding_turn_exact.py::test_the_committed_mesh_and_request_are_the_generators[x90]`, `[oblique]` | The turn-exact goldens are no longer among the requested goldens (they were admitted) | `phase3.1_export-island-padding` |
| `tests/parity/test_tier0_gate.py::test_corpus_covers_every_child`, `test_manifest_names_its_private_record_by_hash_only[tier0/assets3d/export-padding-kernel-wand-2048]`, `test_stability_report_classifies_every_golden` | A new Tier 0 family `tier0/assets3d` whose manifest names its golden `tier0/semantics/…`; the stability report does not classify the goldens admitted since (29 missing, e.g. `export-padding-turn-exact-x90`, `ocio16-*`, `srgb-bitmap-minification-random`) | `phase3.1_export-island-padding`; Tier 0 stability report |
| `tests/export/test_tga_capture_replay.py::test_r322_tga_capture_diagnostic` | `TGA diagnostic setup or execution failed`, again on re-run; the stage was not read | R-322 TGA work |
| `tests/sources/test_doc_overlap.py::test_inventory_prose_shares_no_span_with_the_documentation` | `.rulebook/decisions/368-…md:64`: a table cell occurs verbatim in the Adobe documentation | decision 368's author |
| `tests/sources/test_doc_overlap.py::test_checked_files_cover_the_analyses_review_and_decisions` | *Moved tree*: the untracked decision 402 appeared mid-run; passes on re-run | none |
| `tests/sources/test_revision_check.py::test_repository_revisions_are_valid` | `docs/approved-sources.md` neither clears nor quarantines new analyses (`docs/analysis/padding-world-offset-residuals/01-…`, `02-…`, `docs/analysis/painter-recording-backlog/01-inventory.md`, …) | clean-room provenance audit |
| `tests/supervisor/test_headless.py::test_a_session_without_a_console_shows_no_window[vulkan-True]`, `[dx12-False]` | The detached adapter (`execute_python`) exits 3 with empty stderr; not diagnosed (GPU runs of another session overlapped) | supervisor |
| `tests/vendoring/test_modifications.py::test_standalone_static_library_build` | First read here as a stray file `-x` (*moved tree*); that was wrong. Since `022a909d` (decision 394) each artifact compiles a generated stamp as `zig clang -x c <stamp>`, and the test took `-x` as the source path. Fixed in `9035bae1` (§9.2) | this gate |
| `tests/vendoring/test_render_core_integration.py`, 3 errors (`test_relocated_build_*`) | The relocated build cannot read `src/procedural/filter_gate_pins.cpp`'s `#embed` of `parity/envelopes/…/requests/tier0/api-probes/filter-context-settings-a.json` (`3f536fb3`) | `phase3.1_proc-backend-seam` |
| `tests/vendoring/test_render_core_integration.py::test_build_script_paths_stay_in_the_repository` | `build.zig` names `export/cook_uzengine.cpp` (`0b838186`), which the test reads as a UzEngine path | `phase3.3_uze-png-cook-cli` |
| `tests/vendoring/test_render_core_integration.py::test_no_submodule_runtime_lib_or_patch_queue` | An ignored leftover `scripts/tmp/r322-integration.patch` (2026-10-24) counts as a patch queue; `scripts/tmp/` is a temporary folder that only the owner may remove (`AGENTS.override.md`) | owner |
| `tests/vendoring/test_vcruntime.py::test_folder_matches_the_pinned_files`, `test_signature_ignores_the_parent_module_path` | The Authenticode signer Windows reports for the vendored `thirdparty/vc-runtime` DLLs changed from "Microsoft Windows Software Compatibility Publisher" to "Microsoft Windows" (catalog signature of this OS build) | vendoring (re-pin or OS question) |
| `tests/vendoring/test_vendor_check.py::test_full_check_with_build_passes` | *Moved tree*: the fresh build log records `072756c0`, HEAD was `1d16098b` when the check ran; not re-run | none |

G1 stays open until these are fixed at their root and the full gate passes once on the gate commit.

### 8.4 Repairs after the first run (other sessions, 2026-11-05)

| Commit | Repairs (§8.3 row) |
|---|---|
| `147f07b6` | decision 368's probe count reworded in our own words (doc overlap) |
| `dbc31df0` | `docs/approved-sources.md` quarantines the six uncited analyses (revision check) |
| `59b9e392` | `build.zig` may name its own UzEngine-format sources (`cook_uzengine.cpp`) |
| `8a3dd16a` | the vc-runtime DLLs are pinned on their embedded signer, not Windows' verdict signer |
| `3b21a5ce` | a procedural source without a snapshot provider is `unsupported_source`, not `missing_resource` (compositor `NotYetSupported` case) |
| `db7ececd` | `build.zig.zon` paths include the `#embed` targets under `parity/` (the three relocated-build errors) |
| `70404be9` | the headless adapter call selects the diagnostic-import context (headless supervisor, both ids) |
| `17529d7c` | `parity/semantics/export-processing.json` republished over the goldens admitted since 2026-10-25 |
| `e02d9e8d` | the Tier 0 gate counts the `assets3d` folder's semantics goldens; the turn-exact generator check (tier0 gate ×3, `padding_turn_exact` ×2) |
| `58f7260b` | the 51 stale Tier 0 traces regenerated after an evidence audit (decision 403; field tracing started in `7604e4e1`, not only `ae45b4bc`) |

Also in the tree of the second run: `ee0e4723` (`phase3.1_height-magnification-fit` archived; decision 402, native `CheckSampling` change `3325b5df`) and `6b08d37a` (new unrecorded padding requests).

## 9. Second full local gate (decision 200)

Run once, 2026-11-05 from 16:05, on `58f7260ba745f2051808dbb56f67c59b2187f74e`. The checkout was quiet: no other build or test process, and HEAD was the same at the start and end of the run. The native lock was held as `g1-gate` for the whole run, its timestamp refreshed every 5 minutes so that no session's 5400 s stale rule could take it. The only uncommitted files were other sessions' parked ones; the three parked decision-245 test files were left out by path as in §8.

| Step | Command | Result |
|---|---|---|
| Product build | `zig build painter -Doptimize=ReleaseFast -j4` | exit 0 (§6.3) |
| Selftest | `zig-out/bin/UzPainter.exe selftest` (ReleaseFast) | exit 0: 18 checks PASS, 0 FAIL; DX12 and Vulkan hardware slices passed |
| Type-check | `python -m mypy <the 708 committed .py files of the configured roots>` | exit 0, no issues |
| Lint | `python -m ruff check . --extend-exclude <the parked files>` | exit 0 |
| Vendoring check | `python -m tools.vendoring.vendor_check --no-build` | exit 0, 97 vendored files; the build-path rule is `test_full_check_with_build_passes` in the suite: passed |
| Guard | `python -m tools.parity.guard` | exit 0, 5344 files, 0 blocked (§4.3) |
| Full suite | `python -m pytest -p no:cacheprovider -q -rfEsxX --junitxml=… --ignore=<the three parked files>` | **exit 1**: **10 failed**, 7441 passed, 31 skipped, 2 xfailed, 0 errors, in 16 165.56 s (4 h 29 min) |

The 31 skips name their reason (for example the OCIO16 export cases that need an approved `UZP_OCIO16_EXPORT_TESTS_EXE`); the 2 xfails are the bitmap-defaults OCIO release gap (decision 190) and the Sash's production round, which is expected to refuse the islanded export.

### 9.1 The 10 failures

| Node ids | Cause | Status, owner |
|---|---|---|
| `tests/parity/test_initial_paint_cleanup.py::test_only_successful_owned_creation_can_arm_cleanup[True]`, `[False]` | Introduced by this gate's `1f830aca`: the test extracts `create_project` alone from `painter_side.py` by AST, and the identity check now lives in `own_project_identity()` (NameError) | **fixed** in `78eb9e3b`; 2 passed on re-run |
| `tests/vendoring/test_modifications.py::test_standalone_static_library_build` | The compile-list parser took the `-x` of the native input stamps' `zig clang -x c <stamp>` (`022a909d`, decision 394) as a source path | **fixed** in `9035bae1`; 1 passed on re-run under the native lock |
| `tests/python/test_pyapi_lifecycle_tier0.py::test_observed_probe_events_equal_painter[phase1-reload-mesh]` | Painter 12.2.0 records `LayerStacksModelDataChanged` at s9 and s11; the facade emits none. Needs repeated Painter recordings to decide | known; recording batch |
| `tests/python/test_pyapi_reload_order_tier0.py::test_reload_results_equal_every_painter_recording[zam]`, `[mza]`, `::test_independent_alias_origin_equals_every_painter_recording[zam]`, `[mza]` | The current envelope's `p22b-reload-order-*-all-origins` goldens hold 2 recordings; decision 338's tests need 6 from 3 sessions | known; recording batch |
| `tests/export/test_tga_capture_replay.py::test_r322_tga_capture_diagnostic` | The R-322 TGA diagnostic stops in setup or execution: the OCIO16 gap | known; `phase3.2_unreal-ue56-packed-preset`, awaiting a root decision |
| `tests/vendoring/test_render_core_integration.py::test_no_submodule_runtime_lib_or_patch_queue` | Leftover ignored files in `scripts/tmp/` (`r322-integration.patch` and one more) count as a patch queue; `scripts/tmp/` is a temporary folder that only the owner may remove (`AGENTS.override.md`) | known; awaiting the owner's OK |

### 9.2 Fixes after the second run

| Commit | Change | Re-run |
|---|---|---|
| `78eb9e3b` | `tests/parity/test_initial_paint_cleanup.py` extracts `own_project_identity` and `create_project` into one namespace; its assertions are unchanged | the two node ids: 2 passed |
| `9035bae1` | `tests/vendoring/test_modifications.py` sets the native input stamp commands apart: language `c`, inside the build's own cache, one each for `uzrendercore` and `uzp-vendor-tests`; every other command is checked as before | the node id under the native lock: 1 passed (90.6 s) |

After these, the full gate's only failures are the 7 known ones of §9.1. G1 is not archived while any test is red.
