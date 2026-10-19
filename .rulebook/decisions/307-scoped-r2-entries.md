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

## Amendment (2026-10-19): EXC-001 to EXC-005 scoped

The open item of the Consequences is closed. Each of EXC-001 to EXC-005 has a version 2 with its version 1's bounds, evidence basis, decision 032 and approval unchanged, scoped to the goldens and outputs its evidence measured unstable. Version 1 of each stays in the register as history. This only narrows what the entries cover, so it needs no new owner approval.

**Measured** with `tools/parity/fit/stability.py` (r1 against r2, every exported map) on the private records the entries name and, for EXC-001 and EXC-002, also on the current envelope's re-recordings (`7cf9c35b…`, `e8f9ccda…`). Their maps equal the named records' maps in both recordings (`parity/reports/phase0/oracle-envelope.md`), and the unstable outputs are the same. Each entry's summary already named these outputs as its unstable maps. Every other map of the listed goldens is stable.

| Entry | Goldens | Outputs (r2 ≠ r1) | Left out of the domain |
|---|---|---|---|
| EXC-001 v2 | `quantisation-thirds` | the 16 of 36: s0/user3-5; s1/user1, user3, user4, user7; s2/scattering, user0, user3, user4, user7; s3/scattering, user2, user3, user4 | (the only golden of the domain) |
| EXC-002 v2 | `blend-inputs` | s2/user2, s2/user3 (sRGB8), s2/user4 (RGB8) | (the only golden of the domain) |
| EXC-003 v2 | `height-normal-sharp-plane-strength`, `height-normal-sobel-plane-strength` | s1 and s4: Normal_DirectX, Normal_OpenGL, height (the same six in each golden) | the sharp and Sobel sphere and bevelled-cube goldens |
| EXC-004 v2 | `height-normal-channel-coverage` | s2/Normal_DirectX, s2/Normal_OpenGL, s2/normal | `height-normal-mesh-map`, `height-normal-mesh-map-directx` |
| EXC-005 v2 | `height-normal-resolution-2048` | s2/Normal_DirectX, s2/Normal_OpenGL | `height-normal-resolution-512`, `-1024`, `-1024-sobel` |

The sharp sphere's one unstable output is a settings-panel readback, not an exported map. No entry judges it.

**Consumers.** The union run's `observe` (`tests/evaluator/union_run.py`) now names the golden and the output in its comparisons. Without them, no scoped entry would cover its r2 comparisons. `tests/parity/test_verdict.py::test_decision_032_entries_cover_no_stable_comparison` checks each decision 032 domain. A stable comparison with a one-code difference must fail, whether it names no golden, a stable output of a scoped golden, or another golden of the domain. Each listed output must still pass against r2 at its entry's maximum, through that entry alone.

## Amendment (2026-10-19, SUP-036)

The verdict loophole behind the open item is closed in code. Scoping narrows which comparisons an entry names, but a scoped entry (EXC-008, or a version 2 of EXC-001 to EXC-005) still covered an in-bounds difference on a stable comparison of its listed goldens and outputs. `tools/parity/verdict.py` (`_basis_eligible`) now makes an `oracle_instability` entry ineligible whenever the comparison's `oracle_stable` is true, whatever its domain, goldens, outputs or bounds; such a difference fails. Unchanged: an exact stable comparison passes, r1 stays the exact target of an unstable golden, r2 passes within the entry's bounds, `noise_floor` still covers Tier 3, and any other basis still covers a stable oracle. Test: `tests/parity/test_verdict.py::test_an_instability_entry_never_covers_a_stable_oracle` (unscoped EXC-001 sample and scoped EXC-008).
