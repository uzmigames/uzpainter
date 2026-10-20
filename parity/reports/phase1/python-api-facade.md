# P1-PYAPI gate: `phase1.24_python-api-facade`

`phase1.24_python-api-facade` is the parent and acceptance task of P1-PYAPI (`docs/dag.md`; `docs/architecture/10-python-api.md`). Its five children are archived on main: phase1.19 (native module), phase1.20 (facade), phase1.21 (dispatcher and lifecycle), phase1.22 (CLI and capabilities) and phase1.23 (pipeline adapter). Their local run reports are `pyapi-native-module.md`, `pyapi-facade.md`, `pyapi-dispatcher-lifecycle.md`, `pyapi-cli-capabilities.md` and `pyapi-pipeline-adapter.md` in this folder.

Under decision 028, this report is the local-run evidence for the G1 gate record. The run was on 2026-10-12, branch `wt/phase1.24-api-parent` from main `8dc3c96`, envelope `painter-12.1.5_js-api.1.1.20`. The decisions are 115, 116 and 117.

**Result.** The evidence is recorded below. The P1-PYAPI gate is **open** (§5). Item 1.1 is closed: its three prerequisites are archived. Item 3.1 is closed: all 36 current traced replays passed on one build (section 4.2). The Dota 2 user-channel label policy remains question q1, decision 299, section 3. Decision 117 gave every other output outside the supported scope an owning checklist item. The code changes of this task are ready for merge review apart from task acceptance.

## 1. Integration added by this task

| Change | Where | Decision |
|---|---|---|
| The native inserts give Painter's effective defaults: Height `LinearDodge` and Normal `NormalMapDetail` on new content-stack fills, fill effects and groups; BaseColor 0.8 and Height 0 sources on a new fill; "Levels - Base color" and "Compare mask". The facade no longer re-applies them. | `src/python/bind_layerstack.cpp`, `stack_sync.{h,cpp}`, `python/uzpainter_facade/nodes.py` | 115 §1 |
| The native `sync_stack` builds the document `painter_layer_stack.py sync` builds through the facade. It used to blend Height `Normal` on the wand's height layers. | `src/python/stack_sync.cpp` | 115 §2 |
| A user channel takes a uniform colour as given. Before, the facade decoded an sRGB colour on every channel; BaseColor still decodes. | `python/uzpainter_facade/colour.py`, `nodes.py` | 115 §3 |
| The native replay of `fill-layer-readback` goes through UzPainter's own operations: `Transaction`, name addressing, `Stack.uid`, and `export.plan` / `start` / `Job.wait` with the Height map compared. | `tests/python/test_pyapi_tier0.py` | 115 §4 |
| A project records its template. `Settings(template=…)`, `project.templates()` and `project.template()` exist, export and `reload_mesh` read the recorded template, and the facade maps `create(template_file_path=…)` by the shipped file name. | `src/uzp_core`, `src/python`, `src/export/project_export.cpp`, `src/evaluator/templates.*`, `assets/templates` (5 `default_resolution`), `python/uzpainter_facade/project.py` | 116 |
| Each export job records its own sources. The Codex audit found that the adapter rebased every receipt on the project open at the end of the run, so it named the wrong project after a later switch, close or change of directory. Now:<br>• the job result carries `project_path` (absolute, resolved when `open` or `save_as` named the file) and `mesh_path`;<br>• `mesh_path` is the exported revision's own `MeshReference.source`, the absolute path that the last create or `reload_mesh` imported from, persisted in the manifest as the optional `mesh.source`;<br>• a project written before `mesh.source` existed has none, and its manifest is null with the reason;<br>• the adapter rebases each receipt on its own job's sources. | `src/uzp_core/types/project.h`, `manifest/manifest.cpp`, `schema/manifest.schema.json`, `src/mesh/mesh_import.cpp`, `src/python/bind_export.cpp`, `session.{h,cpp}`, `bind_project.cpp`, `adapters/assets3d/runner.py` | coordinator audit items |
| Capability manifest: the trace of 26 compared replays, the new symbols, and the `srgb8-material-channels` release gap of `export_project_textures` in both packages (owner phase1.25_pilot-wand item 2.6). | `tools/capabilities/*.json`, `tests/python/test_capability_conformance.py` | 112, 116 §5 |

## 2. Scope of the acceptance

- **Pipeline scripts (item 3.2)**, wand v1 inputs, pins from the R9 request manifest:
  - `painter_create.py` and `painter_layer_stack.py sync` return their JSON results.
  - `painter_export.py` runs its pinned bytes. The script saves the project, then the export engine refuses the 16-bit sRGB8 BaseColor with `NotYetSupported`, naming R-090, before writing any map file.
  - This task makes no claim about the wand's exported maps. The PNG 16 export of sRGB8 material channels is phase1.25_pilot-wand item 2.6. The five-map export and its parity with Painter are phase1.25 items 3.1 and 4.1 (decision 116 §5).
  - The capability manifest lists that export as a `release-gap` in both packages, owned by phase1.25 item 2.6. The conformance test calls it and requires `NotYetSupported` naming R-090, with the revision unchanged.
- **Tier 0 (item 3.1).** Every output in the supported scope is compared exactly with the golden, both recordings. The outputs outside it are listed in §3.

## 3. Outputs outside the supported scope, with their owners

| Outputs | Kind | Owner |
|---|---|---|
| Content-stack fill effects and their steps (`set-source-none-multichannel` s5…, `insert-positions` s5, s9, s12, s18, s23…) | Refused: `NotYetSupported` before any change (decision 081) | phase3.2_proc-filter-families |
| Mask-stack levels effects (`mask-stack` s13…, `insert-positions` s7, s26) | Refused (decision 081) | phase4.2_remaining-nodes |
| Compare masks (`insert-positions` s8, s29) | Refused (decision 081) | phase4.1_nodes-mask-effects items 2.1, 3.1 |
| `mask-stack` exported `uzp_plane/basecolor` | Not compared: Painter's mask includes the refused levels effect s13/s14, so the masked BaseColor differs (decision 081). Other BaseColor exports formerly listed here are now compared by these replays. | phase4.2_remaining-nodes |
| A uid's value (`phase1-delete-node` s17, `phase1-resource-update` s14-s15) | Normalisation: Painter's own allocation. The identity outputs compare what a uid resolves to. | — |
| Resource contexts `project<N>` | Normalisation up to the session offset (decision 107 §4) | — |
| `phase1-execute-when-not-busy` s9-s10 | Painter's two recordings differ from each other | the recording (decision 109) |
| **Known divergences that return a value.** Each test requires them to still differ. | | |
| Painter's empty default paint layer "Layer 1" | Divergence: UzPainter creates no such layer. The structure readbacks are compared without it after asserting it is exactly that empty layer. | phase4.1_nodes-paint-layers item 2.8 |
| `phase1-reload-resources` recording 2 s9, s12: Painter reports reloads of bytes the project already holds | Divergence (decision 110 §6) | phase5.2_parity-report-tiers item 2.10 (decision 117): after recording 1 is exact, explained by a recording that settles it, or entered in `parity/exceptions.json` as a decision-032 r2 divergence. Named first by decision 110 §6 and phase1.21 item 2.8 (archived). |
| The channel labels of Dota 2's User0-User3 (`project-templates`) | Deliberate non-pixel metadata difference: they read "", Painter's text is not shipped (decision 116 §4). No texture changes: texture sets, resolution, channels and formats of all 26 templates are exact. | Question q1 in the task's `.metadata.json`, answered 2026-10-19 with option (a), **decision 299**: UzPainter keeps its generic or empty labels and never copies Painter's label text. Codex and Claude chose it under the owner's delegation of that day. It is not a licence review, and not an owner approval to copy Adobe text. The test still requires the labels to differ: `python -m pytest -q tests/python/test_pyapi_facade_tier0.py -k project_templates`, exit 0, 1 passed (main ed4627c, 2026-10-19). |
| BaseColor exports of `phase1-srgb-uniform-decode-ocio-part1..4` (`uzp_plane/basecolor`) | Not compared in this replay: the native project is Legacy, since no creation path yields an OCIO project (decision 202, Consequences) | The OCIO evaluation and export are compared by decision 190's `test_ocio_encode_equals_painter_files` (`tests/export/test_export_encoders.py`) |
| P20-A's Normal map (`phase1-fill-channel-defaults` `uzp_plane/normal`) | Refused: the grey bitmap on Normal (`evaluator:unsupported_source`, decision 249) | phase1.15_compositor-colour-fits (item 2.9's open note): the recording decision 249 lists settles it |

