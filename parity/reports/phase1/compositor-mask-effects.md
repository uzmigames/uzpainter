# `phase1.11_compositor-mask-effects`: acceptance run on the owner's machine

Child of `phase1.14_compositor-core` (P1-COMPOSITOR; `docs/architecture/04-layer-stack-and-compositing.md` §1 and §2 steps 2, 4, 5). Under decision 028 the Tier 0 comparisons against the private oracle store and the GPU checks run locally on the owner's machine, and this report is their evidence. Numbers only; every recorded Painter output stays in the private store. Run on 2026-10-11 on the tree of commit `a0e04c2` with this task's working-tree changes, and re-run on 2026-10-11 on `90ce14c` with the same changes (same results; the published fit re-derives byte for byte) (`src/evaluator/`, `tests/evaluator/`, `build.zig`, `parity/semantics/masks-levels.json`).

**Result.** Masks, mask effects, mask precision, levels and the levels clamp are exact against both recordings on the CPU and on the GPU: `mask-precision` (20 maps on RGB16, L16, RGB32F, sRGB8, L8), `levels-clamp` (16 maps on RGB32F, RGB16F, RGB16, L16F) and `effect-order` s6 (levels alone, RGB16 and sRGB8). Group masks are exact wherever the masked child is fully covered or absent; where the child's mask lies strictly between 0 and 1, the source-over onto a partly covered backdrop inside the group keeps a residual (an open item of `phase1.10_compositor-float32-residual`, below). The content-effect order of fill and levels effects and `Mesh` geometry masks are implemented, unit-tested and release gaps: no golden records them without the Blur filter or a geometry mask. No exception is proposed.

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200 |
| Backend | DX12; kernels `cs_6_6 -Gis` through the render layer's kernel cache |
| Build | Zig 0.15.2, Debug; `zig build painter` and `zig build evaluator-tests` exit 0, no warning (`-Wall -Wextra -Werror -ffp-contract=off`) |
| Oracle | the current envelope `painter-12.1.5+js-api.1.1.20` (decision 037), manifests under `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/` resolved through `tools.parity.envelope.registry`; store `C:\Users\Bolado\AppData\Local\UzPainter\parity-store`. Its drift report lists `mask-precision`, `group-masks`, `levels-clamp` and `effect-order` as unchanged from 12.1.0 and `api-probes/mask-stack` as changed in readbacks only (maps equal) |
| Profile | `painter-12.1-isolated-linear` (unchanged; no meaning of it moved) |

## What the goldens settled (04 §9)

