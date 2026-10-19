# 285. The gutter flood reads clamped to the image edge, which closes the Wand's 83 flood misses; an own tap in a triangle that shares a UV edge with the ring texel's triangle is measured through its own triangle; the seam reach D lies in [1.772, 1.787) texels of plain segment distance

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

On 2026-10-18 the owner ruled that the Wand must match Painter everywhere, padding included. Exact `infinite` padding (item 2.7 of `phase1.25_pilot-wand`) is the critical path.

**What decision 281 left open, and this pass took:**
1. **The gutter (281, item 4(b)).** Given Painter's own ring values, 83 Wand gutter texels differ: 81 exact flood-seed ties and 2 non-equidistant seeds. No offset order, comparison, step sequence or distance precision beat decision 197's flood.
2. **The curved same-island multi-triangle texels (281, item 4(c)):** 42 all-four ring misses.
3. **The reach cap.** Decision 279 put the seam reach D in (1.7, 1.8] from the probes, while the Wand prefers 1.5. Decision 281 has 6 all-four misses with a seam edge 1.5 to 2 texels away.
4. **"Other" (281, item 4(c)):** 96 all-four ring misses.

Out of scope: multi-facet distances (decision 284), the concave hinge distance (282), the Height operand (283) and the flagged texels.

**How it ran:**
- **The model.** Decision 281's Wand pipeline: `tests/export/padding_reference.py` at f7bbc0a, decision 279's pickled Wand geometry, 281's 1/256 coverage snap and the nearer fewest-hinge development for own and far taps. It reproduces 281's counts exactly: 5,729 all-four ring texels and 2,996,125 all-four gutter texels.
- **Decision 280's tap-count fix** was added first: a kept list with no own tap is not a copy. Decision 281 had not combined it. Main has since integrated both (6fa7fd9). The probe counts here also use it.
- **Scoring.**
  - The Wand is scored as in decision 281: all four maps, plus BaseColor, Roughness and Metallic exact with Height LP-consistent.
  - A flood variant is scored as in decision 281: the gutter texels whose Painter value differs from Painter's value at our flood seed.
  - Probe ring texels must be bit-exact on all 24 channels.
- **The probes:**
  - the `export-padding-kernel-*` probes: atlas 512, 1024, 2048 and 1024-moved; tie-512 and tie-2048; the five ramps; `sphere-256`; `bevelled-cube-256`;
  - decision 272's three sweep seams probes;
  - decision 278's three concave-fold probes.
- **Setting.** CPU only (numpy and scipy): no Painter and no GPU. The scripts read oracle values, so they stay in private scratch (`pad285/`).

## Findings

### 1. The gutter flood reads clamped to the image edge

Decision 197's flood skips a neighbour offset that falls outside the image. Painter clamps the read to the nearest edge texel instead, and takes the seed stored there as a candidate.

**The Wand.** These are gutter texels that differ given Painter's ring values, with 281's snapped coverage:

| Out-of-image read | Differing gutter texels |
|---|---|
| Skipped (decision 197) | 83 |
| Clamped in y only | 2 (the 2 non-equidistant seeds) |
| Clamped in x only | 81 (the ties) |
| **Clamped in x and y** | **0** |
| Wrapped in x, or in x and y | 83 |
| Wrapped in x, clamped in y | 2 |
| Mirrored | 8,302 |
| In-place (Gauss-Seidel) update | 373 |
| L1 distance | 3,210,363 |

- **Why the ties clustered.** The 81 ties sit near the bottom rows (y ≥ 1,922) and around the middle row (y ≈ 1,026 to 1,054). At those rows a step of k = 1,024 or less reads past the bottom edge. The clamped read returns a seed from row 2,047, and that seed carries the tie.
- **The 2 non-equidistant texels.** (1040, 21) and (2047, 9) lie near column 0. There the clamped x read brings in a seed that the skipped read never sees.

**The probes.** These are gutter texels that differ given Painter's ring values. Our coverage is used, with the ring as its uncovered 8-neighbours:

| Probe | Skipped | **Clamped** |
|---|---|---|
| `atlas-512` | 95 | **0** |
| sweep seams `centred`, `offcentre`, `box320` | 22 each | **0** |
| `concave-fold` / `-shape` | 4 / 25 | **0 / 0** |
| tie-512, tie-2048, the atlas at 1024, 2048 and 1024-moved, the five ramps, `concave-fine`, `bevelled-cube-256` | 0 | **0** |
| `sphere-256` | 54 | 54 |