The refused-node exclusions also cover dependent identity/default readbacks: `set-source-none-multichannel` identity/defaults s5 and `identity/reopen`; `mask-stack` identity/defaults s13 and `identity/reopen`; `insert-positions` identity/defaults s5, s9, s12 (content fill), s7 (mask levels), s8 (compare mask), plus s24/root-list and `identity/reopen`. The content-fill dependent steps also include `insert-positions` s21, s25 and s28. Each follows the same owner as its refused node. Lifecycle event comparisons remove asynchronous `during_step` markers from both sides; `phase1-execute-when-not-busy` compares only through s8 because s9/s10 race in Painter itself. This validation changed no comparison rule or capability status.

Closed by phase1.15_compositor-colour-fits item 2.1 (decision 214, 2026-10-13): `phase1-reload-resources` recording 1 s9 and s12 (a grey bitmap on BaseColor now binds in sRGB, P20-A) and the 70/255 decode of `export-ocio-encode-legacy` (the Legacy decode fitted from P20-B) are compared exactly; their rows are removed.

## 4. Local run on the owner's machine

Each line is one pytest command, run directly with no pipe, with `UZP_UPDATE_TIER0_TRACE` unset unless noted. The exit status is pytest's own.

| Command | Result |
|---|---|
| `python -m pytest -q tests/python/test_pyapi_facade.py` | exit 0, 9 passed |
| `python -m pytest -q tests/python/test_pyapi_native.py` | exit 0, 16 passed |
| `python -m pytest -q tests/python/test_pyapi_dispatcher.py` | exit 0, 10 passed |
| `python -m pytest -q tests/python/test_pyapi_tier0.py tests/python/test_pyapi_lifecycle_tier0.py tests/python/test_pyapi_facade_tier0.py --deselect tests/python/test_pyapi_facade_tier0.py::test_uniform_colour_ramps_export_as_painter` | exit 0, 23 passed, 3 deselected (the ramps, row below) |
| `UZP_UPDATE_TIER0_TRACE=1 python -m pytest -q tests/python/test_pyapi_facade_tier0.py::test_uniform_colour_ramps_export_as_painter` | 3 passed in 979 s. All 192 exported maps and all 216 readbacks of each of `colour-ramps-srgb`, `-working` and `-raw` are exact, both recordings. A first run, with the facade decoding sRGB on user channels, failed 384 readbacks of `-srgb`: that measurement set decision 115 §3. |
| `python -m pytest -q tests/python/test_pyapi_cli.py tests/python/test_capability_conformance.py tests/capabilities` | 40 passed, 1 failed: the new `srgb8-material-channels` recipe lacked `dithering`, so it raised `ValueError` before the gap. The recipe was fixed (RGB channels, `dithering` false, `paddingAlgorithm` passthrough). The node was re-run alone (§4.1). |
| `python -m pytest -q tests/adapters` | exit 0, 40 passed |

The traced Tier 0 replays number 26. New ones: `native/fill-layer-readback` with its Height map, `facade/colour-ramps-*` (3) and `facade/project-templates`, where all 26 shipped templates are exact as created and after save and reopen (texture sets, resolution, channels, formats).

The capability manifest:

| Package | supported | pending-evidence | release-gap | desktop-only-omitted |
|---|---|---|---|---|
| `uzpainter` | 220 | 290 | 69 | — |
| Painter inventory | 262 | 295 | 294 | 15 |

Of the 63 UzPainter-only `pending-evidence` entries, 9 are now `supported`. The rest name gate G5 (phase5.6_gate-g5) as owner, with the reason (decision 115 §4).

### 4.1 After the provenance and recipe fixes

Build at 07:38, `zig build painter pyapi-tests --prefix <scratch>/p124/build`, exit 0. The native test targets `uzp-core-tests`, `uzp-core-transaction-tests`, `uzp-store-tests`, `uzp-store-inspect-tests` and `export-tests` also built, exit 0.

| Command | Result |
|---|---|
| `python -m pytest -q tests/python/test_capability_conformance.py::test_release_gaps_raise_not_yet_supported_before_mutation` (on the 07:29 build) | exit 0, 1 passed |
| `python -m pytest -q tests/uzp_core` | exit 0, 48 passed |
| `python -m pytest -q tests/python/test_pyapi_native.py` | exit 0, 16 passed |
| `python -m pytest -q tests/adapters` | exit 0, 44 passed |

The adapter regressions export a project, then each of the following, and require the manifest to name the export's own project and mesh:
- save it under another name;
- close it;
- create from a relative mesh path, save under a relative path and leave from another directory;
- reopen from another directory;
- reload identical mesh bytes from another folder;
- that reload followed by a revert to the revision before it.

### 4.2 Full current Tier 0 run, 2026-10-19 local time

One CPU build, commit `3b7c70afe9dc1ce39f4311a0888293896fee79f4`, isolated worktree `.claude/worktrees/a36`; runner SHA-256 `226b9a3ad73488a7179897a13ca5150cb60c475605c087694c399d1b7927fc33`. Run `tmp/scratch/api36/20261019T234301Z` started 2026-10-19 23:43:01 UTC and finished 2026-10-20 00:02:37.496119 UTC (2026-10-19 locally).

`F:\Python313\python.exe -m pytest -q tests/python/test_pyapi_tier0.py tests/python/test_pyapi_lifecycle_tier0.py tests/python/test_pyapi_facade_tier0.py` with isolated basetemp and JUnit paths recorded in `run.json`: **exit 0, 36 passed in 1173.02 s**, no skips, failures or errors. JUnit suite time is 1172.934 s. No test deselected. The three modules cover every current `tier0-trace.json` ID exactly once: 2 native, 8 lifecycle/events, 26 facade. The trace and all three test files match the run worktree byte-for-byte. `tmp/scratch/closure/api36-evidence.json` records all 36 replay-to-test mappings and source/JUnit SHA-256 hashes; `pytest.log`, `junit.xml` and `run.json` preserve the raw evidence.

The result closes item 3.1 only within section 3's named comparison scope. It does not accept P22-B recordings, admission or compared replays, change capability statuses, or close the P1-PYAPI gate. Section 4's older 26-replay results remain historical evidence.

## 5. Open

