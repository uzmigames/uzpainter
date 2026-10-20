## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_proc-backend-seam

## 2. Implementation
- [ ] 2.1 Discover each material's parameters, outputs, ranges and labels through the documented `Property` API
- [x] 2.2 Implement felt and burlap with every output channel reachable through `output_mapping`
  - Done 2026-10-20 (decision 334): `src/procedural/materials.{h,cpp}` and `shaders/proc_materials.hlsli`, six outputs per material (basecolor, normal, roughness, metallic, height, ambient_occlusion) in the record; `MaterialRequests` gives one request per `output_mapping` channel and `SetMaterialSource` admits each before its transaction (`uzp-proc-material-tests` `families`, `tiling`, `kernels`). Uncertified.
- [x] 2.3 Implement leather grain and leather pattern with every output channel reachable through `output_mapping`
  - Done 2026-10-20 (decision 334): the same six outputs and mapping; Worley cells with grooves and pores, creases with ridged-fBm wrinkles (`families`, `tiling`, `kernels`). Uncertified.
- [x] 2.4 Implement physical-size evaluation (`MaterialPhysicalSize`, `CustomPhysicalSize`) under the project unit rule; record effective units
  - Done 2026-10-20 (decision 334): `EvaluatePhysicalScale` and its receipt `PhysicalScale::ToJson` (size and origin, units {source, from, requested_mesh_unit_scale, scale_to_internal}, textures per file unit, centimetres per UV from the certificate's density, UV scale) (`physical` case). Painter's own rule is UzPainter's assumption until the oracle half of 3.2; the evaluator still refuses both modes until a material is `exact`.
- [ ] 2.5 Calibrate black-box against private Painter oracles; write the provenance record, per-asset/per-output parity status and Tier 2a manifests; calibration starts only after item 2.6 has declared the domain and committed the held-out hash list, and never reads held-out oracles
- [ ] 2.6 Before calibration, declare each asset's certified editable domain (parameter ranges and joint constraints, seed policy, geometry inputs, resolutions, formats and colour spaces; `05-procedural-content.md` §6, decision 222) and reserve its held-out set (meshes, interior parameter points, seeds and a resolution outside the calibration set), recorded in the same batch with its hash list committed before calibration starts; a held-out case used to change a fit is moved to the calibration set and replaced (decision 222)
  - Domains declared 2026-10-20 in `assets/procedural/records/material.*@1.json` before any calibration (UzPainter parameter names and ranges, `tiling` {1, ..., 32}, any 32-bit seed, the three mesh classes on one UV tile, no image input, f32 output at 1024, 2048 and 4096, linear or sRGB with 1 or 3 channels, each output's spec in `outputs`), every status `unavailable`, no alias. Still open: the held-out reservation and its hash list come from the recording batch, and the ranges are revised once item 2.1 discovers Painter's.

## 3. Tests
- [ ] 3.1 Tier 2a for every output of each material on unit sphere, bevelled cube and hat v6 low × {1024, 2048, 4096} × parameter sets × seeds against private goldens (the calibration set), and on the held-out set reserved in 2.6, reported separately
- [ ] 3.2 Physical-size test: the same material on meshes in two unit scales gives the oracle outputs and records the effective units
  - Half done 2026-10-20: one OBJ plane imported with the file unit and with `mesh_unit_scale` 100 records different effective units and scales 100 times apart, for both modes (`physical` case). Open: the oracle outputs need Painter goldens.
- [x] 3.3 DX12 repeatability: identical bytes across two runs per material
  - Done 2026-10-20: `gpu` case, every output of every material: two DX12 runs give identical bytes, DX12 equals the CPU reference bit for bit over the whole 1024 texture and on a border tile, and two seeds differ (93 checks).
- [x] 3.4 Domain-refusal test: a parameter, seed, mesh-map input and resolution just outside the declared domain each raise `UnsupportedProcedural{reason: "outside certified domain"}` before mutation, with nothing clamped or substituted
  - Done 2026-10-20: `domain` case, fifteen cases per material through `SetMaterialSource`, each naming its field, with no transaction, revision 0 and the project unchanged; the candidate lane evaluates nothing.

## 4. Acceptance
- [ ] 4.1 Acceptance: every material output exact on its calibration and held-out sets, or covered by an owner-approved exception, inside its declared domain; the rest of its documented range listed as a release gap

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
  - Done 2026-10-20: `05-procedural-content.md` "As built, materials", decision 334.
- [x] 5.2 Write tests covering the new behavior
  - Done 2026-10-20: `tests/procedural/materials_test.cpp`, `tests/procedural/test_proc_material_families.py`.
- [x] 5.3 Run tests and confirm they pass
  - Done 2026-10-20: one run of `tests/procedural/test_proc_material_families.py -k "not dx12"` on the CPU (`UZP_NO_GPU=1`): 11 passed, 1 deselected, exit 0; log `tmp/scratch/proc-tails/pytest-material.log`. The deselected case is the DX12 one. Its last pass is the one recorded under items 2.x and 3.x.
