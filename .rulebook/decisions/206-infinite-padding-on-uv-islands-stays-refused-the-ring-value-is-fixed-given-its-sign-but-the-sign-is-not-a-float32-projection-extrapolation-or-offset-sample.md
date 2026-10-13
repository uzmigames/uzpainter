# 206. `infinite` padding on UV islands stays refused: the ring value is fixed given its sign, but the sign is not a float32 projection, extrapolation or offset sample

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

Item 2.7 of `phase1.25_pilot-wand` asks for a bit-exact fit of `infinite` padding on UV-islanded sets. Decision 197 identified the gutter: a jump flood, bit-exact on all 11 probes when it is seeded with Painter's ring. It left open the sign of the ring offset. Every straight-edge ring texel sits ±25·2⁻¹⁵ (512) or ±24·2⁻¹⁵ (1024, 2048) of a texel off the weighted mean, along the edge, and never at zero.

This pass tested the three hypotheses the brief named:
1. **H1.** The ring is a bilinear sample of the covered texture at the ring texel's centre projected onto the UV edge in float32.
2. **H2.** The ring is extrapolated from the covered neighbours with a float32 finite-difference gradient, over a float32 distance to the UV edge.
3. **H3.** The ring is an offset-sample rasterisation. The test solves each ring texel's sample position from its value: the ramp encodes R = u and G = 1 − v.

The data is the same as decisions 176, 184 and 197:
- the P-ramp probes `export-padding-ramp-{r1,r2,r15}-{p0,p25,p75}-v2` (1024);
- the P-tie probes `export-padding-tie-512` and `export-padding-tie-2048-v2`.

Each is User0 RGB32F at r1 step 10. The r2 recordings are bit-identical to r1 on all 11 probes.

The test set is the 17,508 straight-edge ring texels, those with exactly three covered neighbours in a line:

| Probe | Ring texels |
|---|---|
| tie-512 | 744 |
| tie-2048 | 3,048 |
| r1 (each phase) | 1,524 |
| r2 (each phase) | 1,140 |
| r15 (each phase) | 1,908 |

There are also 120 corner-adjacent ring channels, with one side and one diagonal covered neighbour.

Everything ran on the CPU from the private store, without Painter, within a 2-hour time box. Comparison is on float32 bit patterns. Only counts are recorded here, and the scripts stay in private scratch (`pad206/`). The meshes are `parity/fixtures/tier0-semantics/meshes/tie.obj` and `seam-ramp-*.obj`.

## Findings

### 1. The three hypotheses are rejected

Sign agreement is counted only where the hypothesis predicts a nonzero along-edge error.

| Hypothesis | Variants | Along error zero | Sign agreement where nonzero | Bit-exact ring values |
|---|---|---|---|---|
| H1: projection onto the UV edge, then masked bilinear | 3 centre constructions × 3 projections (t = dot/len² clamped, barycentric, line equation) | t and line: 17,508 / 17,508. Barycentric: 17,011 | barycentric: 297 / 497 (r15 only) | 0 / 17,508 |
| H2: finite-difference gradient extrapolated to the float32 edge projection | 2 centre constructions × 2 projections | 17,508 / 17,508 | none | 0 / 17,508 |
| H3: solved sample position | none | none | none | not applicable |
| Extra: UV → barycentric → world → UV round trip in float32 | ring centre, side neighbour | ring centre 15,763; side neighbour 15,753 | 871 / 1,745 and 680 / 1,755 (r15 only) | not applicable |

**H1 and H2.**
- Every candidate is exact on the tie, r1 and r2 geometry. Their UVs are dyadic, so the float32 projection carries no error, and therefore no sign.
- Where an error exists (r15), it agrees with Painter's sign only at chance.
- H1 reproduces the perpendicular channel, because the masked bilinear keeps the covered centre. H2 does not: its perpendicular value lands on the edge, half a texel outside that centre.

**H3.**
- The solved position of every one of the 17,508 texels lies exactly one texel inward, perpendicular to the edge, at the covered neighbour's centre.
- Along the edge it lies ±25·2⁻¹⁵ texel (512) or ±24·2⁻¹⁵ texel (1024, 2048) from the centre.
- None lies inside the ring texel's own footprint. A conservative or offset-sample rasterisation of the ring texel would place its sample inside that footprint, so H3 is rejected.

### 2. Given its sign, the ring value is bit-exact

**The output grid.** Every ring value lies on a grid of 2⁻²⁴ in UV, whatever its float binade (its power-of-two range).

