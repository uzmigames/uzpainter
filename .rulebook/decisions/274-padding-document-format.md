# 274. The measured `infinite` padding works in each channel's document format, not on the PNG 16 export codes, correcting decision 223's padding domain

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders
**Corrects**: decision 223 (its padding domain only; decision 259's refusal stands)

## Context

Decision 223 padded the stored values of an exported file: OpenEXR floats, and PNG codes read as UNORM operands, with each filled code written back by the UNORM write rule. It measured the Wand on its PNG 16 codes. Decisions 267, 268 and 270 later fitted the ring kernel, the FMA lerp chain over at most 4 taps. That kernel is exact on the synthetic User-channel probes, but on the Wand it reached only 3 exact BaseColor ring texels out of 6,334.

The Wand's exports show what each channel stores. All of these observations are black-box readings of Painter's r1 files in the private store:
- every Roughness and Metallic code is a multiple of 257 (4,194,304 of 4,194,304 each). These are 8-bit channels written at 16 bits;
- every BaseColor code (12,582,912 of 12,582,912) is one of the 256 codes Painter writes under OCIO for the sRGB8 codes (encode.h `OcioSrgbPng16Code`). It is an sRGB8 channel;
- the Height codes are none of these. They are a 16-bit Height, L16F in the default templates. Decision 263 found Painter's Height ring in float32 before the L16F write.

A lerp of PNG 16 codes leaves those sets. Painter's ring texels stay in them, so Painter pads before the export encode, in the channel's own format.

## Decision

The measured `infinite` padding (padding.h, `InexactPadding::measure`) pads each channel in its document format:
- **Which channels.** A file channel that reads one component of a documentMap source carries its stack channel's `ChannelFormat` (`FileRaster::documentFormat`, set by `EvaluateFileOn`). Its operands are that format's operands, the values the evaluator reads out: an sRGB8 channel's linear operands, an 8- or 16-bit UNORM channel's operands, a float channel's floats.
- **How a texel is filled.** The ring kernel (decisions 267, 268 and 270) and the gutter flood (decision 197) run on those operands. Each filled texel is then stored as the format stores it (evaluator/cpu_store.h `StoreValue` and `OperandOf`): the GPU's float-to-sRGB8 conversion, the 8- or 16-bit UNORM write, or the half rounded toward zero.
- **How it is written.** The stored value is written exactly like the channel's covered texels: the PNG UNORM write, the sRGB export encode or the OCIO code table, a Height's v * 0.5 + 0.5, or the OpenEXR float or half.
- **Other channels.** A mesh map, a virtual map, a luma or a constant keeps decision 223's domain: the file's stored values. No recording shows Painter's domain for them. The combined virtual normal stays refused on islands (decision 245).

The production export is unchanged. `infinite` padding on incomplete coverage is still refused before anything is written (`CheckPadding`, R-090, decision 259), because the ring is not yet exact.

## Measurements

The Wand v1's r1 PNG 16 maps went through `uzp-export-tests process` in measure mode over the Wand's mesh (material `11-Varinha-Madeira`, 2048 x 2048). The coverage had 508,305 covered texels, a ring of 6,334 and a gutter of 3,679,665. Each map was read back as its document format: BaseColor sRGB8 under OCIO, Roughness and Metallic L8, Height as noted. Covered texels are exact in every run (0 differing).

| Map | Ring exact, codes domain (223) | Ring exact, document format (274) | Gutter exact, 223 | Gutter exact, 274 |
|---|---|---|---|---|
| BaseColor (sRGB8) | 3 | 3,935 | 6,512 | 1,300,122 |
| Roughness (L8) | 2,632 | 4,926 | 2,476,462 | 3,072,357 |
| Metallic (L8) | 4,439 | 5,301 | 2,804,400 | 3,125,749 |
| Height, 16-bit UNORM | 5,145 | 5,145 | 2,950,549 | 2,950,549 |
| Height, L16F (indicative) | | 5,147 | | 2,949,635 |
| All four maps | 3 | 3,779 (3,776 with the 16-bit Height) | 6,512 | 1,267,552 |

The ring counts equal the previous agent's Python measurement of the same domains (BaseColor 3,935, Roughness 4,926, Metallic 5,301, Height 5,145). The C++ path therefore reproduces it.

**Height.** The Wand's Height codes (32,669 to 32,767) each have several L16F preimages, so a PNG 16 file cannot give back the document's halves. The L16F row takes, for each code, the half nearest 2u - 1, where u is the code's UNORM operand. It is indicative only. In the 16-bit UNORM domain the Height result is identical to decision 223's.

## Consequences

- **The tap set is most of the remaining gap.** With the 16-bit Height, 2,558 ring texels are still off in some map. The previous agent's classification of the same domains puts 1,552 on the tap set and 184 on the tap count. A further 89 are the V-gap position and 5 the order of near-equal shares. The other 728 have none of the 8 nearest candidates as their taps. Item 2.7 continues from these numbers.
- **The gutter improves with the ring.** It copies ring texels, so it improves with them. It is not yet measured against Painter's own ring.
- **The test tool.** `process` takes `document_format` and `ocio`, and reads a PNG source's codes back as the format's operands (`DocumentOperands`). `tests/export/test_padding_ring.py::test_padding_runs_in_the_document_format` checks the L8, OCIO sRGB8 and L16F Height domains on synthetic codes.
- **Not measured.** The 16F and 32F domains of other channels and the 8-bit sRGB8 legacy encode follow the same rule unmeasured.
