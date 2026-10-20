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
| `phase1-create-default-paths` (P21-B) | exact apart from one open seam | `s3/get_default_export_path` is a release gap: the facade has no such function and raises AttributeError. Painter returns its user's export folder. This is an **open 4.1 seam** owned by phase1.24_python-api-facade item 4.1. The symbol stays `release-gap`, and its excluded output promotes no symbol. |
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

Item 4.1 stays open for:
- the 18 P22-B recordings (decisions 295-297), with their admission and compared replays;
- the `get_default_export_path` release gap (P21-B s3), owned by phase1.24_python-api-facade item 4.1.
