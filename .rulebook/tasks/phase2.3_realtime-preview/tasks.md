## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand
- [ ] 1.2 Child accepted: phase2.1_preview-display-presets
- [ ] 1.3 Child accepted: phase2.1_preview-viewport-window
- [ ] 1.4 Child accepted: phase2.2_preview-capture

## 2. Implementation
- [ ] 2.1 Integration scenario on the wand v1 project: worker with an attached preview window running evaluation, export and captures in all Phase 2 modes
- [x] 2.2 Settling report writer for `parity/reports/phase2/preview-settling.json`
- [x] 2.3 (decision 148's release gap, owned here) Orthographic cameras in `painter_viewport` captures (decision 163)
- [x] 2.4 (decision 251) Ray-traced self-occlusion in `painter_viewport`: a deterministic CPU-built BVH over every texture set's triangles, diffuse and specular visibility ratios per RGB channel (environment-importance samples mixed with cosine samples for the diffuse and with GGX VNDF samples for the specular), counts chosen by measurement; the `shadows` flag declared inert in the receipt, `render.display.state()`, the capability notes, PREVIEW.md and 07 §6; the AO mesh map stays unapplied
- [x] 2.5 (decision 257 and its amendment) The AO mesh map in `painter_viewport`: a fifth material slot fed by `exporter::PassThroughMeshMap`, applied inside the diffuse and specular visibility rays as the per-ray weight `μ^k` about the faded shading normal (`k = 2(1 − a)/a`, cosine-weighted mean `a`, glTF strength 1.0); the window's material maps, lighting and BVH resident on the GPU per revision; no cavity or horizon term (cavities stay open, see §9), the AO channel not applied; the receipt's `occlusion` record, `render.display.state()`'s `ao_strength` and `ao_channel`, the capability notes, PREVIEW.md and 07 §6

## 3. Tests
- [x] 3.1 Captures in a local run on the owner's machine (decision 028) without any window or desktop focus, in `painter_viewport`, `base_color`, `channel:<name>` and `mask:<uid>` modes
- [ ] 3.2 Preview window open, minimised and stalled while the wand v1 export runs: export bytes and timing unaffected by the preview, no evaluation wait on the preview thread
- [x] 3.3 `painter_iray` reported as an explicit unavailable capability in `uzpainter://capabilities` and by `capture`

## 4. Acceptance
- [ ] 4.1 DAG gate met: captures window-independent and preview never pauses evaluation; report written to `parity/reports/phase2/preview-settling.json`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Notes (child results)
- phase2.1_preview-viewport-window (2026-10-12, owner machine, RTX 4090 driver 32.0.16.1714): `tests/preview` all green (display, environment, hand-over, unsupported configuration, regression goldens of sphere/plane/bevelled cube, stalled preview, window lifecycle, standalone `--preview`); details in that task's notes.
- phase2.2_preview-capture (2026-10-12, owner machine, RTX 4090 driver 32.0.16.1714; decision 148): `tests/preview/test_preview_capture.py` 7 passed. These are the headless `painter_viewport` capture, `painter_iray` refused before any work, diagnostic captures equal to the exports, the receipt schema, and freshness after mutations. The viewport goldens still hold, and the adapter shim writes the viewport under `UzPainter.exe run`. `painter_viewport` renders only OCIO projects without fill sources until phase1.15; the diagnostic modes are Legacy-only until phase1.18. Details in that task's notes.

## 7. Notes (this task, 2026-10-12; decisions 162, 163)
- Prerequisites 1.1-1.4: open. phase1.25_pilot-wand is not accepted, and each child keeps its own 1.1 open on it; all three children are merged with every other item checked.
- 2.1: open, implemented. `tests/preview/test_preview_settling.py::test_wand_v1_with_the_preview_attached` rebuilds the wand v1 through the pipeline adapter. A DX12 worker with the preview window open must give a worker without a preview's bytes for:
  - the GPU evaluation of the five channels;
  - the pipeline's export configuration;
  - captures `base_color` and `channel:roughness`, equal in decoded values to the maps exported in the same worker, plus the gem's `mask:<uid>`.
  The test also checks that `painter_iray` is refused. Since decision 207 (86052ed) the wand is an OCIO project with Painter's substance config (`painter_create.py` sets `OCIO`), so the window draws the wand with its four maps and `painter_viewport` renders it (decision 248; the capture evaluates every wand map on the Debug worker's CPU evaluator, about 11 minutes, so a quick run leaves it out). The same worker then closes the wand, and renders the OCIO fixture in the window and in a `painter_viewport` capture. Until 2026-10-13 the test still expected the Legacy refusal: the capture ran for about 11 minutes and then failed on the missing refusal. What stays open, with its owner:
  - The pipeline's `infinite` padding and its Normal map (a virtualMap under `passthrough` is unrecorded, R-090) wait on phase1.25_pilot-wand item 2.7. Until then the export runs with `passthrough` padding and four maps, and switches when `export-processing.json` `padding-islands` is fitted.
