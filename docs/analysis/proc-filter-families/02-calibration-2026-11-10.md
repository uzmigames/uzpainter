# Filter calibration, 2026-11-10 (phase3.2_proc-filter-families items 2.1, 2.5, 2.6, 3.1)

Painter `12.2.0+js-api.1.1.20`, Legacy colour management, one session under the Assets3D Painter lock (seq 2370 to 2371). Requests: `parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/requests/phase3/proc-filters/` (`python -m tools.parity.proc_filters write`). Every golden was recorded twice (r1; r2 after save and reopen), admitted, verified (`python -m tools.parity.store verify`), and its inbox run deleted. Only numbers appear below. Every map is a private oracle in the owner's store.

## 1. How a filter golden is recorded

One Painter project per mesh and resolution (`tools/parity/proc_filters/requests.py`):

- Every L32F User channel is a fill of one authored periodic 256 x 256 16-bit bitmap (`parity/fixtures/proc-filters/content-grey.png`), tiled resolution / 256 times, Nearest. That puts one bitmap texel on each texel, offset by half a tile, because Painter scales about the UV centre.
- User0 holds the content alone. Each case adds one content effect on its own channel: the starter filter found by `s:starterassets u:filter n:<name>=` with the case's parameters, or the native levels effect.
- Painter then bakes World Space Normals with no dilation, to mark its UV coverage.
- Every map is exported as OpenEXR 32f with `passthrough` padding.
- Recording took 6 to 16 s per golden, with no other bake.

The compared texels are those of decision 423 §1. The batch builder (`tools/parity/proc_filters/batch.py`) checks that r1 equals r2 on every one of them, then stores each oracle with every other texel set to 0. The case input is the r1 content on every texel, because a filter reads neighbours across island borders.

**The content channel.** Each content texel is a function of its bitmap code k: on every texel of every golden, it is I(I(F(k))). Here I(v) = float32(1 - v), and F is the recording GPU's UNORM16 fetch, which is correctly rounded (`hw-unorm16.zlib`, decision 424 §1). For values below 0.5, this lands on a grid of 2^-24. It is the same twice-inverted store that `generator/occlusion@2` ends with.

## 2. Batches, pinned before certification (commit `e7a4df91`)

Both batches were recorded in the same session as their calibration sets, and pinned before any certification:

| Batch | Domain | §6 matrix (calibration) | Held-out |
|---|---|---|---|
| `filter/sharpen@2` | `intensity` in [0, 4] (the documented range); seed 0 | sphere, rounded cube, hat v8 x 1024/2048/4096 x {defaults 1, the hat v8 recipe sets 0.25, 0.2 and 0.4, boundaries 0 and 4}: 54 cases | knob cube 2048 and Tunic v10 1024 x {defaults, recipe 0.25, interior 0.63 and 2.71}: 8 cases |
| `filter/levels@2` | `filter.levels@1`'s ranges and constraint (input and output in [0, 1], gamma in [0.125, 8], clamp in {0, 1}); seed 0 | the same meshes and resolutions x {defaults, the right bracer's recipe (input 0.42 to 0.6), boundary gamma 0.125, boundary gamma 8 with output 1 to 0 and clamp}: 36 cases | the same meshes x {defaults, recipe, interior gamma 1.7 with output 0.05 to 0.9, interior gamma 0.4 with output 0.2 to 0.95 and clamp}: 8 cases |

Both have content as an L32F channel and a coverage input, with output in f32 mono at 1024/2048/4096.

**Disclosed:** exploration of the diagnostic golden and of the calibration goldens started before the pin commit. Every held-out golden had already been recorded, in the same session, before any fitting. The batch builder read the held-out oracles only to check r1 = r2 and to apply the coverage mask. No fit read them before certification.

## 3. Sharpen (`filter/sharpen@2`): calibrated, not exact

The model was found on the diagnostic golden and confirmed on the calibration set (`tools/parity/proc_filters/sharpen_candidate.py`):

- Painter's Sharpen is the four-neighbour Laplacian sharpening of Gonzalez and Woods, with Painter's `intensity` as the coefficient.
- It computes on the content's 16-bit codes, wrapping at the texture border: y = x + intensity (4 x - ((n + s) + (e + w))) on x = F(k).
- It writes the 16-bit code rint(clamp(y, 0, 1) 65535). The channel then stores I(I(F(code))).
- At intensity 1, an unconstrained 7 x 7 least-squares fit gives exactly that kernel.

Certification (`python -m tools.parity.proc_cert certify parity/manifests/phase3/proc-cert/filter__sharpen@2/batch.json --fitter tools.parity.proc_filters.sharpen_candidate:fit`): **outcome fail, `calibrated`**. The report is `parity/reports/phase3/proc-cert/filter__sharpen@2/727f63f70a79abab.json`. The held-out set is spent on this candidate, as the ledger records.

