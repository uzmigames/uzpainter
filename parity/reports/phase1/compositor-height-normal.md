# `phase1.12_compositor-height-normal`: acceptance run on the owner's machine

Child of `phase1.14_compositor-core` (P1-COMPOSITOR; `docs/architecture/04-layer-stack-and-compositing.md` §6). Under decision 028 the Tier 0 comparisons against the private oracle store and the GPU checks run locally on the owner's machine, and this report is their evidence. Numbers only; every recorded Painter output stays in the private store. First run on 2026-10-11 on the branch `wt/phase1.12-height-normal` merged with main `7be83f4` (decisions 064 and 065); closing run on 2026-10-11 on `wt/phase1.12-close` from main `d4c9cfc` with the recordings of decision 077 (decisions 079 and 080). Profile `painter-12.1-isolated-coverage-weights`.

**Result.** Every recorded golden of the child is exact on every r1 map, on the CPU and on the GPU (DX12), identical bit for bit: both height-to-normal methods over the amplitude sweep, the sphere and the bevelled cube, `blend-normal-channel`, and the ten recordings of decision 077 (the Normal mesh map in OpenGL and DirectX projects, SignedAddition on Height, Normal-channel coverage, 8- and 16-bit Normal imports in both conventions, the sweep at 512, 1024 and 2048 px). r2 is exact wherever it equals r1; four sets differ after save and reopen (decision 032): two are EXC-003's, two are the new EXC-004 and EXC-005 (decision 080, for the owner's review).

## Run record

### Current-envelope fit reproduction (2026-10-23)

`tools.parity.fit.normal.fit(Context(store, repository))` was re-derived against
`painter-12.2.0+js-api.1.1.20-env-a981b586eae7` on the CPU, validated with
`publishable_problems`, then published as `parity/semantics/height-to-normal.json`.
All 14 entries, including formulas, public sources, statuses and residuals, are
identical to the previously published 12.1.5 document. The only changed document
field is the build identity supplied by the fresh fit's current envelope.
This resolves a stale publication, not a compositor change or a new acceptance
exception. Existing nonzero residuals and gaps remain unchanged. No Painter or
GPU ran for this refresh; the earlier GPU evidence below remains historical.

The original `test_published_fit_reproduces` passes after publication (1 passed
in 227.29 seconds, `scripts/tmp/semantic-normal-check.xml`). The two refreshed
fits also pass schema/source/envelope checks, and the publication guard checks
both fits and both run reports against the private-store index with zero blocks.

### Original run

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200 |
| Backend | DX12; kernels `cs_6_6 -Gis` through the render layer's kernel cache (Painter renders through Vulkan, decision 056; the kernels use the measured tables, not this GPU's instructions) |
| Build | Zig 0.15.2, Debug; `zig build evaluator-tests` exit 0, no warning (`-Wall -Wextra -Werror -ffp-contract=off`) |
| Oracle | the current envelope `painter-12.1.5+js-api.1.1.20` (decision 037); store `%LOCALAPPDATA%\UzPainter\parity-store` |
| Profile | `painter-12.1-isolated-coverage-weights` (current); the virtual maps add no profile meaning |

## 1. What the goldens settled (04 §9: height→normal methods and strength scaling)

