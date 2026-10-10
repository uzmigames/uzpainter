# Proposal: phase1.24_python-api-facade

## Why
The Assets3D pipeline and every AI agent drive the texturing tool through Python: Painter's `substance_painter` scripts must run unchanged, and a typed native API must expose the document with one transaction per call, exact readback, explicit capability statuses and no silent no-op. Requirements: OWN-04, INT-01, INT-02, INT-10, INT-20, INT-23, LAY-01, LAY-06, LAY-07, LAY-08, LAY-12, QG-03, ARC-03, ARC-13, ARC-14 (`docs/prd.md`). Implements D9 (decision 011) and D2 (decision 004, amended by decision 019: brush strokes out of scope) as specified in `docs/architecture/10-python-api.md`, with the worker roles and threads of D1 (decision 003) in `docs/architecture/02-runtime-topology.md` §1 and §4. DAG node P1-PYAPI (`docs/dag.md`), on the Phase 1 critical path to `phase1.25_pilot-wand` and gate G1 ("the three pipeline scripts run unchanged through the adapter", `docs/roadmap.md`).

This is the parent integration and acceptance task, split per the `docs/dag.md` task decomposition rule into five independently reviewable children.

## What Changes
Integration of the five children (DAG Outputs of P1-PYAPI):
- `phase1.19_pyapi-native-module`: the pybind11 `uzpainter` module (`src/python/`), the mutation contract, error classes, jobs, native `Transaction`, name addressing and `sync_stack`, GIL rules of the Python command thread.
- `phase1.20_pyapi-facade`: the `substance_painter` facade subset of documented symbols (`python/substance_painter/`), output-changing quirks, desktop-only omissions, inert state, `js.evaluate` whitelist, colour-configuration profiles, `substance_painter_plugins`.
- `phase1.21_pyapi-dispatcher-lifecycle`: the Python dispatcher thread, events, asynchronous lifecycle, computation state, mesh-reload callback.
- `phase1.22_pyapi-cli-capabilities`: the `run` CLI and the capability manifest populated with Phase 1 statuses and checked against behaviour.
- `phase1.23_pyapi-pipeline-adapter`: the UzmiGames pipeline adapter (`adapters/assets3d/`) with the private-call shim and the migration list.
Tests in `tests/python/` and `tests/adapters/assets3d/`.

## Dependencies
- DAG inputs: `phase1.3_document-model` (P1-DOCMODEL), `phase1.18_export-engine` (P1-EXPORT), `phase1.8_project-store` (P1-STORE).
- Children (all mandatory): `phase1.19_pyapi-native-module`, `phase1.20_pyapi-facade`, `phase1.21_pyapi-dispatcher-lifecycle`, `phase1.22_pyapi-cli-capabilities`, `phase1.23_pyapi-pipeline-adapter`.
- Downstream: `phase1.25_pilot-wand` (P1-WAND), then gate `phase1.26_gate-g1`; `phase2.8_mcp-server` maps its typed tools onto the native operations; `phase3.1_assets3d-cutover` uses the adapter.

## Acceptance
DAG gate of P1-PYAPI: the three pipeline scripts run unchanged through the adapter (`painter_create.py`, `painter_layer_stack.py sync`, `painter_export.py` on the wand v1 inputs, script SHA-256 pinned; the `smart` and `capture` paths fail explicitly with capability errors until `phase3.6_smart-presets-projections` and `phase2.2_preview-capture` deliver them); the API-probe goldens of `phase0.6_tier0-api-probes` (set→get readback, mask `None` rules, insertion rules, active-channel reset, event order) are exact. The parent closes only when all five children are accepted.

## Impact
- Affected specs: `python-api`
- Affected code: `src/python/`, `python/substance_painter/`, `python/substance_painter_plugins/`, `adapters/assets3d/`, `tools/capabilities/` (status inputs), `tests/python/`, `tests/adapters/assets3d/`
- Breaking change: NO
- User benefit: existing Painter scripts and new agents drive UzPainter through one Python API whose capabilities are explicit and whose every call is transactional