**The model.** The ring value is the exact position, rounded first to float32 at the result's own ulp, then to the 2⁻²⁴ grid with ties to even. With that rounding:
- **Corners: 120 of 120 channels are bit-exact.** The weight fraction f lies in [0.4142230, 0.4142260], slightly above √2 − 1 = 0.4142136.
  - With f = √2 − 1, only 48 of 120 match.
  - With a single rounding to the grid, only 96 of 120 match.
  - The double rounding explains the corner values in [0.25, 0.5) that decision 197 saw as ±1 anomalies: 13,574 at 512, 6,786 at 1024 and 3,394 at 2048, in units of 2⁻²⁴.
- **Straight edges: the along channel is bit-exact on 17,508 of 17,508.** The model is the centre ± E·2⁻¹⁵/N, with Painter's sign and one constant E for every resolution, with E between 24.75 and 25.0.
  - With E = 24.5: 16,764 match.
  - With E = 25.1: 12,936 match.
- **The perpendicular channel** is the covered centre on every texel.

So once the sign rule is known, the ring is fully determined, and with it the decision-197 gutter.

### 3. What the sign follows

**Fixed per side on three probe families.** On r1 (all three phases, both islands), r2 (both islands) and r15's 256-texel island, every texel takes one direction, and none of the 10,278 is an exception:
- horizontal edges shift +x;
- vertical edges shift −row;
- in UV, with v up, both point toward +u, +v.

**Mixed on two families.** The sign varies on:
- tie at both resolutions;
- r15's 384-texel island, which runs in period-3 patterns whose phase slips at x = 256, that is u = 0.25.

**On tie:**
- **A shared start.** Read in image order (left to right, top to bottom) from each edge's first ring texel, edges start with the same run:
  - all six left and right edges of the three islands: "−−+−+−+−+" in the +row sense;
  - all three top edges, and island 1's bottom edge: "++−++−++−" in the +x sense.

  The bottom edges of islands 2 and 3 do not follow it: their first 18 texels are all +.
- **Then they diverge.** Edges with the same along-edge range diverge with the perpendicular coordinate.
  - The right edges at u = 0.5615 and u = 0.8115 differ in 2 of 62 texels, and the left edges at u = 0.1885 and u = 0.6885 in 1 of 62.
  - The right edge at u = 0.3115 differs from the one at u = 0.8115, on the same rows, in 11 of 62, the first at the 18th texel.
- **Two readings fit equally.** The diverging edges are those whose perpendicular u lies in [0.25, 0.5). They are equally those whose island's world-space x lies in a different power-of-two range (5 against 17 and 29; 19 against −5 and 7).

**What it points to.** The sign therefore comes from a float32 rounding that is exact on r1, r2 and r15's 256-texel island and inexact on tie and r15's 384-texel island. No UV-space computation qualifies:
- on tie every UV quantity is dyadic and exact;
- r15's 256-texel island has non-dyadic UVs yet a fixed sign.

The source is some other per-island quantity.

## Decision

1. `infinite` padding on islanded sets stays refused before writing (`padding.h`, `NotYetSupported` naming R-090).
   - Item 2.7 stays unchecked.
   - No production code, semantics entry, capability, conformance case or golden-comparison test changes.
   - **Why.** The ring is exact only given Painter's sign, so no full padding golden can be reproduced. The brief gated the full-padding and seam checks on an exact ring, so they were not run.
2. **Rejected, with the counts above:**
   - H1: projection onto the UV edge, then sampling (9 variants);
   - H2: gradient extrapolation (4 variants);
   - H3: offset-sample rasterisation;
   - a world-space round trip.
3. **Identified, recorded for the implementation:**
   - the output rounding: float32, then the 2⁻²⁴ UV grid with ties to even;
   - the corner fraction, f in [0.4142230, 0.4142260];
   - the straight-edge magnitude, E·2⁻¹⁵ texel with E in [24.75, 25.0] at every resolution;
   - the fixed direction (+u, +v) where the sign does not vary.
4. **Still open:**
   - **(a)** The sign rule on tie and on r15's 384-texel island (decision 197, 4(a)).
   - **(b)** The seam blend (decision 176, 3(b)).
   - **(c)** The sphere poles (decision 129 (c)).
   - **(d)** Confirming the decision-197 gutter on `export-padding`, `export-padding-bevelled-cube` and `export-padding-sphere`.
5. **No new recording is requested.** The next measurement is offline. It is to find which per-island float32 quantity is inexact on tie and on r15's 384-texel island but exact on the other islands, starting from the shared start of finding 3. Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- G1's P1-WAND gate and the wand's five-map export stay blocked on 2.7, as decisions 127, 129, 176, 184 and 197 recorded.
- An implementation can already reproduce the ring and the gutter on every island whose sign is fixed. It still cannot claim exactness in general, because the sign rule on the other islands is unknown.
- Projection, extrapolation, offset-sample and world-round-trip explanations of the sign need no retesting.
