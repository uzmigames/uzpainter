## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.8_toolchain-slice

## 2. Implementation
- [ ] 2.1 Define the backend-neutral interfaces in `src/render/backend.h` (device, queue, resources, compute pipeline, wait result `signaled|timeout|device_lost`)
- [ ] 2.2 Implement the DX12 device/queue wrapper over the vendored RHI, reporting `device_removed {backend, reason}` and `gpu_backend_unavailable {backend, reason}` explicitly
- [ ] 2.3 Implement the engine thread: sole device owner, request queue against revision snapshots, futures, deadline on every GPU wait (default 60 s, configurable)
- [ ] 2.4 Implement the kernel compile path HLSL → DXIL and HLSL → SPIR-V through the vendored DXC compiler with `precise` arithmetic and no fast-math
- [ ] 2.5 Implement the kernel cache keyed by xxHash64 over source, includes, defines, target and DXC version, stored under the user's local app-data folder
- [ ] 2.6 Implement the capability query (formats, usages, ray-query support, descriptor capacities, DXGI VRAM budget) and derive the tile admission budget

## 3. Tests
- [ ] 3.1 Compile one compute kernel from the same source to DXIL and to SPIR-V and dispatch the DXIL kernel on DX12; written values equal the expected values
- [ ] 3.2 Kernel cache: an identical key hits; a change of source, include, define, target or DXC version misses
- [ ] 3.3 Deadline wait: a test-induced stalled fence returns `timeout` within the configured deadline instead of waiting forever
- [ ] 3.4 Device removal injected with `ID3D12Device5::RemoveDevice` returns `device_removed {backend: dx12, reason}` from the engine thread
- [ ] 3.5 Requesting an unavailable backend yields `gpu_backend_unavailable` before any mutation and does not use another backend
- [ ] 3.6 Capability report on the DX12 hardware adapter lists formats, usages, ray-query support and the VRAM budget; the admission budget is derived from it

## 4. Acceptance
- [ ] 4.1 All tests of this child green on the DX12 hardware adapter in a local run on the owner's machine (decision 028); the local run report recorded as evidence for the parent's acceptance

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
