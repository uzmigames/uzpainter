# 287. The Normal's padding ring is a plain copy of the nearest covered 8-neighbour, not the ring kernel: bit-exact on every Tier 0 float32 ring texel, and the Wand's Normal ring and gutter within 1 code up to 28 flood-seed ties

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.12_compositor-height-normal, phase1.18_export-engine

## Context

Decision 276 found that outside the islands Painter's Normal is the mesh map at each texel combined with the padded mesh-free normal (the height normal combined with the Normal channel). The gutter is a copy of the ring texel that seeds it in decision 197's flood. What was open (its item 4 (a)) was the ring: how Painter fills the mesh-free normal on the ring texels. Two candidates had failed on the Tier 0 float32 goldens: the stencil of decision 263's pinned ring Heights (95 of 499) and decision 267/268's chain on normal values (at most 26 of 131). Both were tested before decisions 270–281 improved the ring kernel.

This pass retested those candidates against the current kernel and then looked for the actual rule. The owner's rule applies: everything must be identical.

**Method.**
- **Setting.** CPU only (numpy and scipy). No Painter and no GPU. The scripts read oracle values, so they stay in private scratch (`pad287/`). Only counts are recorded here.
- **Goldens.** The Tier 0 goldens `export-padding` (mesh `islands`, with a Normal channel bitmap), `export-padding-sphere` and `export-padding-bevelled-cube`. Each one exports `Normal_OpenGL` and Height as OpenEXR 32f with `infinite` padding. r1 and r2 give the same counts.
- **Ring kernel.** The ring kernel is `tests/export/padding_reference.py` at main (decisions 278 and 279), plus decision 280's tie order and tap count. A ring texel is an uncovered texel with a covered 8-neighbour, with wrap-around in x as the reference uses. The gutter is every other uncovered texel.
- **Normal model.** The normal model is `tools/parity/fit/normal.py` (Sharp, the recording GPU's rsqrt).
- **The Wand.** The Wand uses decision 276's inputs (`Normal_OpenGL` PNG 16 and the bound 16-bit mesh map) and its recovered mesh-free normal. Coverage is snapped as in decision 281: two texels become covered.

## Findings

### 1. The current kernel's float32 Height ring (context for hypothesis (a))

With the L16F write rule (rounding toward zero to half), the current kernel reproduces Painter's exported Height ring at 1,379 of 1,387, 1,585 of 2,176 and 1,969 of 2,344 texels. Decision 276's 510, 0 and 2 compared the float32 chain with the half export directly.

The float32 values behind those halves are still not exact. Padded with the current ring and decision 197's flood, they reproduce the covered edge normals at:
- 1,248 of 1,452 edge texels on `export-padding`;
- 1,405 of 2,176 on the sphere;
- 1,907 of 2,296 on the cube.

The interior is exact (26,870, 59,264 and 51,040).

### 2. The brief's three hypotheses are rejected

The table gives the ring texels reproduced bit for bit in all three float32 components. Every chained row uses the current kernel's taps and decision 268's quantised fractions.

| Hypothesis | export-padding (1,387) | sphere (2,176) | cube (2,344) |
|---|---|---|---|
| (a) Stencil of the padded Height (current kernel's float32 ring, then decision 197's flood) | 100 | 0 | 0 |
| (b) Chain over the encoded components fma(n, ½, ½) | 105 | 38 | 0 |
| (b) Chain over the encoded components, then decode, renormalise and encode | 80 | 21 | 0 |
| (b) Chain over the unit vector n | 77 | 13 | 0 |
| (b) Chain over n, then renormalise | 65 | 13 | 0 |
| (b) Chain over n's x and y, then z = √(1 − x² − y²) | 56 | 13 | 0 |
| (c) Chain over the height normal, then combine with the channel | 97 | 10 | 0 |
| (c) Chain over the reoriented base, then combine with the channel | 97 | 13 | 0 |

**Why they fail.** On the cube, Painter's ring normal is often steeply tilted next to nearly flat covered normals: (0.952, 0.324, 0.620) beside (0.494, 0.503, 1.000). So it is neither a blend of the kernel's taps nor a stencil of the padded Height there.

### 3. The rule: each ring texel is a copy of one covered texel

**Test.** For every ring texel, every covered texel holding Painter's exact float32 Normal bits was looked up. Painter's ring value is a bit-exact copy of a covered texel on all but the tile-border texels of §4:
- 1,288 of 1,288 on `export-padding`;
- 2,152 of 2,152 on the sphere;
- 2,344 of 2,344 on the cube.

**Which texel.** The copied texel is the nearest covered 8-neighbour in texel distance, without wrap-around: a side neighbour before a diagonal one.
- **Equally near neighbours** go in decision 197's flood offset order, as (dy, dx), v down: (0, 1), (0, −1), (−1, 0), (1, 0), (−1, 1), (1, −1), (−1, −1), (1, 1). The first covered one at the smallest distance wins. That is a single strict-comparison k = 1 flood pass over the covered texels.
- **Ties observed.** 1,089 ring texels have two or three equally near neighbours with different values: 256 on `export-padding`, 494 on the sphere, and 339 on the Wand that the 16-bit codes separate by more than 1 code. The order matches all 1,089.
- **Decision 197's full flood** over the covered texels matches 1,088 of them. It misses one diagonal tie, `export-padding` (96, 23).
- **Pinned as copies.** On `export-padding`, `export-padding-sphere` and `export-padding-bevelled-cube`, renormalising the copied unit vector changes 112, 27 and 120 of the copies whose source the model reproduces. So the copy is of the float32 normal as it is.

**Rejected selections:**
- The ring kernel's first tap, which may be a far tap across a seam: 1,111, 411 and 68 texels.
- The nearest own neighbour by decision 273's 3D comparator: 1,111, 2,081 and 2,344. At the tied texels, 3D distance picks Painter's texel at only 79 of 256 and 429 of 494.

### 4. Ring texels whose covered neighbours are all across the tile border

Some ring texels have covered 8-neighbours only through the wrap-around in x: 99 on `export-padding` (column 255) and 24 on the sphere (columns 0 and 255). Painter does not pad these. They hold the unpadded value: a flat height normal combined with the Normal channel's own texel there.
- This reproduces 99 of 99 and 24 of 24 bit for bit.
- The stencil of the padded Height does not reproduce the sphere's 24: Painter writes the flat (0.5, 0.5, 1) there.
- These texels are ring texels for the Height kernel (decision 263; the kernel reproduces all 99 on `export-padding`). For the Normal they keep their own value and seed the gutter flood like every other ring texel.

### 5. The whole Tier 0 tile

The rule of §3 and §4 on the ring, then decision 197's flood over the covered and ring texels (decision 276). Counts are bit-exact, r1 = r2.

| Golden | Ring | Gutter |
|---|---|---|
| `export-padding` | **1,387 / 1,387** | 35,822 / 35,827 |
| `export-padding-sphere` | **2,176 / 2,176** | 1,917 / 1,920 |
| `export-padding-bevelled-cube` | **2,344 / 2,344** | **9,856 / 9,856** |

- **The gutter residual.** These are decision 276's 8 texels, the same count it gets from Painter's own ring: flood-seed ties.
- **Two floods, not one.** A single flood over the covered texels and the §4 texels gets 33,979 and 1,785 gutter texels, so the ring step comes before the gutter flood.
- **End to end with UzPainter's own covered normal** (§1's float32 Height ring):

