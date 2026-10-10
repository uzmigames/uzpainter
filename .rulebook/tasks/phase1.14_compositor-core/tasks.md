## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.4_render-core-layer, phase1.3_document-model, phase1.7_mesh-loader, phase0.8_tier0-goldens

## 2. Children (each accepted before this parent closes)
- [ ] 2.1 `phase1.5_compositor-tile-dag` accepted
- [ ] 2.2 `phase1.8_compositor-sources-projection` accepted
- [ ] 2.3 `phase1.9_compositor-quantisation-profile` accepted
- [ ] 2.4 `phase1.10_compositor-blend-kernels` accepted
- [ ] 2.5 `phase1.11_compositor-mask-effects` accepted
- [ ] 2.6 `phase1.12_compositor-height-normal` accepted
- [ ] 2.7 `phase1.13_compositor-diagnostics` accepted
- [ ] 2.8 Register every Phase 1 node kind, source, projection and blend mode as `supported` with its Tier 0 evidence id, and every excluded one as `release-gap`, in the capability inventory of `phase1.2_docmodel-capability-manifest`

## 3. Tests
- [ ] 3.1 Run the union of the children's Tier 0 golden sets in one pass in a local DX12 run on the owner's machine (decision 028) and publish, in the local run report used as evidence, the comparison numbers (max |Δ|, mean |Δ|, p99, differing-texel count and percentage) next to oracle stability and UzPainter repeatability
- [ ] 3.2 Repeatability lane: the same Tier 0 inputs evaluated twice in separate processes give byte-identical channel rasters
- [ ] 3.3 Requesting an excluded feature (for example a triplanar projection or a compare mask) raises `NotYetSupported` before any mutation

## 4. Acceptance
- [ ] 4.1 Acceptance (P1-COMPOSITOR gate): Tier 0 semantics exact for the implemented subset; report written to `parity/reports/phase1/` (numbers and hashes only) for the G1 gate record

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
