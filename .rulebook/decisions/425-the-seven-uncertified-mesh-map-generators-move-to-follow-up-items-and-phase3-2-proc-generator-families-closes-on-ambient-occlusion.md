# 425. The seven uncertified mesh-map generators move to follow-up items; `phase3.2_proc-generator-families` closes on Ambient Occlusion

**Status**: accepted (coordinator scope split under the owner's throughput rule, 2026-11-10)
**Date**: 2026-11-10
**Related Tasks**: phase3.2_proc-generator-families, phase3.2_proc-grunge-families, phase3.3_procedural-families

## Context

`phase3.2_proc-generator-families` certifies eight mesh-map generators. On 2026-11-10 one of them is exact: `generator/occlusion@2` (decision 424; calibration 40 of 40, held-out 8 of 8). Decisions 423 and 424 were accepted in the model panel's root review the same day. The other seven are release gaps, each with recorded evidence (decision 423 §4, `docs/analysis/proc-generator-families/02-calibration-2026-11-09.md` §3). Each has a different blocker, and none of the blockers is inside this task:

- **Dirt, Metal Edge Wear and Mask Builder - Legacy.** The seed alone changes their output at the defaults. They need Painter's seeded grunge, which is the work of `phase3.2_proc-grunge-families`.
- **Curvature and Mask Editor.** Equal curvature inputs give unequal outputs, so these two apply a multi-scale filter of the curvature mesh map. No public source describes that filter.
  - It does not belong in `phase3.2_proc-filter-families`. That task certifies filter assets on layer content: Sharpen, grayscale conversion, Levels and Blur.
  - It is processing inside a generator, on a mesh map.
- **Position and World Space Normals.** They are per-texel at their defaults, but no Assets3D recipe uses them, and the harness needs a recipe parameter set in the §6 matrix (decision 303).

## Decision

1. **Moved items.** Until its new item certifies it, each generator stays a release gap: refused (`family not certified`), no alias, its record `unavailable`.
   - `phase3.2_proc-grunge-families` item 2.7 takes Dirt, Metal Edge Wear and Mask Builder - Legacy. They are certified after the seeded grunge they read, and that task's acceptance 4.1 now counts them.
   - `phase3.3_procedural-families` item 2.8 takes Curvature and Mask Editor: the multi-scale curvature filter, then the two generators.
   - `phase3.3_procedural-families` item 2.9 takes Position and World Space Normals. Certifying them first needs a recipe that uses them, or a decision that changes the §6 matrix rule for assets no recipe uses.
2. **Narrowed acceptance.** `phase3.2_proc-generator-families` is accepted when:
   - Ambient Occlusion (`generator/occlusion@2`) is exact on its calibration and held-out sets, inside its declared domain, and refused outside it;
   - its record, alias and native kernel ship;
   - the seven generators are listed as release gaps with their new items.

   Items 2.5, 2.6, 2.7 and 3.1 are read for Ambient Occlusion. The infrastructure this task built stays and serves the moved items: the requests, the batch builder, the coverage mask of decision 423 §1, the diagnostic golden and the `@1` records with their declared domains.

## Alternatives Considered

- **Keeping the task open until all eight are exact.** Rejected. It would hold the parent behind work owned by other tasks (grunge) or blocked on missing inputs (no recipe for Position and World Space Normals).
- **Moving Curvature and Mask Editor to `phase3.2_proc-filter-families`.** Rejected. That task's assets are filters on layer content, certified independently. The curvature filter acts on a mesh map inside a generator.

## Consequences

- `phase3.2_proc-generator-families` is archived on 2026-11-10, and parent item 2.3 is met.
- The capability manifest keeps the seven as release gaps until their items close. Nothing is relaxed: each moved generator still needs to be exact, or an owner-approved exception.
