# Mesh-map generator calibration, 2026-11-09 (phase3.2_proc-generator-families items 2.5, 2.7, 3.1)

Painter `12.2.0+js-api.1.1.20`, Legacy colour management, one session under the Assets3D Painter lock (seq 2354 to 2359). Requests: `parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/requests/phase3/proc-generators/` (`python -m tools.parity.proc_generators write`); every golden recorded twice (r1; r2 after save and reopen), admitted, verified (`python -m tools.parity.store verify`) and its inbox run deleted. Numbers only below: every map is a private oracle in the owner's store.

## 1. How a generator golden is recorded

One Painter project per mesh and resolution (`tools/parity/proc_generators/requests.py`): up to eight cases, each a white Raw fill on its own L32F User channel over a black base fill, under a black mask holding the generator with the case's parameters. The bake is the last state step (low as high, `OutputSize` the resolution, `DilationWidth` 0 for the batch goldens): a bake leaves Painter's UI in its Baking mode, which has no active stack, so the layer steps come first and the generators recompute from the baked maps. The User maps and the baked mesh maps are exported as OpenEXR 32f, padding `passthrough`.

Compared texels (`tools/parity/proc_generators/coverage.py`): the texels the World Space Normals bake covers whose 3 x 3 neighbourhood it also covers. Outside them the two recordings of a golden differ (export padding is undefined under `passthrough`, and on the hat at 4096 one island-edge texel differs), so the batch stores each oracle with those texels set to 0, and the candidate reproduces the mask from its World Space Normals input (`tools/parity/proc_generators/batch.py`). On every compared texel r1 equals r2 in all ten AO goldens.

Hat v6 low is lost (decision 260); the delivered hat v8 low mesh (`10-Chapeu/Export/10-Chapeu-v8.fbx`, SHA-256 `4b860d91…`, git-ignored in Assets3D and now kept in the private store as an input) stands in for the garment-class mesh. The held-out mesh is the Tier 2b bevelled cube with its knob.

## 2. Ambient Occlusion (`generator/occlusion@2`)

Declared before calibration and pinned in commit `20ce70bf` (`parity/manifests/phase3/proc-cert/generator__occlusion@2/`): `ao_invert` and `global_invert` in {0, 1}, every other parameter at Painter's default and not editable, the single listed seed 0 (the generator has no `$randomseed`), the AO and World Space Normals maps as f32 Raw, one UV tile, output f32 linear mono at 1024/2048/4096. §6 matrix: sphere, rounded cube, hat v8 x {1024, 2048, 4096} x {defaults, the Tunic v10 recipe (`global_invert` 1, the "Cavidades - AO high" mask of `18-Tunica/report.json`), `ao_invert` 1, both inverts}: 36 calibration cases. Held-out: knob cube at 2048, the same four sets (4 cases).

Certification (`python -m tools.parity.proc_cert certify … --fitter tools.parity.proc_generators.occlusion_candidate:fit`, report `parity/reports/phase3/proc-cert/generator__occlusion@2/fe4ee8f2e713b52a.json`, held-out set spent on candidate `be93c9a9…` in `parity/reports/phase3/held-out-ledger.json`): **outcome fail, parity status `calibrated`**.

| Set | Calibration (9 cases each) | Held-out (1 case each) |
|---|---|---|
| defaults | 9 exact | exact |
| both inverts | 9 exact | exact |
| `global_invert` 1 (Tunic recipe) | 3 exact (sphere), 6 residual | residual |
| `ao_invert` 1 | 3 exact (sphere), 6 residual | residual |

Residual cases, affected texels of the case's texels (unit: ULP of float32; every other compared texel exact):

| Mesh | 1024 | 2048 | 4096 |
|---|---|---|---|
| rounded cube | 6, max 128 | 14, max 128 | 58, max 256 |
| hat v8 | 35 674, max 256 | 144 047, max 256 | 581 952, max 256 |
| knob cube (held-out) | | 7 498, max 128 | |

