# 331. The grunge family: seventeen UzPainter assets from the recipes, six periodic pattern kinds over the primitive library, a whole-number tiling, UzPainter's own parameter names, a host-computed parameter block, and domains declared uncertified

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase3.2_proc-grunge-families

## Context

`phase3.2_proc-grunge-families` items 2.1, 2.3 and the domain half of 2.6, with test 3.2 and the DX12 half of test 3.3, can be built without Painter. Items 2.2 (parameter discovery through the `Property` API), 2.4 (calibration), 2.5 (Tier 2a manifests), 3.1 and the oracle half of 3.3 need Painter recordings or goldens, and stay open. Facts at the start (main `c477be55`):

- The seam, the HLSL host, the primitive library and the asset library exist (decisions 222, 303, 324). The filter families are declared uncertified (decision 328). No family is certified.
- The primitive library's noises are not periodic: their lattice indices are not wrapped.
- The recipes record grunges by Painter name. The body recipe records only a projection scale and a mask Levels per grunge. The hat recipe records each source's parameters and seed, read back through the documented API.
- The publication rule (`05-procedural-content.md` §3) keeps Adobe content out. Painter names stay out of the shipped library until an asset is `exact` (decision 324).

The coordinator's brief fixed the frame: the math comes from published sources only (decision 006), every status stays `unavailable`, no alias is registered, and no file outside the grunge files and their registration lines is changed while the generator families are built in parallel. No model panel ran. The forks below follow from those rules.

## Decision

Code: `src/procedural/grunges.{h,cpp}`. Records: `assets/procedural/records/grunge.*@1.json`. Inventory: `docs/analysis/proc-grunge-families/01-asset-inventory.md`. Tests: `tests/procedural/grunges_test.cpp` (`uzp-proc-grunge-tests`) and `tests/procedural/test_proc_grunge_families.py`.

1. **The inventory (item 2.1).**
   - Seventeen assets: the six grunges of the body recipe, the eleven grunge sources of the hat recipe (two of them shared with the body), `cracks_leather` and `fabric_linen`.
   - The body and hat recipes use no crack grunge. The cracks row is `cracks_leather`, used by the bracer v1 and belt v1 recipes.
   - `fabric_linen` is inventoried as the sash uses it: a single-channel thread mask. Its use as a full material belongs to `phase3.2_proc-material-families`.
   - Only the "ratio" variants of `bnw_spots_3`, `dirt_1` and the two grunge maps are recorded. Each gets one UzPainter asset.
   - A recipe's `tiling`, UV scale or triplanar scale is the fill's projection, not a parameter of the asset. The body's 3.5 is not a whole number, which confirms it.
2. **Names.** Each asset is `uzasset://grunge/<id>@1`, usage `PROCEDURAL`, with a UzPainter name ("UzPainter Rock Grunge", ...). The inventory names the Painter asset each alias will carry. The alias table stays empty.
3. **Six pattern kinds, one fixed configuration per asset.**
   - The kinds are fBm and ridged fBm of Perlin 2002 gradient noise on the z = 0 plane, spots, scratches and cracks on one Worley feature per cell, and a plain weave.
   - Each asset fixes a kind, its periods, octaves or layers, gain and kind constants, and an optional fBm break-up. These are UzPainter's design choices, not fitted to Painter. Calibration (item 2.4) may change them, but only before it starts, or with a new held-out set (decision 222).
   - The scratch directions and the spot radii come from a table in the parameter block.
4. **Tiling.**
   - Every lattice is periodic. A cell index is taken modulo the period, and every distance is computed from the fractional part of the coordinate. So the texture continued past its border is the texture itself, bit for bit.
   - The texel coordinate (x + 1/2) P / R is exact in float32 for every period and resolution of the domain. This is what makes the float computation periodic, and the tiling test checks it.
   - The `tiling` parameter is a whole number of repeats across the texture, from the set {1, ..., 8}. A fractional tiling would break the wrap, and Painter's own tiling semantics are not discovered yet.
5. **UzPainter's own parameters.**
   - Every asset has `balance`, `contrast`, `invert` and `tiling`. Some add `disorder` (spots), `rotation_variation` (scratches), `flip_horizontal` and `flip_vertical` (humidity), `hardness` and `shape` (cracks), or `tension_variation` (linen).
   - The inventory maps the recorded parameters onto these names by name only. A recorded parameter with no counterpart (`brush_pattern`, `random_mode`, `tile_ratio`, `rotate_by_45_degrees`) is outside the domain, so a request that carries it is refused. Nothing ignores it silently.
   - Item 2.2 revises the names, ranges and defaults before calibration starts.
6. **A host-computed parameter block.**
   - Every float the kernel needs is computed once on the host: the normalisations, 1 / (1 - 0.9 contrast), 1 / r^2, 1 / width^2, and the scratch directions' sines and cosines. The divisions and the Taylor series are computed in IEEE double, then rounded to float32.
   - So the kernel has no division and no transcendental, and every machine computes the same block.
   - The CPU reference (`GrungeTexel`) reads the same words as the kernel and mirrors it operation for operation, with flushed single operations and no contraction. DX12 equals it bit for bit.
   - The periodic noise helpers live in the grunge files and use the primitive library's `CellHash`, `SeedOffset`, `Fade2002`, `SqrtRn` and arithmetic. The shared library is left unchanged while the generator families are built beside it.
7. **Domains declared before calibration, uncertified (the domain half of item 2.6).**
   - Any 32-bit seed, because the recipes record arbitrary seeds. No image input.
   - The classes of the certification meshes (`sphere`, `bevelled-cube`, `garment`) on one UV tile.
   - Output: float32 linear mono at 1024, 2048 and 4096.
   - Every status is `unavailable` with no corpus. `s:uzpainter` lists the assets, and `assets list --parity` prints their domains.
   - The held-out reservation and its hash list come from the recording batch, so item 2.6 stays open.
8. **Not wired into the evaluator.** As for the filters (decision 328), the family is compiled into its test executable only. Production may serve only `exact` assets (phase3.3).

## Alternatives Considered

- **Periodic noise in the shared primitive library.** Deferred, not rejected. It belongs there once the generator families' work on `src/procedural` lands. Moving it later changes no output, because the operations are the same.
- **A distinct kernel per asset.** Rejected. Seventeen bodies would mirror one CPU reference each. One body over six kinds keeps a single mirror to review.
- **A continuous `tiling` range.** Rejected, because the texture would not wrap.
- **Painter's recorded parameter names as the UzPainter names.** Rejected. Their ranges and meanings are undiscovered, and some names carry Painter's typos (`historgram_contrast`).

## Consequences

- Items 2.2, 2.4, 2.5 and 3.1, the held-out half of 2.6 and the oracle half of 3.3 remain. 4.1 waits on them.
- An asset whose calibration needs another kind or structure changes it before calibration starts.
- The domain-refusal test 3.4 needs no Painter, but is not part of this slice.
