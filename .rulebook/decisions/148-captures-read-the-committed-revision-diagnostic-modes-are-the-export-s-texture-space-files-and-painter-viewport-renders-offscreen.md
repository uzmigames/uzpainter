# 148. Captures read the committed revision; diagnostic modes are the export's texture-space files, and painter_viewport renders offscreen

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.2_preview-capture, phase2.3_realtime-preview, phase2.6_mcp-typed-tool-families, phase1.15_compositor-colour-fits, phase1.18_export-engine, phase3.7_path-tracer

## Context

Task `phase2.2_preview-capture` implements `display.capture(path, mode, camera, size, samples, seed, preset)` of `docs/architecture/07-preview-and-render-parity.md` §5. Its acceptance says the diagnostic captures (`base_color`, `channel:roughness`, `mask:<uid>`) "equal the corresponding channel exports in decoded values", and its spec scenario runs `channel:roughness` "at the set resolution". The task does not say whether the diagnostic modes are screen-space renders or texture-space maps, which stack they read, what the receipt's fields hold, or how the `painter_viewport` capture reaches a GPU from `UzPainter.exe run`.

Facts on main:

- `painter_viewport` (decision 134) is a deterministic compute pass: one sample per pixel, perspective rays from an eye and a basis, RGBA16F linear and RGBA16 display codes from the calibrated table. Its only display configuration is OCIO with Painter's substance config and `Default - sRGB`; anything else fails before GPU work with `unsupported_configuration ... (decision 038)`. It is a preview, never parity evidence.
- Every project UzPainter creates is Legacy colour-managed (OCIO creation waits on phase1.15). Under OCIO the evaluator refuses every fill source, uniform colours included (phase1.15), and the export refuses the project (phase1.18). Today `painter_viewport` therefore renders only OCIO projects whose stacks have no fill source, and the export and its diagnostics run only on Legacy projects.
- The Python API evaluates on a CPU evaluator (decision 111). The export and the views of decision 136 read the committed revision and refuse inside an open native Transaction. `materialMask/<uid>` is an export `diagnosticMap` source.
- The render standard's `base_color` comparison pass is Painter's screen-space viewport "Base color / Single channel" display.
- `UzPainter.exe run --gpu-backend` creates no device until the first GPU operation (decision 111); the worker owns one engine.

### Model panel, one round (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5)

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1. Diagnostic modes are texture-space files of one stack, made by the export engine | PARTLY: add `stack`; omitted options valid, given inapplicable ones refused; compare PNG with PNG and EXR with EXR; the screen-space Base-color pass stays a separate unmet requirement | PARTLY: pin the comparison's parameters; refuse inside a Transaction; Legacy-only today | PARTLY: `stack` and the refusals are a design choice to record; Legacy-only today |
| C2. `painter_viewport`: CPU evaluation of the committed revision, the preview's scene, the pass offscreen on the process's GPU | PARTLY: state the synchronisation (upload barriers, readback completion); check the display configuration before the device; declare the dropped alpha; OCIO without fill sources only | PARTLY: define the scene builder here; a typed GPU error | PARTLY: keep an explicit readiness step; scope the claim to supported configurations |
| C3. Camera, samples, seed | PARTLY: vertical field of view is UzPainter's convention, not measured; samples default 1; seed is not operative | PARTLY: record the field-of-view assumption | PARTLY: say it is an assumption |
| C4. `painter_iray` refuses first with `PathTracerUnavailable`; the other modes leave release-gap | PARTLY: after argument binding, before the body; pending-evidence only in the supported domains | AGREE | AGREE |
| C5. The receipt | PARTLY: hash the resolved render state; name the source, padding and encodings; adapter and driver null on the CPU | PARTLY: an explicit encoding field; adapter null too; spell the hash keys | PARTLY: keep every task field |
| C6. The adapter shim and item 3.6 | PARTLY: keep the success path open, owned by phase1.15 and phase1.18 | AGREE | PARTLY: name both owners |
| C7. The worker's `capture` tool | PARTLY: GPU by mode; `painter_iray` before the path check; define `texture_set`/`stack`; contain every written file in the root | PARTLY: GPU by mode; conflicting selectors; return the file paths | AGREE |
| C8. An unsupported configuration raises `UnsupportedInUzPainter` | AGREE | AGREE | AGREE |