| Golden | Covered | Ring | Gutter |
|---|---|---|---|
| `export-padding` | 28,118 / 28,322 | 1,147 / 1,387 | 30,663 / 35,827 |
| `export-padding-sphere` | 60,669 / 61,440 | 1,020 / 2,176 | 771 / 1,920 |
| `export-padding-bevelled-cube` | 52,947 / 53,336 | 1,929 / 2,344 | 7,936 / 9,856 |

  All of these misses come from the covered edge texels (decision 263's float32 Height ring), which the ring and the gutter copy.

### 6. The Wand (16-bit, mesh map bound)

**The test.** For each ring texel, the mesh-free normal was copied from the covered neighbour chosen by §3 and combined with the mesh map at the ring texel. Every gutter texel takes the mesh-free normal of its flood seed over the covered and ring texels (decision 276). Coverage is snapped as decision 281 requires.

| Class | Within 1 code | Exact | Max |
|---|---|---|---|
| Ring | **6,334 / 6,334** | 4,966 | 1 |
| Gutter | **3,679,635 / 3,679,663** | 3,435,905 | 592 |
| Covered, round trip of the recovery (noise floor) | 508,307 / 508,307 | 506,003 | 1 |

- **The 1-code spread** is the noise of recovering the mesh-free normal from 16-bit codes. The covered round trip has the same noise.
- **The 28 gutter misses** each have two or more equally near flood seeds. They are decision 197 seed ties.
- **With unsnapped coverage** the ring has 6,332 texels within 1 code. The 2 misses, (454, 548) and (455, 548), are decision 281's coverage texel and its neighbour.
- **Decision 276, given Painter's own recovered ring:** 3,675,295 gutter texels within 1 code. With the modelled ring the count rises to 3,679,635.
- **No mesh step:** the copy of Painter's 16-bit codes matches 183 ring texels within 1 code.

## Decision

1. **Recorded rule: Painter's `infinite` padding of the virtual Normal.**
   - The padded quantity is the mesh-free normal (decision 276). Its covered texels are decision 263's evaluated normal.
   - **The ring.** A ring texel copies the float32 mesh-free normal of its nearest covered 8-neighbour: texel distance, no wrap-around, ties in decision 197's flood offset order, with no blend and no renormalisation.
   - **No neighbour.** A ring texel with no covered 8-neighbour without wrap-around keeps its unpadded value: a flat height normal combined with the Normal channel at that texel.
   - **The gutter.** Every other uncovered texel copies its seed in decision 197's flood over the covered and ring texels.
   - **The mesh map.** Each uncovered texel then combines the mesh map at that texel with the padded mesh-free normal (decision 276).
   - **Independence from item 2.7's kernel.** The ring kernel of decisions 267–281 is not used for the Normal. The Normal's padding depends on it only through the covered edge texels (decision 263).
2. **Hypotheses (a), (b) and (c) are rejected**, with the counts in §2.
3. **The float32 form is pinned where a recording shows it.**
   - Without a mesh map, the ring and the gutter are bit-exact copies of the float32 normal (§3, §5). The encoded and unit forms cannot be told apart, because a copy preserves both. A renormalisation after the copy is rejected.
   - With a mesh map, the combination order is pinned only to within 1 code (§6). This is decision 276's item 4 (b), still open.
   - Decision 276's item 4 (c) is still open: no recording has a mesh map and Normal-channel content on islands.
   - **Assumption, not observed:** a §4 texel on a set with a mesh map is the mesh map at that texel combined with the flat height normal and the local channel. No recording has a §4 texel with a mesh map; the Wand has none.
4. **No production change.**
   - Decision 245's refusal (`CheckIslandNormal`), decision 259's `CheckPadding` refusal and R-090 are unchanged.
   - No `src/`, test, semantics entry or capability changes.
   - What still blocks an exact Normal is decision 263's float32 Height ring at the covered edge texels (§1, §5). That is item 2.7's open ring, not the Normal's padding.
5. **Integration**, under item 2.7, once decision 263's edge is exact:
   - give the Normal file its own padding (§1 of this Decision) instead of the measured ring kernel;
   - combine the mesh map per uncovered texel (decision 276, Decision 3).
6. **No new recording is requested.** Decision 276's item 5 recording (a mesh map, Height and Normal-channel content on islands, `Normal_OpenGL` OpenEXR 32f `infinite`, r1 and r2) still closes items 4 (b) and 4 (c).

## Alternatives Considered

- **The stencil of the padded Height on the ring (a).** Rejected by §2: 100, 0 and 0 texels. On the sphere's border texels Painter writes the flat normal where the stencil gives a tilt.
- **The ring kernel over a normal quantity (b and c).** Rejected by §2: at most 105, 38 and 0 texels.
- **Decision 197's full flood over the covered texels for the ring.** It matches 1,088 of the 1,089 observed ties. The single k = 1 pass in the same offset order matches all of them, so the pass is recorded. The two are identical except on diagonal ties.
- **One flood over the covered texels for the whole outside.** Rejected by §5: the gutter needs the ring texels as seeds.

## Consequences

- Decision 276's item 4 (a) is closed. With exact covered normals the Normal is exact on every Tier 0 float32 ring texel, and on the gutter up to decision 197's seed ties. The Wand's Normal outside the islands reaches the 16-bit noise floor, up to 28 seed ties.
- G1's Normal blocker shrinks to decision 263's covered edge (the float32 Height ring under item 2.7) and the 16-bit float32 form of the mesh combination (decision 276, item 4 (b)).
- **These need no retesting:** the ring kernel's taps, fractions or tie orders applied to normals; the stencil of the padded Height outside the islands.
