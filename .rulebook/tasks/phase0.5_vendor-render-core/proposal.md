# Proposal: phase0.5_vendor-render-core

## Why
The owner requires the render system to come from UzEngine's rendering code with zero dependency on UzEngine: the code is copied (vendored) from a clean commit, with no `runtime.lib`, no pin, no patch queue, no upstream obligation and no submodule (Q8, decision 021, superseding 014; PRD OWN-02, ARC-07, LIC-02, LIC-01). UzEngine's checkout carried uncommitted edits during the analyses and the copied code has known defects (endless DX12 fence wait, DXR Tier 1.0 check, Agility path mismatch, SPIR-V target mismatch) that must be fixed in the copy or avoided, and the glTF 32/48-byte stride defect must stay out of the copy (`docs/architecture/13-engine-integration.md` §1–§3, §7; `docs/licensing-and-clean-room.md` §3; `docs/dag.md` P0-VENDOR, implements D12).

## What Changes
This parent is the integration and acceptance task for four children:
- `phase0.1_vendor-core-copy`: commit selection (13 §3.1), export of the 97-file subset (13 §2.1) from a commit object, layout `thirdparty/uzengine-render-core/` (13 §3.2), `LICENSE`, `ORIGIN.md`, `MANIFEST.json`, the root `NOTICE` entry.
- `phase0.2_vendor-thirdparty`: D3D12MA, DirectX-Headers, DirectXMath, DXC, Agility SDK, volk, VMA, Vulkan-Headers, SPIRV-Reflect, spdlog, Tracy headers from their own upstream releases (13 §2.5) under `thirdparty/<library>/` with their licences and `ORIGIN.md`.
- `phase0.3_vendor-modifications`: UZP-MOD-001…006 (13 §3.4) with Apache-2.0 §4(b) notices, `MODIFICATIONS.md`, and the static-library target of the subset in UzPainter's own `build.zig`. UZP-MOD-007 (Vulkan ray tracing) belongs to `phase3.3_vulkan-backend-ray-tracing`.
- `phase0.4_vendor-check`: the CI vendoring check of 13 §3.3.

## Dependencies
- Prerequisites: `phase0_owner-decisions` (P0-OWNER, archived).
- Children (must pass first): `phase0.1_vendor-core-copy`, `phase0.2_vendor-thirdparty`, `phase0.3_vendor-modifications`, `phase0.4_vendor-check`.
- Successors: `phase0.8_toolchain-slice` (P0-TOOLCHAIN). Selection check (c) of 13 §3.1 (hardware slice of `selftest`) is confirmed by `phase0.6_toolchain-hardware-slice` and recorded in `ORIGIN.md`.

## Acceptance
Builds standalone in UzPainter's own build; no `runtime.lib`, no submodule, no engine path, no pin or patch queue (`docs/dag.md`, P0-VENDOR). Contributes to G0: "vendored render core builds standalone" (`docs/roadmap.md`).

## Impact
- Affected specs: render-core
- Affected code: `thirdparty/uzengine-render-core/`, `thirdparty/<library>/`, `NOTICE`, `build.zig`, CI vendoring check
- Breaking change: NO
- User benefit: DX12 and Vulkan backends, shader compiler and readback primitives available to UzPainter with UzEngine changes never blocking it