- **The input is the Height read-out before its write rule.** At opacity 0.75 and 0.1 the read-out `q × half(opacity)` is off the half grid; the stencils read that float32 value (54 248 values of s1 differ when they read the stored half). LinearDodge copies read the per-layer-quantised accumulator, the stack's own rule.
- **Sharp:** `v = (h(-1,0) − h(0,0), h(0,0) − h(0,−1), 100 / W)` (backward one-texel differences, rows top first, wrap-around at the borders). **Smooth (Sobel):** `v = (L − R, B − T, 800 / W)` with (1, 2, 1)-weighted columns and rows. z is a UV-space gradient (0.390625 and 3.125 at 256 px; a fixed z leaves about 428 000 values off at 512 px and 6.7 M at 2048 px). No strength setting exists (decision 047); the gradient is linear in the height amplitude.
- **The combination:** `H = normalise(v)`, reoriented (Barré-Brisebois and Hill 2012) onto F, normalised, then the Normal channel's normal C reoriented onto that, normalised (the recording GPU's rsqrt); `fma(n, ½, ½)`; DirectX negates `n.y` first. F is the bound Normal mesh map decoded from its 16-bit codes (y negated for a DirectX map), else flat. The two reorientations made the last texels exact: one normalisation alone leaves 657 values off over the Sharp sweep, the Normal channel as the first base 180-192 per `blend-normal-channel` set; for the mesh map, reoriented(H, F) leaves about 138 000 values off, F after the channel about 92 000, the codes passed through 3 072.
- **The Normal channel:** its root list from a transparent start, colour X and coverage a, gives C = decode(X) at full coverage, the flat normal where uncovered, and otherwise decode(X rcp(a)) turned toward (0, 0, 1) by a (`(u.x k, u.y k, cos t)`, `t = a acos(z)`, `k = sin(t) rsqrt(1 − z²)`). The arccosine is the GPU's Vulkan `acos`: 2 P(√(½ − ½z)) above 0.57, else π/2 − P(z), P the arcsine polynomial (0 mismatches on 33 554 432 inputs over [−1, 1] through `tools/parity/vk_sampler_probe`); π/2 − asin(z) (the blend modes' rotation) leaves 82 values one code off, IEEE X / a instead of X rcp(a) 78. Reading the channel's read-out instead leaves thousands of values off (up to 8 610 codes).
- **The channel's read-out** composites its layers over (0.5, 0.5, 1) (over 127/255: 131 072 values off), while an empty channel exports 127/255 in both conventions. Imports store (r, max − g, b) / max written half toward zero in OpenGL and DirectX projects (8 and 16 bits); a DirectX project's export of a non-empty channel inverts green again (half toward zero of 1 − g). The virtual maps read the storage: the DirectX export with y negated leaves 41 800 values up to 20 codes off.
- **Magnified Height bitmaps** are filtered as signed values 2t − 1 (filtering t and taking 2v − 1 leaves 16 values at 512 px, 462 at 2048 px one half step off near 0).
- **SignedAddition on Height** is the blend kernel (a + 2b) − 1 on the signed content, exact with no change.
- **Explicit Sharp equals the default** (decision 047): the older `height-normal-*` goldens are reproduced by the same model.

## 2. Tier 0 comparisons (CPU and GPU identical)

| Golden | Maps compared | r1 | r2 |
|---|---|---|---|
| `semantics-ui/height-normal-sharp-plane-strength` s0–s7 | Normal_OpenGL, Normal_DirectX, Height | exact | exact on s0, s2, s3, s5–s7; s1, s4 differ from r1 (§3, EXC-003) |
| `semantics-ui/height-normal-sobel-plane-strength` s0–s7 | same | exact | same |
| `semantics-ui/height-normal-{sharp,sobel}-{sphere,bevelled-cube}` | same, eroded UV coverage (58 816, 51 040 texels) | exact | exact |
| `semantics/height-normal-plane-amplitudes` s0–s3, `-sphere`, `-bevelled-cube` | same | exact | exact |
| `semantics/blend-normal-channel` s0–s3 | Normal_OpenGL | exact | exact |
| `semantics/height-normal-mesh-map` s0–s7 (Sharp, Sobel) and `-directx` s0–s3 | virtual maps, Height, Normal (export), `normal_base` | exact | exact |
| `semantics/height-signed-addition` s0–s7 | virtual maps, Height | exact | exact |
| `semantics/height-normal-channel-coverage` s0–s7 | virtual maps, Height, Normal | exact | exact except s2 (§3, EXC-004) |
| `semantics/normal-channel-import`, `-directx` s0–s3 (8 and 16 bits) | virtual maps, Height, Normal | exact | exact |
| `semantics/height-normal-resolution-512`, `-1024`, `-1024-sobel`, `-2048` s0–s3 | virtual maps, Height | exact | exact except 2048 s2 (§3, EXC-005) |

`parity/semantics/height-to-normal.json`: entries `height-normal-sharp`, `height-normal-sobel`, `height-normal-normal-channel`, `height-normal-height-readout`, `height-normal-default-normal-channel-base`, `height-normal-mesh-normal-map`, `height-normal-channel-coverage`, `height-normal-channel-import`, `height-normal-resolution-scaling`, `height-signed-addition` exact; three save-and-reopen divergences calibrated (r2 only); one gap (`height-normal-unrecorded-inputs`). `python -m tools.parity.fit check --fit normal` reproduces it.

## 3. Save-and-reopen divergences (decision 032)

