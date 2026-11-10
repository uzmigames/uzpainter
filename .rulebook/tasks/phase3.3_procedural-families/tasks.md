## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.6_procedural-feasibility, phase2.10_pilot-tunic-recovery

## 2. Child tasks (mandatory)
- [ ] 2.1 phase3.1_proc-backend-seam accepted
- [x] 2.2 phase3.2_proc-snapshot-backend accepted — archived 2026-11-09 (799a2bb2; acceptance evidence 327f87a9: 20 real-capture snapshots served byte-equal, 35 single-field mismatch checks unavailable)
- [x] 2.3 phase3.2_proc-generator-families accepted — archived 2026-11-10 (decision 425: closed on `generator/occlusion@2`, exact, calibration 40 of 40 and held-out 8 of 8, decisions 423 and 424 accepted in the model panel's root review; the other seven generators moved to grunge item 2.7 and items 2.8 and 2.9 here)
- [ ] 2.4 phase3.2_proc-grunge-families accepted
- [ ] 2.5 phase3.2_proc-filter-families accepted
- [ ] 2.6 phase3.2_proc-material-families accepted
- [ ] 2.7 Moved from `phase3.2_source-substance-presets-inputs` (decision 416): a material `mask_output` other than the output mapped to Height (P413-C r2/r3 one binary16 ulp lower than the exact r1 model; needs a reopen model or an owner decision-032 exception), the split template-channel stores of a Substance resource (BaseColor and any split channel other than User L32F, P413-D), the `source-substance-presets-inputs` r2 (it starts masked) and the material source's default resolution (not in the capture's metadata); until then each refuses before mutation naming this item
- [ ] 2.8 Moved from `phase3.2_proc-generator-families` (decision 425): the Curvature and Mask Editor generators. Equal curvature inputs give unequal outputs at their defaults, so they apply a multi-scale filter of the curvature mesh map (`curvature_fine` … `curvature_huge`; decision 423 §4, `docs/analysis/proc-generator-families/02-calibration-2026-11-09.md` §3), and no public source describes it. Separate the filter with recordings, implement it, then certify both generators with a §6 batch pinned before calibration (decision 222) and the coverage mask of decision 423 §1. Until then both stay release gaps: refused with `family not certified`, records `unavailable`, no alias
- [ ] 2.9 Moved from `phase3.2_proc-generator-families` (decision 425): the Position and World Space Normals generators. They are per-texel at their defaults, but no Assets3D recipe uses them, and the harness needs a recipe parameter set in the §6 matrix (decision 303). Before certification, a recipe must use them, or a decision must change the matrix rule for assets no recipe uses. Then batch, calibrate and certify each one as `generator/occlusion@2` was (decision 424). Until then both stay release gaps: refused with `family not certified`, records `unavailable`, no alias

## 3. Integration
- [ ] 3.1 Run the full Tier 2a certification for every certified asset on the owner's machine (unit sphere, bevelled cube, hat v6 low with its mesh maps × {1024, 2048, 4096} × {defaults, recipe sets, two boundary sets} × {recorded seed, one other}) and on each asset's held-out set, whose hash list was committed before its calibration (decision 222)
- [ ] 3.2 Publish the Tier 2a report under `parity/reports/phase3/` (max/mean/p99 |Δ|, affected-texel counts, parity status per asset, exceptions relied on, calibration and held-out results separately, each asset's certified editable domain; numbers and hashes only)
- [ ] 3.3 Regenerate the capability manifest: certified assets `supported` inside their certified editable domain; the rest of each documented range, uncertified Painter assets and `.sbsar` execution listed as release gaps; `uzpainter assets list --parity` matches the report

## 4. Acceptance
- [ ] 4.1 Acceptance: Tier 2a published; every certified asset exact on its calibration and held-out sets or covered by an owner-approved exception, inside a declared editable domain outside which it is refused; every mandatory child accepted

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
