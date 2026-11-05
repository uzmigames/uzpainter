## 1. Prerequisites
- [x] 1.1 Inputs available: phase1.8_compositor-sources-projection and phase1.12_compositor-height-normal (archived); `tier0/semantics/height-normal-resolution-4096` admitted (dff6765f, decision 400)

## 2. Implementation
- [x] 2.1 Fit Painter's bilinear magnification of the signed heights at 4096 px against `height-normal-resolution-4096` s0 (48,126 Height texels off under the 512-2048 rule, decision 400 §2); request further recordings if one golden does not separate the candidates
  - 2026-11-05 (decision 402): exact, no new recording needed. The 48,126 s0 texels were the Python model's error: `magnified` kept the exact dyadic weights, while Painter (and the evaluator's CPU and GPU filters, already) round the corner weight to 1/256, w11 = (fx fy + 127) >> 8, w10 = fx - w11, w01 = fy - w11, w00 = 256 - fx - fy + w11, then `BilinearFilter`. Every off texel sat where both axes vary; at 16x fx fy is k/1024, at 2x-8x a multiple of 1/256. Candidates (s0 texels off): exact weights 48,126; w11 rounded to 1/256 0; all four rounded 0; w11 floored/ceiled 62,118/62,060; all floored/ceiled ~16.7 M; 1/512 ties-even 0 (same rounding here), ties up/down ~16.7 M; float32 product sums 643/1,286. The model gives s0-s3 Height, both virtual maps and the Normal channel equal to r1 everywhere and r2 where r2 = r1.
- [x] 2.2 Implement it on the CPU reference and the GPU kernel, operation for operation, and in `tools/parity/fit/normal.py` `magnified`
  - 2026-11-05: `magnified` mirrors `ProjectTexel` + `BilinearFilter` (`bilinear_filter`, `resample.bilinear_weights`), commit 48065941; fit entry `height-magnification-4096` exact, republished. The CPU reference and `evaluator_project.hlsl` already compute exactly this (8-bit fixed point, w11 rounded): no native arithmetic change.
- [x] 2.3 Lift decision 400's refusal in `CheckSampling` only for what 2.1 makes exact; keep the rest refused with this task as the owner
  - 2026-11-05 (decision 402): `CheckSampling` admits above 2048 px only the recorded case — 16x of a square 256 px bitmap, identity projection, BilinearHQ, Repeat, square 4096 set; the rest stays refused naming decision 400 and this task. Widening needs the recordings of decision 402 §4 (ramps at 512/1024/2048/128 px on 4096; UV scale 2 + offset; BilinearSharp).

## 3. Tests
- [x] 3.1 `height-normal-resolution-4096` s0-s3: Height, Normal_OpenGL and Normal_DirectX equal r1 on every texel, and r2 wherever r2 equals r1, on DX12 and the CPU (decision 028)
  - 2026-11-05: `test_recorded_inputs_exact[cpu|dx12-...-resolution-4096]` and `test_height_magnification_at_4096_equals_painter` passed (r2 of the virtual maps of s1 and s2 differs from r1, decision 400, and is not compared).
- [x] 3.2 The refusal stays for every unrecorded magnification (native `height-normal` case)
  - 2026-11-05: native `height-normal` (`test_height_normal_on_the_cpu`): 32x, anisotropic, tiled 8x and BilinearSharp 16x at 4096 refused, the recorded 16x evaluates; `test_unrecorded_height_magnification_at_4096_is_refused` passed.

## 4. Acceptance
- [x] 4.1 Acceptance: the magnification exact on its recordings; the refusal lifted for that scope only
  - 2026-11-05: holds on the recording (items 3.1, 3.2; decision 402).

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
  - 2026-11-05: decision 402; `docs/architecture/04-layer-stack-and-compositing.md`, `08-export.md`; `projection_uv.h` comments; fit entry `height-magnification-4096`.
- [x] 5.2 Write tests covering the new behavior
  - 2026-11-05: `test_magnification_rounds_the_corner_weight_to_eight_bits`, the two 4096 tests above, the 4096 golden in `RECORDED_SETS`, native checks.
- [x] 5.3 Run tests and confirm they pass
  - 2026-11-05: affected tests only (ruff, mypy first): 5 evaluator tests (CPU and DX12) and 18 fit tests passed.