Every PARTLY point is adopted below, except a typed GPU-unavailable Python class (one vote): the refusal stays `RuntimeError` with the render layer's `gpu_backend_unavailable {backend, reason}` text, and the worker returns the `gpu_backend_unavailable` code as every GPU tool does. GPT's request to refuse non-square captures with a camera record until Painter's field-of-view orientation is measured was outvoted: the viewport is never parity evidence, and the assumption is recorded.

## Decision

1. **Reading.** Every capture reads the committed revision once, refusing inside an open native Transaction (`RuntimeError`), and evaluates it synchronously. The receipt names that revision.
2. **`painter_iray`** raises `uzpainter.exception.PathTracerUnavailable`, a `NotYetSupported`, as the first step after the arguments are bound: before any argument check, project read, evaluation, device or file. In the worker it also comes before the path check. The capability manifest keeps the context `mode:painter_iray` as `release-gap`.
3. **Diagnostic modes** (`base_color`, `channel:<name>`, `mask:<uid>`) are texture-space captures of one stack, at its texture set's resolution, made by the export engine.
   - The source is a one-file plan: `documentMap baseColor`, `documentMap <name>` with the export's map names, or `diagnosticMap materialMask/<uid>`. It is compiled (`CompilePlan`) and encoded in memory (`EncodeExport`) with padding `passthrough`, as a 16-bit PNG at `path` and a 32-bit float OpenEXR at `<stem>.exr`. A three-component source is written RGB, a one-component source L. Each file equals the export of that source with the same format, bit depth and padding.
   - The stack is the `stack` argument (Python: a `Stack` handle; worker: `texture_set` and `stack` names), else the active stack. `mask:<uid>` takes its node's stack, and giving a stack raises `ValueError`.
   - An omitted option is the mode's default. A given `camera`, `preset`, `samples` or `seed`, or a `size` other than the set's resolution, raises `ValueError`, since resampling would break the equality.
   - They run where the export runs, which today means Legacy projects. The render standard's screen-space Base-color viewport pass is not one of these modes, and nothing here claims it.
