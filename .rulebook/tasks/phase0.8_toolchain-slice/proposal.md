# Proposal: phase0.8_toolchain-slice

## Why
UzPainter keeps its own build, Zig-first unless the vendored subset dictates otherwise, with CPython embedded through its C API and qualified in Phase 0 by `selftest` with a C-ABI DLL fallback (Q8, decision 021; PRD ARC-08, OWN-08, NFR-01). The platform is Windows 10/11 x64 with DX12 primary and Vulkan as the second backend; WARP is probed and reported, never mandatory (Q9, decision 022). The supervisor/worker topology needs the MCP SDK and CPython boundaries proven before Phase 1 (D1, `docs/architecture/02-runtime-topology.md`). `docs/architecture/13-engine-integration.md` §4.2 defines the toolchain decision procedure and the qualification slice; §5 the DLL footprint; §7 the Phase 0 settling evidence (`docs/dag.md` P0-TOOLCHAIN, implements D12 and D1).

## What Changes
This parent is the integration and acceptance task for three children:
- `phase0.6_toolchain-hardware-slice`: `build.zig` (Zig pinned in `build.zig.zon` and CI) building `UzPainter.exe` with the vendored core; the `UzPainter.exe selftest` command; the DX12 hardware-adapter slice (device, compute kernel compiled to DXIL and SPIR-V, 16-bit PNG through readback, Embree intersection); link map and DLL import closure compared with an allowlist.
- `phase0.7_toolchain-probes`: Vulkan 1.2 availability probe, ray-query probes (DXR Tier 1.1 + SM 6.6; `VK_KHR_acceleration_structure`, `VK_KHR_deferred_host_operations`, `VK_KHR_ray_query`) and the WARP probe report, with "probe completed" and "backend qualified" reported separately.
- `phase0.7_toolchain-cpython`: embedded CPython 3.13, the statically linked `uzpainter` module, 16-bit buffer and exception round trips, vendored MCP SDK import; the C-ABI fallback if the direct boundary fails.

## Dependencies
- Prerequisites: `phase0.5_vendor-render-core` (P0-VENDOR).
- Children (must pass first): `phase0.6_toolchain-hardware-slice`, `phase0.7_toolchain-probes`, `phase0.7_toolchain-cpython`.
- Successors: `phase0.9_normal-convention-fixture` (P0-NORMAL), `phase1.4_render-core-layer` (P1-CORE) and gate `phase0.10_gate-g0` (G0).

## Acceptance
Hardware slice green on the owner's machine; WARP probe completed and reported (supported capabilities, executed checks, unsupported reasons) — WARP failure leaves that path unsupported and does not fail G0; CPython boundary qualified or fallback chosen (`docs/dag.md`, P0-TOOLCHAIN). The Vulkan probe never fails G0; the Vulkan hardware selftest belongs to `phase3.3_vulkan-backend-ray-tracing` (13 §4.2).

## Impact
- Affected specs: build
- Affected code: `build.zig`, `build.zig.zon`, `selftest` command sources, CI configuration
- Breaking change: NO
- User benefit: the toolchain and every native boundary are proven on the owner's machine before any feature code depends on them
