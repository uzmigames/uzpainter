## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase3.1_proc-backend-seam
  - Note (2026-11-11): archived (`.rulebook/archive/2026-11-08-phase3.1_proc-backend-seam`).

## 2. Implementation
- [x] 2.1 Discover each material's parameters, outputs, ranges and labels through the documented `Property` API
  - Note (2026-11-11, decision 432): `python -m tools.parity.recorder.material_survey` (`painter_material_survey.py`, documented symbols only, no pixel) ran under the Painter lock (Painter 12.2.0, Legacy, seq 2380 to 2381); the private survey's SHA-256 is `c14b57a2…`. `python -m tools.parity.proc_materials.discovery` publishes names, labels, widget types, declared defaults, ranges, visibility, resource URLs, port counts, output names and the default material fill's channels and mapping: `docs/analysis/proc-material-families/01-parameter-discovery.md`.
    - Felt and leather grain are the starter materials `fabric_felt` (13 outputs) and `leather_grain` (10 outputs), each with 3 presets, a `$randomseed` and colour parameters. A default felt fill activates BaseColor, BaseMetalness, Height and SpecularRoughness. A default leather grain fill activates BaseColor, BaseMetalness, Normal and SpecularRoughness.
    - Burlap and leather pattern are the single sources under the pattern layers of the starter smart materials Fabric Burlap and Leather Damaged: the procedurals `weave_2` (a mask source) and `grunge_leather_damaged` (a split BaseColor and Height source), each in its smart material's embedded context with a `$randomseed`. The smart-material structures stay private.
    - The UzPainter records keep their own names and ranges: no family is calibrated (item 2.5 note), so decision 334 §6's revision of ranges does not arise.
- [x] 2.2 Implement felt and burlap with every output channel reachable through `output_mapping`
  - Done 2026-10-20 (decision 334): `src/procedural/materials.{h,cpp}` and `shaders/proc_materials.hlsli`, six outputs per material (basecolor, normal, roughness, metallic, height, ambient_occlusion) in the record; `MaterialRequests` gives one request per `output_mapping` channel and `SetMaterialSource` admits each before its transaction (`uzp-proc-material-tests` `families`, `tiling`, `kernels`). Uncertified.
- [x] 2.3 Implement leather grain and leather pattern with every output channel reachable through `output_mapping`
  - Done 2026-10-20 (decision 334): the same six outputs and mapping; Worley cells with grooves and pores, creases with ridged-fBm wrinkles (`families`, `tiling`, `kernels`). Uncertified.
