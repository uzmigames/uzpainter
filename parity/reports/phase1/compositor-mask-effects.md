# `phase1.11_compositor-mask-effects`: acceptance run on the owner's machine

Child of `phase1.14_compositor-core` (P1-COMPOSITOR; `docs/architecture/04-layer-stack-and-compositing.md` §1 and §2 steps 2, 4, 5). Under decision 028 the Tier 0 comparisons against the private oracle store and the GPU checks run locally on the owner's machine, and this report is their evidence. Numbers only; every recorded Painter output stays in the private store. Run on 2026-10-11 on the tree of commit `a0e04c2` with this task's working-tree changes, and re-run on 2026-10-11 on `90ce14c` with the same changes (same results; the published fit re-derives byte for byte) (`src/evaluator/`, `tests/evaluator/`, `build.zig`, `parity/semantics/masks-levels.json`). Re-run on 2026-10-11 on main `4949d28` (after phase1.10's coverage-weights profile, decisions 058, 059; phase1.11 blend gaps, decision 054; the PassThrough first-child backdrop, decision 066) for items 3.3, 3.4 and 4.1 (section Re-run below).

**Result.** Every Tier 0 set this task owns is exact against both recordings on the CPU and on the GPU: `mask-precision` (20 maps on RGB16, L16, RGB32F, sRGB8, L8), `levels-clamp` (16 maps on RGB32F, RGB16F, RGB16, L16F), `effect-order` s6 (levels alone, RGB16 and sRGB8), `group-masks` s2–s3 (a group mask on the group in its default mode and in `Normal`, RGB16, sRGB8, RGB32F) under the current profile `painter-12.1-isolated-coverage-weights` (decisions 058, 059), and the `PassThrough` group with a group mask, a child mask and both (`semantics-ui/group-passthrough-masks` s1–s3, decisions 054, 066). The other `effect-order` sets hold the Blur filter, a P3-PROC release gap: by decision 069 they belong to `phase3.2_proc-filter-families` item 3.4, and the order of fill and levels effects is unit-tested here, not golden-verified. `Mesh` geometry masks are implemented, unit-tested and a release gap (no golden). No exception is proposed.

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200 |
| Backend | DX12; kernels `cs_6_6 -Gis` through the render layer's kernel cache |
| Build | Zig 0.15.2, Debug; `zig build painter` and `zig build evaluator-tests` exit 0, no warning (`-Wall -Wextra -Werror -ffp-contract=off`) |
| Oracle | the current envelope `painter-12.1.5+js-api.1.1.20` (decision 037), manifests under `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/` resolved through `tools.parity.envelope.registry`; store `C:\Users\Bolado\AppData\Local\UzPainter\parity-store`. Its drift report lists `mask-precision`, `group-masks`, `levels-clamp` and `effect-order` as unchanged from 12.1.0 and `api-probes/mask-stack` as changed in readbacks only (maps equal) |
| Profile | `painter-12.1-isolated-linear` on the first runs; `painter-12.1-isolated-coverage-weights` (the current profile, decision 058) on the re-run |

## What the goldens settled (04 §9)

- **Mask precision: 16 bits.** The mask is stored with the 16-bit UNORM write rule after every effect, on every channel format. With an 8-bit mask, 4 095–9 225 L8 values of `mask-precision` differ; with an unquantised mask, s2 differs on 31 065 RGB16 values.
- **The effect mix.** A mask effect blends as `v = a + (r − a)·α` for every mode (`r` the mode's kernel, clamped to [0, 1]). The layer mix `a(1 − α) + r·α` leaves 6 of 65 536 texels of s3 (two effects, the second Multiply) off by one code on every format. Content fill effects use the same mix (not separately observable, below).
- **Levels.** `t = (v − in_min)·Rcp(in_max − in_min)` with the recording GPU's reciprocal; `clamp` limits t to [0, 1] before gamma, and the output range is never clamped (values beyond [0, 1] reach the float channels); a gamma other than 1 gives `sign(t)·pow(|t|, gamma)`; `out = fma(t, out_max − out_min, out_min)` (the plain `out_min + t·range` leaves 20 values of `effect-order` s6 off). A gamma of exactly 1 skips the power (with the power, s0 differs on 56 295 RGB32F values).
- **The GPU's pow.** Painter's pow is the GPU's `exp2(g·log2 x)` (equal on 2^20 hashed inputs), whose log2 and exp2 are approximations: with a correctly rounded pow, `effect-order` s6 keeps 62 RGB16 values and `levels-clamp` s2 18 003 RGB32F values off. `uzp-evaluator-tests pow-hardware` measured both on every mantissa of four reduced domains; the rest of the domain follows by rule (`hwmath.h`: log2 is `e + lg2-hi[m]`, `lg2-lo[m]` or `(e + 1) + lg2-lo[m]` rounded toward zero; exp2 truncates the fraction of |y| to 23 bits and scales a table value, flushing below 2^-126). The four tables (`src/evaluator/tables/hw-lg2-hi.zlib` 275 544 bytes, `hw-lg2-lo.zlib` 285 848, `hw-ex2-pos.zlib` 196 765, `hw-ex2-neg.zlib` 197 953; second differences of the measured bit patterns) equal the GPU on all 4 × 8 388 608 entries, and `hw::Log2` and `hw::Exp2` equal it on 2^20 inputs each (40 edge values: zeros, subnormals, infinities, NaN, exponent limits; and 1 048 536 hashed inputs), `hw::Pow` on 2^20 hashed inputs.
- **Levels in masks** take no blending (the API refuses it, `api-probes/mask-stack`) and remap the mask in place.
- **Group masks.** A group's mask scales its isolated composite as a layer's does; `group-masks` s2 (default mode) and s3 (`Normal`) agree texel for texel, as s0 and s1 do.

## Tier 0 comparisons (CPU and GPU identical)

| Golden | Maps | r1 | r2 |
|---|---|---|---|
| `mask-precision` s0–s3 | 20 (RGB16, L16, RGB32F, sRGB8, L8) | exact | exact |
| `levels-clamp` s0–s3 | 16 (RGB32F, RGB16F, RGB16, L16F) | exact | exact |
| `effect-order` s6 | 2 (RGB16, sRGB8) | exact | exact |
| `group-masks` s2, s3 | 6 (RGB16, sRGB8, RGB32F) | exact (re-run; the first runs left 57 RGB16, 3 709 sRGB8, 21 469 RGB32F values off) | exact |
| `semantics-ui/group-passthrough-masks` s0–s3 | 12 (RGB16, sRGB8, RGB32F) | exact (re-run) | exact |
| `api-probes/mask-stack` | BaseColor | exact (2026-10-13, item 3 below) | unstable golden: 4 608 values off, Painter's own r1–r2 difference |

`parity/semantics/masks-levels.json` publishes every residual (entries `mask-precision`, `mask-stack-effect-mix`, `levels`, `levels-clamp`: exact; `group-masks`, `group-coverage-order`: exact under the current profile; `mask-stack-probe`: calibrated, exact on r1; `content-effect-order`, `geometry-mask-mesh`: gap). `python tests/evaluator/masks_fits.py <exe> <work>` re-derives it and `test_published_fit_reproduces` requires the file to match.

## Re-run on main (2026-10-11, items 3.3, 3.4, 4.1)

Same machine and backend (RTX 4090, DX12, `-Gis`), on worktree branch `wt/phase1.11-mask-close` at main `4949d28`. The command was `python -m pytest tests/evaluator/test_compositor_mask_effects.py tests/evaluator/test_compositor_blend_gaps.py::test_passthrough_groups_equal_the_golden`: 39 passed, none skipped, in 3 min 26 s. Every comparison covers both recordings on the CPU and on DX12.

- **Exact:** `mask-precision` s0–s3, `levels-clamp` s0–s3, `effect-order` s6, `group-masks` s2–s3 (3.4, the group mask in the default mode and in `Normal`), `group-coverage-order` s0–s3, and `semantics-ui/group-passthrough-masks` s0–s3 (3.4, the `PassThrough` group with a group mask, a child mask and both).
- **Converts and evaluates:** `api-probes/mask-stack`.
- **Re-derived byte for byte:** the published fit.
- **Pass:** the native cases `masks`, `masks-gpu-vs-cpu` and `pow-hardware`.

## Open items

Update 2026-10-11 (re-run on main `4949d28`): items 1 and 2 are resolved, and so is item 4 as far as this task owns it. Items 3, 5 and 6 stay as they were. Under the current profile `painter-12.1-isolated-coverage-weights` (`phase1.10_compositor-float32-residual`, decisions 044, 058, 059; `parity/reports/phase1/compositor-float32-residual.md`), `group-masks` s2–s3 is exact on RGB16, sRGB8 and RGB32F against both recordings, on the CPU and on DX12. The source-over onto a partly covered backdrop weights the source with the rounded coverage, with a fused read-out. The sRGB8 coverage goes through binary16 from one half up, and a 32-bit float uniform colour is its float32 value.

1. **Partly covered source-over (`group-masks` s2–s3). Resolved** by decisions 058 and 059 (above). The first runs, under `painter-12.1-isolated-linear`, left 57 RGB16, 3 709 sRGB8 and 21 469 RGB32F values of s2 off. They lay only where the Multiply child's mask (the ramp y/255) is strictly between 0 and 1, and over a hundred straight and premultiplied float32 orderings and coverage-storage variants failed to remove them. That profile is still registered and evaluated as it was.
2. **The 32-bit float operand of a uniform colour. Resolved:** the new profiles take the uniform fill's float32 value `float32(v)` instead of the read-out operand `1 + (v − 1)`. That reproduces the RGB32F row of `group-masks` where the child's mask is 0. `painter-12.1-isolated-linear` keeps its meaning (decision 017 pinning).
3. **`api-probes/mask-stack`. Resolved 2026-10-13: exact on r1.** The earlier claim that its masked half lay above the fill and the base, off the sRGB8 lattice, was wrong. The fit compared Painter's sRGB-encoded BaseColor export with the linear decode of the stored codes, which is the export rule of User channels. Under decision 126 an sRGB8 BaseColor exports the sRGB encode of that decode (`masks_fits.exported16`). With that rule the evaluation equals r1 on all 196 608 values: where the mask is 0, the template base `float32(0.8)` is stored as code 231 and exports 59422. r2 differs from r1 on 4 608 values (up to 252 codes): Painter is unstable here (`tier0-stability.md` §4), and the golden is not admitted. The published residual had been 3048 while the template base held the export value 0.9063401. It rose to 6943 when decision 126 made the base linear (full-gate republish `9df99a8`). Both values came from the fit's export rule, not from the mask stack. `test_mask_stack_probe_equals_r1` asserts r1.
4. **Content-effect order and the content fill effect's mix. Split by decision 069.** Every `effect-order` set except s6 (levels alone) and s7 (Blur alone) holds the starter-asset Blur filter. Blur is a P3-PROC filter effect that this task's proposal excludes, and it is not the identity on the fields' interiors. This task owns s6, which is exact, and the list order of fill and levels effects, which is a native unit case (`masks`: fill then levels differs from levels then fill). Neither is golden evidence of the order. s0–s5 and s7 are not evaluated: they belong to `phase3.2_proc-filter-families` item 3.4, whose scope now includes the Blur filter. The published fit keeps `content-effect-order` as a gap and names that owner. Filter effects fail with `unsupported_node`, and `phase1.14_compositor-core` item 2.8 registers them as release gaps.
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
