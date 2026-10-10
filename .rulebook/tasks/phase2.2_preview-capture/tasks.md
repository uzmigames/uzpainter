## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand, phase2.1_preview-viewport-window, phase2.1_preview-display-presets

## 2. Implementation
- [ ] 2.1 Capture entry point with modes `painter_viewport`, `base_color`, `channel:<name>`, `mask:<uid>` and explicit camera, size, samples, seed and preset
- [ ] 2.2 Readiness: wait for evaluation of the current revision and all resource uploads before rendering
- [ ] 2.3 Offscreen rendering without swapchain or window; display transform; readback through `TextureReadback`; PNG and EXR writers
- [ ] 2.4 Capture receipt with every field of `07-…` §5
- [ ] 2.5 Diagnostic modes as direct channel visualisations
- [ ] 2.6 `painter_iray` mode returns `PathTracerUnavailable` before any work and is listed as a release gap
- [ ] 2.7 Pipeline adapter `save_viewport` shim routed to `capture(mode=painter_viewport)`
- [ ] 2.8 Worker capture command handler on the IPC vocabulary for the MCP `capture` tool

## 3. Tests
- [ ] 3.1 Headless capture in a local run on the owner's machine (decision 028) with no window, no desktop focus and no swapchain
- [ ] 3.2 Freshness: mutate, capture, and check the receipt revision and the changed pixels
- [ ] 3.3 Receipt schema test covering every field
- [ ] 3.4 Diagnostic captures (`base_color`, `channel:roughness`, `mask:<uid>`) equal the corresponding channel exports in decoded values
- [ ] 3.5 `painter_iray` capture fails with `PathTracerUnavailable` before any work
- [ ] 3.6 Pipeline adapter shim test through `UzPainter.exe run` with the pipeline's capture subcommand

## 4. Acceptance
- [ ] 4.1 Every §3 test green; results attached to `phase2.3_realtime-preview`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
