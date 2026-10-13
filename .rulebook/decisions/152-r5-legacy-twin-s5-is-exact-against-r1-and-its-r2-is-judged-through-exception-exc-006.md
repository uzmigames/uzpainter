# 152. R5 Legacy twin s5 is exact against r1, and its r2 is judged through exception EXC-006

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.15_compositor-colour-fits

## Context

Item 2.4 of `phase1.15_compositor-colour-fits` (decisions 108 and 130) fits set s5 of `export-ocio-encode-legacy`, R5's Legacy twin. In s5, the authored 8-bit sRGB ramp (`srgb8-ramp`) fills BaseColor at 1:1 (UV, BilinearHQ, RepeatNone) in the sRGB space. The fill sits inside a group with a Black mask, and the mask holds one fill effect whose source is grey A (16-bit grey, no colour space). BaseColor is exported at PNG 16 (step 46), PNG 8 (step 47) and OpenEXR 32f (step 48).

Painter is unstable on s5 (`parity/reports/phase0/tier0-stability.md` §4). Measured on the private record `ce9a70b4…`:
- r2 (after save and reopen) differs from r1 on 15 947 of 196 608 BaseColor values (14 662 texels) in each of the three exports.
- The differences are: PNG 16 max |Δ| 619 codes, mean 20.1657; PNG 8 max 2 codes; OpenEXR 32f max 0.015625.
- The two probe exports of the same map differ in the same way.
- Only texels where grey A is strictly between 0 and 65 535 differ. Every other map of the golden is stable.

Grey A is an 8-bit ramp stored in 16 bits: every code is a multiple of 257.

## Decision

1. **r1 is the exact target (decision 032), and it needs no evaluator change.** Two rules are already fitted: the 8-bit sRGB ramp is its own sRGB8 code (decision 145), and a linear mask source is `float32(c / M)`. With the group mask composite of `phase1.11` / `phase1.14`, they reproduce r1. The rebuilt texture set, written by `WriteExport` through the plan (`uzp-export-tests export`), matches Painter's r1 files byte for byte: 3 of 3 (PNG 16, PNG 8, OpenEXR 32f).
2. **The export tests' spec loader now reads layer masks with fill effects** (`tests/export/export_test.cpp` `ParseMask`, the fields uzp-evaluator-tests reads). Content effects and mask effects other than fill are still refused there. Only the test harness changed; no product code did.
3. **r2 is judged only through the exception register.** `parity/exceptions.json` gains EXC-006, under decision 032's standing approval, flagged for the owner's review:
   - domain `tier0/colour/ocio-encode`, basis `oracle_instability`;
   - bounds from the PNG 16 export's r2 residuals, the largest: max |Δ| 619, mean 20.1657, 15 947 values differing.

   `tests/export/test_export_encoders.py::test_srgb8_bitmap_equals_painter_files` checks that each of s5's three files passes through EXC-006 in both judgements: against r1 as the exact target, and against r2.
4. **The OCIO twin is not covered.** `export-ocio-encode` shares the domain but is unrecorded (Session O, item 2.3). If it is unstable, it needs its own evidence and a new version of EXC-006.

## Alternatives Considered

- **Leave r2 unjudged.** Rejected: under decision 032, an unstable golden without a register entry is `blocked` even when r1 is equal (`tools/parity/verdict.py`), so the golden could never pass.
- **Bound the entry per export unit.** Not possible with `whole`-scope bounds: one entry covers the domain. The PNG 16 residuals are the largest in native units, as in EXC-001.

## Consequences

### Positive
- Item 2.4 is done. All 9 BaseColor files of s3, s4 and s5 now pass the export test. 15 of the 18 comparisons are byte-identical (r1 and r2 of s3 and s4, r1 of s5), and the 3 s5 r2 files pass through EXC-006.
- No refusal changes, and `compositor-capabilities.json` keeps its entries: a masked group was never refused.

### Negative
- The register entry covers residuals of up to 619 16-bit codes on this domain's r2 comparisons. Because a comparison against r1 must be exact, it hides no defect that r1 shows.
