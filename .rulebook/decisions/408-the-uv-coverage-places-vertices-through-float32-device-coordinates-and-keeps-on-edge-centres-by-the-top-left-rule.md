# 408. The UV coverage places vertices through float32 device coordinates and keeps on-edge centres by the top-left rule

**Status**: accepted
**Date**: 2026-11-08
**Related Tasks**: phase3.1_export-island-padding
**Supersedes in part**: decision 281 (its vertex placement and its on-edge test; the 1/256-texel grid stays)

## Context

Decision 281's coverage rounds each vertex's texel-space UV, computed exactly in double as (u W, (1 - v) H), to the nearest 1/256 texel (ties to even), and covers a texel whose centre lies inside or on an edge of the snapped triangle. Decision 401 left three Tunic island-edge texels at 4096 px that Painter treats as padding and that rule covers. `phase3.1_export-island-padding` item 2.1 found a candidate and had it recorded (task notes 2026-11-05 and 2026-11-08):

- `padding_coverage.py`'s vertex rule (905d99f6): each coordinate t goes through float32 device coordinates with v up, p = ((2 t - 1) + 1) N / 2, each operation rounded to float32; p is rounded to the nearest 1/256 texel (ties to even) and the rows are flipped, y = H - p_v. Below t = 1/2 the sum 2 t - 1 rounds, which moves a vertex near a 1/256 tie.
- The top-left rule: with the triangle wound to a positive area (rows top first), a centre on an edge is covered only when the edge has dy < 0, or dy = 0 and dx < 0.

Three kernel-code probes (decision 266) record Painter's coverage on every texel: a texel is covered when all 24 `infinite` components equal its sources. Scored by `tools/parity/fit/padding_coverage_recorded.py` (covered, too many, too few):

| Probe | Recorded | Decision 281 | Vertex rule alone | Vertex rule + top-left |
| --- | ---: | --- | --- | --- |
| `export-padding-kernel-islands-256` | 28,322 | 0 / 0 | 0 / 0 | 0 / 0 |
| `export-padding-fold-tie` (512) | 13,824 | 288 / 0 | 288 / 0 | 0 / 0 |
| `export-padding-kernel-tunic-4096` | 4,222,246 | 3 / 1 | 0 / 0 | 0 / 0 |

On the fold tie the 288 texels have their centres exactly on an island's edge. Strict inside misses 480 fold-tie and 2 Tunic texels.

**Every recorded mesh** (`python -m tools.parity.fit.padding_coverage`, its `408` columns: every tier0 padding and height-normal golden at its size, every kernel probe, and the Wand, Sash and Tunic Tier 1 meshes at 1024, 2048 and 4096). Texels decision 281 covers and the adopted rule does not, and the reverse:

- every tier0 padding, kernel and height-normal golden: 0 / 0, except the fold tie (288 / 0) and the Tunic kernel probe (3 / 1), where the adopted rule equals Painter on every texel;
- the Wand at 1024, 2048 and 4096: 0 / 0;
- the Sash at 2048, its recorded size: 0 / 1, the vertex rule's one texel; with it covered, all 37 ring texels around it equal Painter's BaseColor, against 33 under decision 281 (task notes 2026-11-05);
- the Tunic at 4096, its recorded size: the kernel probe's mesh, 3 / 1 as above;
- at unrecorded sizes: the Sash at 1024 (60 / 0) and 4096 (280 / 0), centres on an island edge as on the fold tie, and the Tunic at 2048 (0 / 2, the vertex rule).

So the rule changes no texel of any recorded golden except where it equals Painter and decision 281 does not, and makes no new mismatch.

## Decision

1. **The vertex.** `evaluator::SnappedVertex` (`src/evaluator/geometry_mask.h`): x = round(p(u, W) 256) / 256 and y = H - round(p(v, H) 256) / 256, with p(t, N) = ((2 t - 1) + 1) (N / 2), each operation a float32 operation (`-ffp-contract=off`), the rounding ties to even.
2. **The edge test.** `CoveredTexels`: a degenerate snapped triangle covers nothing; otherwise, wound to a positive area, a centre is covered when it lies strictly inside every edge, or on an edge with dy < 0, or dy = 0 and dx < 0.
3. **The seam strips' ends** (decision 368) are those vertices (`KernelTriangle::s`; `kStripSubTexel` is gone).
4. **Mirrors, operation for operation:** `tests/export/padding_reference.py` (`snapped_vertex`, `covered_texels`, `Triangle.s`, `strip_covers` on snapped ends) and `tools/parity/coverage.py` (`ndc_vertex`, `snapped`, `coverage`). Decision 281's rule stays in `tools/parity/fit/padding_coverage.py` as `coverage_281`, for scoring only.

No tolerance, exception or refusal changes here. Decision 281's 1/256-texel grid, degenerate-triangle rule and texel-centre convention stand.

## Consequences

- The export's coverage, the evaluator's `Mesh` geometry masks and the Tier 1 coverage masks (`verdict.py`) follow the rule. The Tunic's three decision-401 texels become padding and its one undecided texel becomes covered; the Sash at 2048 covers one more texel.
- Synthetic fixtures with a centre exactly on a right or upper island edge change: `tests/export/test_padding_ring.py`'s decision-281 snap case now snaps a left edge onto a centre (covered) and a right edge onto one (not covered); the decision-279 lone-edge case's ring texel (8, 15) has no covered neighbour any more, and no ring texel discovers the lone 1.7768 edge.
- The ReleaseFast product binary must be rebuilt for the change to reach a delivered export.