- 2.2: `tools/parity/settling/preview.py`, schema `uzpainter/preview-settling/1`, decision 162.
  - It follows decision 150's structure: closed, entries keyed by case and backend, and Vulkan `pending` with decision 121. The diagnostic captures and `painter_iray` run on the `cpu` backend.
  - The writer is the `tests/preview/conftest.py` hook under `UZP_PREVIEW_SETTLING_REPORT`. Tests carry `@pytest.mark.preview_settling(<case>)`, and the children's tests are tagged, not copied.
  - The guard rule is `parity/reports/<phase>/preview-settling.json`.
  - The report is `parity/reports/phase2/preview-settling.json`. The wand cases are `not_run` until the coordinator's batch run.
- 2.3: decision 163. Parallel rays along the forward axis from the plane through the camera. `orthographic_height` is the full vertical extent, a UzPainter convention like the vertical field of view. Only hits in front of that plane count.
  - The perspective images are byte-identical. The regression goldens were re-keyed to kernels `3f173b7573f95bba` (CRLF) and `91bc3285269b6519` (LF), with every image hash unchanged.
  - Found while testing, and older than this change: perspective rays are not watertight. Five pixels on the plane's shared diagonal show the background, because the binary32 Moller-Trumbore test misses both triangles on the shared edge. Fixed by decision 178 (watertight coverage); no golden image changed.
