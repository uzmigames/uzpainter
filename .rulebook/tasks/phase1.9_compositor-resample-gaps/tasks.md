## 1. Prerequisites
- [x] 1.1 Prerequisite accepted: phase1.8_compositor-sources-projection

## 2. Implementation
- [x] 2.1 Fit the bilinear rounding of the `resample-uv` near-tie (s0/s1 User2) without moving any other value, or prepare an exception proposal with its evidence
  - Root cause: Painter's bilinear is the recording GPU's linear filter of a float32 texture (measured, `bilinear-hardware`; decision 043); `BilinearFilter` on CPU and GPU; `resample-uv` magnification exact, every other golden unchanged.
- [ ] 2.2 Fit Painter's minification prefilter for `BilinearHQ` and `BilinearSharp` (User6, scale 3.3); record further Tier 0 goldens if the existing one does not determine it
  - Recorded (decision 048) and identified (decision 056, report §5): the recording GPU's anisotropic texture unit through Vulkan (maxAnisotropy 4, float32 box mips; Sharp one sample at LOD bias -1.5, HQ a 3 x 3 supersample at gradients / 3).
  - Painter's side identified exactly (decision 060, report §6.1): float32 affine UV, ties-up mip means, HQ's fine-derivative subsamples, accumulation order, level-0 base sample and per-pixel alpha. With the GPU's sampler in the loop, every value of `resample-uv-minify`, `-impulse` and the held-out `resample-uv` user 6 matches (13 566 120 values, both recordings).
  - The texture unit itself has no closed-form software replica (decision 061, report §6.2, `texture_unit.py`): the probe offsets are a non-separable function of the 9-bit gradient mantissas, the weights carry more than 9 bits, the offsets follow the level, and rotations take a 2-D path. Stop point reached for the closed-form search; open until a tabulated axis-aligned replica (the follow-up of decision 061) passes its gates.
  - Tabulated replica (decision 071, report §7, `replica_gates.py`): gates 1 (LOD band, tap split, 4 325 376 weights exact) and 2 (9-bit keys, ddx/ddy roles, (rho, f, sign) geometry, bias 0 = bias -1.5) pass as measured; gate 3 fails: several probes are summed with an unresolved sub-ulp truncation (dark 16-bit bitmaps: 51 of 150 000 samples one ulp low). Open until the multi-probe accumulator is measured (decision 071 item 3).
  - Accumulator identified (decision 083, report §8, `replica_gates.py <work-dir> 3`): each probe truncated to a multiple of 2^(coarse(E) - 36), coarse(E) the exponent with E + 126 lowered to a multiple of 4; the probes of a level in pairs, ordered along the major-axis gradient, the running sum truncated to the pairs' coarse(G) grid before each addition after the first; offset-0 pairs one probe; ties up. Decision 071's datasets (1 170 000 samples, dial 58 848 steps), 23 footprints (1 840 000) and 10 held-out footprints (800 000) all exact. Gate 3 passes; open until the tables are acquired and the replica is validated sample for sample against the hardware (gate 4).
- [ ] 2.3 Implement both in the CPU reference and the projection kernel; lift the `evaluator:unsupported_source` refusal for bilinear minification
  - The near-tie half is implemented (CPU and GPU, bit for bit); the UV offset now precedes the scale and the rotation on both backends (decision 056); the minification half waits for a bit-exact model of 2.2, so the refusal stays (decisions 061, 071). Painter's float32 UV lands with that model (decision 060: no magnifying golden separates it from the double UV).
- [ ] 2.4 Re-derive and publish `parity/semantics/uv-sampling.json`
  - Re-derived and published for 2.1 (`uv-bilinear-repeat` exact), for decision 056 (transform order) for decisions 060-061 and for decision 071 (`uv-bilinear-minification` states Painter's exact arithmetic and stays a gap); to be re-derived again with a bit-exact minification model.

## 3. Tests
- [ ] 3.1 `resample-uv` s0, s1, s3 every user channel exact against both recordings on CPU and GPU
- [ ] 3.2 GPU equals CPU bit for bit on random minifying projection stacks

## 4. Acceptance
- [ ] 4.1 Local DX12 run on the owner's machine exact (decision 028), or an owner-approved exception-register entry (decision 017)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