- **Item 1.1: closed.** `phase1.3_document-model`, `phase1.18_export-engine` and `phase1.8_project-store` are archived (`.rulebook/archive/2026-10-10-phase1.3_document-model`, `2026-10-12-phase1.18_export-engine`, `2026-10-13-phase1.8_project-store`).
- **Item 3.1: closed.** Full current 36-replay run passed on one build; section 4.2 records execution identity, results and coverage. Question q1 remains answered by decision 299; section 3 records the comparison exclusions.
- **Item 3.4: authoring closed.** Decisions 295-297 supply 18 requests: 8/80 requested symbols plus 4 routed (295), 6/76 plus 10 routed (296), and 4/64 plus 19 routed (297). Total: 220 requested and 33 routed, 253 symbols. Decision 189's 257 reconciles as +1 ExportStatus.Error, -3 colormanagement symbols already supported, -2 display symbols covered by decision 188. The three `test_api_probes_p22b_*` modules check the symbol-to-request/route coverage, explicit vocabulary and fake recordings. Existing execution evidence: decision 295 module 17 passed; decision 296 module included in the 55-passed recorder batch; decision 297 had 33 passed and one fake-wrapper failure, then that node passed after correction (`e609803`). Source records and exact results are preserved in `tmp/scratch/closure/p22b-authoring-evidence.json` and `p22b-host-validation.json`. These are authoring checks, not Painter evidence. Item 4.1 stays open for P22-B recordings, admission and compared replays; routed symbols retain their named owners and all pending-evidence statuses remain unchanged.
- **Recordings named** (owner action): P23-A, `save_as` onto an existing `.spp` (decision 113); P24-A, a template path that is missing or is not a template (decision 116); P22-B, one api-probe calling every Painter symbol marked `pending-evidence` (decision 112).
- **The adapter's session carry: fixed (decision 118; commits 1c09894, fbfbf97, 254d96e).** The runner stored `project.file_path()`, as given, as the next call's project. A script that changed directory and then saved under a relative path carried a path that the next process resolved in the client's directory. The call failed, or another project of the same name was reopened (Codex audit, P2).
  - The fix: the runner now carries `uzpainter.project.absolute_file_path()`, the path `open` or `save_as` resolved when it ran, and refuses a session file that names a relative path.
  - The host tests pass (`tests/adapters/assets3d/test_adapter_units.py`).
  - Verified natively on 2026-10-12: `test_a_project_saved_under_a_relative_path_is_reopened_where_it_was_saved` (`tests/adapters/assets3d/test_pipeline_adapter.py`) passed at fbfbf97, on `UzPainter.exe` SHA-256 `f7cf93233b44faf00e2be309691ba3fb44238e2551d5c08ceeb14cde01bfdcff`. Its first call changes directory and saves under a relative path. The second call, run from a directory that holds a same-named copy of another project, reopens the saved project: same UUID, same absolute path.
  - A bundle directory (Codex audit): it opens as the `.uzp` it is imported into, but the carry named the directory, and reopening it fails because the `.uzp` exists. `project_source`, which `absolute_file_path()` and the export jobs read, is now the store's own file, resolved when `open` or `save_as` ran. Host test `test_a_project_opened_from_a_bundle_is_carried_as_its_store_file`; native regression `test_a_project_opened_from_a_bundle_directory_is_reopened_from_its_store_file`. Both native regressions passed at 254d96e on 2026-10-12, on `UzPainter.exe` SHA-256 `ddd14fe0f9ed5af1e647797c3af9b63b90427890e194e7931e39223da592aa23`.

## 6. Reproduce

```
zig build painter pyapi-tests --prefix <prefix>
python -m pytest -q tests/python/test_pyapi_native.py tests/python/test_pyapi_facade.py
python -m pytest -q tests/python/test_pyapi_tier0.py tests/python/test_pyapi_lifecycle_tier0.py tests/python/test_pyapi_facade_tier0.py
python -m pytest -q tests/adapters
```

## 7. Compared replays of the ten observed API-probe goldens (item 4.1), 2026-10-20

An audit found ten API-probe goldens that were admitted (decisions 180, 198 and 205) but had no compared replay: P21-A to P21-G, R-095 P7, R10 engine computations and P23-A.

Each one is now replayed through the facade with the recorder's own Painter-side code, step for step as `record_api_probe` drives Painter, including the events and states it observes after every step. The helper is `tests/python/observed_replay.py`. The queued events are delivered at the recorder's remote-call boundary.

Every output of both recordings is compared field by field with the golden, read from the private store at run time. An excluded output must be recorded in the golden and must still differ. No Painter value is copied into the repository.

The behaviours these goldens settled are in decision 319, which supersedes parts of decisions 105, 109 and 110. The facade was fixed to match them.

### 7.1 Runs (separate identities)

Every run used the same runner, `uzp-pyapi-tests.exe` SHA-256 `f8c5a64b5b255aef66808305d87a3bdb589e8fd605481e173047a67d5c7af5b1`, from one build: `zig build pyapi-tests uzp-store-save-tests -j2`, exit 0, on CPU. The pytest fixtures' own builds install the same binary from the cache. The logs are under `tmp/scratch/api-replays/`.

| Run | What | Result |
|---|---|---|
| Combined first run (`combined/`) | Claude's 5 replays, Codex's 3 files, dispatcher, lifecycle, conformance, `tests/store/test_store_save.py` | The failures led to the fixes and exclusions below. Store save tests: 13 passed. Dispatcher: 11 passed. |
| 39-test batch, before the host fix (`trace-regen/pytest.log`) | `test_pyapi_facade_tier0.py` (26), `test_pyapi_lifecycle_tier0.py` (8) and `test_pyapi_observed_tier0.py` (5), one pytest session, `UZP_UPDATE_TIER0_TRACE=1` | exit 0, 39 passed in 967.8 s |
| Native 2 (`trace-regen/native.log`) | `test_pyapi_tier0.py`: fill-layer-readback and textureset-project-readback, by node id, `UZP_UPDATE_TIER0_TRACE=1` | exit 0, 2 passed in 9.3 s |
| Codex 5 (`codex-final/evidence.json`) | P21-F, P21-G, R10, P23-A and R-095 P7: the original test functions run directly on the existing binary, not through pytest | 5/5 passed, exit 0 |
| Final-async 30 (`final-async/evidence.json`) | After Codex's fix that delivers queued events before the edition state changes: dispatcher (12), lifecycle (8) and the 10 new replays. The original functions ran on the existing binary with the committed Python sources as an overlay. | 30/30 passed, exit 0, 112.5 s |
| Conformance and manifest (`trace-regen/conformance.log`, `capabilities-tests.log`) | `test_capability_conformance.py` and `tests/capabilities`, on the consolidated trace | exit 0: 5 passed and 44 passed |

### 7.2 Results by golden (exact-behaviour verdicts)

"Exact" means exact apart from the named exclusions, in both recordings.

| Golden | Verdict | Exclusions, with owners |
|---|---|---|
| `phase1-create-mesh-maps` (P21-A) | exact | none |
| `phase1-create-default-paths` (P21-B) | exact apart from one open seam | `s3/get_default_export_path` returns UzPainter's own absolute export folder, `<Documents>/UzPainter/export` (decision 320, commit f819cc0). Painter returns its host's export folder, so s3 is recorded as an explicit host difference, not literal parity. The symbol is `pending-evidence`, and the excluded output promotes no symbol. |
| `phase1-texture-throttling` (P21-C) | exact | none |
| `phase1-shelves` (P21-D) | exact apart from the host environment | `s4/all`, `s5/application_shelf`, `s6/user_shelf`: Painter's installed and user shelves are Adobe content that UzPainter never ships (decision 006). |
| `phase1-layer-stack-events` (P21-E) | exact apart from refusals and one unstable output | Refused before any change, together with each step's event:<br>• s14 `insert_paint` (phase4.1_nodes-paint-layers)<br>• s16 and s17, compare mask and colour selection (phase4.1_nodes-mask-effects)<br>• s18 anchor point (phase4.1_nodes-instances-anchors)<br>Also excluded:<br>• r2 `identity/reopen`, which lists those nodes<br>• `s30/set_parameters`: Painter's TypeError text holds an object address that differs between its two recordings (decision 205) |
| `phase1-create-open-timing` (P21-F) | exact | the raw `thread_polls`, which are wall-clock samples (decision 198) |
| `phase1-close-without-saving` (P21-G) | exact | the lock-file suffix rule (decision 319 §9a) |
| `phase1-export-preset-search` (R-095 P7) | exact apart from refusals | `s3`, `s4` `search`: a release gap (decision 113, phase3.1_proc-backend-seam item 2.4) |
| `phase1-engine-computations` (R10) | exact | the export-publication metadata rule (decision 319 §9b; decisions 097, 105): the plan, receipt and published copies are checked, and only the declared housekeeping files are left out |
| `phase1-save-as-existing` (P23-A) | exact | the lock-file suffix rule (decision 319 §9a) |

### 7.3 Trace verdicts (decision 112)

- **The 46 entries.** `tools/capabilities/tier0-trace.json` now holds 46 replays: the 36 historical ones plus the 10 new.
  - The 26 facade and 2 native entries come from the 39-test batch and the native run.
  - The 8 lifecycle and 10 new entries come from the final-async records. For the 13 replays both runs traced, their symbol sets are identical.
- **`save_as`.**
  - Every facade and lifecycle entry dropped `uzpainter.project.save_as`. The facade's `save_as` now uses the private `_save_as_replace`, so only the native replays credit the native `save_as`.
  - The public `substance_painter.project.save_as` is credited by the facade replays.
- **Manifest.** The manifest follows the trace:
  - 64 symbols that the exact replays exercised become `supported`;
  - 344 entries' `tier_evidence` is updated;
  - none is demoted;
  - refused calls and excluded outputs credit nothing.
