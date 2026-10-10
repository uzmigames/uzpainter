## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.8_tier0-goldens, phase1.3_document-model, phase1.10_compositor-blend-kernels, phase1.8_compositor-sources-projection

## 2. Implementation
- [ ] 2.1 Implement mono-channel mask stacks: background, ordered effects with own mode/opacity, disabled mask as 1, mask opacity and blend
- [ ] 2.2 Implement the fill effect and levels effect in content stacks and in mask stacks, in list order, with the Tier 0 levels clamp rule
- [ ] 2.3 Implement subtraction in masks through the blend kernels and the settled mask precision
- [ ] 2.4 Implement `Mesh` geometry masks multiplying the mask; reject `UVTile` geometry masks as a release gap
- [ ] 2.5 Implement group masks and the per-group Height blend override with its effective value readable
- [ ] 2.6 Publish `parity/semantics/masks-levels.json`

## 3. Tests
- [ ] 3.1 Tier 0 mask goldens: black and white backgrounds, bitmap fill effect, levels, subtraction exact
- [ ] 3.2 Tier 0 levels-clamp goldens exact
- [ ] 3.3 Tier 0 content-effect order goldens exact
- [ ] 3.4 Tier 0 group goldens with masks: `Normal` and `PassThrough` groups with a mask exact
- [ ] 3.5 Tier 0 mask-precision goldens (8 vs 16 bit) exact
- [ ] 3.6 Tier 0 base-value goldens under complementary masks exact (no default bleed, LAY-10)

## 4. Acceptance
- [ ] 4.1 Tier 0 sets of this child exact on the self-hosted GPU runner (DX12); unit tests green

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
