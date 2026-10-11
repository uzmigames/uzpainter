## 1. Prerequisites
- [x] 1.1 Prerequisite accepted: phase1.9_compositor-quantisation-profile (archived 2026-10-11)

## 2. Implementation
- [ ] 2.1 Identify the float32 operation order of Painter's source-over in a partly covered root stack that reproduces the 16 RGB32F/L32F values of `quantisation-thirds` against r1 without moving any other value of `quantisation-thirds` or `blend-inputs` s2; record a further Tier 0 golden if the existing ones do not determine it
- [ ] 2.2 Implement it for 32-bit float channels in the CPU reference and the kernel generator under a new profile id; `painter-12.1-isolated-linear` stays registered and unchanged
- [x] 2.3 Re-derive and publish `parity/semantics/quantisation-profile.json`; if no order is found, keep the residual published as a divergence and ask the owner (`rulebook_task ask`) (published with the new entry `quantisation-isolated-half-alpha`; order not found, divergence kept, owner question q1)

## 3. Tests
- [ ] 3.1 `quantisation-thirds` s0-s3 RGB32F and L32F exact against r1 on CPU and GPU; every other map of both goldens still exact against r1
- [x] 3.2 GPU equals CPU bit for bit on random partly covered 32-bit float stacks (`gpu-vs-cpu`, current profile, every format)
- [x] 3.3 Profile pinning: projects stamped `painter-12.1-isolated-linear` evaluate bit for bit as before

## 4. Acceptance
- [ ] 4.1 Local DX12 run on the owner's machine exact against r1 (decision 028, decision 032), or the residual published as a divergence with the owner's decision recorded

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass (tests/evaluator 265 passed after merging main; tests/parity 696 passed)

## Status (2026-10-11)
- 2.1, 2.2, 3.1: the float32 order was not identified (decision 044, `parity/reports/phase1/compositor-float32-residual.md`); found and shipped instead as profile `painter-12.1-isolated-half-alpha`: the sRGB8 coverage written through binary16 (`group-masks` s2-s3 sRGB8 exact) and plain 32-bit float uniform colours. A diagnostic recording is specified in the report.
- 4.1: waits for the owner's decision on q1 (exception or recording).
