## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_proc-backend-seam, phase0.6_procedural-feasibility

## 2. Implementation
- [ ] 2.1 Discover each generator's parameter names, ranges and labels through the documented `Property` API and record them with provenance
- [ ] 2.2 Implement the Curvature, Position, World Space Normals and Ambient Occlusion generators reading mesh maps by usage
- [ ] 2.3 Implement Dirt and Metal Edge Wear from curvature/AO edge and cavity detection plus the shared noise and morphology primitives
- [ ] 2.4 Implement Mask Builder (Legacy) and Mask Editor
- [ ] 2.5 Calibrate each generator black-box against private Painter oracles; write the family provenance record (sources, author, corpus id, residuals) and per-asset parity status; calibration starts only after item 2.7 has declared the domain and committed the held-out hash list, and never reads held-out oracles
- [ ] 2.6 Register compatibility aliases for the Painter names and author the Tier 2a manifests under `parity/manifests/`
- [ ] 2.7 Before calibration, declare each asset's certified editable domain (parameter ranges and joint constraints, seed policy, geometry inputs, resolutions, formats and colour spaces; `05-procedural-content.md` §6, decision 222) and reserve its held-out set (meshes, interior parameter points, seeds and a resolution outside the calibration set), recorded in the same batch with its hash list committed before calibration starts; a held-out case used to change a fit is moved to the calibration set and replaced (decision 222)

## 3. Tests
- [ ] 3.1 Tier 2a for every generator on unit sphere, bevelled cube and hat v6 low × {1024, 2048, 4096} × parameter sets × seeds against private goldens (the calibration set), and on the held-out set reserved in 2.7, reported separately
- [ ] 3.2 Loud-failure test: a generator with a missing or invalid mesh map fails evaluation, nothing is substituted
- [ ] 3.3 DX12 repeatability: identical bytes across two runs for each generator
- [ ] 3.4 Domain-refusal test: a parameter, seed, mesh-map input and resolution just outside the declared domain each raise `UnsupportedProcedural{reason: "outside certified domain"}` before mutation, with nothing clamped or substituted

## 4. Acceptance
- [ ] 4.1 Acceptance: every generator exact on its calibration and held-out sets, or covered by an owner-approved exception, inside its declared domain; the rest of its documented range and any other generator listed as release gaps

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