| Set | Calibration | Held-out |
|---|---|---|
| defaults (1), recipe 0.2, recipe 0.4, boundary 0, boundary 4 | 45 of 45 exact | defaults 2 of 2 exact |
| recipe 0.25 | 9 residual | 2 residual |
| interior 0.63, 2.71 | | 4 residual |

**Every residual texel is a code midpoint.** Each residual texel is one 16-bit code off, at a texel where intensity x (4 k - the neighbours' codes) lies exactly halfway between two codes. An intensity of 0.2 or 0.4 never gives a midpoint, and neither does an integer intensity. The intensities 0.25, 0.63 and 2.71 do.

On the sphere at 1024 with intensity 0.25, there are 52 224 midpoints. Painter rounds 49 868 of them down and 2 356 up.

None of these reproduces that split:

- the forms tried, which are every association of the five-tap sum, c + I L, (1 + 4I) c - I S, the fused multiply-add chains, the lerp forms, and inputs F(k), I(I(F(k))) or k float32(1 / 65535);
- conversions RNE of f32 or of exact y 65535, floor(y 65535 + 1/2), and a 24-bit quantised y.

A downward input bias (k / 65535 scaled by 1 - 2^-24) rounds every midpoint down, which leaves the 2 356 up. The residual is at most one code: 131 072 f32 ULP at the smallest outputs. Pooled, the mean is 6.9 ULP and p99 is 0.

## 4. Levels (`filter/levels@2`): calibrated, not exact

The native levels effect (`masks-levels.json` `levels`, `levels-clamp`; `tools/parity/proc_filters/levels_candidate.py`) works as follows:

- It reads x = F(k), not the stored content.
- It computes t = (x - in_min) Rcp(in_max - in_min) with the GPU's reciprocal, clamps t when `clamp` is set, and applies sign(t) pow(|t|, gamma) with the GPU's log2 and exp2 (`tools/parity/fit/hwmath.py` `log2`, `exp2`, `pow`). The output is fma(t, out_max - out_min, out_min).
- The channel then stores I(I(.)).

Certification: **outcome fail, `calibrated`**. Calibration is 36 of 36 exact. Held-out is 6 of 8 exact. The report is `parity/reports/phase3/proc-cert/filter__levels@2/a278c3bef66e745b.json`, and the held-out set is spent.

- The two residual cases are `interior-a`: gamma 1.7, output 0.05 to 0.9, no clamp, on the knob cube at 2048 (1 218 014 texels) and on Tunic v10 at 1024 (119 164 texels). The maximum is 32 f32 ULP. Painter's output lies 1 to 8 ULP below the candidate's, by a roughly constant relative factor of about -2.5e-7, which corresponds to an effective gamma of 1.7000006.
- The other interior set, gamma 0.4 with output 0.2 to 0.95 and clamp, is exact. So are all calibration gammas (1, 0.125 and 8). Correct division in place of the reciprocal, other output forms, and the exact pow do not close the gap.
- The calibration set has no gamma that is neither 1 nor a power of two with `clamp` off. That regime is what the held-out set exposed.
- The residual was looked at in order to refit, so both `interior-a` cases are spent. They join the calibration set as regression cases (decision 222 §2), and the next candidate needs a new held-out set.

## 5. Grayscale Conversion and Blur (diagnostic golden only)

`diagnostic-mixed-rounded-cube-1024` uses RGB32F channels with RGB content on the rounded cube at 1024. It is never a calibration or held-out case.

| Filter | Separating evidence | Status |
|---|---|---|
| Grayscale Conversion | Its outputs lie on the 16-bit code grid. In `Channels Weights` mode, the weighted sum of F(k) stored at 16 bits misses 26 657 of 608 972 compared texels by one code (defaults) and 17 954 (BT.709 weights). `Average` mode is not the mean. | release gap: no Assets3D recipe uses it, so the harness has no recipe parameter set for its §6 matrix (decision 303) |
| Blur | r1 and r2 differ on compared texels: by up to 6e-8 on 35 186 of them at its defaults, and on 4 838 at intensity 4. Eroding the coverage by 8 texels still leaves 33 392 differing, so this is not a coverage effect. Painter does not reproduce its own Blur across a save and reopen. | release gap: no recipe uses it, and save-reopen-unstable (decision 032 territory). The Tier 0 `effect-order` behaviour of decision 346 stands. |

The Sharpen case on RGB in the same golden follows the Sharpen model on every compared unclamped value whose output code also occurs in the content (919 175 values, none differing).

## 6. Not covered

- Sharpen inside a mask stack, where three of the four hat v8 uses are, and on channels other than L32F.
- Levels on RGB channels, or with per-component parameters.
- Content that is not a 16-bit bitmap fill. Both candidates refuse content off the I(I(F(k))) grid.
