# 349. Export resize (upscale, downscale by half) and PNG 8 dithering on integer channels are exact; the rest stays refused

**Status**: accepted
**Date**: 2026-10-22
**Related Tasks**: phase3.2_unreal-ue56-packed-preset (item 2.9), phase1.25_pilot-wand (item 2.7)

## Context

Decision 103 refused dithering at PNG 8, dithering in OpenEXR and every resize. Item 2.9 fits them against the admitted recordings `export-dither` (R-090 P3) and `export-resize` (R-090 P4). Measured on Painter's own files, r1 and r2 (identical in both goldens); numbers only:

- **Dithering at PNG 8.** On an RGB16 channel (User0) and an sRGB8 BaseColor it changes nothing: 0 texels on s0 to s3, under infinite and passthrough padding. On float channels (User1 L16F, User2 RGB32F, Height L16F) and the virtual normals it changes up to one code at 17 000 to 62 000 texels per map. It is deterministic and nearly a function of texel position. Two L files share the noise, but the R, G and B channels each have their own. It is not periodic up to 128, and it is not error diffusion (Floyd-Steinberg, Atkinson, JJN and Sierra all miss about 20 000 texels). It reaches about ±0.75 code, and pairs of sets disagree by a few hundredths of a code at 600 to 1 300 texels. Within the time box it is not fitted.
- **Upscale** (sizeLog2 9 and 10, PNG 16 and OpenEXR 32f, passthrough at 9). The file equals UzPainter's CPU evaluation of the texture set at the file's size at every texel. This holds for BaseColor (sRGB8), User0 (RGB16) and Height (L16F) on s0 to s3 (Nearest and BilinearHQ), and for Normal_OpenGL and Normal_DirectX on s0 and s2. On s1 (not square) and s3 (a bilinear 16-bit normal) the evaluator refuses the normals itself.
- **Downscale** (sizeLog2 7 on 256 x 256; probes [8, 7] and [7, 8]). Each texel is the mean of the 2 or 4 texels it covers in the set's evaluation, taken in one step and stored in the channel's format:
  - RGB16: the nearest 16-bit code, with a 2-texel tie rounding up (the impulse texel).
  - L16F: the nearest half, ties away from zero. Ties to even miss 1796 texels, and a two-step mean misses 1184.

  This is exact for User0 and Height at PNG 16, OpenEXR 32f, PNG 8 and passthrough PNG 16. It is not evaluation at the smaller size, which misses 11 000 to 14 000 texels. The data has no 4-texel RGB16 tie. sRGB8 BaseColor is not reproduced: averaging the linear values and rounding them in the encoded domain misses 13 156 texels. The virtual normals after a downscale are not fitted.
- **Sizes.** Painter writes no side below 128. sizeLog2 6 on a 256 set is written at 128, and sizeLog2 7 on 256 x 128 at 256 x 128. The plan names the requested size.

## Decision

1. **Shipped** (`src/export/resize.{h,cpp}`, `write.cpp`, `guards.cpp`):
   - **Upscale.** Each side is the set's times a power of two, and one side is larger. The file is evaluated on the project with its texture set at the file's size. Admitted for RGB16 and L16F channels, an sRGB8 BaseColor, and Normal_OpenGL and Normal_DirectX, at PNG 16 and OpenEXR 32f.
   - **Downscale.** Each side is the set's or half of it. The file is the single-step mean above. Admitted for RGB16 and L16F channels at PNG 8, PNG 16 and OpenEXR 32f. A 4-texel RGB16 tie fails the evaluation (`unsupported_source`) before anything is written.
   - **Padding.** Both resizes need the coverage to be complete at the set's size and at the file's size, under infinite or passthrough padding.
   - **Dithering at PNG 8** is admitted when every channel reads an RGB16 channel or an sRGB8 BaseColor, at the set's size.
2. **Refused before writing** (`NotYetSupported`, naming this decision and item 2.9):
   - dithering at PNG 8 on any other source;
   - dithering in OpenEXR;
   - dithering with a resize;
   - a resize to a side below 128;
   - a mixed or non-power-of-two resize;
   - a resize at OpenEXR 16f, or an upscale at PNG 8;
   - a downscaled sRGB8 channel, virtual normal or other source;
   - an upscale of any other source;
   - a resize on a set whose UV islands leave texels uncovered (Painter's padding around a resize; see also phase1.25 item 2.7).
   - The paddings `color`, `transparent` and `diffusion` stay refused (item 2.9).

## Consequences

- `tests/export/test_export_resize.py` and `test_export_dither.py` replay the admitted goldens on the lifted cases and check every refusal above, before writing.
- The upscale evaluates a copy of the project at another resolution. This is exercised on the CPU evaluator. The DX12 lane runs it in the coordinator's GPU batch.
- Item 2.9 stays open for PNG 8 dithering of float channels and virtual normals, OpenEXR dithering, sRGB8 and virtual-normal downscales, and the dilation paddings.
