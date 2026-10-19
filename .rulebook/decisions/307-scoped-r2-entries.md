# 307. The OCIO and sRGB-variants r2 residuals get their own decision 032 entries, EXC-008 and EXC-009, and register entries can be scoped to goldens and outputs

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.15_compositor-colour-fits

## Context

Supervisor finding SUP-027. `phase1.15_compositor-colour-fits` left 8 r2 comparisons out of its tests without a register entry:
- 5 of `export-ocio-encode`: s5 BaseColor, steps 46, 47 and 48, probes 50 and 51;
- 3 of `srgb-bitmap-variants-v2`: s5 BaseColor, steps 78, 80 and 82.

Decision 032 (owner, 2026-10-11) makes r1 the exact target of an unstable golden and gives each such golden a register entry. The entry names decision 032 as its owner approval. This is a register task under that standing approval, not a new owner question. EXC-006 covers only the Legacy twin `export-ocio-encode-legacy`. Its note said the OCIO twin was unrecorded and would need its own evidence and a new entry version.

**Measured** on the admitted private records (r1 against r2, native units; UzPainter writes r1 byte for byte, so these are also UzPainter's r2 residuals):

| Golden (record) | Output | max \|Δ\| | mean \|Δ\| | Differing values / texels |
|---|---|---|---|---|
| `export-ocio-encode` (`7f6acce3…`) | step 46 and probe 50, PNG 16 | 620 | 20.165838 | 15 947 / 14 662 |
| | step 47 and probe 51, PNG 8 | 2 | 0.081212 | 15 947 / 14 662 |
| | step 48, OpenEXR 32f | 0.015625 | 0.000520673 | 15 947 / 14 662 |
| `srgb-bitmap-variants-v2` (`6b39d103…`) | steps 78 and 79, PNG 16 | 334 | 19.591146 | 15 360 / 14 592 |
| | steps 80 and 81, PNG 8 | 1 | 0.078125 | 15 360 / 14 592 |
| | steps 82 and 83, OpenEXR 32f | 0.0078125 | 0.000454903 | 15 360 / 14 592 |
| `export-ocio-encode-legacy` (`ce9a70b4…`) | step 46 and probe 50, PNG 16 | 619 | 20.165660 | 15 947 / 14 662 |

In each golden the differing texels are the same in every file. Each one lies where grey A, the mask source, is strictly between 0 and 65 535. Every other map is stable.

**Instability evidence.** Both goldens have a repeat of r1 that agrees with r1 while r2 differs:
- Within each recording, the repeat export of the unstable map equals the first export byte for byte. In `export-ocio-encode`, probe 50 repeats step 46 and probe 51 repeats step 47. In `srgb-bitmap-variants-v2`, steps 79, 81 and 83 repeat 78, 80 and 82.
- The OCIO twin also has a reproduction in another process. `export-ocio-encode-legacy` is a separate project, recorded on 2026-10-12 in Painter session `15cd71a3…`. `export-ocio-encode` was recorded on 2026-10-13 in session `efd9f704…`. Their r1 and r2 PNG 8 and OpenEXR 32f files are identical blobs. Their PNG 16 files differ only by the measured OCIO PNG 16 encode (decision 190).
- `srgb-bitmap-variants-v2`'s s5 (a uniform colour under a layer mask) is recorded by no other golden.

**Decision 032 has no rule for two goldens in one domain.** Register entries match a comparison by tier and domain. Every in-force entry whose bounds hold covers it.
- Domain `tier0/colour/ocio-encode` holds both twins. A second entry there, or a widened EXC-006, would let each twin pass through the other's bounds. That would reuse Legacy's bounds for OCIO, which the supervisor ruled out.
- Domain `tier0/colour/srgb-bitmaps` also holds the stable `srgb-bitmap-minification`. A domain-wide entry would cover that golden's differences too.

**Model panel**, 2026-10-19 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5), on the register mechanism and the evidence. The exception terms themselves rest on decision 032.

