# 144. R9 follows the owner's committed pipeline, its route guard runs unadapted, and its pinned inputs outlive Assets3D `_tmp` in the private store

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.25_pilot-wand, phase1.23_pyapi-pipeline-adapter

## Context

Assets3D commit `9a718b9` (2026-10-12, "Zombie post-mortem and the mandatory production runner") changed `Pipeline/painting/painter_layer_stack.py`. Before every command it now runs a route guard:

- it sends its own probe `GUARD_CODE` through `execute()`;
- it imports `locate` from the new `Pipeline/qa/route_check.py`;
- for a project inside a new-layout character (`Creatures/<Family>/<Name>/Project/`), it asks the production runner for the open paint attempt and passes that attempt's token to the MCP client as `execute(code, token)`.

The script's SHA-256 moved from `cc303741…` to `bf7006e2…`. The R9 request (`phase1/tier1/wand-v1`, decision 099) therefore no longer loaded, and the adapter tests, the Tier 1 wand runner and the pending R9 recording all failed. The create and export scripts and the other inputs did not change.

While this was being fixed, another session cleaned Assets3D's git-ignored `_tmp` (about 20:08). That removed `_tmp/claude/varinha11-v1/`, which held 21 of the 25 R9 inputs: the two arguments files, the stack JSON, the mesh and its material library, the normal, the AO and the 14 bitmaps. Uncommitted Assets3D work in progress also deletes `Pipeline/qa/route_check.py` and moves `locate` into `Pipeline/production/run.py`.

## Decision

1. **Re-pin to the owner's current committed pipeline.** The old bytes are not kept. R9 has not been recorded, the scripts must run unchanged, and parity follows what the owner runs (the rolling-oracle rule of decision 037, applied to pipeline inputs). As in decision 040 (1), only committed Assets3D content is followed: the pins are those of `9a718b9`. The re-pin was made with the generator (`python -m tools.parity.recorder.script_run manifest`):
   - `painter_layer_stack.py` is pinned at `bf7006e2…`;
   - `Pipeline/qa/route_check.py` is a new pinned input (`route-check-py`, `d2024ead…`; it imports only the standard library);
   - the sync step names it in a new argument `imports`. The recorder loads each listed module from its pinned bytes, under its file stem, for the sync run only, and refuses an `imports` entry that the script does not import.
2. **The guard runs; nothing fakes it.**
   - **Recorder.** The recorder's `execute` takes the script's `token` argument. The guard's probe goes through it like any other call. The recorder requires exactly two calls, the probe (the script's own `GUARD_CODE`) and then one sync, and returns the sync's result. Scripts run from their staged copies; a root marker in the staged mirror makes their Assets3D root that mirror. The project lies in the recorder's private work directory, so `locate` answers `legacy`, as it does for the wand's production path under the Skeletal Mage. Two verdicts are refused as recorder errors: a `ROUTE BLOCKED` exit, and an attempt token (the recorder does not carry the production runner's token).
   - **Adapter.** The adapter needs no change. The probe is an ordinary M1 call, and the facade serves it. The adapter test now runs `painter_create.py` through `client.py execute_python`. The reason: since `9a718b9`, `run` sends the probe first, and the probe needs a saved project open.
3. **Pinned inputs outlive `_tmp` (coordinator decision).** An input resolves at its `assets3d_path` when the file there holds the pinned bytes. Otherwise it resolves from the private store (`%LOCALAPPDATA%\UzPainter\parity-store`), by hash. If neither holds the bytes, the call is refused and names both. The store gains authored-input entries: `python -m tools.parity.store input FILE --path P` stores the blob, plus a write-once `inputs/<sha256>.json` naming the path. All 25 R9 inputs are stored. Every one had a hash-identical copy:
   - 21 from earlier staged test mirrors;
   - `painter_create.py` and `painter_export.py` from Assets3D;
   - the two `9a718b9` scripts from git objects, checked out with CRLF line endings.

   Nothing is written to Assets3D.
4. **Approved sources.** Decision 040 is applied: new rows U-A3D-STACK-3, U-A3D-ROUTECHECK and U-A3D-MCPCLIENT-2 at `9a718b9`. The reviewer audited each delta. None contains Adobe content.

## Alternatives Considered

- Keep the old bytes pinned. Rejected: parity would follow a pipeline the owner no longer runs.
- Follow the uncommitted `locate` move into `run.py`. Rejected: decision 040 (1), and the work was in progress.
- Treat the guard's probe as a recorder artefact and skip it, or answer it host-side. Rejected: the pipeline's own call would then be faked.
- Restore the deleted files into Assets3D. Rejected: Assets3D is read-only to UzPainter.

## Consequences

- R9 and the adapter tests no longer depend on Assets3D `_tmp`.
- When the owner commits the `locate` move, the re-pin is mechanical: regenerate, then name `Pipeline/production/run.py` in `imports`.
- Assets3D's MCP client gained its own guard: project changes on a new-layout character are refused without `UZ_ROUTE_TOKEN`. The adapter's drop-in client has no such check and ignores the token (MIGRATIONS M8). Every current fixture is outside the new layout, so both clients pass. Whether the adapter must refuse new-layout characters the same way is left to the owner.
