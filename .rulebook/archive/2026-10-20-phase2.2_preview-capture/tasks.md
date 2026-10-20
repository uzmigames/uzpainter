## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.25_pilot-wand, phase2.1_preview-viewport-window, phase2.1_preview-display-presets — checked as a recorded scope split (decision 326): phase1.25_pilot-wand is not accepted; its open items (2.7 `infinite` padding and 3.1-4.1) are the Wand's own parity work: recordings plus fit; this task's deliverables do not read the Wand's maps

## 2. Implementation
- [x] 2.1 Capture entry point with modes `painter_viewport`, `base_color`, `channel:<name>`, `mask:<uid>` and explicit camera, size, samples, seed and preset
- [x] 2.2 Readiness: wait for evaluation of the current revision and all resource uploads before rendering
- [x] 2.3 Offscreen rendering without swapchain or window; display transform; readback through `TextureReadback`; PNG and EXR writers
- [x] 2.4 Capture receipt with every field of `07-…` §5
- [x] 2.5 Diagnostic modes as direct channel visualisations
- [x] 2.6 `painter_iray` mode returns `PathTracerUnavailable` before any work and is listed as a release gap
- [x] 2.7 Pipeline adapter `save_viewport` shim routed to `capture(mode=painter_viewport)`
- [x] 2.8 Worker capture command handler on the IPC vocabulary for the MCP `capture` tool

## 3. Tests
- [x] 3.1 Headless capture in a local run on the owner's machine (decision 028) with no window, no desktop focus and no swapchain
- [x] 3.2 Freshness: mutate, capture, and check the receipt revision and the changed pixels
- [x] 3.3 Receipt schema test covering every field
- [x] 3.4 Diagnostic captures (`base_color`, `channel:roughness`, `mask:<uid>`) equal the corresponding channel exports in decoded values
- [x] 3.5 `painter_iray` capture fails with `PathTracerUnavailable` before any work
- [x] 3.6 Pipeline adapter shim test through `UzPainter.exe run` with the pipeline's capture subcommand

## 4. Acceptance
- [x] 4.1 Every §3 test green; results attached to `phase2.3_realtime-preview`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## 6. Notes (evidence and scope)
- 1.1: open; phase1.25_pilot-wand is not accepted (G1 prerequisite). Both phase2.1 children are on main (decisions 132, 134) and this task builds on them.
- Decision 148. One panel round: AGREE x3 on C8; AGREE or PARTLY on the rest, with every PARTLY point adopted except a typed GPU-unavailable class (one vote). It fixes four things:
  - the diagnostic modes are texture-space files made by the export engine;
  - `painter_viewport` renders offscreen on the process's GPU from a CPU evaluation of the committed revision;
  - the receipt `uzpainter/capture-receipt/1`;
  - the shim and the worker tool.
- 2.1: `src/python/capture.{h,cpp}` with `CaptureArguments` (mode, path, camera, size, samples, seed, preset, stack). It is bound as `uzpainter.render.capture` (`bind_display.cpp`), and the `capture` gap stub is removed. The pass takes a `CameraPose` (eye and basis; `viewport.{h,cpp}`), so a Painter camera record renders as its `Rx @ Ry @ Rz` frame. The orbit cameras of the window and of the goldens render byte-identically (`viewport-golden` green).
- 2.2: every capture reads the committed revision once (and refuses inside an open Transaction), evaluates it synchronously on a CPU evaluator and records that revision. The pass uploads its buffers, places barriers, dispatches and waits in one submission, and only then reads back.
- 2.3: the scene comes from the window's own builder, `preview::SceneOf` (moved to `src/preview/scene.cpp`). The display configuration is checked before any evaluation or device.
  - The process's GPU is the worker's engine, or `run`'s `--gpu-backend` device created per capture (`SetCaptureGpu`).
  - Readback goes through `TextureReadback`; the writers are the export's `EncodePng` (16-bit RGB display codes) and `EncodeExr` (RGB binary16 linear).
  - No window and no swapchain exist on this path.
