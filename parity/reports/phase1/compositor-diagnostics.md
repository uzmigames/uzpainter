# `phase1.13_compositor-diagnostics`: acceptance run on the owner's machine

Child of `phase1.14_compositor-core` (P1-COMPOSITOR; `docs/architecture/04-layer-stack-and-compositing.md` §8; LAY-09, LAY-14, EXP-04, DIA-01). Under decision 028 the GPU checks run locally on the owner's machine, and this report is their evidence. Run on 2026-10-11 on the branch `wt/phase1.13-diagnostics` merged with main `d4c9cfc` (profile `painter-12.1-isolated-coverage-weights`). Decisions 075 and 076.

**Result.** Every diagnostic is an export of the general evaluator and is green on the CPU and on DX12:

- isolation leaves the document exactly as it was, also when the evaluation fails midway;
- contribution equals full minus isolated, texel for texel;
- material views report exactly the injected leaks;
- region statistics equal an independent Python computation, double for double;
- every source name round-trips;
- every output is byte-identical across runs and between the GPU and the CPU.

No Painter recording is needed. An isolated map is an ordinary evaluation of another stack, under the parity the evaluator already has (decision 075).

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200 |
| Backend | DX12 (the evaluator's generated kernels through the render layer's kernel cache) and the CPU store |
| Build | Zig 0.15.2, Debug; `zig build` and `zig build evaluator-tests` exit 0, no warning (`-Wall -Wextra -Werror -ffp-contract=off`) |
| Profile | `painter-12.1-isolated-coverage-weights` (current); the diagnostics add no profile meaning |

## 1. What the diagnostics are (decisions 075, 076)

- **`isolate(node)`** hides a layer, group, instance or effect in a private copy of the revision and evaluates the copy through `EvaluateOn` or `EvaluateVirtualNormalOn`. Nothing is committed: the document, its revision, operation records and save state never change. The restore is therefore atomic by construction, including on a failure at any tile. The tiles below the hidden node are served from the cache.
- **`contribution(node)`** is the full map minus the isolated map: one float32 subtraction per sample of the decoded values, signed and never clamped. It works on any channel and on `Normal_OpenGL` / `Normal_DirectX`.
- **`material_views(material)`** takes a fill layer or group.
  - Its region is the effective mask: the float32 product of its own mask and each enclosing group's mask, from the material outward, evaluated by the engine's mask chain. A texel is inside where that product is at least 1/2.
  - **ID view:** the bound ID mesh map inside the region. A leak is a texel whose code triple is not the modal one.
  - **BaseColor, Height, Normal, Roughness (`SpecularRoughness`) and Metallic (`BaseMetalness`) views:** the full evaluation inside the region. A leak is a texel whose full value differs bitwise from the material's solo evaluation.
  - Views the set or stack cannot give are listed as missing.
- **`region_stats(map, mask)`** gives:
  - the texel count, the thresholded coverage and the weighted coverage;
  - per component: min, max, mean (correctly rounded sum / n) and p10/p50/p90 (linear rule);
  - for three-component maps, the luminance ((r + g) + b) / 3 and the HSV saturation.
- **Export-plan sources.** `srcMapType` `diagnosticMap`, with `srcMapName` one of `isolated/<map>/<uid>`, `contribution/<map>/<uid>`, `materialMask/<uid>`, `materialView/<view>/<uid>`, `materialLeaks/<view>/<uid>` or `regionStats/<map>/<uid>`. Statistics are canonical JSON.

## 2. Checks

`uzp-evaluator-tests diagnostics` (CPU), 18 checks, all passed:

- **3.1** Six cases on a 2048 × 128 set (two tiles), on the CPU: isolate a bitmap layer, a group, a content effect, a mask effect and an invisible layer, plus a contribution of the top layer. In each case, a resource provider fails the first bitmap fetch of tile 1 after every fetch of tile 0 succeeded. The call fails with `missing_resource` after exactly half the fetches plus one. The document's revision object, deep equality, operation records, needs-saving flag and the node's visibility are unchanged. They are also unchanged after a successful run. A node outside the stack fails with `not_found`.
- **3.2** Contribution equals the general evaluator's full map minus its map with the node hidden by the test's own walk, texel for texel: 1 572 864 values over sRGB8, L16, L8, L16F, RGB32F and RGB16 for eight nodes (layers, a group, a child, content and mask effects, an invisible layer). An invisible node contributes exactly 0. Isolating the top layer is served from cached tiles. On both virtual normal maps, the contribution of a LinearDodge Height layer equals the virtual map minus the map without it.
- **3.3** On the two-material fixture (128 × 128, an 8-bit ID mesh map, B under A with complementary masks, a one-texel Roughness touch-up of A inside B's region), `material_views(B)` gives:
  - the ID view with modal blue and no leak;
  - each channel view equal to the full evaluation inside the mask and 0 outside;
  - exactly one leak, the injected texel (80, 20) on Roughness, with its full value (0.8) and its solo value (0.2).

  Further cases:
  - A mask spilling onto A's ID island at (63, 40) is an ID leak (red against modal blue) and a leak of every channel view.
  - Nested in a group whose mask is the top half, B's region is the float32 product of the two masks: a texel at code 45000 in both masks (0.687 each) is outside.
  - A missing ID map and absent channels are listed as missing.
  - An instance material fails with `unsupported_node`, an unknown one with `not_found`, and an ID map off the set resolution with `unsupported_source`.
- **3.4** Region statistics on three fixtures (colour, grey, an empty region; masks at 0, 0.25, 0.4999, 0.5, 0.75 and 1) are recomputed by `tests/evaluator/test_compositor_diagnostics.py` with `math.fsum` and the linear rule in Python floats, and are equal double for double. Region statistics refuse a mask of another shape and a non-finite value inside. The `regionStats` source equals region statistics over the evaluated map and the material's mask.
- **2.5** 25 source names (every kind; channels and both virtual normal maps) round-trip. 14 malformed names fail with `not_found`. Every named source equals its direct diagnostic.
- **3.5** 51 outputs are byte-identical across two fresh CPU evaluators and on a warm cache.

`uzp-evaluator-tests diagnostics-gpu-vs-cpu` (DX12), 2 checks, both passed:

- 129 outputs on the GPU equal the CPU reference bit for bit and repeat byte for byte across two GPU runs: isolate and contribution of eight nodes on six channel formats, material masks, views, leaks, region statistics, and isolate/contribution of the materials and the touch-up. `EvaluateMaterialViews` gives the same bytes and leak lists.
- A GPU contribution failing midway (tile 1 of 2) leaves the document as it was.

Regression: the other native cases (`arith`, `templates`, `order`, `cache`, `admission`, `profile`, `sources`, `masks`, `height-normal`; `gpu-vs-cpu`, `masks-gpu-vs-cpu`, `height-normal-gpu-vs-cpu`) all pass, and `python -m pytest tests/evaluator` (Tier 0 goldens against the private store included) gives 308 passed in 29 min.

## 3. Open items

- **1.1 (prerequisites).** `phase1.12_compositor-height-normal` is merged on main (decisions 064, 065, 077), but its task stays open on recordings that are still to be made: a bound mesh normal map, SignedAddition on Height, and resolutions other than 256. The diagnostics use only its merged code and inherit its refusals: the virtual normal maps at other resolutions and with a mesh normal map fail with `unsupported_source`. The item stays unchecked until phase1.12 is accepted, so this task is not archived.

## Commands

```
zig build evaluator-tests --prefix <dir>
<dir>/bin/uzp-evaluator-tests diagnostics assets/templates <work-dir>
<dir>/bin/uzp-evaluator-tests diagnostics-gpu-vs-cpu assets/templates <work-dir>
python -m pytest tests/evaluator/test_compositor_diagnostics.py
```