- [x] 2.4 Implement physical-size evaluation (`MaterialPhysicalSize`, `CustomPhysicalSize`) under the project unit rule; record effective units
  - Done 2026-10-20 (decision 334): `EvaluatePhysicalScale` and its receipt `PhysicalScale::ToJson` (size and origin, units {source, from, requested_mesh_unit_scale, scale_to_internal}, textures per file unit, centimetres per UV from the certificate's density, UV scale) (`physical` case). Painter's own rule is UzPainter's assumption until the oracle half of 3.2; the evaluator still refuses both modes until a material is `exact`.
- [x] 2.5 Calibrate black-box against private Painter oracles; write the provenance record, per-asset/per-output parity status and Tier 2a manifests; calibration starts only after item 2.6 has declared the domain and committed the held-out hash list, and never reads held-out oracles
  - Note (2026-11-11, decision 432; ticked on the narrowed acceptance): no calibration was run. All four families are seeded Adobe Substance graphs, which no public source describes, so no clean-room kernel can be exact (decision 427 §1 and §2, applied to materials). The ~2 h time box cannot change that. There is no candidate, so there is no candidate exception.
    - Route: decision 429's snapshot-only route, by its precedent. The families are served only from project-private snapshots of the user's own Painter and refused without one. The `material.*@1` records stay `unavailable` with no alias, and their reason names decision 432.
    - The route cannot serve them yet. These release gaps move to `phase3.3_procedural-families` item 2.16:
      - the capture's codec holds no colour parameter, and both materials and the recipes use colours;
      - only a material fill's Height composition is recorded;
      - captures run on the 128 px plane only;
      - Painter's physical-size rule is not recorded.
    - The masked and split uses of burlap and leather pattern follow items 2.15 and 2.7, inside `phase3.6_smart-presets-projections`.
    - No Tier 2a manifest is authored, and no parity status other than `unavailable` is written (decision 429 §6).
- [x] 2.6 Before calibration, declare each asset's certified editable domain (parameter ranges and joint constraints, seed policy, geometry inputs, resolutions, formats and colour spaces; `05-procedural-content.md` §6, decision 222) and reserve its held-out set (meshes, interior parameter points, seeds and a resolution outside the calibration set), recorded in the same batch with its hash list committed before calibration starts; a held-out case used to change a fit is moved to the calibration set and replaced (decision 222)
  - Domains declared 2026-10-20 in `assets/procedural/records/material.*@1.json` before any calibration (UzPainter parameter names and ranges, `tiling` {1, ..., 32}, any 32-bit seed, the three mesh classes on one UV tile, no image input, f32 output at 1024, 2048 and 4096, linear or sRGB with 1 or 3 channels, each output's spec in `outputs`), every status `unavailable`, no alias. Still open: the held-out reservation and its hash list come from the recording batch, and the ranges are revised once item 2.1 discovers Painter's.
  - Note (2026-11-11, decision 432; ticked on the narrowed acceptance): the domain half stays met. No held-out set is reserved, because no family can be calibrated (item 2.5 note), and a snapshot-only family has no held-out set (decision 429 §6).

## 3. Tests
- [x] 3.1 Tier 2a for every output of each material on unit sphere, bevelled cube and hat v6 low × {1024, 2048, 4096} × parameter sets × seeds against private goldens (the calibration set), and on the held-out set reserved in 2.6, reported separately
  - Note (2026-11-11, decision 432; ticked on the narrowed acceptance): no family has a Tier 2a run, because none has a clean-room candidate (item 2.5 note). The families moved to `phase3.3_procedural-families` item 2.16 on the snapshot-only route, where Tier 2a does not apply.
- [x] 3.2 Physical-size test: the same material on meshes in two unit scales gives the oracle outputs and records the effective units
  - Half done 2026-10-20: one OBJ plane imported with the file unit and with `mesh_unit_scale` 100 records different effective units and scales 100 times apart, for both modes (`physical` case). Open: the oracle outputs need Painter goldens.
  - Note (2026-11-11, decision 432; ticked on the narrowed acceptance): the oracle half moves to `phase3.3_procedural-families` item 2.16. Painter's own `MaterialPhysicalSize` and `CustomPhysicalSize` rules are not recorded, and no family can be served on a mesh other than the 128 px plane yet. Both modes stay refused by the support check.
- [x] 3.3 DX12 repeatability: identical bytes across two runs per material
  - Done 2026-10-20: `gpu` case, every output of every material: two DX12 runs give identical bytes, DX12 equals the CPU reference bit for bit over the whole 1024 texture and on a border tile, and two seeds differ (93 checks).
- [x] 3.4 Domain-refusal test: a parameter, seed, mesh-map input and resolution just outside the declared domain each raise `UnsupportedProcedural{reason: "outside certified domain"}` before mutation, with nothing clamped or substituted
  - Done 2026-10-20: `domain` case, fifteen cases per material through `SetMaterialSource`, each naming its field, with no transaction, revision 0 and the project unchanged; the candidate lane evaluates nothing.

## 4. Acceptance
- [x] 4.1 Acceptance: every material output exact on its calibration and held-out sets, or covered by an owner-approved exception, inside its declared domain; the rest of its documented range listed as a release gap
  - Note (2026-11-11, decision 432, narrowed acceptance): no family is exact, and none has an exception.
    - Felt, leather grain, burlap and leather pattern are listed as release gaps with the survey's evidence. They are served only from project-private snapshots and refused without one. Their records are `unavailable`, with no alias. Their serving gaps moved to `phase3.3_procedural-families` item 2.16.
    - Met here: the discovery (2.1), the kernels (2.2, 2.3), the physical-size receipt (2.4), the declared domains (2.6, first half), and the repeatability and domain-refusal tests (3.3, 3.4).
    - New refusal: a material fill with an active channel other than Height is refused before any change, naming item 2.16. Before, the evaluator left that channel as the layers below gave it, which is not what Painter does.
    - Evidence: `tests/parity/test_proc_material_discovery.py` (2 passed); one run of `tests/procedural/test_material_snapshot_source.py` (the `snapshot-material` case, now also refusing another active channel), `tests/python/test_material_source_replay.py`, `tests/procedural/test_proc_asset_library.py`, `tests/procedural/test_proc_material_families.py::test_every_material_has_a_record_and_no_alias` and `tests/parity/recorder/test_provenance.py` on the CPU (`UZP_NO_GPU=1`): 75 passed, none skipped, exit 0 (JUnit `tmp/scratch/material-affected.xml`); `test_material_domain_is_declared_before_calibration` 4 passed.

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
  - Done 2026-10-20: `05-procedural-content.md` "As built, materials", decision 334.
- [x] 5.2 Write tests covering the new behavior
  - Done 2026-10-20: `tests/procedural/materials_test.cpp`, `tests/procedural/test_proc_material_families.py`.
- [x] 5.3 Run tests and confirm they pass
  - Done 2026-10-20: one run of `tests/procedural/test_proc_material_families.py -k "not dx12"` on the CPU (`UZP_NO_GPU=1`): 11 passed, 1 deselected, exit 0; log `tmp/scratch/proc-tails/pytest-material.log`. The deselected case is the DX12 one. Its last pass is the one recorded under items 2.x and 3.x.
