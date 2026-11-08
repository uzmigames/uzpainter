# G2 "Pilot parity" — gate record

Task `phase2.11_gate-g2` (`docs/dag.md` G2, D14; `docs/roadmap.md` Phase 2 gate, rules 2, 3 and 6). Written 2026-11-08 on the owner's machine (Windows 11 Pro 10.0.26200, NVIDIA GeForce RTX 4090, Zig 0.15.2, Python 3.13.9) on the shared checkout at `main` `a0e07449b5ac0c23524e0010b5622077fcc067e9`, after every Phase 2 feature task was archived (decision 397). Numbers and hashes only: every recorded Painter output stays in the private store. SHA-256 values are of the committed file bytes at `a0e07449` (`git show a0e07449:<path>`), as in the G0 and G1 records, unless marked otherwise.

**Result: G2 open.** Every joined task is archived and accepted (§3), the exceptions relied on are owner-approved and none relaxes a structural difference (§4), the capability manifest is current (§6), and every Phase 2 task but this gate is archived (§8). One clause has no evidence: **the Belt v5 (Sash v5) dump-and-rebuild** (§3.6). `docs/roadmap.md` G2 reads "Tier 1 map comparisons and dump-and-rebuild checks pass for belt and tunic v10", and this task's spec requires that "Belt v5 and Tunic v10 Tier 1 maps and dump-and-rebuild pass". The Tunic's passes; the Sash has no dump-and-rebuild test, run or report. G2 is not archived.

No new run was made for this record (§5).

## 1. Oracle envelope

Unchanged since G1's closure: `parity/envelopes/registry.json` SHA-256 `c64a70858c2baa671f7a2b7ab963012622f9af5f5097778762aaa80ac67871f6`, current envelope `painter-12.2.0+js-api.1.1.20-env-a981b586eae7`. The Sash and Tunic goldens (`phase2/tier1/sash-v5-current`, `phase2/tier1/tunic-v10-current`) are admitted manifests of that envelope. G1's `store verify` on `6112a539` (433 manifests, 24434 blobs, all `available`; whole store `parity-store: ok`, gate-g1.md §9.4) covers them: no manifest under `phase2/` changed after `6112a539`.

## 2. Clauses of `docs/roadmap.md` G2

