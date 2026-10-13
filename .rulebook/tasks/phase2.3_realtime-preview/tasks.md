## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand
- [ ] 1.2 Child accepted: phase2.1_preview-display-presets
- [ ] 1.3 Child accepted: phase2.1_preview-viewport-window
- [ ] 1.4 Child accepted: phase2.2_preview-capture

## 2. Implementation
- [ ] 2.1 Integration scenario on the wand v1 project: worker with an attached preview window running evaluation, export and captures in all Phase 2 modes
- [x] 2.2 Settling report writer for `parity/reports/phase2/preview-settling.json`
- [x] 2.3 (decision 148's release gap, owned here) Orthographic cameras in `painter_viewport` captures (decision 163)

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
  The test also checks that `painter_viewport` is refused on the Legacy wand (the window shows the same refusal), that `painter_iray` is refused, and that the same worker renders the OCIO fixture in the window (`frames_rendered`) and in a `painter_viewport` capture. What stays open, with its owner:
  - `painter_viewport` and the window rendering the wand itself wait on phase1.15_compositor-colour-fits (OCIO creation and fill evaluation under OCIO). The test fails, naming phase1.15, once the wand is no longer Legacy.
  - The pipeline's `infinite` padding and its Normal map (a virtualMap under `passthrough` is unrecorded, R-090) wait on phase1.25_pilot-wand item 2.7. Until then the export runs with `passthrough` padding and four maps, and switches when `export-processing.json` `padding-islands` is fitted.
- 2.2: `tools/parity/settling/preview.py`, schema `uzpainter/preview-settling/1`, decision 162.
  - It follows decision 150's structure: closed, entries keyed by case and backend, and Vulkan `pending` with decision 121. The diagnostic captures and `painter_iray` run on the `cpu` backend.
  - The writer is the `tests/preview/conftest.py` hook under `UZP_PREVIEW_SETTLING_REPORT`. Tests carry `@pytest.mark.preview_settling(<case>)`, and the children's tests are tagged, not copied.
  - The guard rule is `parity/reports/<phase>/preview-settling.json`.
  - The report is `parity/reports/phase2/preview-settling.json`. The wand cases are `not_run` until the coordinator's batch run.
- 2.3: decision 163. Parallel rays along the forward axis from the plane through the camera. `orthographic_height` is the full vertical extent, a UzPainter convention like the vertical field of view. Only hits in front of that plane count.
  - The perspective images are byte-identical. The regression goldens were re-keyed to kernels `3f173b7573f95bba` (CRLF) and `91bc3285269b6519` (LF), with every image hash unchanged.
  - Found while testing, and older than this change: perspective rays are not watertight. Five pixels on the plane's shared diagonal show the background, because the binary32 Moller-Trumbore test misses both triangles on the shared edge. The fix changes the perspective goldens and needs an owner.
- 3.1: `painter_viewport` comes from a worker that owns no window (phase2.2's `test_headless_viewport_capture`, OCIO fixture). `base_color`, `channel:roughness` and `mask:<uid>` come from `UzPainter.exe run` (`test_diagnostic_captures_equal_channel_exports`). Both passed in the report run.
- 3.2: open, implemented. `test_wand_v1_export_with_the_preview_minimised_and_stalled`: with the window minimised and the preview stalled while it holds its frame, the evaluation and export run to the end with the baseline's bytes; `frames_taken` stays frozen and `frames_published` grows. The window-open export is the 2.1 test's. The export times are report metrics with no threshold (decision 162).
  - The full wand run takes about 30 minutes: one Debug CPU export is 7.5 minutes, 6.6 of them BaseColor. That is beyond an agent's 10-minute budget, so it belongs to the coordinator's batch:
    `UZP_PREVIEW_SETTLING_REPORT=<repo>/parity/reports/phase2/preview-settling.json python -m pytest tests/preview/test_preview_settling.py`
  - `UZP_PREVIEW_WAND_QUICK=1` (no BaseColor) passed both wand tests in about 7 minutes. It is never evidence.
- 3.3: done. `painter_iray` is a `release-gap` in the manifest `UzPainter.exe capabilities` prints (`test_painter_iray_is_an_unavailable_capability`), it is refused by `uzpainter.render.capture` and by the worker's `capture` before any work, and `uzpainter://capabilities` publishes that manifest unchanged with the entry among its release gaps (phase2.6_mcp-typed-tool-families, `tests/supervisor/test_typed_tools.py::test_unavailable_families_fail_before_mutation`, which also checks the `capture` refusal over MCP; decisions 162, 165).
- 4.1: open until the splits close (decision 162, panel PARTLY ×2): phase1.15 (the wand rendered), decision 121 (Vulkan entries) and phase2.6 (the resource).
- 5.3: open until the coordinator's batch run of `tests/preview/test_preview_settling.py` at full size. Tests run (2026-10-12, RTX 4090, driver 32.0.16.1714), each command once, re-running only failures:
  - `tests/preview` regression goldens, `painter_iray`, diagnostics, headless viewport, stall, window lifecycle, and `test_painter_iray_is_an_unavailable_capability`: 7 passed.
  - The orthographic test failed once on its perspective contrast (the crack above); after the fix it passed.
  - The wand tests first failed at setup: `passthrough` refuses the Normal virtualMap. A 512 px variant refused the wand's sRGB bitmap at non-1:1. The quick run then gave 2 passed.
  - `tests/parity/test_guard.py` preview-settling cases: 12 passed. `tests/capabilities/test_capabilities.py`: 28 passed.
  - ruff, ruff format and mypy --strict pass on the touched Python. `zig build painter preview-tests` builds with -Werror.
