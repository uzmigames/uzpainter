## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_proc-backend-seam

## 2. Implementation
- [ ] 2.1 Discover each filter's parameter names, ranges and labels through the documented `Property` API
- [ ] 2.2 Implement Sharpen and grayscale conversion as filter-effect kernels on the current layer content
- [ ] 2.3 Map the Levels filter onto the native levels effect with its Tier 0 semantics
- [ ] 2.4 Enforce the Filter-effect `ResolutionOverride` restriction
- [ ] 2.5 Calibrate black-box against private Painter oracles; write the provenance record, per-asset parity status and Tier 2a manifests

## 3. Tests
- [ ] 3.1 Tier 2a for Sharpen, grayscale conversion and Levels on unit sphere, bevelled cube and hat v6 low × {1024, 2048, 4096} × parameter sets against private goldens, with authored input content
- [ ] 3.2 Effect-order test: a filter computes from the content produced by the effects below it and blends with its own mode and opacity
- [ ] 3.3 `ResolutionOverride` on a filter-used source raises as documented
- [ ] 3.4 Tier 0 `effect-order` s0–s5, s7 exact (content-effect order of fill and levels effects around Blur; phase1.11_compositor-mask-effects item 3.3)

## 4. Acceptance
- [ ] 4.1 Acceptance: each filter exact or covered by an owner-approved exception; otherwise listed as a release gap

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
