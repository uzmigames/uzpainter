# 162. The preview gate runs on the wand with named scope splits, settles "no wait" structurally, and reports per case and backend

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.3_realtime-preview, phase2.1_preview-viewport-window, phase2.2_preview-capture, phase1.15_compositor-colour-fits, phase1.25_pilot-wand, phase2.6_mcp-typed-tool-families, phase3.1_vulkan-compute-parity

## Context

phase2.3_realtime-preview is the parent of the preview subsystem. Its items ask for:

- 2.1: an integration scenario on the wand v1 with the preview window attached, running evaluation, export and captures in every Phase 2 mode;
- 2.2: a writer for `parity/reports/phase2/preview-settling.json`;
- 3.1: window-independent captures;
- 3.2: the wand export with the window open, minimised and stalled, its "export bytes and timing unaffected";
- 3.3: `painter_iray` listed as unavailable in `uzpainter://capabilities` and by `capture`;
- 4.1: the DAG gate.

Facts on main:

- `painter_viewport` renders only the pinned OCIO configuration. Every project UzPainter creates is Legacy until phase1.15, so the wand is refused (`unsupported_configuration`, decision 038), and the attached window shows that refusal instead of drawing.
- The wand's own export uses `infinite` padding, whose UV-island case is a gap (`padding-islands`, phase1.25 item 2.7). With `passthrough` padding, its four document maps (BaseColor, Roughness, Metallic, Height) export. Its Normal map, a virtualMap, is refused, because a virtualMap outside the UV islands under `passthrough` is unrecorded (R-090, decision 090).
- `uzpainter://capabilities` is phase2.6 item 2.9, not started. The manifest it will publish ships with the exe.
- No Vulkan device exists (decision 121).

### Model panel, one round (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5)

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| A1. 2.1 on the wand with `passthrough` padding; `painter_viewport` refused on the wand and rendered on the OCIO fixture in the same worker; scope split named | PARTLY: partial acceptance with explicit deferred cases | PARTLY: the wand never exercises one mode; re-run the wand scenario when OCIO lands | PARTLY: the wand preview never draws |
| A2. "Timing unaffected" settled by the stall, timings recorded without a threshold | PARTLY: keep the structural proof and the non-gating timings separate | PARTLY: the stall covers the held case only; record the metric | AGREE |
| A3. 3.3 on the manifest, `run` and the worker; the resource is phase2.6's | PARTLY: the resource remains unmet | AGREE: phase2.6 must test that the resource publishes the manifest verbatim | PARTLY: same gap |
| A4. The report: decision 150's structure | AGREE: keep missing cases visible and name the build | AGREE | AGREE |
| A5. 4.1 checked on a full DX12 run with named splits | PARTLY: the gate is not met through splits alone | PARTLY: make the gate conditional on the splits closing | AGREE |

## Decision

