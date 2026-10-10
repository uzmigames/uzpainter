## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.3_baker-evidence-publication, phase3.2_baker-normal

## 2. Implementation
- [ ] 2.1 Implement `CurvatureMethod` `FromMesh` with `NbSecondary`, `SamplingRadius` and `MaxDistanceRelativeScale`
- [ ] 2.2 Implement `CurvatureMethod` `FromNormalMap` from the baked `Normal` map of the same request
- [ ] 2.3 Implement `AutoMinMax` bounds over the set and `TonemappingBounds`; record the effective bounds in `baked.effective_normalization` and the receipt
- [ ] 2.4 Reuse recorded effective bounds on re-bake and across a linked set when requested
- [ ] 2.5 Author the `Curvature` Tier 2b manifests under `parity/manifests/`

## 3. Tests
- [ ] 3.1 Tier 2b on plane, sphere and bevelled cube with highs for both methods: hit/coverage first, then maps, exact against private goldens
- [ ] 3.2 Tier 2b on the wand and hat low/high/cage pairs, exact against private goldens
- [ ] 3.3 Repeat 3.1 at two thread counts and on each qualified ISA; identical bytes
- [ ] 3.4 Normalisation test: effective bounds recorded; a re-bake reusing them reproduces the map; no silent auto-rescale when `AutoMinMax` is off

## 4. Acceptance
- [ ] 4.1 Acceptance: `Curvature` Tier 2b exact or covered by an owner-approved exception on every fixture; effective bounds recorded and reused

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
