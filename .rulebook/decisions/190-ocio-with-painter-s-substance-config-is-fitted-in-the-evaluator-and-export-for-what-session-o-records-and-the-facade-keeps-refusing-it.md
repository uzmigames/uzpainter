# 190. OCIO with Painter's substance config is fitted in the evaluator and the export for what Session O records, and the facade keeps refusing it

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.15_compositor-colour-fits, phase1.25_pilot-wand, phase2.1_preview-viewport-window, phase3.3_unreal-gltf-presets

## Context

Item 2.3 of `phase1.15_compositor-colour-fits` fits OCIO colour management against the Session O goldens, admitted by decision 180:
- `tier0/semantics/export-ocio-encode`: R5 under OCIO, with the same sets and steps as its Legacy twin `export-ocio-encode-legacy`, which is already exact (decisions 145, 152 and 174).
- `tier0/semantics/export-presets-ocio`.

Session O ran with `OCIO` set to Painter's `resources/ocio/substance/config.ocio`, the file decision 134 pins by SHA-256 `15059d4b…`. That file is never read.

Measured on the private store (counts only):

1. **What OCIO changes.** The two R5 goldens share 144 of their 162 common records byte for byte. The probe files differ only in their names (`$colorSpace`). 16 exported maps differ, r1 and r2:
   - **The PNG 16 of BaseColor.** It differs on every set but s2 and s6.
   - **s4 BaseColor** (the authored 8-bit ramp in Raw) in all three formats.
   
   Every PNG 8 and OpenEXR 32f file of the other sets is identical. So are every non-BaseColor map and Normal_OpenGL.
2. **PNG 16 of an sRGB8 BaseColor.** It is a function of the stored code, recorded for all 256 codes by s3 (each code at many texels, one value each, r1 = r2) and for the empty BaseColor (float32(0.8), 59396) by s7.
   - It differs from the Legacy encode on 74 of the 257 values, by one code.
   - The IEC encode rounded to nearest misses 14 of them. OpenColorIO 2.4.2's `ExponentWithLinearTransform` (2.4, 0.055), evaluated in its exact and fast-power modes, misses 15 and 35. A 1D LUT inverse (256 to 65 536 nodes, several value precisions) misses at least 11.
   - The codes of the operands 5k·2⁻¹⁴ (k = 1..10, the sRGB8 decodes of codes 1-10, all on the linear segment) step by 259 twice in a row (1033 → 1292 → 1551). No rounding of a linear function of k does that. So no analytic transfer function evaluated on the operand reproduces it.
   - The exactness hunt was stopped at the time cap. The rule is the measured table.
3. **8-bit Raw bitmap on BaseColor (s4).** Legacy reads code c as float32(c / 255). Under OCIO, four codes store one code lower: 176, 245, 247 and 254. Code 254 needs a value at least 2.3·10⁻⁴ lower, so only a coarse quantisation explains it.
   - float32(c / 255) rounded toward zero to a binary16 stores all 256 codes exactly. This is the conversion Painter's OpenEXR 16f export uses (recording R-090 P2, `src/export/encode.h`).
   - Rounded to nearest, it misses 7.
4. **Facade readbacks.** Painter's working value of an sRGB uniform colour (`get_source`) differs from the facade's float32 rule on all six recorded components, by 1·10⁻⁷ to 7·10⁻⁶ relative. Examples: (0.2, 0.5, 0.8) reads back (0.0331045575, 0.2140414566, 0.6038273573) against (0.0331047624, 0.2140411437, 0.6038274169).
   - Neither OCIO 2.4.2 mode reproduces it.
   - The bitmap listing has eleven spaces: Raw, Working, sRGB, Linear, sRGB, Rec709, Rec2020, ACES - ACEScg, Display P3, ACES sRGB and False Color.
   - The stored codes of those colours are the Legacy ones (s0, s1, s6 PNG 8 identical).
5. **`$colorSpace`.** In the probes, a PNG of BaseColor is named `sRGB`, and a PNG of SpecularRoughness or Height is named `Raw`. Under Legacy the wildcard is empty.

## Decision

1. **The configuration.** `evaluator::PainterOcio`: mode `ocio` with config hash `kPainterOcioConfigSha256` (`src/evaluator/sources.h`). The evaluator (`CheckColourManagement`, `support.cpp`) and the export plan admit it next to Legacy. Any other OCIO configuration still fails before anything is evaluated.
2. **Sources under it.** These are evaluated, each as Legacy does except where stated:
   - uniform colours;
   - an 8-bit colour bitmap in sRGB on an sRGB8 channel at 1:1;
   - a 16-bit grey bitmap in a linear space as a mask source at 1:1;
   - an 8-bit colour bitmap in Raw on an sRGB8 channel at 1:1, whose texels are the binary16-toward-zero values above (`OcioRawDecoded`, a float32 image like the sRGB decode, so the GPU projection is unchanged).

   Every other bitmap use fails with `unsupported_source` before any mutation (`OcioBitmapGap`) or at evaluation (`CheckOcioBitmap`: image kind and 1:1). That covers another space or channel, 16-bit fills, grey fills and any resampling.
3. **Export.**
   - An sRGB-encoded channel's PNG 16 writes the measured table (`OcioSrgbPng16Code`, `src/export/encode.cpp`). PNG 8 and OpenEXR are unchanged.
   - A value outside the 256 codes and float32(0.8) fails before writing. A luma or another default is such a value.
   - Under OCIO, `$colorSpace` is `sRGB` for a PNG of one sRGB8 BaseColor and `Raw` for a PNG of non-sRGB8 document channels. Every other file naming `$colorSpace` is refused as not recorded.
