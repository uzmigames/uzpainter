## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.5_vendor-render-core (including phase0.3_vendor-modifications and phase0.2_vendor-thirdparty)

## 2. Implementation
- [ ] 2.1 Add the `UzPainter.exe` executable target to `build.zig`, linking the vendored render core and libc++ statically under the pinned Zig
- [ ] 2.2 Vendor Embree 4.x and the selected PNG library (libpng + zlib, or spng) from their upstream releases with licence files and `ORIGIN.md`
- [ ] 2.3 `selftest` harness: ordered stages, per-stage result, machine-readable report, non-zero exit when a mandatory stage fails, extension points for the probe and CPython stages
- [ ] 2.4 Stage: DX12 device on the hardware adapter with the Agility SDK loaded from `D3D12\`; report adapter, driver and Agility SDK version
- [ ] 2.5 Stage: compile a compute kernel at run time through DXC from HLSL to DXIL and to SPIR-V
- [ ] 2.6 Stage: dispatch the DXIL kernel writing a known 16-bit pattern, read it back through the vendored readback primitives, write a 16-bit PNG and decode it back equal to the pattern
- [ ] 2.7 Stage: Embree intersection of a known ray with a known triangle, checking hit distance and barycentrics
- [ ] 2.8 Produce the link map and inspect it for the statically linked render core and libc++
- [ ] 2.9 DLL import-closure tool: read the import tables of every binary in the output folder, compare with the `13-engine-integration.md` §5 allowlist, report count and footprint
- [ ] 2.10 Run `selftest` on the owner's machine; publish `parity/reports/phase0/toolchain-hardware-slice.md` and record selection check (c) in `thirdparty/uzengine-render-core/ORIGIN.md`

## 3. Tests
- [ ] 3.1 Hardware slice on the owner's machine: every mandatory stage passes and the report lists adapter, driver, OS build, Zig and DXC versions
- [ ] 3.2 Failure path: with `D3D12\D3D12Core.dll` removed the device stage fails with an explicit reason and `selftest` exits non-zero
- [ ] 3.3 PNG16 round trip: decoded PNG values equal the 16-bit pattern bit for bit (no 8-bit truncation)
- [ ] 3.4 Closure check: an unlisted DLL in the import closure fails the check; a system DLL in the output folder fails the check
- [ ] 3.5 Clean-machine start: the output folder starts and runs the non-GPU stages on a clean Windows 10/11 x64 machine without the Windows SDK, Vulkan SDK, Python or Painter

## 4. Acceptance
- [ ] 4.1 Child acceptance (contributes to P0-TOOLCHAIN): DX12 hardware slice green on the owner's machine; link map and DLL closure inspected against the allowlist; clean-machine start recorded; selection check (c) recorded

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
