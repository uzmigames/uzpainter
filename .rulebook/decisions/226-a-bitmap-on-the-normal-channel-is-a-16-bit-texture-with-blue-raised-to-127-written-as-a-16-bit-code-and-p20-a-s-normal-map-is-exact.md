# 226. A bitmap on the Normal channel is a 16-bit texture with its 8-bit blue codes raised to 127, written as a 16-bit code, and P20-A's Normal map is exact

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.15_compositor-colour-fits

## Context

Item 2.9 of `phase1.15_compositor-colour-fits` (decisions 214 and 218) left P20-A's Normal map open (`tier0/api-probes/phase1-fill-channel-defaults`, PNG 16; r1 and r2 are byte-identical). The evaluator refused the grey bitmap on Normal (`evaluator:unsupported_source`: a Normal-channel bitmap had to be RGB), so the map was excluded from `test_facade_fill_channel_defaults_equal_painter`.

The Normal channel (RGB16F, OpenGL project) holds three fills, bottom up, each magnified 16 times by the default bilinear filter, with Repeat, in the default NormalMapDetail mode:

1. the 16 x 16 8-bit colour checker (cells (204, 51, 26) and (26, 128, 204)), in NormalXYZLeft;
2. the 8-bit grey `mask_left_half`, in NormalXYZLeft, under a black mask whose fill effect is the checker (decision 218's R16F mean);
3. the default source (0.5, 0.5, 1), under a black mask whose fill effect is `mask_left_half`.

Measured (counts of the 65 536 texels, against both recordings). The evaluator was replicated in numpy, equal to it on all 65 536 texels, and the candidates were compared through that replica and then through the evaluator:

1. **A grey bitmap on Normal is not inverted.** It feeds its value c / 255 to the three components. The cell interiors on both halves are exact with (g, g, g) and miss with the green inverted.
2. **The blue is clamped before the filter.** With the import as it was (green inverted, codes c / 255 filtered as they are), 27 888 texels differ, by up to 21 056 codes, in every transition of the checker.
   - The z of a texel is clamped to 0 before the bilinear filter: max deviation 192 codes.
   - Normalising each texel as well misses by up to 4 592 codes. Normalising without the clamp misses by up to 20 064.
3. **The clamp is at the 8-bit code 127**, the flat normal's code. The clamp at 1/2 leaves 21 408 texels, at 128/255 53 104 (it moves the cell interiors), and at 126/255 24 720.
4. **The filter's result is written as a 16-bit code.** With the blue at 127, 768 texels still differ, by one binary16 step, all where a tap weighs 8/256.
   - Writing the filtered value as a 16-bit UNORM code (`WriteUnorm(v, 16)`, or the nearest k / 65535) before the channel's half store makes all 65 536 texels exact, r1 and r2.
   - The candidates that miss: the bare float32 result, k / 65536 (320 texels), 2^-17 to 2^-20 grids, the binary16 to nearest of the result (40 736), binary16 texels, and an exact (double) filter (4 864).
   - The grey image cannot tell whether its result passes through the 16-bit code. Its values are 0 and 1, and its transitions are exact both ways.
5. **The content still reaches the blend as a half.** A first version wrote the content tile itself as 16-bit UNORM. It broke `blend-normal-channel` s1-s3 (137 588 values), whose upper operand is the imported map rounded half toward zero (blend-modes.json). So the 16-bit code is the projection's output, and the tile keeps the channel's format.

No model panel was consulted. The rule is read from the recordings, and the scope follows the exactness rule.

## Decision

1. **The rule** (`evaluate.cpp` `NormalTexture`). A bitmap on the Normal channel is sampled as a 16-bit UNORM texture (an 8-bit code c becomes 257 c, the same value c / 255).
   - A colour image has its green codes inverted, max - g, as before.
   - An 8-bit blue code below 127 becomes 127.
   - A grey image feeds its code to the three components, not inverted and not raised.
2. **The 16-bit write.** The projection writes its result as a 16-bit code (`DecodedImage::unorm16Target`: `projection_uv.cpp` `Written` on the CPU; `IMAGE_UNORM16_TARGET` in `evaluator_project.hlsl` on DX12, with the exact division `DivNearest`). The channel then stores that value half toward zero, as before.
   - A 1:1 sample keeps its code, so every recorded import (8 and 16 bits, OpenGL and DirectX) is unchanged.
3. **Admitted:** an 8-bit grey bitmap on Normal (previously refused).
4. **Refused before any mutation:** a 16-bit grey bitmap on Normal, with `evaluator:unsupported_source` naming item 2.9 and this decision. It is not recorded.
5. **P20-A.** The Normal map is byte for byte, both recordings. Its exclusion is removed from `test_facade_fill_channel_defaults_equal_painter`. The Tier 0 trace is unchanged.
6. **Native tests.**
   - `sources` checks P20-A's codes on Normal: the 16-bit write at a 8/256 tap, the raised blue in a cell, and the grey transition. It also checks the 16-bit grey refusal.
   - `projection-gpu-vs-cpu` checks that an 8-bit colour and grey bitmap magnified on Normal, upright and rotated, is the same on DX12 as on the CPU.

## Alternatives Considered

- **Keeping the grey bitmap refused.** Rejected: P20-A records it, and the rule is exact.
- **Clamping z at 1/2, or normalising each texel.** Rejected: each misses texels (above).
- **Storing the Normal content tile as 16-bit UNORM.** Rejected: it breaks the recorded blends of two imported maps (`blend-normal-channel` s1-s3).

## Consequences

- P20-A's Normal map is exact. Of P20-A's maps, only BaseColor stays open (item 2.7, decision 218).
- These cases are modelled by the same texture rule but are not recorded:
  - a magnified or minified 16-bit normal map: its result is now written as a 16-bit code, and its blue is not clamped;
  - an 8-bit normal map at 1:1 with a blue code below 127: it now stores 127.
- `export-resize`'s BilinearHQ magnification of the Normal channel (decision 103: not reproduced) was not re-checked against this rule.
