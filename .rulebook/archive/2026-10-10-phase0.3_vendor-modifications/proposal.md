# Proposal: phase0.3_vendor-modifications

## Why
The UzEngine render core is copied verbatim where possible, but six upstream behaviours are wrong or out of scope for UzPainter (`docs/architecture/13-engine-integration.md` §3.4): the RHI factory still builds DX11 and Metal branches; `ResolveRHIConfig` drags in UzEngine's config and CVar system; DX12 fence waits never end and Vulkan waits give up after 5 s without reporting device loss, so the worker watchdog cannot rely on them (`02-runtime-topology.md` §1); the DX12 device reports ray-tracing support at DXR Tier ≥ 1.0 although `RayQuery` needs Tier 1.1 and SM 6.6; the Agility SDK is looked up in two different folders; and SPIR-V is emitted for Vulkan 1.3 while the device requests a Vulkan 1.2 instance. Apache-2.0 §4(b) requires a prominent notice in every modified file, and ARC-07 requires local modifications to be marked and logged. The P0-VENDOR gate also requires the vendored subset to build standalone in UzPainter's own build (OWN-02, ARC-08), which needs a UzPainter-owned static-library target. Child of `phase0.5_vendor-render-core` (implements D12, decision 021).

## What Changes
- Local modifications in `thirdparty/uzengine-render-core/` (`13-…` §3.4), each citing the upstream behaviour as `path:line` at the selected commit:
  - UZP-MOD-001 `engine/rhi/rhi_factory.cpp`: DX11 and Metal branches and factory cases removed.
  - UZP-MOD-002 `engine/rhi/rhi_config.cpp`: `ResolveRHIConfig(const Config&)` removed; the backend is passed in by the caller (from `--gpu-backend`, `02-…` §1); no `engine/config` or `engine/core/cvar` include remains.
  - UZP-MOD-003 `engine/rhi/dx12/dx12_fence.*`, `engine/rhi/vulkan/vulkan_fence.*`: deadline wait returning `signaled`, `timeout` or `device_lost` (DX12 device-removed reason; Vulkan `VK_ERROR_DEVICE_LOST`), replacing the endless DX12 wait and the Vulkan 5 s give-up.
  - UZP-MOD-004 `engine/rhi/dx12/dx12_device.*`: the inline-ray-query capability is reported only for DXR Tier 1.1 and SM 6.6.
  - UZP-MOD-005 `engine/rhi/dx12/dx12_device.cpp`: Agility SDK loaded from the `D3D12\` subfolder, matching the exported `D3D12SDKPath`.
  - UZP-MOD-006 `engine/shader/shader_compiler.cpp`: SPIR-V target environment `vulkan1.2`; the ray-query SPIR-V extension added when requested.
- The Apache-2.0 §4(b) notice at the top of every modified file: `Modified by UzmiGames for UzPainter — see thirdparty/uzengine-render-core/MODIFICATIONS.md <id>. Original: UzEngine runtime/<path> at <commit>. Licensed under the Apache License, Version 2.0.`
- `thirdparty/uzengine-render-core/MODIFICATIONS.md`: one entry per change `{id, files, reason (defect | trim | platform | capability), description, upstream behaviour cited as path:line, date, author, covering test}`, plus the behaviours kept on purpose (`FatalErrorLoop` abort, contained by the worker boundary; `ShaderCompiler::Init` DLL directory). `MANIFEST.json` entries of the modified files switch to `status: modified` with their modification ids and new `vendored_sha256`.
- `build.zig` with a static-library target for the vendored subset and `build.zig.zon` pinning the Zig release (≥ 0.15.2, the release used for the selected commit): `-std=c++23 -DSPDLOG_COMPILED_LIB`, `TRACY_ENABLE` and `UZ_PROFILING_ENABLED` undefined, include and library paths only inside the UzPainter repository (`thirdparty/uzengine-render-core/`, `thirdparty/<library>/`, Windows SDK), no DX11/Metal sources.
- UZP-MOD-007 (Vulkan acceleration structures, ray query, descriptor-indexing bindless) is not part of this task; it belongs to `phase3.3_vulkan-backend-ray-tracing`.

## Dependencies
- Prerequisites: `phase0_owner-decisions` (P0-OWNER, archived), `phase0.1_vendor-core-copy` (copied subset, manifest, selected commit), `phase0.2_vendor-thirdparty` (third-party libraries the static library compiles against).
- Parent: `phase0.5_vendor-render-core` (P0-VENDOR) closes only when this child passes.
- Successors: `phase0.4_vendor-check` (checks the notices, log and hashes written here), `phase0.6_toolchain-hardware-slice` (extends this `build.zig` with the executable and `selftest`).

## Acceptance
UZP-MOD-001…006 applied, each with its §4(b) notice, a `MODIFICATIONS.md` entry and a passing covering test; `MANIFEST.json` reflects every modified file; the vendored subset compiles as a static library in UzPainter's own `build.zig` under the pinned Zig with no `runtime.lib`, no submodule and no include or library path into a UzEngine checkout (P0-VENDOR gate, `docs/dag.md`).

## Impact
- Affected specs: render-core
- Affected code: `thirdparty/uzengine-render-core/engine/rhi/`, `engine/shader/shader_compiler.cpp`, `MODIFICATIONS.md`, `MANIFEST.json`; new `build.zig`, `build.zig.zon`
- Breaking change: NO
- User benefit: bounded, truthful GPU waits for the worker watchdog, correct ray-query capability reporting and Vulkan 1.2 SPIR-V, built from UzPainter's own build with no engine dependency
