# 103. The export writes PNG 8, OpenEXR 16f, signed Height, alpha layouts and pass-through mesh maps exactly; the unfitted remainder is split with named owners

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.18_export-engine, phase1.16_export-processing-encoders, phase1.25_pilot-wand, phase3.2_unreal-ue56-packed-preset, phase3.3_unreal-gltf-presets

## Context

Item 6.1 of `phase1.18_export-engine` took over everything phase1.16 refused (decision 090). Recording R-090 is now admitted on main (decision 101): `export-bit-depth`, `export-dither`, `export-resize`, `export-alpha-layouts`, `export-padding*` and `export-ocio-encode-legacy`. `export-presets-legacy` crashed Painter, and the OCIO preset and encode requests are not recorded. Painter is now in the owner's hands, so no new recording can be planned. Each fit was time-boxed at about 2 hours: exact, or refused.

Measured on Painter's own files (numbers only; the files stay in the private store):

- **PNG writer.** 8-bit grey files take the row filter with the least cost among all five filters, and compress with zlib's `Z_DEFAULT_STRATEGY`. Every other layout takes the least-cost filter among None, Sub and Paeth only, and compresses with `Z_FILTERED`. Both rules hold for every file: 76 of 76 8-bit grey files and 1773 of 1773 others. The phase1.16 encoder used the three-filter rule everywhere, and the two failing encoder tests on main came from that. Decoded and encoded again, every distinct file of the envelope is byte-identical: 1826 PNG and 823 OpenEXR. The OpenEXR files include HALF channels and the `A, Y` layout.
- **Values.** Each processing rule was checked by encoding Painter's own OpenEXR 32f file of a map and comparing the result with Painter's other files of that map.
  - PNG 8 is `arith::WriteUnorm` at 8 bits of the 32f value.
  - OpenEXR 16f is the value rounded toward zero to a half.
  - A Height channel is written to PNG as `v * 0.5 + 0.5`, at 8 and 16 bits.
  - Result: 384 of 384 cases byte-identical (8 sets × 16 maps × PNG 8, PNG 16, OpenEXR 16f). The 16 maps are user and material channels plus the AO, Curvature, Position and normal_base mesh maps.
  - The evaluator's read-out equals Painter's 32f files for the User channels, Height, SpecularRoughness and Normal on those sets. Normal_OpenGL, Normal_DirectX and normal_base are exact at PNG 8 and OpenEXR 16f.
- **Mesh maps.** AO, Curvature and Position export the bound image's codes as their UNORM operands, at the set's size.
- **Alpha.** L+A and RGB+A are written as they are. An alpha of 1 everywhere is dropped, so the file is L or RGB: 4 of 4 files.
- **Dithering.** It changes nothing at PNG 16: 20 of 20 maps. At PNG 8 it is deterministic (the same-session repeat and r2 are identical), but it is not a threshold matrix: the threshold constraints contradict each other at 63449 of 65536 pixels, and no period from 2 to 128 fits. OpenEXR with dithering has no "off" twin recorded.
- **Resize.**
  - An upscale equals evaluating at the target size for Nearest sources and for non-normal BilinearHQ channels.
  - A downscale is a 2×2 box, stored in the channel's format: UNORM16 exact, and L16F with rounding half away from zero, exact.
  - Not reproduced:
    - sRGB8 channels (16700 texels on s0);
    - virtual normals after a downscale;
    - BilinearHQ normal-channel magnification (21888 texels at 512).
  - sizeLog2 6 is written at 128.
- **sRGB8 material channels** (BaseColor, Specular, Emissive).
  - PNG 8 is `WriteUnorm` at 8 bits of the IEC sRGB encoding of the linear 32f value: exact.
  - PNG 16 misses by up to one code on 65 to 72 of the 258 distinct values under every model tried: IEC encoding in double and in float; LUTs of 256 to 65536 entries with linear or nearest interpolation; half or significand-rounded decodes.
  - The evaluator holds these channels' template constants as export values, so the 32f value of a uniform or empty BaseColor differs: 196608 texels on s2.
- **Paddings.** `color`, `transparent` and `diffusion` with `dilationDistance`, and `infinite` on islanded sets, were not fitted within the time box. Phase1.16's partial fit (decision 090) stands.

The model panel (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5) was asked on claims C1–C5 below. The local proxy refused every connection, so no verdict came back, and the decision rests on the measurements above. The dossier is kept in the session's scratch:

- C1: 6.1 is a recorded scope split.
- C2: the sRGB8 material channels and `infinite` on islands go to phase1.25.
- C3: dithering, resize and the dilation paddings go to phase3.2_unreal-ue56-packed-preset.
- C4: 6.2 goes to phase3.3.
- C5: a new child task, as the alternative to C2.

## Decision

1. **Shipped exact** (`src/export/`, `EXPORT.md` §4):
   - the PNG writer's layout-dependent rule;
   - OpenEXR HALF and `A, Y` channels;
   - PNG 8 values and OpenEXR 16f values;
   - Height written signed to PNG;
   - L+A and RGB+A, with the all-opaque alpha dropped (the receipt records the written layout);
   - dithering at PNG 16;
   - sRGB8 User channels in OpenEXR;
   - the AO, Curvature and Position mesh maps.

   `tests/export/test_export_encoders.py::test_processing_reproduces_painter_files` and the published `parity/semantics/export-processing.json` carry the evidence.
2. **Refused before writing** (`NotYetSupported`). Each refusal names recording R-090 and this decision:
   - dithering at PNG 8 and in OpenEXR;
   - resize;
   - the dilation paddings;
   - `infinite` on islanded sets;
   - sRGB8 material channels.

   The alpha layouts are also refused on islanded sets.
3. **Scope split of item 6.1** (the pattern of decision 069). The gaps stay visible in `parity/semantics/export-processing.json` (status gap, with the owner), in the report `parity/reports/phase1/export-engine.md` and in the refusal messages.
   - **sRGB8 material-channel export** (PNG 16 encode and a linear read-out of export-valued constants) and **`infinite` padding on islanded sets**: new items in `phase1.25_pilot-wand`. Wand v1 is the first export that needs both (BaseColor through the five-map preset, on a real mesh). Its maps-equal gate cannot pass without them, so the blocker stays on the critical path.
   - **Dithering at PNG 8 and in OpenEXR, resize, and the `color`, `transparent` and `diffusion` paddings**: new items in `phase3.2_unreal-ue56-packed-preset`, the first preset with 8-bit output and dilation. Until then they are release gaps.
4. **Scope split of item 6.2.** Per-preset parity needs recording R-095, which cannot be made now. It moves to `phase3.3_unreal-gltf-presets`. `pbr-metallic-roughness` and `blender-principled-bsdf` stay refused while their layout is `unconfirmed`, so nothing is claimed.

## Consequences

- The two red encoder tests on main pass. Phase1.20's facade can drop its exclusion of Height PNG maps (the old writer wrote `round(h * 65535)`).
- Phase1.25's acceptance now explicitly includes the BaseColor encoding and the island padding; G1 waits on them there, not in a hidden gap.
- No approximate fit was shipped. The partial resize and padding models are recorded as fits, not as behaviour.
