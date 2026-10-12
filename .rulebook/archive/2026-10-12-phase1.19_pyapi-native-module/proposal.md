# Proposal: phase1.19_pyapi-native-module

## Why
Child of `phase1.24_python-api-facade` (P1-PYAPI in `docs/dag.md`), implementing D9 (decision 011) as specified in `docs/architecture/10-python-api.md` §1, §5 and §7, with the worker thread rules of D1 (decision 003) in `docs/architecture/02-runtime-topology.md` §4. Every script, the `substance_painter` facade, the pipeline adapter and later the MCP typed tools reach the document through one typed native API; it must mirror Painter's documented module and class names, run each call as one transaction, read back every value it sets, and never report an empty success. Requirements: INT-01, INT-10, LAY-01, LAY-06, LAY-07, LAY-08, QG-03, ARC-11, OWN-04 (`docs/prd.md`).

## What Changes
- `src/python/`: the pybind11 `uzpainter` module, statically linked into `UzPainter.exe` on the embedded CPython 3.13 whose boundary `phase0.7_toolchain-cpython` qualified, with a private vendored site-packages (pip unsupported).
- Phase 1 modules, named after Painter's wherever a Painter symbol exists: `uzpainter.project` (create, open, close, `save` modes, `save_as`, `save_as_copy`, revert, `revision()`, `needs_saving()` over `phase1.8_project-store`), `.textureset`, `.layerstack` (the node kinds, masks, levels and blending the Phase 1 compositor evaluates), `.source` (uniform colour, bitmap, UV projection), `.resource` (import, `resource://project/<name>?version=<sha256>` URLs, in-place resource replacement on a node instance, LAY-08), `.export` (export through `phase1.18_export-engine`, `export.plan(config)` dry run from `phase1.15_export-plan-compiler`), `.colormanagement`, `.levels`, `.properties`, `.exception`, `.logging`, `.application`, and the UzPainter-only `.jobs` (`Job.id/status/progress/wait/cancel`, `list()`) with synchronous conveniences over worker jobs.
- Modules whose behaviour arrives later (`.baking` with `phase3.5_embree-bakers`; `.render`, `.display` with `phase2.3_realtime-preview`; `.diagnostics` and `project.dump_recipe()` with `phase2.2_recipe-and-diagnostics`) are importable, and each call raises `NotYetSupported` before any mutation.
- Mutation contract (10 §5): thin handles with `__slots__` (assigning an unknown attribute raises `AttributeError`); every setter has a getter, read back through a freshly resolved handle (`layerstack.get_node_by_uid`); every operation takes an explicit `(texture_set, stack)` address with the active stack only as a default; one API call = one transaction through `src/uzp_core/transaction/`, with results enumerating created/modified/hidden node ids and imported/skipped resources (QG-03); the native `Transaction` context manager for atomic multi-call execution; 64-bit `Node.uid()`; a stale handle raises `ValueError`.
- Error classes: `ProjectError`, `ServiceNotFoundError`, `ResourceNotFoundError`, `ValueError`, `EditionContextException`, `RuntimeError` where Painter raises them; UzPainter additions `UnsupportedInUzPainter`, `NotYetSupported`, `UnsupportedProcedural`, `BusyError(job_id)`, `StaleRevisionError(expected, current)`. No failure returns an empty success.
- The native API never resets values when active channels are toggled (LAY-01); the facade's Painter quirk is added by `phase1.20_pyapi-facade`.
- Name addressing through `src/uzp_core/naming/` (LAY-06) and the native composite `layerstack.sync_stack` (LAY-07): loads the stack JSON (`title`, `groups`, `layers`; fields `base`, `base_tex`, `rough`, `metal`, `spec`, `height`, `op`, `mask`) without editing it, rebuilds only the named root group, hides (never deletes) other root groups unless their names match the explicit keep-visible prefixes, attached in one step through the composite mechanism of `phase1.2_docmodel-transactions`.
- Python command thread rules (02 §4): the document lock is held only for the CPU-side mutation; the GIL is released (`py::gil_scoped_release`) around every engine-thread or job wait.

## Dependencies
- Parent: `phase1.24_python-api-facade` (integration and acceptance of P1-PYAPI).
- Prerequisites (the DAG inputs of P1-PYAPI): `phase1.3_document-model`, `phase1.18_export-engine`, `phase1.8_project-store`; the render core, mesh loader and compositor arrive through `phase1.18_export-engine`.
- Followed by the siblings `phase1.20_pyapi-facade`, `phase1.21_pyapi-dispatcher-lifecycle`, `phase1.22_pyapi-cli-capabilities` and `phase1.23_pyapi-pipeline-adapter`, which all build on this module.

## Acceptance
- Every Phase 1 setter passes set → get → save → reopen → get through a freshly resolved handle; the matching Tier 0 API-probe readbacks (`phase0.6_tier0-api-probes`) are exact.
- Assigning an unknown attribute raises `AttributeError`; a stale handle raises `ValueError`; every later-phase call raises `NotYetSupported` before mutating; no failure returns an empty success.
- A failed call leaves its mutation unapplied; a script that raises after earlier calls keeps those calls committed and its error receipt names the last committed revision; a raising `Transaction` commits nothing.
- `sync_stack` rebuilds only the named group, hides the other root groups unless keep-visible, and leaves unrelated roots and resources intact.

## Impact
- Affected specs: `python-api` (native module, mutation contract)
- Affected code: `src/python/`, `tests/python/`
- Breaking change: NO
- User benefit: one typed, transactional Python API whose every call either commits and reads back or fails explicitly
