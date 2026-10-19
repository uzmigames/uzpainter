# G1 "Foundation green" — gate record (draft)

Task `phase1.26_gate-g1` (`docs/dag.md` G1, D14; `docs/roadmap.md` Phase 1 gate, rules 2, 3 and 6). **Draft, pre-verified 2026-10-19** on the owner's machine (Windows 11 Pro 10.0.26200, NVIDIA GeForce RTX 4090, Zig 0.15.2, Python 3.13.9) on a clean checkout of `main` `39d8d7b`. Every check below is CPU only: no GPU run was made for this draft. Numbers and hashes only: every recorded Painter output stays in the private store. SHA-256 values are of the committed file bytes at `39d8d7b` (`git show 39d8d7b:<path>`), as in the G0 record.

**Result: G1 open.** Every item that does not depend on the Wand pilot is evidenced below. Pending: the Wand clauses (§2, `phase1.25_pilot-wand`, item 2.2 of the gate), `phase1.24_python-api-facade` (§3.6), the other open Phase 1 tasks (§5), the gate-commit re-run of the checks (§4) and the Phase 2 duration Hypothesis (§7). The record is final only when it is re-run on the gate commit.

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
| Wand v1 maps equal to the private Painter goldens (Tier 1) | `phase1.25_pilot-wand` | §3.5 | **pending** (item 2.7, then 3.1) |
| Wand v1 maps byte-stable across two runs | `phase1.25_pilot-wand` | §3.5 | **pending** (item 3.2) |
| The three pipeline scripts run unchanged through the adapter | `phase1.24_python-api-facade` | §3.6 | evidenced by item 3.2; the task is not accepted |
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

All their children are archived (§5).

### 3.5 P1-WAND — `phase1.25_pilot-wand` (pending)

Open. Done: items 2.1-2.6, 3.4 and 3.5. Open: 1.1 (needs `phase1.24_python-api-facade` accepted), 2.7 (`infinite` padding on UV-islanded sets, in progress), 3.1 (Tier 1 equality on DX12), 3.2 (byte-stable across two processes), 3.3 (save/reopen), 4.1, 4.2 (decision 035 re-forecast) and 5.1-5.3. The current comparison report predates 2.7's close and is not gate evidence yet.

| Evidence (current, not final) | SHA-256 |
|---|---|
| `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/phase1/tier1/wand-v1.json` | `6e54e7f6c05071d26e631ed29163b94e1f3433d6958f12566d61a1a1b7b96478` |
| `parity/reports/phase1/tier1-wand-v1.json` | `d2f89e107cd9479c866ca2740fa609fdef295350e013572d88d25ff0c9500722` |

### 3.6 P1-PYAPI — `phase1.24_python-api-facade` (not accepted)

Children `phase1.19_pyapi-native-module` to `phase1.23_pyapi-pipeline-adapter` archived 2026-10-12. The pipeline-script clause is evidenced by item 3.2 (`tests/adapters`: 44 passed, report §4.1). This draft did not re-run it: the adapter's export runs on DX12. The task still lacks:

- item 1.1: its text still says `phase1.18_export-engine` and `phase1.8_project-store` are not accepted. Both are now archived (2026-10-12, 2026-10-13), as is `phase1.3_document-model`. The item is ready to tick on that evidence.
- item 3.1: owner question q1 (`.rulebook/tasks/phase1.24_python-api-facade/.metadata.json`, pending since 2026-10-12): may UzPainter ship Painter's label text for the Dota 2 template's User0-User3?
- item 3.4: P22-B, the 257 `pending-evidence` Painter symbols that decision 189 moved here (probe vocabulary, requests and recordings, by module).
- item 4.1: its acceptance, after 1.1, 3.1 and 3.4.

| Evidence | SHA-256 |
|---|---|
| `parity/reports/phase1/python-api-facade.md` | `ca279fb9a8d70bd3b70a85fd0c9f7c75f8aeda7279f56ace670fb59308310e84` |
| `parity/reports/phase1/pyapi-pipeline-adapter.md` | `02f0fccb38464071a128bba128e7c426884e83983a3f0c9cbc106e56346cf730` |

### 3.7 Exceptions relied on

`parity/exceptions.json` (SHA-256 `f4ef87337725330216ffd0c676eca96987592984ab45f3abb54a1f3b874c6633`) holds EXC-001 to EXC-006 (Tier 0, basis `oracle_instability`) and EXC-007 (Tier 1, `tier1/pilot/wand-v1`), which is withdrawn in version 2 (decision 259). The Wand's own list of exceptions relied on is pending (§3.5, item 4.1).

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

## 5. Phase 1 tasks not archived (roadmap rule 3)

43 Phase 1 tasks are in `docs/task-index.md`. 39 of them are archived under `.rulebook/archive/`, together with 5 Phase 1 analysis and docs tasks outside the index. Open:

| Task | Open items | Blocked by |
|---|---|---|
| `phase1.15_compositor-colour-fits` | 3.1, 4.1, 5.1-5.3 | Items 2.1-2.9 are done. 3.1 and 4.1 need the local DX12 run on the owner's machine for every case lifted after the 2026-10-13 run. That run left 2.1, 2.5 and 2.6 to lift, and 2.7-2.9 came later. Then the tail. |
| `phase1.24_python-api-facade` | 1.1, 3.1, 3.4, 4.1 | §3.6 |
| `phase1.25_pilot-wand` | 1.1, 2.7, 3.1-3.3, 4.1, 4.2, 5.1-5.3 | §3.5 |
| `phase1.26_gate-g1` | this gate | every row above |

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

The manifest hash recorded at the gate is the one from the Phase 1 build of the gate commit. The Wand's padding work and phase1.24 item 3.4 can still change it.

## 7. Phase 2 duration Hypothesis (owner Q14, roadmap rule 6)

Pending. Decision 035 makes it the measured re-forecast of `phase1.25_pilot-wand` item 4.2, made when the pilot completes.
