# 113. The Assets3D adapter swaps only the transport, carries the session between `run` calls and refuses a missing capability before mutation

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.23_pyapi-pipeline-adapter, phase1.24_python-api-facade, phase1.25_pilot-wand, phase2.1_supervisor-ipc-worker, phase2.2_preview-capture, phase3.1_assets3d-cutover, phase3.6_smart-presets-projections

## Context

Task phase1.23 builds the UzmiGames adapter. It lets the Assets3D scripts `painter_create.py`, `painter_layer_stack.py` and `painter_export.py` drive UzPainter byte-unchanged (10 §2, §6). Measured facts:

- **One transport for every call.** The pipeline calls every Painter script through `painter_layer_stack.py`: `sync`, `smart` and `capture` build code; `run FILE` reads a file. Its only transport is `execute(code)`, which runs `[MCP_PYTHON, CLIENT, "execute_python", args.json]` with two hard-coded module globals.
- **The community bridge.** It executes the code in `{"params": {}}` and returns `{"success": true, "data": result}` with `default=str`.
- **One process per call.** Painter is one persistent process: create saves a project, sync edits it unsaved, and export saves and exports it. `UzPainter.exe run` is one process per call, and it closes the project with the native close, which keeps every committed revision (decisions 105, 111).
- **Measured with the pinned bytes on the wand v1 inputs.** Create returns its result in 1.5 s and sync in 4.3 s through the carried session.
- **The wand's export is refused before writing.** The 16-bit BaseColor (an sRGB8 channel at PNG 16) is refused with `NotYetSupported` naming R-090 (decision 103, owner phase1.25 item 2.6).
- **Re-running create fails.** Running `painter_create.py` again onto its existing `dst` raises `ProjectError`, because native `save_as` refuses an existing file. Painter's behaviour there is unrecorded.
- **Phase 1 capability gaps.** `smart` deletes and inserts nodes before it reaches `insert_smart_mask` and `resource.search`, both release gaps. `capture` changes nothing before the private `save_viewport` call, and capture mode `painter_viewport` is a release gap.
- **Work decision 097 left to the adapter.** It chooses the consumers' route, rebases `manifest_files` under the Assets3D root, and supplies the app version and build. The native export already passes the version and build.

The model panel answered in one round: cx/gpt-6-astra, kimi/kimi-k3 and xai/grok-4.5.

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 session carry | PARTLY: locking, atomic writes, tests of the restored state | AGREE: document one pipeline per session file | PARTLY: prove the facade can restore the context and the active stack |
| C2 rebind `CLIENT`/`MCP_PYTHON` | AGREE | AGREE | AGREE |
| C3 envelope superset, bridge semantics, exits | PARTLY: map exits explicitly | AGREE | AGREE |
| C4 shim; `smart` gated host-side | PARTLY: `pending-evidence` must not open the gate; state that `run FILE` is ungated | PARTLY: open only on `supported` | AGREE |
| C5 fixed-name copy verified in the run, manifest rebased | DISAGREE: later unlocked reads can race another export | AGREE | AGREE |
| C6 fixture from the R9 pins with mirrored redirects | PARTLY: isolate the session; nothing written outside the work tree | PARTLY: the env var must not be silent | AGREE |

## Decision

1. **Transport (C2).** `adapters/assets3d/layer_stack.py` runs the script's bytes under a module name other than `__main__`. It rebinds only `CLIENT` (to `client.py`) and `MCP_PYTHON` (to the running interpreter), then calls the script's own `main()`.
   - `client.py execute_python args.json` runs `UzPainter.exe run runner.py`.
   - `--pin FILE=SHA256` refuses a changed file before anything runs.
2. **Result contract (C3).** The runner executes the code in `{"params": {}}` and normalises `result` with `default=str`.
   - The reply is a superset of the bridge's envelope: `stdout`, `stderr`, `error {type, message, traceback}`, `code_sha256`, `session`, `exports`, `redirects`.
   - Exit codes are mapped, not forwarded: 0 ok, 1 structured failure or refusal, 2 usage, 3 host error.
