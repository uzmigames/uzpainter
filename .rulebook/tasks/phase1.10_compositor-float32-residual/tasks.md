## 1. Prerequisites
- [x] 1.1 Prerequisite accepted: phase1.9_compositor-quantisation-profile (archived 2026-10-11)

## 2. Implementation
- [x] 2.1 Identify the float32 operation order of Painter's source-over in a partly covered root stack that reproduces the 16 RGB32F/L32F values of `quantisation-thirds` against r1 without moving any other value of `quantisation-thirds` or `blend-inputs` s2; record a further Tier 0 golden if the existing ones do not determine it (identified on the diagnostic golden `group-coverage-order`: the coverage weights, `ws = ao - ab`; plus the fused read-out and the grey of unrounded components; decision 058)
- [x] 2.2 Implement it for 32-bit float channels in the CPU reference and the kernel generator under a new profile id; `painter-12.1-isolated-linear` stays registered and unchanged (profile `painter-12.1-isolated-coverage-weights`, every channel format; with decision 059's sRGB8 coverage rule)
- [x] 2.3 Re-derive and publish `parity/semantics/quantisation-profile.json`; if no order is found, keep the residual published as a divergence and ask the owner (`rulebook_task ask`) (entry `quantisation-isolated-coverage-weights` selected, exact against r1; `masks-levels.json` entries `group-masks` exact and `group-coverage-order` new)

## 3. Tests
- [x] 3.1 `quantisation-thirds` s0-s3 RGB32F and L32F exact against r1 on CPU and GPU; every other map of both goldens still exact against r1 (also `group-masks` s2-s3 and `group-coverage-order` s0-s3, every map, both recordings)
- [x] 3.2 GPU equals CPU bit for bit on random partly covered 32-bit float stacks (`gpu-vs-cpu`, current profile, every format)
- [x] 3.3 Profile pinning: projects stamped `painter-12.1-isolated-linear` evaluate bit for bit as before

## 4. Acceptance
- [x] 4.1 Local DX12 run on the owner's machine exact against r1 (decision 028, decision 032), or the residual published as a divergence with the owner's decision recorded (exact; `parity/reports/phase1/compositor-float32-residual.md`)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass (tests/evaluator 265 passed after merging main; tests/parity 696 passed)

## Status (2026-10-11)
- First round (decision 044): the float32 order was not identified; the sRGB8 binary16 coverage and plain 32-bit float uniform colours shipped as profile `painter-12.1-isolated-half-alpha`. q1 answered: keep the divergence, record the diagnostic golden.
- Second round (decisions 058, 059): the diagnostic golden `group-coverage-order` identifies the order; profile `painter-12.1-isolated-coverage-weights` makes `quantisation-thirds`, `blend-inputs` s2, `group-masks` s2-s3 and `group-coverage-order` exact on every map, CPU and GPU.