- **EXC-003** (`tier0/height-normal/method`): r2 of plane-strength s1 (opacity 0.75) and s4 (0.1) differs from r1 for both methods: Sharp s1 Normal_OpenGL 42 242 of 196 608 values (max 31 codes), s4 22 350 (max 10); Sobel s1 53 371 (16), s4 24 753 (6); the Height export s1 30 640 values (2^-11), s4 every value (2^-14). Neither the reopened Height export as the stencil input (40 112 values off on s1) nor one opacity for every texel (27 064) explains r2.
- **EXC-004** (`tier0/height-normal/combination`, decision 080): r2 of `height-normal-channel-coverage` s2 (normal-a at opacity 1 under a Black mask with a mask-codes fill): Normal_OpenGL 142 764 and Normal_DirectX 142 862 of 196 608 values (max 61 codes, mean 4.63), the Normal export 114 266 values (max 2^-10). No coverage variant explains r2's Normal export (round to nearest half 110 508 values off, 8-bit coverage 122 174, the unquantised coverage 110 675).
- **EXC-005** (`tier0/height-normal/resolution`, decision 080): r2 of `height-normal-resolution-2048` s2 (opacity 0.25): 4 and 5 values of the virtual maps, one code. r2 equals the stencils on the **stored** Height (half toward zero; at opacity 0.25 the values near 0 are subnormal halves and truncated) instead of the read-out before the write rule.

Each was recorded again in a freshly started Painter process with the same two results (decision 077): deterministic, not run-to-run noise. r1 is the exact target and the evaluator equals it; the entries bound only the r2 comparisons, by the published residuals.

## 4. Unit and GPU checks

- `uzp-evaluator-tests height-normal` (CPU): stencils, z = 100 / W and 800 / W, the flat case in both methods and conventions, DirectX mirroring y, `hw::Acos` on 48 measured Vulkan inputs, the channel normal at coverage 0, 1 and 1/2, the float32 read-out (32 706 of 65 536 values off the half grid at opacity 0.75, each stored as its half toward zero), the EXP-09 tags (the relief round follows the Height content and the method, not BaseColor), the Normal-channel import `(r, 65535 − g, b)` in both conventions, a Normal layer at opacity 1/2 over (0.5, 0.5, 1), the mesh map as F (a DirectX map mirrors y), a 512 set, the geometry-only pass-through (8 and 16 bits, both conventions), and the explicit failures (a 128 set, a 512 × 256 set, an 8-bit mesh map in the combination, a mesh map in the other convention, a uniform Normal colour or a Normal bitmap at opacity 1/2 in a DirectX project, a pass-through without a mesh map).
- `uzp-evaluator-tests height-normal-gpu-vs-cpu` (GPU): the kernel over a 3 × 3 grid of 72-texel tiles with halo reads across every tile edge and the set border, both methods and conventions, with a constant partly covered channel, RGB32F and RGB16F Normal root lists at every coverage (including 0), mesh maps in both conventions and the z of a 512 set (2 239 488 values); the raw read-out on all nine channel formats (77 824 values); whole evaluations through `Evaluator` and `CpuEvaluator` with a mesh map and a Normal layer at opacity 0.6: bit for bit.
- `tests/evaluator/test_compositor_height_normal.py::test_recorded_inputs_exact` runs every decision-077 golden through the evaluator on the CPU and on the GPU.

## 5. Not recorded (refused with `unsupported_source`, decision 079)

- A DirectX project's Normal channel other than one bitmap fill in Normal mode at opacity 1 without mask or effects (other modes, partial coverage, stacks, uniform colours).
- A Normal mesh map in the combination that is 8-bit, of another size than the set or in the other convention.
- Sets other than square 256, 512, 1024 or 2048 px.

Modelled by the recorded rules but not recorded: Normal root lists of several layers at partial coverage, and the signed bilinear filter of a Height bitmap with non-dyadic weights (rotated or scaled projections). A Vulkan probe of the sampler's linear filter on synthetic positions disagreed with the projection model on 1.5 % of samples even for non-negative texels, so the negative-texel path of the hardware filter is not measured; the recorded magnifications have dyadic weights, where the values do not depend on it.

## Commands

```
zig build evaluator-tests --prefix <dir>
<dir>/bin/uzp-evaluator-tests height-normal assets/templates
<dir>/bin/uzp-evaluator-tests height-normal-gpu-vs-cpu assets/templates <work>
python -m pytest tests/evaluator/test_compositor_height_normal.py tests/parity/fit/test_normal.py tests/parity/test_verdict.py
python -m tools.parity.fit check --fit normal
```