| Claim | Verdicts |
|---|---|
| C1: scope entries to goldens (`domain.goldens`); EXC-006 v2 = v1's terms scoped to Legacy, EXC-008 = OCIO, EXC-009 = variants; widening EXC-006 or a second domain-wide entry both widen coverage | AGREE x3 |
| C2: the in-session r1 repeat against r2 (and, for OCIO, the cross-process twin) suffices under decision 032; no new recording first | AGREE x3 (Astra: the twin reproduces PNG 8 and OpenEXR, not PNG 16) |
| C3: bounds = the golden's measured PNG 16 residuals, rounded up only at the last published digit, as EXC-006 | AGREE x2, PARTLY x1 (Astra: per-format bounds would be tighter) |
| C4: a domain-wide instability entry also covers stable comparisons of its domain; fix that in a separate task, flagged | AGREE x3 |

## Decision

1. **Scoped entries.** An entry's `domain` may list:
   - `goldens`: the public manifests' `golden_id`s it covers;
   - `outputs`: the recorded output ids it covers, which requires `goldens`.

   A comparison names its golden and output (`Comparison.golden_id`, `output_id`). A scoped entry covers only a comparison that names a listed golden and, when outputs are listed, a listed output. An entry without these fields covers its whole domain, as before. `register_problems` checks that every listed golden resolves through the current envelope with the entry's domain. Schema `parity/schema/exceptions.json`, `tools/parity/verdict.py`, `tools/parity/schemas.py`, CONTRACT §5.
2. **EXC-006 version 2**: version 1's bounds (619, 20.1657, 15 947), scoped to `export-ocio-encode-legacy` and its five unstable s5 BaseColor outputs. Its note now says the OCIO twin is recorded and has EXC-008, replacing the stale "unrecorded".
3. **EXC-008** (`export-ocio-encode`, steps 46-48 and probes 50, 51): max |Δ| 620, mean 20.1659, 15 947 values differing. These bounds are measured on this golden, not taken from EXC-006.
4. **EXC-009** (`srgb-bitmap-variants-v2`, steps 78-83): max |Δ| 334, mean 19.5912, 15 360 values differing. The stable `srgb-bitmap-minification` is not covered.
5. All three entries have:
   - basis `oracle_instability`, `decision_id` 032, `approved_by: owner`, `approved_on` 2026-10-11, entered under decision 032's standing approval like EXC-004 to EXC-006 and flagged for the owner's review;
   - their private records' hashes as evidence;
   - the defect test `tests/parity/test_verdict.py::test_decision_032_entries_catch_injected_defects`.
6. **The tests judge these files through the register.** `test_ocio_encode_equals_painter_files` and `test_srgb_variants_equal_painter_files` no longer list the unstable files as exclusions. Each file whose r2 differs from r1 is judged against both recordings through `tools/parity/verdict.py`, like `test_srgb8_bitmap_equals_painter_files`:
   - r1 is the exact target, so any difference from r1 fails;
   - r2 must hold within the bounds;
   - the verdict must name the golden's own entry.

## Alternatives Considered

- **Widen EXC-006 version 2 to both twins.** Rejected: Legacy would become one code looser, and the OCIO comparisons would pass through Legacy's entry.
- **Add EXC-008 on the same domain, unscoped.** Rejected: both entries would be in force on both twins.
- **Per-format entries** (PNG 16, PNG 8 and OpenEXR bounds apart). Not taken: decision 032 asks for one entry per golden. Every r1 comparison is exact, so a defect in any format already fails against r1.
- **Ask for a new Painter recording first.** Not needed: the r1 repeats are in the admitted records. For OCIO, a second Painter process also reproduces r1 and r2.

## Consequences

- Both goldens' r2 comparisons pass only within their own measured bounds, and only with r1 exact. A defect larger than the bound fails against r2 as well. The injected wrong region, +4 096 codes, fails both.
- **Open, separate task:** an unscoped instability entry (EXC-001 to EXC-005) still covers differences on stable comparisons of its domain. The scoped entries do not.
- The PNG 8 and OpenEXR r2 comparisons are bounded by the PNG 16 numbers. Their r1 comparisons stay exact.
