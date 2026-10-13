## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input); for the DDS items also `phase3.1_uze-uztexture-writer`

## 2. Implementation
- [ ] 2.1 Record the private observed outputs: Painter's files for `Unreal Engine (Packed)` on a UzmiGames fixture project and the documented `list_output_maps()` result, stored in the private oracle store with hashes in `parity/manifests/`
- [ ] 2.2 Author `assets/export-presets/unreal-engine-packed.json` by hand from documented semantics (BaseColor+opacity, ORM linear, `Normal_DirectX`, Emissive)
- [ ] 2.3 Provenance record `assets/export-presets/unreal-engine-packed.provenance.json` with public sources, observed-output hashes, packing decisions and parity status
- [ ] 2.4 Compatibility alias so `defaultExportPreset: "Unreal Engine (Packed)"` resolves to the shipped preset (CLR-06)
- [ ] 2.5 TGA 8-bit output path through stb for the default encoding
- [ ] 2.6 DDS header writer and the DDS variant: BC7 for BaseColor, ORM and Emissive, BC5 for Normal, through the BC encoder adapter
- [ ] 2.7 `_SpecularWeight` written as a separate map when the channel exists and listed as a consumer gap in the receipt
- [ ] 2.8 UE 5.6 import fixture manifest `parity/manifests/consumers/unreal/wand-v1.json` and runner, run locally on the owner's machine (decision 028), consuming through the delivery adapter or publication lock

- [ ] 2.9 (decision 103, from phase1.18_export-engine item 6.1) Fit and implement exactly, against the admitted recordings `export-dither`, `export-resize` and `export-padding*` (R-090 P3, P4, P5): dithering at PNG 8 (deterministic, not a threshold matrix) and in OpenEXR; resize (partial fit: upscale is the evaluation at the target size, downscale a 2x2 box stored in the channel format; sRGB8, virtual normals after downscale and BilinearHQ normal magnification open); the `color`, `transparent` and `diffusion` paddings with `dilationDistance`. Until then each is refused before writing
- [ ] 2.10 (decision 131, from phase1.15_export-plan-compiler items 3.6, 4.1) Fit and implement the `AO_Mixed` virtual map (the ORM's R) exactly in the plan (`src/export/virtual_maps.cpp`) against recordings R-086a (`ao-mixed`, `ao-mixed-opacity` and its OpenEXR 32f twin) and the R-092 isolation goldens (`ao-mixed-isolation`, `-float`, `-8bit`), every texel of r1 at PNG 8, PNG 16 and OpenEXR 32f; the best model of decision 092 misses r1 at 31 values. If the isolation goldens do not identify the operator, record R-131 (decision 131 §2: the 256x256 grid of mesh-map and channel codes at the missed opacities and at opacity 1). Until then the plan refuses AO_Mixed before writing (also `phase3.2_uze-uzmat-preset`'s `<set>_orm`)

## 3. Tests
- [ ] 3.1 Output parity on wand v1, belt v5 and tunic v10: every preset file equals Painter's export of the same preset in decoded values
- [ ] 3.2 Consumer-matrix row 8 on wand v1, PNG/TGA variant: BaseColor sRGB, ORM linear, Normal as DirectX normal map, Emissive sRGB
- [ ] 3.3 Consumer-matrix row 8 on wand v1, DDS BC7/BC5 variant: same bindings; whether UE re-encodes on cook is recorded
- [ ] 3.4 Defect detection: an ORM map with swapped G/B channels fails the packing check
- [ ] 3.5 Fixed-name interruption test: interrupting each fixed-name copy and immediately running the UE import through its adapter yields one complete generation or fails before consumption (EXP-06)
- [ ] 3.6 Provenance record validates against its schema on the local CPU lane (decision 200)

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase3.3_unreal-gltf-presets`: UE 5.6 fixture loads both variants; ORM packing confirmed; SpecularWeight gap reported

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
