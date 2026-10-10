## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.11_compositor-mask-effects, phase1.12_compositor-height-normal

## 2. Implementation
- [ ] 2.1 Implement `isolate(layer)` with atomic visibility restore, including on failure
- [ ] 2.2 Implement `contribution(layer)` as the difference between full and isolated evaluation
- [ ] 2.3 Implement `material_views(mask)` for ID, BaseColor, Height, Normal, Roughness and Metallic
- [ ] 2.4 Implement `region_stats(map, mask)` over mask regions
- [ ] 2.5 Expose every diagnostic as a source the export plan can name

## 3. Tests
- [ ] 3.1 Isolation restores the exact prior visibility state, also when the evaluation fails midway
- [ ] 3.2 `contribution` equals full evaluation minus isolated evaluation texel for texel
- [ ] 3.3 `material_views` returns the per-channel values under a material mask on a two-material fixture and detects an injected leak
- [ ] 3.4 `region_stats` equals a CPU computation over the same map and mask
- [ ] 3.5 Diagnostics outputs are byte-identical across two runs

## 4. Acceptance
- [ ] 4.1 Diagnostics tests green on the self-hosted GPU runner (DX12)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
