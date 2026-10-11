# Proposal: phase1.11_compositor-blend-gaps

## Why
`phase1.10_compositor-blend-kernels` made the 24 separable blend modes exact against the Tier 0 sweeps. Its q1 was answered with option 1 (coordinator, 2026-10-11): archive, and move the modes that are not exact into this follow-up. Nothing here counts as a pass until a mode matches Painter exactly or the owner approves an exception-register entry (decision 017; `docs/architecture/14-parity-testing.md` §5). Residuals are published in `parity/semantics/blend-kernels.json` and the evidence is in `parity/reports/phase1/compositor-blend-kernels.md`.

Three gaps remain:
- **(a) Tint, Saturation, Color, Value.** They are exact on grey (L16) channels. On colour channels the HSV fit of `blend-modes.json` (hexcone, ε = 2^-12, value doubled, hardware reciprocal) leaves up to 53 100 of 196 608 RGB16 values off, concentrated where the hue source is nearly grey. Painter's hue arithmetic there is not identified.
- **(b) NormalMapCombine, NormalMapDetail and NormalMapInverseDetail below opacity 1.** They are exact at opacity 1 on every format and on the Normal channel. Below opacity 1 they are off by at most 1 RGB16 code (RGB16 at 0.5), 2 sRGB codes (sRGB8 at 0.5) and 1.8e-7 (RGB32F at 0.25). Painter's float32 rotation of the upper normal toward (0, 0, 1) is not identified.
- **(c) PassThrough.** It has no kernel: it is a group placement, implemented as a hypothesis (the children composite into the enclosing list with their opacities scaled by the group's). Painter 12.1.0's API cannot set it, so no golden records it.

## What Changes
- Fit the HSV hue (and saturation) arithmetic near grey on the `blend-component` s0–s3 colour channels. Candidates are public HSV/HSL definitions (S-W3C-BLEND non-separable modes, the hexcone family) with float32 and hardware-reciprocal orders (`src/evaluator/hwmath.h`). Record a finer Tier 0 sweep (near-grey hue sources) if the existing golden does not determine it.
- Fit the opacity rotation of the normal-map modes on `blend-component` s4–s6 User1, User3 and User7, recording an opacity sweep if needed. Candidates are slerp with the GPU's float32 `acos`/`sin`, nlerp variants, and rotation by quaternion (P-BARRE, X-D3D12).
- Determine whether PassThrough can be recorded through Painter's documented API (Python or JavaScript). If it can, record a golden and fit it. If it cannot, record it `not_migratable` with the reason (owner scope decision).
- Implement everything in `src/evaluator/arith.cpp` and `shaders/evaluator_blend.hlsl` with GPU = CPU bit for bit. Re-derive `parity/semantics/blend-kernels.json` through `tests/evaluator/blend_fits.py`. Lift the release-gap entries of `tools/capabilities/painter-api-inventory.json` only together with their Tier 0 evidence.

## Dependencies
- `phase1.10_compositor-blend-kernels` (the kernels, the hardware arithmetic tables and the published fit).
- Not a prerequisite of `phase1.14_compositor-core`. The Wand v1 pilot stacks (Assets3D `Pipeline/retopology/wand11-v1/paint/stack-wand.json` and `stack-wand-v3.json`, synced by `painter_layer_stack.py`) use only `Normal`, `LinearDodge` on Height, and groups in their default mode (`Normal`, or `Normal` on Height for `replace_height`). None of the seven modes, and no PassThrough group, appears; none of their layers sets a `blend` key. This task becomes a prerequisite of any later gate whose content uses one of these modes (check Belt v5 and Tunic v10 before their gates).

## Acceptance
`blend-component` s0–s6 every channel, and `blend-normal-channel` s1–s3, exact on CPU and GPU against both recordings in a local DX12 run (decision 028). PassThrough must be either recorded and exact or ruled `not_migratable` by the owner. Anything that remains needs an owner-approved exception-register entry.

## Impact
- Affected specs: `compositor`
- Affected code: `src/evaluator/arith.*`, `src/evaluator/shaders/evaluator_blend.hlsl`, `tests/evaluator/`, `parity/semantics/blend-kernels.json`, `tools/capabilities/painter-api-inventory.json` (status only)
- Breaking change: NO
- User benefit: the component and normal-map blend modes match Painter at every opacity.
