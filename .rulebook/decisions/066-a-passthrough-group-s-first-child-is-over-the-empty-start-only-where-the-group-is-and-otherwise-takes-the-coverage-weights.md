# 66. A PassThrough group's first child is over the empty start only where the group is, and otherwise takes the coverage weights

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.10_compositor-float32-residual, phase1.11_compositor-blend-gaps

## Context

Merging main (phase1.11) into the phase1.10 branch joins two rules that were written apart.

- **phase1.10 (decisions 058, 059).** Under the current profile `painter-12.1-isolated-coverage-weights`, the first layer of a list over its empty (transparent) start is copied. Every other backdrop that is not opaque, a backdrop layer of coverage 0 included, takes the coverage weights with the hardware reciprocal. The blend flag `emptyBackdrop` carries "the backdrop is the empty start"; the evaluator set it as `i == 0` for every list.
- **phase1.11 (decisions 053, 054).** A PassThrough group composites its children onto a copy of the accumulator below the group, then mixes by t = opacity x mask: `fma(g - a, t, a)` over an opaque backdrop. Over a backdrop that is not opaque the mix is a hypothesis (the result with coverage t times its coverage over a transparent backdrop, a premultiplied lerp with a correctly rounded reciprocal between).

After the merge, `i == 0` also flagged the first child of a PassThrough group as over the empty start, although its backdrop is the accumulator below the group. Above a partly covered layer, that child took the general W3C formula with a correctly rounded reciprocal; above a layer of coverage 0, a plain copy. With a backdrop layer at 0.4 and a child at 0.3, the RGB32F result differs from the coverage weights.

No golden decides it. `semantics-ui/group-passthrough-masks` has an opaque backdrop (fields A at full coverage), where both rules give the same bits. The model panel was consulted (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| C1 The first child of a PassThrough group is over the empty start only when the group is the first layer of a list that starts empty (propagated through nested PassThrough groups); otherwise it takes the coverage weights. The merged `i == 0` is a definitional bug | AGREE x3 |
| C2 The group's own mix over a backdrop that is not opaque stays phase1.11's unrecorded hypothesis; it does not take the coverage weights or the hardware reciprocal | AGREE x3 |
| C3 Older profiles stay bit for bit: without `coverageWeights` the flag is never read | AGREE x3 |
| C4 No new golden is needed to land the merge; a PassThrough over a backdrop that is not opaque is a future Tier 0 recording | AGREE x2, PARTLY x1: it stays a gap that blocks any acceptance claim on that behaviour |

The panel's risks: nested PassThrough groups must chain the flag through every level, and isolated groups reset it; the flag must follow the list position, never `alpha == 0`; GPU and CPU must read one host-side flag; RGB8 and sRGB8 can hide the difference, RGB32F shows it.

## Decision

1. `EvaluateList` takes `emptyStart`. The root and every isolated group start empty. A PassThrough group's children get `emptyStart && i == 0` of the group's own position. A blend's `emptyBackdrop` is `emptyStart && i == 0`.
2. The flag is set on the host (`BlendOp::emptyBackdrop`), so the CPU store and the HLSL kernel (`FLAG_EMPTY_BACKDROP`) change together. `gpu-vs-cpu` (variant 1) composites a PassThrough group above a stack of partial opacities, GPU = CPU bit for bit.
3. The PassThrough mix itself is unchanged under every profile and stays unrecorded. A Tier 0 recording of a PassThrough above a partly covered layer, and above a layer of coverage 0, on RGB32F, is the evidence that would confirm or refute both halves.

## Consequences

- `group-passthrough-masks`, `group-coverage-order`, `group-masks`, `quantisation-thirds`, `blend-component` and `blend-normal-channel` keep their results, since their PassThrough backdrops are opaque.
- The native `profile` case checks the rule on RGB8, sRGB8 and RGB32F above a layer at 0.4 and at 0. On RGB32F at 0.4 it fails with the merged `i == 0`.
- PassThrough over a backdrop that is not opaque stays an inferred behaviour, in `EVALUATOR.md` and in `blend-kernels.json`'s `kernel-passthrough` ("not recorded").