- **Limitation.** The rich per-output trace records of final-async (`by_output`, exclusions, differences) were overwritten by the symbol records, because of a helper naming bug fixed in `cc635174`. Only `{replay, golden, symbols}` remain. The evidence of that run is the binary and source SHA-256s in `final-async/evidence.json`.

### 7.4 Open

At the end of this run, item 4.1 remained open for P22-B recording/admission/replays and the
P21-B default-path difference. Section 9 records the subsequent admission and compared fixes.

## 8. `get_default_export_path` as a UzPainter host policy (decision 320), 2026-10-20

Section 7's runner (`f8c5a64b…`) predates this change; this section's evidence is separate.

- **Code:** commit f819cc0f, on parent 75bf5c34. The private `uzpainter.export._default_export_path` returns `<Documents>/UzPainter/export` from `SHGetKnownFolderPath(FOLDERID_Documents, KF_FLAG_DONT_VERIFY)`. It does no existence check, never creates the folder and has no fallback.
- **Run:** `tests/python/test_default_export_path.py` plus `test_observed_probe_equals_painter[phase1-create-default-paths]`, one pytest session, exit 0, 2 passed, 0 skipped.
  - Runner SHA-256: `226a77fd57d70e00b7f7e6088df2eaee42e97b66f5efd1937dd4b25987806119`.
  - Evidence: `tmp/scratch/default-export/validation-run3/{evidence.json,junit.xml,pytest.log}`, including the source hashes of the five changed files.
  - Earlier attempts (run1 with 2 skips, run2 with no collection) are not evidence.
- **Verdict:** P21-B s3 returns a valid absolute path and is recorded as an explicit host difference from Painter's path. It is not literal parity. The symbol is `pending-evidence` and is not `supported`.

## 9. P22-B admission and compared corrections, 2026-10-20

Commit `8f9eac52` admits all 18 P22-B recordings, together with ten rendering diagnostics.
The public manifests contain hashes only; oracle data remains in the private store. The Tier 0
stability report now covers all 269 admitted Tier 0 goldens. Admission checks: 502 passed before
the report completed; the sole failing coverage check passed after regeneration, in a 35-test
batch that also verified script-pilot authoring. No recording is still required for P22-B.

The first strict replay exposed real facade differences. Corrections now have these compared
results, with no new exclusions:

| Golden | Result in both recordings |
|---|---|
| `p22b-project-mesh-unit-scale` | exact; scene bounds use stored mesh geometry before the unit-scale setting |
| `p22b-project-tangent-per-fragment` | exact |
| `p22b-project-tangent-per-vertex` | exact, including Metadata setter return and persisted values |
| `p22b-project-workflow-default` | exact |
| `p22b-textureset-channels` | exact, including canonical channel aliases and error messages |
| `p22b-textureset-texture-set` | exact, including description persistence and property forms |
| `p22b-textureset-user-channels` | exact, including label clearing |
| `p22b-export-error-status` | exact, including raised ValueError and event message/status/order |
| `phase1-create-default-paths` (P21-B) | exact, including literal default-path equality; s3 exclusion removed |

The replay harness now passes its root to `probe_reset`, as the recorder does, and stages the
same authored plugin modules through `probes.plugin_root`. These fixes restore the recorded
instructions; they do not normalize differences. Native export errors remain the chained cause
of the facade's recorded ValueError. The default-path amendment in decision 320 changes only
the facade's returned string; the native destination policy and explicit-export-path requirement
remain unchanged.

Validation identities are separate:

- `tmp/scratch/closure/api-integrated-junit.xml`: 10 passed, no skips; focused contracts plus
  P21-B and export-error replays. Runner SHA-256
  `b881b10a0f41212b998e83126239447e146fad610fdb20573943ce5d1b77c9fd`.
- `tmp/scratch/closure/p22b-final-junit.xml`: 31 passed, no skips; seven permanent Project/
  TextureSet replays plus facade and dispatcher regressions. Runner SHA-256
  `d6f2b025a85feccdbc47ffd366d222c52327770da6ef710438f034df70c74be6`.
- `tmp/scratch/closure/project-final-junit.xml`: 2 passed after correcting BoundingBox's
  public constructor order and list-valued fields; stored geometry survives source changes
  and save/reopen.
- Installed Python hashes accompany these runs in the corresponding `*-build-identity.json`;
  traces are in `integrated-api-traces/` and `p22b-final-traces/`. No full-suite claim is made.

Item 4.1 remains open for the four HOST and six Layer/Color/Levels compared replays and final
trace/capability reconciliation. Successful comparisons do not by themselves promote inventory
entries. The BoundingBox radius evidence is the recorded plane; no separate arbitrary-3D-radius
qualification is claimed. Wand export parity remains owned by `phase1.25_pilot-wand`.

## 10. Trace and capability reconciliation of the exact P22-B replays, 2026-10-20

Thirteen exact P22-B and P21-B replays now carry Tier 0 trace evidence:

- the seven Project/TextureSet replays;
- `p22b-export-error-status`;
- P21-B `phase1-create-default-paths`;
- the four host replays (application, events, plugins and resources, commit `96ba2261`).

### 10.1 Runs (separate identities)

| Run | Runner `uzp-pyapi-tests.exe` SHA-256 | Result |
|---|---|---|
| Codex, `p22b-final-junit.xml` (seven replays) | `d6f2b025…74be6` | 31 passed (section 9) |
| Codex, `api-integrated-junit.xml` (P21-B, export error) | `b881b10a…c77c9fd` | 10 passed (section 9) |
| Codex, host validation (`tmp/scratch/p22b-host/validate.json`) | `8cd17d90…caf98`, with a source overlay | four host replays exact |
| First regeneration, on `4f95a1b3` (`tmp/scratch/trace-p22b/replays.log`) | `993b42a4…f9324d34` | exit 0, 9 passed in 18.7 s |
| Final regeneration, on `96ba2261` (`tmp/scratch/trace-p22b/replays2.log`) | `be0e2fa2…ca19054c` | exit 0, 16 passed in 60.4 s |

- **Final run.** It covers the 13 replays and three older entries that had drifted:
  `facade/phase1-resource-update`, `facade-events/phase1-resource-update` and
  `facade-events/phase1-reload-resources`, with `UZP_UPDATE_TIER0_TRACE=1`.
- **Build.** The final run's build is `zig build pyapi-tests -j4` from the branch rebased on
  `96ba2261`, exit 0, on CPU. Its installed Python sources are those of the tree
  (`replay2-build-identity.json`). For the nine replays both regenerations traced, the symbol
  sets are identical.
- **Codex's builds differ from the commits.** The P22-B builds installed `baking.py` and
  `properties.py` from before `8fa4f517`. The `b881b10a` build also installed an intermediate
  facade `project.py` (`67be7e8f…`), and that binary no longer exists.
- **Codex's Project/TextureSet trace records were not merged.** They were written by a
  `capability_trace.py` older than `4c931156`. That version did not see the facade's
  `ChannelType` as an enum, so it took the members for data fields. Every scan of one member
  then credited all 85: 78 extra members in seven records, 43 in the channels record and 54 in
  the user-channels record. Apart from those members, their symbols and per-output keys equal
  the regenerated records.
- **The host records match Codex's.** On their Painter symbols, the four regenerated host records
  equal `symbols-validate.json`. They also list the native `uzpainter` symbols.

### 10.2 Trace and manifest

- **Trace.** `tools/capabilities/tier0-trace.json` now holds 59 replays: 12 are new and 4 were
  regenerated.
  - P21-B adds `get_default_export_path` and the facade aliases `ChannelType.Metallic` and
    `Roughness`.
  - The three regenerated older entries add the same two aliases and lose
    `project.Metadata`, `.get` and `.set`, which other replays still exercise.
- **Promotions.** 204 exercised symbols become `supported`. `tier_evidence` follows the trace on
  every other supported entry. Nothing is demoted.
  - Project, TextureSet and export: 142 symbols, 84 Painter and 58 `uzpainter`. Five of them
    come from `release-gap`: `get_scene_bounding_box` and `BoundingBox` with its `center`,
    `dimensions` and `radius`, which the mesh-unit-scale replay now compares.
  - Host: 62 symbols, among them `logging`, `ui`, `js.evaluate` (s21 to s25),
    `substance_painter_plugins`, `display.set_environment_resource` and the resource filters and
    reloads.
