# Proposal: phase1.1_core-device-kernels

## Why
The compositor needs one owner of the GPU device, bounded GPU waits, generated-kernel compilation with a content-keyed cache, and a capability query from which the tile admission budget is derived (`docs/architecture/04-layer-stack-and-compositing.md` §7; `docs/architecture/13-engine-integration.md` §4.1, §6). A worker must never hang on a GPU wait or fall back silently to another backend (`docs/architecture/02-runtime-topology.md` §1, §4, §5). Requirements: OWN-08, NFR-01, NFR-03, NFR-06, ARC-08 (`docs/prd.md`). Implements D12 as decided by the owner (decision 021, Q8: render core vendored from a clean UzEngine commit, zero dependency on UzEngine; decision 022, Q9: Windows 10/11 x64, DX12 primary, Vulkan second backend) in `docs/architecture/13-engine-integration.md` §4.1, §6 and §7, and the evaluator substrate of D3 (decision 005) in `docs/architecture/04-layer-stack-and-compositing.md` §7. Child of `phase1.4_render-core-layer` (P1-CORE).

## What Changes
- `src/render/backend.h`: backend-neutral interfaces (device, queue, buffer/texture, compute pipeline, fence wait result `signaled|timeout|device_lost`).
- `src/render/device.{h,cpp}`: device/queue wrapper over the vendored RHI on DX12; device removal reported as `device_removed {backend, reason}`; an unavailable backend reported as `gpu_backend_unavailable {backend, reason}`.
- `src/render/engine_thread.{h,cpp}`: the engine thread as sole owner of the device; a request queue evaluated against revision snapshots; completion through futures; every GPU wait carries a deadline (default 60 s per evaluation request, configurable) using the deadline wait added by P0-VENDOR (UZP-MOD-003).
- `src/render/kernel_cache.{h,cpp}`: HLSL → DXIL and → SPIR-V through the vendored `shader_compiler` (DXC); cache keyed by xxHash64 over source, includes, defines, target and DXC version; cache folder under the user's local app-data (the install folder stays read-only); kernels compiled `precise`, no fast-math.
- `src/render/capabilities.{h,cpp}`: capability query (formats, usages, ray-query support, descriptor capacities, VRAM budget through the DXGI memory-budget query) and the derived tile admission budget consumed by the evaluator.

## Dependencies
- DAG input of the parent: `phase0.8_toolchain-slice` (vendored render core and DXC loading proven by `selftest`).
- Parent: `phase1.4_render-core-layer`. Siblings that build on this child: `phase1.2_core-readback`, `phase1.3_core-uv-raster`, `phase1.3_core-image-passes`.

## Acceptance
Part of the P1-CORE gate (unit tests on synthetic meshes; readback drain tests on DX12): the engine thread, deadline waits, kernel cache and capability query pass their unit tests on the DX12 hardware adapter.

## Impact
- Affected specs: `render-core`
- Affected code: `src/render/backend.h`, `src/render/device.*`, `src/render/engine_thread.*`, `src/render/kernel_cache.*`, `src/render/capabilities.*`, `tests/render/`
- Breaking change: NO
- User benefit: A single, deadline-bounded GPU owner with cached generated kernels, so evaluation never hangs and never silently changes backend.
