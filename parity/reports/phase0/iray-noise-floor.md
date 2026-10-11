# Iray noise floor and first render fits

Task `phase0.8_render-reference-fits` (child of `phase0.9_render-reference-capture`, P0-FEAS-RENDER in `docs/dag.md`). It measures the noise floor of Tier 3 render parity, (a) Iray's run-to-run difference, (b) Iray's Monte-Carlo error at S and (c) UzPainter's error at S (`docs/architecture/07-preview-and-render-parity.md` §4 step 1), publishes the first clean-room lobe fits with their residuals (`parity/semantics/iray.json`), records the transport evidence and the ray-tracing probes of the owner's GPU. Decisions 038 (fixed pipeline), 042 (open-pbr scope), 046 (the reference set) and 050-052 apply. This report holds numbers and hashes only; Painter's renders stay in the private store, and the prototype's renders stay in the work folder on the owner's machine.

**Status (2026-10-11).** Noise floor measured: (a) and (b) for the 22 fixture goldens of decision 046, (c) for the feasibility prototype. First clean-room lobe fits published in `parity/semantics/iray.json`, all `calibrated`. **No lobe is reproduced:** on held-out pixels the chosen model sits 4 to 930 codes (up to 1.4% of full scale) from Iray's k*S renders, far outside the noise floor (§4). The ray-tracing probes of the owner's RTX 4090 pass (§8). Open: the cause of the face-confined run-to-run difference, provisional until the capture request of §9 returns; the shipped tracer's term (c) (phase3.6); the lobe structure (phase3.5).

## 1. Scope (decision 050)

- **References.** The 22 fixture goldens of decision 046 (`iray-references.md`), each with two `separate_session` S renders (256 samples) and one `k_times_samples` render (k = 4), Save Render 16-bit display-referred PNG at 1200 x 1200, OCIO Default - sRGB. The qualification sphere is left out: its material is the template default, which no fixture table records.
- **Prototype.** `tools/parity/render_fits/` is a CPU program written from the 07 §3.1 sources: path tracing with next-event estimation and multiple importance sampling (power heuristic), piecewise-constant environment importance sampling, Russian roulette after three vertices, at most eight vertices, Owen-scrambled Sobol (Burley 2020) under a fixed seed, each pixel summing its samples in index order. It is not shipped and is never Tier 3 evidence. It renders the fixtures as Painter stores them: sRGB8 base colour, L8 metalness and roughness, the committed meshes and bitmaps, the camera of decision 046 and the pipeline's two environments read by SHA-256 on the owner's machine.
- **Term (c).** Measured on the prototype. Phase3.6 item 2.3 measures the shipped `painter_iray`'s (c) with the same statistics (`noise.pair_statistics`).
- **Units.** 16-bit display codes of the reference encoding (one 8-bit code is 257 codes; 1e-4 of full scale is 6.55 codes), RGB samples, per region: `interior` (object pixels), `edge` (the 2-pixel band around the projected outline), `background`.

## 2. Display encoding and the structure of the run-to-run difference

**Display encoding (item 2.3, `iray.json` entry `display-encoding`).** Under the fixed pipeline every Iray code is, to within one code, the IEC 61966-2-1 encoding of a binary16 (half-float) linear value: of the interior RGB samples of the 66 fixture renders, 95.65% lie exactly on that 10,871-code lattice and every other one is a single code away. The clear-colour background lies on it too. This is a fitted model of the observable codes, not a statement about Iray's internals; the prototype's renders go through the same model before any comparison.

**Run-to-run (a), the rounding class.** In 19 goldens the two sessions differ only in scattered samples, and 79% to 100% of those differ by exactly one binary16 step of the linear value (table below; one step is about 9 codes at 18% grey). They are spatially white and zero-mean, and the same-session repeat of the procedure probe shows the same count. Iray is therefore not bit-repeatable, at the level of floating-point rounding; the mechanism (accumulation order or otherwise) is not identified.

**Run-to-run (a), the face-confined class.** In three goldens the difference is broad (up to 36 binary16 steps) and confined to whole flat faces: the tilted plane (96.5% of its pixels) and the bevelled cube's top face in `cube-mid-grey` (86%) and `cube-saturated--ref-match-000` (90%). The other five visible cube faces stay at the rounding level, and in `cube-saturated--ref-match-180` the top face does too (0.1%). The two affected facets are exactly those whose normal has an x component of exactly zero: the plane n = (0, 0.77, 0.64) and the cube's top n = (0, 0.91, 0.42); every unaffected face has a nonzero x component. Within the plane, rms(a)^2 / 2 rms(b)^2 = 0.126: about an eighth of the S render's noise is drawn afresh in each render. Decision 052 records a hypothesis, not an explanation: a sampling frame that depends on the sign of an exactly-zero normal component, so that renders draw mirrored sample sets whose values differ only where the environment is asymmetric about that mirror. Branching on a degenerate value or other state-dependent sampling remain alternatives. The capture request of §9 tests it. Until it returns, (a) of these three goldens is provisional and reported per face below; it stays out of the floor because (b) already contains each S render's own noise, and any bound on these faces must respect the per-face (a).

**Nested samples.** On all 13 goldens whose interior is noise-dominated (sigma_K^2 / sigma_S^2 below 0.3), rms(S - K) matches sqrt(sigma_S^2 - sigma_K^2) from the renders' own high-pass noise, not sqrt(sigma_S^2 + sigma_K^2): the k*S render continues the S render's sample sequence. The measured ratio sigma_K^2 / sigma_S^2 is 0.13 to 0.19 for this one pair of sample counts, below the 1/k = 0.25 of independent samples. It is recorded as measured, not as a convergence law, and bounds derived from (b) are not rescaled by 1/k (decision 052). The S-render sigma of decision 046 (a range) is replaced by the nested reading and the high-pass sigma_S per golden.

**Bias of S against k*S.** The S render is darker than the k*S render on every noise-dominated golden. Jensen's inequality on the concave encoding predicts the sign on 13 of 13; the observed / predicted magnitude ranges from 0.3 to 2.0 (median about 1.3; columns `Jensen-predicted` and `observed` below). It contributes; it is not shown to be the whole bias. Bias tests report the comparison at the same S and the k*S comparison raw and with the predicted term subtracted, with the prediction's spread; equal S does not cancel the term when two renderers' variances differ (decision 052). Rows whose high-pass sigma is dominated by image structure (sigma_K^2 / sigma_S^2 near 1: the mirror spheres, low-roughness and perturbed fixtures, the 180-degree cube) do not measure noise and are given for completeness.

<!-- display:begin -->
| Interior RGB samples | On the lattice | Fraction | Distinct codes | Off-lattice codes | Largest distance | Lattice size |
|---|---|---|---|---|---|---|
| 46769247 | 44734063 | 0.9565 | 9903 | 625 | 1 code | 10871 |
<!-- display:end -->

