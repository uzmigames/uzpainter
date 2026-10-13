## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.6_procedural-feasibility, phase2.10_pilot-tunic-recovery

## 2. Child tasks (mandatory)
- [ ] 2.1 phase3.1_proc-backend-seam accepted
- [ ] 2.2 phase3.2_proc-snapshot-backend accepted
- [ ] 2.3 phase3.2_proc-generator-families accepted
- [ ] 2.4 phase3.2_proc-grunge-families accepted
- [ ] 2.5 phase3.2_proc-filter-families accepted
- [ ] 2.6 phase3.2_proc-material-families accepted

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
