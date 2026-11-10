# Grunge diagnostic evidence, 2026-11-10 (phase3.2_proc-grunge-families items 2.2, 2.4)

Painter `12.2.0+js-api.1.1.20`, Legacy colour management, one session under the Assets3D Painter lock (seq 2372 to 2373). Requests: `parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/requests/phase3/proc-grunges/` (`python -m tools.parity.proc_grunges write`, tooling committed in `05fc6701` before the session). Every golden was recorded twice (r1; r2 after save and reopen), admitted, verified (`python -m tools.parity.store verify`), and its inbox run deleted. Numbers only below: every map and readback is a private oracle in the owner's store. Numbers by `python -m tools.parity.proc_grunges.evidence`.

These goldens are **diagnostic**. They are never a calibration or held-out case of any batch.

## 1. How a grunge golden is recorded

One Painter project on the authored plane (`parity/fixtures/meshes/plane.obj`, UVs 0..1, one tile) per resolution, with up to eight cases (`tools/parity/proc_grunges/requests.py`). Each case is a white Raw fill on its own L32F User channel, over a black base fill, under a black mask. The mask holds a fill effect whose source is the grunge, at the fill's default UV projection. So the User channel holds the grunge's mask value. No mesh map is baked. The User maps are exported as OpenEXR 32f, padding `passthrough`.

The resources are the Painter 12.2.0 shelf versions found by the starter-asset survey of 2026-11-08 (private, SHA-256 `68d59fea…`). The hat recipe recorded the "ratio" variants of `bnw_spots_3`, `dirt_1`, `grunge_map_009` and `grunge_map_012` from its own project. The 12.2.0 shelf lists the plain ones, which were recorded here.

Cases: seeds 1 and 2 at 1024 and seed 1 at 2048 for every grunge with a seed. Two of the first goldens were refused (`$randomseed` not found): `grunge/dirt-large` lists no seed. Their requests are kept unchanged (`goldens.REFUSED`). A second wave recorded the first four grunges at their defaults, seed unset, at 1024 and 2048, and the seed cases of the three of them that list a seed. Eleven goldens were admitted.

Parameter discovery (item 2.2): `02-parameter-discovery.md`, from the readbacks of the same goldens.

## 2. Results (1024 x 1024 = 1 048 576 texels per case)

Columns:
- r1 ≠ r2: texels where the two recordings of the grunge's cases differ.
- Seed 1 vs 2: texels that differ, the largest difference, and the texels still different after the best cyclic translation of seed 2 onto seed 1 (phase-correlation peak).
- Default vs 1: the same count between the default seed (0) and seed 1, where recorded.
- Distinct: distinct values at 1024.
- 2048 sample: the fewest texels where the 1024 output differs from one of the four 2 x 2 samplings of the 2048 output.
- 2 x 2 mean: the largest difference between the 1024 output and the 2 x 2 mean of the 2048 output.

