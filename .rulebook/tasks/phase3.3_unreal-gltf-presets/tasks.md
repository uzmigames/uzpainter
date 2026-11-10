## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery`
  - Archived (2026-11-10 check): `.rulebook/archive/2026-11-05-phase2.10_pilot-tunic-recovery/`.

## 2. Children (mandatory)
- [ ] 2.1 Child accepted: `phase3.2_unreal-ue56-packed-preset`
  - Open (2026-11-10). The child's items 2.8, 3.2, 3.3 and 3.5 and its acceptance 4.1 need a UE 5.6 project folder on the owner's machine (decision 028), and none has been named. Its item 2.9 (dithering, resize and the dilation paddings) is an open fit (decisions 103, 349).
- [x] 2.2 Child accepted: `phase3.1_unreal-gltf-pbr-preset`
  - Accepted and archived 2026-11-09 (`.rulebook/archive/2026-11-09-phase3.1_unreal-gltf-pbr-preset/`, its section "Closure"): the glTF preset's files equal Painter's own glTF export of Wand v1, Sash v5 and Tunic v10 in decoded values under EXC-013 and EXC-014 (`parity/reports/phase3/tier1-*-gltf.json`); the fastgltf fixture loads the production Wand v1 export with ORM packing confirmed (`parity/reports/phase3/gltf-consumer-wand-v1.md`; this also gives item 4.2's evidence). Decision 419 (AO_Mixed without an AO mesh map under OCIO; the Legacy twin).

## 3. Integration
- [x] 3.1 Run both presets on wand v1, belt v5 and tunic v10 through the plan compiler and generational publication
  - Both presets ran on all three pilots through the production export (plan compiler, generational publication), two ReleaseFast rebuilds per pilot. glTF: `tests/parity/tier1/test_gltf_pilots.py`, 3 passed, 2026-11-09 (the glTF child's closure). Unreal Engine (Packed): `tests/parity/tier1/test_unreal_pilots.py`, 3 passed, 2026-11-10 (UE 5.6 child item 3.1). Belt v5 is the Sash v5 current round (decisions 260, 399).
- [x] 3.2 Output parity: each preset's files compared with Painter's export of the same preset on the same projects (private oracle, decoded values at native depth)
  - Both presets pass under EXC-013 (padding) and EXC-014 (the Normal's island edge) only, the exceptions each receipt names. No exception was created or widened. Every covered texel of BaseColor and ORM equals Painter's r1. The Normal differs only on covered island-edge texels: glTF 42, 880 and 25,393 (Wand, Sash, Tunic; `parity/reports/phase3/tier1-*-gltf.json`); Unreal 43, 872 and 25,382 (UE 5.6 child, section "Pilot goldens"). Painter is stable and UzPainter's rebuilds are byte-repeatable.
- [ ] 3.3 Consolidated consumer-gap report for both presets in `parity/reports/phase3/`
  - Published 2026-11-10 as `parity/reports/phase3/unreal-gltf-consumer-gaps.md`. It covers the receipts' gaps for every preset (SpecularWeight on all three; the DDS `cook` gap; glTF's unbound emissive) and the pilots, and is complete for glTF. The item stays open on its Unreal half: the UE 5.6 bindings and the cook re-encode observation come from the UE 5.6 fixture (child 2.8, 3.2, 3.3), which waits on the owner's UE project folder.
- [ ] 3.4 Regenerate the capability manifest with both presets at their proven status
  - Open (2026-11-10). The Unreal preset's proven status changes when the UE 5.6 child is accepted. The manifest has no per-preset entry today: no `tools/capabilities` input names a preset context. The entry shape (for example `uzpainter.export.export_project_textures` @ `preset:<id>`) is settled with the entries when the child closes. Both provenance records still say `parity.status: pending`.

- [ ] 3.5 (decision 103, from phase1.18_export-engine item 6.2, decision 096) Record R-095 (`parity/reports/phase1/export-presets.md` §3; `export-presets-legacy` crashed Painter in the 2026-10-12 session, the OCIO presets were not recorded); confirm or correct `pbr-metallic-roughness` and `blender-principled-bsdf` from it (provenance `parity.layout` "confirmed"); add an output-parity test per shipped preset in `tests/export/test_export_presets.py` against the R-095 goldens (every file's name and decoded pixels); set each record's `privateRecords` and `parity.status` "exact" once BaseColor (phase1.25_pilot-wand item 2.6) is fitted
  - Status 2026-11-10, nothing changed. R-095 is now admitted in the current envelope (`tier0/semantics/export-presets-legacy` and `-ocio`, r1 and r2).
    - `blender-principled-bsdf`: layout confirmed (`test_blender_layout_matches_private_r095_readback`).
    - `pbr-metallic-roughness`: Painter's `list_output_maps` readback in both sessions has 6 maps, and the shipped preset has 5. The 5 shared positions differ in file name and parameters, and two of them also in channels (a local comparison, counts only). The preset is still `unconfirmed` and refused naming R-095.
  - Not yet possible: correcting it from the readback, and the per-preset decoded-pixel tests. R-095 records only the PBR preset's layout, not its files, so the PBR pixel test needs a new recording of its export. The Blender pixel test needs its files compared under the export's padding and dithering rules (child 2.9). The item stays open.

## 4. Tests
- [ ] 4.1 Consumer-matrix row 8 (`08-export.md` §5.1) passes on wand v1 for the PNG/TGA and the DDS variants
  - Open: the UE 5.6 fixture (child 3.2, 3.3) waits on the owner's UE project folder.
- [x] 4.2 The glTF consumer fixture passes on wand v1
  - Joined from the glTF child's 3.2 (2026-11-09). fastgltf 0.9.1 validates and loads the production Wand v1 export with the four core bindings. ORM G and B equal the independent Roughness and Metallic on all 4,194,304 texels. Sources: `parity/manifests/consumers/gltf/wand-v1.json` (`real-fixture-passed`) and `parity/reports/phase3/gltf-consumer-wand-v1.md`.
- [x] 4.3 Byte determinism: two exports of each preset from the same build, project and config are identical (EXP-05)
  - `tests/export/test_preset_determinism.py` (2026-11-10, CPU, 4 passed in 40.62 s) runs two separate `publish` processes per case. The cases: `unreal-engine-packed` PNG 8, `unreal-engine-packed-dds`, `gltf-pbr-metal-roughness` (all on the authored set in AO_Mixed's scope), and the Unreal TGA 8 encoding (test copy, set without SpecularWeight). In every case the files are byte-identical and the receipts list the same files and hashes. On the GPU, the pilots' two production rebuilds are byte-repeatable for both presets (3.1).

## 5. Acceptance
- [ ] 5.1 DAG gate P3-UNREAL met: fixtures load; packing confirmed
  - Open: the glTF fixture loads with its packing confirmed (4.2). The UE 5.6 fixture (2.1, 4.1) waits on the owner's UE project folder. Not archived.

## 6. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 6.1 Update or create documentation covering the implementation
- [ ] 6.2 Write tests covering the new behavior
- [ ] 6.3 Run tests and confirm they pass
