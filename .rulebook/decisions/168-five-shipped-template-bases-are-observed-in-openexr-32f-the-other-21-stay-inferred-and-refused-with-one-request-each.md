# 168. Five shipped template bases are observed in OpenEXR 32f; the other 21 stay inferred and refused, with one request each

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.25_pilot-wand

## Context

Decision 126 left the linear base of 26 shipped templates `inferred`: only their PNG 16 code was recorded (48107 on 18 templates, 59397 on four OpenPBR templates, 14330 on four sRGB8-Specular templates), and a range of floats writes each code. The export refuses every file that depends on such a base. Decision 160 admitted the three OpenEXR 32f exports of an empty base that decision 157 requested, all stable (`r1 = r2`, every same-session repeat identical), under the envelope `painter-12.1.5_js-api.1.1.20`. Only numbers are used here; the files stay in the private store.

- **The new goldens.** Every texel of each OpenEXR 32f file holds one value, bit for bit:
  - `export-template-base-unreal-engine` BaseColor: `0x3EFEFEFF`, `float32(127/255)`;
  - `export-template-base-openpbr-anisotropy` BaseColor: `0x3F4CCCCD`, `float32(0.8)`;
  - `export-template-base-pbr-specular-glossiness` Specular: `0x3D20A0A1`, `float32(10/255)`.

  Their PNG 16 controls hold 48107, 59397 and 14330, as the base-values goldens did. Each value is the candidate decision 126 named for its code.
- **Two more templates, already in the store.** Decision 093's float twins of the virtual-map goldens export the template's BaseColor (or Specular) at OpenEXR 32f, and their set `s7` is empty. Their `s7` files are byte-identical to the new goldens' files:
  - `virtual-maps-template-openpbr-coat-float` s7 BaseColor is the OpenPBR - Anisotropy file (`float32(0.8)`);
  - `virtual-maps-template-pbr-metallic-roughness-alpha-blend-float` s7 BaseColor is the Unreal Engine file (`float32(127/255)`);
  - `virtual-maps-template-pbr-specular-glossiness-float` s7 Specular is the PBR - Specular Glossiness file.

  Decision 126 had missed these files.
- **What stays unidentified.** Those five templates agree with their code class every time (two of two at 48107, two of two at 59397, one at 14330). Agreement is not identity, though. For 48107, the half `0.498046875` writes the same code as `float32(127/255)`, and so does every float32 in a range about 2.3e-5 wide. A class rule would claim 21 values no recording shows, so it is not adopted.

The coordinator's brief settled the scope: lift the refusal only where the data is exact. Nothing was left to choose, so the model panel was not consulted.

## Decision

1. **Five bases are `observed`** (`assets/templates/*.json`). These are Unreal Engine, PBR - Metallic Roughness Alpha-blend (`float32(127/255)`), OpenPBR - Anisotropy, OpenPBR - Coat (`float32(0.8)`) and PBR - Specular Glossiness (Specular `float32(10/255)`). Each `base_provenance` names the OpenEXR golden, its golden-record hash and its map. It keeps `export16`, the base-values code that the sRGB export encode of the value writes. The values are unchanged. `RequireIdentifiedBase` now lets these channels through, through documentMap and diagnosticMap sources alike.
2. **Twenty-one bases stay `inferred` and refused**, naming decision 126 and this item: 16 at 48107, OpenPBR - Fuzz and OpenPBR - Subsurface Scattering at 59397, and Maxwell, Non-PBR and VrayMtl Specular Glossiness at 14330.
3. **One request per remaining template** (`recording_requests.REMAINING_BASE_TEMPLATES`). Each `export-template-base-<template>` is decision 157's template-base golden: an empty project on the plane, BaseColor and Specular at OpenEXR 32f and PNG 16, each export done twice, under Legacy. They are listed in `parity/RECORDER.md` §11.4. When one is admitted, its template's entry becomes `observed`, after its value is checked against the candidate.
4. **Evidence and tests.**
   - `test_observed_template_bases_equal_painter_files` (`tests/export/test_export_encoders.py`) writes the empty base of each of the six goldens through `WriteExport`, at every export step. That is 18 files: OpenEXR 32f, plus PNG 16 for the three new goldens. Each must be byte-identical to Painter's r1 and r2.
   - The refusal tests and the `srgb8-inferred-template-base` conformance case move from Unreal Engine to Blender, which is still inferred.

## Consequences

- BaseColor and Specular of the five templates export exactly at every format the evaluator writes.
- Item 2.6 stays open. It closes when the 21 requests are recorded and admitted. Owner action: one Legacy Painter session (§11.4), about 21 small goldens.
- The capability context `srgb8-inferred-template-base` stays a release gap. Its notes now name the five observed templates.
