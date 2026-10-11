## 1. Prerequisites
- [x] 1.1 Prerequisite accepted: phase1.8_compositor-sources-projection

## 2. Implementation
- [x] 2.1 Fit the bilinear rounding of the `resample-uv` near-tie (s0/s1 User2) without moving any other value, or prepare an exception proposal with its evidence
  - Root cause: Painter's bilinear is the recording GPU's linear filter of a float32 texture (measured, `bilinear-hardware`; decision 043); `BilinearFilter` on CPU and GPU; `resample-uv` magnification exact, every other golden unchanged.
- [ ] 2.2 Fit Painter's minification prefilter for `BilinearHQ` and `BilinearSharp` (User6, scale 3.3); record further Tier 0 goldens if the existing one does not determine it
  - Recorded (decision 048) and identified (decision 056, report §5): the recording GPU's anisotropic texture unit through Vulkan (maxAnisotropy 4, float32 box mips; Sharp one sample at LOD bias -1.5, HQ a 3 x 3 supersample at gradients / 3, alpha = min(footprint - 1, 1)), measured by `tools/parity/vk_sampler_probe` to one code on `resample-uv-minify`, `-impulse` and the held-out `resample-uv` user 6. Not bit for bit: the hardware's anisotropic probes, fixed-point LOD and blend arithmetic, Painter's float32 UV and HQ's anisotropic rule are not modelled; open.
- [ ] 2.3 Implement both in the CPU reference and the projection kernel; lift the `evaluator:unsupported_source` refusal for bilinear minification
  - The near-tie half is implemented (CPU and GPU, bit for bit); the UV offset now precedes the scale and the rotation on both backends (decision 056); the minification half waits for a bit-exact model of 2.2, so the refusal stays.
- [ ] 2.4 Re-derive and publish `parity/semantics/uv-sampling.json`
  - Re-derived and published for 2.1 (`uv-bilinear-repeat` exact) and for decision 056 (transform order, `uv-bilinear-minification` states the mechanism and stays a gap); to be re-derived again with a bit-exact minification model.

## 3. Tests
- [ ] 3.1 `resample-uv` s0, s1, s3 every user channel exact against both recordings on CPU and GPU
- [ ] 3.2 GPU equals CPU bit for bit on random minifying projection stacks

## 4. Acceptance
- [ ] 4.1 Local DX12 run on the owner's machine exact (decision 028), or an owner-approved exception-register entry (decision 017)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
