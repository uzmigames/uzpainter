## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.5_vendor-render-core

## 2. Children
- [ ] 2.1 Child accepted: phase0.6_toolchain-hardware-slice (`build.zig`, `selftest`, DX12 hardware slice, link map, DLL closure)
- [ ] 2.2 Child accepted: phase0.7_toolchain-probes (Vulkan, ray-query and WARP probe reports)
- [ ] 2.3 Child accepted: phase0.7_toolchain-cpython (CPython boundary qualified or C-ABI fallback chosen)

## 3. Integration tests
- [ ] 3.1 Full `UzPainter.exe selftest` on the owner's machine from one build: hardware slice green, probe reports written, CPython checks green; result attached to the gate evidence
- [ ] 3.2 Toolchain decision recorded per `13-engine-integration.md` §4.2: Zig kept, or the change and its failing selftest output recorded as an update to decision 021

## 4. Acceptance
- [ ] 4.1 Acceptance gate (P0-TOOLCHAIN): hardware slice green on the owner's machine; WARP probe completed and reported (WARP failure leaves that path unsupported and does not fail G0); CPython boundary qualified or fallback chosen

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