- **The sphere's 54 are not the flood.** They lie at the tile corners. Painter's value there matches no seed at all, which points at the coverage or the ring near the tile border.
- **This corrects decision 197.** Decision 197 rejected clamped addressing, but that run used the default 3 × 3 order. With 197's own offset order, clamping keeps every one of its probes at 0.

### 2. An own tap across a UV edge is measured through its own triangle

**Which taps.** Take an own neighbour that lies in triangle K of τ's island, where:
- τ is the ring texel's triangle (decision 279);
- K ≠ τ;
- K shares a UV edge with τ, that is two UV corners.

**The rule.** Its distance is |q_K − P|:
- q_K is the ring texel's centre extrapolated in K's plane;
- P is the tap's position.

So it is no longer |q − P unfolded into τ's plane|. This is the measure decision 279 (b) already uses for an own neighbour in another island.

| Variant (Wand, with decision 280's fix) | All four | Multi-triangle same-island texels exact (of 447) | Probes |
|---|---|---|---|
| Unfolded into τ's plane (current) | 5,762 | 293 | — |
| **Through K, when K shares a UV edge with τ** | **5,808** | **339** | sphere 916 → 916, cube 1,872 → 1,874, others unchanged |
| Through K, for every K ≠ τ of the island | 5,813 | 344 | sphere 916 → 885 (its 31 exact multi-triangle texels → 0) |
| Unfolded raw position, minimum, maximum or mean of the two | 5,761 to 5,790 | 292 to 321 | — |
| The tap extrapolated in τ's plane | 5,754 | 285 | — |

**Why the rule stops at a shared UV edge.** The sphere's multi-triangle ring texels are V-gaps: K and τ share only one UV corner. There decision 279's unfolded distance is right, on 31 texels, and "through K" is wrong on all of them.

Five Wand texels that share only a vertex prefer "through K". They stay open.

**The class.** Decision 281's 42 curved same-island multi-triangle misses become 34 exact all four. Overall the rule gains 48 texels and loses 2, (130, 808) and (348, 1420).

### 3. The seam reach: plain segment distance, D in [1.772004, 1.787242)

**No other measure reconciles the probes and the Wand.**

| Measure (cap) | Wand all four | Probes |
|---|---|---|
| UV segment distance, D = 1.8 (current) | 5,762 | reference |
| Segment distance, D = 1.5 | 5,774 | sweep loses 69 per box, atlas 4 |
| Perpendicular distance only (foot on the segment) | 5,770 | sweep −730, atlas −91, concave −489 to −842 |
| Foot on the segment ≤ 1.8, past an endpoint ≤ 1.0 | 5,787 | sweep −139, atlas −28 |
| Rectangle: ≤ 1.8 across, ≤ 0.8 past an endpoint | 5,787 | sweep −138 |
| Distance to the edge's line | 5,420 | — |
| Chebyshev distance ≤ 1.25 to 1.28 | 5,777 | cube −2 |
| Own-triangle edges, plus edge-adjacent or corner-adjacent triangles | 5,762 to 5,773 | — |

The probes need two kinds of edges, which the Wand-preferred measures drop:
- **edges whose foot lies on the segment, at 1.767767** (= 1.25·√2): the sweep and atlas seam corners, at every resolution (512, 1024 and 2048);
- **endpoint-nearest edges** (cube (4, 234) at 1.772004; the sweep's endpoint edges below 1.77).

**The bracket.**
- **Lower bound.** `bevelled-cube-256` (4, 234) needs an endpoint edge at **1.772004**. No probe texel needs anything beyond it.
- **Upper bound.** Three Wand texels need an endpoint edge excluded:
  - (740, 1459) at **1.787242**;
  - (349, 1300) at 1.790753;
  - (454, 491) at 1.798331.

  Six more need edges from 1.83 to 1.98 excluded.
- **A value inside it.** D = 1.78 leaves every probe unchanged:
  - sweep 6,301 / 6,286 / 6,611;
  - atlas 2,840 and 2,831 (moved);
  - cube 1,872, sphere 916;
  - concave 6,848 / 11,742 / 14,441;
  - ramps and tie-512.

  It gains 3 Wand texels over 1.8.

**What the Wand's 1.5 preference is not.** 12 Wand texels prefer D ≤ 1.5. Their edges lie 1.54 to 1.73 away, and every one is endpoint-nearest. The probes need edges of that kind included. So these 12 are not a reach effect, and no single measure gives both.

**Decision 281's "reach cap" class is not the reach either.** No cap from 1.5 to 2.5 changes any of its 6 texels. Decision 280's tap-count fix makes 3 of them exact.

### 4. "Other": decision 280's fix, then no rule

- **Decision 280's fix comes first.** It makes 26 of the 96 exact.
- **The other 70 have no rule.** All 70 are single-triangle texels with far taps, 54 of them BaseColor-only.
- **The decode does not settle them.** It searched subsets of up to 4 of a widened pool: no reach limit, no gate, our distances. That allows several tap sets per texel, with no common pattern. Their remaining error is in the far-tap distances or windows, which this pass did not fit.

### 5. Wand counts

Ring of 6,334 texels, gutter of 3,679,663, with decision 281's snapped coverage:

| Rules | Ring all four | BRM + Height consistent | Gutter all four, skipped reads | **Gutter all four, clamped reads** |
|---|---|---|---|---|
| Decision 281 (5,729 / 2,996,125) | 5,729 | 6,013 | 2,996,125 | 2,996,206 |
| + decision 280's tap-count fix | 5,762 | 6,048 | 3,532,327 | 3,532,409 |
| + finding 2 | 5,808 | 6,097 | 3,538,657 | 3,538,739 |
| **+ D = 1.78 (finding 3)** | **5,811** | **6,100** | 3,538,917 | **3,538,999** |

Per map after all of them, ring / gutter (clamped):

| Map | Ring | Gutter |
|---|---|---|
| BaseColor | 6,117 | 3,608,668 |
| Roughness | 6,278 | 3,666,601 |
| Metallic | 6,311 | 3,665,485 |
| Height (LP-consistent) | 6,016 (6,316) | 3,601,815 |

Decision 281's residual classes after these rules (all-four exact, of the class):

| Class | Exact |
|---|---|
| Curved same-island multi-triangle | 34 of 42 |
| Other | 26 of 96 |
| Reach cap | 3 of 6 |
| Multi-facet | 11 of 122 |

Every remaining gutter miss is inherited from a ring miss: given Painter's ring, the clamped flood misses 0.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259).
   - `src/export/` and `tests/export/padding_reference.py` are unchanged. The integration pass takes these rules.
2. **Identified, for the integration:**
   - **(a) The gutter flood.** It is decision 197's flood with every neighbour read clamped to the image edge, in x and in y. A clamped read is not skipped: it returns the seed stored at the edge texel. On the Wand this matches Painter on every gutter texel given Painter's ring, and on every probe except the sphere's 54 corner texels, which are not flood texels.
   - **(b) Own taps across a UV edge.** An own neighbour in a triangle K ≠ τ of τ's island, where K shares a UV edge with τ, takes |q_K − P|, measured through K. Other own neighbours keep decisions 279 and 281: V-gaps sharing a single corner are unfolded into τ's plane.
   - **(c) The seam reach.** It stays the UV segment distance from the ring texel's centre, with D in [1.772004, 1.787242). D = 1.78 is used for the counts, replacing decision 279's 1.8.
3. **Rejected, with the counts above:**
   - for the reach: an endpoint cap, a rectangular cap, perpendicular-only distance, distance to the line, Chebyshev distance, and topological reach (own, edge-adjacent or corner-adjacent triangles);
   - for the flood: wrapped, mirrored and in-place reads, and the L1 distance;
   - for an own tap: "through K" for V-gap triangles sharing only a corner.
4. **Still open:**
   - **(a)** The 70 "other" single-triangle far-tap texels.
   - **(b)** 8 curved texels and the 2 texels that finding 2 loses.
   - **(c)** The 5 Wand texels where K shares only a vertex with τ.
   - **(d)** The 12 Wand texels that prefer D ≤ 1.5 against the probes.
   - **(e)** The sphere's 54 corner gutter texels.
   - **(f)** Decision 287's 28 Normal flood-seed ties and decision 276's 4,370 Normal ties were not rescored. The clamped flood is the first thing to try on them.
5. **No new recording is requested.** Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- **The gutter needs one change: clamp the flood's reads.** With an exact ring, the Wand's gutter is then exact everywhere.
- **The ring takes two small changes:**
  - the own-tap measure across a UV edge;
  - D = 1.78.

  Together with decision 280's fix they move the Wand's measured all-four ring from 5,729 to 5,811, and its gutter from 2,996,125 to 3,538,999.
- **These need no retesting:**
  - other flood addressing modes;
  - endpoint, rectangle, line and Chebyshev reach measures.