<!-- half-steps:begin -->
| Golden | (a) differing samples | 1 step | 2 steps | 3 steps | > 3 steps | Max steps | One-step fraction |
|---|---|---|---|---|---|---|---|
| `neutral-reflective` | 377 | 376 | 1 | 0 | 0 | 2 | 0.997 |
| `metal1-rough010` | 1458 | 1148 | 143 | 43 | 110 | 164 | 0.787 |
| `metal1-rough050` | 3891 | 3721 | 125 | 30 | 15 | 9 | 0.956 |
| `metal1-rough090` | 5105 | 4825 | 146 | 88 | 46 | 9 | 0.945 |
| `neutral-grey-diffuse` | 6000 | 5421 | 299 | 185 | 95 | 7 | 0.903 |
| `base-light-grey` | 5518 | 4995 | 309 | 135 | 79 | 7 | 0.905 |
| `base-saturated` | 2325 | 2147 | 98 | 39 | 41 | 15 | 0.923 |
| `metal0-rough010` | 1747 | 1604 | 86 | 38 | 19 | 7 | 0.918 |
| `metal0-rough050` | 3065 | 2824 | 142 | 58 | 41 | 8 | 0.921 |
| `metal0-rough090` | 2385 | 2180 | 133 | 40 | 32 | 8 | 0.914 |
| `normal-ridges` | 4761 | 4477 | 158 | 58 | 68 | 16 | 0.940 |
| `height-stripes` | 2448 | 2226 | 128 | 58 | 36 | 10 | 0.909 |
| `emission` | 4958 | 4454 | 286 | 112 | 106 | 10 | 0.898 |
| `opacity-stripes` | 2685 | 2480 | 141 | 39 | 25 | 5 | 0.924 |
| `plane-mid-grey` | 739559 | 207062 | 152826 | 109924 | 269747 | 36 | 0.280 |
| `cube-mid-grey` | 66062 | 34932 | 12293 | 7143 | 11694 | 18 | 0.529 |
| `neutral-grey-diffuse--ref-match-000` | 2475 | 2235 | 132 | 66 | 42 | 9 | 0.903 |
| `neutral-grey-diffuse--ref-match-180` | 654 | 612 | 21 | 6 | 9 | 4 | 0.936 |
| `neutral-reflective--ref-match-000` | 66 | 66 | 0 | 0 | 0 | 1 | 1.000 |
| `neutral-reflective--ref-match-180` | 465 | 465 | 0 | 0 | 0 | 1 | 1.000 |
| `cube-saturated--ref-match-000` | 71864 | 31760 | 14000 | 8417 | 17678 | 16 | 0.442 |
| `cube-saturated--ref-match-180` | 1464 | 1285 | 127 | 11 | 6 | 7 | 0.878 |
<!-- half-steps:end -->

<!-- faces:begin -->
| Golden | Face (facet normal) | Pixels | (a) differing fraction | (a) rms | (b) rms | rms(a)^2 / 2 rms(b)^2 | One-step fraction |
|---|---|---|---|---|---|---|---|
| `plane-mid-grey` | face n=(+0.00, +0.77, +0.64) | 286384 | 0.965 | 67.2 | 133.7 | 0.126 | 0.28 |
| `cube-mid-grey` | face n=(+0.00, +0.91, +0.42) | 31713 | 0.860 | 21.3 | 142.7 | 0.011 | 0.50 |
| `cube-mid-grey` | face n=(+0.41, +0.40, +0.82) | 17652 | 0.005 | 1.1 | 212.9 | 0.000 | 0.73 |
| `cube-mid-grey` | face n=(+0.57, -0.35, +0.74) | 74997 | 0.010 | 0.9 | 144.3 | 0.000 | 0.96 |
| `cube-mid-grey` | face n=(-0.17, -0.42, +0.89) | 20115 | 0.041 | 1.2 | 131.6 | 0.000 | 0.96 |
| `cube-mid-grey` | face n=(-0.58, +0.47, +0.67) | 12460 | 0.016 | 1.7 | 112.1 | 0.000 | 0.84 |
| `cube-mid-grey` | face n=(-0.82, -0.24, +0.52) | 43778 | 0.026 | 1.3 | 201.5 | 0.000 | 0.94 |
| `cube-saturated--ref-match-000` | face n=(+0.00, +0.91, +0.42) | 31713 | 0.900 | 26.7 | 143.2 | 0.017 | 0.43 |
| `cube-saturated--ref-match-000` | face n=(+0.41, +0.40, +0.82) | 17652 | 0.007 | 1.3 | 167.2 | 0.000 | 0.76 |
| `cube-saturated--ref-match-000` | face n=(+0.57, -0.35, +0.74) | 74997 | 0.007 | 0.3 | 75.9 | 0.000 | 0.93 |
| `cube-saturated--ref-match-000` | face n=(-0.17, -0.42, +0.89) | 20115 | 0.005 | 0.4 | 95.9 | 0.000 | 0.97 |
| `cube-saturated--ref-match-000` | face n=(-0.58, +0.47, +0.67) | 12460 | 0.007 | 1.4 | 139.4 | 0.000 | 0.76 |
| `cube-saturated--ref-match-000` | face n=(-0.82, -0.24, +0.52) | 43778 | 0.006 | 0.4 | 108.3 | 0.000 | 0.95 |
| `cube-saturated--ref-match-180` | face n=(+0.00, +0.91, +0.42) | 31713 | 0.001 | 0.3 | 788.5 | 0.000 | 1.00 |
| `cube-saturated--ref-match-180` | face n=(+0.41, +0.40, +0.82) | 17652 | 0.003 | 0.2 | 154.7 | 0.000 | 0.98 |
| `cube-saturated--ref-match-180` | face n=(+0.57, -0.35, +0.74) | 74997 | 0.010 | 0.2 | 35.0 | 0.000 | 0.86 |
| `cube-saturated--ref-match-180` | face n=(-0.17, -0.42, +0.89) | 20115 | 0.006 | 0.2 | 31.9 | 0.000 | 0.93 |
| `cube-saturated--ref-match-180` | face n=(-0.58, +0.47, +0.67) | 12460 | 0.003 | 0.1 | 202.8 | 0.000 | 0.91 |
| `cube-saturated--ref-match-180` | face n=(-0.82, -0.24, +0.52) | 43778 | 0.006 | 0.2 | 61.2 | 0.000 | 0.86 |
<!-- faces:end -->

