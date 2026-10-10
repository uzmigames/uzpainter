# Proposal: phase1.23_pyapi-pipeline-adapter

## Why
Child of `phase1.24_python-api-facade` (P1-PYAPI in `docs/dag.md`), implementing D9 (decision 011) as specified in `docs/architecture/10-python-api.md` §2 and §6. The Assets3D pipeline drives Painter through `painter_mcp_client.py execute_python` and its scripts `A3D\Docs\Pipeline\Retopologia\cajado-v10\painter_create.py`, `painter_export.py` and `A3D\Docs\Pipeline\Pintura\painter_layer_stack.py` (UzmiGames code, readable freely). They must run unchanged against UzPainter (OWN-04), which requires a UzmiGames-owned adapter that swaps only the transport and serves the pipeline's one private Painter call outside the facade, so the facade stays documented-only and every adaptation is listed as a migration. This child carries the P1-PYAPI acceptance item "the three pipeline scripts run unchanged through the adapter". Requirements: OWN-04, INT-01, INT-10, LAY-06, LAY-07 (`docs/prd.md`).

## What Changes
- `adapters/assets3d/`: the UzmiGames pipeline adapter (not part of the facade) replacing `painter_mcp_client.py execute_python` with `UzPainter.exe run`, with absolute paths unchanged; it preserves the contract that the script assigns `result`, returned as JSON with captured stdout and stderr, and that an uncaught exception is a structured failure with the traceback.
- A UzmiGames-owned shim for the private viewport-capture call `_substance_painter.display.save_viewport(path, w, h, _)`, supplied only to the scripts the adapter runs, calling `uzpainter.render.capture(mode=painter_viewport)` (always the current state, never stale). That capture mode is delivered, and the shim wired to it, by `phase2.2_preview-capture` (child of `phase2.3_realtime-preview`); until then the shim raises an explicit capability error naming the missing mode, never a silent no-op.
- `adapters/assets3d/MIGRATIONS.md`: the list of every shim and host-side change, one entry per adapted call.
- Phase 1 fixture `tests/adapters/assets3d/`: `painter_create.py`, `painter_layer_stack.py sync` and `painter_export.py` run on the wand v1 inputs, with each script's SHA-256 pinned so the run proves the scripts are byte-unchanged; the script paths that need later capabilities (`painter_layer_stack.py smart` with smart presets from `phase3.6_smart-presets-projections`, `capture` with the viewport capture of `phase2.2_preview-capture`) fail explicitly with a capability error until those land.

## Dependencies
- Parent: `phase1.24_python-api-facade` (integration and acceptance of P1-PYAPI).
- Prerequisites: `phase1.3_document-model`, `phase1.18_export-engine`, `phase1.8_project-store` (DAG inputs of P1-PYAPI) and the siblings `phase1.19_pyapi-native-module`, `phase1.20_pyapi-facade`, `phase1.21_pyapi-dispatcher-lifecycle`, `phase1.22_pyapi-cli-capabilities` (`run`).
- Consumed by `phase1.25_pilot-wand` (wand v1 rebuilt via `painter_create/sync/export`) and later by `phase3.1_assets3d-cutover`.

## Acceptance
- `painter_create.py`, `painter_layer_stack.py sync` and `painter_export.py` run unchanged (pinned SHA-256) through the adapter on the wand v1 inputs and return their JSON results.
- The shim is visible only to adapter-run scripts and is listed in `MIGRATIONS.md`; the facade exposes no `_substance_painter` symbol; until the viewport capture exists the shim raises an explicit capability error.
- LAY-06 and LAY-07 behaviour the scripts rely on holds through the scripts: repeated named operations create no duplicate, an ambiguous name fails before mutation, and `sync` rebuilds only the addressed group while unrelated roots and resources survive.

## Impact
- Affected specs: `python-api` (pipeline adapter)
- Affected code: `adapters/assets3d/`, `tests/adapters/assets3d/`
- Breaking change: NO
- User benefit: the existing Assets3D scripts drive UzPainter without edits, with every adaptation on record