| Asset | r1 ≠ r2 | Seed 1 vs 2: differing | max | after translation | Default vs 1 | Distinct | 2048 sample | 2 x 2 mean |
|---|---|---|---|---|---|---|---|---|
| `grunge/rock` | 0 | 0 | 0 | 0 | 0 | 51 488 | 1 038 935 | 0.120 |
| `grunge/stone-details` | 0 | 0 | 0 | 0 | 0 | 61 152 | 1 047 631 | 0.385 |
| `grunge/dirt-large` | 0 | no seed parameter | | | | 1 016 | 1 036 167 | 7.7e-6 |
| `grunge/dirt-spots-small` | 0 | 341 133 | 0.959 | 341 598 | 338 008 | 44 989 | 278 524 | 0.027 |
| `grunge/spots-bw-a` | 0 | 1 048 548 | 1.000 | 1 048 539 | | 56 485 | 1 047 331 | 0.106 |
| `grunge/spots-bw-b` | 0 | 1 048 535 | 0.780 | 1 048 540 | | 46 752 | 1 047 835 | 0.037 |
| `grunge/dirt-a` | 0 | 976 977 | 1.000 | 977 740 | | 48 742 | 717 729 | 0.280 |
| `grunge/scratches-fine` | 0 | 1 046 851 | 0.391 | 1 046 713 | | 20 840 | 929 236 | 0.185 |
| `grunge/scratches` | 0 | 0 | 0 | 0 | | 43 017 | 1 047 474 | 0.181 |
| `grunge/scratches-dirty` | 0 | 1 048 466 | 0.357 | 1 048 453 | | 21 987 | 1 048 287 | 0.202 |
| `grunge/rust-fine` | 0 | 1 048 548 | 0.998 | 1 048 550 | | 58 024 | 1 048 207 | 0.742 |
| `grunge/humidity` | 0 | 999 500 | 0.694 | 798 362 | | 160 | 827 214 | 0.012 |
| `grunge/map-a` | 0 | 891 329 | 1.000 | 891 329 | | 32 768 | 747 154 | 1.000 |
| `grunge/map-b` | 0 | 615 565 | 1.000 | 615 908 | | 30 307 | 458 773 | 1.000 |
| `grunge/spots-soft` | 0 | 1 047 517 | 1.000 | 1 047 672 | | 36 740 | 1 015 656 | 0.031 |
| `grunge/cracks-leather` | 0 | 312 783 | 0.996 | 314 278 | | 53 503 | 284 706 | 0.990 |
| `grunge/linen` | 0 | 1 041 903 | 0.409 | 1 043 039 | | 421 | 1 035 535 | 0.243 |

Every recording is stable: r1 equals r2 on every texel of every case.

## 3. What the evidence separates

**Fixed textures (4 assets).** These outputs depend on no seed, so their content is fixed:
- `grunge/rock`, `grunge/stone-details` and `grunge/scratches` list a `$randomseed`, but seeds 0, 1 and 2 give the same output on every texel.
- `grunge/dirt-large` has no seed. Its 1024 output equals the 2 x 2 mean of its 2048 output within 7.7e-6 on every texel, with only 1 016 distinct values: a fixed image, box-filtered between levels.

A texel-exact reimplementation of a fixed texture reproduces that texture's content. The clean room copies no asset bytes and never ships Adobe grunges (`docs/licensing-and-clean-room.md` §1 items 1 and 3, `05-procedural-content.md` §3). Their content is the asset, so no clean-room kernel can be exact, however long it is fitted.

**Seeded patterns (13 assets).** The seed changes between 30 % (`grunge/cracks-leather`, `grunge/dirt-spots-small`) and 100 % of the texels, by up to 1.0. The best cyclic translation of one seed onto the other leaves about as many texels different (at best 76 % of them, `grunge/humidity`), so a seed does not just move a fixed texture. The output is a function of the seed through the Substance engine's random number generator and each asset's graph. No public source describes either.

The clean-room route allows public literature plus black-box calibration of constants (`05-procedural-content.md` §3). It cannot reproduce an undocumented random sequence texel for texel. Recovering that sequence from Painter's outputs would reverse-engineer Adobe's engine, not fit a published kernel. This confirms, now for each of the 13, what the feasibility study found for the seeded grunge inside Metal Edge Wear (`parity/reports/phase0/procedural-feasibility.md` §1).

**No fitting time was spent.** The owner's throughput rule gives about 2 h of fitting per family. None of the six UzPainter pattern kinds (decision 331 §3) has a free parameter that could turn it into either class above: a fixed Adobe texture, or Adobe's seeded sequence. The time box would not change this outcome, so it was not used. No candidate exists, so no residual is offered as a candidate exception.

**Resolution.** For 16 assets the 1024 output is neither a 2 x 2 sampling nor the 2 x 2 mean of the 2048 output. Painter evaluates the graph at the output resolution. A future route would need a batch per resolution.

## 4. Consequences for the moved generators (item 2.7)

Dirt, Metal Edge Wear and Mask Builder - Legacy read Painter's seeded grunge at their defaults (decision 423 §4: seed 1 changes 604 417, 30 115 and 122 972 of 608 972 compared texels). They inherit the seeded-pattern blocker of §3, and stay release gaps with it.
