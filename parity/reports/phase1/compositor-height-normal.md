# `phase1.12_compositor-height-normal`: acceptance run on the owner's machine

Child of `phase1.14_compositor-core` (P1-COMPOSITOR; `docs/architecture/04-layer-stack-and-compositing.md` §6). Under decision 028 the Tier 0 comparisons against the private oracle store and the GPU checks run locally on the owner's machine, and this report is their evidence. Numbers only; every recorded Painter output stays in the private store. Run on 2026-10-11 on the branch `wt/phase1.12-height-normal` merged with main `7be83f4` (profile `painter-12.1-isolated-coverage-weights`). Decisions 064 and 065.

**Result.** Both height-to-normal methods of Painter 12.1.5 are exact: every r1 map of `Normal_OpenGL`, `Normal_DirectX` and the Height export over the amplitude sweep (opacity 1, 0.75, 0.5, 0.25, 0.1; 2, 3, 4 copies in LinearDodge), the sphere and the bevelled cube, for `Sharp` and `Smooth (Sobel)`, and the older default-method goldens; every map of `blend-normal-channel` (the Normal channel in the virtual map). CPU and GPU are identical bit for bit. Open: SignedAddition on Height (3.1) and the mesh normal map in the combination (3.3) have no recording; §5 specifies them.

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200 |
| Backend | DX12; kernels `cs_6_6 -Gis` through the render layer's kernel cache (Painter renders through Vulkan, decision 056; the kernels use the measured tables, not this GPU's instructions) |
| Build | Zig 0.15.2, Debug; `zig build evaluator-tests` exit 0, no warning (`-Wall -Wextra -Werror -ffp-contract=off`) |
| Oracle | the current envelope `painter-12.1.5+js-api.1.1.20` (decision 037); store `%LOCALAPPDATA%\UzPainter\parity-store` |
| Profile | `painter-12.1-isolated-coverage-weights` (current); the virtual maps add no profile meaning |

## 1. What the goldens settled (04 §9: height→normal methods and strength scaling)

