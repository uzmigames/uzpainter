## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.4_render-core-layer, phase1.3_document-model, phase1.7_mesh-loader, phase0.8_tier0-goldens
  - All four archived (2026-10-10, 2026-10-11).

## 2. Children (each accepted before this parent closes)
- [x] 2.1 `phase1.5_compositor-tile-dag` accepted (archived 2026-10-11)
- [x] 2.2 `phase1.8_compositor-sources-projection` accepted (archived 2026-10-11; its follow-up `phase1.9_compositor-resample-gaps`, bilinear minification, archived 2026-10-12)
- [x] 2.3 `phase1.9_compositor-quantisation-profile` accepted (archived 2026-10-11, with its follow-up `phase1.10_compositor-float32-residual`)
- [x] 2.4 `phase1.10_compositor-blend-kernels` accepted (archived 2026-10-11; its follow-up `phase1.11_compositor-blend-gaps` archived 2026-10-11, decision 073: every blend mode exact)
- [x] 2.5 `phase1.11_compositor-mask-effects` accepted (archived 2026-10-11)
- [x] 2.6 `phase1.12_compositor-height-normal` accepted (archived 2026-10-11, decisions 079, 080)
- [x] 2.7 `phase1.13_compositor-diagnostics` accepted (archived 2026-10-12)
- [x] 2.8 Register every Phase 1 node kind, source, projection and blend mode as `supported` with its Tier 0 evidence id, and every excluded one as `release-gap`, in the capability inventory of `phase1.2_docmodel-capability-manifest`
  - `tools/capabilities/compositor-capabilities.json` (decision 081): context `compositor`/`compositor:<case>`, 54 `supported` with current-envelope goldens, 42 `release-gap` naming their owner task (Blur and filter effects, minification, instances, ...); evidence resolves through the current envelope (decision 037).
- [ ] 2.9 (decisions 108 §4 and 117, from phase1.24_python-api-facade item 3.1) Record P20-A (fill channel defaults) and P20-B (dense sRGB decode), the recordings of decision 107, then fit the facade's colour tables to them exactly: `DEFAULT_SOURCES` (`python/uzpainter_facade/nodes.py`), `default_bitmap_space`, `available_bitmap_spaces` and the float32 sRGB decode (`colour.py`)
  - Acceptance: every P20-A and P20-B output equal to its golden, both recordings; the `NotYetSupported` refusals naming P20-A and the exclusion `readback/get_source/29/BaseColor` of `export-ocio-encode-legacy` removed, their tests turned into exact comparisons; `phase1-reload-resources` recording 1 s9 and s12 exact in `test_pyapi_lifecycle_tier0.py`.
  - Blocked only by the two recordings (owner action); `parity/reports/phase1/python-api-facade.md` §3 names this item as the owner.

## 3. Tests
- [ ] 3.1 Run the union of the children's Tier 0 golden sets in one pass in a local DX12 run on the owner's machine (decision 028) and publish, in the local run report used as evidence, the comparison numbers (max |Δ|, mean |Δ|, p99, differing-texel count and percentage) next to oracle stability and UzPainter repeatability
  - Harness: `python tests/evaluator/union_run.py --label final` (two passes in separate processes; `observe` at every child comparison site; verdicts by `tools/parity/verdict.py`). Interim run at `de66bfd` in `parity/reports/phase1/compositor-core.md`: 57 goldens, 1434 maps, 2834 comparisons, every one exact (1445 of 1445 against r1), 31 maps with an unstable oracle (r1 target, decision 032), 1456 of 1456 rasters byte-identical across the passes. Open: the final run once phase1.9_compositor-resample-gaps, phase1.12_compositor-height-normal and phase1.13_compositor-diagnostics close (18 current-envelope goldens are not yet compared by any child).
- [x] 3.2 Repeatability lane: the same Tier 0 inputs evaluated twice in separate processes give byte-identical channel rasters
  - `tests/evaluator/test_compositor_core.py`: 17 channel specs and 2 virtual-normal specs from the public manifests, CPU and GPU (38 cases); the union run also compares every evaluated raster across its two passes.
- [x] 3.3 Requesting an excluded feature (for example a triplanar projection or a compare mask) raises `NotYetSupported` before any mutation
  - Decision 082: `core::NotYetSupported` (transaction error type), `evaluator::RequireSupported` (`support.h`), `ErrorClassName` (`unsupported_*` → NotYetSupported; diagnostics' argument refusals → new `invalid_argument`); native case `not-yet-supported` (30 features).

## 4. Acceptance
- [ ] 4.1 Acceptance (P1-COMPOSITOR gate): Tier 0 semantics exact for the implemented subset; report written to `parity/reports/phase1/` (numbers and hashes only) for the G1 gate record

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
  - `tools/capabilities/README.md`, `src/evaluator/EVALUATOR.md`, `src/uzp_core/TRANSACTIONS.md`, decisions 081, 082, `parity/reports/phase1/compositor-core.md`.
- [x] 5.2 Write tests covering the new behavior
  - `tests/evaluator/test_compositor_core.py`, native case `not-yet-supported`, `tests/capabilities/test_capabilities.py` (compositor registrations), `tests/evaluator/union_run.py` (the union run).
- [x] 5.3 Run tests and confirm they pass
  - At `f74057a`: `tests/uzp_core`, `tests/capabilities`, `tests/parity/fit` 160 passed; `tests/evaluator` 364 passed (35 min, CPU and DX12); `zig build painter` and `evaluator-tests` with `-Werror`; ruff and mypy strict clean.
