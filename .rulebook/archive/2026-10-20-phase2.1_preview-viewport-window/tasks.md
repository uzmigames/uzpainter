## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.25_pilot-wand — checked as a recorded scope split (decision 326): phase1.25_pilot-wand is not accepted; its open items (2.7 `infinite` padding and 3.1-4.1) are blocked only by Painter recordings; this task's deliverables do not read the Wand's maps

## 2. Implementation
- [x] 2.1 Environment precomputation for split-sum IBL (prefiltered radiance, BRDF lookup) and SH irradiance from the project environment
- [x] 2.2 Forward `painter_viewport` pass with GGX/Smith/Schlick/Burley lobes, the project's material parameters and MikkTSpace normal mapping
- [x] 2.3 Display transform shared with captures: OCIO with Painter's substance config pinned by hash and the view `Default - sRGB`; Legacy `Linear` and Legacy `ACES` pinned out by decision 038 (decision 042); explicit error for unsupported configurations
- [x] 2.4 Preview thread reading the double-buffered last evaluation without blocking the engine thread
- [x] 2.5 Preview window (`--preview <file.uzp>` and attached mode): read-only, orbit camera only, low frame rate, `painter_iray` panel stating the mode is unavailable until a capture exists
- [x] 2.6 Viewport regression goldens on UzmiGames-authored sphere, plane and bevelled-cube fixtures, keyed by build, adapter and driver

## 3. Tests
- [x] 3.1 Viewport regression goldens exact for a fixed build, adapter and driver, run locally on the owner's machine (decision 028); the local run report is the evidence
- [x] 3.2 Preview-thread stall hook: evaluation and export complete with unchanged results and no wait on the preview thread
- [x] 3.3 Window opened, minimised, resized and closed during evaluation: no effect on evaluation results or revision order
- [x] 3.4 Unsupported display configuration (Legacy `Linear`, Legacy `ACES`, ACE mode, another OCIO view) fails before rendering with an error naming decision 038

## 4. Acceptance
- [x] 4.1 Every §3 test green; results attached to `phase2.3_realtime-preview`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## 6. Notes (evidence and scope)
- 1.1: open; phase1.25_pilot-wand is not accepted. This task builds on the render layer, evaluator, supervisor/worker and display presets merged on main (8b4ea21).
- 2.1: `src/preview/environment.{h,cpp}`: OpenEXR and Radiance HDR decoding, the `iray.json` `environment-mapping` direction convention, SH irradiance (Ramamoorthi and Hanrahan 2001), six GGX-prefiltered levels and the 32 x 32 (A, B, Burley D) albedo table (Karis 2013; Heitz 2014; Burley 2012), deterministic on the CPU.
- 2.2: `src/preview/viewport.{h,cpp}`, `shaders/viewport.hlsl`: one compute pass on the render layer with CPU tile binning and per-pixel ray casting, GGX/Smith/Schlick specular and Burley diffuse, base colour, metalness, roughness and the combined `Normal_OpenGL` map (height as bump) in the MikkTSpace frame. Emission (luminance 0) and opacity are off, as in the Iray fits (decision 042).
- 2.3: decision 134 (panel: AGREE x1, PARTLY x2 on the realisation; AGREE x3 on the refusals and the environment rule). The pinned view is realised as its calibrated binary16 table, shared by GPU and CPU, without linking OpenColorIO; the config hash is the display presets' `kOcioConfigSha256`. Every other configuration fails before any GPU work, naming what differs and decision 038.
- 2.4: `src/preview/latest.h` (wait-free triple buffer) and `PreviewFeed`; the preview thread owns its own `render::Engine`, so it never queues on the worker's device.
- 2.5: `UzPainter.exe --preview <file.uzp>` and `--worker/--mcp ... --preview` (`preview_status`, Debug-only `test_fault preview_stall|preview_resume`). The window reads the view, the config pin and the clear colour from the display presets' state (`python::display::PresetOf`, decision 132). The `painter_iray` panel states the mode is unavailable: no capture can exist before P3-PATHTRACER, so showing an existing capture has nothing to show until phase3 delivers one. Every project UzPainter creates today is Legacy colour-managed, so the window shows the decision 038 refusal for it until a project carries the OCIO identity (phase1.15_compositor-colour-fits gates OCIO creation).
- 2.6, 3.1: `tests/preview/viewport-goldens.json`, keyed by (viewport kernel XXH64, adapter, driver). Local run on the owner's machine, 2026-10-12, NVIDIA GeForce RTX 4090, driver 32.0.16.1714, kernel `aa3bdc3d44f421cd` (CRLF checkout; `d6b90f6fa9031f0a` is the same HLSL with LF endings, identical image hashes): sphere display `cc7c22d2...`, plane `d9a9ea63...`, bevelled cube `6403eaee...`; two renders byte-identical and every display code equal to the CPU table. `python -m pytest tests/preview -v`: 6 passed, 2 failed (a test bug: export hashes keyed by tuples); after the fix and the merge of main, `tests/preview/test_preview_window.py` + `tests/supervisor/test_worker_pipe.py`: 13 passed.
- 3.2: the stall hook holds the preview thread while it holds its frame; evaluation, a commit and an export complete with the bytes and revisions of a worker without a preview; frames keep being published and are not taken until the stall ends.
- 3.3: window minimised, restored, resized twice and closed between and during evaluations: results and revision order equal the baseline's; the worker keeps serving after the close.
- 3.4: native case `viewport-unsupported` (Legacy Linear, Legacy ACES, ACE mode, another view: no GPU submission, error names decision 038) and `display` (CPU, every configuration).
- 4.1: results attached to `phase2.3_realtime-preview` (its notes).