- 3.1: `painter_viewport` comes from a worker that owns no window (phase2.2's `test_headless_viewport_capture`, OCIO fixture). `base_color`, `channel:roughness` and `mask:<uid>` come from `UzPainter.exe run` (`test_diagnostic_captures_equal_channel_exports`). Both passed in the report run.
- 3.2: open, implemented. `test_wand_v1_export_with_the_preview_minimised_and_stalled`: with the window minimised and the preview stalled while it holds its frame, the evaluation and export run to the end with the baseline's bytes; `frames_taken` stays frozen and `frames_published` grows. The window-open export is the 2.1 test's. The export times are report metrics with no threshold (decision 162).
  - The full wand run takes about 30 minutes: one Debug CPU export is 7.5 minutes, 6.6 of them BaseColor. That is beyond an agent's 10-minute budget, so it belongs to the coordinator's batch:
    `UZP_PREVIEW_SETTLING_REPORT=<repo>/parity/reports/phase2/preview-settling.json python -m pytest tests/preview/test_preview_settling.py`
  - `UZP_PREVIEW_WAND_QUICK=1` (no BaseColor) passed both wand tests in about 7 minutes. It is never evidence.
- 3.3: done. `painter_iray` is a `release-gap` in the manifest `UzPainter.exe capabilities` prints (`test_painter_iray_is_an_unavailable_capability`), it is refused by `uzpainter.render.capture` and by the worker's `capture` before any work, and `uzpainter://capabilities` publishes that manifest unchanged with the entry among its release gaps (phase2.6_mcp-typed-tool-families, `tests/supervisor/test_typed_tools.py::test_unavailable_families_fail_before_mutation`, which also checks the `capture` refusal over MCP; decisions 162, 165).
- 4.1: open until the splits close (decision 162, panel PARTLY ×2): phase1.15 (the wand rendered), decision 121 (Vulkan entries) and phase2.6 (the resource).
- 4.1 (decision 221, 2026-10-13): the Vulkan entries of `parity/reports/phase2/preview-settling.json` (`viewport_capture_headless`, `preview_stall`, `preview_window_lifecycle`, `wand_integration`, `wand_export_preview`) are acceptance obligations of `phase3.1_vulkan-compute-parity` items 2.7 and 4.1, not of this task: G2 is pilot parity on DX12 and does not wait on a Phase 3 backend. They stay `pending` with decision 121 in the report until phase3.1 settles them, and reach G3 and G5 through it. Nothing is waived; 4.1 stays open on the other splits.
- Acceptance waits on: phase1.15_compositor-colour-fits (the wand rendered in `painter_viewport` and the window; item 2.1 and decision 162's split, written here as a canonical wait under decision 221)
- 5.3: open until the coordinator's batch run of `tests/preview/test_preview_settling.py` at full size. Tests run (2026-10-12, RTX 4090, driver 32.0.16.1714), each command once, re-running only failures:
  - `tests/preview` regression goldens, `painter_iray`, diagnostics, headless viewport, stall, window lifecycle, and `test_painter_iray_is_an_unavailable_capability`: 7 passed.
  - The orthographic test failed once on its perspective contrast (the crack above); after the fix it passed.
  - The wand tests first failed at setup: `passthrough` refuses the Normal virtualMap. A 512 px variant refused the wand's sRGB bitmap at non-1:1. The quick run then gave 2 passed.
  - `tests/parity/test_guard.py` preview-settling cases: 12 passed. `tests/capabilities/test_capabilities.py`: 28 passed.
  - ruff, ruff format and mypy --strict pass on the touched Python. `zig build painter preview-tests` builds with -Werror.

## 8. Notes (item 2.4, 2026-10-13; decision 251)
- 2.4: done on branch `wt/viewport-shadows`.
  - `src/preview/visibility.{h,cpp}` builds the BVH: binned SAH, leaves of at most 4 triangles, a depth cap of 32 that the kernel's stack matches. It is cached by the world-space corners bit for bit.
  - `PrecomputeLighting` builds the environment-importance distribution.
  - `viewport.hlsl` multiplies the specular and the diffuse by their per-channel visibility ratios.
  - The receipt gains `visibility` (in the digest) and `shadows` (requested, effect none). `render.display.state()` gains `shadows_effect`.
  - Docs: PREVIEW.md (Lighting, Pass, Captures, goldens), 07 §5-§6, PYAPI.md and the capability notes.
- Counts: (128, 64), after the review (below).
  - It is the smallest pair of the ladder (8, 4) to (256, 128) whose ratios meet the `0.5 / sqrt(N)` noise bound on the concave fixture. On the Wand v1 low mesh (1248 triangles, Debug build) its window-size render took 170.0 ms, within the 200 ms period, while another agent's GPU test ran.
  - At 1700 × 1250 it took 689 ms. The RMSE against (1024, 1024) is 0.0042, and 0.0354 without occlusion.
  - The table is in PREVIEW.md.
- Goldens re-keyed to `e570812a72826a6c` (CRLF) and `6f233e84d741c0ac` (LF), then, after the review, to `87e4fbc2537c02f2` (CRLF) and `4e1b7a7f23a5ebfb` (LF).
  - Sphere, plane and bevelled cube: 0 changed pixels against the `51810c8132b4cdc5` renders, display and linear.
  - `cube-on-plane` is added.
- Found while testing and fixed:
  - **Shared-edge leak.** The BVH slab test replaced a zero direction component by 1e-20. A ray running along a box face then got a far distance of 0 in that slab and skipped the node, so a ray along a box edge leaked (BVH only; the test of every triangle blocked it). A component of 0 now checks the origin against the slab.
  - **Specular estimator.** The `0.5 / sqrt(N)` bound held for the diffuse ratio (0.073 at 32 rays) but not for the specular one (0.217 at 16 rays), because VNDF rays alone do not sample the radiance. Fixed in the review, below; the bound is kept for both terms.
- Review fixes (2026-10-13):
  - **Specular estimator.** The specular ratio now mixes VNDF directions with environment-importance directions under the balance heuristic, as the diffuse one does: `w = F·D·G2 / (4·n·v·p_mix)`. At 16 rays its RMSE fell from 0.217 to 0.130, still above the 0.125 bound. The count was raised, not the bound: at 64 rays it is 0.051 (bound 0.0625). The interim `N_eff = N / 4` was removed.
  - **Black pixels and speckle.** Root cause: the old specular estimator, not self-hits. The three pure-black pixels of the 3/4 close view (e.g. (x 1243, y 734), 156 before, 0 after) show 144 in a 1024-ray render. Their diffuse ratio was 0.98-1.0; they are metal, so one blocked heavy VNDF ray zeroed the only term. The rim glint at (x 1068, y 607) of the owner's view (255 before, 39 after) shows 194 at 1024 rays. No pixel of the 1024-ray render has a ratio of 0, and only 1 of 213 029 wand pixels has a diffuse ratio below 0.05, so no origin is buried in a shell. The glint at (x 1358, y 741), 255 to 29, is real: 35 at 1024 rays, diffuse ratio 0.14, inside the pommel step.
  - **Renders at (128, 64).** Compared with a (1024, 1024) render of the same views, the 3/4 close view has RMSE 0.82 codes (8-bit), against 3.04 before the fix. It has no pure-black pixel, and 55 groups darkened by more than 40 codes, against 38 in the reference and 354 before the fix. The owner's view has RMSE 0.78 codes, against 2.87.
  - **What the owner will see.** Self-occlusion only: there is no floor under the standard, and the AO mesh map is not applied. In the owner's full frame, 8458 of 44 299 wand pixels change, darkened by 4.35 codes on average, and the wand's mean drops from 64.51 to 63.68. To the eye that looks the same as before. The darkening shows only in 4x crops: the ferrule and pommel rims, the ring and the pommel's inner step. The leather-wrap seams do not change, because they are normal-map detail, not geometry. The crevice darkening of Painter's realtime viewport comes from the AO map, an open question for phase3.5 item 3.3.
- Wand before and after (owner's view and a 3/4 close view of the grip) are for the owner's eye only, never evidence.
  - The base build reproduces the owner's capture byte for byte: PNG `f22b9da6…`, digest `b0ca4cda…`.
- AO stays unapplied. The factorial AO recording belongs to phase3.5_path-tracer-materials item 3.3.

## 9. Notes (item 2.5, 2026-10-13; decision 257)
- 2.5: done on branch `wt/viewport-ao`. `painter_viewport` applies each texture set's AO mesh map (`a = 1 + 1.0·(ao − 1)`) inside decision 251's diffuse and specular rays as the per-ray weight `μ^k`, `k = 2(1 − a)/a`, about the faded shading normal.
  - `MaterialSlot::Occlusion` and `MaterialInputs::occlusion`, fed by `exporter::PassThroughMeshMap` (`preview::OcclusionOf`) in `EvaluateFrame` and in the capture; a set without an AO mesh map reads 1. The AO channel is not applied.
  - The receipt gains `occlusion` (in the digest); the schema follows; `render.display.state()` gains `ao_strength` and `ao_channel`. Docs: PREVIEW.md, 07 §5-§6, PYAPI.md, the capability notes; approved sources P-OAT, P-JIMENEZ and S-GLTF's scope.
  - Amendment of decision 257 (A1-A4, for the coordinator's ruling): the hard cone first specified tore smooth metal into black and ended its darkening on triangle edges, so it was replaced by the power-law weight of the same calibration; the 256 specular rays an earlier build traced in the cone are withdrawn (64 meets the grain measure with the weight); the window's camera-independent inputs are resident on the GPU per revision (`ResidentInputs`), which makes the Consequences' 200 ms window and upload-cache claims true (135 ms at 660 × 600 with the Wand's five 2048² maps, Debug); each Consequence is marked met, superseded or tested in A3.
  - Goldens re-keyed to `12ad333c66b267b6` (CRLF) and `bb1a1bc7ea0a64bd` (LF); all four fixtures keep their hashes.
  - Tests: `test_preview_viewport.py::test_viewport_ao_visibility` (`uzp-preview-tests viewport-occlusion`), the goldens, `test_preview_capture.py::test_viewport_capture_applies_the_ao_mesh_map` (the real input path) and the receipt checks, the state check of `test_display_presets.py`; `uzp-preview-tests viewport-occlusion-time` (manual, asserts the 200 ms window).
  - Not done, not claimed: a cavity term. The owner's "cavities" are met only where the AO bake holds them; inlays and grooves whose bake reads close to 1 stay flat. A cavity term needs its own decision (decision 257 item 4: analytic fixtures, texel-density normalisation, a bound Curvature mesh map, which the Wand lacks) and a decision number from the coordinator.
  - The Wand before and after (four views, 1920 × 1080) are for the owner's eye, never evidence.