- **Nothing excluded is credited.** Excluded outputs, refusals and host differences credit
  nothing:
  - the version outputs s3, s4 and s20 (decision 330);
  - the excluded `texture_states` outputs and `TextureStateEventAction` (decision 332);
  - `event.Event` (decision 297 §3.4);
  - `ReloadedResourceError` and `Usage.COLOR_LUT`.
- **`get_default_export_path`.** Under decision 320's amendment, s3 is compared literally, with no
  exclusion, so it is no longer a host difference.
- **Notes.** 22 entries stay `pending-evidence` with corrected notes, because these replays reach
  them without a credit:
  - `Resolution.width` and `height`, and five native `uzpainter.project.Settings` fields: they
    are pybind11 properties, which the trace does not credit;
  - the 13 native `uzpainter.textureset.ChannelType` legacy aliases: the facade passes only the
    canonical member.

### 10.3 Open in item 4.1 (not ticked)

- **Layer side.** The five layer probes of agent p22b-layer pass, but they are not on main yet.
  After that merge, every `check_trace` replay is regenerated: the layer changes shift the
  create/open replays and the group inserts.
- **Seams (decisions 330 and 332).**
  - `TextureStateEvent` emission.
  - The application version, which UzPainter reports as its own.
- **Trace drift in the older entries.** The facade `ChannelType` of `4f95a1b3` puts each legacy
  alias on its canonical member. 38 older entries still credit `BaseMetalness` or
  `SpecularRoughness` without `Metallic` or `Roughness`. Their next trace check will report the
  aliases as added. They are regenerated in the pass after the layer merge. No name is added by
  hand.
- **Conformance.** `test_release_gaps_raise_not_yet_supported_before_mutation` fails on
  `export_project_textures @ l8-material-channel-png-unrecorded`. Since `4f95a1b3`, the facade
  re-raises the native `NotYetSupported` as `ValueError("Error during the export (see logs).")`,
  so the refusal is no longer visible as one. The fault is in the facade, not in this change.

## 11. Final trace reconciliation on one build, 2026-10-20

Every `check_trace` and `check_observed_trace` replay was regenerated in one pytest session on one build, using the method of `68a4137b` and `abd94980`. 64 of the 65 replays passed and their traces are consolidated. One replay fails on behaviour, so **item 4.1 stays open** (§11.6).

### 11.1 Run identities

| Run | Identity | Result |
|---|---|---|
| Build | `zig build pyapi-tests -j2` from commit `6518f49eaaf8108d0f30c4ba55941e7d0276647a` (worktree `wt/trace-final`), with a fresh `ZIG_GLOBAL_CACHE_DIR` under `tmp/scratch/trace-final/`; CPU only | exit 0, 1 min 56 s (`build.log`) |
| Runner | `uzp-pyapi-tests.exe` SHA-256 `6f63d36ea1266f9bded4f2f39e4c58625de8a32efc3153694862184985fec55f`. All 51 installed Python files equal the commit's `python/` sources (`replay-build-identity.json`) | — |
| Replays | One session on that binary (`run_existing.py`, no fixture rebuild), `UZP_UPDATE_TIER0_TRACE=1` and `UZP_OBSERVED_TRACE_DIR=traces/`, from 15:46:54Z to 16:08:31Z | 65 tests: 64 passed, 1 failed, exit 1, 1295.65 s (`replays.log`, `replays-junit.xml`) |
| Conformance | `tests/python/test_capability_conformance.py`, run once on the same binary | exit 1: 4 passed, 1 failed (§11.5; `conformance.log`) |
| Manifest | `tests/capabilities`, run once | exit 0, 44 passed (`capabilities-tests.log`) |

The logs are in `tmp/scratch/trace-final/`. The session covered:
- 2 native replays;
- `facade/baking-defaults`;
- 26 facade replays;
- 8 lifecycle replays;
- 10 observed replays (P21-A to P21-G, R-095 P7, R10 and P23-A);
- `p22b-export-error-status`;
- 7 P22-B Project/TextureSet replays;
- 4 host replays, with decision 332's texture comparison mandatory;
- 5 layer replays;
- the colour replay.

`mask-stack`, `insert-positions`, `fill-layer-readback`, `phase1-resource-update` and `phase1-reload-resources` are among the facade and lifecycle replays.

### 11.2 P22-B verdicts (18 probes)

"Exact" means exact in both recordings apart from the named exclusions.

| Golden | Verdict | Exclusions, with owners |
|---|---|---|
| `p22b-project-mesh-unit-scale` | exact | none |
| `p22b-project-tangent-per-fragment` | exact | none |
| `p22b-project-tangent-per-vertex` | exact | none |
| `p22b-project-workflow-default` | exact | none |
| `p22b-textureset-channels` | **fails on behaviour** (§11.6) | none |
| `p22b-textureset-texture-set` | exact | none |
| `p22b-textureset-user-channels` | exact | none |
| `p22b-export-error-status` | exact | none |
| `p22b-host-application` | exact apart from the host difference | s3 `version`, s4 `version_info`, s20 `evaluate`: decision 330, host difference, no credit |
| `p22b-host-events` | exact, including the texture comparison | none. ADD and REMOVE are exact per step; UPDATE matches as decision 332's s7-s8 (action, channel type) pairs. Cache keys and texture ids are not claimed. |
| `p22b-host-plugins` | exact | none |
| `p22b-host-resources` | exact apart from four outputs | • s5 `import_project_resource`: refused, the COLOR_LUT is pinned to none (decision 038)<br>• s15 `get_environment_resource`: host content, permanent (decisions 006 and 038)<br>• s23 `reload_modified_resources_async`: release gap, shelf resources (phase3.3_procedural-families)<br>• r2 s20 `events`: reload order unproven; **owner phase1.24 item 4.1 itself** |
| `phase1-blending-modes-layer` | exact | none |
| `phase1-blending-modes-mask` | exact | none |
| `phase1-layer-navigation` | exact apart from refusals | Fill effect in a content stack, step 19 and its node's outputs (phase3.2_proc-filter-families, decision 081). Triplanar projection, s60-s63 (phase3.4_smart-projections). Painter's default "Layer 1", s30 and r1 s88 (phase4.1_nodes-paint-layers item 2.8). |
| `phase1-layer-node-kinds` | exact apart from refusals | Paint effect s5 (phase4.1_nodes-paint-layers). Filter and generator effects s6 and s8 (phase3.3_procedural-families, decisions 113 and 324). Instance layer s17 (phase4.1_nodes-instances-anchors). r2 `identity/reopen`, which lists their nodes. |
| `phase1-levels-params` | exact apart from refusals | Levels effect in a mask stack, step 9 and its node's outputs (phase4.2_remaining-nodes, decision 081) |
| `phase1-color-srgb-value` | exact | none |

### 11.3 Observed verdicts (10 probes)

All 10 are exact. Their exclusions and comparison rules are unchanged from §7.2:

| Golden | Exclusions or rule |
|---|---|
| P21-A `phase1-create-mesh-maps` | none |
| P21-B `phase1-create-default-paths` | none (decision 320 amendment) |
| P21-C `phase1-texture-throttling` | none |
| P21-D `phase1-shelves` | s4, s5 and s6: host environment (decision 006) |
| P21-E `phase1-layer-stack-events` | Refusals s14 and s16-s18, each with its events (phase4.1_nodes-paint-layers, nodes-mask-effects and nodes-instances-anchors). r2 `identity/reopen`. s30 `set_parameters`, unstable in Painter (decision 205). |
| P21-F `phase1-create-open-timing` | the raw `thread_polls` (decision 198) |
| P21-G `phase1-close-without-saving` | the lock-file suffix rule (decision 319 §9a) |
| R-095 P7 `phase1-export-preset-search` | s3 and s4 `search`: known divergence (phase3.3_procedural-families, decisions 113, 164 and 324) |
| R10 `phase1-engine-computations` | the export-publication metadata rule (decision 319 §9b) |
| P23-A `phase1-save-as-existing` | the lock-file suffix rule (decision 319 §9a) |

### 11.4 Seams