4. **Evidence.** `export-ocio-encode` is rebuilt per set as an OCIO project and written by `WriteExport`. That covers every map of steps 46-49 plus the `$colorSpace` probes 50 and 51: 128 files, 251 of 251 comparisons byte-identical (r1, and r2 wherever r2 = r1), and 48 of 48 probe names. s5's BaseColor is unstable in Painter (5 files), so r1 is its exact target (decision 032). EXC-006 is not extended, because its bounds (619) do not cover this golden's r2 (620). The test is `tests/export/test_export_encoders.py::test_ocio_encode_equals_painter_files`.
5. **What stays refused.**
   - **The facade's OCIO profile.** The Python facade keeps raising `NotYetSupported` for an OCIO project (`colour.require_supported_configuration`), because its readbacks are measurably not Painter's (fact 4). This is item 2.6 of this task. It is settled by a recording of the dense uniform decode under OCIO (P20-B's OCIO twin) and by the eleven-space listing.
   - **The Wand pilot (phase1.25)** runs under OCIO through the facade, so it stays blocked on item 2.6.
   - **`export-presets-ocio`** (every map r1 = r2): per-preset pixel parity belongs to `phase3.3_unreal-gltf-presets` item 3.5, as for its Legacy twin. Its names record `$colorSpace` beyond the probes: `Raw` for normal (a virtual map), metallic and displacement. The plan admits `Raw` for document channels only, so a virtual map named with `$colorSpace` under OCIO stays refused until that parity work.
6. **Preview.** `painter_viewport` evaluates through the same evaluator. It now renders an OCIO project's sources within item 2's domain, and every other source fails as in the export.
7. **Capabilities.** `compositor:ocio` is `supported` with `tier0/semantics/export-ocio-encode`. The new `compositor:ocio-unrecorded` (release gap, item 2.6) lists what stays refused.

The model panel was not consulted. Each rule is what the recording shows; facts 2 and 3 name the only candidates exact on every value.

## Alternatives Considered

- **Fit an analytic OCIO encode.** Not found within the time cap, and fact 2 rules out every function of the operand that is linear on the low segment. The table covers the whole domain an sRGB8 channel can hold.
- **Lift the facade with the Legacy uniform rule.** Rejected. Its readbacks differ from Painter's on every recorded component, and "only where exact" forbids it.
- **Judge s5's r2 through EXC-006.** Rejected. This golden's r2 residual (620) exceeds the entry's bound (619), and r1 is met exactly.

## Consequences

### Positive
- An OCIO project with Painter's substance config evaluates and exports byte-identically to Painter for every set of `export-ocio-encode`. It no longer stops at the evaluator.

### Negative
- The PNG 16 encode under OCIO is a 257-entry measured table, not a formula.
- The facade, and so the Wand pilot, still refuse OCIO until item 2.6 is recorded and fitted.

## Amendment (2026-11-02, Tunic v10 current round, front S3)

Decision item 5 kept a virtual map named with `$colorSpace` under OCIO refused. The Tunic v10 current-round rebuild names its normal through the Blender preset's `$textureSet_Normal(_$colorSpace)`, so it stopped at plan time. Codex root gave the GO for one case, on admitted records (names and hashes read from the private store, no values):

- `export-presets-ocio` (12.2.0 envelope), record `18ca9d7dbf8a82ab3a74ce79cf76c82547d3bcce5267115aea5075dab825dbc0`. Readback s31 gives the starter Blender preset's Normal map as R, G and B of virtualMap Normal_OpenGL, PNG 16, no dithering. Step 35 (that preset, the pipeline's PNG 16 parameters) writes `uzp_bevelled_cube_Normal_Raw.png`, 16-bit RGB PNG, `18651397cc8debcdb0182bc56ce61545add60cb6b1ffa99046000b4ebec6dd65`, in r1 and r2. Step 36's inline `uzp_staff_Normal.png` has the same hash. The 12.1.5 record `9e84c5d35661be308385a64d74be8b9003f038a975d744f1e138ff95ff6d3aec` gives the same name and hash.
- `tunic-v10`, record `59ef801eaf67c74879e3f5ec51dc526da110ce80fc364c4e366f2ba2582701bf` (decision 215), export configuration `7167a93e…`: `DefaultMaterial_Normal_Raw`, 16-bit RGB PNG, `f372fdf3efbdddf2d5de0139d8b47c81c97e36c9d07154d9b3821b6c1d94c540`, in r1, r1-repeat and r2.
- Both ran under `OCIO` = `resources/ocio/substance/config.ocio` (`15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4`; `8f384af9…` is the records' aggregate colour-configuration hash, not this file's).

The rule: `OcioColourSpace` (`src/export/plan.cpp`) also gives `Raw` for a PNG 16 RGB file whose R, G and B read R, G and B of virtualMap Normal_OpenGL (`OcioNormalOpenGlPng16`), under the same profile guard (`PainterOcio`). Everything else stays refused: that file at PNG 8, as OpenEXR, as L, swapped or as luma, every other virtual map, and a file mixing it with document channels. Normal_DirectX stays refused too, although step 33 of the same record (the starter PBR Metallic Roughness preset) names its PNG 16 `Raw`. The test is `tests/export/test_export_plan.py::test_ocio_colour_space_of_normal_opengl_png16`.

This settles the name only. The encode of that file is already covered: `export-ocio-encode` record `20e36255ea7282c406a0aae1d5203c00e9d304b2cd02a4908d62dc4969fddde1`, step 49, through `test_export_encoders.py::test_ocio_encode_equals_painter_files`. It does not prove the Tunic's pixel parity. The shipped Blender preset itself is still refused before planning, because its layout is `unconfirmed` (R-095, decision 095).
