# 248. The attached preview evaluates every committed revision on its own thread and device, and clears when the project closes

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.1_preview-viewport-window, phase2.3_realtime-preview

## Context

The practical end-to-end report (`parity/reports/phase2/practical-e2e.md`) found three preview problems.

- **B7 (Medium).** The preview attached to an MCP session (`--mcp --preview`) showed nothing after `project_open` or after edits until an `evaluate_channel` call. It then showed only the evaluated channels (BaseColor without the normal detail), and it kept showing a project after `project_close`.
- **B12 (Low).** The `ref_match` preset failed with "the project stores no environment 77eeed8d…", and nothing said which file that is or where it lives.
- **B13 (Low).** On a Legacy project the panel read "display: OCIO, Painter's substance config", and the README did not say the viewport needs OCIO.

The cause of B7 is in the worker, not in the window. The worker published to the preview's feed only inside `evaluate_channel`, and only that call's slot. Nothing was published on open, on a commit or on close. The feed kept every slot across revisions and never cleared.

The fix must hold the preview's governing requirements: the preview never pauses evaluation, and export bytes and timing are unaffected by it (phase2.3_realtime-preview). One GPU `evaluate_channel` takes 0.7–5.5 s at 2048², and a mutation takes 0.02–0.06 s.

The model panel's votes (one round):

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 B7's cause is the publish point: only `evaluate_channel`, one slot at a time, and never on open, commit or close; the feed never clears | AGREE | AGREE | AGREE |
| C2 After every change of what the session holds, the worker hands the committed revision to a preview evaluation thread with its own device and evaluator. That thread evaluates the four slots of every texture set and publishes one complete frame. Newest wins. Close publishes a frame without a project. `evaluate_channel` no longer publishes | PARTLY | AGREE | AGREE |
| C3 Evaluating synchronously on the worker's request thread after each commit is rejected | AGREE | AGREE | AGREE |
| C4 Evaluating on the window's own device or thread is rejected | PARTLY | AGREE | AGREE |
| C5 The evaluation thread reads resources through an access object the worker revokes inside the close, waiting at most for one read in flight | PARTLY | PARTLY | PARTLY |
| C6 A refused display configuration is published without evaluating, and a failed evaluation is shown as text, never as a silently defaulted map | AGREE | AGREE | AGREE |
| C7 B12: refuse clearly and name the file instead of shipping it | AGREE | AGREE | AGREE |
| C8 B13: the panel, `preview_status` and the standalone report name the real display configuration; one README line | AGREE | AGREE | AGREE |

Refinements adopted:

- **C5, all three models.** The evaluation thread never holds the open project itself. Each resource read takes the access's lock for that one read only. Revoking it rejects every later read, and bytes already read stay usable. The GPU work runs on bytes already fetched. So revoking waits at most for one blob read, never for an evaluation.
- **C2 (GPT, Grok) and Kimi's coalescing note.** One thread is the only publisher: the close is handed to it like any other change, in order. One slot holds the pending revision, and a newer one replaces it before it starts. Staleness is checked between evaluations and again just before publishing, so a closed project's late result is never shown after the empty frame.
- **C2 (GPT): the third device isolates ownership, not the hardware.** The preview's evaluation still shares the GPU and the CPU with the worker. Nothing is evaluated once the window has been closed. Export times with and without the preview stay settling metrics with no threshold (decision 162).
- **C4 (GPT).** Sharing the window's device without blocking would need an asynchronous render loop. The window loop renders synchronously (decision 227), so a separate device is the smaller change.
- **Kimi.** A device that cannot be created only shows as the failed evaluation in the window. The worker is not affected.

## Decision

1. **The attached preview evaluates the committed revision itself** (`src/preview/evaluation.{h,cpp}`, `AttachedEvaluation`).
   - The worker hands it every change of what the session holds, from `python::Session::on_durable_change`: create, open, a rebuild from a recipe, every committed call, `save_as` and close.
   - Its thread has its own `render::Engine` and `evaluator::Evaluator`. It evaluates the newest revision with `EvaluateFrame`, the evaluation the standalone `--preview` shares. That is the base colour, metalness and roughness of every texture set's first stack, and its combined Normal_OpenGL map.
   - It is the feed's only publisher. `evaluate_channel` publishes nothing.
   - The worker hands the change to the preview before it sends the supervisor its revision event.