3. **Session (C1, amended).** A session file carries what a call left open: the project file, the facade's project index, its `needs_saving()` and the active stack. The next call reopens the project through the facade and restores them.
   - Calls are serialised by an OS lock on `<session>.lock`, and the file is replaced atomically.
   - A carried project that does not open fails the call before the code runs and empties the session.
   - A call that leaves an untitled project open fails with `AdapterSessionError`, keeping the script's `result`.
   - Selection, UI mode and collapsed state are not carried.
   - Tests read back the context URLs, the uids, `needs_saving()` and the content across calls. The carry ends with phase2.1's persistent worker.
4. **Missing capabilities (C4, amended).** A shim in the runner serves `_substance_painter.display.save_viewport`, installed into `sys.modules` for adapter runs only. It calls `uzpainter.render.capture(mode="painter_viewport")` and, until phase2.2_preview-capture delivers that mode, raises `NotYetSupported` naming the mode.
   - The host refuses `smart` before any call, naming "smart presets" (phase3.6_smart-presets-projections).
   - The gate reads `capabilities.json` and opens only when every symbol it needs is `supported`.
   - Code sent through `run FILE` is not gated: a missing call raises where it is reached, as Painter's contract has it (10 §5).
5. **Exports (C5, adopted 2 to 1; the residual recorded).** The consumers keep the fixed-name copy in `exportPath`. Before the call succeeds, the runner verifies the copy of the run's last export into each folder against its receipt: the journal's generation, completeness, and every file's size and SHA-256.
   - `exports[]` returns each receipt's `manifest_files` rebased under `UZP_ASSETS3D_ROOT`, or null with the reason.
   - The app version and build come from the native export.
   - **Residual (GPT):** reads after the call are not locked. Assets3D's Painter lock serialises export and consumption. The pinned-generation route for consumers that can change belongs to phase3.1_assets3d-cutover.
6. **Fixture (C6, amended).** The wand fixture loads the committed R9 request manifest with the recorder's loader, so every input is hash-checked. It stages the inputs into a mirror of the Assets3D tree, along with the session file.
   - It maps exactly the two hard-coded arguments paths, through `UZP_ASSETS3D_OPEN_REDIRECTS`, to copies whose Assets3D paths name the mirror. This is decision 099's adaptation (a).
   - The reply lists every redirect applied.
   - The test checks that the production `dst` and `out` are untouched.
7. **Scope split of items 3.1 and 3.5 (decision 069 pattern).**
   - **3.1.** Create and sync return their JSON results. The pinned export runs and returns the export engine's explicit refusal while `srgb8-material-channels` is a gap in `parity/semantics/export-processing.json`. The test flips to the five-map result by itself when that entry stops being a gap (owner phase1.25 item 2.6).
   - **3.5.** "Create twice" is blocked on recording **P23-A**, owner phase1.24_python-api-facade. The three scripts make no name-addressed call that can match two nodes: the sync title replaces every match by the script's design, and texture-set names are unique. The ambiguity rule stays tested at the API level (`tests/python/test_pyapi_native.py`, `test_pyapi_facade.py`).

## Recordings this decision names (not recorded; owner action)

- **P23-A, `save_as` onto an existing file.** With a project open, `project.save_as(path)` where `path` is an existing `.spp` that is not open. Read whether it raises (type, message) or overwrites (`file_path()`, the file's size and mtime, a reopen of `path`). Both recordings.

## Alternatives Considered

- **Replacing `execute()` (the recorder's 099 4b).** Rejected: it skips the script's own reply handling.
- **Waiting for phase2.1's persistent worker.** Rejected: Phase 1 would have no adapter.
- **Running every call in one native `Transaction`, so a failing `smart` rolls back.** Rejected: it changes Painter's partial-commit contract for every script.
- **Opening the gate on `pending-evidence`.** Rejected (Kimi, GPT): the symbol is unverified, and the gated code mutates first.
- **The locked or pinned reader for the Blender consumers.** Not possible with unchanged consumers. Recorded as the residual.

## Consequences

- `adapters/assets3d/` (`client.py`, `runner.py`, `layer_stack.py`, `MIGRATIONS.md` M1-M7) and `tests/adapters/assets3d/` exist. mypy covers `adapters/`.
- phase2.2 wires the shim. phase3.6 opens the `smart` gate through the manifest. phase1.25 turns the wand export into a result. phase1.24 owns P23-A.
