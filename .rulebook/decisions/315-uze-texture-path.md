# 315. UzEngine texture path: etcpak 2.1 behind a BC adapter with fixed settings, 16-bit power-of-two mip chains with pow-free sRGB, and a `.uztexture` writer whose header declarations win over its comments

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase3.1_uze-uztexture-writer, phase3.4_uzengine-preset, phase3.2_unreal-ue56-packed-preset

## Context

`phase3.1_uze-uztexture-writer` needs a deterministic BC encoder, mip chains per map class and a `.uztexture` writer (`08-export.md` §3, §4). The proposal fixes etcpak with bc7enc, but leaves open the settings, the mip arithmetic, how the writer reads the vendored header where its comments contradict its declarations, and what the test-only decoder is.

## Decision

1. **Vendoring.** etcpak release `2.1` (tag commit `7f15da47`), the archive pinned by SHA-256 in `tools/vendoring/thirdparty.py`. All 59 files of UzEngine's copy are byte-identical to the archive. Vendored: the BC units (`ProcessDxtc`, `bc7enc`, `Dither`, `Math.hpp`, `ForceInline.hpp`), bcdec (`bcdec.h`, `bcdec.c`), `LICENSE.txt`, `AUTHORS.txt`. Compiled into the static library `uzp_texture` and its tests, not into `UzPainter.exe`, until the UzEngine preset (phase3.4) links it. etcpak is compiled with `-ffp-contract=off`.
2. **Encoder adapter** (`src/export/bc_encoder.h`).
   - `BcEncoder` is the backend interface; etcpak is the backend. bc7enc_rdo can replace it behind the same interface.
   - The image is padded to whole blocks by repeating the last column and row.
   - Workers take contiguous ranges of whole block rows and write each block at its row-major offset. The thread count changes which worker writes a block, never its bytes.
   - Fixed settings:
     - BC1, BC3, BC4 and BC5: etcpak's single-pass fit, no dithering;
     - BC7: bc7enc's defaults (all modes, 64 partitions, uber level 0, least squares, mode 1/7 filter bank), with perceptual weights for BC7 sRGB and uniform weights for linear BC7.
   - The sRGB variants of BC1 and BC3 encode the same bytes as their UNORM twins; only the metadata differs.
3. **Mips** (`src/export/mips.h`).
   - Full chains. Each level is the 2x2 box of the level above, computed at 16 bits and quantised to 8 bits only for the encoder.
   - Power-of-two sides only. Other sizes are refused, because a 2x2 box does not tile them.
   - Per map class:
     - Linear: the rounded integer mean.
     - Colour: decoded to linear light, averaged, re-encoded to the 16-bit code whose decoded interval holds the mean.
     - Normal: renormalised at every level, level 0 included; a zero sum becomes (0, 0, 1).
     - Masked colour: alpha scaled per level so that the count of texels whose 8-bit alpha exceeds the threshold is the one nearest to level 0's share. The scale is found by bisection over the sorted box means, and a tie keeps the higher count.
   - The sRGB x^2.4 is a fixed 40-step Newton fifth root, not the C runtime's `pow`. So the chain is only IEEE +, *, /, sqrt and integer arithmetic, and gives the same bits on every machine. It agrees with `std::pow` within 2.2e-16.
4. **Writer** (`src/export/uztexture_writer.h`).
   - It fills the vendored `UzTextureHeader` and `UzTextureMipLevel` and lays them out as the header documents. `WriteUzTexture` and `ReadUzTexture` stay unimplemented.
   - The header's validation comments say `flags == 0` and format 0..4, but its declarations define `kUzTextureFlag_sRGB` and `TextureFormat::BC4 = 5`, and `TextureFormatToRHI` reads both. The declarations win. sRGB BC4 and BC5 are refused, because the engine maps both to UNORM.
   - Each texture returns its metadata (binding, format, colour space, mips) for the preset's receipt.
5. **Normal guard.** `CookUzTexture` refuses a Normal-class BC5 map that has any texel with B <= 32767 (Z < 0). It throws `NegativeZNormal` with the count and the first texel, before anything is encoded. The plan option (fail or route to RGB) and its receipt record belong to the preset, `phase3.4_uzengine-preset`.
6. **Test-only decoding.**
   - Amendment, 2026-10-20: BC1/3/4/5 and all eight BC7 modes are decoded by UzPainter's own test-only code (`tests/export/bc_decoder.cpp`, `bc7_decoder.cpp`). BC7 format constants retain the pinned bc7enc MIT attribution. The BC1-5 integer convention preserves the prior CPU metrics; it does not claim exact GPU reconstruction. Sources and arithmetic: `docs/BC-DECODER.md`.
   - The vendored bcdec remains only an independent differential oracle. Its recorded local fix initialises alpha endpoints before RGB-only modes shift them; the authored corpus exposed the undefined read in ReleaseSafe. The same corpus passes with the fix and sanitizers enabled. This supersedes the original use of bcdec as the production test reader, satisfying item 2.8's own-code requirement.
   - The `.uztexture` reader and the lossy-derivative error (max, mean, p99 per channel and mip) are UzPainter's own code in `tests/export/`.

## Consequences

- Every BC format encodes to the same bytes at 1, 4, 7, 32 and 1000 workers.
- The mip and layout rules are pinned by `uzp-texture-tests` (`tests/export/test_uze_texture.py`).
- Non-power-of-two canonical maps cannot be cooked until a filter for them is declared.
