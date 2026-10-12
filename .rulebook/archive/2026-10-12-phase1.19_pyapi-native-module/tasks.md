## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.18_export-engine, phase1.8_project-store — phase1.3 and phase1.8 are archived; phase1.18_export-engine is still open (its children's code, which the native export uses, is on main; decision 106 §3)

## 2. Implementation
- [x] 2.1 pybind11 `uzpainter` module statically linked into `UzPainter.exe` on the embedded CPython 3.13 with a private vendored site-packages
- [x] 2.2 Handle base with `__slots__`, uid-based re-resolution, `AttributeError` on unknown attributes and `ValueError` on stale handles
- [x] 2.3 Error hierarchy: Painter-documented exceptions plus `UnsupportedInUzPainter`, `NotYetSupported`, `UnsupportedProcedural`, `BusyError(job_id)`, `StaleRevisionError(expected, current)`
- [x] 2.4 `uzpainter.project`: create, open, close, `save` modes, `save_as`, `save_as_copy`, revert, `revision()`, `needs_saving()` over the project store
- [x] 2.5 `uzpainter.textureset`, `.layerstack`, `.source`, `.levels`, `.properties` for the Phase 1 compositor subset, each setter paired with a getter and an explicit `(texture_set, stack)` address
- [x] 2.6 `uzpainter.resource`: import, resource URLs, in-place replacement of a mask/bitmap resource on a node instance (LAY-08)
- [x] 2.7 `uzpainter.export` over the export engine, including `export.plan(config)` dry run; `uzpainter.colormanagement`, `.logging`, `.application`
- [x] 2.8 `uzpainter.jobs` (`Job.id/status/progress/wait/cancel`, `list()`) and synchronous conveniences over worker jobs, releasing the GIL while waiting
- [x] 2.9 One call = one transaction through `src/uzp_core/transaction/`; result objects enumerating created/modified/hidden ids and imported/skipped resources; native `Transaction` context manager
- [x] 2.10 Name addressing (LAY-06) exposed on every name-taking call; ambiguous matches fail before mutation
- [x] 2.11 Native `layerstack.sync_stack` composite (LAY-07): unedited stack JSON, named-group rebuild, hide-not-delete of other root groups, keep-visible prefixes
- [x] 2.12 Later-phase modules and calls (`.baking`, `.render`, `.display`, `.diagnostics`, `project.dump_recipe()`) importable and raising `NotYetSupported` before mutation
- [x] 2.13 Document lock held only for the CPU-side mutation; `py::gil_scoped_release` around every engine-thread and job wait

## 3. Tests
- [x] 3.1 Set → get → save → reopen → get through a freshly resolved handle for every Phase 1 setter
- [x] 3.2 Tier 0 API-probe readbacks owned by the native API (set→get, LAY-01 values unchanged across active-channel toggles) compared exactly with `phase0.6_tier0-api-probes` goldens in a local run on the owner's machine (decision 028; the local run report is the evidence) — native-owned readbacks of `fill-layer-readback` and `textureset-project-readback` exact in both recordings (`tests/python/test_pyapi_tier0.py`, `parity/reports/phase1/pyapi-native-module.md`); facade-shaped readbacks are a scope split to `phase1.20_pyapi-facade` item 3.7 and Painter's default "Layer 1" to `phase4.1_nodes-paint-layers` item 2.8 (decisions 105, 106)
- [x] 3.3 `AttributeError` on an unknown attribute assignment; `ValueError` on a deleted node's handle; `NotYetSupported` raised before mutation by each later-phase call
- [x] 3.4 Transaction tests: failed call leaves no mutation; script raising after two calls keeps both and its error receipt names the last committed revision; a raising `Transaction` block commits nothing; results list created/modified/hidden ids
- [x] 3.5 LAY-06: ambiguous name fails before mutation with candidate ids; repeating a named operation creates no duplicate; ids survive save/reopen
- [x] 3.6 LAY-07: `sync_stack` rebuilds only the named group; other root groups hidden, not deleted, unless keep-visible matches; unrelated roots and resources survive
- [x] 3.7 LAY-08: replacing a mask resource on a node instance keeps the node uid and changes only that binding
- [x] 3.8 GIL test: a second Python thread runs while the command thread waits on an export job

## 4. Acceptance
- [x] 4.1 Every §3 test green (hosted CPU lane where no GPU is needed, with GPU and oracle tests skipped there with an explicit reason; a local run on the owner's machine for evaluation, export and private-golden comparisons, decision 028); results attached to `phase1.24_python-api-facade` — 16 of 16 in `tests/python` (the Tier 0 file skips without a private store); report `parity/reports/phase1/pyapi-native-module.md` for `phase1.24_python-api-facade` (decision 106 §4)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation — `src/python/PYAPI.md`, `docs/architecture/10-python-api.md` §7
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
