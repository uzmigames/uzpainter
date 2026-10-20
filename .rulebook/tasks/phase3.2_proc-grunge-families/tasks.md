## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_proc-backend-seam

## 2. Implementation
- [x] 2.1 Build the asset inventory from the body and hat recipes (grunge, dirt, spots, scratches, rust, humidity, cracks) plus `fabric_linen`, with aliases and the recorded parameter sets
  - Done 2026-10-20: `docs/analysis/proc-grunge-families/01-asset-inventory.md`, 17 UzPainter assets (`uzasset://grunge/<id>@1`) with the Painter name each alias will carry and the recorded parameter sets mapped by name. No alias is registered: decision 324 admits only `exact` assets.
- [ ] 2.2 Discover each asset's parameter names, ranges and labels through the documented `Property` API
- [x] 2.3 Implement each asset on the shared primitive library with tiling, seed and parameters
  - Done 2026-10-20 (decision 331): `src/procedural/grunges.{h,cpp}`, 17 assets on six periodic pattern kinds; DX12 equals the CPU reference bit for bit on every asset (`uzp-proc-grunge-tests` `families`, `kernels`, `gpu`). Uncertified.
- [ ] 2.4 Calibrate black-box against private Painter oracles; write the family provenance record and per-asset parity status; calibration starts only after item 2.6 has declared the domain and committed the held-out hash list, and never reads held-out oracles
- [ ] 2.5 Author the Tier 2a manifests under `parity/manifests/`
- [ ] 2.6 Before calibration, declare each asset's certified editable domain (parameter ranges and joint constraints, seed policy, geometry inputs, resolutions, formats and colour spaces; `05-procedural-content.md` §6, decision 222) and reserve its held-out set (meshes, interior parameter points, seeds and a resolution outside the calibration set), recorded in the same batch with its hash list committed before calibration starts; a held-out case used to change a fit is moved to the calibration set and replaced (decision 222)
  - Domains declared 2026-10-20 in `assets/procedural/records/grunge.*@1.json` (UzPainter parameter names and ranges, any 32-bit seed, the three mesh classes on one UV tile, no image input, f32 linear mono output at 1024, 2048 and 4096), every status `unavailable`. Still open: the held-out reservation and its hash list come from the recording batch, and the ranges are revised once item 2.2 discovers Painter's.

## 3. Tests
- [ ] 3.1 Tier 2a for every inventoried asset on unit sphere, bevelled cube and hat v6 low × {1024, 2048, 4096} × parameter sets × seeds against private goldens (the calibration set), and on the held-out set reserved in 2.6, reported separately
- [x] 3.2 Tiling test: outputs wrap seamlessly at the tile boundary where the asset tiles
  - Done 2026-10-20: `tiling` case, every asset at tilings 1 to 8, flips and 1024/2048/4096: the texture continued one tile past each border equals itself bit for bit (6.0 M texel pairs).
- [ ] 3.3 Seed test: two seeds give the oracle's two outputs; the same seed repeats byte-identically on DX12
  - Half done 2026-10-20: the same seed repeats byte-identically on DX12 and two seeds differ, for every asset (`gpu`, `seeds` cases). Open: the oracle's two outputs need Painter goldens.
- [x] 3.4 Domain-refusal test: a parameter, seed, mesh-map input and resolution just outside the declared domain each raise `UnsupportedProcedural{reason: "outside certified domain"}` before mutation, with nothing clamped or substituted
  - Done 2026-10-20 (decision 331 amendment): `domain` case of `uzp-proc-grunge-tests`. `SetGrungeSource` sets a grunge as a fill's source, on a content channel or a mask fill. It refuses 16 requests per asset just outside the domain, plus one for each of the asset's own parameters (285 in all). The 16 are a parameter one ulp above and one below its range, `invert` 2, `tiling` 9, 0 and 2.5, the recorded `brush_pattern` with no counterpart, seed 2^32, another mesh class, two UV tiles, an `AO` mesh-map input, output resolutions 512 and 8192, f16, sRGB and three channels. Each raises `outside certified domain`, names its field, and comes before `submit`: the revision and the project are unchanged, and the CPU lane evaluates nothing. Inside the domain the asset is still refused (`family not certified`). An admitted source is committed as given. Evidence: `tests/procedural/test_proc_grunge_families.py::test_domain_refusals_come_before_mutation`; log `tmp/scratch/proc-tails/pytest-grunge.log`.

## 4. Acceptance
- [ ] 4.1 Acceptance: every inventoried asset exact on its calibration and held-out sets, or covered by an owner-approved exception, inside its declared domain; the rest of its documented range and any other asset listed as release gaps

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
  - Done 2026-10-20: `05-procedural-content.md` "As built, grunges and noises", decision 331 and its amendment, `docs/analysis/proc-grunge-families/01-asset-inventory.md`. They cover the items built so far. The Painter items (parameter discovery, calibration, Tier 2a) add their own docs and tests when they land.
- [x] 5.2 Write tests covering the new behavior
  - Done 2026-10-20: `tests/procedural/grunges_test.cpp`, `tests/procedural/test_proc_grunge_families.py`.
- [x] 5.3 Run tests and confirm they pass
  - Done 2026-10-20: one run of `tests/procedural/test_proc_grunge_families.py -k "not dx12"` on the CPU (`UZP_NO_GPU=1`): 23 passed, 1 deselected, exit 0; log `tmp/scratch/proc-tails/pytest-grunge.log`. The deselected case is the DX12 one. Its last pass is the one recorded under items 2.x and 3.x.
