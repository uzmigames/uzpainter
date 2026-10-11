## 1. Prerequisites
- [ ] 1.1 Prerequisite accepted: phase1.9_compositor-quantisation-profile

## 2. Implementation
- [ ] 2.1 Identify the float32 operation order of Painter's source-over in a partly covered root stack that reproduces the 16 RGB32F/L32F values of `quantisation-thirds` against r1 without moving any other value of `quantisation-thirds` or `blend-inputs` s2; record a further Tier 0 golden if the existing ones do not determine it
- [ ] 2.2 Implement it for 32-bit float channels in the CPU reference and the kernel generator under a new profile id; `painter-12.1-isolated-linear` stays registered and unchanged
- [ ] 2.3 Re-derive and publish `parity/semantics/quantisation-profile.json`; if no order is found, keep the residual published as a divergence and ask the owner (`rulebook_task ask`)

## 3. Tests
- [ ] 3.1 `quantisation-thirds` s0-s3 RGB32F and L32F exact against r1 on CPU and GPU; every other map of both goldens still exact against r1
- [ ] 3.2 GPU equals CPU bit for bit on random partly covered 32-bit float stacks
- [ ] 3.3 Profile pinning: projects stamped `painter-12.1-isolated-linear` evaluate bit for bit as before

## 4. Acceptance
- [ ] 4.1 Local DX12 run on the owner's machine exact against r1 (decision 028, decision 032), or the residual published as a divergence with the owner's decision recorded

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