4. **`painter_viewport`** evaluates base colour, metalness, roughness and the combined Normal_OpenGL map of every texture set's first stack on a CPU evaluator with the export's inputs.
   - It builds the scene with the preview window's own builder, `preview::SceneOf` (`src/preview/scene.cpp`). The display state is the project's, or `preset` (a standard preset's name or a whole preset) applied to an in-memory copy that is never committed.
   - The display configuration, the mesh and the environment are checked before any evaluation or device.
   - It renders offscreen on the process's GPU: the worker's own engine in the worker, or a device of `run`'s `--gpu-backend` created for the call. Without a device it raises `RuntimeError` with the render layer's `gpu_backend_unavailable {backend, reason}` text.
   - Readiness and synchronisation: the pass uploads every buffer, places copy-to-shader-resource barriers before its one dispatch, and waits for the submission. Its two targets are read back through `TextureReadback`, whose completion is awaited before any file is written.
   - It writes `path` (16-bit RGB PNG of the display codes) and `<stem>.exr` (RGB binary16 of the linear colour). Alpha is always 1 and is not written.
   - It renders today only OCIO projects with no fill sources (phase1.15, phase1.18).
5. **Camera and sampling.**
   - `camera` is a Painter camera record, validated as the display API does. Right, up and forward are `R·x`, `R·y` and `-R·z` with `R = Rx @ Ry @ Rz`, in Painter's Y-up scene space.
   - `field_of_view` is used as the vertical angle. This is UzPainter's convention, not a measured Painter fact: square captures, such as the standard's 1200 × 1200, are unaffected.
   - The default camera is the display state's default camera, else the preview's fit camera (`FitCamera`).
   - An orthographic camera raises `NotYetSupported`, because the pass casts perspective rays only. Its owner is the parent task, phase2.3_realtime-preview.
   - `size` is required. `samples` is absent or 1, and the receipt records 1, never the preset's Iray 256. `seed` is recorded and is not operative.
6. **Unsupported display configuration.** It raises `UnsupportedInUzPainter` (symbol `uzpainter.render.capture`, reason decision 134's `unsupported_configuration: ...`), and only for `painter_viewport`.
7. **Receipt** `uzpainter/capture-receipt/1`, written as `<stem>.receipt.json` and returned with `files` {png, exr, receipt}. Every field is always present.
   - `{schema, revision, project_uuid, evaluator_profile` (the manifest's), `mode`.
   - `render_state_digest`: the SHA-256 of the canonical JSON of the resolved render state.
     - `painter_viewport`: the environment's SHA-256, rotation and exposure, the linear background, the camera record and pose, size, samples, seed, shader and display configuration.
     - Diagnostic modes: the source, size and encoding.
   - `source` (diagnostic: `{type, name, texture_set, stack, root_path}`; viewport: null), `encoding` (each file's bit depth and layout; padding for diagnostic modes).
   - `backend` (`dx12` | `vulkan`; `cpu` for diagnostic modes), `adapter` and `driver` (DXGI user-mode version; both null on the CPU).
   - `samples`, `seed`, `camera` (null for diagnostic modes), `size`, `display_configuration` (`{mode, config_sha256, view}`; null for diagnostic modes).
   - `hashes` `{png, exr}`: the SHA-256 of the bytes written.
8. **Adapter shim.** `_substance_painter.display.save_viewport(path, w, h, _)` calls `capture(path, "painter_viewport", size=(w, h))` and no longer rewrites its errors.
   - On the Legacy wand project, the pipeline's `capture` subcommand reaches the capture and fails with `UnsupportedInUzPainter ... unsupported_configuration`. This happens before any evaluation or device, writes nothing and leaves the revision unchanged.
   - The same shim, run through `UzPainter.exe run runner.py`, writes the PNG on the OCIO fixture. That fixture is opened natively in the call, because the facade, and so the adapter's session restore, refuses OCIO projects until phase1.15.
   - The pipeline subcommand's success path is a recorded scope split owned by phase1.15_compositor-colour-fits (OCIO creation, the facade's OCIO profile and fill evaluation) and phase1.18_export-engine (OCIO export).
9. **Worker tool** `capture {mode, path, camera?, size?, samples?, seed?, preset?, texture_set?, stack?}`.
   - It is non-mutating and listed `gpu: true`. Only `painter_viewport` checks the device: a missing device gives `gpu_backend_unavailable`, so the CPU modes run without one.
   - `path` must lie inside `--output-root`, and a relative path is taken under it. The OpenEXR and the receipt are its siblings in the same folder.
   - `texture_set` and `stack` apply to `base_color` and `channel:<name>` only; elsewhere they are `invalid_arguments`. The tool returns the receipt.
   - Refusals keep the API's classes: `call_failed` with `details.type` `PathTracerUnavailable`, `UnsupportedInUzPainter`, `ValueError`, and so on.
10. **Capabilities.** Decision 112 gives a `pending-evidence` entry the context `any`. So the four contexts `mode:painter_viewport`, `mode:base_color`, `mode:channel` and `mode:mask` become one `uzpainter.render.capture` entry, context `any`, `pending-evidence`, whose notes name each mode's supported domain (OCIO without fill sources; Legacy) and the orthographic gap. `mode:painter_iray` stays `release-gap`, and the conformance test calls it. `uzpainter.exception.PathTracerUnavailable` is listed.

## Alternatives Considered

- Diagnostic modes as screen-space unlit renders (rejected: a screen-space image cannot equal a channel export in decoded values, which the task's acceptance requires; the standard's screen-space Base-color pass is a parity pass outside §5's diagnostic captures)
- A capture on the GPU evaluator (rejected: the Python API evaluates on the CPU, decision 111, and the export-equality of diagnostic modes comes from the export's own entry points)
- Accepting `seed` or `samples` other than 1 for `painter_viewport` silently (rejected: the pass is deterministic and renders one sample per pixel)

## Consequences

- No Painter recording is needed: captures are UzPainter-only, `painter_viewport` is never parity evidence, and the diagnostic modes equal UzPainter's own export.
- The task's tests run diagnostic modes on Legacy projects and `painter_viewport` on a hand-written OCIO bundle without fill sources. A freshness check of `painter_viewport` therefore mutates the display state (camera, environment rotation). Material changes are checked on the diagnostic modes.
- Open: the screen-space Base-color viewport pass of the render standard has no owner in this task; the owner should assign it.