- **Version, a host difference (decision 330).** UzPainter reports its own version. s3, s4 and s20 of `p22b-host-application` stay excluded and credit nothing.
- **Texture window (decision 332).**
  - UzPainter's observer (`06b182fe`) now emits the pairs Painter emits within s7-s8, and `p22b-host-events` passes with the texture comparison mandatory, so decision 332 §5's condition holds for that golden.
  - Cache keys and texture ids are not claimed.
  - The same observer causes the failure in §11.6.

### 11.5 Trace and manifest

- **Trace.** `tools/capabilities/tier0-trace.json` holds 65 replays.
  - 6 are new: the 5 layer replays and the colour replay.
  - 58 were regenerated, 2 of them (the native replays) with an identical symbol set.
  - `facade/p22b-textureset-channels` is left exactly as `abd94980` recorded it, because it fails here (§11.6). No symbol is promoted from it: every promotion has another exact replay behind it.
- **Promoted (77).** These are exercised only by exact compared outputs, after excluded outputs and refusals are removed (`observed_symbols`, `exercised`):
  - 65 Painter symbols: 50 `layerstack` (BlendingMode members, selection, navigation, collapsed, symmetry, material source, ScopedModification), 13 `levels` and `colormanagement.Color.sRGB` and `.value`;
  - 12 `uzpainter` symbols.
  - The list is in `tmp/scratch/trace-final/promoted.txt`.
- **`tier_evidence`.** It follows the trace on 321 supported entries.
- **Demoted (7), with reasons in their notes.**
  - `uzpainter.layerstack.BlendingMode` and its members `LinearDodge`, `Multiply`, `Normal`, `NormalMapDetail` and `Screen`: since `d83195de` the facade passes its own BlendingMode, and no compared replay exercises the native members.
  - `substance_painter.resource.ShelvesListFilter`: its earlier credit came from s23/states while the excluded s23 reload was still running. The reload now ends before the call returns, so no compared output exercises it.
- **Unchanged.** 1,428 entries keep their status: 784 supported, 305 pending-evidence, 324 release-gap and 15 desktop-only.
- **Held pending (4).** `substance_painter.event.TextureStateEventAction` and its `ADD`, `REMOVE` and `UPDATE`.
  - The trace credits them in 34 replays, but only through the facade's own TextureStateEvent construction (`texture_state.py`).
  - 33 of those probes connect no TextureStateEvent handler, so their dispatches are filtered out and never compared. Only `p22b-host-events` compares them.
  - Because the conformance test requires `tier_evidence` to equal the trace, they cannot be promoted on that one golden alone. Their notes say so and name item 4.1.
  - This is the one conformance failure: `test_supported_entries_equal_the_tier0_trace`, "exercised but not supported", these 4 symbols. Its other two checks hold: nothing is supported without a replay, and no evidence is wrong.
  - It is settled by a trace rule that credits only compared dispatches, or by a decision to accept the facade-internal credit.
- **No credit from excluded material.** Nothing is credited from:
  - excluded outputs or refusals;
  - the version outputs (decision 330);
  - cache keys or texture ids (decision 332);
  - `event.Event`, `ReloadedResourceError` or `Usage.COLOR_LUT`.
- **Credits that only widened `tier_evidence`.** The observer's internal calls widen the `tier_evidence` of entries that were already supported:
  - `uzpainter.textureset.Stack.uid`, `TextureSet.uid` and `Stack.material`;
  - `TextureStateEvent.cache_key_invalidation_throttling_period`.

  None of them is a promotion.
- **`test_release_gaps_raise_not_yet_supported_before_mutation`.** The §10.3 failure no longer occurs: it passes on this build.

### 11.6 Item 4.1: not ticked

Clause by clause:

- **Three pipeline scripts through the adapter.** Holds, on item 3.2's evidence (§2, §4.1).
- **API-probe goldens exact apart from named exclusions with owners.** Does **not** hold:
  1. `tests/python/test_pyapi_p22b_project_textureset_tier0.py::test_p22b_project_textureset_replay[p22b-textureset-channels]` fails on behaviour. Its `close_project` step raises `RuntimeError: texture notification worker failed`, caused by `incomplete native texture snapshot: unsupported texture DAG: 4/BaseDiffuseRoughness`. The source is `src/python/session.cpp`: the observer's snapshot calls `evaluator::BuildDag` on every channel and fails on the BaseDiffuseRoughness channel this probe adds. The log is `tmp/scratch/trace-final/replays.log`. The replay passed exactly at `abd94980`, before the observer existed; Codex owns the fix.
  2. The `p22b-host-resources` r2 s20 `events` exclusion names phase1.24 item 4.1 as its owner. It needs an owner that outlives this task, or a recording that settles the order.
  3. The admitted goldens P22-A `phase1-mesh-map-update` and P22-C `phase1-restored-values` (decision 180) have no compared replay. Both were named by decision 111, and the mesh-map release gap of `update_layer_stack_resource` names phase1.24.
- **Results recorded in `parity/reports/phase1/`.** Holds: this section.

### 11.7 Before archive

The task is not archived, because 4.1 is open. Besides §11.6, the manifest still names this task as the owner of open evidence:
- 126 pending entries still read "Recording P22-B settles it (phase1.24_python-api-facade)", although every P22-B recording is now admitted and replayed;
- 32 entries name item 4.1 itself: the 4 held entries, the 6 demoted BlendingMode entries and the 22 notes of §10.2.

Each needs a reason and an owner that outlives the task.

## 12. Integration trace pass on one build, 2026-10-20

The replays that the changes since `6518f49e` touch were regenerated on one build: `88f5ffe7` (texture observer) and `b427cf00` (P22-A and P22-C, decision 336). The pass used the method of §11. All 28 replays pass. 4.1 stays **open** on one exclusion (§12.4).

### 12.1 Run identities

| Run | Identity | Result |
|---|---|---|
| Build | `zig build pyapi-tests -j2` from commit `f689f08a138d5dd5c75ab25a46cd7a698c5be5b7` (worktree `wt/api-integrate`), with a fresh `ZIG_GLOBAL_CACHE_DIR` under `tmp/scratch/api-integrate/`; CPU only | exit 0, 1 min 52 s (`build.log`) |
| Runner | `uzp-pyapi-tests.exe` SHA-256 `afabf268f0eaac9e11532a57fe5a94a705d480dd028f085b3e88792199c0611b`. All 51 installed Python files equal the commit's `python/` sources (`replay-build-identity.json`) | — |
| Replays, set 1 | `run_existing.py` on that binary, `UZP_UPDATE_TIER0_TRACE=1`, `UZP_OBSERVED_TRACE_DIR=traces/`, 16:45:59Z to 16:49:04Z | 19 passed, exit 0 (`replays.log`, `replays-junit.xml`) |
| Replays, set 2 | the same, `traces2/`; the replays whose `set_name` revision credit moved (§12.2) | 9 passed, exit 0 (`replays2.log`, `replays2-junit.xml`) |
| Conformance | `tests/python/test_capability_conformance.py` on the same binary | exit 0, 5 passed (`conformance.log`) |
| Manifest | `tests/capabilities` | exit 0, 44 passed (`capabilities-tests.log`) |
| Recorder | `tests/parity/recorder/test_api_probes_p22b_d297.py`, then its 2 failed node ids after the fix (§12.3) | exit 1, 34 passed and 2 failed; then exit 0, 2 passed (`recorder-d297.log`, `recorder-d297-rerun.log`) |

**Set 1** covered:
- `p22b-textureset-channels`;
- P22-A `phase1-mesh-map-update` and P22-C `phase1-restored-values`;
- the facade replays `phase1-resource-update`, `textureset-project-readback`, `fill-layer-readback`, `mask-stack`, `export-ocio-encode` and `export-ocio-encode-legacy`;
- the lifecycle replays `phase1-save-modes` and `phase1-resource-update`;
- the observed replays `phase1-create-mesh-maps` and `phase1-layer-stack-events`;
- the 5 layer replays and the colour replay.

**Set 2** covered:
- the facade replays `phase1-create-settings` and `phase1-delete-node`;
- the lifecycle replays `phase1-create-settings`, `phase1-delete-node`, `phase1-reload-mesh` and `phase1-execute-when-not-busy`;
- `phase1-close-without-saving`, `phase1-engine-computations` and `phase1-save-as-existing`.

The logs are in `tmp/scratch/api-integrate/`.

### 12.2 Trace

