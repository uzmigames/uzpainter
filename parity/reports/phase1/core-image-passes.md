# P1-CORE child `phase1.3_core-image-passes` — owner's machine run

Task `phase1.3_core-image-passes`, child of `phase1.4_render-core-layer` (P1-CORE, `docs/dag.md`; `docs/architecture/13-engine-integration.md` §4.1, `04-layer-stack-and-compositing.md` §7, `08-export.md` §3). Decision 028: GPU checks run locally on the owner's machine and this report is their evidence for the parent's acceptance (P1-CORE gate item, image-pass part: unit tests on synthetic masks and images green on DX12, each pass equal to its CPU reference and repeatable byte for byte). Run on 2026-10-10 on the tree of commit `a6f9cfa` with the working-tree changes of the Phase 1 tasks in progress and this task.

**Result: all image-pass tests green on the DX12 hardware adapter.** The Painter-fitted padding modes (`phase1.16_export-processing-encoders`) and the Tier 0 comparisons of resampling (`phase1.8_compositor-sources-projection`) build on these passes and are not part of this task.

## Machine and build

| Item | Value |
|---|---|
| Machine | Windows 11 (build 10.0.26200), NVIDIA GeForce RTX 4090, the adapter of `core-device-kernels.md` |
| Build | `zig build render-tests` and `zig build painter` (Zig 0.15.2, Debug), `-Wall -Wextra -Werror` on `src/render/` and `tests/render/`, exit code 0 |
| Kernels | `src/render/shaders/dilation_jfa.hlsl` (3 entry points), `resample.hlsl` (1), `mips.hlsl` (7), shared `image_common.hlsli` and the generated `srgb_tables.hlsli`; embedded with `#embed`, compiled `cs_6_6 -Gis` through the kernel cache, resources through SM 6.6 `ResourceDescriptorHeap`. Each kernel also compiles to SPIR-V (checked once during the task; Vulkan dispatch is Phase 3) |

## Arithmetic

Exact integer arithmetic on unorm codes, single IEEE float operations in a fixed order for float channels, no hardware approximation in any result (no `pow`, `rsqrt` or `sqrt`; the one division, code / M before a unorm store, is far within the store conversion's rounding to the exact code). Unorm results use the float-to-UNORM write rule of `parity/semantics/resampling.json` (truncate to n + 4 fractional bits, nearest code, ties down); 16-bit float results round to the nearest half, ties to even; sRGB decode and encode go through float32 tables of IEC 61966-2-1; normals are renormalised with a three-step Newton reciprocal square root. The CPU references (`tests/render/reference/`) are written independently: 128-bit integer division for the write rule, the compiler's `_Float16` conversion for half rounding, their own sRGB tables.

## Tests (`python -m pytest tests/render/test_core_image_passes.py`, `uzp-render-tests.exe image-*`)

| Task item | Case | Evidence of this run | Verdict |
|---|---|---|---|
| 2.4 references | `image-reference` (CPU, also under `UZP_NO_GPU=1`) | the write rule equals the resampling.json BilinearHQ storage formula for all 16 776 961 weighted sums 0 .. 256 x 65535; halfway values round down; every 8- and 16-bit code's value maps back to the code; sRGB encode inverts decode for all 256 codes; jump-flood schedules (8-texel limit: 1, 8, 4, 2, 1); jump flooding equals the brute-force nearest covered texel on the island masks (limit 8 and unlimited), and on four random 2 % masks of 128 x 128 no texel differs | met |
| 3.1 dilation | `image-dilation` | two islands (a disc of radius 12.5 and an L-shaped block) in a 96 x 80 R8Unorm mask, distance 8, in RGBA8Unorm, RGBA16Unorm, RGBA16Float and R32Float: equal to the CPU jump-flood reference and to the brute-force nearest covered texel (ties to the smaller linear index) exactly; 1733 texels filled; every covered texel and every texel farther than 8 texels unchanged. Unlimited distance fills every texel with its nearest island's colour; three random masks (128 x 112, 2 %) at distance 5 and unlimited equal the CPU jump-flood reference; distance 0 copies; a mask of another size is rejected with `request_failed` | met |
| 3.2 resampling | `image-resample` | 13 format and colour-mode combinations (R8/RG8/RGBA8/R16/RGBA16 unorm, R32/RG16/RGBA16/RGBA32 float; linear, sRGB on 8-bit, normal on four channels) from 37 x 29: identity size bit-exact for Nearest, Bilinear and Box; 64 x 48, 16 x 11, 37 x 58, 5 x 3 and 111 x 29 equal the CPU reference for Nearest, Bilinear (clamp and repeat) and Box (94 checks); sRGB filtering of a float format is rejected | met |
| 3.3 mips | `image-mips` | sRGB8 chains of 64 x 40 (7 levels) and 45 x 27 (6 levels) equal the CPU decode-filter-encode reference on every level; linear chains (RGBA16Unorm, R16Float, RGBA32Float, RG8Unorm, 45 x 27) equal the reference; normal chains (RGBA16Unorm, RGBA8Unorm, RGBA16Float, 64 x 48) equal the renormalising reference with worst \|length − 1\| 0.000024, 0.0059 and 0.00040 against storage-precision bounds 0.000031, 0.0076 and 0.00085; alpha coverage at cutoff 0.5 (code 128) of a 64 x 64 foliage mask (2054 of 4096 covered) is preserved exactly on every level (513/1024, 128/256, 32/64, 8/16, 2/4, 1/1) and equals the reference with linear and sRGB colour; without preservation level 3 covers 38 of 64 instead of 32 | met |
| 3.4 repeat | `image-repeat` | unlimited dilation (RGBA16Float), sRGB bilinear resampling with repeat (RGBA8Unorm to 301 x 77), box resampling (RGBA16Float to 45 x 31), a normal mip chain (RGBA16Unorm) and an sRGB alpha-coverage chain (RGBA8Unorm), each run twice: byte-identical outputs | met |

The four GPU cases skip under `UZP_NO_GPU=1` (hosted CI) with the decision-028 reason.

## Reproduce

```
zig build render-tests
python -m pytest tests/render/test_core_image_passes.py
zig-out\bin\uzp-render-tests.exe image-mips <work-dir>
```
