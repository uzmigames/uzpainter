# P1-CORE child `phase1.2_core-readback` — owner's machine run

Task `phase1.2_core-readback`, child of `phase1.4_render-core-layer` (P1-CORE, `docs/dag.md`; `docs/architecture/13-engine-integration.md` §2.3, §2.4, §4.1). Decision 028: GPU checks run locally on the owner's machine and this report is their evidence for the parent's acceptance (P1-CORE gate item: readback drain tests green on DX12). Run on 2026-10-10 on the tree of commit `58cca2a` with the working-tree changes of `phase1.1_core-device-kernels` and this task.

**Result: all readback tests green on the DX12 hardware adapter.**

## Machine and build

| Item | Value |
|---|---|
| Machine | Windows 11 (build 10.0.26200), NVIDIA GeForce RTX 4090, the adapter of `core-device-kernels.md` |
| Build | `zig build render-tests` (Zig 0.15.2, Debug), `-Wall -Wextra -Werror` on `src/render/` and `tests/render/`, exit code 0; `zig build painter native-tests probe-tests render-tests` exit code 0 |
| Vendored change | UZP-MOD-009 (16-bit unorm color formats `R16Unorm`, `RG16Unorm`, `RGBA16Unorm`), logged in `thirdparty/uzengine-render-core/MODIFICATIONS.md`; `python -m tools.vendoring.modifications`: 8 modifications, 16 modified files, 0 problems; `tests/vendoring` 157 passed |

## Tests (`python -m pytest tests/render`, `uzp-render-tests.exe`)

| Task item | Case | Evidence of this run | Verdict |
|---|---|---|---|
| 3.1 drain (P1-CORE gate item) | `readback-drain` | 64 readback requests over 8 textures (R16Unorm, RGBA16Unorm, R8Unorm, RGBA8Unorm, R16Float, RGBA16Float, R32Float, RGBA32Float; 1 to 4097 texels wide) in flight at once, each with its own staging buffer (the D3D12MA allocation count rose by exactly 64); `Drain()` reported all 64 in submission order with every texel exact; afterwards no request outstanding and the allocation count back at its baseline. A `TextureReadback` destroyed with 17 outstanding requests released all 17; four threads each submitting a 16-readback burst all drained exactly; at the end the device held no more allocations than before the first request | met |
| 3.2 pitch | `readback-pitch` | widths 1, 3, 1023 and 4097 texels, 5 rows, in L8 (R8Unorm), RGB8 (RGBA8Unorm, 3 channels), L16 (R16Unorm), RGB16 (RGBA16Unorm, 3 channels), RGB16F (RGBA16Float, 3 channels), L32F (R32Float), RGBA32Float and RGB32F (RGB32Float): every row read back unshifted; the readback pitch equalled the row pitch D3D12's `GetCopyableFootprints` reports in every case (uploads used that footprint, independently of the readback code) | met |
| 3.3 exactness | `readback-exact` | pseudo-random bytes (every bit pattern, float NaNs and denormals included) uploaded to 1023 x 7 textures of all 19 readable formats — R8/RG8/RGBA8 unorm and sRGB, BGRA8 unorm and sRGB, R16/RG16/RGBA16 unorm, R16/RG16/RGBA16 float, R32/RG32/RGB32/RGBA32 float, R32/RG32/RGBA32 uint — read back bit-identical; the spec's scenario (an RGB16 texture 1023 texels wide) read back every texel unchanged; mip level 2 (16 x 10) of a 64 x 40 RGBA16Unorm texture read back bit-identical | met |
| 3.4 failure | `readback-failure` | a readback succeeded; new contents were uploaded; two readbacks were pending when `ID3D12Device5::RemoveDevice` was called: the completed one failed with `device_removed {backend: dx12, reason: DXGI_ERROR_DEVICE_REMOVED (0x887A0005)}` and returned no texels (neither the earlier nor the new ones), the drain failed the other the same way, a readback requested afterwards failed with `device_removed`, no staging buffer was left. A readback behind a stalled queue (300 ms deadline) failed with `timeout` and no texels; its staging buffer was held until the queue was released and the copy completed, then the drain released it | met |
| 2.4 formats, UZP-MOD-009 | `readback-layout` | the texel layout of every readable format matches the RHI's bytes per texel; the RHI sizes the 16-bit unorm formats (2, 4, 8 bytes) and maps them to `DXGI_FORMAT_R16_UNORM`, `R16G16_UNORM`, `R16G16B16A16_UNORM`; block-compressed, depth and unknown formats are rejected | met |

`readback-layout` also runs under `UZP_NO_GPU=1` (hosted CI); the four GPU cases skip there with the decision-028 reason. The capability report now lists 31 formats (the 28 of `core-device-kernels.md` plus the three 16-bit unorm formats).

## Reproduce

```
zig build render-tests
python -m pytest tests/render tests/vendoring/test_modifications.py
zig-out\bin\uzp-render-tests.exe readback-drain <work-dir>
```
