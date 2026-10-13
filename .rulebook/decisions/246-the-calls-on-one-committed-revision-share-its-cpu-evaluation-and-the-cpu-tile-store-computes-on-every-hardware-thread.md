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

- **Bytes.** Every file of the 15 calls above has the same SHA-256 before, with A and with A + B (PNG16, PNG8, EXR 32f and `infinite` exports, the `base_color` and `mask:10` captures, the 11 `material_views` files, the `region_stats` JSON, the exports after the edit). The Wand's capture is `f22b9da6…` and its export `f5202163…`, `24171dfa…`, `9cd65935…`, `e893061d…` before and after, the e2e report's hashes.
- **Tests (A).** `tests/python/test_pyapi_native.py::test_calls_on_one_revision_reuse_its_evaluation` (same bytes, the warm exports under a third of the cold one, a refusal keeps the evaluation, a capture writes the export's BaseColor) and `::test_a_commit_supersedes_the_kept_evaluation` (after a commit the bytes are a fresh process's); the export, diagnostics, capture (CPU and GPU) and worker diagnostics tests that read these paths.
- **Tests (B).** The CPU golden comparisons of every store operation, under `UZP_NO_GPU=1`: `tests/evaluator` (sources and projection, blend kernels and pass-through groups, mask effects and levels, height to normal, two-process determinism, evaluation order and cache) and `tests/export` (the written and processed goldens, the sRGB8, variant and minification files, the five-map preset's normal). 131 passed and 118 GPU variants skipped. One failed: `test_export_encoders.py::test_written_files_equal_the_dry_run_in_two_processes`, whose spec puts a colour bitmap on a one-channel channel; it is refused by decision 218 before any store operation runs, and it fails the same way in the full gate on `959b16a`, before this change. The regression tests' stack evaluates about 11 times longer than it encodes in Debug on all threads, so their "a third of the cold export" bound holds with margin.

## Alternatives Considered

- Run exports and captures on the GPU evaluator: rejected. It would change which evaluator writes the delivered bytes.
- Key the kept evaluation on the revision number: rejected. A closed and reopened project, or another project, can have the same number.
- Key it on a content hash of the revision, so that a reopened project finds it (kimi): not taken. The evaluation lives with the open project, and a reopened project evaluates its revision once.
- Remove a failed operation's tile from the cache instead of dropping the evaluation: rejected. It needs every allocation site of the evaluator to undo its own allocation; dropping is local to the lease.

## Consequences

- An export, capture or diagnostic of a revision another call evaluated only encodes or reads what that call left; the first call on a revision still evaluates.
- The worker keeps one revision's tiles between calls (dropped on commit, on another revision, on close, or when memory is short).
- The CPU evaluator uses every hardware thread for each tile operation; two concurrent evaluations (an export job and a capture) share the cores.
