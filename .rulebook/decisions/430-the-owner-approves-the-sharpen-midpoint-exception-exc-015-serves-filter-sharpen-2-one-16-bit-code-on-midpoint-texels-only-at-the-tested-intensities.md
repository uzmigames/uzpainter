# 430. The owner approves the Sharpen midpoint exception: EXC-015 serves `filter/sharpen@2`, one 16-bit code on midpoint texels only, at the tested intensities

**Status**: accepted
**Date**: 2026-11-10
**Related Tasks**: phase3.3_procedural-families

## Context

Decision 428 §2 fixed the terms of a Sharpen exception that the model panel recommended. §3 put them to the owner as a plain yes/no question, because a panel's delegation is not his approval (decision 259 §6, `parity/CONTRACT.md` §5). The question, verbatim (pt-BR):

> "Sharpen: em alguns texels, só onde a conta cai exatamente no meio entre dois níveis de 16 bits, o UzPainter pode ficar 1 nível (1/65535) acima ou abaixo do Painter; todo o resto fica idêntico. Vale só para as intensidades testadas (0, 0.2, 0.25, 0.4, 0.63, 1, 2.71, 4); outras são recusadas. A exceção cai quando medirmos o arredondamento da GPU. Aprova? (Sim/Não)"

**The owner's answer** (André, 2026-11-10, relayed by the coordinator session), verbatim:

> "Sim, aprovo"

This is his own yes to the terms of decision 428 §2 (decision 259 §6). It is not a delegation.

## Decision

