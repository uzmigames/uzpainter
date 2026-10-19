# 276. Outside the islands, Painter's Normal is the mesh map at each texel combined with the padded mesh-free normal, not the stencil of the padded Height

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.12_compositor-height-normal, phase1.18_export-engine

## Context

The Wand measurement (commit 975f6e4) found that padding the stored Normal codes cannot give Painter's Normal outside the islands. Even when it is seeded with Painter's own ring, the flood misses 3,679,387 of 3,679,665 gutter texels. Decisions 245 and 263 say the covered island-edge texels read Painter's `infinite`-padded Height in float32. The working idea was that Painter computes the whole Normal map from that padded Height, so the export would compute it the same way.

This pass checked that idea on the CPU, from the private store, without Painter. Only counts are recorded here. The scripts stay in private scratch (`ngutter/`), because they read oracle pixels.
- **Model.** The height-to-normal model is `tools/parity/fit/normal.py`, which matches `src/evaluator/height_to_normal.cpp` operation for operation. Sharp, z = 0.390625 × 256 / 2048, wrap-around, the recording GPU's rsqrt.
- **Wand inputs.** The bound 16-bit Normal mesh map (OpenGL) and an empty Normal channel (`stack-wand.json` has no Normal layers).
- **Coverage.** Coverage and ring come from `uzp-export-tests process`. The ring is the uncovered texels with a covered 8-neighbour. The gutter is every other uncovered texel. The interior and the edge are as decision 245 defines them.

## Findings

### 1. The model on Painter's padded Height (the decisive test)

Painter's exported PNG 16 Height of the Wand (`infinite`) was decoded as float32(2 t − 1), and the model was run over the whole tile with the mesh map. The result was compared with Painter's `Normal_OpenGL` PNG 16. r1 and r2 give the same counts.

| Class | Texels | Differing | Max codes |
|---|---|---|---|
| Interior | 502,004 | 84,295 | 24 |
| Edge | 6,301 | 2,000 | 21 |
| Ring | 6,334 | 2,076 | 1,957 |
| Gutter | 3,679,665 | 1,121,031 | 2,036 |

- **Covered texels.** PNG rounding explains the interior and edge misses. At 2048 px one Height code (2/65535) moves the Normal by about 20 codes. Painter's covered read-out is not on the 16-bit grid (fills at opacity 0.25 and masks), and the misses are ≤ 24 codes. Decision 223 already shows UzPainter's own evaluated interior is exact.
- **The gutter misses.** Rounding does not explain them. 958,229 of the 1,121,031 have a flat Sharp window: the left, upper and centre taps hold the same Height code. In the gutter those are flood copies of one float, so the stencil returns exactly the flat normal there whatever the rounding. Painter writes a tilted normal there instead. One example is a block of 187,171 texels whose Height is constant (code −54 from 32767) over a flat mesh map. Painter writes one tilted normal (32916, 32808, 65535) across the whole block.
- **Float32 control.** The Tier 0 goldens `export-padding`, `export-padding-sphere` and `export-padding-bevelled-cube` export both maps as OpenEXR 32f with `infinite` padding, so they have no PNG rounding. The stencil of Painter's exported Height reproduces 12 of 35,827, 1 of 1,920 and 0 of 9,856 gutter texels bit for bit. It reproduces 100 of 1,387, 1 of 2,176 and 0 of 2,344 ring texels. The interior stays exact (26,870, 59,264 and 51,040).

So Painter's gutter Normal is not the height-to-normal pass run on the padded Height. The brief's Step 2 (write the gutter as the stencil of our padded Height) would be wrong, and nothing is wired.

### 2. What the gutter is

- **Without a mesh map (Tier 0, float32, r1 = r2).** Each gutter texel is a bit-exact copy of Painter's Normal at the ring texel that seeds it in decision 197's jump flood. This holds at 35,822 of 35,827, 1,917 of 1,920 and 9,856 of 9,856 texels. Each of the 8 misses is either a seed tie where Painter's Height flood misses too (7), or it is matched by a neighbour's seed (1).
  - The Normal channel bitmap on `export-padding` is copied too. In the gutter the channel normal is not the local layer value: it comes from the seed with the height part.
- **With a mesh map (the Wand).** Painter's gutter Normal is not a copy of any normal code. Within each seed region over a flat mesh map it is constant (3,192 of 3,207 regions). Over a non-flat mesh map it follows the mesh map at the texel.
  - Test: recover the mesh-free normal at every texel by undoing the reoriented-normal step of Painter's Normal against the mesh map (float64). Then combine the mesh map at each gutter texel with the mesh-free normal at its flood seed.
  - 3,675,295 of 3,679,665 gutter texels come out within 1 code, and 3,128,828 exactly. The 1-code spread is the noise of undoing the step from 16-bit codes.
  - The remaining 4,370 are flood-seed ties: 4,367 fall in the 4,954 texels where the flood also misses Painter's other four maps, and the last 3 are matched by a neighbour's seed.
  - A flood copy of Painter's Normal codes matches 278 texels.

