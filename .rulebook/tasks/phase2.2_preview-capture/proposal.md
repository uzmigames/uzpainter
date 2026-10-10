# Proposal: phase2.2_preview-capture

## Why
Child of `phase2.3_realtime-preview` (P2-PREVIEW in `docs/dag.md`), implementing capture of D6 (`docs/architecture/07-preview-and-render-parity.md` §1, §5; decision 018). Agents and the paint gates need headless captures that reflect the latest state with explicit camera and resolution, in lit preview and diagnostic modes, and that never depend on a window; `painter_iray` must be an explicit unavailable capability until the path tracer passes. Requirements: VIS-02, VIS-03, QG-01, INT-07, NFR-01, ARC-11 (`docs/prd.md`).

## What Changes
- `uzpainter.render.capture(path, mode, camera, size, samples, seed, preset)` (the `display.capture` of `07-…` §5) with modes `painter_viewport`, `base_color`, `channel:<name>` and `mask:<uid>`; mode `painter_iray` fails with an explicit unavailable-capability error (`PathTracerUnavailable`, listed as a release gap in the capability manifest) before any work until `phase3.7_path-tracer` passes.
- Capture steps: wait for evaluation of the current revision and all resource uploads; render to an offscreen target without swapchain or window (RGBA16F for `painter_viewport`); apply the display transform; read back through `TextureReadback`; write PNG (and EXR for the linear buffer); write the receipt `{revision, evaluator_profile, render_state_digest, mode, backend, adapter, driver, samples, seed, camera, size, display_configuration, hashes}`.
- Diagnostic captures (unlit BaseColor, single channel, mask/ID) as direct channel visualisations, exact like channel exports.
- The pipeline adapter's `save_viewport` shim served by `capture(mode=painter_viewport)`, always on the current state (`docs/architecture/10-python-api.md` §2).
- The worker's capture command handler on the IPC vocabulary, so the MCP `capture` tool of `phase2.6_mcp-typed-tool-families` becomes available when this lands.

## Dependencies
- Parent: `phase2.3_realtime-preview`.
- Prerequisites: `phase1.25_pilot-wand` (DAG input of P2-PREVIEW), `phase2.1_preview-viewport-window` (pass and display transform), `phase2.1_preview-display-presets` (preset and camera arguments).

## Acceptance
- Captures run with no window, no desktop focus and no swapchain, and their receipts are complete.
- A capture taken after a mutation reports the new revision and shows the new state.
- Diagnostic captures equal the corresponding channel exports in decoded values.
- `painter_iray` fails explicitly before any work.

## Impact
- Affected specs: `preview` (capture)
- Affected code: render capture path, receipts, worker command handler, pipeline adapter shim
- Breaking change: NO
- User benefit: cheap, truthful visual evidence for agents and paint gates
