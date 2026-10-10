## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.8_toolchain-slice, phase1.1_core-device-kernels, phase1.2_core-readback

## 2. Implementation
- [x] 2.1 Define the backend-neutral corner-buffer input with explicit vertex strides (no fixed-stride path)
- [x] 2.2 Implement the UV-space raster pass writing position, normal and tangent-frame buffers (RGBA32F) and island/material id buffers (R32Uint) per set and UV tile
- [x] 2.3 Implement texel-centre coverage and the supersampled conservative coverage mask
- [x] 2.4 Index every buffer by UV tile (tile 1001 in v1)

## 3. Tests
- [x] 3.1 Plane fixture: texel-centre coverage equals the analytic coverage and interpolated positions equal the analytic values at texel centres
- [x] 3.2 Sphere and bevelled-cube fixtures: the conservative mask covers every texel touched by a triangle and contains the texel-centre coverage
- [x] 3.3 Two-material, two-island synthetic mesh: material and island ids are correct per texel
- [x] 3.4 Repeatability: two runs produce byte-identical buffers

## 4. Acceptance
- [x] 4.1 Synthetic-mesh unit tests of the UV raster pass green on DX12 (P1-CORE gate item)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
