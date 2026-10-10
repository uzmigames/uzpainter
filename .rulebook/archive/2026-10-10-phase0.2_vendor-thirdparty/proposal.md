# Proposal: phase0.2_vendor-thirdparty

## Why
The vendored UzEngine render core (P0-VENDOR, decision 021, owner Q8) compiles against third-party code: D3D12MA, DirectX-Headers, DirectXMath, the DirectX Shader Compiler (headers and binaries), the Direct3D 12 Agility SDK, volk, Vulkan Memory Allocator, Vulkan-Headers, SPIRV-Reflect, spdlog with its bundled fmt, and Tracy's public headers (`docs/architecture/13-engine-integration.md` §2.2, §2.5). Copying these out of UzEngine's tree would inherit unknown local edits and hide their provenance; UzPainter takes each library from its own upstream release, keeps its licence and notices, and records every difference from UzEngine's copy. Without this, PRD LIC-02 (every dependency confirmed and listed with its notice), ARC-07 (attribution and source recorded, local modifications marked) and OWN-02 (zero dependency on UzEngine, no engine path) cannot be met, and the third-party inventory of `docs/licensing-and-clean-room.md` §3 stays unverified. Child of `phase0.5_vendor-render-core` (implements D12).

## What Changes
- `thirdparty/<library>/` for each library of `13-…` §2.5, fetched from the library's own upstream release at the version UzEngine's tree uses at the selected commit (on 2026-10-10 UzEngine's `runtime/thirdparty/README.md` listed, for example, D3D12MA 3.1.0, VMA 3.2.1, volk `vulkan-sdk-1.4.304.1`, Vulkan-Headers 1.4.342, DirectX-Headers 1.619.1, DXC 1.9.2602, Agility 1.619.1, spdlog 1.17.0, Tracy 0.13.1; the versions are re-read at the selected commit):
  - D3D12MA (`include/`, `src/`, upstream `NOTICES.txt`), DirectX-Headers (`include/directx`), DirectXMath (headers), DXC (`dxcapi.h`, `dxcompiler.dll`, `dxil.dll`, package licence files), Agility SDK (`D3D12Core.dll` and its headers), volk, VMA, Vulkan-Headers, SPIRV-Reflect (`spirv_reflect.c`), spdlog with bundled fmt (compiled library, `SPDLOG_COMPILED_LIB`), Tracy public headers only (no Tracy client).
  - Per library: upstream `LICENSE`/`NOTICE` files kept verbatim and an `ORIGIN.md` recording upstream URL, release tag or package version, archive SHA-256, retrieval date, importer, selected files, selected features and distribution role (shipped, build-only or headers-only).
- Byte comparison of each upstream package with UzEngine's copy at the selected commit, recorded in that library's `ORIGIN.md`. A UzEngine patch under `thirdparty/<lib>/patches/` is applied only if the build needs it and is then logged as a local modification with the fields of `MODIFICATIONS.md` (`13-…` §3.3).
- Third-party inventory rows of `docs/licensing-and-clean-room.md` §3 for these libraries confirmed against the exact pinned packages (licence, notices, package hash, selected features, distribution role). The DXC `LICENSE-MS.txt` scope / `dxil.dll` redistribution and the Agility SDK package licence are checked against the package text and recorded as confirmed or as a named release blocker (the policy makes unverified entries release blockers).

## Dependencies
- Prerequisites: `phase0_owner-decisions` (P0-OWNER, decision 021, archived), `phase0.1_vendor-core-copy` (selected UzEngine commit, whose `runtime/thirdparty/README.md` fixes the versions).
- Parent: `phase0.5_vendor-render-core` (P0-VENDOR) closes only when this child passes.
- Successors: `phase0.3_vendor-modifications` (standalone static-library target resolves third-party includes here), `phase0.8_toolchain-slice` (P0-TOOLCHAIN build and DLL closure), `phase5.2_packaging` (P5-PACKAGE `NOTICE`/`LICENSES`).

## Acceptance
Every third-party library of the vendored subset is present under `thirdparty/<library>/` from its own upstream release, with its licence, notices and `ORIGIN.md`; each package is byte-compared with UzEngine's copy and every difference or applied patch is logged; no third-party file comes from a UzEngine tree; each inventory row is confirmed or carries an explicit release-blocker status. Contributes to the P0-VENDOR gate "builds standalone in UzPainter's own build; no `runtime.lib`, no submodule, no engine path" (`docs/dag.md`).

## Impact
- Affected specs: render-core
- Affected code: `thirdparty/<library>/` (new); licence inventory evidence for `NOTICE`/`LICENSES`
- Breaking change: NO
- User benefit: the render core's dependencies have verifiable provenance and licences, so the build needs no UzEngine checkout and the release inventory can be completed (LIC-02)
