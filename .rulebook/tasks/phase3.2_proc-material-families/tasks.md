## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_proc-backend-seam

## 2. Implementation
- [ ] 2.1 Discover each material's parameters, outputs, ranges and labels through the documented `Property` API
- [ ] 2.2 Implement felt and burlap with every output channel reachable through `output_mapping`
- [ ] 2.3 Implement leather grain and leather pattern with every output channel reachable through `output_mapping`
- [ ] 2.4 Implement physical-size evaluation (`MaterialPhysicalSize`, `CustomPhysicalSize`) under the project unit rule; record effective units
- [ ] 2.5 Calibrate black-box against private Painter oracles; write the provenance record, per-asset/per-output parity status and Tier 2a manifests

## 3. Tests
- [ ] 3.1 Tier 2a for every output of each material on unit sphere, bevelled cube and hat v6 low × {1024, 2048, 4096} × parameter sets × seeds against private goldens
- [ ] 3.2 Physical-size test: the same material on meshes in two unit scales gives the oracle outputs and records the effective units
- [ ] 3.3 DX12 repeatability: identical bytes across two runs per material

## 4. Acceptance
- [ ] 4.1 Acceptance: every material output exact or covered by an owner-approved exception; otherwise listed as a release gap

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
