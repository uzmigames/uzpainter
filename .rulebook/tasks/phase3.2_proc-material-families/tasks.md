## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_proc-backend-seam

## 2. Implementation
- [ ] 2.1 Discover each material's parameters, outputs, ranges and labels through the documented `Property` API
- [ ] 2.2 Implement felt and burlap with every output channel reachable through `output_mapping`
- [ ] 2.3 Implement leather grain and leather pattern with every output channel reachable through `output_mapping`
- [ ] 2.4 Implement physical-size evaluation (`MaterialPhysicalSize`, `CustomPhysicalSize`) under the project unit rule; record effective units
- [ ] 2.5 Calibrate black-box against private Painter oracles; write the provenance record, per-asset/per-output parity status and Tier 2a manifests; calibration starts only after item 2.6 has declared the domain and committed the held-out hash list, and never reads held-out oracles
- [ ] 2.6 Before calibration, declare each asset's certified editable domain (parameter ranges and joint constraints, seed policy, geometry inputs, resolutions, formats and colour spaces; `05-procedural-content.md` §6, decision 222) and reserve its held-out set (meshes, interior parameter points, seeds and a resolution outside the calibration set), recorded in the same batch with its hash list committed before calibration starts; a held-out case used to change a fit is moved to the calibration set and replaced (decision 222)

## 3. Tests
- [ ] 3.1 Tier 2a for every output of each material on unit sphere, bevelled cube and hat v6 low × {1024, 2048, 4096} × parameter sets × seeds against private goldens (the calibration set), and on the held-out set reserved in 2.6, reported separately
- [ ] 3.2 Physical-size test: the same material on meshes in two unit scales gives the oracle outputs and records the effective units
- [ ] 3.3 DX12 repeatability: identical bytes across two runs per material
- [ ] 3.4 Domain-refusal test: a parameter, seed, mesh-map input and resolution just outside the declared domain each raise `UnsupportedProcedural{reason: "outside certified domain"}` before mutation, with nothing clamped or substituted

## 4. Acceptance
- [ ] 4.1 Acceptance: every material output exact on its calibration and held-out sets, or covered by an owner-approved exception, inside its declared domain; the rest of its documented range listed as a release gap

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
