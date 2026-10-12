# 126. sRGB8 material channels are written as the GPU sRGB encode of a linear read-out; inferred template bases stay refused

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.23_pyapi-pipeline-adapter, phase1.24_python-api-facade

## Context

Item 2.6 of `phase1.25_pilot-wand` took over decision 103's sRGB8 material-channel gap. Decision 103 left two problems. PNG 16 missed by up to one code on 65 to 72 of the 258 distinct values. The evaluator also held these channels' template constants as export values. This fit used recording R-090 on main: `export-bit-depth` (P10), with `export-ocio-encode-legacy`, `export-padding-bevelled-cube` and `export-padding-sphere` as held-out checks. Only numbers are used here; the files stay in the private store.

- **The linear value.** Every OpenEXR 32f value of a stored BaseColor, Specular or Emissive is `arith::Srgb8Operand(code)`, the recording GPU's sRGB8 decode (256 of 256 codes). Painter's OpenEXR 16f file holds the same value as a half, because those decodes are halves. The two other values are template constants: `float32(0.8)` (empty BaseColor) and `float32(10/255)` (empty, added sRGB8 Specular). An empty, added sRGB8 Emissive exports 1.0.
- **The encode.** `x <= 0.0031308 ? 12.92 x : fma(1.055, exp2(0.41666 log2 x), -0.055)` in float32, with the recording GPU's `log2` and `exp2` (`hw::Pow`), then `arith::WriteUnorm` at the file's depth. This is the encode that decision 091 found for probe P5, which phase1.18 had not reused.
  - 258 of 258 values are exact at PNG 16 and PNG 8, on r1 and r2.
  - Encoding Painter's own OpenEXR 32f file reproduces its PNG 16 and PNG 8 files of the same map on 134 of 134 map pairs in four goldens. The pairs include `export-ocio-encode-legacy` (bitmaps in sRGB and Raw, uniform colours in sRGB, Raw and none, opacity 0.25 over the base) and the two padding goldens.
  - The exponent matters. With exactly 1/2.4, every pow and rounding variant misses 64 to 72 values: that was phase1.18's residual. Exponent 0.41666 with the hardware pow, or with a correctly rounded float32 pow, gives the same codes on all 256 decodes.
- **Uniform colours.** A colour with no space, or in sRGB, on these channels is decoded to linear. A Raw or Working colour is taken as linear. Both are then stored through the GPU's sRGB8 conversion. This is decision 107's facade rule (`uzpainter_facade.colour`). The six recorded values match it, and so does `export-bit-depth` s2 and s6 end to end.
- **Template constants.** Only the default template's BaseColor is observed linear (OpenEXR 32f: `float32(0.8)`). For the 25 other templates only a PNG 16 code is recorded: 59397 (four OpenPBR templates), 48107 (18 templates) and 14330 (four sRGB8 Specular templates). A range of floats writes each code; for 48107 that is every float32 from 0.4980261 to 0.4980471. So the linear base is not identified. `float32(0.8)`, `float32(127/255)` and `float32(10/255)` are the candidates.

A Codex source review (relayed by the coordinator) raised two points:
1. Channel defaults observed on sRGB8 only must not apply to every format.
2. An inferred base must not be presented as an exact linear read-out.

Both are adopted below. The model panel was not consulted: both points come from a review and leave nothing to choose.

## Decision

1. **The export** (`src/export/encode.{h,cpp}`, `plan.{h,cpp}`).
   - A PNG of an sRGB8 BaseColor, Specular or Emissive document map, its luma included, writes the encode above at the file's depth (`FileRaster::srgbEncoded`, `SrgbEncodedOnExport`).
   - OpenEXR files keep the linear value.
   - An sRGB8 User channel stays linear. Any other sRGB8 channel (EmissionColor, Diffuse, CoatColor, ...) is refused before writing as not recorded.
   - The refusal of the luma of an sRGB8 base constant is removed: that constant is now linear.
2. **Template constants** (`assets/templates/*.json`).
   - The sRGB8 BaseColor and Specular bases hold linear values.
   - `default` BaseColor is `float32(0.8)`, kind `observed`.
   - The other 25 entries are kind `inferred` (new; EVALUATOR.md §3): `float32(0.8)`, `float32(127/255)` and `float32(10/255)`. Each note records the PNG 16 code and the candidate.
   - The export refuses every file whose values depend on a channel whose base is `inferred`, in any format, before anything is written (`RequireIdentifiedBase` in `plan.cpp`; `unsupported_source`, `NotYetSupported` in the Python API). That covers the documentMap of the channel (sRGB8, RGB16, ...) and the diagnosticMap sources that read it (`isolated`, `contribution`, `regionStats`, `materialView` and the non-ID `materialLeaks`, which compares the channel's full and solo read-outs). Diagnostics on a template whose base is observed keep working. The evaluator itself still evaluates these constants: the base-values goldens compare their PNG 16 codes, which every candidate in the range writes.
3. **Channel defaults.**
   - `channel-defaults.json` gains Specular (`float32(10/255)`) and Emissive (1.0). Both are restricted to `"format": "sRGB8"`, the only format recorded.
   - A channel-defaults entry may now name a format (`TemplateLibrary::BaseChannel`). On another format, the channel fails with `missing_base_value`, as before.
4. **Evidence and gates.**
   - `parity/semantics/export-processing.json` entry `srgb8-material-channels` is exact, with residuals.
   - Written end to end, export-bit-depth's material maps on s0-s3 and s6 are 60 files and 120 of 120 comparisons byte-identical to Painter (r1 and r2) at PNG 8, PNG 16, OpenEXR 16f and OpenEXR 32f. s4, s5 and s7 fill these channels from grey 16-bit bitmaps in the sRGB space. The evaluator refuses those before writing (phase1.14_compositor-core, `sources.h`), and Painter's files of them are not compared.
   - Tests:
     - `test_processing_reproduces_painter_files`: the material maps of export-bit-depth in PNG 8, PNG 16 and OpenEXR 16f;
     - `test_srgb8_material_channels_equal_painter_files`: written end to end;
     - `test_srgb8_material_channels_are_written_encoded`;
     - `test_no_export_reads_an_inferred_template_base` (documentMap on sRGB8 and RGB16, and five diagnosticMap kinds, against the default template's diagnostics);
     - `test_five_map_preset_writes_basecolor_srgb_encoded`;
     - `test_luma_probe_exact`, now on s1 too;
     - `test_base_values_equal_the_empty_project_exports`, which encodes the constant.
   - The capability context `srgb8-material-channels` is replaced by `srgb8-inferred-template-base` (a release gap in both packages; its conformance case uses the Unreal Engine template and must name this decision).
   - The pipeline adapter's wand test also waits on `padding-islands` (item 2.7). The wand uses the default template, so its BaseColor no longer blocks.

## Consequences

- Integration note (from the Codex review): any host recipe that asks the template library for a base value must pass the stack channel's real format (`BaseValue(template, type, format)`). Without it, the sRGB8-only Specular and Emissive defaults are refused.

- The wand's BaseColor (default template) is exported exactly. Its five-map export is still refused, because `infinite` padding on its UV islands is not fitted (decision 127).
- Exporting BaseColor or Specular on any shipped template other than `default` waits for a recording. The recording is an OpenEXR 32f export of the empty channel: one template with code 48107 (for example Unreal Engine), one OpenPBR template and one sRGB8-Specular template. Owner: `phase1.25_pilot-wand` (owner action: a Painter session).
- Specular and Emissive added in a format other than sRGB8 remain unsupported (`missing_base_value`) until recorded.
