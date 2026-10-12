# 147. Embedded files are part of their object's cache key through a content digest define

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.9_compositor-resample-gaps (first report), phase2.1_preview-viewport-window (second report)

## Context

Two agents saw a GPU test keep running an old kernel after they edited only an `.hlsl` that a C++ source pulls in with `#embed`. The stale kernel stayed until the embedding `.cpp` changed or the build used a fresh `--cache-dir`. The phase1.9 transcript shows it on `src/evaluator/shaders/evaluator_project.hlsl`. The executable built after the edit did not contain the new text, and a fresh `--cache-dir` build did.

Measured on Zig 0.15.2 (clang 20.1.2):

- **Plain edits are tracked.** clang's dependency file lists `#embed` targets, and Zig records them in the object manifest. An edit followed by a rebuild picked up the new bytes in a fixture and in the real `render-tests`, `preview-tests`, `painter` and `evaluator-tests` builds, for `mips.hlsl`, `viewport.hlsl` and `evaluator_project.hlsl`.
- **The race is not.** Zig hashes the files from the dependency file after the compile (`Cache.addDepFilePost`), as decision 041 found for headers. A fixture embedded a small file and then a 160 MB file. The small file was rewritten while that compile was running. The build kept the old bytes, which is expected. Every later sequential rebuild also kept them, because the manifest recorded the new hash. This reproduces the reported symptom exactly.

## Decision

`build.zig` adds an `EmbedInputs` helper. Every source group that holds an embedding source goes through `embed_inputs.add`: the render layer, the evaluator and the preview, in all six modules.

- **Digest define.** At configure time, `add` scans each source for quoted `#embed` lines and resolves each target beside the source, as clang does. It then compiles that source on its own with `-DUZP_EMBED_DIGEST=<hex>`. The value is a SHA-256 over each target's name and the SHA-256 of its bytes, truncated to 128 bits. The flags are part of the object's cache key and of the executable's cache key, and they are hashed before any compile. New bytes therefore always select a new key. The race could now only leave a stale object if a target changed and then changed back within one compile.
- **Unsupported targets fail the build.** A target that cannot be read fails the build. So does an `#embed` of anything other than a quoted file name.
- **Guard.** `embed_inputs.check()` runs when `build()` returns. It walks `src/` and `tests/` and fails the build when a C or C++ file that embeds a file was not passed to `add`. The same check covers a header with `#embed`.
- **Scope.** Only the embedding sources are split out and recompiled when an embedded file changes. The other files of a group keep their objects.
- **Revert.** Reverting an embedded file gives back the byte-identical executable, because the original key names the original object and link again.
- **Cost.** A configure takes 0.17 s with the scan.
- **Test.** `tests/vendoring/test_embed_inputs.py` covers this on a copy of the package, CPU only:
  - the digest is present on exactly the embedding render sources;
  - an edit to a shader changes the executable and puts the new bytes in it;
  - a revert gives back the byte-identical executable;
  - an untracked `#embed` fails the build.

The panel was not consulted. The coordinator fixed the mechanism class, and the choice between the listed ways is not a scope fork.

## Alternatives Considered

- `Step.addWatchInput` / Run-step `addFileInput`: rejected. Zig 0.15.2 has no extra-file input for a C object. Watch inputs only drive `--watch`, and Run-step inputs do not reach a compile's cache key.
- One digest per source group: rejected. Any shader edit would recompile every file of the render or evaluator group.
- A hand-kept list of embedded files: rejected. The sources already name their targets, and the guard catches any embedder that is not tracked.

## Consequences

- An embedded shader or table can no longer poison its object's cache entry by being saved during a build. Decision 041's race still applies to headers and to `.cpp` files themselves, and the worktree and no-edit-during-build rule stays.
- A new `#embed` in a file that is not compiled through `embed_inputs.add` fails the build until its call site is converted.
- Caches poisoned before this change are bypassed, because every embedding object now has a new key.