`tools/capabilities/tier0-trace.json` now holds 67 replays.
- **Added (2).** `facade-observed/phase1-mesh-map-update` and `facade-observed/phase1-restored-values`.
  - P22-A is exact apart from `s12/uid`, Painter's uid allocation (decision 336).
  - P22-C is exact with no exclusion.
- **`p22b-textureset-channels`.** It passes now that `88f5ffe7` skips unmaterialized channels. Its trace adds `TextureStateEvent.cache_key_invalidation_throttling_period` and `uzpainter.application.engine_computations_status`.
- **Moved revision credit (15 traces).** `b427cf00` moves the revision read of a value edit from `nodes.py` into `state.value_edit`, which the trace does not credit. So 15 traces lose `uzpainter.project.revision`:
  - 5 `facade-events/`: `phase1-create-settings`, `-delete-node`, `-execute-when-not-busy`, `-reload-mesh` and `-resource-update`;
  - 5 `facade-observed/`: colour, `engine-computations`, `layer-navigation`, `layer-node-kinds` and `levels-params`;
  - 5 `facade/`: `fill-layer-readback`, `mask-stack`, `phase1-create-settings`, `-delete-node` and `-resource-update`.

  The symbol keeps its evidence from other replays.
- **Mesh-map rebind.** It adds `uzpainter.textureset.TextureSet.get_mesh_map_resource` to both `phase1-resource-update` traces. The lifecycle trace also gains `substance_painter.textureset.TextureSet` and `all_texture_sets`.
- **Blending-mode replays.** Both gain `uzpainter.project.needs_saving`.
- **Unchanged.** The other 9 regenerated replays keep identical symbol sets.

### 12.3 Manifest

- **Promoted 0, demoted 0.** No exercised symbol was pending. `tier_evidence` follows the trace on 302 supported entries.
- **Status counts, unchanged.**
  - Painter inventory: 529 supported, 268 release-gap, 70 pending-evidence and 15 desktop-only.
  - UzPainter additions: 336 supported, 238 pending-evidence and 56 release-gap.
- **`update_layer_stack_resource @ mesh-map` stays a release gap,** facade and native.
  - Single-map replacement is implemented and exact on P22-A (decision 336).
  - It is not general. Import the same bytes under two names, bind AO to one and Thickness to the other: the facade replaces by name, but the native guard matches by content. So the update raises `NotYetSupported` before any change.
  - An alias control recording is pending. Until it replays exactly, both entries keep the gap. Owner: `phase5.3_parity-report-capability-gaps`.
  - The conformance recipe now builds that alias case. A run on this runner checked that it raises `NotYetSupported` with the revision unchanged (6 to 6) and both bindings as they were (`alias-check/report.json`).
- **`BlendingMode.PassThrough`.** The inventory entry and the compositor entry move from item 4.1 to `phase5.3_parity-report-capability-gaps` (gap register), re-checked should a later Painter build expose the member. Their recorded evidence is kept.
- **No manifest entry names phase1.24 any more.**
- **Recorder test fix.** Two tests in `test_api_probes_p22b_d297.py` failed:
  - `test_every_pending_symbol_of_the_group_is_requested_or_routed`;
  - `test_every_routed_symbol_names_its_route_in_the_manifest`.

  Both expected `substance_painter.display` to be pending under a decision 297 route. `abd94980` made it supported, through `display.set_environment_resource`, which `p22b-host-resources` exercises exactly. The expectation was stale, so the test's `ROUTED` table drops `display`. The inventory is unchanged and the recorder code untouched.

### 12.4 Item 4.1: not ticked

Clause by clause:
- **Three pipeline scripts through the adapter.** Holds, on item 3.2's evidence (§2, §4.1).
- **API-probe goldens exact apart from named exclusions with owners.** Does **not** hold yet, for one reason.
  - §11.6's behaviour failure is settled: `p22b-textureset-channels` passes.
  - §11.6's missing replays are settled: P22-A and P22-C replay exactly.
  - Still open: the `p22b-host-resources` `after_save_reopen s20/events` exclusion, the reload order of the one recording that reloads two resources at once (`tests/python/test_pyapi_observed_host_tier0.py`). It still names phase1.24 item 4.1 as its owner. A dedicated recording is being prepared for it (SUP-213/214), and item 4.1 stays open until it is replayed.
- **Results recorded in `parity/reports/phase1/`.** Holds: this section.

### 12.5 Before archive

- **Not archived.** Item 4.1 is open, and archiving also needs the coordinated full suite.
- **Native refusal message.** `src/python/edits.cpp` still reads "release gap until recording P22-A (phase1.24_python-api-facade)" for the mesh-map case. That case is now the alias case, owned by phase5.3. This is product code, left for its owner.

## 13. Final affected trace pass on the receiver-aware trace, 2026-10-20

Every `check_trace` and `check_observed_trace` replay was regenerated in one pytest session on one runner, using the method of §11. The session also ran the P22-A and P22-C replays, the mesh-map alias replay, the four decision 338 reload-order replays and the multiset unit tests. The source was main `e0106d9b` (receiver-aware `capability_trace.py`) plus Codex's uncommitted decision 338 patch.

All 108 tests passed, and the traces are consolidated. One conformance check fails, on one held symbol (§13.5), so **item 4.1 is not ticked yet** (§13.6).

### 13.1 Run identities

| Run | Identity | Result |
|---|---|---|
| Source | Worktree `wt/trace-final2` at `e0106d9bbfac76bcc650c242001ac17974c95803`, plus 8 uncommitted Codex files copied from the main checkout and never edited. Their SHA-256 values are in `source-overlay.json`: `python/FACADE.md`, `python/uzpainter_facade/resource.py`, `python/uzpainter_facade/state.py`, `tests/python/observed_replay.py`, `tests/python/test_pyapi_observed_host_tier0.py`, `tests/python/reload_result_multiset.py`, `tests/python/test_pyapi_reload_order_tier0.py` and `tests/python/test_reload_result_multiset.py`. Codex's padding files are not part of it. | — |
| Runner | No rebuild. `uzp-pyapi-tests.exe` SHA-256 `a15306f2b6b31cacd36bca2b8e244760878d25e08b9eec1550988bfb7d2917c2`, the install prefix of `tmp/scratch/closure/alias-padding-build`, built from `0e01fb36` plus the mesh-alias delta (`alias-padding-build-identity.json`). Its native sources equal `e0106d9b`'s, line endings aside, apart from `src/export/padding.cpp`, which the build took from Codex's padding work. The prefix was copied to `prefix/`, and the worktree's `python/` sources were laid over `prefix/bin/python`. All 51 installed Python files equal the worktree's sources (`replay-build-identity.json`). | — |
| Replays | One session (`run_existing.py`, no fixture rebuild), `UZP_UPDATE_TIER0_TRACE=1` and `UZP_OBSERVED_TRACE_DIR=traces/`, from 17:48:34Z to 18:12:19Z | 108 passed, exit 0, 1424.69 s (`replays.log`, `replays-junit.xml`) |
| Conformance | `tests/python/test_capability_conformance.py`, run once on the same prefix | exit 1: 4 passed, 1 failed (§13.5; `conformance.log`) |
| Manifest | `tests/capabilities`, run once | exit 0, 44 passed (`capabilities-tests.log`) |

The logs are in `tmp/scratch/trace-final2/`. The session covered:
- the 65 replays of §11;
- the 2 other tests of `test_pyapi_baking.py`;
- P22-A `phase1-mesh-map-update`, P22-C `phase1-restored-values` and the alias golden `p22b-mesh-map-alias-update`;
- the 4 reload-order replays of `test_pyapi_reload_order_tier0.py`. Each is compared with all 6 recordings of its golden, from 3 Painter sessions;
- the 34 tests of `test_reload_result_multiset.py`.

While the session ran, Codex's `tests/export` run on the source prefix of the runner (`uzp-export-tests.exe`) was also running. No `tests/evaluator`, `tests/preview` or `union_run` process was running.

### 13.2 Verdicts

"Exact" means exact in both recordings apart from the named exclusions. §11.3's ten observed goldens are exact, with their exclusions and comparison rules unchanged. The table below lists the goldens whose verdict or exclusions differ from §11.2, and the goldens §11 did not replay.

