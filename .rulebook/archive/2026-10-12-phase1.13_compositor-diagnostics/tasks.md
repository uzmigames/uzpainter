## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.11_compositor-mask-effects, phase1.12_compositor-height-normal (all three archived: phase1.3 on 2026-10-10, phase1.11 and phase1.12 on 2026-10-11, decisions 079, 080; the diagnostics use only phase1.12's merged code and inherit its refusals)

## 2. Implementation
- [x] 2.1 Implement `isolate(layer)` with atomic visibility restore, including on failure (`IsolateOn`: the node is hidden in a private copy of the revision, never committed; decision 075)
- [x] 2.2 Implement `contribution(layer)` as the difference between full and isolated evaluation (`ContributionOn`: float32 full − isolated per sample, channels and virtual normal maps)
- [x] 2.3 Implement `material_views(mask)` for ID, BaseColor, Height, Normal, Roughness and Metallic (`MaterialViewsOn`: the effective mask, the ID mesh map and the channel views, leaks against the modal ID colour and the solo evaluation; decision 075)
- [x] 2.4 Implement `region_stats(map, mask)` over mask regions (`ComputeRegionStats`, `RegionStatsJson`)
- [x] 2.5 Expose every diagnostic as a source the export plan can name (`srcMapType` `diagnosticMap`, `SourceName`/`ParseSourceName`, `EvaluateDiagnosticOn`, `Evaluator::Diagnose`; decision 076)

## 3. Tests
- [x] 3.1 Isolation restores the exact prior visibility state, also when the evaluation fails midway (CPU and DX12, failing at tile 1 of 2)
- [x] 3.2 `contribution` equals full evaluation minus isolated evaluation texel for texel (six channel formats, eight nodes, both virtual normal maps)
- [x] 3.3 `material_views` returns the per-channel values under a material mask on a two-material fixture and detects an injected leak (plus an ID spill and a nested material)
- [x] 3.4 `region_stats` equals a CPU computation over the same map and mask (independent Python computation, double for double)
- [x] 3.5 Diagnostics outputs are byte-identical across two runs (51 CPU outputs; 129 GPU outputs equal to the CPU and repeated)

## 4. Acceptance
- [x] 4.1 Diagnostics tests green in a local DX12 run on the owner's machine (decision 028; the local run report is the evidence: `parity/reports/phase1/compositor-diagnostics.md`)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation (`src/evaluator/EVALUATOR.md`, `04-layer-stack-and-compositing.md` §8, `08-export.md` §6, decisions 075, 076)
- [x] 5.2 Write tests covering the new behavior (`uzp-evaluator-tests diagnostics`, `diagnostics-gpu-vs-cpu`, `tests/evaluator/test_compositor_diagnostics.py`)
- [x] 5.3 Run tests and confirm they pass (`python -m pytest tests/evaluator` after merging main `d4c9cfc`: 308 passed, CPU and DX12; `diagnostics` 18 and `diagnostics-gpu-vs-cpu` 2 checks; ruff, mypy strict clean)