- **Mask precision: 16 bits.** The mask is stored with the 16-bit UNORM write rule after every effect, on every channel format. With an 8-bit mask, 4 095–9 225 L8 values of `mask-precision` differ; with an unquantised mask, s2 differs on 31 065 RGB16 values.
- **The effect mix.** A mask effect blends as `v = a + (r − a)·α` for every mode (`r` the mode's kernel, clamped to [0, 1]). The layer mix `a(1 − α) + r·α` leaves 6 of 65 536 texels of s3 (two effects, the second Multiply) off by one code on every format. Content fill effects use the same mix (not separately observable, below).
- **Levels.** `t = (v − in_min)·Rcp(in_max − in_min)` with the recording GPU's reciprocal; `clamp` limits t to [0, 1] before gamma, and the output range is never clamped (values beyond [0, 1] reach the float channels); a gamma other than 1 gives `sign(t)·pow(|t|, gamma)`; `out = fma(t, out_max − out_min, out_min)` (the plain `out_min + t·range` leaves 20 values of `effect-order` s6 off). A gamma of exactly 1 skips the power (with the power, s0 differs on 56 295 RGB32F values).
- **The GPU's pow.** Painter's pow is the GPU's `exp2(g·log2 x)` (equal on 2^20 hashed inputs), whose log2 and exp2 are approximations: with a correctly rounded pow, `effect-order` s6 keeps 62 RGB16 values and `levels-clamp` s2 18 003 RGB32F values off. `uzp-evaluator-tests pow-hardware` measured both on every mantissa of four reduced domains; the rest of the domain follows by rule (`hwmath.h`: log2 is `e + lg2-hi[m]`, `lg2-lo[m]` or `(e + 1) + lg2-lo[m]` rounded toward zero; exp2 truncates the fraction of |y| to 23 bits and scales a table value, flushing below 2^-126). The four tables (`src/evaluator/tables/hw-lg2-hi.zlib` 275 544 bytes, `hw-lg2-lo.zlib` 285 848, `hw-ex2-pos.zlib` 196 765, `hw-ex2-neg.zlib` 197 953; second differences of the measured bit patterns) equal the GPU on all 4 × 8 388 608 entries, and `hw::Log2`, `hw::Exp2` and `hw::Pow` equal it on 40 edge values (zeros, subnormals, infinities, NaN, exponent limits) and 2^20 hashed inputs each.
- **Levels in masks** take no blending (the API refuses it, `api-probes/mask-stack`) and remap the mask in place.
- **Group masks.** A group's mask scales its isolated composite as a layer's does; `group-masks` s2 (default mode) and s3 (`Normal`) agree texel for texel, as s0 and s1 do.

## Tier 0 comparisons (CPU and GPU identical)

| Golden | Maps | r1 | r2 |
|---|---|---|---|
| `mask-precision` s0–s3 | 20 (RGB16, L16, RGB32F, sRGB8, L8) | exact | exact |
| `levels-clamp` s0–s3 | 16 (RGB32F, RGB16F, RGB16, L16F) | exact | exact |
| `effect-order` s6 | 2 (RGB16, sRGB8) | exact | exact |
| `group-masks` s2, s3 | 6 (RGB16, sRGB8, RGB32F) | 57 RGB16, 3 709 sRGB8, 21 469 RGB32F values of 196 608 differ per map, max one step | same |
| `api-probes/mask-stack` | BaseColor | not comparable (below); residual published | same |

`parity/semantics/masks-levels.json` publishes every residual (entries `mask-precision`, `mask-stack-effect-mix`, `levels`, `levels-clamp`: exact; `group-masks`, `mask-stack-probe`: calibrated; `content-effect-order`, `geometry-mask-mesh`: gap). `python tests/evaluator/masks_fits.py <exe> <work>` re-derives it and `test_published_fit_reproduces` requires the file to match.

## Open items

1. **Partly covered source-over (`group-masks` s2–s3).** The residual lies only where the Multiply child's mask (the ramp y/255) is strictly between 0 and 1: the uniform Screen fill above it composites over a partly covered backdrop inside the group. Every texel where that mask is 1, and where it is 0 on the 16-bit and 8-bit maps, is exact; so are the group's own mask and opacity. Every sRGB8 difference (1 862 down, 1 847 up, one code) lies on an even row y ≥ 32, exactly the rows where the group's stored coverage (255 + y)/510 is an 8-bit tie; odd rows are exact. The RGB16 differences (35 down, 22 up) and the RGB32F ones (1–128 ULP) lie on both parities. Over a hundred float32 orderings of the W3C §5.1 straight and premultiplied source-over (with the correctly rounded, hardware and divided reciprocal) were tried, and then these coverage and storage variants, as differing RGB16 / sRGB8 / RGB32F values of s2 against the baseline 57 / 3 709 / 21 469: coverage stored as float32 5 812 / 4 000 / 21 469, as UNORM16 57 / 3 999 / 104 052, as half nearest 114 027 / 4 261 / 193 261, as half toward zero 136 808 / 4 887 / 193 866; 8-bit coverage ties up 211 / 3 860 / 21 469, ties to even – / 3 779 / –, `floor(x·255 + 0.5)` – / 4 316 / –; colour divided by the stored coverage 9 965 / 9 309 / 21 469 (hardware reciprocal 19 521, true division 25 870 on RGB32F); colour stored premultiplied by the stored coverage 25 999 / 25 835 / 23 320. None is exact or better than the baseline. This is the operation order `phase1.10_compositor-float32-residual` owns, and it also shows on RGB16 and sRGB8 here, not only on 32-bit floats, so it may matter for masked stacks of the pilots (the coordinator should weigh making that task a prerequisite of G1).
2. **The 32-bit float operand of a uniform colour.** On the RGB32F row of `group-masks` where the child's mask is 0, the uniform fill's float32 value `float32(v)` reproduces both recordings, and the read-out operand `1 + (v − 1)` of `blend-modes.json` (`uniform_operand`) does not (8 values). With `float32(v)`, one more of the six open `quantisation-thirds` values becomes exact (s0 User4 G). Changing it changes the meaning of `painter-12.1-isolated-linear` (decision 017 pinning), so it is left to that task's new profile.
3. **`api-probes/mask-stack`.** Its masked half exports above both the 0.9 fill and the template base, and its values lie off the sRGB8 export lattice of the semantics goldens: the colour path of a Working colour on that project's BaseColor channel is not the evaluator's linear colour (a sources question, not a mask one). The mask stack it records converts and evaluates; the residual is published, not counted.
4. **Content-effect order and the content fill effect's mix.** Every `effect-order` set but s6 (levels alone) and s7 (Blur alone) holds the starter-asset Blur filter (P3-PROC), and Blur is not the identity on the fields' interiors, so the order of fill and levels effects is implemented from the documented list order and unit-tested, not yet observed.
5. **Geometry masks** (`Mesh`): no golden; `UVTile` fails explicitly.
6. **Complementary masks (LAY-10).** No Tier 0 golden records two fills under complementary masks. The `masks` case checks that such a stack equals the isolated-root model over the template's base value (whose empty-project exports, the `base-values-*` goldens, stay exact) and differs from the same model over a zero base: the uncovered part is exactly the defined base, never a default.

## Design note: the DAG shape

Settled before mask effects depend on it (planning review). Content and mask effect chains are graph nodes keyed by chained subtree hashes (`CacheKind::Effect`, `CacheKind::Mask`); a layer's contribution hash covers its final content hash and its mask hash; a mask's hashes do not depend on the channel, so one mask raster serves every channel of a layer. `uzp-evaluator-tests masks` checks that an upstream change (a mask effect, then a content effect, as an anchor's change would be) re-evaluates only its chain from the change up and the prefixes above the layer, serves the lower effects, the other chain and the prefixes below from the cache, and gives the same bytes as a fresh evaluation.

## Commands

```
zig build painter
zig build evaluator-tests --prefix <dir>
<dir>/bin/uzp-evaluator-tests masks assets/templates
<dir>/bin/uzp-evaluator-tests masks-gpu-vs-cpu assets/templates <work>
<dir>/bin/uzp-evaluator-tests pow-hardware assets/templates <work>
python tests/evaluator/masks_fits.py <dir>/bin/uzp-evaluator-tests.exe <work>
python -m pytest tests/evaluator
```