| Golden | Verdict | Exclusions, with owners |
|---|---|---|
| `p22b-textureset-channels` | exact (§11.6's failure is fixed, as §12 found) | none |
| `p22b-host-resources` | passes. The decision 338 scope is compared as a multiset (`comparison_passed: true`), so `exact_apart_from_exclusions` is false. | • s5 `import_project_resource`: refused, the COLOR_LUT is pinned to none (decision 038)<br>• s15 `get_environment_resource`: host content, permanent (decisions 006 and 038)<br>• s23 `reload_modified_resources_async`: release gap, shelf resources (phase3.3_procedural-families)<br>The §11 exclusion `after_save_reopen s20/events`, owned by item 4.1, is gone. Under decision 338 that output is now compared: the `ReloadResourcesEnded` results as a multiset of complete objects, with duplicates kept, and the outer events and errors exactly. |
| P22-A `phase1-mesh-map-update` | exact | s12 `uid`: Painter's uid allocation (decision 336) |
| P22-C `phase1-restored-values` | exact | none (lock-file suffix rule, decision 319 §9a) |
| `p22b-mesh-map-alias-update` | exact | none |
| `p22b-reload-order-zam` | exact, raw, against all 6 recordings | none |
| `p22b-reload-order-mza` | exact, raw, against all 6 recordings | none |
| `p22b-reload-order-zam-all-origins` | passes against all 6 recordings under decision 338 (`comparison_passed: true`, `exact_apart_from_exclusions: false`). The multiset scopes are s8 and s11 `events` in both conditions. | none |
| `p22b-reload-order-mza-all-origins` | as `zam-all-origins` | none |

**Decision 338.** The three decision 338 traces record `comparison_passed` and their comparison contract. Raw result order is unclaimed there: `raw_reload_result_order` reads `{parity: unclaimed, oracle_stability: fresh-process-unstable}`. This report does not claim that every replay is raw exact.

The four reload-order replays write `traces/*.trace.json` but no `check_observed_trace` record. So they add no entry to `tier0-trace.json` and credit no symbol.

**Outside the corpus claim.** Painter evidence has not observed two behaviours, and nothing here claims them:
- **(a)** A new alias with the same content, created after a save and reopen. The facade gives it the saved canonical origin (`state.Session.opened_resource_origins`). No recording creates such an alias.
- **(b)** Explicit outdated-ID behaviour: reloading or binding through a `ResourceID` whose version a later import has superseded.

The admitted reload controls (`p22b-reload-order-*` and `p22b-host-resources`) remain the closure evidence.

### 13.3 Trace

`tools/capabilities/tier0-trace.json` holds 68 replays, with none added or removed. 61 were regenerated with a changed symbol set. 7 are unchanged:
- `native/fill-layer-readback` and `native/textureset-project-readback`;
- `facade/textureset-project-readback`, `facade/phase1-fill-channel-defaults` and `facade/p22b-project-tangent-per-vertex`;
- `facade-observed/phase1-create-mesh-maps` and `facade-observed/p22b-mesh-map-alias-update`.

The diffs are in `trace-diff.txt`.

- **Receiver-aware attribution (`e0106d9b`).** An inherited call is now credited only to its receiver's class.
  - The false FillEffectNode credits disappear from 39 traces, among them the 8 of `facade/fill-layer-readback` and the 6 of `facade-events/phase1-reload-resources`, which Codex predicted.
  - In the other direction, the false FillLayerNode credits disappear from 5 traces: `mask-stack`, both `phase1-resource-update` traces, `phase1-blending-modes-mask` and `phase1-layer-navigation`. In `phase1-layer-navigation`, the receiver is a fill effect.
- **`uzpainter.project.Metadata` and `.get`.** They are added to 51 traces. This is facade-internal: since Codex's patch, `Session.project_started` reads the saved resource origins at every create and open. Both entries were already supported, so the credit only widens their `tier_evidence`.
- **`p22b-host-resources`.** It gains:
  - `uzpainter.resource.resource_origin` and `uzpainter.resource.ResourceID`, from s20 (the decision 338 scope), s22 `states` and the s24 reload. s22 and s24 are compared exactly;
  - `substance_painter.resource.ShelvesListFilter`, from s23 `states` (§13.5).

### 13.4 Manifest

The manifest was consolidated with §11's `consolidate2.py`, copied into `trace-final2/`. Nothing was deleted from the trace by hand.

- **Promoted (1).** `uzpainter.resource.resource_origin`, from pending-evidence. Its evidence is `p22b-host-resources`, through the exact s22 `states` and s24 reload outputs. Since Codex's patch, the reload worker calls it for every candidate without a saved origin.
- **Demoted (2), to pending-evidence, with reasons in their notes.** Both are now owned by `phase5.3_parity-report-capability-gaps`.
  - `substance_painter.layerstack.FillEffectNode.set_projection_parameters`. All 5 of its goldens (`fill-layer-readback`, `phase1-layer-navigation`, `phase1-layer-stack-events`, `export-ocio-encode` and `export-ocio-encode-legacy`) called it on fill layers. `FillLayerNode.set_projection_parameters` keeps that evidence.
  - `substance_painter.layerstack.FillLayerNode.is_symmetry_enabled`. Its one golden, `phase1-layer-navigation`, calls it on a fill effect. `FillEffectNode.is_symmetry_enabled` keeps that evidence.
- **`tier_evidence` narrowed (15).** These stay supported on their remaining goldens (`evidence-changes.txt`):
  - FillEffectNode: the class itself, `active_channels`, `get_projection_mode`, `get_projection_parameters`, `get_source`, `reset_source`, `set_projection_mode`, `set_source`, `set_symmetry_enabled` and `source_mode`;
  - FillLayerNode: `get_source`, `reset_source`, `set_projection_mode`, `set_source` and `set_symmetry_enabled`.
- **`tier_evidence` widened (3).** `uzpainter.project.Metadata`, `Metadata.get` and `uzpainter.resource.ResourceID`.
- **Status counts.**
  - Painter inventory: 528 supported, 72 pending-evidence, 267 release-gap and 15 desktop-only.
  - UzPainter additions: 338 supported, 237 pending-evidence and 55 release-gap.
- **No manifest entry and no exclusion names phase1.24 any more.**

### 13.5 Held: `ShelvesListFilter`, the one conformance failure

`test_supported_entries_equal_the_tier0_trace` fails with "exercised but not supported": `substance_painter.resource.ShelvesListFilter`. The other 4 conformance tests pass.

- **The credit comes from excluded material.** It comes from `p22b-host-resources` s23 `states`.
  - The s23 reload, a ShelvesListFilter reload, is an excluded output (release gap, shelf resources).
  - Its worker thread posts `ReloadResourcesEnded` after the call returns. Thread timing decides whether that work is traced under s23 or under s23 `states`.
  - It landed under s23 in the runs of §11 and §12, and under s23 `states` in this one.
  - §11 demoted the symbol for exactly this reason. Under the rule "no credit from excluded material", it is held at pending-evidence and not promoted.
- **The note is updated.** It now gives this reason instead of "the reload now ends before the call returns". The note was edited after the manifest test ran, and that test was not run again.
- **How it settles.** Either a trace rule attributes a reload worker's calls to the output that started the reload, or the coordinator decides to accept the credit. Either way, the owner is the trace tool. The facade's behaviour is not the cause.

### 13.6 Item 4.1

Clause by clause:
- **Three pipeline scripts through the adapter.** Holds, on item 3.2's evidence (§2, §4.1).
- **API-probe goldens exact apart from named exclusions with owners.** Holds on this run.
  - Every admitted API-probe golden replays, and every exclusion names an owner other than this task.
  - The last item 4.1 exclusion, `p22b-host-resources after_save_reopen s20/events`, is settled by the reload-order recordings under decision 338.
  - Raw result order inside a `ReloadResourcesEnded` stays unclaimed (§13.2), and behaviours (a) and (b) are outside the claim.
- **Results recorded in `parity/reports/phase1/`.** Holds: this section.
- **Capability evidence equal to the trace.** One symbol is short of it, the held `ShelvesListFilter` (§13.5), so the conformance check is red.

4.1 can be ticked once §13.5 is settled and Codex's patch is committed with these 8 file hashes. The full gate is still needed before archive.
