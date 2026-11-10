# 426. Sharpen and Levels filters are calibrated, not exact; Grayscale Conversion and Blur stay release gaps; the four filters move to follow-up items

**Status**: accepted (coordinator scope split under the owner's throughput rule, 2026-11-10). The candidate exceptions in §2 and §3 are the owner's to approve, and none is approved here.
**Date**: 2026-11-10
**Related Tasks**: phase3.2_proc-filter-families, phase3.3_procedural-families

## Context

`phase3.2_proc-filter-families` certifies Sharpen, Grayscale Conversion and the Levels filter over the §6 matrix, and reproduces the starter-asset Blur. Each must be exact, or covered by an owner-approved exception; otherwise it is listed as a release gap.

Painter 12.2.0 was recorded on 2026-11-10 (Legacy, Painter lock seq 2370 to 2371):

- a survey of all 62 starter filters through the documented `Property` API (item 2.1);
- 22 Tier 2a goldens;
- one diagnostic golden.

The Sharpen and Levels batches were pinned in `e7a4df91`, before certification. Evidence and numbers are in `docs/analysis/proc-filter-families/02-calibration-2026-11-10.md`.

## Decision

1. **The filter golden and its compared texels.**
   - The content is a 16-bit bitmap fill, one bitmap texel per texel. The channel stores I(I(F(k))) of its code k, with I(v) = float32(1 - v) and F the measured UNORM16 fetch. That is the store `generator/occlusion@2` ends with.
   - The compared texels are those of decision 423 §1.
   - Each candidate reads every content texel back to its code, and refuses content off that grid.

2. **Sharpen (`filter/sharpen@2`) is `calibrated`.**
   - The model is the four-neighbour Laplacian of Gonzalez and Woods with Painter's `intensity`, computed on the 16-bit codes with texture wrap and written as a 16-bit code.
   - Calibration: 45 of 54 cases exact. Held-out: 2 of 8 exact, and the set is spent (report `parity/reports/phase3/proc-cert/filter__sharpen@2/727f63f70a79abab.json`).
   - Every residual texel is one code off, at an exact midpoint between two codes. These occur at intensity 0.25, which is the hat v8 recipe set, and at 0.63 and 2.71. Painter rounds most midpoints down. No tried arithmetic order or float-to-UNORM16 conversion reproduces which midpoints it rounds up.
   - Candidate exception for the owner: one 16-bit code on midpoint texels. It is not a pass.

3. **The Levels filter (`filter/levels@2`) is `calibrated`.**
   - The model is the native levels effect of `masks-levels.json` on F(k), stored as I(I(.)).
   - Calibration: 36 of 36 cases exact. Held-out: 6 of 8 exact (report `parity/reports/phase3/proc-cert/filter__levels@2/a278c3bef66e745b.json`).
   - The two residual cases share one interior point: gamma 1.7, output 0.05 to 0.9, no clamp. Painter lies up to 32 float32 ULP below the candidate, by a near-constant relative factor.
   - Those two cases were examined in order to refit, so they are spent. Under decision 222 §2 they join the calibration set as regression cases, and the next candidate needs a new held-out set.
   - Candidate exception for the owner. It is not a pass.

4. **Grayscale Conversion and Blur stay release gaps, not batched.**
   - No Assets3D recipe uses either one, and the harness needs a recipe parameter set in the §6 matrix (decision 303, as decision 423 §4 ruled for Position).
   - Grayscale Conversion (diagnostic golden): its `Channels Weights` output is a 16-bit weighted sum, one code off on about 3 to 4 % of the texels.
   - Blur (diagnostic golden): its own two recordings differ on up to 35 186 compared texels by up to 6e-8, so it does not reproduce itself across a save and reopen. Decision 346's Tier 0 `effect-order` result stands.

5. **Moved items.** Each filter stays a release gap until its new item certifies it: refused with `family not certified`, its `@1` record `unavailable`, no alias.
   - `phase3.3_procedural-families` item 2.10 takes Sharpen. It needs the midpoint rule, for which one route is measuring the recording GPU's float-to-UNORM16 write as `tools/parity/vk_sampler_probe` measured the fetch, then a new held-out set. Sharpen inside a mask stack, where three of the four hat v8 uses are, is part of the item.
   - Item 2.11 takes the Levels filter. It needs the gamma regime of §3, with the spent cases added as regression cases, then a new held-out set.
   - Item 2.12 takes Grayscale Conversion and Blur. They need a recipe use, or a decision that changes the matrix rule; Blur also needs a reproducible recording.

6. **Narrowed acceptance.** `phase3.2_proc-filter-families` is accepted when:
   - item 2.1's discovery is published;
   - each declared domain and the pinned Sharpen and Levels batches exist;
   - the four filters are listed as release gaps with the evidence above and their new items;
   - items 2.2 to 2.4 and 3.2 to 3.5 stay met.

   Nothing is relaxed: each moved filter still needs to be exact, or covered by an owner-approved exception.

## Alternatives Considered

- **Keeping the task open until Sharpen and Levels are exact.**
  - Rejected under the owner's throughput rule. Both residuals are narrow and documented.
  - Their next step needs a new measurement (Sharpen) or a new held-out recording (Levels), and the parent item holds that as well as this task does.
- **Shrinking the Sharpen domain to intensities that never produce a midpoint.**
  - Rejected: it would drop the hat v8 recipe set 0.25, which the §6 matrix requires.
- **A table of Painter's midpoint directions.**
  - Rejected: it would ship Painter output values (decision 423).

## Consequences

- `phase3.2_proc-filter-families` is archived, and parent item 2.5 is met.
- No record, alias or native kernel of an uncertified filter is added.
- The capability manifest keeps all four filters as release gaps.
- The tooling serves the moved items: the survey, the requests, the batch builder, both candidates, and the hardware log2, exp2 and pow of `tools/parity/fit/hwmath.py`. A new candidate or a new held-out set re-runs in minutes.
