## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.8_toolchain-slice, phase1.1_core-device-kernels, phase1.2_core-readback

## 2. Implementation
- [x] 2.1 Implement jump-flood dilation over a coverage mask with a dilation-distance limit and a documented tie-breaking rule
- [x] 2.2 Implement the resampling pass with the filter kernel as a parameter; identity size is an exact copy
- [x] 2.3 Implement mip generation: sRGB-aware, normal-renormalising and alpha-coverage-preserving modes
- [x] 2.4 Write CPU reference implementations of the same arithmetic for the tests

## 3. Tests
- [x] 3.1 Dilation on synthetic islands equals the CPU nearest-covered-texel reference (same tie-break) exactly; texels beyond the distance limit stay untouched
- [x] 3.2 Resampling at identity size is bit-exact; up- and down-sampling equal the CPU reference of the same filter
- [x] 3.3 sRGB-aware mips equal the CPU decode–filter–encode reference; normal mips are unit length at storage precision; alpha coverage at the test cutoff is preserved
- [x] 3.4 Every pass produces byte-identical output across two runs

## 4. Acceptance
- [x] 4.1 Image-pass unit tests green on DX12 (P1-CORE gate item)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
