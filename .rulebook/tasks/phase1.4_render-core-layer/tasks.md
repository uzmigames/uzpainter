## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.8_toolchain-slice

## 2. Children (each accepted before this parent closes)
- [ ] 2.1 `phase1.1_core-device-kernels` accepted
- [ ] 2.2 `phase1.2_core-readback` accepted
- [ ] 2.3 `phase1.3_core-uv-raster` accepted
- [ ] 2.4 `phase1.3_core-image-passes` accepted
- [ ] 2.5 Wire the four children behind the backend-neutral interface in `src/render/backend.h` and register them in the `build.zig` render-layer target

## 3. Tests
- [ ] 3.1 Run the render-layer unit suite on the synthetic meshes (plane, sphere, bevelled cube of the Tier 0 corpus, `docs/architecture/14-parity-testing.md` §3) on the DX12 hardware adapter in a local run on the owner's machine (decision 028; the local run report is the evidence)
- [ ] 3.2 Run the `TextureReadback` drain tests on DX12 together with a compute kernel compiled through the kernel cache (end to end: compile, dispatch, read back)
- [ ] 3.3 Run the vendoring check and confirm no include or library path of the render layer points into a UzEngine checkout (`docs/architecture/13-engine-integration.md` §3.3)

## 4. Acceptance
- [ ] 4.1 Acceptance (P1-CORE gate): unit tests on synthetic meshes and readback drain tests on DX12 green; record the run (hardware, driver, backend, build hash) for the G1 gate record

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
