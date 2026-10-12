# 145. 8-bit colour and 16-bit grey sRGB bitmaps at 1:1 on sRGB8 channels are fitted, and the other sRGB bitmap uses wait for one recording

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.15_compositor-colour-fits, phase1.25_pilot-wand

## Context

Item 2.2 of `phase1.15_compositor-colour-fits` fits the sRGB bitmap uses other than a 16-bit colour bitmap sampled 1:1 onto an sRGB8 channel. The Wand v1 pilot (phase1.25) is blocked by one of them: its `T_base` is an 8-bit sRGB colour bitmap, and the evaluator refused it with `evaluator:unsupported_source` in `SrgbDecoded` (`src/evaluator/evaluate.cpp`).

The item asks to measure the admitted goldens first. A scan of every admitted manifest of the current envelope for a bitmap source in the sRGB space (set explicitly, or on BaseColor, Specular or Emissive with no space, where Painter's default applies) gives the following:

| Golden | Bitmap | Channel | Sampling | Space |
|---|---|---|---|---|
| `export-ocio-encode-legacy` s3 | `srgb8-ramp`, 8-bit RGB, 256 px, every code 0-255 in each channel | BaseColor (sRGB8) | UV, BilinearHQ, RepeatNone, identity, 1:1 | sRGB, set |
| `export-ocio-encode-legacy` s5 | the same ramp, in a group masked by grey A | BaseColor | 1:1 | sRGB (item 2.4: unstable) |
| `export-bit-depth` s4, s5, s7 | `height-ramps`, `grey-a`, 16-bit grey | BaseColor, Specular, Emissive | Fill, 1:1 | default |
| `export-dither` | `height-ramps`, `grey-a`, 16-bit grey | BaseColor | 1:1 | default |
| `export-bit-depth` s0-s1, `virtual-maps-*`, `export-probes-*`, `export-padding*`, `export-resize`, `view-2d-state-*` | 16-bit colour | BaseColor and the other sRGB8 material channels | 1:1 | default |

No admitted golden holds an 8-bit grey sRGB bitmap, a resampled sRGB bitmap, an sRGB bitmap on a channel that is not sRGB8, an sRGB mask source, or a bitmap in the Working or Linear space. Every bitmap above is sampled 1:1.

Measured on recorded data (private store, counts only):

- **8-bit colour.** `export-ocio-encode-legacy` s3 BaseColor equals the ramp's own codes, taken as sRGB8 codes, on every texel of PNG 16 (step 46, through the sRGB8 decode and the 16-bit sRGB encode), PNG 8 (step 47) and OpenEXR 32f (step 48, the sRGB8 decode), in r1 and in r2. The linear reading c / 255 (the Raw rule, which s4 confirms exactly) misses 195 072 of 196 608 values in each. The code is also what the 16-bit rule gives: an 8-bit code c is the 16-bit code 257 c (float32(c / 255) is float32(257 c / 65535)), and the sRGB decode of it stores c through the double-precision decode and through the GPU's float32 one for each of the 256 codes. Whether Painter decodes in hardware or in a shader, the stored code is c.
- **16-bit grey.** `export-bit-depth` s7 BaseColor (grey A, no space set) equals the 16-bit rule applied to the grey code on each of the three channels, on every texel of its eight BaseColor exports (PNG 8, PNG 16, OpenEXR 16f and 32f, each done twice), r1 and r2. The linear reading misses 195 072 of 196 608 values. So Painter decodes a grey bitmap on BaseColor as sRGB and feeds the grey to the three channels.

End to end, through the plan and `WriteExport` (`uzp-export-tests export`), the rebuilt texture sets are byte-identical to Painter's files:
- `export-ocio-encode-legacy` s3 and s4 BaseColor at steps 46-48: 6 files, 12 of 12 comparisons;
- `export-bit-depth` BaseColor, Specular and Emissive on all eight sets: 96 files, 192 of 192 comparisons. This includes s4 (`height-ramps` twice in LinearDodge) and s5 (grey A in SignedAddition) on the sRGB8 channels, which were refused before.

## Decision

1. An sRGB bitmap sampled 1:1 onto an sRGB8 channel is evaluated for three image kinds (`SrgbDecoded`, `src/evaluator/evaluate.cpp`; rule in `sources.h`):
   - a 16-bit colour image, as before;
   - a 16-bit grey image: the decode of each grey code feeds the three channels;
   - an 8-bit colour image: each code is its own sRGB8 code.

   The decoded image is always an 8-bit three-channel image of the bitmap's size.
2. Still refused with `evaluator:unsupported_source`, naming `phase1.15_compositor-colour-fits`:
   - an 8-bit grey sRGB bitmap;
   - a resampled sRGB bitmap;
   - an sRGB bitmap on a channel that is not sRGB8, or as a mask source;
   - the Working and Linear bitmap colour spaces.

   The 8-bit grey case follows from the two fitted rules, but no golden shows it. It stays refused, because the item lifts only what is exact on recorded data. `support.cpp` and the `not-yet-supported` case do not change, because they never refused the lifted kinds: only `SrgbDecoded` did.
3. One Tier 0 recording settles every refused variant: `tier0/semantics/srgb-bitmap-variants`, under Legacy on the 4x2 grid at 256 px. Each set exports at PNG 16, PNG 8 and OpenEXR 32f, and reads back `get_color_space` and `list_available_color_spaces`.
   - s0: an authored 8-bit grey ramp (every code 0-255) on BaseColor at 1:1, set to sRGB. Settles the 8-bit grey case.
   - s1-s3: field A (16-bit) and `srgb8-ramp` (8-bit) on BaseColor, set to sRGB. The UV projection is BilinearHQ with scale (2, 2), rotation 30 and offset (0.1, 0.2) in s1; BilinearHQ at scale (0.5, 0.5), which minifies, in s2; and Nearest at scale (2, 2) in s3. Settles resampling.
   - s4: field A set to sRGB on User3 RGB16, User1 RGB8, User5 RGB16F, User7 RGB32F, User2 L8 and User4 L16. Settles the other channel formats.
   - s5: grey A as a mask fill effect's source, with `set_color_space(sRGB)` attempted. The recording keeps Painter's refusal if it refuses: the facade's recorded listing for a mask source offers only Raw, Data and DataSigned. Settles the mask source.
   - s6-s8: field A on BaseColor in Working, in Legacy Linear and in Legacy sRGB. Settles the Working and Linear spaces.
4. The capability entry `compositor` of `SourceBitmap.set_color_space` cites `export-ocio-encode-legacy` and `export-bit-depth`. `compositor:srgb-unrecorded` lists only what stays refused.

## Alternatives Considered

- **Lift 8-bit grey by composition.** Rejected: it is unrecorded. The derivation above is strong, but the item's rule is exactness on recorded data, and s0 of the recording above settles it cheaply.
- **Fit the 8-bit case as the 16-bit formula on c / 255 instead of copying the code.** Not needed: the two are equal for each of the 256 codes, and the native `sources` case asserts that equality.

## Consequences

### Positive
- The Wand's `T_base` evaluates when it is sampled 1:1 onto BaseColor under Legacy. If it is not the size of the texture set, the resampled refusal applies. The pilot golden `wand-v1` is specified under OCIO (decision 101), which item 2.3 owns.
- export-bit-depth's sRGB8 material channels are exact on every set, not five of eight.

### Negative
- Item 2.2 stays open for the five refused variants until `srgb-bitmap-variants` is recorded (an owner action at Painter).
- Painter's default colour space of a grey bitmap on BaseColor, as the facade reports it, is still item 2.1 (P20-A). The output shows a decode, but no readback of that tag is recorded.