| Clause | Task | Evidence | Verdict |
|---|---|---|---|
| Requires G1 | `phase1.26_gate-g1` | §3.1 | met |
| Tier 1 map comparisons pass for Belt v5 under the exception policy | `phase2.9_pilot-belt` | §3.5 | met **under EXC-012, not exact** (decision 399) |
| Tier 1 map comparisons pass for Tunic v10 under the exception policy | `phase2.10_pilot-tunic-recovery` | §3.4 | met **under EXC-011 v2, not exact** (decisions 398, 401) |
| Dump-and-rebuild checks pass for Tunic v10 | `phase2.10_pilot-tunic-recovery` | §3.4 | met (digests equal, measure exports byte-identical) |
| Dump-and-rebuild checks pass for Belt v5 | `phase2.9_pilot-belt` | §3.6 | **not evidenced** |
| The Belt round completed through MCP only with Python disabled | `phase2.9_pilot-belt` | §3.5 | met (measure export, decision 398 §4's route) |
| Worker-kill, lost-acknowledgement and stalled-fence recovery tests pass | `phase2.4_supervisor-worker` | §3.2 | met (DX12 and the GPU-free Vulkan cases, decision 221) |
| Captures window-independent | `phase2.3_realtime-preview` | §3.3 | met (capture evidence only, §9) |
| Render parity is not part of G2 | — | §9 | stated |

## 3. Joined items

### 3.1 G1 — `phase1.26_gate-g1`

Archived `.rulebook/archive/2026-11-08-phase1.26_gate-g1/` (`a0e07449`), gate commit `6112a539`; every item of its `tasks.md` checked, 4.1 included. The R-322 TGA diagnostic is an owner-approved gap, a strict xfail on the decision-190 refusal alone (decision 407).

| Evidence | SHA-256 |
|---|---|
| `parity/reports/phase1/gate-g1.md` | `18084da8ba0c0df0c3f8a5ebff360545c6247427bcabb5af47d35214e2813ac9` |
| `.rulebook/archive/2026-11-08-phase1.26_gate-g1/tasks.md` | `074f6a39f4416b086a72dcc1d49fe99513138331e2c14fc30120249d66a106f0` |

### 3.2 P2-SUPERVISOR — `phase2.4_supervisor-worker`

Archived `.rulebook/archive/2026-10-20-phase2.4_supervisor-worker/` (`909457ca`) with its children `phase2.1_supervisor-ipc-worker`, `phase2.2_supervisor-admission-ledger` and `phase2.3_supervisor-jobs`; every item checked. Its item 4.1: the `02-runtime-topology.md` §7 tests pass on DX12 and, for every GPU-free case, on Vulkan; the Vulkan device cases were assigned to `phase3.1_vulkan-compute-parity` (decision 221). `supervisor-settling.json` holds 29 cases, all `pass`: DX12 on `c416de4f…` (2026-10-20), Vulkan on `90c0ecc0…` (2026-10-23).

| G2 recovery clause | Settling case ids | Tests in the second full gate on `58f7260b` (§5) |
|---|---|---|
| Worker kill | `worker_killed_during_long_job`, `_during_save`, `_during_compaction`, `_from_outside`, `native_abort`, `native_access_violation` | `test_supervisor_jobs.py::test_a_worker_killed_during_a_long_job_is_interrupted_and_resolved`, `test_settling.py::test_worker_killed_during_a_save[…]` ×2, `test_supervisor_mcp.py::test_worker_killed_from_outside`: passed |
| Lost acknowledgement | `commit_then_die_retry`, `replay_inside_window`, `replay_beyond_retention_lost_ledger`, `client_disconnect_reconnect` | `test_supervisor_admission.py::test_lost_acknowledgement_returns_the_stored_outcome`, `test_mcp_contract.py::test_a_lost_acknowledgement_is_retried_to_the_stored_outcome[stdio]`, `[http]`, `test_supervisor_mcp.py::test_lost_acknowledgement_reports_the_durable_revision`: passed |
| Stalled fence | `gpu_stall`, `device_lost` | `test_supervisor_gpu.py::test_device_fault_fails_the_job_and_relaunches_on_the_same_backend[gpu_stall-timeout-args1]`, `test_supervisor_gpu_export.py::test_export_gpu_fault_publishes_nothing_and_recovers[gpu_stall-timeout-False]`, `[…-True]`: passed |

In that full gate all 195 `tests/supervisor` cases passed, none skipped. The Vulkan `gpu_stall` and `device_lost` cases also pass on hardware (2026-10-23, `supervisor-settling.md`); G2 relies only on the DX12 and GPU-free Vulkan cases.

| Evidence | SHA-256 |
|---|---|
| `.rulebook/archive/2026-10-20-phase2.4_supervisor-worker/tasks.md` | `d3b12530efca2e2bacba7f698239874bab2a1f9c01d3e7598763c1d7c5717ee1` |
| `parity/reports/phase2/supervisor-settling.json` | `0b390eb86f3d816277e82669088b7d079a97e08bca73536de6ebcf260591ad05` |
| `parity/reports/phase2/supervisor-settling.md` | `ccb6a08468dcfb03e7cd289a72a090f544525a16b2c7f23a6bcfde606f022877` |

### 3.3 P2-PREVIEW — `phase2.3_realtime-preview`

Archived `.rulebook/archive/2026-10-20-phase2.3_realtime-preview/` (`909457ca`) with its children `phase2.1_preview-display-presets`, `phase2.1_preview-viewport-window` and `phase2.2_preview-capture`; every item checked. Its item 4.1: captures are window-independent and the preview never pauses evaluation. `preview-settling.json` holds 12 cases, all `pass`: `viewport_capture_headless` (DX12 and Vulkan), `diagnostic_captures_headless` (CPU), `painter_iray_unavailable` (CPU), `preview_stall`, `preview_window_lifecycle`, `wand_integration` and `wand_export_preview` (DX12 and Vulkan each).

In the second full gate on `58f7260b`, `tests/preview` gave 33 passed and 1 skipped: `test_preview_window.py::test_window_presents_only_complete_frames`, which reads the owner's screen and runs by hand only (decision 252); it is not a capture case. `test_preview_capture.py::test_headless_viewport_capture` and the `tests/supervisor/test_headless.py` cases (no window opened, none shown) passed.

| Evidence | SHA-256 |
|---|---|
| `.rulebook/archive/2026-10-20-phase2.3_realtime-preview/tasks.md` | `9899e9675f1431ce60209ffe5007388f53f94536f6783b6ec55f1e4aba8b9d15` |
| `parity/reports/phase2/preview-settling.json` | `75c5587c97a871dd6fb5ebf5c276509739ffa3f97ec5eec77de93de47ff9817f` |

### 3.4 P2-TUNIC — `phase2.10_pilot-tunic-recovery` (accepted under EXC-011 v2, not exact)

Archived `.rulebook/archive/2026-11-05-phase2.10_pilot-tunic-recovery/` (`fa25190d`); every item checked. The changed baseline is the owner's (decision 398): the golden is the current round `phase2/tier1/tunic-v10-current`, not the approved v10 project.

- **Tier 1** `parity/reports/phase2/tier1-tunic-v10.json`: outcome `pass`, `exceptions_relied_on` EXC-011 version 2, `structural` empty, oracle `stable`, rebuilds `repeatable`. DX12, `UzPainter.exe` `7386579a5e9d5eb63c51978eb44283851b44b44d071ac8102f7e5acd9d6671f3`, run on `fa69d085`. Covered interior / island edge / padding values per map: BaseColor 0 / 5 / 2,707,306; Height 0 / 9 / 4,188,330; Metallic 0 / 0 / 0; Normal 0 / 25,431 / 2,620,462; Roughness 0 / 3 / 1,420,314. Save/reopen export byte-identical.
- **Dump-and-rebuild**: `test_tunic_current_recipe_rebuild_exports_identical_bytes_in_the_measure_mode`: the typed state round, the dump, the rebuild into a new project in a separate `run` process; recipe digests equal and both measure exports byte-identical; `run_python` absent from all three MCP sessions. The production-mode flow test `test_tunic_current_recipe_rebuilds_the_typed_round_from_its_dump` gives equal digests with both exports refused alike (islanded padding). There is no published `recipe-rebuild-tunic-*.json`: the evidence is the test node and archive item 3.4.
- In the second full gate on `58f7260b` all six Tunic nodes of `tests/parity/tier1/test_mcp_round.py` passed: the state round, both recipe nodes, the Tier 1 maps (693 s), the save/reopen.
- The maps are the diagnostic measure export's (decision 286), not a conformant delivery: production still refuses the islanded export (decisions 245, 259; owner `phase3.1_export-island-padding`).

| Evidence | SHA-256 |
|---|---|
| `.rulebook/archive/2026-11-05-phase2.10_pilot-tunic-recovery/tasks.md` | `98a8d17792a9440a0f3e85bb70e10d18a8b42643b619a207db56192d5b3fb51c` |
| `parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/manifests/phase2/tier1/tunic-v10-current.json` | `e3b69e5451af87b32eff12d2a7bc99fa529b7769215ff9f28a94072046fa129d` |
| `parity/reports/phase2/tier1-tunic-v10.json` | `1838877088ebf462ef5b1c10c927f2669868b033c52af5df123ed885faa748cc` |
| `parity/reports/phase2/tunic-v10-input-inventory.md` | `6bb5b5541e3ca752ef2cbc3cae6ca6e383a30d94f1e5399d85717dceed0b2e6f` |
| `tests/parity/tier1/test_mcp_round.py` | `f4a17cdab15226f04c2ed66a1128336f5a48acd0c93acdf8becc54af4d6d2713` |

### 3.5 Items reaching G2 through P2-TUNIC

| Task | Archived | Acceptance (archive item 4.1) | Evidence | SHA-256 |
|---|---|---|---|---|
| `phase2.8_mcp-server` (P2-MCP), children `phase2.5`–`phase2.7` | `.rulebook/archive/2026-10-20-phase2.8_mcp-server/` (`909457ca`) | contract fixtures pass on synthetic fixtures; unavailable families reported as capability gaps | `parity/reports/phase2/mcp-contract.json` | `79701d522af557f82b8ecf32b870dcbe9671bd8cd8214e05515dfa4bae2245ba` |
| `phase2.2_recipe-and-diagnostics` (P2-RECIPE), children `phase2.1_recipe-*` | `.rulebook/archive/2026-11-03-phase2.2_recipe-and-diagnostics/` (`434c1f32`) | rebuild-from-dump equality on the Wand: digests equal, files identical, both exports `diagnostic_measure` | `parity/reports/phase2/recipe-rebuild-wand.json` | `14e5db08ad23d3af012dd43b50b18bdb318d9f9298740e06f632e51aab4e4989` |
| `phase2.9_pilot-belt` (P2-BELT) | `.rulebook/archive/2026-11-03-phase2.9_pilot-belt/` (`fc864900`) | equal maps under EXC-012; the Python-disabled MCP round completed | `parity/reports/phase2/tier1-sash-v5.json`, `parity/reports/phase2/sash-v5-mcp-round.json` | below |

Every one of these archives has no unchecked item.

**P2-BELT.** The Belt v5 pilot is the Sash v5 (decision 260: no Skeletal Mage belt piece had complete inputs); its golden is the owner's re-run `phase2/tier1/sash-v5-current` (decision 399).

- **Tier 1** `tier1-sash-v5.json`: outcome `pass`, `exceptions_relied_on` EXC-012 version 1, `structural` empty, oracle `stable`, rebuilds `repeatable`. DX12, `UzPainter.exe` `4900af0674a2d137b5c610bd4217ee3f0ec8952130455cddb89b5940b583152b` (`7d35eb99`, decision 400's mesh-map decode). BaseColor, Roughness, Metallic and Height: every covered texel equal. Normal: covered interior 0, island edge 880 values, padding 66,753 values. Save/reopen export byte-identical.
- **Python-disabled MCP-only round** `sash-v5-mcp-round.json`: outcome `completed`, `allow_python` false, `run_python_listed` false, 67 tools listed, 6 typed calls (`project_create`, `set_list`, `set_mesh_maps`, `project_save_as`, `sync_stack`, `project_save`), `export_mode` `diagnostic_measure`, `equal_to_tier1` `equal` (all five maps byte-identical to the Tier 1 run's). Round workers on Vulkan, `UzPainter.exe` `4900af06…`. The measure export is a separate `run` process after the session, not an MCP call (archive §18). The production round stays an expected failure on the islanded refusal (decision 259).
- In the second full gate on `58f7260b`, `tests/parity/tier1/sash_v5`: 4 passed, 1 xfailed (that production round).

| Evidence | SHA-256 |
|---|---|
| `.rulebook/archive/2026-11-03-phase2.9_pilot-belt/tasks.md` | `882390e95bcb2634ae2dfaa8e4d4d89368ca7c5f56fbaf7cc3d2fa01288058bd` |
| `parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/manifests/phase2/tier1/sash-v5-current.json` | `b3028e5a2a729a3340eeedbd8b76907802f10ced88f13a8159164f532ee1b44c` |
| `parity/reports/phase2/tier1-sash-v5.json` | `b7948c6310264ae78a4d1719e00764061e4c12d67d249f9517b62ddb2e7559fb` |
| `parity/reports/phase2/sash-v5-mcp-round.json` | `58875ead7f7e94a37bcb9c3fb3c288f04d517d1b8d4cf9812105557d77259ec3` |
| `parity/reports/phase2/sash-v5-input-inventory.md` | `2aabb1a0197d9cbc5c2a9a456806b68cce95aa22686b88c672876cbc751114a9` |
| `tests/parity/tier1/sash_v5/test_sash_v5.py` | `d60cac8f37c2a196a1f65bd7dbcfcb0983e28f8a9e2d07d785f3371ee98fa642` |
| `.rulebook/archive/2026-11-03-phase2.2_recipe-and-diagnostics/tasks.md` | `debd49150ff2c39fd34582fef9d651b6fc359bc6a13202d69eeeb15c8829e648` |
| `.rulebook/archive/2026-10-20-phase2.8_mcp-server/tasks.md` | `018de99c10928abd4f8ba05479e7c45e49fb9de620af3a19dec891c62ff882f3` |

### 3.6 The missing clause: the Belt v5 dump-and-rebuild

What G2 asks: `docs/roadmap.md` "Tier 1 map comparisons and dump-and-rebuild checks pass for belt and tunic v10 under the exception policy". This task's spec ("G2 MUST record that Belt v5 and Tunic v10 Tier 1 maps and dump-and-rebuild pass") and proposal ("Tier 1 maps and dump-and-rebuild pass under the exception policy (Belt v5 and Tunic v10)") say the same. `parity/CONTRACT.md` §Tier 1 lists dump-and-rebuild among the Belt v5 recipe's checks.

What exists for the Sash: two rebuilds through the adapter (repeatability) and the save/reopen export. Neither is a dump-and-rebuild, which rebuilds a new project from the recipe dump and compares recipe digests and exports, as `test_wand_recipe.py` and the Tunic's recipe nodes do. Searched on 2026-11-08: the Belt archive's `tasks.md`, decisions 192, 260, 399 and 400, `tests/parity/recipe/` (Wand only), `tests/parity/tier1/sash_v5/` (five nodes, no recipe), `tests/parity/tier1/test_mcp_round.py` (Wand and Tunic only) and `parity/reports/phase2/` (only `recipe-rebuild-wand.json`). No Sash dump-and-rebuild test, run or report exists.

The two readings:

- `docs/dag.md` gives P2-BELT the acceptance "Equal maps; Python-disabled MCP integration round completed" and P2-TUNIC "Equal maps; rebuild equal"; its G2 row says "Tier 1 maps and dump-and-rebuild pass" without naming the pilots. This task's item 2.5 confirms the Belt for "Tier 1 and the Python-disabled MCP-only round" only. On this reading the Tunic's dump-and-rebuild suffices.
- The roadmap, this task's spec and proposal, and the contract name the Belt's dump-and-rebuild. On this reading G2 needs it.

Dropping the Belt's dump-and-rebuild would narrow a gate clause, so this record does not choose: it is a root decision (Codex root; never pre-approved by a coordinator). Either route closes the clause:

1. **Run it.** A Sash measure-mode dump-and-rebuild on `sash-v5-current`, as the Tunic's: the typed round's saved project dumped, rebuilt into a new project in a separate `run` process, recipe digests equal and both measure exports byte-identical; a report `parity/reports/phase2/recipe-rebuild-sash-v5.json` under the `recipe-rebuild-report` schema. It needs a test node (the Tunic's `tunic_recipe` flow is Tunic-specific) and one GPU run under the native lock.
2. **Record the narrower reading.** A decision recording that G2's dump-and-rebuild is the Tunic's (with the Wand's of P2-RECIPE), and the roadmap and spec text aligned to `docs/dag.md`.

## 4. Exceptions relied on

`parity/exceptions.json` SHA-256 `1678b0f2635c69110cba47ae0c6d7520d53fc36bdb7ea351fb5b0693052d4815`, unchanged since G1's gate run (last change `c9156e0e`, EXC-011 v2). Checked 2026-11-08 against the register:

| Exception | Version | Tier | Domain | `approved_by`, `approved_on` | Decision record | Relied on by |
|---|---|---|---|---|---|---|
| EXC-012 | 1 | 1 | `tier1/pilot/sash-v5-current`, golden `phase2/tier1/sash-v5-current` | owner, 2026-11-03 | `399-the-owner-re-runs-the-sash-s-waist-v5-round-…` (`dfc640da1abfcff53f96e8496a0dd726e26d48b4dbb7fca09454a7b6e678f92f`) | Belt v5 Tier 1 (§3.5) |
| EXC-011 | 2 | 1 | `tier1/pilot/tunic-v10-current`, golden `phase2/tier1/tunic-v10-current` | owner, 2026-11-05 | `401-the-owner-widens-exc-011-…` (`aff6ae81c675fa79c90c7b215291acb7971ba02cba1c54a8426ab618799ec1b0`); version 1 `398-…` (`a80ed90794fbcd9c545c052c9fc23da9e74d3abfaebf78f090ca051b74ae3709`) | Tunic v10 Tier 1 (§3.4) |
| EXC-010 | 1 | 1 | `tier1/pilot/wand-v1`, golden `phase1/tier1/wand-v1` | owner, 2026-11-03 | `395-the-owner-approves-exc-010-…` (`3558a12d178c766fc4c577546d661f9f81dd4ef0bb48c234f698935ef1556af7`) | inherited through G1 (the Wand's Tier 1); the Wand's recipe rebuild itself is exact |

Each is basis `owner_scope_split`, quotes the owner's answer, and names its defect test (`tests/parity/test_verdict.py::test_exc012_catches_injected_defects`, `::test_exc011_v2_catches_injected_defects`, `::test_exc010_catches_injected_defects`; 63 `test_verdict.py` cases passed in the second full gate). **None relaxes a structural difference:** every bound is `max_abs_diff` 0 on `covered_interior` (unexcepted) and on `covered` (excepting only the listed island-edge outputs); padding is free; a comparison without a coverage mask, with a mask of another size or naming no output is held to both bounds. Both pilot reports have `structural` empty, and a refused export is a structural failure (decision 255), never covered by an exception. The Tier 0 entries EXC-001, -002, -006, -008, -009 stay relied on only as Tier 0 evidence of `supported` capabilities (gate-g1.md §3.7); no G2 clause compares under them. Not relied on: EXC-003 to EXC-005, EXC-007 (withdrawn, decision 259), EXC-011 version 1 (superseded). No exception was created or widened for this gate.

## 5. Why no new run was made

- **The full local gate.** The last full decision-200 gate ran on `58f7260b` (gate-g1.md §9): 7441 passed, 31 skipped, 2 xfailed, 10 failed, all 10 resolved before G1 closed on `6112a539` (§9.4 there). Every Phase 2 acceptance node passed in it (§3.2 to §3.5 above). JUnit `tmp/scratch/g1r2-fullsuite.xml` (untracked, SHA-256 of the file `b9fc347e31832e5cd4e09cf2dc424db6b7550477782252d458f8140fe0631186`).
- **What changed since.** `git log 6112a539..a0e07449`: one commit, `a0e07449`, which moves G1 to the archive and edits `gate-g1.md` and the archived `tasks.md`; no code, test, manifest or native source. Between `58f7260b` and `6112a539` the changes were Tier 0 manifests and requests, the envelope registry, capability inputs, parity tools and tests, all re-verified by G1's affected runs (§9.2 to §9.4 there). None touches `src/`, the supervisor, preview, MCP, recipe or pilot code paths, or `tests/parity/tier1/`.
- So the G1 full-gate evidence covers G2, under CLAUDE.md's test-time override (2026-10-12) and decision 397. The Python-disabled MCP-only Belt round, the recovery tests and the window-independent captures all have archived acceptance evidence, and each passed again in that full gate; none needed a re-run.
- The one clause without evidence (§3.6) needs new work, not a re-run.

## 6. Capability manifest (roadmap rule 3)

The gate's manifest is the ReleaseFast build of `ba0fa817` (gate-g1.md §9.3): `zig-out/bin/capabilities.json` SHA-256 **`9f4d2abc558a43bbdf32bb751b78bb0570e257d4851693ff342cb2b4655a16e5`** (1 564 459 bytes), `zig-out/bin/UzPainter.exe` `bafbd3027d182ef0b7bd169003c543064613147fa8f5fd14f159194c6d517b16` (18 036 224 bytes); both still in `zig-out/bin/` with those hashes on 2026-11-08.

Not rebuilt. The eight build inputs have the same SHA-256 at `a0e07449` as at `ba0fa817` (table in gate-g1.md §9.3). The generator also reads the repository's Tier 0 manifests, and three of them changed after `ba0fa817` (two added, one modified, plus one request; `98b21d57`, `705846ed`), so the generator was run by hand on 2026-11-08 with the build's arguments (`python -I tools/capabilities/generate_capabilities.py --inventory … --additions … --compositor … --tools … --matrix … --repo-root . --output <a throwaway file in tmp/scratch/>`, deleted after this record's commit): exit 0, byte-identical, SHA-256 `9f4d2abc…16e5`. Entries: 985 `supported`, 327 `pending-evidence`, 328 `release-gap`, 15 `desktop-only-omitted`.

**Phase 2 gaps**, as the manifest and the pilots state them:

| Gap | Where stated | Owner |
|---|---|---|
| `uzpainter.render.capture` `mode:painter_iray`: `release-gap`, raises `PathTracerUnavailable` before any work; `preview-settling.json` case `painter_iray_unavailable` passes | manifest entry; operation-matrix row (fixture `tests/preview/test_preview_capture.py::test_worker_capture_tool`) | `phase3.7_path-tracer` (P3-PATHTRACER) |
| 37 of 106 operation-matrix rows are `capability gap`: smart materials and masks, procedurals, generators, filters, anchors, instances, compare-mask and colour-selection effects, material sources, vector and font sources, 3D projections, UV tiles, the TGA/BMP/JPEG/DDS writers, TIFF/PSD/WebP/J2K (not in v1), `painter_iray` | manifest `operation_matrix` | Phase 3 and 4 owners named in each row |
| Production export of islanded texture sets with `infinite` padding refused (decisions 245, 259); all three pilots pass only through the diagnostic measure export (decision 286). No dedicated manifest entry | pilot reports and archives | `phase3.1_export-island-padding` |
| Pilot parity is under EXC-010, EXC-011 v2 and EXC-012, never exact | §4 | narrowed by `phase3.1_export-island-padding` |
| Vulkan device cases of supervisor and preview: outside G2 by decision 221; they pass on hardware since 2026-10-23 | `supervisor-settling.md`, `preview-settling.json` | `phase3.1_vulkan-compute-parity` |
| R-322 TGA diagnostic, OCIO RGB16 bitmap `unsupported_source` (decision 190): strict xfail (decision 407) | G1 | `phase3.2_unreal-ue56-packed-preset` item 2.5 |

## 7. Build, hardware, driver, backend

| Run | Commit | `UzPainter.exe` SHA-256 | Backend |
|---|---|---|---|
| Sash Tier 1 and MCP-only round | `7d35eb99` (report `f1c2b21a`) | `4900af0674a2d137b5c610bd4217ee3f0ec8952130455cddb89b5940b583152b` | DX12 (Tier 1), Vulkan (round workers) |
| Tunic Tier 1 | `fa69d085` | `7386579a5e9d5eb63c51978eb44283851b44b44d071ac8102f7e5acd9d6671f3` | DX12 |
| Supervisor settling | 2026-10-20 / 2026-10-23 | `c416de4f…` (DX12), `90c0ecc0…` (Vulkan) | DX12, Vulkan |
| Preview settling | 2026-10-19 to 2026-10-23 | `ee810a0e…`, `c416de4f…`, `90c0ecc0…`, `694332a5…` | DX12, Vulkan, CPU |
| Second full local gate | `58f7260b` | `4c5788b0f5885198be92222a75460a01206e96d16a7f2792c733b2e27d9eb62c` (ReleaseFast) | DX12 and Vulkan selftest slices passed |
| Capability manifest | `ba0fa817` | `bafbd3027d182ef0b7bd169003c543064613147fa8f5fd14f159194c6d517b16` (ReleaseFast) | — |

Hardware and driver, from both pilot reports' `run` block: `AMD Radeon(TM) Graphics | NVIDIA GeForce RTX 4090`, driver `32.0.11024.2 | 32.0.16.1714`. On 2026-11-08 the NVIDIA driver is still `32.0.16.1714`; the AMD integrated GPU's is `32.0.21042.62`. Painter `12.2.0+js-api.1.1.20`. G2 has no gate commit yet; it will be the commit that closes §3.6.

## 8. Phase 2 tasks (roadmap rule 3)

Checked 2026-11-08 on `a0e07449`: `docs/task-index.md` names 18 Phase 2 tasks. 17 are archived under `.rulebook/archive/` with no unchecked item: 14 on 2026-10-20 (`909457ca`, `bb2745dd`), `phase2.2_recipe-and-diagnostics` and `phase2.9_pilot-belt` on 2026-11-03, `phase2.10_pilot-tunic-recovery` on 2026-11-05. The only `phase2.*` task under `.rulebook/tasks/` is this gate.

## 9. Render parity is not part of G2

G2 makes no render-parity claim and cannot satisfy G5's render requirements. The `painter_viewport` captures of §3.3 are cited only as evidence that captures are window-independent. They are never parity evidence (manifest entry `uzpainter.render.capture`; owner Q2). Render parity is Tier 3, through `phase3.7_path-tracer` and gate G5.

## 10. Durations (owner Q14, roadmap rule 6)

Phases 3–5 revised on 2026-11-08 in `docs/roadmap.md`, "Schedule checkpoint: gate G2". Measured facts and Hypotheses are marked there.
