## 1. Prerequisites
- [x] 1.1 Inputs available: phase1.8_compositor-sources-projection and phase1.12_compositor-height-normal (archived); `tier0/semantics/height-normal-resolution-4096` admitted (dff6765f, decision 400)

## 2. Implementation
- [ ] 2.1 Fit Painter's bilinear magnification of the signed heights at 4096 px against `height-normal-resolution-4096` s0 (48,126 Height texels off under the 512-2048 rule, decision 400 §2); request further recordings if one golden does not separate the candidates
- [ ] 2.2 Implement it on the CPU reference and the GPU kernel, operation for operation, and in `tools/parity/fit/normal.py` `magnified`
- [ ] 2.3 Lift decision 400's refusal in `CheckSampling` only for what 2.1 makes exact; keep the rest refused with this task as the owner

## 3. Tests
- [ ] 3.1 `height-normal-resolution-4096` s0-s3: Height, Normal_OpenGL and Normal_DirectX equal r1 on every texel, and r2 wherever r2 equals r1, on DX12 and the CPU (decision 028)
- [ ] 3.2 The refusal stays for every unrecorded magnification (native `height-normal` case)

## 4. Acceptance
- [ ] 4.1 Acceptance: the magnification exact on its recordings; the refusal lifted for that scope only

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
