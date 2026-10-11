# 75. Diagnostics evaluate a private copy of the revision, and a material's leaks are texels of its effective mask where the full stack differs from its solo

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.13_compositor-diagnostics

## Context

Task `phase1.13_compositor-diagnostics` implements `isolate(layer)`, `contribution(layer)`, `material_views(mask)` and `region_stats(map, mask)` (`04-layer-stack-and-compositing.md` §8; LAY-09, LAY-14, DIA-01). The task names the operations but not their rules:

- how visibility is "restored atomically, also when the evaluation fails midway";
- what a material, its mask, its "ID" view and a "leak" are;
- which texels are inside a soft mask;
- which statistics are computed, and how exactly.

The facts it starts from:

- The document is copy-on-write. A revision is an immutable `shared_ptr<const Project>`, and a transaction edits a private copy that it publishes as the next revision. A published revision creates an operation record and marks the project as needing saving.
- The evaluator's cache keys every node output by a subtree hash. Hiding one layer leaves every prefix below it unchanged, so those tiles are served from the cache.
- A layer's mask is mono, independent of the channel, and stored at 16 bits.
- Painter has no ID channel. ID is a baked mesh map (`MeshMapUsage::ID`).
- Painter 12.1's templates name the roughness and metallic channels `SpecularRoughness` and `BaseMetalness`. No template has a legacy `Roughness` or `Metallic` channel.
- In the owner's stacks a material is a root group or fill layer whose mask is the material mask: bitmap fill effects in the mask (`02-painter-usage.md`).
- The owner's region script (`board_ref_vs_render.py`) computes L = mean(R, G, B), numpy percentiles 10/50/90, the median of S = (max − min) / max(max, 1) on 8-bit values, and the pixel count.

The model panel was consulted twice (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5).

| Claim | Verdicts |
|---|---|
| C1 isolate hides the node in a private copy of the revision snapshot, evaluates it through the general evaluator and never commits: the document, its revision, records and save state are untouched at every instant, so the restore is atomic by construction, also on a failure midway. A transaction hide + rollback holding the document lock through a GPU evaluation is rejected | AGREE x3 |
| C2 contribution = full − isolated, one float32 subtraction per sample of the decoded values, as a signed float32 map, for channels and the virtual normal maps | AGREE x1, PARTLY x2: unclamped signed float output, constants decoded as values |
| C3 (round 1) the ID view is the material's own mask | DISAGREE x1, PARTLY x2: ID is the baked ID mesh map; nested materials need their enclosing groups' masks |
| R1 (round 2) the region is the effective mask, the float32 product of the material's mask and every enclosing group's, from the material outward; `materialMask` exports it | AGREE x3 |
| R2 (round 2) the ID view is the bound ID mesh map inside the region; its leaks are texels whose exact code triple differs from the region's modal one (ties to the smallest triple); a missing ID map or channel is listed, not dropped | AGREE x2, PARTLY x1: modal disagreement measures ID heterogeneity; a material may legitimately span IDs |
| C4/R3 a channel leak is a texel inside the region whose full value differs bitwise from the material's solo evaluation (every layer that is neither the material, an enclosing group nor inside it hidden); an instance material is refused | AGREE x4, PARTLY x2 |
| C5 inside = mask ≥ 1/2 for views, leaks and statistics (a 16-bit code ≥ 32768); coverage = inside / texels | AGREE x2, PARTLY x1: also report the weighted coverage |
| C6 statistics: count, coverage, per-component min/max/mean (correctly rounded sum / n) and p10/p50/p90 by the linear rule; for three components luminance ((r + g) + b) / 3 and saturation (max − min) / max, 0 where max ≤ 0 | AGREE x1, PARTLY x1, DISAGREE x1 (saturation denominator, see below) |
| R4 differences, masking, leak comparisons and statistics run on the CPU over read-back values; GPU = CPU for the evaluations is the engine's invariant, tested | AGREE x1, PARTLY x2: prove GPU = CPU by test |

On saturation: the owner's `max(max, 1)` acts on 8-bit integers, where max is either 0 or at least 1. It therefore equals (max − min) / max, with 0 for black. That is the claimed formula on the owner's own domain, so the formula stands.

## Decision

1. **Isolation (LAY-09).** `IsolateOn` hides the node in a private copy of the revision's project (`HiddenCopy`) and evaluates the copy through `EvaluateOn` or `EvaluateVirtualNormalOn`. The node can be a layer, group, instance or a content or mask effect. Nothing is committed. A node outside the stack fails with `not_found`. An invisible node isolates to the full map. Every evaluation of one diagnostic reads the one snapshot passed to `Evaluator::Diagnose`.
2. **Contribution.** The full map minus the isolated map, one float32 subtraction per sample of their operands: the decoded stored values, with constant tiles as their constant. It is never clamped and is returned with both maps.
3. **Material views (LAY-14).**
   - A material is a fill layer or group. An instance is refused with `unsupported_node`, because its solo is undefined.
   - Its region is the effective mask: the float32 product of its own mask and the mask of each enclosing group, from the material outward. Each mask is evaluated by the engine's mask chain (`BuildLayerMask`, `EvaluateLayerMask`) and shares tiles with the channel evaluations.
   - The ID view is the bound ID mesh map inside the region. Its leaks are the texels whose code triple differs from the modal triple, and the modal colour is reported.
   - The BaseColor, Height, Normal, Roughness and Metallic views read BaseColor, Height, Normal, SpecularRoughness and BaseMetalness. Each is the full value inside the region and 0 outside. Its leaks are the texels where the full value differs bitwise from the solo value.
   - A view the set or stack cannot give is listed in `missing`.
   - A leak is evidence that another material shows inside the region (above it, or below it through partial opacity or mask). It is not proof of an authoring error. ID heterogeneity can be legitimate, and the consumer judges it.
4. **Membership.** A texel is inside a mask when its value is at least 1/2, for views, leaks and statistics alike.
5. **Region statistics (DIA-01).**
   - Counts: texels and inside, the thresholded coverage (inside / texels) and the weighted coverage (`maskMean`, the correctly rounded sum of the mask over the texels).
   - Per component: min, max, mean (Shewchuk's exact partials, the algorithm of Python's `math.fsum`, divided by n) and p10/p50/p90 by Hyndman and Fan's definition 7 (numpy's default), in double.
   - For three components: luminance ((r + g) + b) / 3 and HSV saturation (max − min) / max (0 where max ≤ 0).
   - A non-finite value inside, or a mask of another shape, fails with `unsupported_source`.
6. **Determinism.** The evaluations run on the store, and the GPU equals the CPU bit for bit. The post-processing runs on the CPU over the read-back values, so both stores give the same bytes. This is tested: `diagnostics-gpu-vs-cpu` covers 129 outputs, and `diagnostics` repeats every output on fresh and warm evaluators.

## Consequences

- No Painter recording is needed. An isolated map is an ordinary evaluation of another stack, under the parity the evaluator already has.
- The diagnostics inherit the evaluator's refusals, for example the virtual normal maps at resolutions other than 256 (phase1.12).
- Nested-material regions follow the product rule. A material that spans several ID colours reports the minority as ID leaks, and that is for the consumer to judge.
