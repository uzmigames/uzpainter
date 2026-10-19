# 277. A seam edge folded concave by about 15° or more gives the ring no far taps: the Wand's 632 residual seam texels are own-only straight-edge texels, and the rest of the Wand's Height misses are the L16F operand inside each PNG 16 code

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding on UV islands (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**Decision 275** fixed the seam ring's far window: the far island's covered texels in the 3 × 3 block around floor(f − ½) in v-up texel space. Its open item (a) was the Wand's 632 single-triangle seam texels that fail all four maps and that no chain over their 4 window taps reproduces, even with nearby level codes. A further 46 were fixed only by another 4-subset of the window.

**This pass asked where those values come from.** It used the Height map first, because it is the only 16-bit map.

**Hypotheses tested** on the 632 (and the 46):
1. the far taps hold already-padded or bilinearly sampled values;
2. the far point comes from another triangle, or from decision 273's arithmetic carried through the fold;
3. the Wand has non-manifold seams, mirrored or overlapping UVs;
4. Painter's coverage differs near these texels;
5. more than 4 taps or a fifth level.

**The data and tools:**
- the Wand v1's r1 PNG 16 maps (`wand-v1`) and its low-poly OBJ, read from the private store;
- decision 275's Python port of `padding.cpp`'s ring geometry (`pad275/`, read only). It matches the C++ path on all 6,334 ring texels;
- decision 275's scoring: a texel counts when some order of its exactly tied shares reproduces Painter's code. Each map is padded in its document format (decision 274).

**How it ran.** On the CPU with numpy and scipy: no Painter, no GPU and no writes to Assets3D, within the 2-hour box. The scripts stay in private scratch (`pad277/`), because they read oracle values.

## Findings

### 1. The 632 sit on concave seam edges, and there Painter takes no far tap

**Where the 632 are, by geometry:**
- **Ruled out:**
  - none is mirrored (both UV triangles have the same orientation);
  - every 3D edge of the Wand is shared by exactly 2 triangles, with consistent winding and shared OBJ vertex indices;
  - no 3D position is duplicated.

  So hypotheses 2 (another triangle) and 3 do not apply.
- **The far side.** 631 of the 632 take their far window from a single far triangle J, and 588 have every far tap in J's own planar face. So hypotheses 1 and 5 have no extra source to draw on.
- **Where they lie:**
  - 609 lie on the 12 seam edges between the tip piece and the shaft. Those are the Wand's two largest UV charts, 120 and 1,104 triangles. On those 12 edges no ring texel passes under decision 275's rule.
  - 10 lie on concave internal seams of the shaft;
  - 13 lie on convex edges (11 on the end cap's seam).
- **The Height is decisive.** On 538 of the 632, the chain over the **own covered 8-neighbours alone** (decision 267's straight edge) reproduces the Height. The window's far taps are nearer, and they do not.

**The separating property is the fold of the seam edge in 3D.** Every Wand seam edge was classed by whether J's apex lies in front of or behind τ's plane (τ is the ring texel's own triangle). A texel was counted for an edge when exactly one of two rules reproduces all four maps:
- decision 275's window;
- the own neighbours only.

| Seam edges (both sides) | Fold | Window only | Own only |
|---|---|---|---|
| Convex seam edges up to 67° (end cap, tip and shaft seams; 122 sides) | convex | 3,955 | 0 |
| Shaft and butt-cap seams, 0.39° to 7.23° (16 sides) | concave | 401 | 0 |
| Shaft and butt-cap seams, 14.84° to 28.23° (11 sides) | concave | 0 | 196 |
| Tip-to-shaft seam, 45.1° to 67.1° (24 sides) | concave | 0 | 737 |

- **The split is clean:**
  - concave folds up to 7.23° take the window;
  - concave folds from 14.84° up take only own taps;
  - convex folds take the window at every angle seen.
- **The fold probes agree.** The kernel atlas's `-fold90` and `-fold53` items fold B down from a flat A, so they are convex. They take far taps, as decision 275 found. No probe yet has a concave fold.
- **Vertex normals do not decide it.** Every corner of the concave seams below 30° carries the same OBJ normal on both sides (16 corners below 10°, 12 from 14.84° to 28.23°), yet the two groups split.
- **The threshold is bracketed but not found.** On the Wand, the dihedral angle (7.23° | 14.84°) and the elevation of J's apex above τ's plane (6.00° | 14.53°) both separate the two groups. Neither can be told apart from a per-tap or per-texel test there, because each edge's deciding texels are all of one kind. The scoring below uses 10° as a placeholder inside the bracket. It is not a decided constant.

### 2. The rule and the Wand counts

**The rule.** A far candidate reached across seam edge (τ, J) is admitted only when the edge is convex, or concave by less than the threshold θ₀ ∈ (7.23°, 14.84°). Otherwise the ring texel's taps are its own covered 8-neighbours, as on an island border without a seam (decision 267). Window, weights and chain are unchanged (decisions 268, 270 and 275).

**All 6,334 Wand ring texels.** The "Height consistent" column is finding 3's.

| Rule | Height exact | Height consistent | BaseColor | Roughness | Metallic | All four exact |
|---|---|---|---|---|---|---|
| Decision 275 | 5,281 | 5,498 | 4,694 | 5,138 | 5,415 | 4,517 |
| Decision 275 + concave gate | **5,938** | **6,242** | **5,746** | **6,165** | **6,227** | **5,465** |

**The 632:**
- 541 are now exact in all four maps;
- 619 are exact in BaseColor, Roughness and Metallic (BRM);
- 622 are Height consistent (finding 3).

**The 46** are now exact in all four maps, except 1.

**The gate also explains the losses a pure convex gate would cause.** Admitting far taps only across convex edges reaches the same Height (5,938). But it loses 420 all-four texels on the shallow concave seams (0.39° to 7.23°), where BaseColor shows that the far taps are used. That is how the threshold is bracketed from below.

### 3. A 1-code Height miss is the L16F operand, not the tap set

The Wand's Height is a 16-bit float document channel (decision 274). Each PNG 16 code has several half preimages, so a PNG 16 file cannot give back the operands.

**The 1-code misses.** Of the 396 ring texels still off in Height under the gated rule, 262 are exact in the other three maps and only 1 code off in Height:
- 94 own-only texels;
- 159 single-triangle seam texels;
- 9 multi-triangle texels.

**The consistency test.** Is there one value per covered tap, inside its code's preimage interval, that makes every ring texel's chain land in Painter's code interval? This is a linear program (LP): taps in code units within ±0.5, each ring value within ±0.55. It is solved elastically, with HiGHS, over all 6,334 ring texels at once.
- Decision 275's rule: 836 ring texels are inconsistent.
- The gated rule: **92**. The 6,242 others are consistent with the taps, weights and chain, with one shared operand per covered texel.

**What is still inconsistent:**
- 34 single-triangle convex seam texels: tap set, 22 of them on the end cap's seam (open item (b));
- 57 multi-triangle texels: decision 270's V-gap, open;
- 1 single-triangle concave texel.

Over the 5,887 single-triangle ring texels, the Height-inconsistent count goes from 734 (decision 275) to 35.

**So on this mesh Height is exact only up to its unrecoverable operand.** Decision 275's "Height alone" fits, and the ±12-code search, scored codes against operands that are not Painter's.

### 4. What was not the cause

- **Already-padded or bilinear far values, another far triangle, non-manifold seams, mirrored UVs, more taps (hypotheses 1, 2, 3, 5).** The 632 have no far tap at all, and the mesh has no such features.
- **Coverage (hypothesis 4).** The own-only chain over this coverage is exact in BaseColor, Roughness and Metallic on 619 of the 632. A different coverage would change those taps.
- **Decision 273's arithmetic through the fold.** It was not needed for these texels and was not tested. Decision 275's open item (b) stands.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes. `src/export/` belongs to decision 274's integration this round.
2. **Identified, for the integration:**
   - **The gate.** A seam edge whose 3D fold is concave by at least θ₀ contributes no far candidates. Its ring texels take decision 267's own-only taps. Convex seam edges, and concave ones below θ₀, keep decision 275's window.
   - **The bracket.** θ₀ lies in (7.23°, 14.84°) as a dihedral angle, or (6.00°, 14.53°) as J's apex elevation. Production must refuse any concave seam edge inside the bracket until θ₀ is measured (decision 001: nothing unproven is guessed). The Wand's concave edges all lie outside it.
   - **Where it is exact:** on the Wand, 5,465 of 6,334 ring texels in all four maps, and 6,242 Height-consistent.
   - It closes decision 275's open item (a): 619 of the 632 lie on concave edges, and 540 of those are exact in all four maps.
3. **Rejected as the cause of the 632**, with finding 1's counts:
   - padded or sampled far values;
   - a far point from another triangle;
   - non-manifold, mirrored or overlapping UVs;
   - a different coverage;
   - more than 4 taps;
   - a convex-only gate (it loses 420 texels on shallow concave seams);
   - vertex-normal equality across the seam.
4. **Still open:**
   - **(a) θ₀ and its form:** dihedral, apex elevation, or a per-tap or per-texel test. The Wand cannot separate these.
   - **(b) The 34 single-triangle convex seam texels** that are Height-inconsistent, 22 of them on the end cap's seam.
   - **(c) The 57 multi-triangle texels** (decision 270's V-gap).
   - **(d) The Height operand.** A PNG 16 file cannot give the L16F operand. Height exactness against the oracle needs an export whose Height is a float file (OpenEXR), or is scored as consistency (finding 3).
   - **(e)** Decision 275's open items (b), (c) and (e).
5. **A new recording is requested**, for open item (a): a concave-fold sweep of decision 266's seam item.
   - **The configurations:** B folded up rather than down, at 8° to 14° in 0.5° steps, with flat and convex 10° controls.
   - **Separating the forms:** a second set whose B apex is offset along the edge, so that its apex elevation differs from the dihedral.
   - Owner: `phase1.25_pilot-wand` item 2.7 (probe batch).

## Consequences

- **Every Wand seam ring texel on a concave edge of 14.84° or more is own-only.** These are the tip-to-shaft ring, four internal shaft seams and two butt-cap seams. With the gate, the Height-inconsistent single-triangle ring texels drop from 734 (decision 275) to 35.
- **Height scoring should be consistency, not exact codes, on PNG 16 recordings.** One-code Height misses with exact 8-bit maps are not tap-set evidence.
- **These need no retesting** as the cause of the Wand's residual:
  - padded or sampled far values;
  - other far triangles;
  - non-manifold or mirrored UVs;
  - coverage;
  - more than 4 taps.