- **The input is the Height read-out before its write rule.** At opacity 0.75 and 0.1 the read-out `q × half(opacity)` is off the half grid; the stencils read that float32 value (54 248 values of s1 differ when they read the stored half). LinearDodge copies read the per-layer-quantised accumulator, the stack's own rule.
- **Sharp:** `v = (h(-1,0) − h(0,0), h(0,0) − h(0,−1), 0.390625)` (backward one-texel differences, rows top first, wrap-around at the borders). **Smooth (Sobel):** `v = (L − R, B − T, 3.125)` with (1, 2, 1)-weighted columns and rows. No strength setting exists (decision 047); the gradient is linear in the height amplitude, with no other scale.
- **The combination:** `H = normalise(v)`, reoriented (Barré-Brisebois and Hill 2012) onto the flat base, normalised, then the Normal channel reoriented onto that, normalised (the recording GPU's rsqrt); `fma(n, ½, ½)`; DirectX negates `n.y` first. The two reorientations made the last texels exact: one normalisation alone leaves 657 values off over the Sharp sweep, `(−k dx, k dy, 1)` with k = 2.56 600+, the Normal channel as the first base 180-192 per `blend-normal-channel` set.
- **The empty Normal channel** exports float32(127/255) yet acts as exactly flat: the channel is composited over (0.5, 0.5, 1) for the virtual maps.
- **Explicit Sharp equals the default** (decision 047): the older `height-normal-*` goldens are reproduced by the same model.

## 2. Tier 0 comparisons (CPU and GPU identical)

| Golden | Maps compared | r1 | r2 |
|---|---|---|---|
| `semantics-ui/height-normal-sharp-plane-strength` s0–s7 | Normal_OpenGL, Normal_DirectX, Height | exact | exact on s0, s2, s3, s5–s7; s1, s4 differ from r1 (§3) |
| `semantics-ui/height-normal-sobel-plane-strength` s0–s7 | same | exact | same |
| `semantics-ui/height-normal-{sharp,sobel}-{sphere,bevelled-cube}` | same, eroded UV coverage (58 816, 51 040 texels) | exact | exact |
| `semantics/height-normal-plane-amplitudes` s0–s3, `-sphere`, `-bevelled-cube` | same | exact | exact |
| `semantics/blend-normal-channel` s0–s3 | Normal_OpenGL | exact | exact |

`parity/semantics/height-to-normal.json`: entries `height-normal-sharp`, `height-normal-sobel`, `height-normal-normal-channel`, `height-normal-height-readout`, `height-normal-default-normal-channel-base` exact; `height-normal-save-reopen-divergence` calibrated (r2 only); four gaps. `python -m tools.parity.fit check --fit normal` reproduces it.

## 3. Save-and-reopen divergence (decision 032, EXC-003)

r2 of plane-strength s1 (opacity 0.75) and s4 (0.1) differs from r1 for both methods: Sharp s1 Normal_OpenGL 42 242 of 196 608 values (max 31 codes), s4 22 350 (max 10); Sobel s1 53 371 (16), s4 24 753 (6); the Height export s1 30 640 values (2^-11), s4 every value (2^-14). The opacity read back after the reopen equals r1's. Neither the reopened Height export as the stencil input (40 112 values off on s1) nor one opacity for every texel (27 064) explains r2. r1 is the exact target; EXC-003 (`parity/exceptions.json`, domain `tier0/height-normal/method`) bounds the r2 comparisons by the published residuals.

## 4. Unit and GPU checks

- `uzp-evaluator-tests height-normal` (CPU): stencils, the flat case in both methods and conventions, DirectX mirroring y, the float32 read-out (32 706 of 65 536 values off the half grid at opacity 0.75, each stored as its half toward zero), the EXP-09 tags (the relief round follows the Height content and the method, not BaseColor), the Normal-channel import `(r, 65535 − g, b)`, the geometry-only pass-through (8 and 16 bits, both conventions), and the explicit failures.
- `uzp-evaluator-tests height-normal-gpu-vs-cpu` (GPU): the kernel over a 3 × 3 grid of 72-texel tiles with halo reads across every tile edge and the set border, both methods and conventions, with Normal tiles and constants (1 119 744 values); the raw read-out on all nine channel formats (77 824 values); whole evaluations through `Evaluator` and `CpuEvaluator`: bit for bit.

## 5. Recording requests (open items 3.1, 3.3; decisions 064, 065)

All through the recorder, under the Assets3D Painter lock, Legacy colour management, 16-bit PNG and 32f EXR exports with infinite padding, r1 and r2 (save and reopen). Inputs are the authored fixtures of `parity/fixtures/tier0-semantics/` (`height-ramps`, `normal-a`, `normal-b`, `grey-a`, `mask-codes`). Sobel sets need the UI operator (`--operator ui`, decision 047).

1. **(i) Mesh normal map.** `tier0/semantics/height-normal-mesh-map`: grid4x2, 256 px, OpenGL project. Bind `normal-b` as the Normal mesh map of every set through `textureset.TextureSet.set_mesh_map_resource(MeshMapUsage.Normal, …)`. s0 mesh map only; s1 mesh map + Height ramps fill; s2 mesh map + Normal fill `normal-a`; s3 mesh map + Height + Normal; s4–s7 the same with the method `Smooth (Sobel)` (UI). Export `virtualMap/Normal_OpenGL`, `virtualMap/Normal_DirectX`, `meshMap/normal_base` (PNG16) and `documentMap/height`, `documentMap/normal` (EXR 32f). A second golden `height-normal-mesh-map-directx` repeats s0–s3 in a DirectX project.
2. **(ii) SignedAddition on Height.** `tier0/semantics/height-signed-addition`: grid4x2, 256 px. s0 Height ramps fill in Normal, then a `grey-a` fill on Height in SignedAddition at opacity 1; s1 the same at 0.5; s2 a uniform 0.25 fill in SignedAddition over the ramps; s3 SignedAddition onto the empty Height. Export Height (EXR 32f, PNG16) and both virtual maps.
3. **(iii) Normal-channel coverage.** `tier0/semantics/height-normal-channel-coverage`: grid4x2, 256 px, Height ramps fill in every set. s0 `normal-a` on Normal at opacity 0.5; s1 at 0.25; s2 at opacity 1 with a black mask and a `mask-codes` bitmap fill effect in the mask; s3 a uniform Normal colour (0.6, 0.4, 1) at opacity 0.5. Export Normal (EXR 32f) and both virtual maps.
4. **(iv) Normal imports.** `tier0/semantics/normal-channel-import`: s0–s1 `normal-a` (16 bit) and an 8-bit copy on the Normal channel of an OpenGL project; s2–s3 the same in a DirectX project, each with the Height ramps. Export Normal (EXR 32f) and both virtual maps.
5. **(v) Resolution.** `tier0/semantics/height-normal-resolutions`: `height-normal-plane-amplitudes` at 512, 1024 and 2048 px (Sharp, documented API only), and s0 at 1024 px with `Smooth (Sobel)` (UI). Settles whether z is fixed per texel or a UV-space gradient (z = 100 / width); the evaluator refuses every set other than 256 until then.

## Commands

```
zig build evaluator-tests --prefix <dir>
<dir>/bin/uzp-evaluator-tests height-normal assets/templates
<dir>/bin/uzp-evaluator-tests height-normal-gpu-vs-cpu assets/templates <work>
python -m pytest tests/evaluator/test_compositor_height_normal.py tests/parity/fit/test_normal.py
python -m tools.parity.fit check --fit normal
```