**Rule (recorded):** outside the islands and the ring, Painter's combined normal is the bound Normal mesh map at that texel, combined (reoriented normal mapping) with the mesh-free normal of the texel's flood seed. The mesh-free normal is the height-derived normal combined with the Normal channel. Painter pads the mesh-free normal, not the Height and not the final Normal. It does not pad the mesh map: the gutter reads the imported map's own texel values.

### 3. The ring of the mesh-free normal is not identified

The gutter copies the ring, so the ring must be exact first. On the Tier 0 float32 goldens, two candidate rings were tested, and neither matches.

**Stencil of the float32 ring Height.** This uses the ring Heights that decision 263 pinned (`taps.pkl`) where every tap is pinned. It is consistent at 95 of 499 tested ring texels on `export-padding`, 0 of 343 on the sphere and 0 of 868 on the cube.

**Decision 267/268's chain over a normal quantity.** This was tested only on ring texels where the same chain reproduces Painter's Height ring and every tap's stencil is inside the island (131 texels on `export-padding`). The table gives the texels matched, of 131.

| Quantity chained | Matched |
|---|---|
| Encoded components fma(n, ½, ½) | 26 |
| Unit vector n | 22 |
| n, renormalised after the chain | 16 |
| The height vector (vx, vy) | 1 |
| The normalised height normal | 1 |

The current kernel is itself inexact on these goldens' Height ring (510 of 1,387, 0 of 2,176, 2 of 2,344), so this ring stays open under item 2.7.

### 4. Tile borders

- **No covered texel on a border.** The Wand's islands span rows 53–1994 and columns 53–751. So no covered texel is within one texel of the tile border, and the stencil's wrap-around (decision 064, fitted on full-coverage grids) is not exercised.
- **The flood does not wrap.** All 8,188 border texels match rule §2 within 1 code under the non-wrapping flood. A wrapping flood would give column 2047 a seed 54 texels away across the border, instead of the island column 751, about 1,296 texels away. Painter's gutter flood does not wrap in x or y.

## Decision

1. **Record the rule of §2.** Outside the islands and the ring, Painter's combined virtual normal is the mesh map at the texel combined with the mesh-free normal of the texel's flood seed. Only the mesh-free normal is padded: the height-derived normal and the Normal channel, together.
2. **No export change.** The brief's Step 2 premise, the gutter Normal as the height-to-normal of the padded Height, is refuted by §1. The rule of §2 needs the mesh-free normal's ring, which §3 leaves open.
   - Decision 245's refusal (`CheckIslandNormal`), decision 259's `CheckPadding` refusal and R-090 are unchanged.
   - The measured padding (`InexactPadding::measure`) of a Normal file is now documented as wrong wherever a mesh map is bound (`src/export/padding.h`). No production code, semantics entry, capability or test changes.
3. **What the implementation will need**, under item 2.7:
   - The evaluator must supply the mesh-free normal. That is `EvaluateVirtualNormalOn` with the flat normal in place of the mesh map. Its texels inside the islands are what Painter pads.
   - Pad it with the exact ring and decision 197's flood.
   - Then combine each uncovered texel with the mesh map at that texel.
   - The covered texels keep decision 263's rule.
4. **Still open, in this order:**
   - (a) the ring of the mesh-free normal (§3);
   - (b) the float32 form of the padded quantity and of the gutter combination (encoded, unit vector, or the separate height and channel normals). The Wand's 16-bit codes pin the structure only to within 1 code, and no float32 recording has a bound mesh map on islands;
   - (c) the combination order when a set has both a mesh map and Normal-channel content on islands. No recording has it.
5. **No new recording is requested now.** (b) and (c) need a golden with an islanded mesh, a bound 16-bit Normal mesh map, Height and Normal-channel content, exporting `Normal_OpenGL` as OpenEXR 32f `infinite`, r1 and r2. Item 2.7 schedules it once (a) is fitted.

## Alternatives Considered

- **Write the gutter as the stencil of UzPainter's padded Height (the brief's Step 2).** Rejected by §1. It misses 1,121,031 Wand gutter texels even on Painter's own Height, 958,229 of them where the Height window is flat. On Tier 0 float32 it reproduces almost none: 12 of 35,827.
- **Pad the stored Normal codes (the current measure path).** Rejected. It misses 3,679,387 Wand gutter texels. It is exact only without a mesh map (§2), which the Wand does not have.
- **Implement §2 now with decision 267's ring on the mesh-free normal.** Rejected under decision 001. The ring misses (§3), and the float32 form is not pinned.

## Consequences

- G1's Normal blocker now has three parts, all under item 2.7: the exact Height ring (decision 263, covered edges), the mesh-free normal's ring (§3), and the gutter rule of §2, which is known. The gutter itself is solved, given the ring.
- The 3.68 million gutter texels that differ are not a separate mystery: the mesh map's texels and the flood's seeds account for all of them.
