# `phase1.23_pyapi-pipeline-adapter`: local run on the owner's machine

This task is a child of `phase1.24_python-api-facade` (P1-PYAPI; `docs/architecture/10-python-api.md` §2 and §6; OWN-04, INT-01, INT-10, LAY-06, LAY-07). Under decision 028, its wand v1 fixture runs locally against the UzmiGames asset repository. This report is its evidence for `phase1.24_python-api-facade`.

- Run on 2026-10-12, branch `wt/phase1.23-adapter` with main merged (`a48d1ea`), Assets3D at `0f608a4`.
- Decision 113. Implementation: `adapters/assets3d/` (`MIGRATIONS.md` M1-M7) and `tests/adapters/assets3d/`.
- No Painter recording was made. The adapter is UzmiGames code over UzPainter.

## Scripts run, pinned by SHA-256

The pins come from the committed R9 request manifest (`parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase1/tier1/wand-v1.json`, decision 099). The recorder's loader hash-checks the scripts and their 21 inputs (arguments, stack, mesh, mesh maps, 14 bitmaps) under the Assets3D root before anything runs.

| Script | SHA-256 |
|---|---|
| `Pipeline/retopology/wand11-v1/painter_create.py` | `6820831ccd59b66314eaab5a010607f7f55d720e6d2e628aadf9d44a6018535f` |
| `Pipeline/painting/painter_layer_stack.py` | `cc3037413a89c687ffb2d6b340ce1ad5a1351ad4924d7911c876eeb13d29eebc` |
| `Pipeline/retopology/wand11-v1/painter_export.py` | `777ac278c7ce376bd8652bdd8400f0e5e5e1bef561262ccb7c22a9ac1c95c468` |

## Result

### Wand v1 fixture over `UzPainter.exe` (`tests/adapters/assets3d/test_pipeline_adapter.py`, owner's machine): 10 of 10 pass

All these tests use the `UzPainter.exe` of a fresh `zig build painter`.

- **3.1** (recorded scope split, decision 113 §7).
  - `painter_create.py` returns its result: the project saved at the repointed `dst`, the set `11-Varinha-Madeira` at 2048, Normal and AO bound, `needs_saving` false. Wall time about 1.5 s.
  - `painter_layer_stack.py sync` returns `SYNC_DONE` with 13 layers, the 14 images imported and nothing hidden. Wall time about 4 s, through the carried session.
  - `painter_export.py` runs its pinned bytes. It returns the export engine's explicit `NotYetSupported` for the 16-bit sRGB8 BaseColor (R-090, decision 103) before anything is written, after its own save. The test turns to the five-map result by itself once `srgb8-material-channels` is no longer a gap in `parity/semantics/export-processing.json` (phase1.25_pilot-wand item 2.6).
  - The production `dst` and `out` in Assets3D are untouched.
- **2.5.** A copy of `painter_create.py` with one byte appended is refused with `PinMismatch` before anything runs: no session file is written.
- **3.2.** A raising script returns `success: false`, the type, message and a traceback naming the line in `<uzpainter-assets3d-adapter>`, and the captured stdout, with exit status 1. Through `painter_layer_stack.py run`, the script's own transport raises its usual `Painter MCP call failed`. A successful result returns both streams. A non-JSON value comes back as its `str()`, as the bridge returns it.
- **3.3.** Inside an adapter run, `_substance_painter.display.save_viewport` exists. A plain `UzPainter.exe run` script cannot import `_substance_painter`, even after importing every `substance_painter` module; no facade module has such an attribute; and `capabilities.json` names no such symbol.
- **3.4.**
  - `capture` fails with `NotYetSupported` naming `painter_viewport` and `phase2.2_preview-capture`. No image is written and the revision is unchanged.
  - `smart` is refused before any call, naming "smart presets", `phase3.6_smart-presets-projections` and the two `release-gap` symbols. The revision and the session file are unchanged.
- **3.5** (recorded scope split, decision 113 §7).
  - A repeated `sync` leaves exactly one group of the stack's title with 4 groups and 13 layers, imports nothing again (the state file's resources are reused) and keeps the project's resources unchanged.
  - The node uids read back identical across calls (each a reopen in a fresh process) and after a save.
  - Create run twice: recording P23-A. Ambiguity: tested at the API level.
- **3.6.** After `metal` and `extra` root groups are added (`extra` with a fill bound to a resource only it uses), `sync` rebuilds the stack's group (new uid) and hides `metal` and `extra` without changing them. The resource stays bound to `extra`'s fill. With `--keep-visible met`, `metal` stays shown and `extra` is hidden.
- **Exports (M6).** A probe export through the client publishes generation `000001`, and its fixed-name copy verifies in the run. The receipt's manifest files are named under the Assets3D root (here the work tree's mirror): plan, map, project file and mesh, all valid `$defs/path` values. Under a root that does not hold them, `manifest` is null with the reason.

### Host-side parts (`tests/adapters/assets3d/test_adapter_units.py`, every lane): 24 of 24 pass

These cover the manifest rebase and its refusals, the fixed-name verification (journal generation, incomplete copy, obsolete names, foreign files, changed and missing files), exact-path redirects, the bridge's normalisation, atomic session writes, pins, the `smart` gate (closed for `release-gap`, `pending-evidence` and absent; open for `supported`; other commands never read the manifest), the client's usage and host errors, and the session lock.

### Checks

- `ruff check`, `ruff format --check` and `mypy` (strict, now covering `adapters/`) pass on the whole repository.
- The repository guard passes.

## Recordings named (owner action)

- **P23-A**: `project.save_as` onto an existing `.spp` that is not open (decision 113). It settles re-running `painter_create.py` onto its `dst`. Owner: `phase1.24_python-api-facade`.
- The Wand v1 Tier 1 golden (R9) stays pending in the OCIO session (decisions 099, 100). It is not needed by this task.
