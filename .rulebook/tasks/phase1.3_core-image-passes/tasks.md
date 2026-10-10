## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.8_toolchain-slice, phase1.1_core-device-kernels, phase1.2_core-readback

## 2. Implementation
- [ ] 2.1 Implement jump-flood dilation over a coverage mask with a dilation-distance limit and a documented tie-breaking rule
- [ ] 2.2 Implement the resampling pass with the filter kernel as a parameter; identity size is an exact copy
- [ ] 2.3 Implement mip generation: sRGB-aware, normal-renormalising and alpha-coverage-preserving modes
- [ ] 2.4 Write CPU reference implementations of the same arithmetic for the tests

## 3. Tests
- [ ] 3.1 Dilation on synthetic islands equals the CPU nearest-covered-texel reference (same tie-break) exactly; texels beyond the distance limit stay untouched
- [ ] 3.2 Resampling at identity size is bit-exact; up- and down-sampling equal the CPU reference of the same filter
- [ ] 3.3 sRGB-aware mips equal the CPU decode–filter–encode reference; normal mips are unit length at storage precision; alpha coverage at the test cutoff is preserved
- [ ] 3.4 Every pass produces byte-identical output across two runs

## 4. Acceptance
- [ ] 4.1 Image-pass unit tests green on DX12 (P1-CORE gate item)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