1. **EXC-015 version 1** (`parity/exceptions.json`), the next unused id, carries decision 428 §2's terms and nothing wider:
   - **Domain.** Tier 2a, kind `procedural_asset`, selector `procedural_asset/filter/sharpen` (the filter goldens' public domain). Its `goldens` are the batch's eleven Sharpen goldens: nine calibration goldens (sphere, rounded cube, hat v8 at 1024, 2048 and 4096) and two held-out goldens (knob cube 2048, Tunic v10 1024). The batch's geometry and resolutions are therefore those goldens'. The diagnostic golden, whose Sharpen runs on an RGB channel, is not listed.
   - **The filter** (`domain.procedural_filter`): asset `uzasset://filter/sharpen@2` and the four-neighbour Laplacian with texture wrap. The only parameter is `intensity`, in the tested set {0, 0.2, 0.25, 0.4, 0.63, 1, 2.71, 4}. The content is decision 426 §1's L32F 16-bit bitmap fill, read back to its codes, in a content stack. A comparison is in the domain only when it names all of these. Any other intensity, a mask stack, another content format or channel count, or content off the 16-bit code grid is not covered.
   - **Midpoint texels** are computed from the inputs, never from the difference. With k the texel's content code and n, s, e, w its four neighbours' codes (wrapping at the texture border), L = 4k - (n + s + e + w). The texel is a midpoint when intensity x L, taken exactly from the decimal intensity, is a half-integer and k + intensity x L lies strictly between 0 and 65535. The second condition is the "between two codes" of decision 426 §2. A texel whose value the clamp decides has one correct code, so it is not a midpoint, and the exception is no wider for it.
   - **Bounds.** `max_abs_diff` 0 over `off_midpoint`: every other texel is exactly equal. `max_abs_diff_code_u16` at most 1 over `midpoint`: the absolute difference of the 16-bit codes the two values read back to. A value off the code grid fails the bound. A comparison with no midpoint texel is not covered, so at the exact intensities (0, 0.2, 0.4, 1, 4) any difference fails.
   - **Basis** `owner_scope_split`: Painter is stable (r1 equals r2 on every compared texel), and the difference is UzPainter's unfitted midpoint rounding. `approved_by: owner`, `approved_on: 2026-11-10`.
   - **Defect test:** `tests/parity/test_exc015_sharpen_midpoint.py::test_exc015_catches_injected_defects`. Each of these fails: a 2-code error at a midpoint, a 1-code error off a midpoint, a wrong midpoint detection, a wrong wrap, a wrong clamp, any change at an exact intensity, and an intensity outside the set.
   - **Expiry.** The exception lapses when the recording GPU's float-to-UNORM16 write is measured (item 2.10). The candidate that follows needs a new held-out set, which narrows, confirms or revokes EXC-015. The spent held-out set blocks only that later step, not this exception (decision 428 §2).
2. **The verdict gains the midpoint scope** (`tools/parity/verdict.py`, `tools/parity/midpoint.py`, `parity/schema/exceptions.json`). It adds:
   - the bound scopes `midpoint` and `off_midpoint`, the metric `max_abs_diff_code_u16`, and the domain member `procedural_filter`;
   - `Comparison.filter_inputs` (asset, parameters, content, content format, stack).

   A midpoint scope is valid only on a `procedural_asset` domain that declares `procedural_filter`.
3. **`filter/sharpen@2` is served, as `calibrated`, only inside EXC-015's domain.**
   - The record `assets/procedural/records/filter.sharpen@2.json` has:
     - the batch's domain, with `intensity` narrowed to the tested set;
     - its residuals from report `727f63f70a79abab.json`;
     - `parity.exception: EXC-015`.
   - The HLSL host serves a `calibrated` record only when it names its exception; an `exact` record needs none. Every request outside the domain is refused before mutation (`outside certified domain`), as is every other calibrated or unavailable status (`family not certified`). Content off the code grid fails before any work.
   - The native kernel is the certified candidate, bit for bit: x = F(k) and its four wrapped neighbours, y = x + intensity (4 x - ((n + s) + (e + w))) in float32, code = rint(clamp(y, 0, 1) 65535) with ties to even, then I(I(F(code))).
4. **No alias.** The library admits an alias only for an `exact` asset (`AssetLibrary::Load`, 05 §2), and that rule is unchanged. No Painter name resolves to `filter/sharpen@2`, and `filter/sharpen@1` stays `unavailable`.
5. **What stays a release gap.**
   - Sharpen inside a mask stack, where three of the four hat v8 uses are.
   - Sharpen on channels other than L32F, and every intensity outside the set.
   - The evaluator still refuses every filter effect node (`src/evaluator/support.cpp`), so a project's layer stack does not evaluate Sharpen yet. The seam serves only `filter/sharpen@2` requests that meet the domain.

## Alternatives Considered

- **A bound of one code on every texel.** Rejected: it is not the approved term. The off-midpoint texels are exact on all 62 cases, and the bound must catch a 1-code error there.
- **Marking midpoints from the difference.** Rejected (decision 428 §2): a predicate taken from the difference excepts whatever differs.
- **An alias for the calibrated record.** Rejected: the alias rule admits exact assets only. A Painter name that resolved to a calibrated asset would answer with an asset that is not Painter's on every texel.

## Consequences

- Reports that rely on EXC-015 say "pass under EXC-015", never exact.
- `phase3.3_procedural-families` item 2.10 notes the exception and its expiry. The item stays open: the mask stack, the float-to-UNORM16 measurement and a new held-out set remain.

## Amendment (2026-11-10, same day): 0.63 and 2.71 are not served

The native CPU lane was judged by the verdict on all 62 batch cases. It is exact on the 47 cases the harness found exact, and "pass under EXC-015" on the 11 cases at intensity 0.25: every residual texel there is an exact midpoint. The 4 interior held-out cases (0.63 and 2.71, knob cube 2048 and Tunic v10 1024) fail EXC-015's bounds.

A counts-only diagnosis of those four cases, run locally (nothing left the machine), found the following.
- At 0.63, 226 of 1 019 residual texels (Tunic) and 2 877 of 11 368 (knob cube) are exact midpoints. The others lie where k + intensity x L is 0.01 to 0.05 code above a half, and Painter writes the code below.
- At 2.71, the off-midpoint residuals lie 0.01 to 0.07 code from a half on either side, mostly rounded down.
- No quantised intensity explains them. Float16, 1/256, 1/255, 1/1024 and 1/4096 intensities all give more differences than the decimal intensity.

Decision 426 §2 and decision 428's premise ("every residual texel is ... at an exact midpoint") therefore hold at 0.25 only. EXC-015's terms are not widened: a near-midpoint band is a different exception that only the owner can approve.

- **EXC-015 version 2** keeps version 1's domain and bounds, the approved terms, unchanged, and corrects the evidence summary. Comparisons at 0.63 and 2.71 stay uncovered.
- **`filter/sharpen@2` serves intensity 0, 0.2, 0.25, 0.4, 1 and 4 only.** Its record's domain omits 0.63 and 2.71, so the seam refuses them before any work (`outside certified domain`). This narrows what decision 430 §3 serves. It widens nothing.
- **Item 2.10** keeps the interior residual: the float-to-UNORM16 write measurement and a new held-out set must explain both the 0.25 tie-break and the near-midpoint rounding at 0.63 and 2.71.
