# P1-CORE child `phase1.3_core-uv-raster` — owner's machine run

Task `phase1.3_core-uv-raster`, child of `phase1.4_render-core-layer` (P1-CORE, `docs/dag.md`; `docs/architecture/12-mesh-import.md` §5, §6, `13-engine-integration.md` §4.1). Decision 028: GPU checks run locally on the owner's machine and this report is their evidence for the parent's acceptance (P1-CORE gate item, raster part: unit tests on synthetic meshes green on DX12). Run on 2026-10-10 on the tree of commit `c0e658c` with the working-tree changes of the Phase 1 tasks in progress and this task.

**Result: all UV raster tests green on the DX12 hardware adapter.** The Tier 0 comparison of island-edge behaviour against Painter is owned by `phase1.8_compositor-sources-projection`, not by this task.

## Machine and build

| Item | Value |
|---|---|
| Machine | Windows 11 (build 10.0.26200), NVIDIA GeForce RTX 4090, the adapter of `core-device-kernels.md` |
| Build | `zig build render-tests` and `zig build painter` (Zig 0.15.2, Debug), `-Wall -Wextra -Werror` on `src/render/` and `tests/render/`, exit code 0 |
| Kernel | `src/render/shaders/uv_raster.hlsl`, embedded with `#embed`, compiled `cs_6_6 -Gis` (IEEE-strict) through the kernel cache; three entry points (`ClearMain`, `CoverMain`, `ResolveMain`), resources bound through SM 6.6 `ResourceDescriptorHeap` |

## Tests (`python -m pytest tests/render/test_core_uv_raster.py`, `uzp-render-tests.exe uv-raster-*`)

The reference is computed on the CPU in double precision: a texel counts as robustly touched or covered when the result holds with a margin of 10⁻³ texel, and the GPU mask must contain every robustly touched texel and nothing outside the loosely touched ones (the same margin outwards); texel-centre coverage likewise.

| Task item | Case | Evidence of this run | Verdict |
|---|---|---|---|
| 2.1 explicit strides | `uv-raster-validate`, `uv-raster-plane` | strides below the attribute size (0 included), offsets not multiples of 4, attributes past their buffer, unknown buffer indices, corner ids out of range, size 0 and tile 1002 are rejected with `request_failed`; the plane rasterised from one interleaved buffer (stride 64, attributes in shuffled order after a 12-byte header) and from five separate streams gave byte-identical buffers | met |
| 3.1 plane | `uv-raster-plane` | a unit plane (5 x 5 quads, shared corners) on the 0-1 square at 256 x 256: all 65 536 texel centres covered, the conservative mask full, positions equal to the analytic value `(u − ½, 0, ½ − v)` at every centre (max \|Δ\| below 5 · 10⁻⁷, bound 10⁻⁶), normal, tangent with sign and bitangent equal to the analytic frame, island and material ids those of the plane | met |
| 2.3 thin triangle (spec scenario) | `uv-raster-thin` | a sliver 0.08 texel wide at its widest: 341 conservative texels, every one of the 341 robustly touched texels marked and none beyond, 7 texel centres (the reference's 7); a triangle inside one texel marks that texel with an empty centre | met |
| 3.2 sphere, bevelled cube | `uv-raster-coverage` | sphere (24 x 12, UVs in 0.05–0.95) and bevelled cube (26 islands, each rotated in its cell), at 512 x 512 and 300 x 200: the mask covers every touched texel, marks no untouched texel and contains the texel-centre coverage; centre coverage equals the reference (sphere 512²: 194 310 centre, 197 116 conservative texels; bevelled cube 512²: 40 666 centre, 43 562 conservative texels) | met |
| 3.3 ids | `uv-raster-ids` | two islands (4 590 and 3 420 unambiguous texels at 128 x 128), the first split between materials 5 and 2: material and island id correct on all 16 384 unambiguous texels; a texture-set filter on material 5 rasterised only that triangle, keeping its original index | met |
| 3.4 repeatability | `uv-raster-repeat` | the bevelled cube at 1024 x 1024 rasterised twice in one process and once each in two processes with separate kernel caches (one compiling, one reading back from its cache): all eight buffers byte-identical (XXH64 of each buffer equal across processes) | met |
| 2.4 tile index | `uv-raster-plane` | every result carries `uvTile = 1001`; other tiles are rejected until the UV-tile workflow (Phase 4) | met |

`uv-raster-validate` also runs under `UZP_NO_GPU=1` (hosted CI); the GPU cases skip there with the decision-028 reason.

## Decision taken in this task

The spec asks for a conservative mask "by supersampling" and, in its thin-triangle scenario, for a mask that holds every texel a triangle touches. A finite sample grid cannot guarantee the second for triangles narrower than its sample spacing, so the mask is evaluated exactly (separating-axis test of the triangle against the texel square, positive-area overlap), which is the limit of supersampling at any density and contains every finite supersampled mask.

## Reproduce

```
zig build render-tests
python -m pytest tests/render/test_core_uv_raster.py
zig-out\bin\uzp-render-tests.exe uv-raster-coverage <work-dir>
```
