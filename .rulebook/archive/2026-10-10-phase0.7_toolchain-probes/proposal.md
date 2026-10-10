# Proposal: phase0.7_toolchain-probes

## Why
Owner Q9 (decision 022) makes DX12 the primary backend and Vulkan the second backend on Windows 10/11 x64, with DXR Tier 1.1 and Vulkan ray queries required by the path tracer and the optional GPU baker (`docs/architecture/07-preview-and-render-parity.md` §3.5, `06-baking.md`). Phase 0 must learn, before any of that work starts, what the owner's machine and the WARP software adapter actually support, without letting an optional path block the contract gate: the Vulkan probe never fails G0 (the Vulkan hardware selftest belongs to P3-VULKAN), and a WARP failure leaves that software path unsupported unless the owner makes it mandatory (`13-engine-integration.md` §4.2; `docs/dag.md` P0-TOOLCHAIN; `docs/roadmap.md` G0). The WARP probe also decides which compute checks the hosted WARP CI lane may run (`14-parity-testing.md` §7). An unavailable backend or missing feature must be an explicit, reported fact, never a silent fallback (`13-…` §5). Child of `phase0.8_toolchain-slice` (implements D12, D1; PRD ARC-08, OWN-08, NFR-01).

## What Changes
- Probe stages of `UzPainter.exe selftest`, each reporting `probe completed` separately from `backend qualified`:
  - **Vulkan availability probe:** system loader (`vulkan-1.dll`) loaded through volk; Vulkan 1.2 instance; per physical device the API version, driver, extensions and features (buffer device address, descriptor indexing, `VK_EXT_memory_budget`); an absent or too-old loader is reported as `unavailable` with its reason, and DX12 is unaffected.
  - **Ray-query probes:** DX12 `D3D12_FEATURE_D3D12_OPTIONS5` `RaytracingTier ≥ D3D12_RAYTRACING_TIER_1_1` and highest shader model ≥ 6.6 (the vendored capability check of UZP-MOD-004); Vulkan `VK_KHR_acceleration_structure`, `VK_KHR_deferred_host_operations`, `VK_KHR_ray_query` and the `accelerationStructure` and `rayQuery` features. A missing feature is listed by name (the `missing` field later used by `PathTracerUnavailable{backend, missing}`).
  - **WARP probe:** DX12 device on the WARP adapter; each compute-path check of the hardware slice attempted (device, DXIL compute compile and dispatch, readback, 16-bit PNG), reporting supported capabilities, executed checks with results, and an explicit reason for every unsupported item; the list of WARP-qualified checks the hosted WARP lane may run.
- Machine-readable probe report from `selftest` (adapter, driver, OS build, backend, per-probe result) and the recorded owner's-machine run published as `parity/reports/phase0/toolchain-probes.md` (UzPainter's own results; no Painter output).
- Exit policy: Vulkan and WARP probe failures never make `selftest` fail the G0 hardware slice; a probe that crashes or cannot complete is reported as `probe not completed` with its error.

## Dependencies
- Prerequisites: `phase0.5_vendor-render-core` (P0-VENDOR), `phase0.6_toolchain-hardware-slice` (the `selftest` harness and DX12 hardware stages).
- Parent: `phase0.8_toolchain-slice` (P0-TOOLCHAIN) closes only when this child passes.
- Successors: `phase0.10_gate-g0` (WARP probe completed and reported; ray-query results cross-checked with `phase0.8_render-reference-fits`), `phase3.3_vulkan-backend-ray-tracing` (Vulkan hardware qualification), `phase3.7_path-tracer`, `phase4.3_dxr-baker`.

## Acceptance
On the owner's machine the Vulkan availability probe and both ray-query probes complete and their results are recorded; the WARP probe completes and reports supported capabilities, executed checks and unsupported reasons; "probe completed" and "backend qualified" are reported separately; a Vulkan or WARP failure leaves that path unsupported and does not fail G0 (P0-TOOLCHAIN gate, `docs/dag.md`).

## Impact
- Affected specs: build
- Affected code: `selftest` probe stages in UzPainter's render-core layer and CLI; `parity/reports/phase0/toolchain-probes.md`
- Breaking change: NO
- User benefit: the backend and ray-tracing capabilities of a machine are known and reported before any feature relies on them, and the hosted WARP lane runs only checks proven on WARP
