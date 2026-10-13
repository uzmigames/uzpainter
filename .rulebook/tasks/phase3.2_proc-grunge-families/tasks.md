## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_proc-backend-seam

## 2. Implementation
- [ ] 2.1 Build the asset inventory from the body and hat recipes (grunge, dirt, spots, scratches, rust, humidity, cracks) plus `fabric_linen`, with aliases and the recorded parameter sets
- [ ] 2.2 Discover each asset's parameter names, ranges and labels through the documented `Property` API
- [ ] 2.3 Implement each asset on the shared primitive library with tiling, seed and parameters
- [ ] 2.4 Calibrate black-box against private Painter oracles; write the family provenance record and per-asset parity status; calibration starts only after item 2.6 has declared the domain and committed the held-out hash list, and never reads held-out oracles
- [ ] 2.5 Author the Tier 2a manifests under `parity/manifests/`
- [ ] 2.6 Before calibration, declare each asset's certified editable domain (parameter ranges and joint constraints, seed policy, geometry inputs, resolutions, formats and colour spaces; `05-procedural-content.md` §6, decision 222) and reserve its held-out set (meshes, interior parameter points, seeds and a resolution outside the calibration set), recorded in the same batch with its hash list committed before calibration starts; a held-out case used to change a fit is moved to the calibration set and replaced (decision 222)

## 3. Tests
- [ ] 3.1 Tier 2a for every inventoried asset on unit sphere, bevelled cube and hat v6 low × {1024, 2048, 4096} × parameter sets × seeds against private goldens (the calibration set), and on the held-out set reserved in 2.6, reported separately
- [ ] 3.2 Tiling test: outputs wrap seamlessly at the tile boundary where the asset tiles
- [ ] 3.3 Seed test: two seeds give the oracle's two outputs; the same seed repeats byte-identically on DX12
- [ ] 3.4 Domain-refusal test: a parameter, seed, mesh-map input and resolution just outside the declared domain each raise `UnsupportedProcedural{reason: "outside certified domain"}` before mutation, with nothing clamped or substituted

## 4. Acceptance
- [ ] 4.1 Acceptance: every inventoried asset exact on its calibration and held-out sets, or covered by an owner-approved exception, inside its declared domain; the rest of its documented range and any other asset listed as release gaps

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
