## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.18_export-engine, phase1.8_project-store

## 2. Implementation
- [ ] 2.1 pybind11 `uzpainter` module statically linked into `UzPainter.exe` on the embedded CPython 3.13 with a private vendored site-packages
- [ ] 2.2 Handle base with `__slots__`, uid-based re-resolution, `AttributeError` on unknown attributes and `ValueError` on stale handles
- [ ] 2.3 Error hierarchy: Painter-documented exceptions plus `UnsupportedInUzPainter`, `NotYetSupported`, `UnsupportedProcedural`, `BusyError(job_id)`, `StaleRevisionError(expected, current)`
- [ ] 2.4 `uzpainter.project`: create, open, close, `save` modes, `save_as`, `save_as_copy`, revert, `revision()`, `needs_saving()` over the project store
- [ ] 2.5 `uzpainter.textureset`, `.layerstack`, `.source`, `.levels`, `.properties` for the Phase 1 compositor subset, each setter paired with a getter and an explicit `(texture_set, stack)` address
- [ ] 2.6 `uzpainter.resource`: import, resource URLs, in-place replacement of a mask/bitmap resource on a node instance (LAY-08)
- [ ] 2.7 `uzpainter.export` over the export engine, including `export.plan(config)` dry run; `uzpainter.colormanagement`, `.logging`, `.application`
- [ ] 2.8 `uzpainter.jobs` (`Job.id/status/progress/wait/cancel`, `list()`) and synchronous conveniences over worker jobs, releasing the GIL while waiting
- [ ] 2.9 One call = one transaction through `src/uzp_core/transaction/`; result objects enumerating created/modified/hidden ids and imported/skipped resources; native `Transaction` context manager
- [ ] 2.10 Name addressing (LAY-06) exposed on every name-taking call; ambiguous matches fail before mutation
- [ ] 2.11 Native `layerstack.sync_stack` composite (LAY-07): unedited stack JSON, named-group rebuild, hide-not-delete of other root groups, keep-visible prefixes
- [ ] 2.12 Later-phase modules and calls (`.baking`, `.render`, `.display`, `.diagnostics`, `project.dump_recipe()`) importable and raising `NotYetSupported` before mutation
- [ ] 2.13 Document lock held only for the CPU-side mutation; `py::gil_scoped_release` around every engine-thread and job wait

## 3. Tests
- [ ] 3.1 Set → get → save → reopen → get through a freshly resolved handle for every Phase 1 setter
- [ ] 3.2 Tier 0 API-probe readbacks owned by the native API (set→get, LAY-01 values unchanged across active-channel toggles) compared exactly with `phase0.6_tier0-api-probes` goldens in a local run on the owner's machine (decision 028; the local run report is the evidence)
- [ ] 3.3 `AttributeError` on an unknown attribute assignment; `ValueError` on a deleted node's handle; `NotYetSupported` raised before mutation by each later-phase call
- [ ] 3.4 Transaction tests: failed call leaves no mutation; script raising after two calls keeps both and its error receipt names the last committed revision; a raising `Transaction` block commits nothing; results list created/modified/hidden ids
- [ ] 3.5 LAY-06: ambiguous name fails before mutation with candidate ids; repeating a named operation creates no duplicate; ids survive save/reopen
- [ ] 3.6 LAY-07: `sync_stack` rebuilds only the named group; other root groups hidden, not deleted, unless keep-visible matches; unrelated roots and resources survive
- [ ] 3.7 LAY-08: replacing a mask resource on a node instance keeps the node uid and changes only that binding
- [ ] 3.8 GIL test: a second Python thread runs while the command thread waits on an export job

## 4. Acceptance
- [ ] 4.1 Every §3 test green (hosted CPU lane where no GPU is needed, with GPU and oracle tests skipped there with an explicit reason; a local run on the owner's machine for evaluation, export and private-golden comparisons, decision 028); results attached to `phase1.24_python-api-facade`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
