## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.8_tier0-goldens, phase1.3_document-model, phase1.10_compositor-blend-kernels, phase1.8_compositor-sources-projection

## 2. Implementation
- [x] 2.1 Implement mono-channel mask stacks: background, ordered effects with own mode/opacity, disabled mask as 1, mask opacity and blend
- [x] 2.2 Implement the fill effect and levels effect in content stacks and in mask stacks, in list order, with the Tier 0 levels clamp rule
- [x] 2.3 Implement subtraction in masks through the blend kernels and the settled mask precision
- [x] 2.4 Implement `Mesh` geometry masks multiplying the mask; reject `UVTile` geometry masks as a release gap
- [x] 2.5 Implement group masks and the per-group Height blend override with its effective value readable
- [x] 2.6 Publish `parity/semantics/masks-levels.json`

## 3. Tests
- [x] 3.1 Tier 0 mask goldens: black and white backgrounds, bitmap fill effect, levels, subtraction exact
- [x] 3.2 Tier 0 levels-clamp goldens exact
- [x] 3.3 Tier 0 content-effect order goldens exact (scope split, decision 069: `effect-order` s6 exact on CPU and DX12 against both recordings; the fill/levels list order is a native unit case, not golden-verified; s0–s5 and s7 hold the Blur filter, a P3-PROC release gap, and are covered by `phase3.2_proc-filter-families` item 3.4; the fit keeps `content-effect-order` as a gap)
- [x] 3.4 Tier 0 group goldens with masks: `Normal` and `PassThrough` groups with a mask exact (`group-masks` s2–s3 under `painter-12.1-isolated-coverage-weights`, decisions 058, 059; `semantics-ui/group-passthrough-masks` s0–s3, decisions 054, 066; both recordings, CPU and DX12)
- [x] 3.5 Tier 0 mask-precision goldens (8 vs 16 bit) exact
- [x] 3.6 Tier 0 base-value goldens under complementary masks exact (no default bleed, LAY-10)

## 4. Acceptance
- [x] 4.1 Tier 0 sets of this child exact in a local DX12 run on the owner's machine (decision 028; the local run report is the evidence); unit tests green (`parity/reports/phase1/compositor-mask-effects.md`, re-run on main `4949d28`)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass (`tests/evaluator/test_compositor_mask_effects.py` and the PassThrough golden test: 39 passed on CPU and DX12; ruff, mypy strict clean)