Pooled: max 256 ULP, mean 0.039 ULP, p99 0. The largest ULP counts are on outputs near 0, where an ULP is tiny: the absolute difference is at most 4.5e-8, under 1/300 of a 16-bit code.

**Model (fitted on the calibration set).** With I(v) the float32 subtraction 1 - v: defaults and both inverts give I(I(ao)) on every compared texel of every case (not `ao` itself: the generator computes the occlusion and inverts it back). One invert gives Painter's 1 - x(k), a deterministic function of the AO map's 16-bit code k: over the 9 913 515 compared texels of the hat at 4096 the 65 534 codes present never give two outputs. x(k) is a float32 of k / 65535 within 0.75 ULP of it, but not the correctly rounded one: for k >= 32768, where 1 - x is exact, it differs from round-to-nearest on 5 461 of 32 767 codes. Tried and refuted, on all 65 534 codes: round to nearest, toward zero, k x float32(1 / 65535), k x the recording GPU's measured reciprocal of 65535 (`hw-rcp`), the fixed-point forms (k x 65537 + b) / 2^32 and k x 2^24 / 65535 with every bias in [-300, 300], a 16-bit invert (65535 - k) / 65535, a binary16 intermediate, and lerp/blend forms of the invert. The rounding threshold on the low byte of k moves irregularly with the high byte. The candidate keeps the plain I(ao) for one invert.

**Separating evidence for the owner.** The single-invert residual is a one-ULP difference in how Painter turns the 16-bit AO code into float32 before one subtraction; on two inverts it cancels. Closing it needs x(k) for every code. Two routes, neither taken here: (a) a UzmiGames measurement of the recording GPU's UNORM16 sampling (as `src/evaluator/tables/hw-*.zlib` measure its reciprocal and roots), if that is where x(k) comes from; (b) a decision-032 exception for the two single-invert sets (absolute residual at most 4.5e-8). The defaults and both-inverts sets are exact on calibration and held-out, but a domain without the single invert would drop the Tunic recipe set the §6 matrix requires.

Disclosed: before the held-out list was pinned, one calibration golden (sphere at 1024) was opened to check the recording procedure. The batch builder read the held-out oracles only to check r1 = r2 and apply the value-independent coverage mask; no fit read them.

## 3. The other seven generators

A diagnostic golden (`diagnostic-mixed-rounded-cube-1024`, never a calibration or held-out case) records Curvature, Mask Editor, Dirt, Metal Edge Wear and Mask Builder - Legacy at Painter's defaults on the rounded cube at 1024, the seeded ones also at seed 1. Over its 608 972 compared texels (the feasibility study's UV domain eroded by one) r1 equals r2.

| Generator | Default output | Separating evidence | Status |
|---|---|---|---|
| Dirt | seeded grunge | seed 1 changes 604 417 texels (max 0.669) | release gap |
| Metal Edge Wear | seeded grunge | seed 1 changes 30 115 texels (max 1.0); phase0.6 found 1 of 8 cases equal | release gap |
| Mask Builder - Legacy | seeded grunge | seed 1 changes 122 972 texels (max 0.849) | release gap |
| Curvature | multi-scale curvature (`curvature_fine` … `curvature_huge`) | 604 583 texel pairs with the same curvature-map value differ by up to 0.0189: not a per-texel function of its input | release gap |
| Mask Editor | 0.5 x the Curvature section at defaults | same as Curvature (max 0.5) | release gap |
| Position | per-texel at defaults | none recorded: no Assets3D recipe uses it, and the harness requires a recipe parameter set in the §6 matrix (decision 303) | release gap, not batched |
| World Space Normals | per-texel at defaults | as Position | release gap, not batched |

A clean-room noise does not reproduce Painter's seeded grunge texel for texel (phase0.6 report §1), and the multi-scale curvature filter is not described by any public source; both stay release gaps until a decision changes the route. Position and World Space Normals have the per-texel structure the AO generator has, so the same 16-bit conversion is likely to decide them; a batch for them needs a recipe set, which no recipe provides.
