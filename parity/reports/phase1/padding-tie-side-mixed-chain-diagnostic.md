# Padding tie-side and mixed-chain diagnostic

Date: 2026-11-02. Status: diagnostic only. No reference or production change; refusals 245/259
unchanged. Task: phase1.25_pilot-wand, item 2.7. Follows decision 366. Front A of decision 367.

## Wand re-measure after decision 366

`UZP_WAND_MEASURE=1 pytest tests/parity/tier1/wand_v1/test_wand_measure.py` (one GPU run, 137 s),
ring texels differing from Painter's r1 (of 6,334):

| Map | Before 366 (published) | After 366 |
| --- | ---: | ---: |
| BaseColor | 99 | 92 |
| Roughness | 22 | 20 |
| Height | 21 | 17 |
| Metallic | 17 | 15 |
| Normal | 60 (+45 covered edge) | 41 (+31 covered edge) |

Interiors of the other four maps stay exact; their gutter differences copy the ring.

## Wand CPU scorer

`tools/parity/fit/padding_wand.py` (commit `91d6caed`) predicts the Wand's BaseColor (sRGB8:
`kSrgb8DecodeBits` operands, `kSrgb8ThresholdBits` store, `kOcioSrgbPng16` codes), Roughness
and Metallic (L8) ring from Painter's own covered texels, through the export's store and write.
Every covered BaseColor code is an OCIO sRGB8 code. On the current reference it reproduces the
GPU measure exactly: 92, 20 and 15 ring texels, the same coordinates (102 in their union). The
Height (L16F) operand is not recoverable from its PNG 16 code, so Height and Normal are counted only
as chain changes against the measured files.

## Cycle 1: the far window's side at exact ties

