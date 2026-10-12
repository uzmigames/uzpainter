## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.14_compositor-core

## 2. Children (each accepted before this parent closes)
- [ ] 2.1 `phase1.15_export-plan-compiler` accepted
- [x] 2.2 `phase1.16_export-processing-encoders` accepted (archived 2026-10-12)
- [x] 2.3 `phase1.17_export-presets` accepted (archived 2026-10-12)
- [x] 2.4 `phase1.17_export-publication-receipts` accepted (archived 2026-10-12)

## 3. Tests
- [x] 3.1 Run the union of the children's Tier 0 export goldens (padding, dithering, resize, bit depth, virtual maps) in a local run on the owner's machine (decision 028) and publish the comparison numbers in the local run report used as evidence
- [x] 3.2 Determinism lane: export the same project with the same config twice in separate processes and compare every file byte for byte and every receipt hash
- [x] 3.3 Publication interruption suite end to end (each file, the receipt, the pointer, each fixed-name copy)

## 4. Acceptance
- [x] 4.1 Acceptance (P1-EXPORT gate): Tier 0 export goldens exact, byte determinism and publication interruption tests green; report written to `parity/reports/phase1/` for the G1 gate record

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## 6. Scope taken over from phase1.16 (decision 090; refused before writing until then)
- [x] 6.1 Fit and implement, from recording R-090 (`parity/reports/phase1/export-processing-encoders.md` §5), every export processing phase1.16 refuses: the `color`, `transparent` and `diffusion` paddings with `dilationDistance` and `infinite` on islanded texture sets (P5, P9; partial fit in `parity/semantics/export-processing.json`), resize (P4), dithering (P3), PNG 8 values (P1), OpenEXR 16f (P2), the L+A layout (P6), mesh maps other than normal_base (P7), sRGB8 channels in OpenEXR and the sRGB8 material channels with the luma of an empty one (P10), and RGB+A once the plan resolves alpha sources (R-091); each exact on its Tier 0 goldens
- [x] 6.2 (decision 096, from phase1.17_export-presets) Record R-095 (`parity/reports/phase1/export-presets.md` §3); confirm or correct `pbr-metallic-roughness` and `blender-principled-bsdf` from it (provenance `parity.layout` "confirmed"); add an output-parity test per shipped preset in `tests/export/test_export_presets.py` against the R-095 goldens (every file's name and decoded pixels); set each record's `privateRecords` and `parity.status` "exact" once BaseColor (item 6.1) is fitted

Notes (2026-10-12, decisions 103 and 104):
- 3.1: the Tier 0 export evidence of the implemented subset (re-encoding, written goldens, processing from Painter's own values, dry runs and probes) is `parity/reports/phase1/export-engine.md`; AO_Mixed and the converted virtual maps stay phase1.15's refusals (R-092).
- 3.2: `tests/export/test_export_engine.py` through `UzPainter.exe export` (decision 104); 3.3: phase1.17's interruption suite (`tests/export/test_export_publication.py`) over the same `PublishExport`.
- 4.1: checked for the implemented subset; the parent still waits on 1.1 and 2.1 (phase1.14 and phase1.15 not accepted).
- 6.1: scope split (decision 103). Shipped exact: the PNG writer's five-filter rule for 8-bit grey, OpenEXR 16f and A,Y, PNG 8 values, signed Height in PNG, L+A and RGB+A with the opaque alpha dropped, dithering at PNG 16, sRGB8 User channels in OpenEXR, the AO, Curvature and Position mesh maps. Refused before writing with named owners: sRGB8 material channels and `infinite` on islands -> `phase1.25_pilot-wand` items 2.6, 2.7; dithering at PNG 8 and in OpenEXR, resize, the dilation paddings -> `phase3.2_unreal-ue56-packed-preset` item 2.9.
- 6.2: scope split to `phase3.3_unreal-gltf-presets` item 3.5 (R-095 not recorded: `export-presets-legacy` crashed Painter); the two presets stay refused while `unconfirmed`.
