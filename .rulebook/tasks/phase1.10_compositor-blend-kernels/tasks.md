## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.8_tier0-goldens, phase1.4_render-core-layer, phase1.9_compositor-quantisation-profile

## 2. Implementation
- [ ] 2.1 Fit each of the 32 modes against the Tier 0 sweeps, starting from the public candidate definitions, and record formula, clamping and colour space
- [ ] 2.2 Implement the 32 kernels per channel format with per-channel mode and opacity and `precise` arithmetic
- [ ] 2.3 Publish `parity/semantics/blend-modes.json` with public source and residual per mode
- [ ] 2.4 Mark any mode not yet exact as `release-gap` in the capability inventory; propose an exception only with evidence per `docs/architecture/14-parity-testing.md` §5

## 3. Tests
- [ ] 3.1 Tier 0 blend goldens: every mode × value sweep × opacity sweep exact at 16 bit
- [ ] 3.2 Per-channel blending: different modes on BaseColor and Roughness of one layer equal their goldens
- [ ] 3.3 Provenance check: every mode in `blend-modes.json` names a public source and a residual

## 4. Acceptance
- [ ] 4.1 Tier 0 blend goldens exact for all 32 modes in a local DX12 run on the owner's machine (decision 028; the local run report is the evidence), or each remaining mode listed as `release-gap` with an owner decision pending

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
