# Compositor core: union of the Tier 0 golden sets (`phase1.14_compositor-core`)

Run: **final**, 2026-10-12 22:38 UTC, commit `563e0cc873b4`, envelope `painter-12.1.5+js-api.1.1.20`, backend DX12 (`gpu`), adapter NVIDIA GeForce RTX 4090. Command: `python tests/evaluator/union_run.py --label final` (2 passes in separate processes, pass-a 850 s, pass-b 880 s). Numbers and hashes only (`docs/licensing-and-clean-room.md`).

The union is every Tier 0 golden test of the compositor children (`tests/evaluator/test_compositor_*.py`, `backend=gpu`), each comparing with its own conversion and domain (`tests/evaluator/union_run.py`). |Δ| is in the unit named per row (16-bit export codes or float values); mean and p99 are pooled over every compared value of the row (p99 nearest-rank, exact from the |Δ| histograms); differing texels have at least one differing component. Verdicts follow `tools/parity/verdict.py` (an unstable golden's exact target is r1, decision 032; r2 passes only through the exception register).

## Headline

- Goldens compared: 74; maps: 1839; comparisons: 3639 (1850 against r1, 1789 against r2).
- Against r1: 1850 of 1850 maps exact.
- Verdicts: pass 3639.
- Oracle stability: 36 of 1839 compared maps differ between r1 and r2.
- UzPainter repeatability: 1899 of 1899 evaluated channel rasters byte-identical across the passes; 3639 of 3639 comparison statistics identical.
- Tests per pass: pass-a: 163 passed, 0 failed, 0 skipped; pass-b: 163 passed, 0 failed, 0 skipped.

## Per golden

| Golden | Unit | Maps | vs r1: max, mean, p99 | r1 differing texels (%) | vs r2: max, mean, p99 | r2 differing texels (%) | Oracle r1 vs r2 | Record SHA-256 |
|---|---|---|---|---|---|---|---|---|
| `tier0/semantics-ui/group-passthrough-masks` | 16-bit code value | 8 | 0, 0, 0 | 0 of 524288 (0.0000) | 0, 0, 0 | 0 of 524288 (0.0000) | stable (12 maps) | `a0de2aa898ec4f74` |
| `tier0/semantics-ui/group-passthrough-masks` | float32 value | 4 | 0, 0, 0 | 0 of 262144 (0.0000) | 0, 0, 0 | 0 of 262144 (0.0000) | stable (12 maps) | `a0de2aa898ec4f74` |
| `tier0/semantics-ui/height-normal-sharp-bevelled-cube` | 16-bit code value | 2 | 0, 0, 0 | 0 of 102080 (0.0000) | 0, 0, 0 | 0 of 102080 (0.0000) | stable (3 maps) | `0d52e0c853818944` |
| `tier0/semantics-ui/height-normal-sharp-bevelled-cube` | float32 value | 1 | 0, 0, 0 | 0 of 51040 (0.0000) | 0, 0, 0 | 0 of 51040 (0.0000) | stable (3 maps) | `0d52e0c853818944` |
| `tier0/semantics-ui/height-normal-sharp-plane-strength` | 16-bit code value | 16 | 0, 0, 0 | 0 of 1048576 (0.0000) | 0, 0, 0 | 0 of 786432 (0.0000) | unstable: 6 of 24 maps, max 31 | `2fe57df3bd838b54` |
| `tier0/semantics-ui/height-normal-sharp-plane-strength` | float32 value | 8 | 0, 0, 0 | 0 of 524288 (0.0000) | 0, 0, 0 | 0 of 393216 (0.0000) | unstable: 6 of 24 maps, max 31 | `2fe57df3bd838b54` |
| `tier0/semantics-ui/height-normal-sharp-sphere` | 16-bit code value | 2 | 0, 0, 0 | 0 of 117632 (0.0000) | 0, 0, 0 | 0 of 117632 (0.0000) | stable (3 maps) | `28a1fbfc27030637` |
| `tier0/semantics-ui/height-normal-sharp-sphere` | float32 value | 1 | 0, 0, 0 | 0 of 58816 (0.0000) | 0, 0, 0 | 0 of 58816 (0.0000) | stable (3 maps) | `28a1fbfc27030637` |
| `tier0/semantics-ui/height-normal-sobel-bevelled-cube` | 16-bit code value | 2 | 0, 0, 0 | 0 of 102080 (0.0000) | 0, 0, 0 | 0 of 102080 (0.0000) | stable (3 maps) | `0836b799ac2138e3` |
| `tier0/semantics-ui/height-normal-sobel-bevelled-cube` | float32 value | 1 | 0, 0, 0 | 0 of 51040 (0.0000) | 0, 0, 0 | 0 of 51040 (0.0000) | stable (3 maps) | `0836b799ac2138e3` |
| `tier0/semantics-ui/height-normal-sobel-plane-strength` | 16-bit code value | 16 | 0, 0, 0 | 0 of 1048576 (0.0000) | 0, 0, 0 | 0 of 786432 (0.0000) | unstable: 6 of 24 maps, max 16 | `c427fce046ae6c0b` |
| `tier0/semantics-ui/height-normal-sobel-plane-strength` | float32 value | 8 | 0, 0, 0 | 0 of 524288 (0.0000) | 0, 0, 0 | 0 of 393216 (0.0000) | unstable: 6 of 24 maps, max 16 | `c427fce046ae6c0b` |
| `tier0/semantics-ui/height-normal-sobel-sphere` | 16-bit code value | 2 | 0, 0, 0 | 0 of 117632 (0.0000) | 0, 0, 0 | 0 of 117632 (0.0000) | stable (3 maps) | `33cf373c58d97c9a` |
| `tier0/semantics-ui/height-normal-sobel-sphere` | float32 value | 1 | 0, 0, 0 | 0 of 58816 (0.0000) | 0, 0, 0 | 0 of 58816 (0.0000) | stable (3 maps) | `33cf373c58d97c9a` |
| `tier0/semantics/base-values-asm-pbr-metallic-roughness` | 16-bit code value | 5 | 0, 0, 0 | 0 of 327680 (0.0000) | 0, 0, 0 | 0 of 327680 (0.0000) | stable (5 maps) | `2318d74099fde442` |
| `tier0/semantics/base-values-asm-pbr-metallic-roughness-anisotropy-angle` | 16-bit code value | 7 | 0, 0, 0 | 0 of 458752 (0.0000) | 0, 0, 0 | 0 of 458752 (0.0000) | stable (7 maps) | `2b6e023353227a7d` |
| `tier0/semantics/base-values-asm-pbr-metallic-roughness-coated` | 16-bit code value | 5 | 0, 0, 0 | 0 of 327680 (0.0000) | 0, 0, 0 | 0 of 327680 (0.0000) | stable (5 maps) | `1a04028bb03f2bc4` |
| `tier0/semantics/base-values-asm-pbr-metallic-roughness-sheen` | 16-bit code value | 5 | 0, 0, 0 | 0 of 327680 (0.0000) | 0, 0, 0 | 0 of 327680 (0.0000) | stable (5 maps) | `40d55228770df7de` |
| `tier0/semantics/base-values-asm-pbr-metallic-roughness-sss` | 16-bit code value | 6 | 0, 0, 0 | 0 of 393216 (0.0000) | 0, 0, 0 | 0 of 393216 (0.0000) | stable (6 maps) | `f9a3bc2892e36dae` |
| `tier0/semantics/base-values-blender` | 16-bit code value | 7 | 0, 0, 0 | 0 of 458752 (0.0000) | 0, 0, 0 | 0 of 458752 (0.0000) | stable (7 maps) | `78018e8e03832132` |
| `tier0/semantics/base-values-default` | 16-bit code value | 10 | 0, 0, 0 | 0 of 655360 (0.0000) | 0, 0, 0 | 0 of 655360 (0.0000) | stable (14 maps) | `bfcde7de54ebe75e` |
| `tier0/semantics/base-values-default` | float32 value | 4 | 0, 0, 0 | 0 of 262144 (0.0000) | 0, 0, 0 | 0 of 262144 (0.0000) | stable (14 maps) | `bfcde7de54ebe75e` |
| `tier0/semantics/base-values-dota-2` | 16-bit code value | 10 | 0, 0, 0 | 0 of 655360 (0.0000) | 0, 0, 0 | 0 of 655360 (0.0000) | stable (10 maps) | `303f5750c28ccce7` |
| `tier0/semantics/base-values-keyshot` | 16-bit code value | 10 | 0, 0, 0 | 0 of 655360 (0.0000) | 0, 0, 0 | 0 of 655360 (0.0000) | stable (10 maps) | `9fd1efab554f5ad2` |
| `tier0/semantics/base-values-lens-studio` | 16-bit code value | 6 | 0, 0, 0 | 0 of 393216 (0.0000) | 0, 0, 0 | 0 of 393216 (0.0000) | stable (6 maps) | `41549fce73b5bd07` |
| `tier0/semantics/base-values-maxwell-metallic-roughness` | 16-bit code value | 5 | 0, 0, 0 | 0 of 327680 (0.0000) | 0, 0, 0 | 0 of 327680 (0.0000) | stable (5 maps) | `c440cf2c35d93a36` |
| `tier0/semantics/base-values-maxwell-specular-glossiness` | 16-bit code value | 5 | 0, 0, 0 | 0 of 327680 (0.0000) | 0, 0, 0 | 0 of 327680 (0.0000) | stable (5 maps) | `c0f0019032037418` |
| `tier0/semantics/base-values-non-pbr-specular-glossiness` | 16-bit code value | 6 | 0, 0, 0 | 0 of 393216 (0.0000) | 0, 0, 0 | 0 of 393216 (0.0000) | stable (6 maps) | `7ccec9147feab217` |
| `tier0/semantics/base-values-openpbr-anisotropy` | 16-bit code value | 6 | 0, 0, 0 | 0 of 393216 (0.0000) | 0, 0, 0 | 0 of 393216 (0.0000) | stable (6 maps) | `56c538f9dcbd9748` |
| `tier0/semantics/base-values-openpbr-coat` | 16-bit code value | 5 | 0, 0, 0 | 0 of 327680 (0.0000) | 0, 0, 0 | 0 of 327680 (0.0000) | stable (5 maps) | `634c0322ad250d65` |
| `tier0/semantics/base-values-openpbr-fuzz` | 16-bit code value | 5 | 0, 0, 0 | 0 of 327680 (0.0000) | 0, 0, 0 | 0 of 327680 (0.0000) | stable (5 maps) | `8d3da793be7de41f` |
| `tier0/semantics/base-values-openpbr-subsurface-scattering` | 16-bit code value | 6 | 0, 0, 0 | 0 of 393216 (0.0000) | 0, 0, 0 | 0 of 393216 (0.0000) | stable (6 maps) | `db13ca9af0ae8621` |
| `tier0/semantics/base-values-pbr-metallic-roughness-alpha-blend` | 16-bit code value | 7 | 0, 0, 0 | 0 of 458752 (0.0000) | 0, 0, 0 | 0 of 458752 (0.0000) | stable (7 maps) | `9b6cd76737b6b5e5` |
| `tier0/semantics/base-values-pbr-metallic-roughness-alpha-test` | 16-bit code value | 7 | 0, 0, 0 | 0 of 458752 (0.0000) | 0, 0, 0 | 0 of 458752 (0.0000) | stable (7 maps) | `70868f67a43e0a91` |
| `tier0/semantics/base-values-pbr-specular-glossiness` | 16-bit code value | 5 | 0, 0, 0 | 0 of 327680 (0.0000) | 0, 0, 0 | 0 of 327680 (0.0000) | stable (5 maps) | `6428a61f3cf28adf` |
| `tier0/semantics/base-values-roblox-materialvariant` | 16-bit code value | 5 | 0, 0, 0 | 0 of 327680 (0.0000) | 0, 0, 0 | 0 of 327680 (0.0000) | stable (5 maps) | `019957ea83cd771c` |
| `tier0/semantics/base-values-roblox-surfaceappearance` | 16-bit code value | 6 | 0, 0, 0 | 0 of 393216 (0.0000) | 0, 0, 0 | 0 of 393216 (0.0000) | stable (6 maps) | `0b4bb07a0e6959d1` |
| `tier0/semantics/base-values-spark-ar-studio` | 16-bit code value | 7 | 0, 0, 0 | 0 of 458752 (0.0000) | 0, 0, 0 | 0 of 458752 (0.0000) | stable (7 maps) | `3bc482e84fdd1311` |
| `tier0/semantics/base-values-unity-hd-render-pipeline-metallic-standard` | 16-bit code value | 5 | 0, 0, 0 | 0 of 327680 (0.0000) | 0, 0, 0 | 0 of 327680 (0.0000) | stable (5 maps) | `279971d2a0280422` |
| `tier0/semantics/base-values-unreal-engine` | 16-bit code value | 5 | 0, 0, 0 | 0 of 327680 (0.0000) | 0, 0, 0 | 0 of 327680 (0.0000) | stable (5 maps) | `a324372db9032e83` |
| `tier0/semantics/base-values-vraymtl-metallic-roughness` | 16-bit code value | 9 | 0, 0, 0 | 0 of 589824 (0.0000) | 0, 0, 0 | 0 of 589824 (0.0000) | stable (9 maps) | `5df3fcbef6d5a75d` |
| `tier0/semantics/base-values-vraymtl-specular-glossiness` | 16-bit code value | 9 | 0, 0, 0 | 0 of 589824 (0.0000) | 0, 0, 0 | 0 of 589824 (0.0000) | stable (9 maps) | `1dc2b2acea6f88c3` |
| `tier0/semantics/blend-additive` | 16-bit code value | 48 | 0, 0, 0 | 0 of 3145728 (0.0000) | 0, 0, 0 | 0 of 3145728 (0.0000) | stable (64 maps) | `a46965d398323fe8` |
| `tier0/semantics/blend-additive` | float32 value | 17 | 0, 0, 0 | 0 of 1114112 (0.0000) | 0, 0, 0 | 0 of 1114112 (0.0000) | stable (64 maps) | `a46965d398323fe8` |
| `tier0/semantics/blend-basic` | 16-bit code value | 50 | 0, 0, 0 | 0 of 3276800 (0.0000) | 0, 0, 0 | 0 of 3276800 (0.0000) | stable (64 maps) | `a08e98a8a46fad5e` |
| `tier0/semantics/blend-basic` | float32 value | 16 | 0, 0, 0 | 0 of 1048576 (0.0000) | 0, 0, 0 | 0 of 1048576 (0.0000) | stable (64 maps) | `a08e98a8a46fad5e` |
| `tier0/semantics/blend-component` | 16-bit code value | 42 | 0, 0, 0 | 0 of 2752512 (0.0000) | 0, 0, 0 | 0 of 2752512 (0.0000) | stable (56 maps) | `ca5f1cd5ecaa46f2` |
| `tier0/semantics/blend-component` | float32 value | 14 | 0, 0, 0 | 0 of 917504 (0.0000) | 0, 0, 0 | 0 of 917504 (0.0000) | stable (56 maps) | `ca5f1cd5ecaa46f2` |
| `tier0/semantics/blend-component-hue` | 16-bit code value | 20 | 0, 0, 0 | 0 of 1310720 (0.0000) | 0, 0, 0 | 0 of 1310720 (0.0000) | stable (40 maps) | `d5faa211e79b4376` |
| `tier0/semantics/blend-component-hue` | float32 value | 20 | 0, 0, 0 | 0 of 1310720 (0.0000) | 0, 0, 0 | 0 of 1310720 (0.0000) | stable (40 maps) | `d5faa211e79b4376` |
| `tier0/semantics/blend-contrast` | 16-bit code value | 50 | 0, 0, 0 | 0 of 3276800 (0.0000) | 0, 0, 0 | 0 of 3276800 (0.0000) | stable (64 maps) | `eb5592917501a662` |
| `tier0/semantics/blend-contrast` | float32 value | 16 | 0, 0, 0 | 0 of 1048576 (0.0000) | 0, 0, 0 | 0 of 1048576 (0.0000) | stable (64 maps) | `eb5592917501a662` |
| `tier0/semantics/blend-inputs` | 16-bit code value | 18 | 0, 0, 0 | 0 of 1179648 (0.0000) | 0, 0, 0 | 0 of 786432 (0.0000) | unstable: 3 of 20 maps, max 768 | `e8f9ccdad8c44531` |
| `tier0/semantics/blend-inputs` | float32 value | 2 | 0, 0, 0 | 0 of 131072 (0.0000) | not compared | - | unstable: 3 of 20 maps, max 768 | `e8f9ccdad8c44531` |
| `tier0/semantics/blend-normal-channel` | 16-bit code value | 4 | 0, 0, 0 | 0 of 262144 (0.0000) | 0, 0, 0 | 0 of 262144 (0.0000) | stable (7 maps) | `f73f5a5e8cdc6932` |
| `tier0/semantics/blend-normal-channel` | float32 value | 3 | 0, 0, 0 | 0 of 196608 (0.0000) | 0, 0, 0 | 0 of 196608 (0.0000) | stable (7 maps) | `f73f5a5e8cdc6932` |
| `tier0/semantics/blend-normal-opacity` | 16-bit code value | 24 | 0, 0, 0 | 0 of 1572864 (0.0000) | 0, 0, 0 | 0 of 1572864 (0.0000) | stable (48 maps) | `2a4539ba565470b6` |
| `tier0/semantics/blend-normal-opacity` | float32 value | 24 | 0, 0, 0 | 0 of 1572864 (0.0000) | 0, 0, 0 | 0 of 1572864 (0.0000) | stable (48 maps) | `2a4539ba565470b6` |
| `tier0/semantics/blend-order` | 16-bit code value | 8 | 0, 0, 0 | 0 of 524288 (0.0000) | 0, 0, 0 | 0 of 524288 (0.0000) | stable (8 maps) | `14c64f1684445f4b` |
| `tier0/semantics/colour-ramps-raw` | 16-bit code value | 192 | 0, 0, 0 | 0 of 12582912 (0.0000) | 0, 0, 0 | 0 of 12582912 (0.0000) | stable (192 maps) | `7a429426a14da3fe` |
| `tier0/semantics/colour-ramps-srgb` | 16-bit code value | 192 | 0, 0, 0 | 0 of 12582912 (0.0000) | 0, 0, 0 | 0 of 12582912 (0.0000) | stable (192 maps) | `ac241b7c0623e7c4` |
| `tier0/semantics/colour-ramps-working` | 16-bit code value | 192 | 0, 0, 0 | 0 of 12582912 (0.0000) | 0, 0, 0 | 0 of 12582912 (0.0000) | stable (192 maps) | `5aef5c6646ca45d7` |
| `tier0/semantics/coverage-srgb8-ties` | 16-bit code value | 72 | 0, 0, 0 | 0 of 4718592 (0.0000) | 0, 0, 0 | 0 of 4718592 (0.0000) | stable (80 maps) | `01127c451fde36c8` |
| `tier0/semantics/coverage-srgb8-ties` | float32 value | 8 | 0, 0, 0 | 0 of 524288 (0.0000) | 0, 0, 0 | 0 of 524288 (0.0000) | stable (80 maps) | `01127c451fde36c8` |
| `tier0/semantics/effect-order` | 16-bit code value | 2 | 0, 0, 0 | 0 of 131072 (0.0000) | 0, 0, 0 | 0 of 131072 (0.0000) | stable (2 maps) | `b9627242fdadc932` |
| `tier0/semantics/group-coverage-order` | 16-bit code value | 16 | 0, 0, 0 | 0 of 1048576 (0.0000) | 0, 0, 0 | 0 of 1048576 (0.0000) | stable (24 maps) | `a58ea909846c403f` |
| `tier0/semantics/group-coverage-order` | float32 value | 8 | 0, 0, 0 | 0 of 524288 (0.0000) | 0, 0, 0 | 0 of 524288 (0.0000) | stable (24 maps) | `a58ea909846c403f` |
| `tier0/semantics/group-masks` | 16-bit code value | 8 | 0, 0, 0 | 0 of 524288 (0.0000) | 0, 0, 0 | 0 of 524288 (0.0000) | stable (12 maps) | `0c709211d33a0b2b` |
| `tier0/semantics/group-masks` | float32 value | 4 | 0, 0, 0 | 0 of 262144 (0.0000) | 0, 0, 0 | 0 of 262144 (0.0000) | stable (12 maps) | `0c709211d33a0b2b` |
| `tier0/semantics/height-normal-bevelled-cube` | 16-bit code value | 2 | 0, 0, 0 | 0 of 102080 (0.0000) | 0, 0, 0 | 0 of 102080 (0.0000) | stable (3 maps) | `74fe1bb68527800c` |
| `tier0/semantics/height-normal-bevelled-cube` | float32 value | 2 | 0, 0, 0 | 0 of 104376 (0.0000) | 0, 0, 0 | 0 of 104376 (0.0000) | stable (3 maps) | `74fe1bb68527800c` |
| `tier0/semantics/height-normal-channel-coverage` | 16-bit code value | 16 | 0, 0, 0 | 0 of 1048576 (0.0000) | 0, 0, 0 | 0 of 917504 (0.0000) | unstable: 3 of 28 maps, max 61 | `58fa28f33cdfefdb` |
| `tier0/semantics/height-normal-channel-coverage` | float32 value | 12 | 0, 0, 0 | 0 of 786432 (0.0000) | 0, 0, 0 | 0 of 720896 (0.0000) | unstable: 3 of 28 maps, max 61 | `58fa28f33cdfefdb` |
| `tier0/semantics/height-normal-mesh-map` | 16-bit code value | 16 | 0, 0, 0 | 0 of 1048576 (0.0000) | 0, 0, 0 | 0 of 1048576 (0.0000) | stable (28 maps) | `245069a4495272c2` |
| `tier0/semantics/height-normal-mesh-map` | float32 value | 12 | 0, 0, 0 | 0 of 786432 (0.0000) | 0, 0, 0 | 0 of 786432 (0.0000) | stable (28 maps) | `245069a4495272c2` |
| `tier0/semantics/height-normal-mesh-map-directx` | 16-bit code value | 8 | 0, 0, 0 | 0 of 524288 (0.0000) | 0, 0, 0 | 0 of 524288 (0.0000) | stable (14 maps) | `0571d1d45aba0b76` |
| `tier0/semantics/height-normal-mesh-map-directx` | float32 value | 6 | 0, 0, 0 | 0 of 393216 (0.0000) | 0, 0, 0 | 0 of 393216 (0.0000) | stable (14 maps) | `0571d1d45aba0b76` |
| `tier0/semantics/height-normal-plane-amplitudes` | 16-bit code value | 8 | 0, 0, 0 | 0 of 524288 (0.0000) | 0, 0, 0 | 0 of 524288 (0.0000) | stable (12 maps) | `ffbdd78546998ce3` |
| `tier0/semantics/height-normal-plane-amplitudes` | float32 value | 8 | 0, 0, 0 | 0 of 524288 (0.0000) | 0, 0, 0 | 0 of 524288 (0.0000) | stable (12 maps) | `ffbdd78546998ce3` |
| `tier0/semantics/height-normal-resolution-1024` | 16-bit code value | 8 | 0, 0, 0 | 0 of 8388608 (0.0000) | 0, 0, 0 | 0 of 8388608 (0.0000) | stable (12 maps) | `5a63f7eca7893785` |
| `tier0/semantics/height-normal-resolution-1024` | float32 value | 4 | 0, 0, 0 | 0 of 4194304 (0.0000) | 0, 0, 0 | 0 of 4194304 (0.0000) | stable (12 maps) | `5a63f7eca7893785` |
| `tier0/semantics/height-normal-resolution-1024-sobel` | 16-bit code value | 8 | 0, 0, 0 | 0 of 8388608 (0.0000) | 0, 0, 0 | 0 of 8388608 (0.0000) | stable (12 maps) | `6e51f5eccb47721b` |
| `tier0/semantics/height-normal-resolution-1024-sobel` | float32 value | 4 | 0, 0, 0 | 0 of 4194304 (0.0000) | 0, 0, 0 | 0 of 4194304 (0.0000) | stable (12 maps) | `6e51f5eccb47721b` |
| `tier0/semantics/height-normal-resolution-2048` | 16-bit code value | 8 | 0, 0, 0 | 0 of 33554432 (0.0000) | 0, 0, 0 | 0 of 25165824 (0.0000) | unstable: 2 of 12 maps, max 1 | `0f02c91260dac103` |
| `tier0/semantics/height-normal-resolution-2048` | float32 value | 4 | 0, 0, 0 | 0 of 16777216 (0.0000) | 0, 0, 0 | 0 of 16777216 (0.0000) | unstable: 2 of 12 maps, max 1 | `0f02c91260dac103` |
| `tier0/semantics/height-normal-resolution-512` | 16-bit code value | 8 | 0, 0, 0 | 0 of 2097152 (0.0000) | 0, 0, 0 | 0 of 2097152 (0.0000) | stable (12 maps) | `e52b103f64176ebf` |
| `tier0/semantics/height-normal-resolution-512` | float32 value | 4 | 0, 0, 0 | 0 of 1048576 (0.0000) | 0, 0, 0 | 0 of 1048576 (0.0000) | stable (12 maps) | `e52b103f64176ebf` |
| `tier0/semantics/height-normal-sphere` | 16-bit code value | 2 | 0, 0, 0 | 0 of 117632 (0.0000) | 0, 0, 0 | 0 of 117632 (0.0000) | stable (3 maps) | `1a05c72b79b77abe` |
| `tier0/semantics/height-normal-sphere` | float32 value | 2 | 0, 0, 0 | 0 of 120256 (0.0000) | 0, 0, 0 | 0 of 120256 (0.0000) | stable (3 maps) | `1a05c72b79b77abe` |
| `tier0/semantics/height-signed-addition` | 16-bit code value | 16 | 0, 0, 0 | 0 of 1048576 (0.0000) | 0, 0, 0 | 0 of 1048576 (0.0000) | stable (24 maps) | `731b1e97ca020aaa` |
| `tier0/semantics/height-signed-addition` | float32 value | 8 | 0, 0, 0 | 0 of 524288 (0.0000) | 0, 0, 0 | 0 of 524288 (0.0000) | stable (24 maps) | `731b1e97ca020aaa` |
| `tier0/semantics/levels-clamp` | 16-bit code value | 4 | 0, 0, 0 | 0 of 262144 (0.0000) | 0, 0, 0 | 0 of 262144 (0.0000) | stable (16 maps) | `385ff8dd604e5fb0` |
| `tier0/semantics/levels-clamp` | float32 value | 12 | 0, 0, 0 | 0 of 786432 (0.0000) | 0, 0, 0 | 0 of 786432 (0.0000) | stable (16 maps) | `385ff8dd604e5fb0` |
| `tier0/semantics/mask-precision` | 16-bit code value | 16 | 0, 0, 0 | 0 of 1048576 (0.0000) | 0, 0, 0 | 0 of 1048576 (0.0000) | stable (20 maps) | `e2d703c9d2872784` |
| `tier0/semantics/mask-precision` | float32 value | 4 | 0, 0, 0 | 0 of 262144 (0.0000) | 0, 0, 0 | 0 of 262144 (0.0000) | stable (20 maps) | `e2d703c9d2872784` |
| `tier0/semantics/normal-channel-import` | 16-bit code value | 8 | 0, 0, 0 | 0 of 524288 (0.0000) | 0, 0, 0 | 0 of 524288 (0.0000) | stable (14 maps) | `eebb4246d50ec6d5` |
| `tier0/semantics/normal-channel-import` | float32 value | 6 | 0, 0, 0 | 0 of 393216 (0.0000) | 0, 0, 0 | 0 of 393216 (0.0000) | stable (14 maps) | `eebb4246d50ec6d5` |
| `tier0/semantics/normal-channel-import-directx` | 16-bit code value | 8 | 0, 0, 0 | 0 of 524288 (0.0000) | 0, 0, 0 | 0 of 524288 (0.0000) | stable (14 maps) | `835b59789f332545` |
| `tier0/semantics/normal-channel-import-directx` | float32 value | 6 | 0, 0, 0 | 0 of 393216 (0.0000) | 0, 0, 0 | 0 of 393216 (0.0000) | stable (14 maps) | `835b59789f332545` |
| `tier0/semantics/quantisation-thirds` | 16-bit code value | 20 | 0, 0, 0 | 0 of 1310720 (0.0000) | not compared | - | unstable: 16 of 36 maps, max 512 | `7cf9c35b8d633e61` |
| `tier0/semantics/quantisation-thirds` | float32 value | 16 | 0, 0, 0 | 0 of 1048576 (0.0000) | not compared | - | unstable: 16 of 36 maps, max 512 | `7cf9c35b8d633e61` |
| `tier0/semantics/resample-uv` | 16-bit code value | 32 | 0, 0, 0 | 0 of 2097152 (0.0000) | 0, 0, 0 | 0 of 2097152 (0.0000) | stable (32 maps) | `367d491d7c52a165` |
| `tier0/semantics/resample-uv-anisotropic` | 16-bit code value | 40 | 0, 0, 0 | 0 of 2621440 (0.0000) | 0, 0, 0 | 0 of 2621440 (0.0000) | stable (40 maps) | `f9421359740f9701` |
| `tier0/semantics/resample-uv-anisotropic-impulse` | 16-bit code value | 40 | 0, 0, 0 | 0 of 2621440 (0.0000) | 0, 0, 0 | 0 of 2621440 (0.0000) | stable (40 maps) | `bc5a5096db686939` |
| `tier0/semantics/resample-uv-impulse` | 16-bit code value | 32 | 0, 0, 0 | 0 of 2097152 (0.0000) | 0, 0, 0 | 0 of 2097152 (0.0000) | stable (32 maps) | `d4e0d8c2bef7d5e8` |
| `tier0/semantics/resample-uv-lod` | 16-bit code value | 32 | 0, 0, 0 | 0 of 2097152 (0.0000) | 0, 0, 0 | 0 of 2097152 (0.0000) | stable (32 maps) | `80bf855316ed9059` |
| `tier0/semantics/resample-uv-lod-boundaries` | 16-bit code value | 40 | 0, 0, 0 | 0 of 2621440 (0.0000) | 0, 0, 0 | 0 of 2621440 (0.0000) | stable (40 maps) | `cbc19cbd97632759` |
| `tier0/semantics/resample-uv-minify` | 16-bit code value | 28 | 0, 0, 0 | 0 of 1835008 (0.0000) | 0, 0, 0 | 0 of 1835008 (0.0000) | stable (28 maps) | `65e85020f81558fc` |
| `tier0/semantics/resample-uv-rotation` | 16-bit code value | 20 | 0, 0, 0 | 0 of 1310720 (0.0000) | 0, 0, 0 | 0 of 1310720 (0.0000) | stable (20 maps) | `8a7ee1e00f74e074` |

## Maps with a difference

None: every compared map equals its recording.

## Tests not passed (first pass)

None.

## Repeatability differences

None.

## Current-envelope semantic goldens no child test compares

Recorded goldens of `tier0/semantics` and `tier0/semantics-ui` outside the union (not yet owned by a comparison, or outside the compositor):

- `tier0/semantics/ao-mixed-isolation-8bit`
- `tier0/semantics/ao-mixed-isolation-float`
- `tier0/semantics/ao-mixed-isolation`
- `tier0/semantics/ao-mixed-opacity-float`
- `tier0/semantics/ao-mixed-opacity`
- `tier0/semantics/ao-mixed`
- `tier0/semantics/export-alpha-layouts`
- `tier0/semantics/export-bit-depth`
- `tier0/semantics/export-dither`
- `tier0/semantics/export-ocio-encode-legacy`
- `tier0/semantics/export-padding-bevelled-cube`
- `tier0/semantics/export-padding-seam-1024`
- `tier0/semantics/export-padding-seam-256`
- `tier0/semantics/export-padding-seam-field-1024`
- `tier0/semantics/export-padding-seam-field-256`
- `tier0/semantics/export-padding-sphere`
- `tier0/semantics/export-padding`
- `tier0/semantics/export-probes-aliases-coat`
- `tier0/semantics/export-probes-aliases-fuzz`
- `tier0/semantics/export-probes-aliases-subsurface`
- `tier0/semantics/export-probes-channels`
- `tier0/semantics/export-probes-config`
- `tier0/semantics/export-probes-naming`
- `tier0/semantics/export-probes-r091-alpha`
- `tier0/semantics/export-probes-r091-dotted`
- `tier0/semantics/export-probes-r091-keys`
- `tier0/semantics/export-probes-r091-mixes`
- `tier0/semantics/export-probes-r091-naming`
- `tier0/semantics/export-resize`
- `tier0/semantics/view-2d-state-camera`
- `tier0/semantics/view-2d-state-default-repeat`
- `tier0/semantics/view-2d-state-default`
- `tier0/semantics/view-2d-state-environment`
- `tier0/semantics/view-2d-state-tone-aces`
- `tier0/semantics/view-2d-state-tone-linear`
- `tier0/semantics/virtual-maps-converted-float`
- `tier0/semantics/virtual-maps-converted`
- `tier0/semantics/virtual-maps-coverage-float`
- `tier0/semantics/virtual-maps-coverage`
- `tier0/semantics/virtual-maps-template-openpbr-coat-float`
- `tier0/semantics/virtual-maps-template-openpbr-coat`
- `tier0/semantics/virtual-maps-template-pbr-metallic-roughness-alpha-blend-float`
- `tier0/semantics/virtual-maps-template-pbr-metallic-roughness-alpha-blend`
- `tier0/semantics/virtual-maps-template-pbr-specular-glossiness-float`
- `tier0/semantics/virtual-maps-template-pbr-specular-glossiness`
- `tier0/semantics-ui/export-probes-r091-renamed`

Owners of the goldens above: every one is an export recording (`export-plan-compiler.md` §4 and the export recording plan: requests R-085, R-086, R-090, R-091 and R-092, decisions 087, 093 and 100; the `export-*` probes, the virtual maps `virtual-maps-*`, `ao-mixed*` and `view-2d-state-*`), not a compositor channel-map golden. Their comparisons belong to the export tests (`tests/export`, `tests/parity/test_tier0_semantics_ui.py`) and to their owners `phase1.15_export-plan-compiler` and `phase1.18_export-engine`, with the export gaps of decision 103 assigned to `phase1.25_pilot-wand` and `phase3.2_unreal-ue56-packed-preset`. The readbacks of `export-ocio-encode-legacy` belong to the facade (`tests/python/test_pyapi_facade_tier0.py`), and its colour gaps belong to `phase1.15_compositor-colour-fits` (decision 130). The 17 compositor goldens that the interim run listed here (the `height-normal-*`, `height-signed-addition`, `normal-channel-import*` and `resample-uv-*` sets) are now compared in the union.
