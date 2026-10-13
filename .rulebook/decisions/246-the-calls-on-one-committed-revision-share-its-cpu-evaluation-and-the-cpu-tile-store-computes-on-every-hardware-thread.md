# 246. The calls on one committed revision share its CPU evaluation, and the CPU tile store computes on every hardware thread

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.2_preview-capture, phase2.1_recipe-diagnostic-views, phase2.4_supervisor-worker

## Context

The practical end-to-end run found B19 (`parity/reports/phase2/practical-e2e.md`): every export evaluated the whole stack again (9-12 s per 2048 x 2048 four-map export, about 1 min at 8192 x 8192), the Assets3D adapter's viewport capture took 47 s, and `material_views` and `region_stats` took 8-19 s.

Measured with scoped timers in the worker (ReleaseSafe, as the report's build; Ryzen 9 7950X3D, 16 cores / 32 threads; the machine was shared with other agents, so the timings are indicative):

- **The e2e stack** (uniform base + a group with a 2048 x 2048 bitmap fill, Multiply 0.8, a 16-bit bitmap mask and a Levels effect), four-map PNG16 export, 13-15 s: CPU evaluation 11-12.3 s (82 %; blend 6.3 s over 36 tile operations, projection 3.6 s over 8, levels 1.8 s over 4), encoding 2.2 s (deflate 1.2 s), padding 0.13 s (`passthrough`) or 6.0 s (`infinite`), mesh re-derivation 0.03 s, templates 0.005 s, bitmap decode 0.2 s, UV coverage 0.04 s, file writes under 0.1 s. A second export of the same revision cost the same: every call built a new `CpuEvaluator`, decoded the bitmaps and re-derived the mesh again.
- **The Wand** (13 layers, 14 masks, 2048 x 2048): the adapter runs every step as its own `UzPainter.exe run` process. Four-map export 54.8 s, of which evaluation 50.7 s (blend 32.9 s over 272 tile operations, projection 15.6 s over 68) and encoding 1.9 s. The viewport capture evaluates BaseColor, Metalness, Roughness and the combined Normal the same way.
- **Build mode**: ReleaseFast (the documented release build) gives the Wand export in 45.1 s (evaluation 42.1 s), with the same bytes. The build mode is not the cause.
- Every CPU tile operation ran its 1024 x 1024 texels on one thread.

So B19 has two causes: no call reused another call's evaluation of the same revision, and the evaluation itself used one of the machine's 32 hardware threads.

## Decision

**A. One evaluation per committed revision** (`src/python/evaluation.{h,cpp}`). The open project keeps the CPU evaluation of one committed revision: the templates, the store's decoded bitmaps, the mesh re-derived from its bytes and the tile cache. Export jobs, texture-space and `painter_viewport` captures and diagnostics lease it.

- **Key.** The open project (its store), the revision's own `core::Project` object and the calling thread's MXCSR control bits. Everything else the evaluation reads is fixed by the revision: the bitmaps and the mesh come from the store by SHA-256 and are checked against it, the templates are installed files, the admission limits are constants, and the evaluator never reads display state, so the viewport capture evaluates the revision itself and applies its preset to the scene only.
- **Lifetime.** At most one revision is kept. A call on the current revision replaces an evaluation of another revision, every commit drops the evaluation it superseded, and `close` drops it. A call on an older revision, or one that finds the evaluation leased by another call, evaluates privately, as every call did before.
- **Kept only when clean.** A tile is cached when it is allocated, before the operation that fills it runs. The lease drops the evaluation if any tile was allocated after the call's last success; a refusal raised before any allocation keeps it. The other kept state cannot be left half-made: a bitmap is cached only once decoded, a geometry raster only once rasterised, a mip chain is rebuilt when empty, and the templates are immutable.
- **Kept only when affordable.** It is dropped when its tiles would take more memory than the machine still has available when the call ends.
- **Not on the commit's time.** A commit hands the superseded evaluation to a thread of its own to release: releasing a 2048 x 2048 stack's tiles took 0.6 s on the committing call.

**B. The CPU tile store computes on every hardware thread** (`src/evaluator/cpu_store.cpp`). Upload, projection, blend, levels and the virtual normal split their texels into contiguous ranges, one per hardware thread, the calling thread taking the first. Every texel is computed by the same code from the same inputs and written by exactly one thread, so the result is the single-threaded one bit for bit. Each worker first takes the caller's MXCSR. An exception is rethrown after every range ended: the one of the first range that threw, which holds the first texel whose computation throws, as the single-threaded loop threw it. Region statistics and other reductions are outside the store and unchanged.

## Model panel

One round on five claims (`cx/gpt-6-astra`, `kimi/kimi-k3`, `xai/grok-4.5`):

1. The key covers everything that affects the evaluation: PARTLY x3. Cx and xai named the floating-point control state; it is now part of the key. Kimi asked for the display preset and the resolution to be checked: no evaluator or export source reads `display`, and the resolution is part of the revision (and of every subtree hash).
2. Dropping only after an allocation since the last success is sufficient: AGREE x2, PARTLY (xai: state other than tiles). Audited as above.
3. B is in scope: AGREE (cx), PARTLY (kimi: in scope, but its own commit behind its own byte-equality gate), DISAGREE (xai: the brief's fix is A; B is its own change). Decided by majority: B is in scope, and it lands as its own commit with its own byte-equality evidence.
4. B is byte-identical: PARTLY x3 (audit reductions, neighbour reads, exceptions; gate on goldens). Every store operation writes only its own texel from inputs no range writes; the neighbour reads of the virtual normal read other tiles. Exceptions keep their single-threaded order. The gate is below.
5. Keeping one revision is an acceptable memory trade-off: AGREE (xai), PARTLY x2 (cx, kimi: a cap or memory-pressure rule). The affordability rule and the off-thread release were added.

## Evidence

Same machine, shared with other agents, ReleaseSafe builds of main `170028e` (before), A, and A + B:

| Call (e2e Legacy session, 2048 x 2048) | Before | A | A + B |
|---|---|---|---|
| export PNG16 (first on the revision) | 19.3 s | 14.6 s | 5.0 s |
| export PNG16 again (same revision) | 18.9 s | 2.7 s | 2.7 s |
| export PNG8 / EXR 32f | 14.8 / 14.0 s | 2.4 / 1.4 s | 2.3 / 1.5 s |
| export PNG16 `infinite` (6 s of it padding) | 21.9 s | 8.3 s | 8.5 s |
| capture `base_color` / `mask:10` | 14.1 / 2.5 s | 2.9 / 1.4 s | 2.6 / 1.5 s |
| `material_views` / `region_stats` | 22.6 / 11.8 s | 12.1 / 0.4 s | 11.6 / 0.5 s |
| export after an edit (new revision), then again | 15.3, 15.0 s | 16.0, 3.0 s | 5.3, 2.8 s |
| the edit itself (`layer_set`) | 0.03 s | 0.64 s (release on the commit thread, then moved off it) | 0.07 s |

| The Wand through the adapter (one process per call) | Before | A + B |
|---|---|---|
| `painter_layer_stack.py capture` (painter_viewport, 1700 x 1250) | 65.9 s | 14.8 s |
| four-map `passthrough` PNG16 export | 57.7 s | 14.0 s |

| 8192 x 8192, a uniform fill under a 16-bit bitmap mask (the e2e scenario) | Before | A + B |
|---|---|---|
| export PNG8 (first on the revision) | 94.5 s | 46.5 s (80.0 s with GPU tests running beside it) |
| export PNG16, then EXR 32f (same revision) | 101.7 s, 69.0 s | 38.5 s, 18.2 s |
| capture `base_color` | 109.3 s | 41.7 s |
| worker memory after the calls | 167 MiB | 3.0 GiB (the kept evaluation) |

At 8192 x 8192 what remains is encoding, on one thread (profiled): building the PNG samples (the sRGB encode of BaseColor included) about 12.5 s per export, deflate 12-20 s, the OpenEXR encode 10 s, `passthrough` padding 2 s; the first export's evaluation is 14.9 s.

- **Bytes.** Every file of the 15 calls above has the same SHA-256 before, with A and with A + B (PNG16, PNG8, EXR 32f and `infinite` exports, the `base_color` and `mask:10` captures, the 11 `material_views` files, the `region_stats` JSON, the exports after the edit), and so has every file of the 8192 x 8192 scenario (12 exported files and the capture). The Wand's capture is `f22b9da6…` and its export `f5202163…`, `24171dfa…`, `9cd65935…`, `e893061d…` before and after, the e2e report's hashes.
- **Tests (A).** `tests/python/test_pyapi_native.py::test_calls_on_one_revision_reuse_its_evaluation` (same bytes, the warm exports under a third of the cold one, a refusal keeps the evaluation, a capture writes the export's BaseColor) and `::test_a_commit_supersedes_the_kept_evaluation` (after a commit the bytes are a fresh process's); the export, diagnostics, capture (CPU and GPU) and worker diagnostics tests that read these paths.
- **Tests (B).** `tests/evaluator` GPU-equals-CPU cases on random stacks, mask effects and height to normal (3 passed, on the RTX 4090). The CPU golden comparisons of every store operation, under `UZP_NO_GPU=1`: `tests/evaluator` (sources and projection, blend kernels and pass-through groups, mask effects and levels, height to normal, two-process determinism, evaluation order and cache) and `tests/export` (the written and processed goldens, the sRGB8, variant and minification files, the five-map preset's normal). 131 passed and 118 GPU variants skipped. One failed: `test_export_encoders.py::test_written_files_equal_the_dry_run_in_two_processes`, whose spec puts a colour bitmap on a one-channel channel; it is refused by decision 218 before any store operation runs, and it fails the same way in the full gate on `959b16a`, before this change. The regression tests' stack evaluates about 11 times longer than it encodes in Debug on all threads, so their "a third of the cold export" bound holds with margin.

## Review (2026-10-13)

A review of A found one defect and one overstated result. Both are fixed on the same branch.

- **A reused evaluation was never dropped.** `LeaseEvaluation` gave a call the kept evaluation by copying the open project's pointer, so the open project kept holding it while the call ran, and the end of the lease could not drop it: the clean and affordable rules held only for the call that built the evaluation. A later call that failed after allocating a tile left the tile, never filled, in the kept cache, and the next call on the revision read it. On the plane, a virtual normal export allocates its read-out tile, then refuses the Normal channel's bitmap minified at 30 degrees; repeated on the same revision it published a normal map from the unfilled tile instead of refusing. `tests/python/test_pyapi_native.py::test_a_call_that_fails_after_allocating_a_tile_drops_the_kept_evaluation` fails that way on `214d239` and passes with the fix. The lease now takes the evaluation out of the open project, as the call that builds one already did, and only the end of the lease puts it back, when the call left it clean, of the current revision and affordable. So the affordability check runs at the end of every call that held the kept evaluation.
- **`material_views` computed every view three times.** Profiled with temporary timers (a ReleaseSafe `uzp-pyapi-tests.exe`, the e2e Legacy project, material 10 and its 5 views, every tile already cached): the reply's mask and views 0.83 s (2.80 s on the first call of a revision), then the export of its 11 files 4.8 s. Of the export, 2.2 s computed each view again for its view file and again for its leaks file (`EvaluateDiagnosticOn` called `MaterialViewsOf` per file, 0.12-0.44 s each), 2.3 s was the OpenEXR 32f encoding on one thread, and 0.08 s the mask. Now `DiagnosticRun::Export` passes the views `DiagnosticRun::MaterialViews` computed to its export (`exporter::SourceInputs::materialViews`, then `evaluator::DiagnosticRequest::materialViews`), and `EvaluateDiagnosticOn` copies that material's mask, views and leaks from them. A view they do not hold is computed as before. Each file is a copy of what the computation gives: `tests/supervisor/test_worker_diagnostics.py` checks that the tool's 11 files have the SHA-256 of an export that computes every source.
- **The first call on a revision.** The timings above for `material_views` and `region_stats` are of calls made after five exports of the same revision. The first call on a revision (right after `project_open`), then the same call again, on the e2e Legacy project at 2048 x 2048, one MCP session per ReleaseSafe build, on the shared machine:

| Call | Before (`170028e`) | A + B (`214d239`) | A + B + review fixes |
|---|---|---|---|
| `material_views`, first on the revision / again | 22.8 / 21.2 s | 13.8 / 7.3 s | 6.8 / 5.0 s |
| `region_stats`, first on the revision / again | 12.7 / 12.3 s | 1.9 / 0.40 s | 2.4 / 0.41 s |

Every file (the 11 of `material_views`, the `region_stats` JSON) has the same SHA-256 in the three builds, first call and repeat. The rest of a repeated `material_views` call is the encoding and publication of its 11 OpenEXR 32f files, on one thread (Consequences).

`::test_a_capture_while_an_export_job_holds_the_evaluation_evaluates_privately` covers a call that finds the evaluation leased: a capture made while an export job holds it writes the bytes it writes from the kept evaluation once the job ended. Two of the review's test requests were not added. A forced "unaffordable" result needs a test-only hook in the module; the drop it causes takes the same branch as the failed call above, which the new test covers. The MXCSR part of the key would need the test to change the interpreter thread's floating-point control state from Python.

## Alternatives Considered

- Run exports and captures on the GPU evaluator: rejected. It would change which evaluator writes the delivered bytes.
- Key the kept evaluation on the revision number: rejected. A closed and reopened project, or another project, can have the same number.
- Key it on a content hash of the revision, so that a reopened project finds it (kimi): not taken. The evaluation lives with the open project, and a reopened project evaluates its revision once.
- Remove a failed operation's tile from the cache instead of dropping the evaluation: rejected. It needs every allocation site of the evaluator to undo its own allocation; dropping is local to the lease.

## Consequences

- An export, capture or diagnostic of a revision another call evaluated only encodes or reads what that call left; the first call on a revision still evaluates.
- The worker keeps one revision's tiles between calls (dropped on commit, on another revision, on close, or when memory is short).
- The CPU evaluator uses every hardware thread for each tile operation; two concurrent evaluations (an export job and a capture) share the cores.
- Encoding stays on one thread and is now most of a large export (above), and of a `material_views` call, whose views are computed once for its reply and its files (Review, below).
