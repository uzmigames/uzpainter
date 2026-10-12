# 89. The export writes Painter's PNG and OpenEXR bytes, with its own PNG encoder over zlib and tinyexr with OpenEXR's Huffman tie-break

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.16_export-processing-encoders, phase1.18_export-engine

## Context

Task phase1.16 asks for a deterministic PNG 8/16 writer over vendored libpng and zlib, and an OpenEXR 16f/32f writer over tinyexr (`docs/architecture/08-export.md` §3). The parity contract compares decoded values at native depth (`14-parity-testing.md`); UzPainter's own exports must be byte-deterministic (EXP-05). The licence inventory already selects spng as the PNG codec and leaves libpng unselected.

Measured on Painter 12.1.5's recorded exports in the private store (numbers only):

- **PNG.** All 984 distinct PNG files (16 bits, grey or RGB) have the chunks IHDR, pHYs (2835 pixels per metre on both axes, unit metre), IDAT and IEND. Every IDAT but the last holds exactly 8192 bytes, and the zlib header is `78 9C`. The decoded samples re-encode to all 984 files byte for byte with one procedure:
  - per row, the filter among None, Sub and Paeth only whose bytes have the smallest sum of min(b, 256 - b), ties to the earlier;
  - the row above the first row is zero;
  - one zlib stream at level 6, window bits 15, memory level 8 and strategy Z_FILTERED, split at 8192 bytes.

  This was found with Python's zlib 1.3.1 and confirmed in C++ with the vendored zlib 1.3.2: 984 of 984 files identical.
- **OpenEXR.** All 216 distinct OpenEXR files (32-bit float) are single-part scanline files, version field 2. They carry the eight standard attributes in alphabetical order, PIZ compression and FLOAT channels `Y` (grey) or `B`, `G`, `R`. OpenEXR 3.4.8 re-encodes their chunks identically. tinyexr v3.2.0 (BSD-3-Clause, the newest release) re-encodes only 20 of 216. The only cause is its PIZ Huffman table builder: its heap comparator compares frequencies only, while OpenEXR's adds the tie-break `(*a == *b && a > b)`. OpenEXR added that tie-break so that `std::make_heap`/`pop_heap`/`push_heap` build the same table with every standard library. Without it, tinyexr's bytes depend on the C++ library's heap algorithm. With that one-line change, tinyexr re-encodes all 216 files byte for byte, header included.

The model panel was consulted under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| C1 Own PNG encoder over zlib with the measured procedure; libpng not vendored; spng stays the decoder | PARTLY x3: verify with the vendored zlib 1.3.2 first; write only the recorded layouts (16 bits, grey and RGB); record the amendment of item 2.1 |
| C2 tinyexr with one recorded local change (OpenEXR's tie-break), recorded in the vendoring table, `ORIGIN.md` and the provenance test; `uncompr.c` from the pinned zlib archive | AGREE x2, PARTLY x1: an explicit, documented exception to the byte-equal vendoring rule, not to be generalised |
| C3 tinyexr unmodified instead | DISAGREE x2, AGREE x1: byte identity with Painter is available and the unpatched bytes depend on the standard library |
| C4 Acceptance: Painter's bytes where recorded, decoded equality, and byte determinism across runs and processes | AGREE x1, PARTLY x2: scope it to the recorded configurations |

## Decision

1. **PNG** (`src/export/png_writer.{h,cpp}`). UzPainter's own encoder over the vendored zlib implements the measured procedure. It writes only the recorded layouts: 16 bits, grey or RGB (decision 090). libpng is not vendored, and the licence inventory says so; item 2.1's "vendor libpng" is satisfied by this decision. spng stays the decoder.
2. **OpenEXR** (`src/export/exr_writer.{h,cpp}`).
   - tinyexr v3.2.0 is vendored in `thirdparty/tinyexr/` (`tinyexr.h`, `exr_reader.hh`, `streamreader.hh`, `LICENSE`). It is compiled once by `src/export/tinyexr_unit.cpp` with third-party flags, over the vendored zlib (`TINYEXR_USE_MINIZ` 0), and miniz is not vendored.
   - zlib's `uncompr.c` (`uncompress`) is added from the same pinned zlib archive.
   - The writer writes FLOAT `Y` or `B`, `G`, `R` scanline images with PIZ.
3. **The one local change.** OpenEXR's tie-break in tinyexr's `FHeapCompare` is an explicit exception to the rule that vendored files equal their archive:
   - `tools/vendoring/thirdparty.py` records it as a `LocalChange` (file, upstream text, replacement, cause), and the importer applies it.
   - `thirdparty/tinyexr/ORIGIN.md` lists it, and the vendored line carries a comment pointing there.
   - The provenance test recomputes the vendored file as the archive member with the change applied.
   - Any future local change needs the same bar: a root-cause defect, a golden that locks it, and a test.
4. **Acceptance.**
   - Every recorded Painter PNG and OpenEXR file, decoded and encoded again, is byte-identical (Tier 0, local run).
   - Files written end to end by `WriteExport` are byte-identical to Painter's where the evaluator is exact.
   - Synthetic images round-trip at native depth, bit for bit, also through independent decoders.
   - Two runs and two processes give identical bytes (hosted CPU lane and local run).

## Alternatives Considered

- **libpng configured to the same procedure.** Rejected: it adds a dependency only to be configured into what about 150 lines over zlib already do. The PNG chunk format is public.
- **tinyexr unmodified.** Rejected: its bytes differ from Painter in 196 of 216 files and change with the standard library.
- **Vendoring OpenEXRCore.** Rejected: it brings libdeflate and the HTJ2K dependencies for the same bytes.
- **An own PIZ encoder.** Rejected: hundreds of lines to reproduce what the one-line fix gives.

## Consequences

- UzPainter's PNG16 and OpenEXR 32f exports can be compared with Painter's by SHA-256, not only by decoded values.
- A zlib or tinyexr upgrade must re-run the 1200-file re-encoding test before it lands.
- Upstreaming the tie-break to tinyexr (and dropping the local change) is a possible follow-up, but nothing depends on it.