- 2.4: `src/python/capture-receipt.schema.json`. It holds every field of 07 §5, plus `schema`, `project_uuid`, `source` and `encoding`. `render_state_digest` is the SHA-256 of the canonical resolved render state; `hashes` hold the SHA-256 of the files written. The receipt is written as `<stem>.receipt.json` and returned with `files`.
- 2.5: `base_color`, `channel:<name>` and `mask:<uid>` are one-file export plans (`documentMap baseColor`, `documentMap <name>`, `diagnosticMap materialMask/<uid>`, padding `passthrough`), encoded by `EncodeExport` as PNG 16 and OpenEXR 32f. They are refused under OCIO with the export's own `NotYetSupported` (phase1.18).
- 2.6: `painter_iray` raises `uzpainter.exception.PathTracerUnavailable`, a new `NotYetSupported`, before any argument check, project read, device or file. The worker refuses it before the path check.
  - Manifest: `uzpainter.render.capture` context `mode:painter_iray` stays `release-gap` (the conformance test now calls it); the symbol, context `any`, is `pending-evidence` with each mode's domain in its notes; `PathTracerUnavailable` is listed.
- 2.7: `adapters/assets3d/runner.py`. `save_viewport(path, w, h, _)` calls `uzpainter.render.capture(path, "painter_viewport", size=(w, h))` and raises its errors unchanged (`MIGRATIONS.md` M3).
- 2.8: worker tool `capture {mode, path, camera?, size?, samples?, seed?, preset?, texture_set?, stack?}`: non-mutating and listed `gpu: true`. Only `painter_viewport` checks the device. The path stays inside `--output-root`, and the tool returns the receipt (`src/supervisor/SUPERVISOR.md`).
- Scope today (decision 148):
  - `painter_viewport` renders only the pinned OCIO configuration, and every project UzPainter creates is Legacy. Its tests therefore use an OCIO bundle without fill sources (`tests/preview/conftest.py` `ocio_bundle`): a Legacy export-bundle whose manifest declares OCIO with Painter's config hash.
  - The diagnostic modes run on Legacy projects only, because the export refuses OCIO.
  - Rendering painted OCIO projects waits on phase1.15_compositor-colour-fits (OCIO creation, fill sources under OCIO) and phase1.18_export-engine (OCIO export).
  - An orthographic camera was a release gap owned by phase2.3_realtime-preview; it renders since decision 163.
  - `field_of_view` is used as the vertical angle: a UzPainter convention, not a measured Painter fact (square captures are unaffected).
  - Open for the owner: the render standard's screen-space Base-color viewport pass is not one of these modes, and no task owns it yet.
- Tests (2026-10-12, owner machine, RTX 4090, driver 32.0.16.1714), each run once, re-running only failures:
  - `tests/preview/test_preview_capture.py`: 7 passed.
    - CPU: `painter_iray` (3.5), the diagnostic modes against the exports (3.4), the receipt schema (3.3), diagnostic freshness (3.2) and the worker tool (2.8).
    - GPU: the headless viewport capture (3.1: the worker owns no window before or after; PNG codes = decision 134's table of the EXR values; worker and `run` give the same bytes; the preset argument does not commit) and viewport freshness after `camera_set` (3.2).
  - `tests/preview/test_preview_viewport.py` unsupported configuration and regression goldens: 2 passed (the `CameraPose` refactor keeps the golden bytes).
  - `tests/python/test_pyapi_cli.py::test_run_with_an_unavailable_backend`: passed. The first GPU call under `--gpu-backend vulkan` raises `gpu_backend_unavailable` (closes phase1.22's 3.3 scope split).
  - `tests/python/test_capability_conformance.py`: 5 passed.
  - `tests/adapters/assets3d/test_pipeline_adapter.py::test_the_shim_writes_the_viewport_under_uzpainter_run`: passed (3.6).
  - ruff and mypy --strict on every touched Python file; `zig build painter pyapi-tests preview-tests` with -Werror.
- 3.6: the shim is tested through `UzPainter.exe run runner.py`. The capture the pipeline's `capture` subcommand makes (its CAPTURE_CODE) writes a 64 x 48 PNG and its receipt on the OCIO fixture.
  - `test_capture_on_the_legacy_wand_is_the_unsupported_configuration` runs the pipeline's own subcommand on the Legacy wand, where the expected refusal is `UnsupportedInUzPainter unsupported_configuration`.
  - After the merge of main (Wand R9 re-pin 261c912, decision 144: inputs resolved by hash from the private store), `tests/preview/test_preview_capture.py` and `tests/adapters/assets3d/test_pipeline_adapter.py` passed 27 of 27, the Legacy-wand subcommand test among them (exit 0, 2026-10-12).
  - The subcommand's success path on a painted project is the decision-148 scope split (phase1.15, phase1.18).
- 4.1: results attached to `phase2.3_realtime-preview` (its notes).