2. **A closed project clears the window.** A frame without a project shows "no project is open". `revision_shown` is then -1 and `maps_shown` is empty; that state is not an error.
3. **Store access.**
   - The evaluation thread reads the project's resources through a `StoreAccess`, which holds the open project.
   - When the project closes, or another one opens, the worker's thread revokes the access inside that change and drops the last reference itself.
   - So the store, its lock sidecar and an untitled project's folder are released before the call that closed the project returns.
4. **Frames are whole or refused.**
   - `PreviewFeed::Update` starts a revision's frame and drops the previous one's maps.
   - A failed evaluation is recorded in the frame (`evaluationError`). The window shows it in place of the image.
   - A project whose display configuration the viewport refuses (decision 038) is published without evaluating. The window shows the refusal.
   - `preview_status` returns `maps_shown`, the `<texture set>/<slot>` maps of the image shown.
5. **`Session::Rebuild` now notifies after the rebuilt project becomes the open one, as `Create` does.**
   - Before, its only notification came from inside the transaction's record, while no project was open yet.
   - So neither the supervisor nor the preview learned of the rebuilt project until its next commit.
6. **B12: refuse, name, do not ship.**
   - When a standard preset's environment is missing, the refusal names the file, where it lives and how to import it.
     - `ref_match`: the render standard's `HDRI/TOS-RefMatch-Skeletal-Mage.exr`, beside `Render-Comparison-Standard.json` in Assets3D's `Pipeline/render`.
     - `common`: Painter's "Studio White Soft", an Adobe asset.
     - Import: MCP `resource_import {path, usage: ENVIRONMENT}`, or Python `resource.import_project_resource(path, Usage.ENVIRONMENT)`.
   - The `capture` tool's `preset` description says the same.
   - The file stays in Assets3D (decision 046). Its redistribution licence is not established, so shipping it would need the owner.
7. **B13: label the real configuration.**
   - The panel's display line is `DisplayLabel(DisplayOf(project))`. On a Legacy project it reads "Legacy colour management with tone mapping Linear: not displayed, the viewport needs OCIO with Painter's substance config and the view 'Default - sRGB' (decision 038)".
   - `preview_status` and the standalone report return the line as `display`.
   - The README's preview row says the viewport and its captures need an OCIO project.

## Consequences

- `tests/preview/test_preview_window.py::test_the_attached_preview_shows_the_committed_revision` covers B7 with no `evaluate_channel`, on the OCIO fixture:
  - after `project_open`, after a committed edit and after a rebuild from the recipe, the window shows that revision with its four maps;
  - the supervisor's last revision event names the rebuilt project;
  - after `project_close` the window shows that no project is open.
- `test_the_previews_evaluation_never_delays_or_changes_the_workers_results` covers the preview's own evaluation on the OCIO fixture. A Legacy project is published without being evaluated, so the stall and lifecycle tests never run it.
  - The worker evaluates while the preview evaluates the opened revision.
  - The Debug hook `test_fault preview_evaluation_stall` then holds the preview's thread inside its evaluation of the next revision. Meanwhile the worker commits again, evaluates and exports.
  - Every result and revision equals a worker's without a preview. The held revision, superseded meanwhile, is never published; the newest one is, with its four maps.
- `test_standalone_preview_opens_and_closes` checks the Legacy display line (B13). The `display` case of `uzp-preview-tests` checks every label.
- `tests/python/test_display_presets.py::test_missing_environment_fails_without_substitute` checks that the refusal names both presets' files (B12).
- The wand is an OCIO project since decision 207. `test_wand_v1_with_the_preview_attached` no longer expects the decision-038 refusal: the window draws the wand with its four maps, `painter_viewport` renders it (left out of a quick run), and after `project_close` the same worker draws and renders the OCIO fixture.
- The stall tests now commit while the preview is stalled. Publication follows commits, not calls: the wand stalled test adds one fill layer after its export, and compares the revision before it with the baseline.
- Decision 227's test sampler checks `DwmFlush` and the screen BitBlt. When the input desktop is not `Default` (a locked workstation), it skips and says why. A complete frame now needs:
  - no black row in the view;
  - the panel's background colour over most of the panel;
  - the text of both panel boxes.
