# Proposal: phase1.2_core-readback

## Why
Every parity comparison and every export reads GPU results back at native precision. The vendored helpers are unsuitable (`ipc/frame_readback` is RGBA8 only and is not vendored), so UzPainter owns `TextureReadback` with per-request ownership, aligned pitch, fence-linked mapping and draining (`docs/architecture/13-engine-integration.md` §2.3, §2.4, §4.1). Requirements: ACC-01, EXP-02, EXP-05, NFR-02 (`docs/prd.md`). Implements D12 as decided by the owner (decision 021, Q8: render core vendored from a clean UzEngine commit, zero dependency on UzEngine; decision 022, Q9: Windows 10/11 x64, DX12 primary, Vulkan second backend) in `docs/architecture/13-engine-integration.md` §4.1, §6 and §7, and the evaluator substrate of D3 (decision 005) in `docs/architecture/04-layer-stack-and-compositing.md` §7. Child of `phase1.4_render-core-layer` (P1-CORE), whose DAG gate names the readback drain tests on DX12.

## What Changes
- `src/render/texture_readback.{h,cpp}`: `TextureReadback` on DX12 behind the backend-neutral interface: per-request ownership of staging buffers, 256-byte row pitch for `CopyTextureToBuffer`, fence-linked map, explicit drain; native formats at full precision (8-bit, 16-bit unorm, 16/32-bit float, one to four channels); failures returned as errors, never as stale data.
- `tests/render/`: drain and exactness tests.

## Dependencies
- DAG input of the parent: `phase0.8_toolchain-slice`.
- Sibling prerequisite: `phase1.1_core-device-kernels` (engine thread, deadline waits).
- Parent: `phase1.4_render-core-layer`.

## Acceptance
P1-CORE gate, readback part: readback drain tests pass on DX12.

## Impact
- Affected specs: `render-core`
- Affected code: `src/render/texture_readback.*`, `tests/render/`
- Breaking change: NO
- User benefit: Exact native-precision GPU readback for exports and parity comparisons, with no leaked staging memory under load.
