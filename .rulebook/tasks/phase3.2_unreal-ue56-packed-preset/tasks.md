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
- [ ] 2.8 UE 5.6 import fixture manifest `parity/manifests/consumers/unreal/wand-v1.json` and runner on the self-hosted GPU runner, consuming through the delivery adapter or publication lock

## 3. Tests
- [ ] 3.1 Output parity on wand v1, belt v5 and tunic v10: every preset file equals Painter's export of the same preset in decoded values
- [ ] 3.2 Consumer-matrix row 8 on wand v1, PNG/TGA variant: BaseColor sRGB, ORM linear, Normal as DirectX normal map, Emissive sRGB
- [ ] 3.3 Consumer-matrix row 8 on wand v1, DDS BC7/BC5 variant: same bindings; whether UE re-encodes on cook is recorded
- [ ] 3.4 Defect detection: an ORM map with swapped G/B channels fails the packing check
- [ ] 3.5 Fixed-name interruption test: interrupting each fixed-name copy and immediately running the UE import through its adapter yields one complete generation or fails before consumption (EXP-06)
- [ ] 3.6 Provenance record validates against its schema in hosted CI

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase3.3_unreal-gltf-presets`: UE 5.6 fixture loads both variants; ORM packing confirmed; SpecularWeight gap reported

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
