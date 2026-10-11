## 1. Prerequisites
- [ ] 1.1 Prerequisite accepted: phase1.8_compositor-sources-projection

## 2. Implementation
- [ ] 2.1 Fit the bilinear rounding of the `resample-uv` near-tie (s0/s1 User2) without moving any other value, or prepare an exception proposal with its evidence
- [ ] 2.2 Fit Painter's minification prefilter for `BilinearHQ` and `BilinearSharp` (User6, scale 3.3); record further Tier 0 goldens if the existing one does not determine it
- [ ] 2.3 Implement both in the CPU reference and the projection kernel; lift the `evaluator:unsupported_source` refusal for bilinear minification
- [ ] 2.4 Re-derive and publish `parity/semantics/uv-sampling.json`

## 3. Tests
- [ ] 3.1 `resample-uv` s0, s1, s3 every user channel exact against both recordings on CPU and GPU
- [ ] 3.2 GPU equals CPU bit for bit on random minifying projection stacks

## 4. Acceptance
- [ ] 4.1 Local DX12 run on the owner's machine exact (decision 028), or an owner-approved exception-register entry (decision 017)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
