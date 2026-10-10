# P1-CORE child `phase1.1_core-device-kernels` — owner's machine run

Task `phase1.1_core-device-kernels`, first child of `phase1.4_render-core-layer` (P1-CORE, `docs/dag.md`; `docs/architecture/13-engine-integration.md` §4.1, §6; `04-layer-stack-and-compositing.md` §7; `02-runtime-topology.md` §1, §4, §5). Decision 028: GPU checks run locally on the owner's machine and this report is their evidence for the parent's acceptance. Run on 2026-10-10 on the tree of commit `58cca2a` with this task's working-tree changes.

**Result: all tests of this child green on the DX12 hardware adapter.**

## Machine and build

| Item | Value |
|---|---|
| Machine | Windows 11 (build 10.0.26200), NVIDIA GeForce RTX 4090 (vendor 0x10DE, device 0x2684), driver 617.14 |
| Build | `zig build render-tests` (Zig 0.15.2, Debug), `-Wall -Wextra -Werror` on `src/render/` and `tests/render/`, exit code 0; `zig build painter native-tests probe-tests` exit code 0 |
| DXC | 1.9, `dxcompiler.dll` 1.9.2602.17 (the compiler identity in the kernel cache key: `dxc 1.9, dxcompiler.dll 1.9.2602.17`) |

## Tests (`python -m pytest tests/render`, `uzp-render-tests.exe`)

| Task item | Case | Evidence of this run | Verdict |
|---|---|---|---|
| 3.1 one kernel to DXIL and SPIR-V; DXIL dispatched on DX12 | `kernel-cache`, `dispatch` | the ramp kernel (one declared include, one define) compiled to a DXIL container and a SPIR-V module from the same source; the cached DXIL kernel dispatched by the engine thread for a request submitted from another thread wrote 100 x 64 R32Float values equal bit for bit to the CPU values computed with one rounding per operation, for two revision snapshots | met |
| 2.4 `precise` arithmetic, no fast-math | `kernel-cache`; `tests/vendoring/test_modifications.py::test_ieee_strict_arithmetic` | every kernel is compiled with `-Gis` (UZP-MOD-008): DXIL float instructions carry no `fast` flag (DXC disassembly), SPIR-V arithmetic is decorated `NoContraction`; without `-Gis` the same kernel's DXIL is all `fast` and its SPIR-V has no `NoContraction` | met |
| 3.2 cache key sensitivity | `kernel-cache` | an identical key hits (same cache and a new cache over the same folder, no compilation); a changed source, include, define, define list, target or DXC version each misses once, recompiles and then hits; 7 distinct keys; include declaration order does not change the key, define order does; a damaged entry is recompiled and rewritten | met |
| 2.5 cache folder | `kernel-cache` | default folder `%LOCALAPPDATA%\UzPainter\kernel-cache`; XXH64 bit-exact with python-xxhash 3.6.0 on 0–1000 bytes and two seeds | met |
| 3.3 stalled fence | `deadline` | the direct queue waits on a fence nothing signals; the request's wait (deadline 300 ms) returned `timeout {backend: dx12}` after 314 ms; later requests fail with the same timeout without running; after the test released the queue the engine stopped normally in 64 ms | met |
| 3.4 device removal | `device-removed` | after `ID3D12Device5::RemoveDevice` the next request failed with `device_removed {backend: dx12, reason: DXGI_ERROR_DEVICE_REMOVED (0x887A0005)}` and its work did not run | met |
| 3.5 unavailable backend | `unavailable` | `--gpu-backend vulkan` (no Vulkan implementation in this build) and DX12 adapter index 64 (3 adapters present) each yield `gpu_backend_unavailable` for the requested backend; requests fail before their work runs; neither `D3D12Core.dll` nor `vulkan-1.dll` was loaded, so no device of any backend was created | met |
| 3.6 capability report | `capabilities` | D3D_FEATURE_LEVEL_12_2, SM6.9, ray tracing yes, inline ray query yes; 28 formats with usages (e.g. RGBA16Float: copy, shader_resource, sample, render_target, unordered_access, unordered_access_load); descriptors 1,000,000 CBV/SRV/UAV, 2048 samplers, 256 RTV, 64 DSV, resource binding tier 3; VRAM budget 24,505,221,120 bytes; admission budget 11,957,792,768 bytes (= (budget − usage − 512 MiB) × 50 %), at most 497,952 live tiles by descriptors | met |

The CPU cases (`xxhash`, `admission`, `kernel-cache`) also run under `UZP_NO_GPU=1` (hosted CI); the five GPU cases skip there with the decision-028 reason.

## Reproduce

```
zig build render-tests
python -m pytest tests/render tests/vendoring/test_modifications.py
zig-out\bin\uzp-render-tests.exe capabilities <work-dir>
```
