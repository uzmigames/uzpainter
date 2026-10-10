# P1-CORE `phase1.4_render-core-layer` — acceptance run on the owner's machine

Parent integration task of the render-core layer (P1-CORE, `docs/dag.md`; `docs/architecture/13-engine-integration.md` §4.1, §7). DAG gate: unit tests on synthetic meshes and readback drain tests on DX12. Decision 028: GPU checks run locally on the owner's machine and this report is their evidence for the G1 gate record. Run on 2026-10-10 on the tree of commit `4ea4731` with this task's working-tree changes.

**Result: P1-CORE gate green on the DX12 hardware adapter.** All four children are accepted (archived 2026-10-10, evidence in `core-device-kernels.md`, `core-readback.md`, `core-uv-raster.md`, `core-image-passes.md`); the whole render-layer suite passed in this run.

## Run record (for the G1 gate record)

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090 (vendor 0x10DE, device 0x2684), Windows 11 Pro 10.0.26200 |
| Driver | 617.14 |
| Backend | DX12 (`--gpu-backend dx12`, the default), D3D_FEATURE_LEVEL_12_2, SM 6.9; kernels `cs_6_6 -Gis` through DXC 1.9 (`dxcompiler.dll` 1.9.2602.17) |
| Build | commit `4ea4731` plus this task's working-tree changes (test cases and the vendoring check's build steps; no change under `src/`); `zig build` and `zig build painter native-tests probe-tests render-tests` (Zig 0.15.2, Debug), `-Wall -Wextra -Werror` on `src/render/` and `tests/render/`, exit code 0 |

## Children

| Child | Accepted | Evidence |
|---|---|---|
| `phase1.1_core-device-kernels` | archived 2026-10-10 | `core-device-kernels.md` |
| `phase1.2_core-readback` | archived 2026-10-10 | `core-readback.md` |
| `phase1.3_core-uv-raster` | archived 2026-10-10 | `core-uv-raster.md` |
| `phase1.3_core-image-passes` | archived 2026-10-10 | `core-image-passes.md` |

## Integration (task item 2.5)

All twelve sources of `src/render/` are listed once in `render_sources` of `build.zig` and compiled into `UzPainter.exe` and `uzp-render-tests.exe`; the four kernel files of `src/render/shaders/` are embedded and compiled through the kernel cache. Every operation is reached through `src/render/backend.h` (`IDevice`, `IQueue`, `Result`/`Error`) and the engine thread. `test_render_layer_headers_are_backend_neutral` follows every header of `src/render/` through its includes (the vendored RHI headers included) and finds no DX12, DXGI or Vulkan header; `device.h` names `ID3D12Device` only as a forward declaration for the DX12 implementation. A second test shows the check detects one (the vendored `dx12_device.h`). The backend is chosen only by `--gpu-backend`: an unavailable backend fails with `gpu_backend_unavailable` before any work runs and loads no other backend (`unavailable` case, `core-device-kernels.md` 3.5).

## Tests (`python -m pytest tests/render`: 28 passed, 0 skipped)

| Task item | Case | Evidence of this run | Verdict |
|---|---|---|---|
| 3.1 synthetic meshes of the Tier 0 corpus | `uv-raster-tier0` (new) | `parity/fixtures/meshes/plane.obj` (2 triangles), `tier0-semantics/meshes/sphere.obj` (960) and `bevelled-cube.obj` (768) rasterised at 512 x 512 and 300 x 200: the conservative mask covers every texel a triangle touches, marks no untouched texel and contains the texel-centre coverage; texel-centre coverage equals the double-precision reference. Plane: all 262 144 and 60 000 centres covered. Sphere 512²: 245 760 centre, 246 784 conservative texels; bevelled cube 512²: 212 400 centre, 214 288 conservative texels | met |
| 3.1 the children's mesh cases | `uv-raster-plane`, `-thin`, `-coverage`, `-ids`, `-repeat` | all green again in this run (`core-uv-raster.md`) | met |
| 3.2 drain behind a cached kernel | `readback-kernel` (new) | the ramp kernel compiled through the engine's kernel cache, dispatched into eight R32Float textures (widths 1 to 4097, heights 5 to 12) in one submission; 64 readbacks of them requested at once without waiting for the dispatch, each with its own staging buffer; `Drain()` reported all 64 in submission order with every texel equal bit for bit to the IEEE-strict CPU value; afterwards no request outstanding and the device's allocation count back at its baseline; the DXIL kernel is a hit in the cache folder | met |
| 3.2 the children's readback cases | `readback-drain`, `-pitch`, `-exact`, `-failure`, `-layout`, `dispatch` | all green again in this run (`core-readback.md`, `core-device-kernels.md`) | met |
| 3.3 vendoring check | `python -m tools.vendoring.vendor_check` | `vendoring check passed: 97 vendored files; build paths checked`, exit 0. The build-path rule now builds `render-tests` too (`BUILD_STEPS`), so every include and library path of the render layer, in `UzPainter.exe` and in its test executable, was checked: none outside the repository, none into a UzEngine checkout; no unlogged change under `thirdparty/uzengine-render-core/` | met |
| 4.1 acceptance | all of the above | synthetic-mesh unit tests and readback drain tests green on DX12; run recorded above | met |

The GPU cases skip under `UZP_NO_GPU=1` (hosted CI) with the decision-028 reason; the header check runs everywhere.

## Reproduce

```
zig build render-tests
python -m pytest tests/render
python -m tools.vendoring.vendor_check
```