<!-- sequence:begin -->
| Golden | sigma S (high-pass) | sigma K | sigma_K^2 / sigma_S^2 | rms(S - K) | nested prediction | independent prediction | Jensen-predicted S - K | observed S - K (s1 / s2) |
|---|---|---|---|---|---|---|---|---|
| `neutral-reflective` | 1032.8 | 1032.2 | 0.999 | 8.7 | 34.7 | 1460.2 | -0.04 | -0.11 / -0.11 |
| `metal1-rough010` | 334.4 | 310.5 | 0.862 | 129.0 | 124.1 | 456.4 | -0.51 | -0.83 / -0.83 |
| `metal1-rough050` | 205.1 | 80.8 | 0.155 | 188.0 | 188.5 | 220.5 | -0.74 | -1.01 / -1.01 |
| `metal1-rough090` | 150.6 | 56.6 | 0.141 | 138.9 | 139.6 | 160.9 | -0.37 | -0.42 / -0.42 |
| `neutral-grey-diffuse` | 157.7 | 59.1 | 0.140 | 143.2 | 146.2 | 168.4 | -0.40 | -0.48 / -0.48 |
| `base-light-grey` | 243.1 | 93.6 | 0.148 | 224.7 | 224.4 | 260.5 | -0.62 | -1.21 / -1.21 |
| `base-saturated` | 250.3 | 110.1 | 0.193 | 236.5 | 224.8 | 273.4 | -1.38 | -2.29 / -2.29 |
| `metal0-rough010` | 286.9 | 235.0 | 0.671 | 164.6 | 164.6 | 370.9 | -0.49 | -0.84 / -0.84 |
| `metal0-rough050` | 189.5 | 74.5 | 0.155 | 174.4 | 174.3 | 203.7 | -0.55 | -0.66 / -0.66 |
| `metal0-rough090` | 167.8 | 61.1 | 0.133 | 154.1 | 156.3 | 178.6 | -0.44 | -0.58 / -0.58 |
| `normal-ridges` | 213.5 | 92.8 | 0.189 | 190.4 | 192.3 | 232.8 | -0.68 | -1.09 / -1.09 |
| `height-stripes` | 404.6 | 355.7 | 0.773 | 192.4 | 192.9 | 538.7 | -0.68 | -1.26 / -1.26 |
| `emission` | 189.5 | 74.5 | 0.155 | 174.4 | 174.3 | 203.7 | -0.55 | -0.66 / -0.66 |
| `opacity-stripes` | 189.5 | 74.5 | 0.155 | 174.3 | 174.3 | 203.7 | -0.55 | -0.66 / -0.66 |
| `plane-mid-grey` | 139.7 | 53.6 | 0.147 | 130.6 | 129.0 | 149.6 | -0.28 | -0.30 / -0.32 |
| `cube-mid-grey` | 232.8 | 166.8 | 0.514 | 161.6 | 162.3 | 286.4 | -0.49 | -0.54 / -0.53 |
| `neutral-grey-diffuse--ref-match-000` | 114.5 | 40.8 | 0.127 | 105.5 | 106.9 | 121.5 | -0.28 | -0.30 / -0.30 |
| `neutral-grey-diffuse--ref-match-180` | 50.2 | 18.7 | 0.139 | 46.7 | 46.6 | 53.6 | -0.14 | -0.04 / -0.04 |
| `neutral-reflective--ref-match-000` | 19.7 | 19.6 | 1.000 | 1.0 | 0.4 | 27.8 | -0.00 | 0.00 / 0.00 |
| `neutral-reflective--ref-match-180` | 25.5 | 25.5 | 0.999 | 0.9 | 0.6 | 36.1 | -0.00 | -0.00 / 0.00 |
| `cube-saturated--ref-match-000` | 161.7 | 151.4 | 0.877 | 56.0 | 56.7 | 221.5 | -0.14 | -0.26 / -0.27 |
| `cube-saturated--ref-match-180` | 615.2 | 547.1 | 0.791 | 297.9 | 281.3 | 823.2 | -3.78 | -1.46 / -1.46 |
<!-- sequence:end -->

## 3. Noise floor per fixture and region

