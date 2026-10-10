# Proposal: phase0.6_toolchain-hardware-slice

## Why
UzPainter has its own build (decision 021; PRD ARC-08 "own build, Zig-first unless the vendored subset dictates otherwise, with Phase 0 qualification"), and G0 requires the hardware `selftest` to be green on the owner's machine before Phase 1 builds the render-core layer on it (`docs/roadmap.md` G0; `docs/dag.md` P0-TOOLCHAIN). The decision procedure of `docs/architecture/13-engine-integration.md` §4.2 keeps Zig only if the DX12 hardware-adapter slice passes: device on the hardware adapter, a compute kernel compiled from HLSL to DXIL and to SPIR-V, a 16-bit PNG written through readback, and an Embree intersection. The one-folder distribution (OWN-08, decision 022) also needs the link map and the DLL import closure measured against an allowlist from the first executable, because "DLL count and footprint are measured, not promised" (`13-…` §5). Selection check (c) of the vendored commit ("UzPainter's build of the subset and the hardware slice pass", `13-…` §3.1) can only be confirmed here. Child of `phase0.8_toolchain-slice` (implements D12, D1; PRD ARC-08, OWN-08, NFR-01, NFR-07).

## What Changes
- `build.zig` extended (on the static-library target of `phase0.3_vendor-modifications`) with the `UzPainter.exe` executable target, the vendored render core and libc++ linked statically, under the Zig release pinned in `build.zig.zon`.
- `UzPainter.exe selftest` harness: ordered stages with a per-stage result, a machine-readable report and a non-zero exit when a mandatory stage fails; later stages (probes of `phase0.7_toolchain-probes`, CPython/MCP of `phase0.7_toolchain-cpython`) plug into the same harness.
- Mandatory DX12 hardware-slice stages: DX12 device on the hardware adapter with the Agility SDK loaded from `D3D12\`; a compute kernel compiled at run time by DXC from HLSL to DXIL and to SPIR-V; dispatch of the DXIL kernel writing a known 16-bit pattern, readback through the vendored readback primitives (256-byte row pitch, mapped buffer) and a 16-bit PNG written and decoded back equal; an Embree intersection on a known triangle and ray.
- Third-party additions needed by the slice, vendored with licence and `ORIGIN.md` like `phase0.2_vendor-thirdparty`: Embree 4.x release (`embree4.dll`, `tbb12.dll` unless internal tasking) and the PNG encoder/decoder selected from the inventory (`docs/licensing-and-clean-room.md` §3: libpng with zlib, or spng).
- Link map from the linker, inspected for the statically linked vendored library and libc++; DLL import-closure tool reading the import tables of every binary in the output folder and comparing them with an allowlist of `13-…` §5 (system DLLs never shipped; shipped DLLs only as listed or measured).
- Clean-machine start: the output folder started on a clean Windows 10/11 x64 machine without the Windows SDK, Vulkan SDK, Python or Painter, with the measured closure resolving.
- Recorded owner's-machine run published as `parity/reports/phase0/toolchain-hardware-slice.md` (adapter, driver, OS build, Zig and DXC versions, per-stage result, closure); selection check (c) recorded in `thirdparty/uzengine-render-core/ORIGIN.md`.

## Dependencies
- Prerequisites: `phase0.5_vendor-render-core` (P0-VENDOR, including `phase0.3_vendor-modifications` static-library target and `phase0.2_vendor-thirdparty` libraries).
- Parent: `phase0.8_toolchain-slice` (P0-TOOLCHAIN) closes only when this child passes.
- Successors: `phase0.7_toolchain-probes`, `phase0.7_toolchain-cpython` (both extend the harness), `phase0.9_normal-convention-fixture` (P0-NORMAL needs the toolchain), `phase1.4_render-core-layer` (P1-CORE).

## Acceptance
The DX12 hardware slice of `selftest` (device, DXIL and SPIR-V compile, compute dispatch, 16-bit PNG through readback, Embree intersection) is green on the owner's machine under the pinned Zig; the link map and DLL import closure are inspected against the allowlist; the folder starts on a clean machine; selection check (c) is recorded. Contributes to the P0-TOOLCHAIN gate "hardware slice green on the owner's machine" (`docs/dag.md`) and G0 "hardware `selftest` green" (`docs/roadmap.md`).

## Impact
- Affected specs: build
- Affected code: `build.zig`, `build.zig.zon`, `UzPainter.exe selftest`, DLL-closure tool, `thirdparty/embree/`, PNG library folder, `parity/reports/phase0/toolchain-hardware-slice.md`
- Breaking change: NO
- User benefit: the toolchain is proven on real hardware before any feature depends on it, and the distribution's DLL footprint is measured from the first build