1. **Integration (2.1).** `tests/preview/test_preview_settling.py` rebuilds the wand v1 once through the pipeline adapter (`create` and `sync`). Each worker opens its own copy of the saved project.
   - Run time: one export of the wand on the Debug worker's CPU evaluator took 7.5 minutes, 6.6 of them its BaseColor (measured 2026-10-12). The scenarios run three exports and three captures, about 30 minutes, beyond an agent's 10-minute budget, so the full run belongs to the coordinator's batch. A lower resolution is no shortcut: the wand's sRGB bitmap is evaluated only at 1:1 (decision 145), so BaseColor is refused below 2048 px.
   - `UZP_PREVIEW_WAND_QUICK=1` leaves BaseColor out of the export and the captures, to check the scenarios in a few minutes. A quick run is never settling evidence: the fixture refuses it when `UZP_PREVIEW_SETTLING_REPORT` is set.
   - A worker without a preview gives the baseline. A DX12 worker with `--preview` must then give the same results:
     - the GPU evaluation of the five wand channels, and the pipeline's export (`painter_export.py`'s configuration, 16-bit PNG, 2048 px), both with the baseline's bytes;
     - `base_color` and `channel:roughness` captures with the decoded values of the maps exported in the same worker, and the gem group's `mask:<uid>` capture.
   - `painter_viewport` must be refused on the wand with `unsupported_configuration: Legacy ... decision 038`, and the window shows the same refusal. The assertion's message names phase1.15, so the test fails, and must be extended, once the wand is no longer Legacy.
   - `painter_iray` is refused before any work.
   - The same worker then opens the OCIO fixture. The window draws it (`frames_rendered`, `revision_shown`), and a `painter_viewport` capture renders it.
   - While `export-processing.json` lists `padding-islands` as a gap, the export uses `passthrough` padding and leaves out the Normal map, which that padding refuses. Once the entry is fitted, it uses `infinite` (the pipeline's own padding) with all five maps.
   - Item 2.1 stays **open**: the wand is not rendered by `painter_viewport` or the window until phase1.15_compositor-colour-fits (OCIO creation and fill evaluation under OCIO), and the pipeline's own padding, with its Normal map, waits for phase1.25 item 2.7.
2. **No wait on the preview (3.2).** The proof is structural. With the preview thread held by the stall hook while it holds its frame, the evaluations and the export run to the end: nothing waits on the preview thread. `frames_taken` stays frozen while `frames_published` grows, and the export with the window open (integration test) and the export with the window minimised and the preview stalled both have the baseline's bytes.
   - The export times are recorded in the report as metrics: baseline, window open, and minimised and stalled. They carry no threshold, since no budget is specified. They are evidence, not a gate.
   - GPU contention from a drawing window during the wand export is not measured, because the window cannot draw the wand before phase1.15.
3. **`painter_iray` (3.3).** The manifest that `UzPainter.exe capabilities` prints lists `uzpainter.render.capture` `mode:painter_iray` as `release-gap`, naming P3-PATHTRACER and `PathTracerUnavailable`. The worker's `capture` refuses it before any work (on the wand), and so does `uzpainter.render.capture` (phase2.2's test).
   - Publication through the MCP resource `uzpainter://capabilities` is phase2.6 item 2.9's. Its gap test (3.5) must include this entry and check that the resource publishes the shipped manifest unchanged.
   - Item 3.3 stays open until then.
4. **Report** `parity/reports/phase2/preview-settling.json`, schema `uzpainter/preview-settling/1` (`tools/parity/settling/preview.py`). It follows decision 150's structure.
   - The schema is closed. Entries are keyed by case and backend. Each `pass` or `fail` carries its date, the exe's SHA-256, its seconds and its metrics.
   - The GPU cases list `dx12` and `vulkan`. On Vulkan they are `pending` with decision 121 until a device exists. The diagnostic captures and `painter_iray` never touch a device, so their backend is `cpu`, as their receipts say.
   - A case that has not run is `not_run`. A case settled by several tests passes only if all of them pass.
   - Tests carry `@pytest.mark.preview_settling(<case>)`, and the children's tests are tagged, not copied. A run under `UZP_PREVIEW_SETTLING_REPORT=<path>` merges into the report. The repository guard validates the file.
5. **Gate (4.1).** It stays open until the splits close: the wand renders in `painter_viewport` and the window (phase1.15), the Vulkan entries pass (decision 121), and `uzpainter://capabilities` is published (phase2.6). The task is not archived before then, and its prerequisites (the children, waiting on phase1.25's acceptance) are open anyway.

## Alternatives Considered

- **A wall-clock threshold for "timing unaffected".** Rejected: no budget is specified, and a ratio on one machine's timings would be a tolerance on a noisy measure. The stall proves the absence of a wait, and the times are kept as evidence.
- **Making the wand OCIO by patching its bundle, as the OCIO fixture is made.** Rejected: the evaluator refuses every fill source under OCIO (phase1.15), and the wand is 13 fills.
- **Checking 2.1, 3.3 and 4.1 as recorded scope splits.** Rejected by the panel (PARTLY ×2 on A1, A3 and A5): the deferred parts are what those items claim.

## Consequences

- phase2.3 items 2.2 and 3.1 are checkable from one local DX12 run. Item 3.2 waits for the coordinator's batch run of the wand scenarios. Items 2.1, 3.3 and 4.1 stay open, each with its owner named.
- The wand integration test fails, by design, when the wand stops being Legacy. Its owner then extends it to render the wand.
