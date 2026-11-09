# 410. EXC-011 version 3 narrows the Tunic's exception back to the Normal's island edge

**Status**: accepted
**Date**: 2026-11-08
**Related Tasks**: phase3.1_export-island-padding, phase2.10_pilot-tunic-recovery
**Applies**: decision 401 §3 (the owner's narrowing path for EXC-011)

## Context

Decision 401 widened EXC-011 to version 2 because three covered island-edge texels of the Tunic at 4096 px differed on BaseColor (5 values), Height (`Displacement_Raw`, 9) and Roughness (3): a coverage near-tie in which Painter counts each texel outside its island. Its §3 sent the exact tie rule to `phase3.1_export-island-padding`, which "narrows EXC-011 version 2 by a new version as it makes the edge exact, back to the Normal only and then to nothing (decision 398 §6)".

Decision 408 adopted the coverage rule that equals Painter's recorded coverage on every texel of the Tunic mesh at 4096 px (`export-padding-kernel-tunic-4096`: 4,222,246 covered texels, 0 wrong). The Tunic's Tier 1 node (`tests/parity/tier1/test_mcp_round.py::test_tunic_current_tier1_maps_equal_painter_under_exc011`, run on 2026-11-08 after 5ccd05d3; report statistics only):

| Map | Covered texels | Covered values differing (v2 run) | Now |
| --- | ---: | ---: | ---: |
| BaseColor | 4,222,246 (was 4,222,248) | 5 | 0 |
| Height (`Displacement_Raw`) | 4,222,246 | 9 | 0 |
| Metallic | 4,222,246 | 0 | 0 |
| Roughness | 4,222,246 | 3 | 0 |
| Normal (island edge) | 4,222,246 | 25,431 | 25,393 |

Every covered interior texel stays exact on all five maps; the rebuild stays byte-identical. Only the Normal's island edge still differs, which is item 2.2's (decisions 245, 263).

## Decision

1. **EXC-011 version 3** (`parity/exceptions.json`) supersedes version 2, which stays in the register with version 1 as history. Its terms are version 1's (EXC-010's): bound 1, `max_abs_diff` 0 over `covered_interior` on every map; bound 2, `max_abs_diff` 0 over `covered` with `excepted_outputs` naming only `export/DefaultMaterial_Normal_Raw`; the padding stays free. Its defect test is `tests/parity/test_verdict.py::test_exc011_v3_catches_injected_defects`.
2. **A narrowing only.** It applies the owner's own terms of decision 401 §3 (approved 2026-11-05); no bound is widened and no exception is created. The entry's `approved_on` is that approval's date.
3. **Reporting.** The Tunic's Tier 1 node, rerun after decision 409's commit (db3a1498), passes under version 3, repeatable, with `exceptions_relied_on` naming EXC-011 version 3 only. A Tunic pass is "pass under EXC-011 v3, against the current reference", never exact. The Tier 1 test accepts only version 3 in `exceptions_relied_on`.
4. **Next.** EXC-011 is withdrawn when the Tunic's Tier 1 passes with no exception (decision 398 §6), which waits on the Normal's island edge (item 2.2) and the padding (item 2.1).

## Consequences

- An island-edge difference on BaseColor, Height, Metallic or Roughness fails the Tunic's Tier 1 again, as under version 1.
- The Wand (EXC-010) and the Sash (EXC-012) are unchanged: decision 408 changes no Wand texel at 2048 px, and the Sash's one newly covered texel equals Painter on every map (its covered bound, Normal's island edge apart, was already exact).