Per golden and region: (a) the two sessions, (b) the first S render against k*S (the second gives the same values within the precision shown; both are in `iray-references.md`), (c) the prototype's seed-1 S render against its own k*S render on a 256 x 256 crop that starts at the interior's centroid (interior, edge and background inside it), all in 16-bit codes; the mean signed delta carries its standard error over 16 x 16 blocks; the downsampled columns give mean |delta| after 2x, 4x and 8x box averaging over blocks wholly inside the region (none fit in the 2-pixel edge band at 8x). The prototype's seed-to-seed difference and its residual against Iray on the same crop are in the measurement's `results.json` (owner's machine).

The floor of a Tier 3 bound combines (b) and (c) per region (07 §4 step 1). On the dielectric goldens the prototype's (c) is 1.3 to 2 times Iray's (b) (grey diffuse interior 154 against 115 codes mean |delta|): at equal samples the prototyped sampler is noisier than Iray's and would need about 2 to 4 times the samples for the same floor. On the low-roughness metals it is quieter (38 against 65).

<!-- noise-floor:begin -->
| Golden | Region | Pixels | (a) mean abs | (a) p99 | (b) mean abs | (b) p99 | (b) mean signed ± se | (c) crop pixels | (c) mean abs | (c) p99 | (c) mean signed ± se | (b) 2x/4x/8x mean abs | (c) 2x/4x/8x mean abs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `neutral-reflective` | interior | 238752 | 0.0 | 0 | 1.5 | 24 | -0.11 ± 0.05 | 57339 | 6.3 | 74 | 0.00 ± 0.06 | 1.1 / 0.7 / 0.4 | 4.5 / 2.6 / 1.3 |
| `neutral-reflective` | edge | 9444 | 0.0 | 0 | 29.8 | 320 | -0.10 ± 0.77 | 1021 | 44.5 | 470 | -0.35 ± 2.84 | 24.9 / 13.6 / - | 41.9 / 19.4 / - |
| `neutral-reflective` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `metal1-rough010` | interior | 238752 | 0.0 | 0 | 65.3 | 508 | -0.83 ± 0.46 | 57339 | 37.8 | 311 | -0.23 ± 0.28 | 32.3 / 15.9 / 7.6 | 19.1 / 9.9 / 4.9 |
| `metal1-rough010` | edge | 9444 | 0.0 | 0 | 115.6 | 870 | -5.29 ± 2.98 | 1021 | 87.3 | 679 | 2.68 ± 5.11 | 76.4 / 45.2 / - | 69.7 / 27.2 / - |
| `metal1-rough010` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `metal1-rough050` | interior | 238752 | 0.1 | 0 | 128.4 | 651 | -1.01 ± 0.67 | 57339 | 59.8 | 234 | -0.21 ± 0.38 | 63.3 / 31.3 / 14.6 | 29.9 / 15.0 / 7.7 |
| `metal1-rough050` | edge | 9444 | 0.1 | 0 | 157.7 | 1235 | 0.48 ± 4.77 | 1021 | 66.2 | 540 | 5.36 ± 3.67 | 99.5 / 56.0 / - | 54.3 / 37.6 / - |
| `metal1-rough050` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `metal1-rough090` | interior | 238752 | 0.1 | 0 | 111.0 | 373 | -0.42 ± 0.37 | 57339 | 97.1 | 329 | 0.55 ± 0.69 | 55.4 / 27.5 / 12.6 | 48.9 / 24.3 / 12.2 |
| `metal1-rough090` | edge | 9444 | 0.0 | 0 | 96.6 | 495 | -1.08 ± 2.11 | 1021 | 73.8 | 486 | -0.99 ± 3.70 | 60.2 / 35.9 / - | 56.8 / 32.6 / - |
| `metal1-rough090` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `neutral-grey-diffuse` | interior | 238752 | 0.1 | 0 | 114.6 | 385 | -0.48 ± 0.34 | 57339 | 154.2 | 518 | -0.91 ± 0.91 | 57.1 / 28.2 / 13.3 | 77.1 / 38.0 / 19.6 |
| `neutral-grey-diffuse` | edge | 9444 | 0.0 | 0 | 77.5 | 434 | -0.17 ± 1.91 | 1021 | 124.0 | 615 | 3.40 ± 6.66 | 49.1 / 27.7 / - | 74.2 / 46.9 / - |
| `neutral-grey-diffuse` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `base-light-grey` | interior | 238752 | 0.1 | 0 | 173.0 | 638 | -1.21 ± 0.60 | 57339 | 305.4 | 1036 | -0.36 ± 1.76 | 86.2 / 42.8 / 20.0 | 152.3 / 76.6 / 38.0 |
| `base-light-grey` | edge | 9444 | 0.1 | 0 | 143.1 | 1070 | -2.02 ± 2.35 | 1021 | 206.3 | 992 | 13.21 ± 8.95 | 86.7 / 49.0 / - | 124.1 / 47.4 / - |
| `base-light-grey` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `base-saturated` | interior | 238752 | 0.0 | 0 | 184.2 | 955 | -2.29 ± 0.70 | 57339 | 181.2 | 862 | -0.51 ± 0.84 | 90.8 / 43.9 / 20.3 | 90.6 / 45.0 / 22.2 |
| `base-saturated` | edge | 9444 | 0.0 | 0 | 205.0 | 1259 | 3.38 ± 5.66 | 1021 | 187.2 | 976 | 5.45 ± 13.40 | 117.8 / 69.5 / - | 116.1 / 55.0 / - |
| `base-saturated` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `metal0-rough010` | interior | 238752 | 0.0 | 0 | 113.0 | 567 | -0.84 ± 0.41 | 57339 | 206.5 | 689 | 0.02 ± 1.13 | 56.1 / 27.5 / 13.0 | 102.3 / 51.7 / 26.2 |
| `metal0-rough010` | edge | 9444 | 0.0 | 0 | 121.3 | 869 | -4.45 ± 2.89 | 1021 | 184.9 | 1618 | -5.66 ± 12.85 | 77.8 / 45.8 / - | 148.9 / 84.9 / - |
| `metal0-rough010` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `metal0-rough050` | interior | 238752 | 0.0 | 0 | 127.3 | 523 | -0.66 ± 0.71 | 57339 | 182.5 | 630 | -0.06 ± 1.07 | 63.5 / 31.2 / 14.3 | 91.2 / 45.7 / 22.9 |
| `metal0-rough050` | edge | 9444 | 0.0 | 0 | 132.7 | 977 | -1.74 ± 4.61 | 1021 | 150.6 | 777 | 7.10 ± 9.70 | 81.5 / 46.4 / - | 95.3 / 44.0 / - |
| `metal0-rough050` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `metal0-rough090` | interior | 238752 | 0.0 | 0 | 123.3 | 414 | -0.58 ± 0.34 | 57339 | 169.7 | 579 | -1.33 ± 1.04 | 61.5 / 30.6 / 14.6 | 85.5 / 42.8 / 21.8 |
| `metal0-rough090` | edge | 9444 | 0.0 | 0 | 74.4 | 398 | -2.15 ± 1.91 | 1021 | 131.1 | 675 | 3.24 ± 6.91 | 44.4 / 22.9 / - | 79.2 / 41.7 / - |
| `metal0-rough090` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `normal-ridges` | interior | 238752 | 0.1 | 0 | 142.9 | 574 | -1.09 ± 0.44 | 57339 | 199.0 | 703 | -1.81 ± 1.17 | 71.1 / 35.1 / 16.6 | 100.1 / 49.9 / 24.5 |
| `normal-ridges` | edge | 9444 | 0.1 | 0 | 128.1 | 962 | -1.58 ± 2.56 | 1021 | 151.1 | 777 | 6.20 ± 9.89 | 78.5 / 48.9 / - | 95.2 / 44.0 / - |
| `normal-ridges` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `height-stripes` | interior | 238752 | 0.0 | 0 | 136.7 | 660 | -1.26 ± 0.88 | 57339 | 185.7 | 651 | -0.24 ± 1.14 | 68.3 / 33.6 / 15.6 | 92.6 / 46.3 / 23.6 |
| `height-stripes` | edge | 9444 | 0.0 | 0 | 149.7 | 1129 | -1.29 ± 4.65 | 1021 | 157.4 | 863 | 9.79 ± 9.02 | 91.5 / 51.0 / - | 94.8 / 41.6 / - |
| `height-stripes` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `emission` | interior | 238752 | 0.1 | 0 | 127.3 | 523 | -0.66 ± 0.71 | 57339 | 182.5 | 630 | -0.06 ± 1.07 | 63.5 / 31.2 / 14.3 | 91.2 / 45.7 / 22.9 |
| `emission` | edge | 9444 | 0.0 | 0 | 132.7 | 977 | -1.75 ± 4.61 | 1021 | 150.6 | 777 | 7.10 ± 9.70 | 81.5 / 46.4 / - | 95.3 / 44.0 / - |
| `emission` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `opacity-stripes` | interior | 238752 | 0.0 | 0 | 127.3 | 523 | -0.66 ± 0.71 | 57339 | 182.5 | 630 | -0.06 ± 1.07 | 63.5 / 31.2 / 14.3 | 91.2 / 45.7 / 22.9 |
| `opacity-stripes` | edge | 9444 | 0.0 | 0 | 132.7 | 977 | -1.73 ± 4.61 | 1021 | 150.6 | 777 | 7.10 ± 9.70 | 81.5 / 46.4 / - | 95.3 / 44.0 / - |
| `opacity-stripes` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `plane-mid-grey` | interior | 286384 | 46.1 | 232 | 106.8 | 340 | -0.30 ± 0.20 | 52224 | 181.8 | 584 | -1.56 ± 0.97 | 53.4 / 26.4 / 12.1 | 91.5 / 46.7 / 22.6 |
| `plane-mid-grey` | edge | 13284 | 35.5 | 259 | 69.5 | 364 | -0.92 ± 1.28 | 1536 | 175.3 | 1248 | 1.00 ± 6.68 | 41.8 / 26.7 / - | 97.8 / 84.3 / - |
| `plane-mid-grey` | background | 1140332 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 11776 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `cube-mid-grey` | interior | 204221 | 2.2 | 47 | 128.0 | 441 | -0.54 ± 0.46 | 50632 | 188.2 | 621 | 0.56 ± 1.48 | 63.7 / 31.6 / 14.3 | 94.9 / 47.6 / 23.8 |
| `cube-mid-grey` | edge | 9407 | 1.3 | 32 | 87.0 | 464 | -0.30 ± 1.78 | 2259 | 141.2 | 864 | 4.56 ± 5.15 | 51.0 / 32.0 / - | 88.0 / 60.4 / - |
| `cube-mid-grey` | background | 1226372 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 12645 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `neutral-grey-diffuse--ref-match-000` | interior | 238752 | 0.0 | 0 | 82.7 | 284 | -0.30 ± 0.21 | 57339 | 87.7 | 310 | -0.64 ± 0.56 | 41.2 / 20.5 / 9.5 | 43.6 / 22.3 / 11.1 |
| `neutral-grey-diffuse--ref-match-000` | edge | 9444 | 0.0 | 0 | 54.2 | 362 | -1.97 ± 1.91 | 1021 | 65.5 | 367 | -3.58 ± 4.73 | 33.7 / 19.8 / - | 42.5 / 28.7 / - |
| `neutral-grey-diffuse--ref-match-000` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `neutral-grey-diffuse--ref-match-180` | interior | 238752 | 0.0 | 0 | 29.7 | 173 | -0.04 ± 0.16 | 57339 | 73.3 | 243 | -0.85 ± 0.44 | 14.9 / 7.3 / 3.3 | 36.7 / 18.5 / 9.3 |
| `neutral-grey-diffuse--ref-match-180` | edge | 9444 | 0.0 | 0 | 45.0 | 343 | -1.51 ± 0.93 | 1021 | 62.7 | 404 | -6.23 ± 6.16 | 31.0 / 18.0 / - | 45.4 / 36.5 / - |
| `neutral-grey-diffuse--ref-match-180` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `neutral-reflective--ref-match-000` | interior | 238752 | 0.0 | 0 | 0.1 | 0 | 0.00 ± 0.00 | 57339 | 0.5 | 8 | 0.01 ± 0.01 | 0.1 / 0.1 / 0.0 | 0.4 / 0.3 / 0.2 |
| `neutral-reflective--ref-match-000` | edge | 9444 | 0.0 | 0 | 20.9 | 261 | -1.52 ± 0.57 | 1021 | 28.6 | 307 | -4.39 ± 2.71 | 19.7 / 12.1 / - | 28.2 / 21.0 / - |
| `neutral-reflective--ref-match-000` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `neutral-reflective--ref-match-180` | interior | 238752 | 0.0 | 0 | 0.1 | 0 | -0.00 ± 0.01 | 57339 | 0.5 | 8 | -0.06 ± 0.02 | 0.1 / 0.0 / 0.0 | 0.5 / 0.4 / 0.2 |
| `neutral-reflective--ref-match-180` | edge | 9444 | 0.0 | 0 | 15.5 | 225 | -0.83 ± 0.45 | 1021 | 28.1 | 310 | -4.10 ± 2.71 | 14.4 / 9.2 / - | 27.4 / 19.8 / - |
| `neutral-reflective--ref-match-180` | background | 1191804 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 7176 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `cube-saturated--ref-match-000` | interior | 204221 | 2.3 | 50 | 73.9 | 413 | -0.26 ± 0.24 | 50632 | 59.4 | 318 | -0.53 ± 0.56 | 36.6 / 18.0 / 8.1 | 29.6 / 14.7 / 7.4 |
| `cube-saturated--ref-match-000` | edge | 9407 | 1.9 | 49 | 57.9 | 427 | -2.16 ± 1.54 | 2259 | 56.6 | 450 | -2.29 ± 1.68 | 36.0 / 21.9 / - | 36.9 / 25.2 / - |
| `cube-saturated--ref-match-000` | background | 1226372 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 12645 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| `cube-saturated--ref-match-180` | interior | 204221 | 0.0 | 0 | 135.5 | 1463 | -1.46 ± 0.86 | 50632 | 36.0 | 195 | -0.04 ± 0.41 | 66.5 / 32.1 / 13.9 | 18.2 / 9.1 / 4.5 |
| `cube-saturated--ref-match-180` | edge | 9407 | 0.0 | 0 | 159.7 | 1617 | -3.82 ± 3.95 | 2259 | 60.8 | 601 | -3.44 ± 2.34 | 91.3 / 50.8 / - | 42.1 / 33.1 / - |
| `cube-saturated--ref-match-180` | background | 1226372 | 0.0 | 0 | 0.0 | 0 | 0.00 ± 0.00 | 12645 | 0.0 | 0 | 0.00 ± 0.00 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
<!-- noise-floor:end -->

FLIP (NVIDIA `flip-evaluator` 1.7, LDR, display-encoded inputs, default 67 pixels per degree), mean per region of the 256 x 256 crop; diagnostic only:

<!-- flip:begin -->
| Golden | Region | Iray S vs Iray k*S | Prototype S vs prototype k*S | Prototype S vs Iray k*S |
|---|---|---|---|---|
| `neutral-reflective` | interior | 0.0007 | 0.0016 | 0.0307 |
| `neutral-reflective` | edge | 0.0041 | 0.0049 | 0.0842 |
| `metal1-rough010` | interior | 0.0041 | 0.0032 | 0.0097 |
| `metal1-rough010` | edge | 0.0089 | 0.0071 | 0.0487 |
| `metal1-rough050` | interior | 0.0068 | 0.0046 | 0.0088 |
| `metal1-rough050` | edge | 0.0083 | 0.0061 | 0.0249 |
| `metal1-rough090` | interior | 0.0070 | 0.0065 | 0.0138 |
| `metal1-rough090` | edge | 0.0071 | 0.0062 | 0.0416 |
| `neutral-grey-diffuse` | interior | 0.0073 | 0.0090 | 0.0414 |
| `neutral-grey-diffuse` | edge | 0.0073 | 0.0085 | 0.0335 |
| `base-light-grey` | interior | 0.0096 | 0.0148 | 0.0557 |
| `base-light-grey` | edge | 0.0087 | 0.0128 | 0.3174 |
| `base-saturated` | interior | 0.0151 | 0.0163 | 0.0875 |
| `base-saturated` | edge | 0.0125 | 0.0153 | 0.2862 |
| `metal0-rough010` | interior | 0.0065 | 0.0111 | 0.0525 |
| `metal0-rough010` | edge | 0.0089 | 0.0137 | 0.0444 |
| `metal0-rough050` | interior | 0.0073 | 0.0101 | 0.0421 |
| `metal0-rough050` | edge | 0.0078 | 0.0097 | 0.2175 |
| `metal0-rough090` | interior | 0.0077 | 0.0097 | 0.0436 |
| `metal0-rough090` | edge | 0.0064 | 0.0089 | 0.0827 |
| `normal-ridges` | interior | 0.0079 | 0.0107 | 0.0744 |
| `normal-ridges` | edge | 0.0082 | 0.0098 | 0.2541 |
| `height-stripes` | interior | 0.0078 | 0.0102 | 0.0602 |
| `height-stripes` | edge | 0.0095 | 0.0096 | 0.1945 |
| `emission` | interior | 0.0073 | 0.0101 | 0.0421 |
| `emission` | edge | 0.0078 | 0.0097 | 0.2175 |
| `opacity-stripes` | interior | 0.0073 | 0.0101 | 0.0421 |
| `opacity-stripes` | edge | 0.0078 | 0.0097 | 0.2175 |
| `plane-mid-grey` | interior | 0.0074 | 0.0102 | 0.0515 |
| `plane-mid-grey` | edge | 0.0066 | 0.0118 | 0.0385 |
| `cube-mid-grey` | interior | 0.0075 | 0.0104 | 0.0462 |
| `cube-mid-grey` | edge | 0.0065 | 0.0096 | 0.1674 |
| `neutral-grey-diffuse--ref-match-000` | interior | 0.0051 | 0.0060 | 0.0364 |
| `neutral-grey-diffuse--ref-match-000` | edge | 0.0044 | 0.0050 | 0.0156 |
| `neutral-grey-diffuse--ref-match-180` | interior | 0.0018 | 0.0055 | 0.0150 |
| `neutral-grey-diffuse--ref-match-180` | edge | 0.0044 | 0.0049 | 0.0163 |
| `neutral-reflective--ref-match-000` | interior | 0.0000 | 0.0003 | 0.0154 |
| `neutral-reflective--ref-match-000` | edge | 0.0036 | 0.0040 | 0.0142 |
| `neutral-reflective--ref-match-180` | interior | 0.0000 | 0.0003 | 0.0153 |
| `neutral-reflective--ref-match-180` | edge | 0.0035 | 0.0040 | 0.0177 |
| `cube-saturated--ref-match-000` | interior | 0.0066 | 0.0076 | 0.0500 |
| `cube-saturated--ref-match-000` | edge | 0.0049 | 0.0051 | 0.0486 |
| `cube-saturated--ref-match-180` | interior | 0.0026 | 0.0035 | 0.0129 |
| `cube-saturated--ref-match-180` | edge | 0.0045 | 0.0051 | 0.0447 |
<!-- flip:end -->

## 4. First lobe fits (`parity/semantics/iray.json`)

Variants and constants (task item 2.4; decisions 050 and 051). Every entry of `parity/semantics/iray.json` cites approved public sources and is `calibrated`: a fitted model with its residuals inline, a candidate exception at most, never a pass. The support is unequal: the display encoding and the environment orientation are tight, the metal lobe is close, the dielectric, the bump and the filter are first guesses. The residuals may come from the lobes, from the environment handling or from the geometry; the fits do not tell these apart.

- **Metal.** GGX with alpha = roughness^2, height-correlated Smith masking, Schlick Fresnel with F0 = base colour, plus an albedo-based multiple-scattering lobe tinted by F0 (the form of MDL's `multiscatter_tint`). Single scattering leaves the roughness-0.9 metal 1.8 times too dark (linear); Kulla-Conty or Turquin compensation still 1.25 times; the F0-tinted lobe brings every metal roughness within about 0.3%.
- **Dielectric.** Schlick Fresnel for IOR 1.5, Lambert diffuse, layering by (1 - E_s(mu_o))(1 - E_s(mu_i)) without renormalisation, and a multiple-scattering lobe tinted by F0 = 0.04. IOR 1.3 to 1.55, Burley diffuse and the other layerings score worse. The low- and mid-roughness goldens keep biases of -510 to +573 codes, the saturated sphere's specular-dominated green and blue channels are too bright, and the ref_match grey sphere changes sign between the two views (-346 at 0 degrees, +220 at 180): the dielectric is not reproduced, an open question for phase3.5.
- **Environment.** Orientation fitted on the mirror sphere (u = frac(atan2(-x, z) / 2 pi + 1/4 + rotation / 360)); one global intensity scale 1.0192, a nuisance constant that absorbs model error. It is not Painter's environment intensity (the pipeline's exposure is 0), and Phase 3 re-fits it.
- **Camera and filter.** A one-pixel box filter beats Gaussians of 0.3 to 0.8 pixels on the edge band of three goldens.
- **Perturbations.** Normal map in the UV-derivative tangent frame; height as bump with strength 0.5 (per unit height per texel of the 256-pixel bitmap); where a perturbed normal faces away from the viewer the interpolated normal is kept. Residuals -529 and -148 codes.
- **Ignored channels.** Emission and opacity render exactly as `metal0-rough050`, as the default shader prescribes.
- **Glossy-fit risk (decision 046).** Without the old bright-patch environment, the glossy lobes are constrained by Studio White Soft and the ref_match HDRI only, and the HDRI is achromatic. The distribution's shape near the specular peak (roughness 0.1 and the mirror) rests on the soft-box edges of these two environments; the roughness mapping alpha = roughness^2 won over alpha = roughness by a wide margin, but a lobe whose tail differs at grazing angles, or a colour-dependent effect, would not be detected by them. Production references with sharper lights are where Phase 3 must check it.

Ranking of the best combinations (score: RMS of 64 x 64-pixel block means against k*S on the fit half, in codes):

<!-- ranking:begin -->
800 metal x dielectric combinations scored; chosen environment scale 1.0192.

| Roughness map | Metal multiscatter | Dielectric Fresnel | Diffuse | Layering | Dielectric multiscatter | Score at scale 1 | Fitted scale | Score |
|---|---|---|---|---|---|---|---|---|
| squared | tint | schlick | lambert | albedo_oi_raw | tint_f0 | 684 | 1.0192 | 610 |
| squared | tint | schlick | lambert | albedo_oi | tint_f0 | 704 | 0.9851 | 658 |
| squared | tint | schlick | lambert | albedo_o | tint_f0 | 715 | 0.9863 | 678 |
| squared | tint | exact | lambert | albedo_oi_raw | tint_f0 | 759 | 1.0184 | 694 |
| squared | tint | exact | lambert | albedo_oi | tint_f0 | 786 | 0.9827 | 729 |
| squared | tint | exact | lambert | albedo_o | tint_f0 | 802 | 0.9837 | 754 |
| squared | tint | schlick | lambert | albedo_oi_raw | tint | 777 | 1.0035 | 775 |
| squared | tint | schlick | lambert | albedo_oi | kulla_conty | 824 | 1.0010 | 824 |
| squared | tint | schlick | lambert | albedo_oi | turquin | 836 | 1.0022 | 835 |
| squared | tint | schlick | lambert | albedo_o | kulla_conty | 838 | 1.0022 | 837 |
<!-- ranking:end -->

Residuals of the chosen model at 256 samples against Iray (prototype minus reference, 16-bit codes; the fit goldens on their held-out chessboard half, the others whole):

<!-- fits:begin -->
| Golden | Pixels used | Pixels | Mean signed vs k*S ± se | Per channel (R / G / B) | Mean abs | p99 abs | rms | Mean signed vs S1 / S2 |
|---|---|---|---|---|---|---|---|---|
| `neutral-reflective` | chessboard half | 1856 | +190 ± 5 | +190 / +190 / +189 | 190 | 360 | 224 | +190 / +189 |
| `metal1-rough010` | chessboard half | 1856 | +30 ± 4 | +31 / +31 / +30 | 80 | 518 | 135 | +33 / +33 |
| `metal1-rough050` | chessboard half | 1856 | +37 ± 6 | +39 / +38 / +35 | 117 | 582 | 170 | +43 / +43 |
| `metal1-rough090` | chessboard half | 1856 | +4 ± 11 | +6 / +4 / +1 | 184 | 821 | 251 | +8 / +8 |
| `neutral-grey-diffuse` | chessboard half | 1856 | -360 ± 11 | -360 / -358 / -364 | 410 | 1146 | 486 | -362 / -362 |
| `base-light-grey` | chessboard half | 1856 | -201 ± 51 | -198 / -198 / -207 | 700 | 4048 | 978 | -198 / -198 |
| `base-saturated` | chessboard half | 1856 | +573 ± 33 | -195 / +878 / +1036 | 874 | 3099 | 1056 | +580 / +580 |
| `metal0-rough010` | chessboard half | 1856 | -510 ± 10 | -511 / -507 / -512 | 529 | 1301 | 609 | -506 / -506 |
| `metal0-rough050` | chessboard half | 1856 | -55 ± 39 | -52 / -52 / -60 | 493 | 3085 | 729 | -49 / -49 |
| `metal0-rough090` | chessboard half | 1856 | -335 ± 17 | -334 / -332 / -339 | 442 | 1255 | 526 | -336 / -336 |
| `normal-ridges` | whole golden | 3718 | -529 ± 44 | -531 / -526 / -530 | 1030 | 5081 | 1383 | -526 / -526 |
| `height-stripes` | whole golden | 3718 | -148 ± 41 | -146 / -146 / -152 | 867 | 7659 | 1693 | -144 / -144 |
| `emission` | whole golden | 3718 | -47 ± 28 | -44 / -44 / -51 | 501 | 3108 | 749 | -42 / -42 |
| `opacity-stripes` | whole golden | 3718 | -47 ± 28 | -44 / -44 / -51 | 501 | 3108 | 749 | -42 / -42 |
| `plane-mid-grey` | whole golden | 4516 | -513 ± 4 | -517 / -510 / -513 | 519 | 1146 | 581 | -514 / -514 |
| `cube-mid-grey` | whole golden | 3186 | -60 ± 18 | -59 / -58 / -63 | 389 | 1162 | 565 | -58 / -58 |
| `neutral-grey-diffuse--ref-match-000` | whole golden | 3718 | -346 ± 6 | -346 / -346 / -346 | 362 | 765 | 393 | -346 / -346 |
| `neutral-grey-diffuse--ref-match-180` | whole golden | 3718 | +220 ± 29 | +220 / +220 / +220 | 360 | 4101 | 826 | +221 / +221 |
| `neutral-reflective--ref-match-000` | whole golden | 3718 | +94 ± 1 | +94 / +94 / +94 | 94 | 314 | 107 | +94 / +94 |
| `neutral-reflective--ref-match-180` | whole golden | 3718 | +92 ± 1 | +92 / +92 / +92 | 92 | 321 | 103 | +92 / +92 |
| `cube-saturated--ref-match-000` | whole golden | 3186 | +528 ± 8 | +55 / +684 / +845 | 640 | 1345 | 714 | +529 / +529 |
| `cube-saturated--ref-match-180` | whole golden | 3186 | +928 ± 60 | +672 / +1056 / +1057 | 967 | 6279 | 2000 | +938 / +938 |
<!-- fits:end -->

Pixel filter (edge band, 256 samples) and the bump strength of `height-stripes`:

<!-- filter:begin -->
| Golden | Filter | Edge mean abs | Edge rms | Edge mean signed |
|---|---|---|---|---|
| `neutral-grey-diffuse` | box | 459 | 740 | 175 |
| `neutral-grey-diffuse` | gaussian sigma 0.3 px | 468 | 747 | 173 |
| `neutral-grey-diffuse` | gaussian sigma 0.5 px | 553 | 824 | 215 |
| `neutral-grey-diffuse` | gaussian sigma 0.8 px | 793 | 1135 | 265 |
| `plane-mid-grey` | box | 316 | 474 | -259 |
| `plane-mid-grey` | gaussian sigma 0.3 px | 357 | 532 | -279 |
| `plane-mid-grey` | gaussian sigma 0.5 px | 597 | 866 | -191 |
| `plane-mid-grey` | gaussian sigma 0.8 px | 1117 | 1572 | -84 |
| `cube-mid-grey` | box | 942 | 1994 | 857 |
| `cube-mid-grey` | gaussian sigma 0.3 px | 949 | 1994 | 857 |
| `cube-mid-grey` | gaussian sigma 0.5 px | 1051 | 1973 | 916 |
| `cube-mid-grey` | gaussian sigma 0.8 px | 1274 | 2093 | 994 |

| Bump strength | 0.00 | 0.25 | 0.50 | 0.75 | 1.00 | 1.50 | 2.00 |
|---|---|---|---|---|---|---|---|
| rms vs k*S (fit half) | 2351 | 2001 | 1874 | 1987 | 2142 | 2479 | 2576 |
<!-- filter:end -->

## 5. Transport evidence

Item 2.5 (decision 051). On the fixed pipeline's fixtures no light-carrying path has a second vertex: each is one convex mesh (the plane a single planar facet set) under an infinite environment, with no ground and the caustic sampler pinned off.

- **Path depth and below-facet directions.** With below-facet directions absorbed (the prototype's rule), the depth-1 and depth-8 renders are bit-identical on every golden tested. Only if such directions pass through the surface ("trace") do paths of two or more vertices carry light, and then only on the perturbed fixtures (normal ridges +7.5 codes mean, 936 of 3,718 sampled pixels; height stripes 68 pixels). This shows the fixtures carry no depth signal; it does not reveal Iray's settings. The maximum path depth and caustic paths are not identifiable from these references: Phase 3 keeps the maximum depth an authored constant and the below-facet rule a documented choice, to be tested where concavity, interreflection or caustics occur (production references).
- **Spectral versus RGB.** A sensitivity of the prototype under one upsampling, not evidence about Iray: per-wavelength products of environment and base colour (Jakob-Hanika upsampling, Wyman et al. colour-matching functions, equal-energy white) change the saturated sphere under Studio White Soft by -1 / -113 / -29 codes (R / G / B), moving its +580 residual to +532. The ref_match HDRI is achromatic (p99 chroma deviation below 0.001), so this formulation cannot change any ref_match render. Nothing here asks for spectral transport; RGB transport stays.

<!-- transport:begin -->
| Golden | Run | Mean signed vs absorb/8 | Max abs vs absorb/8 | Differing pixels | Mean signed vs k*S ± se | rms vs k*S |
|---|---|---|---|---|---|---|
| `height-stripes` | absorb_depth1 | +0.0 | 0 | 0 | -148 ± 41 | 1693 |
| `height-stripes` | absorb_depth8 | +0.0 | 0 | 0 | -148 ± 41 | 1693 |
| `height-stripes` | trace_depth1 | +0.0 | 0 | 0 | -148 ± 41 | 1693 |
| `height-stripes` | trace_depth8 | +0.3 | 110 | 68 | -148 ± 41 | 1693 |
| `neutral-grey-diffuse` | absorb_depth1 | +0.0 | 0 | 0 | -357 ± 8 | 485 |
| `neutral-grey-diffuse` | absorb_depth8 | +0.0 | 0 | 0 | -357 ± 8 | 485 |
| `neutral-grey-diffuse` | trace_depth1 | +0.0 | 0 | 0 | -357 ± 8 | 485 |
| `neutral-grey-diffuse` | trace_depth8 | +0.0 | 10 | 1 | -357 ± 8 | 485 |
| `normal-ridges` | absorb_depth1 | +0.0 | 0 | 0 | -529 ± 44 | 1383 |
| `normal-ridges` | absorb_depth8 | +0.0 | 0 | 0 | -529 ± 44 | 1383 |
| `normal-ridges` | trace_depth1 | +0.0 | 0 | 0 | -529 ± 44 | 1383 |
| `normal-ridges` | trace_depth8 | +7.5 | 915 | 936 | -522 ± 44 | 1375 |
| `plane-mid-grey` | absorb_depth1 | +0.0 | 0 | 0 | -513 ± 4 | 581 |
| `plane-mid-grey` | absorb_depth8 | +0.0 | 0 | 0 | -513 ± 4 | 581 |
| `plane-mid-grey` | trace_depth1 | +0.0 | 0 | 0 | -513 ± 4 | 581 |
| `plane-mid-grey` | trace_depth8 | +0.0 | 0 | 0 | -513 ± 4 | 581 |

| Golden | Base colour (linear) | Env chroma spread (p99) | Spectral - RGB per channel | Max abs | RGB vs k*S | Spectral vs k*S | Upsampling round trip |
|---|---|---|---|---|---|---|---|
| `base-saturated` | 0.6038 / 0.0331 / 0.0103 | 0.092 | -1.2 / -112.8 / -29.3 | 505 | +580 | +532 | 4.4e-16 |
| `cube-saturated--ref-match-000` | 0.6038 / 0.0331 / 0.0103 | 0.000 | +0.0 / +0.0 / +0.0 | 0 | +528 | +528 | 5.6e-17 |
| `cube-saturated--ref-match-180` | 0.6038 / 0.0331 / 0.0103 | 0.000 | +0.0 / +0.0 / +0.0 | 0 | +928 | +928 | 1.4e-17 |
<!-- transport:end -->

## 6. Defect detection (item 3.2)

Each defect is rendered at 256 samples on the golden's 256 x 256 crop and compared with Iray's k*S render exactly as the fitted model is. A defect is outside the floor when its mean signed delta moves by more than three combined standard errors of Iray's (b) and the prototype's (c) on the crop, or when its 8x-downsampled mean |delta| exceeds the fitted model's by as much. All four defects are outside in the interior; the missing normal map is inside in the 2-pixel edge band. Caveat (decision 051): the fitted model itself is hundreds of codes from k*S (§4), so these verdicts grade the shift a defect causes against a misfit baseline. They show sensitivity to these perturbations, not false-positive rates or detection on unseen fixtures, and the thresholds are re-derived once the lobe residuals close. None of the defect goldens has a face-confined (a).

<!-- defects:begin -->
| Defect | Golden | Region | Fitted vs k*S ± se | Defect vs k*S ± se | Mean signed shift | Combined se (b, c) | Fitted 8x mean abs | Defect 8x mean abs | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| environment_rotation | `cube-saturated--ref-match-000` | interior | 555.0 ± 9.3 | 445.6 ± 18.5 | -109.4 | 0.70 | 546.8 | 805.8 | outside |
| environment_rotation | `cube-saturated--ref-match-000` | edge | 537.4 ± 52.6 | 1209.9 ± 117.9 | 672.5 | 2.67 | - | - | outside |
| missing_channel | `normal-ridges` | interior | -507.1 ± 89.1 | 608.2 ± 129.4 | 1115.4 | 1.48 | 799.2 | 1319.0 | outside |
| missing_channel | `normal-ridges` | edge | 3447.9 ± 364.2 | 3469.2 ± 353.6 | 21.3 | 12.64 | - | - | inside |
| roughness_offset | `metal1-rough050` | interior | 31.3 ± 2.2 | 1761.6 ± 172.1 | 1730.4 | 0.72 | 36.1 | 2227.3 | outside |
| roughness_offset | `metal1-rough050` | edge | 50.8 ± 33.7 | -619.5 ± 141.7 | -670.3 | 8.36 | - | - | outside |
| wrong_lobe | `metal0-rough050` | interior | -105.3 ± 52.9 | 1688.1 ± 77.3 | 1793.4 | 1.47 | 351.6 | 1614.5 | outside |
| wrong_lobe | `metal0-rough050` | edge | 2843.5 ± 278.0 | 4660.2 ± 489.3 | 1816.7 | 11.34 | - | - | outside |
<!-- defects:end -->

## 7. Repeatability (item 3.3)

<!-- repeatability:begin -->
| Pixels | Samples | Run 1 SHA-256 | Run 2 SHA-256 | Identical |
|---|---|---|---|---|
| 200 | 64 | `a3ed73b4d56470fa223089d51dbdca4d337dd9a535797784e194d27acdd0d97e` | `a3ed73b4d56470fa223089d51dbdca4d337dd9a535797784e194d27acdd0d97e` | yes |
<!-- repeatability:end -->

## 8. Ray-tracing support of the owner's GPU (item 2.8)

<!-- probes:begin -->
`UzPainter.exe selftest` started 2026-10-11T14:55:19Z, result `passed`; Windows 10 Pro build 10.0.26200.9457, AMD Ryzen 9 7950X3D 16-Core Processor, Zig 0.15.2 Debug.

| Probe | Adapter | Driver | Check | Result | Detail |
|---|---|---|---|---|---|
| `dx12-ray-query` | NVIDIA GeForce RTX 4090 | 32.0.16.1714 | D3D12_FEATURE_D3D12_OPTIONS5 RaytracingTier >= Tier 1.1 | passed | Tier 1.2 |
| `dx12-ray-query` | NVIDIA GeForce RTX 4090 | 32.0.16.1714 | D3D12_FEATURE_SHADER_MODEL HighestShaderModel >= 6.6 | passed | 6.9 |
| `dx12-ray-query` | NVIDIA GeForce RTX 4090 | 32.0.16.1714 | DX12SupportsInlineRayQuery (UZP-MOD-004) | passed | true |
| `vulkan-ray-query` | NVIDIA GeForce RTX 4090 | NVIDIA 617.14 | extension VK_KHR_acceleration_structure | passed | exposed |
| `vulkan-ray-query` | NVIDIA GeForce RTX 4090 | NVIDIA 617.14 | extension VK_KHR_deferred_host_operations | passed | exposed |
| `vulkan-ray-query` | NVIDIA GeForce RTX 4090 | NVIDIA 617.14 | extension VK_KHR_ray_query | passed | exposed |
| `vulkan-ray-query` | NVIDIA GeForce RTX 4090 | NVIDIA 617.14 | feature accelerationStructure | passed | true |
| `vulkan-ray-query` | NVIDIA GeForce RTX 4090 | NVIDIA 617.14 | feature rayQuery | passed | true |
<!-- probes:end -->

The fresh run agrees with `toolchain-probes.md` of 2026-10-10 (same adapter and drivers): DXR Tier 1.2 (at least Tier 1.1 is required), Shader Model 6.9, inline ray queries supported on DX12; `VK_KHR_acceleration_structure`, `VK_KHR_deferred_host_operations` and `VK_KHR_ray_query` exposed with the `accelerationStructure` and `rayQuery` features on Vulkan. The executable was built from commit `9e2c6381a4943eaa51f1c0b5c41c0a9be307bf69` (SHA-256 `83c3ac942b506674236400deba1f32882b9d7824d5f1ecf367110b49de96d6b4`).

## 9. Open items

1. **Cause of the face-confined run-to-run difference** (owner: the coordinator; 18 references, about 45 minutes of Painter time; decision 052). Capture request, all under procedure `iray-capture/1`, S = 256, no k*S render needed:
   - `plane-mid-grey` and `cube-mid-grey` turned by +1 degree and by -1 degree about +Y (no visible facet with a zero x component), two `separate_session` references each (8). The hypothesis predicts (a) at the rounding level for all four.
   - `plane-mid-grey` twice more in separate sessions, and twice in one Painter session (Save Render after each Done, no relaunch) (4): is the decorrelation in every pair, and per session or per render?
   - `cube-saturated--ref-match-180` twice more in separate sessions (2): is the 180-degree view immune, or was the pair a coincidence?
   - `plane-mid-grey` under `ref_match` at rotation 0 and at 180, two `separate_session` references each (4): this varies the environment's symmetry about the mirror on the same facet and tests the mechanism, not only the trigger.
   The new fixtures are rows of the reference table (`tools/parity/render_procedure/references.py`) with their manifests; `stability.face_regions` and `stability.half_steps` measure them.
2. **The shipped tracer's term (c)** (owner: phase3.6 item 2.3): `noise.pair_statistics` on `painter_iray` renders at two seeds and k*S, as §3 does for the prototype.
3. **The dielectric lobe and the view-dependent diffuse residual** (owner: phase3.5): the first fits leave biases of hundreds of codes (§4).

## 10. Commands

- `python -m tools.parity.render_fits measure --work <dir>` reads the store, renders the prototype (cached under `<dir>/renders`) and writes `<dir>/results.json`.
- `python -m tools.parity.render_fits write --work <dir> --selftest-report <dir>/run/selftest-report.json` writes `parity/semantics/iray.json` and the generated blocks of this report.
- `UzPainter.exe selftest --out-dir <dir>/run` records the probes of §8.
- `python -m tools.parity.guard` checks that no render, crop or difference map is in the repository.
