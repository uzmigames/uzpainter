# 69. The content-effect order golden is split: s6 closes in phase1.11, and the Blur sets move to phase3.2_proc-filter-families

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.11_compositor-mask-effects, phase3.2_proc-filter-families, phase1.14_compositor-core

## Context

Item 3.3 of `phase1.11_compositor-mask-effects` reads "Tier 0 content-effect order goldens exact". The golden `effect-order` has eight sets on RGB16 and sRGB8: a fill effect F, a levels effect L and the starter-asset Blur filter B in the orders s0 FLB, s1 FBL, s2 LFB, s3 LBF, s4 BFL, s5 BLF, s6 L and s7 B.

- s6 is exact against both recordings on the CPU and on DX12 (re-run 2026-10-11 on main `4949d28`).
- Blur is a filter effect. The task's proposal excludes filter effects as P3-PROC release gaps, and the evaluator refuses them with `unsupported_node` (`grep` finds no Blur in `src/`). Blur is not the identity on the fields' interiors, so s0–s5 and s7 cannot be evaluated without it.
- The order of fill and levels effects is implemented from the documented list order and unit-tested by the native `masks` case ("fill then levels differs from levels then fill"). No golden observes it without Blur.
- No Phase 3 task named the Blur filter. The filter family listed Sharpen, grayscale conversion and Levels, and `phase3.1_proc-backend-seam` 2.3 ships blur operators as primitives only.
- If 3.3 stays open, `phase1.14_compositor-core` (2.5) and gate G1 wait on Phase 3 work. phase1.14's acceptance reads "Tier 0 semantics exact for the implemented subset".

Two options were weighed. In (a), 3.3 is checked with a note naming the owned slice and the owner of the rest. In (b), 3.3 stays open until Phase 3. The model panel was consulted (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| C1 (a) is the right record: the owned slice is exact, and the rest is unobservable without an excluded P3-PROC feature, so moving it to a later task with a named item is a scope split, not a silently accepted residual | PARTLY x3: only as an explicit, recorded scope split whose note names the unverified sets; s6 is not order evidence, and the unit test is not a golden |
| C2 (b) is wrong because it makes a Phase 1 gate wait on Phase 3 | DISAGREE x1 (phase order does not override the acceptance rule without an explicit scope amendment), PARTLY x2 (right conclusion, but (b) would add evidence later; that evidence is already owned by the later task) |
| C3 The gap stays visible in the report, the published fit and the capability inventory; nothing claims the order is golden-verified | AGREE x3 |
| C4 phase3.2_proc-filter-families owns the new item, not phase3.1_proc-backend-seam | AGREE x1, PARTLY x2: add the reference Blur filter to phase3.2's scope now, not "when planned"; a primitive named blur does not guarantee the reference filter |
| C5 The phase1.10 3.1 precedent ("moved to phase1.11_compositor-blend-gaps as release gaps") makes (a) consistent | AGREE x1, PARTLY x2: same shape, but this split crosses a phase boundary and covers 6 of 8 sets |

Two of three accept (a) as a recorded scope split under conditions. The third accepts it only as an explicit scope amendment, which this decision is. All three require the gap to stay visible and Blur to be owned now.

## Decision

1. Item 3.3 of `phase1.11_compositor-mask-effects` is a scope split, and this decision is its amendment. phase1.11 owns `effect-order` s6, which is exact on CPU and DX12 against both recordings, and the list order of fill and levels effects as a native unit case. 3.3 is checked with that note. Its original wording stays.
2. `effect-order` s0–s5 and s7 move to `phase3.2_proc-filter-families` item 3.4: "Tier 0 `effect-order` s0–s5, s7 exact (content-effect order of fill and levels effects around Blur; phase1.11_compositor-mask-effects item 3.3)". That task is later in the phase order, so no blocker moves down.
3. The starter-asset Blur filter (resource search `s:starterassets u:filter n:Blur=`, default parameters) joins phase3.2's scope now. It goes in the proposal's What Changes and in the Filters row of `docs/architecture/05-procedural-content.md` §3. It is built on phase3.1's blur operators (already phase3.2's prerequisite) and calibrated against the golden. Reusing a convenient primitive does not count as the reference filter.
4. The gap stays visible.
   - The report `parity/reports/phase1/compositor-mask-effects.md` lists s0–s5 and s7 as not evaluated, with their owner.
   - The published fit `parity/semantics/masks-levels.json` keeps `content-effect-order` as status gap and names the owner item.
   - Filter effects stay `unsupported_node`, and phase1.14 item 2.8 registers them as `release-gap` in the capability inventory.
   - s6 is never cited as evidence of the order.

## Consequences

- phase1.11 can archive once its other items are green. phase1.14 and G1 do not wait on Phase 3.
- phase3.2 item 3.4 is a non-waivable item of that task. When Blur exists, s0–s5 and s7 are compared on CPU and DX12 against both recordings, the same standard as s6. A difference there in the fill or levels order is a bug in phase1.11's code, to be fixed then, not a new scope.
- No stand-in for Blur (identity, a box blur) is ever used to make s0–s5 pass.
