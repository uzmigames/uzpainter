## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_proc-backend-seam, phase0.6_procedural-feasibility

## 2. Implementation
- [ ] 2.1 Discover each generator's parameter names, ranges and labels through the documented `Property` API and record them with provenance
- [ ] 2.2 Implement the Curvature, Position, World Space Normals and Ambient Occlusion generators reading mesh maps by usage
- [ ] 2.3 Implement Dirt and Metal Edge Wear from curvature/AO edge and cavity detection plus the shared noise and morphology primitives
- [ ] 2.4 Implement Mask Builder (Legacy) and Mask Editor
- [ ] 2.5 Calibrate each generator black-box against private Painter oracles; write the family provenance record (sources, author, corpus id, residuals) and per-asset parity status
- [ ] 2.6 Register compatibility aliases for the Painter names and author the Tier 2a manifests under `parity/manifests/`

## 3. Tests
- [ ] 3.1 Tier 2a for every generator on unit sphere, bevelled cube and hat v6 low × {1024, 2048, 4096} × parameter sets × seeds against private goldens
- [ ] 3.2 Loud-failure test: a generator with a missing or invalid mesh map fails evaluation, nothing is substituted
- [ ] 3.3 DX12 repeatability: identical bytes across two runs for each generator

## 4. Acceptance
- [ ] 4.1 Acceptance: every generator exact or covered by an owner-approved exception; any other generator listed as a release gap

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