**Finding.** On kernel-bevelled-cube-256, 206 of the 221 decoded residuals have a far window whose
far point lies within 1e-3 texel of a window boundary (a far texel centre), and taking that one
window on its other side reproduces Painter on 192 of the 240 residuals. Every such tie on the cube
is an along-seam coordinate across a fold (the edge vertical in J's UV, the tie in v); 339 of 684
labelled ties are exactly 0 in double.

**Labels.** Ring texels with a near axis (|f - 1/2 - k| < 1e-3) where the side changes the taps,
labelled by which side reproduces Painter: cube 480 ours / 204 flipped, window-side 119 / 93,
atlas-1024-moved 215 / 55, atlases 262-267 / 19-22, hinge-vary 10 / 15. Labels are mixed within
45 of 59 cube seams, along the edge at a fixed across offset.

**Hypotheses scored** (agreement with Painter's side; cube / window-side / atlas-moved):

| Far point | Agreement |
| --- | --- |
| Double precision (current) | 480/684, 119/212, 215/270 |
| Seam edge snapped to 1/256 or 1/16 texel, linear along the edge | about 345/684 |
| Float32 pipeline: q through tau (fused or split determinant), fold, J normal equations, FMA UV interpolation | 537-549/684, 211-212/212, 228-234/270 |
| The same with Rodrigues or no fold, cross-product barycentrics, edge-form UV, raw positions, v-up flooring | at most 549/684 |
| Per-seam affine transfer with float32 coefficients (texel or UV space) | 537-546/684 |
| One-dimensional along-edge float32 forms (shift, lerp, FMA) | 498/628 (always the exact-tie side) |

"Every tie exact" alone gives 537/684 on the cube, and the best recipes recall at most about 110 of
its 204 flipped labels, so no tested arithmetic predicts the cube's minority side. On window-side,
the float32 pipeline with FMA UV interpolation agrees on all 212 ties.

**Characterization.** The hypothesis is right: the window rule (3 x 3 around floor/ceil of f - 1/2)
holds, and the residual is the side taken at exact ties. The implementation is unidentified: the
float32 arithmetic by which Painter computes the folded far point. It is not on the Wand's critical
path: 101 of the Wand's 102 exact-map misses have no near-boundary axis.

**Next probe (not yet requested).** A kernel probe on folded seam pairs whose positions and UVs are
dyadic rationals (texel-aligned UVs at 256 px, positions on a 1/8 cm grid, fold angles from
Pythagorean triples so the normals are rational), so that every float32 formulation gives exact
along-edge ties at far texel centres, beside a twin set offset by non-dyadic deltas. If Painter
takes the exact-tie side on every dyadic copy, the cube's flips are arithmetic noise of the fold;
otherwise a geometric side rule exists.

## Cycle 2: own taps of mixed chains in float32

**Finding.** The Wand's misses are 4-tap far chains (multi-facet), mostly one to two quantization
bins off on the same taps. On the flat kernel probes the matching residuals (corner-reach, window-
side, hinge) sit 1e-3 to 4e-3 bins from a rounding boundary, about 2e-6 relative distance:
float32-scale geometry, as decision 358 found for chains wholly owned by tau.

**Variants scored** (29 kernel probes, baseline 915; Wand exact maps, baseline 102):

| Variant (fractions only; selection and order unchanged) | Kernel fixed / new | Wand fixed / new |
| --- | ---: | ---: |
| Far taps \|fold32(q) - P_K\| in float32, own through K | 52 / 2,657 | 40 / 88 |
| Far taps float32 through the decision 364/366 turned point | — | 1 / 8 |
| Every own tap float32 through its triangle, far double | 26 / 241 | 2 / 0 |
| Own taps float32 as the double rule measures them (tau or a UV-edge neighbour) | 24 / 7 | 2 / 0 |
| **Own taps in tau float32, only in chains with a far tap and an own tap in tau, far double** | **24 / 3** | **2 / 0** |
| The same, plus coplanar own taps through tau or through K | 24 / 3, 24 / 4 | 2 / 0 |

The 24 fixed texels and the 3 new ones (corner-reach, hinge-single, window-side, one each) sit at
the same boundary gaps (3e-3 bins) and in the same configurations, so the own float32 distance moves
the right way 24 times and the wrong way 3 times. Painter's far distances most likely carry float32
error of the same size, which the double far distance does not model.

**Characterization.** Not accepted: 3 new coordinates (decision 367 requires zero). Cycle 3 shows
that the far distance, not float32 own arithmetic, carries the Wand's residual.

## Cycle 3: far taps of tau's own island (Wand kernel probe)

**Data.** `export-padding-kernel-wand-2048` was admitted on 2026-11-02 (`b0f751e2`). User0-7 are
RGB32F in both recordings. Every export keeps the covered source bit for bit, and r1 passthrough
equals the source. `padding_corpus.py` loads it (`1390fcbb`). The current reference misses 560 of
its 6,334 ring texels with no near-boundary axis, plus one tie. By `--infer`, 432 of the misses are
far chains on the same taps, 60 reorders and 30 own chains.

**Reference/native.** The reference now sums share denominators in sequence, as padding.cpp does
(`c415dfd8`: Python's float `sum()` is compensated). Counts are unchanged on every probe.
`uzp-export-tests ring` (SHA-256 `d615ac47...3ea4`) equals the reference on all 174,609 ring texels
of the 30 probes, taps and values.

**Finding.** Decision 356 makes window texels of tau's own island far taps, but decision 364's frame
turns only the far taps of other islands; own-island far taps keep the face-path development. The
patch `island` of `padding_corpus.py` measures them as decision 364 measures other far taps: turned
rigidly from the J of each open window that holds them, at any reach, the least over them.

Ring texels differing, full pipeline (selection, order, fractions):

| Probe | Baseline | `baseline+island` | Fixed | New |
| --- | ---: | ---: | ---: | ---: |
| kernel-wand-2048 | 561 | 220 | 343 | 2 |
| hinge-vary | 83 | 82 | 1 | 0 |
| The other 28 kernel probes | 832 | 832 | 0 | 0 |

On the Wand maps (`padding_wand.py`, exact): BaseColor 92 -> 14, Roughness 20 -> 3, Metallic
15 -> 4 (union 102 -> 16), zero new. The Height and Normal chains change at 368 ring texels, which
only the GPU measure can score. Painter's Normal covered-edge texels read the raw Height ring.

**Variants rejected** (Wand kernel probe fixed / new):

| Variant | Fixed / new |
| --- | ---: |
| Decision 366's J set (frame J and open windows within 1.17) | 277 / 23 |
| Open windows within 1.17 only | 296 / 23 |
| The least of the face path and the rotations | 139 / 1 |
| P developed into J's face before the turn | 84 / 4 |
| J where the K -> tau face path crosses a UV seam | 246 / 3 |
| Float32 distances for every tap (own through tau, far turned) | 351 / 55, and 4 new on atlas-1024-moved |
| Taps re-sorted or re-selected by the float32 distances | corner-reach +60 to +170 new |

The seam-crossing test read a crossing from `links`' first shared edge of each face pair, so it does
not exclude every seam topology.

**The 2 new coordinates.** Each has one open window, a two-hinge face path, a tap on another
face than J, and every hinge folded past decision 282's gate. Painter's bins there equal the face-
path development, and no single triangle of the island reproduces them as J. Every feature tested
(window count, J on the path, K's face against J's, fold gates, UV-seam pattern along the path)
is shared by 11 to 199 fixed or exact chains. The reviewer's "J just outside the last entry into tau's chart on the winning path" is undefined for both, because every triangle of their paths lies in tau's chart. Read at the path's one UV seam instead, it is the window's J that the rule already uses, so it is rejected. The rule is therefore not accepted, and production
stays decision 366.

**Characterization.** The hypothesis is supported by 343 fixed coordinates on the Wand's own
geometry, with zero new on the 29 kernel probes and on the Wand maps. What separates the 2 new is
unidentified. The recordings already decode both texels exactly, so a new probe is not needed;
the next step is the geometric cause of those 2 texels.
