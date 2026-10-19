# 294. Three ring rules found without a new recording: a seam edge of another facet that is reached past its end (beyond a UV corner of the island) has a shorter reach, 1.0 when a seam edge meeting it at that corner is gated and 1.15 otherwise; an own-far tie is ordered by the float32 distances; own taps within 10⁻⁴ of each other are ordered by decision 273's comparator. Wand +20 / −0 (all four 5,897 → 5,917, gutter all four 3,575,535 → 3,580,689), no change on any of 18 probes or the 3 Tier 0 goldens

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.26_gate-g1

## Context

The Wand v1 is gate G1's pilot. The owner ruled that its maps must be identical to Painter's everywhere, padding included. Exact `infinite` padding on UV islands is item 2.7 of `phase1.25_pilot-wand`.

**What was open.** Decision 292 left 437 all-four ring misses on the Wand under the full model, which main 39d8d7b now implements (C++ and the Python reference agree). Two classes wait on other work:
- 293 Height-operand texels wait on decision 283's float recording;
- 119 multi-facet texels wait on decision 289's probes.

The other 25 need no new recording, and they are this pass's target:

| Class (decision 292) | Texels |
|---|---|
| `mixed-gates` | 15 |
| Near-tie (decision 291's list) | 7 |
| Curved multi-triangle | 2 |
| Seam edge 1.5 to 2 texels away | 1 |

Decision 292's open item (c) also says that 19 Wand texels are exact under some gate assignment that the τ-normal gate does not choose.

**How it ran.**
- **The model** is `tests/export/padding_reference.py` at main 39d8d7b, with no change. Each candidate rule is a source patch of `Ring.candidates` or `Ring._ordered`, in private scratch `E:/tmp/uzp-scratch/pad294/` (`rules294.py`, `explore.py`, `dropE_h.py`, `base.py`, `h/sref.py`, `h/t0/t0.py`).
- **The baseline matches decision 292's integration.** The model reproduces it exactly:
  - ring: BaseColor 6,201, Roughness 6,299, Metallic 6,313, Height 6,016, Height LP-consistent 6,318, all four 5,897;
  - gutter all four 3,575,535;
  - the same 437 misses in the same classes.
- **Scoring.**
  - **On the Wand**, BaseColor, Roughness and Metallic (BRM) must be exact. Height is scored exact and with decision 277's LP consistency.
  - **No loss on the Wand.** A rule may not lose any texel on any map, nor any LP-consistent Height texel. This is checked texel by texel, not only on the all-four count.
  - **On the 18 probes**, all 24 channels must be bit-exact per ring texel, compared texel by texel with main.
  - **On the 3 Tier 0 goldens** (`export-padding`, `-sphere`, `-bevelled-cube`), decision 288's Height-consistent and exact columns are compared texel by texel.
- **Setting.** On the CPU with numpy and scipy, in about two hours. No Painter, no GPU, no `src/` change. The scripts stay in private scratch because they read oracle values. Clean room: black-box fits of our own recordings only.

**How the rules were found.**
- **First, per texel.** For each target texel the search scored every gate assignment of its reaching seam edges, every subset of dropped far taps among its first 10 candidates, and swaps of near-tied candidates.
- **Then, per edge.** For every Wand ring texel and every open seam edge of a triangle E ≠ τ, the search closed that edge alone. It labelled the edge *must-drop* when that makes the texel BRM-exact and Height-consistent, and *must-keep* when it breaks it.

## Findings

### 1. The `mixed-gates` texels are not a gate question: they are a reach question at an island corner

**The pattern.** Of decision 292's 15 `mixed-gates` misses, 11 are exact only when both edges are closed. 4 multi-facet texels are exact in the same way.
- In all 15, the open edge belongs to a neighbouring triangle E ≠ τ.
- In all 15, the ring texel's nearest point of that edge is an **endpoint**: the projection of the texel centre onto the edge falls outside [0, 1].
- That endpoint is a UV corner V of τ, where a nearer seam edge of the island also ends. Usually that nearer edge is τ's own edge, and it is gated.

So the texel lies beyond a corner of the island boundary. The far edge reaches it only through its endpoint.

**Closing these edges is the reach, not the gate.** No gate form tried separates the 15 from the 141 `mixed-gates` texels that need such an edge kept:

| Rule tried (Wand, against main) | Change |
|---|---|
| Per far tap, gate by the tap's own triangle K (n_τ · n_K, q behind K's plane) | +15 −70 |
| The same, and the edge rule | +15 −67 |
| K is some edge's J: that edge's gate | +10 −32 |
| Per far chart, the nearest edge's gate for all its edges (UV reach / 3D distance) | +15 −15 / +15 −14 |
| Per far chart, τ's own edge's gate closes every edge into it | +13 −6 |

**The edge labels separate cleanly.** These are the endpoint-nearest edges of triangles outside τ's planar face, not collinear with the edge they meet at V (finding 2). They are labelled by BRM exact and Height LP-consistent:

| Edge meeting it at V | Must-keep reaches | Must-drop reaches |
|---|---|---|
| Some reaching edge ending at V is gated | 0.0539, 0.6395, 0.6648 (and (274, 1989) needs one of 0.9746 and 1.17) | **1.0200** (175, 1101), 1.0532, 1.0938, 1.2540 … 1.7256 (15 texels) |
| Every edge ending at V is open | 0.4596, 0.6654, 0.7514, 1.0130, **1.0759** (634, 1418) | **1.2081** (566, 1439), 1.2744, 1.3679 |

**No single cap fits.**
- With one cap for every such edge, (634, 1418) needs at least 1.0759, while (175, 1101) needs less than 1.0200.
- At a cap of 1.015, (634, 1418) loses all three BRM maps. It was a Height-operand texel: BRM exact and LP-consistent. Its all-four miss hid the loss.

**The rule.** A seam edge (E, J) with all of the following reaches the ring texel only within D_end texels:
- E is outside τ's planar face;
- the edge's nearest point to the texel centre is an endpoint V;
- the edge is not collinear with another seam edge of the island that ends at V.

The value of D_end depends on the edges that meet it at V:
- **D_g = 1.0** when some other reaching seam edge that ends at V is gated for this texel. The bracket is [0.974615, 1.020004).
- **D_o = 1.15** otherwise. The bracket is [1.075926, 1.208074).

The other edges keep decision 285's segment reach, D = 1.78.

**What it does on the Wand: +17 −0 all four, with no per-map loss.** The 17 come from three classes:
- 11 of the 15 `mixed-gates` texels: (89, 613), (134, 866), (135, 869), (272, 1989), (391, 864), (391, 867), (392, 849), (436, 609), (438, 604), (439, 604) and (739, 1459);
- 4 multi-facet texels: (132, 851), (175, 1101), (356, 1099) and (738, 1457);
- 2 near-tie texels: (566, 1439) and (610, 1463).

Per map the rule gains BaseColor +17, Roughness +11, Metallic +4, Height +5 and Height LP-consistent +5. The gutter all four rises by 5,080, almost all of it seeded by (566, 1439) (3,082), (738, 1457) (867) and (610, 1463) (786).

**What it does on the probes: nothing.** No chain changes on any of the 18 probes, and no texel's status changes on the 3 Tier 0 goldens. The rule is fitted on the Wand alone. The probes neither confirm it nor contradict it, as with decision 292's τ normal.

**The brackets.** One Wand texel lies inside each bracket, and both miss either way: (738, 1456) in D_g's and (339, 1862) in D_o's.

### 2. Why the collinear exemption and the facet condition

**The facet condition.** Applied to every E ≠ τ edge, including edges in τ's own planar face, the endpoint cap loses texels:
- `atlas-512`, `-1024` and `-2048` lose 4 each and the moved atlas 3, among them (18, 160), (93, 160), (119, 160) and (456, 24);
- `ramp-r15-p0` loses 2 and `ramp-r2-p25` 1;
- the cube gains 9 and loses 4: (251, 50), (89, 178), (80, 190) and (4, 234).

On those flat islands the endpoint edges of the quad's other triangle need decision 285's full reach.

**The collinear exemption.**
- **The texel that needs it.** Restricted to other facets, the cap still loses `bevelled-cube-256` (4, 234). That is decision 285's lower bound for D: an endpoint edge at 1.772004 is needed there.
- **Its edge is collinear.** That edge continues τ's own seam edge in a straight line at V: the angle is 180.0° and the sine is exactly 0.
- **The Wand edges are not.** Every must-drop edge of the table bends at V; the straightest is (175, 1101)'s, |sin| = 0.0305.
- **The exemption.** An edge is exempt when it is collinear with another seam edge of the island that ends at V: |sin| ≤ 10⁻³ in UV. The threshold's bracket is [0, 0.0305): (4, 234) needs 0 exempt, and (175, 1101) needs 0.0305 capped. Any value inside gives the same counts. The exemption is pinned by (4, 234) alone.

### 3. Two tie orders

**(a) An own-far tie is ordered by the float32 distances.**
- **The texel.** (204, 1614): the own tap (205, 1614) at 0.000171020630 and the far tap (338, 1613) at 0.000171020702 fall in one tie band of 10⁻⁵ relative.
- **What the model does.** Decision 280's order puts the own tap first, as its tie key's first element. That is the `own-far-tie` flag.
- **What Painter does.** It takes the far tap first.
- **The rule.** Within a tie group, sort by the float32 distance of decision 280's keys first: the own tap's decision 273 comparator distance, the far tap's float32 |fold(q_E) − P|. Then own before far, then the neighbour or window order.
  - The own tap here is 0.0010060023; the far tap's key is smaller.
  - The Wand gains 1. No probe chain changes: every own-far tie on the probes, such as `ramp-r1-p0`'s 8, already agrees.

**(b) Own taps within 10⁻⁴ relative are ordered by decision 273's comparator.**
- **The texel.** (345, 1479): the own taps (344, 1480) and (344, 1478) are 4.2025·10⁻⁵ apart in float64 distance, outside decision 288's tie band of 10⁻⁵.
- **What the model does.** It orders them by float64, so (344, 1480) comes first.
- **What Painter does.** It takes (344, 1478), the nearer under decision 273's float32 comparator: 0.0014216336 against 0.001421645.
- **The rule.** Adjacent own taps whose float64 distances lie within ε_own relative are ordered by the comparator.
  - The Wand gains 2: (345, 1479), and the multi-facet texel (348, 1420), which a band of 2·10⁻⁵ already gains.
  - The bracket for ε_own is [4.21·10⁻⁵, at least 10⁻²]. Bands up to 10⁻² gain the same 2 and lose nothing on the Wand. 10⁻⁴ is used.
  - On the probes one chain changes (`atlas-1024-moved`), and it misses either way.

### 4. All three together

**Wand, ring of 6,334 and gutter of 3,679,663:**

| Map | Main ring | **294 ring** | Main gutter | **294 gutter** |
|---|---|---|---|---|
| BaseColor | 6,201 | **6,221** | 3,645,466 | **3,647,542** |
| Roughness | 6,299 | **6,311** | 3,668,608 | **3,671,895** |
| Metallic | 6,313 | **6,317** | 3,665,486 | **3,665,562** |
| Height (LP-consistent) | 6,016 (6,318) | **6,021 (6,323)** | 3,601,775 | **3,602,633** |
| **All four** | 5,897 | **5,917** | 3,575,535 | **3,580,689** |

- **No losses, texel by texel.** There are +20 −0 all four and no per-map loss. No LP-consistent Height texel is lost.
- **The gutter still follows the ring.** Given Painter's ring, the clamped flood still matches all 3,679,663 gutter texels.

**Probes and Tier 0, texel by texel against main:**

| Set | Main | 294 | Chains changed |
|---|---|---|---|
| Ramps (5), `tie-512` | all exact | the same | 0 |
| `atlas-512` / `-1024` / `-2048` / `-1024-moved` | 3,038 / 3,036 / 3,037 / 3,007 | the same | 0 / 0 / 0 / 1 (a miss either way) |
| Sweeps centred / offcentre / box320 | 7,663 / 7,666 / 7,591 | the same | 0 |
| `concave-fold` / `-shape` / `-fine` | 7,759 / 15,487 / 12,236 | the same | 0 |
| `sphere-256` / `bevelled-cube-256` | 1,980 / 1,998 | the same | 0 |
| Tier 0 `export-padding` / `-sphere` / `-bevelled-cube` (exact) | 1,387 / 1,980 / 1,998 | the same, Height-consistent unchanged | — |

### 5. What is left on the Wand

**The ring:** 417 all-four misses (from 437), seeding 98,974 gutter misses (from 104,128).

| Class | Ring texels | Note |
|---|---|---|
| Height operand | 294 | +1: (576, 1618), formerly multi-facet, is now BRM-exact |
| Multi-facet | 112 | — |
| Curved multi-triangle | 3 | (81, 277), (589, 1395), and (267, 1989) (formerly `mixed-gates`) |
| `mixed-gates` | 3 | (88, 610), (392, 848), (738, 1456): no gate assignment and no subset of the pool fits |
| Near-tie (decision 291's list) | 3 | (413, 704) and (582, 1610) fit with one far tap fewer; (587, 1848) fits no subset |
| `reach-bracket` | 1 | (79, 463), formerly multi-facet |
| Seam edge 1.5 to 2 texels away | 1 | (567, 1934): no subset fits |

So of the 25 targets, 17 are exact; the 11 left are listed above.

**The window-side texel.** (633, 1570) is exact under main and under 294, and it seeds 2 gutter texels.
- **Why it is refused.** Its one seam edge has f_u − ½ = 632.0000737, which is 7.37·10⁻⁵ from a window boundary. That is inside decision 291's ε = 10⁻⁴, and the other side changes its chain. So decision 291 (b) refuses it.
- **Painter's side here** is the float64 floor.
- **The offset** is 3.3 times decision 291's largest observed flip offset (2.24·10⁻⁵).
- **A narrower ε**, such as 5·10⁻⁵, would admit it. This pass does not narrow ε. Decision 291's flip offsets were measured on the probes, not on curved islands.

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes. `src/export/padding.cpp` and `tests/export/padding_reference.py` are unchanged.
2. **Identified, for the integration:**
   - **(a) Corner reach** (finding 1). A seam edge (E, J) of a triangle outside τ's planar face, whose nearest point to the ring texel's centre is an endpoint V of the edge, and which is not collinear (|sin| ≤ 10⁻³ in UV) with another seam edge of the island ending at V, reaches only within:
     - **1.0 texel** when another reaching seam edge ending at V is gated for this texel (decision 278 with decision 292's τ normal);
     - **1.15 texels** otherwise.

     Decision 285's segment reach (D = 1.78) is unchanged for every other edge.
     - Production refuses, as `NotYetSupported` naming decision 294, a ring texel where such an edge's reach lies in [0.974615, 1.020004) or [1.075926, 1.208074) and moving the cap across that interval changes its taps. This is the same form as decision 285's reach bracket.
     - It also refuses a texel where such an edge's |sin| lies in (10⁻⁶, 0.0305) and the exemption changes its taps.
     - On the Wand this refuses 2 texels, (738, 1456) and (339, 1862), both misses either way. The collinear bracket refuses none.
   - **(b) Own-far ties** (finding 3 (a)). Within decision 280's tie group, the key's first element is the float32 distance:
     - an own tap's decision 273 comparator distance;
     - a far tap's float32 |fold(q_E) − P|.

     The own-before-far order applies only at exactly equal float32 distances, and the `own-far-tie` flag stays for those.
   - **(c) Own near-ties** (finding 3 (b)). Adjacent own taps whose float64 distances lie within 10⁻⁴ relative are ordered by decision 273's comparator, then by `OWN_ORDER`.
   - **(d) Counts.** On the Wand: all four 5,917 ring texels and 3,580,689 gutter texels. On the 18 probes and the 3 Tier 0 goldens: unchanged.
3. **Rejected,** with the counts of findings 1 and 2:
   - per-tap gates by the tap's triangle;
   - per-far-chart gates by the nearest edge or by τ's own edge;
   - a single reach cap for every E ≠ τ edge (Wand +17 −3: it loses (752, 1454), which seeds 421,846 gutter texels);
   - an endpoint cap for every E ≠ τ edge (atlases −3 to −4, ramps −1 to −2, cube −4);
   - an endpoint cap for other facets without the collinear exemption (cube (4, 234));
   - a single endpoint cap, falsified by (634, 1418) against (175, 1101).
4. **Still open:**
   - **(a)** The 11 small residue texels of finding 5.
   - **(b)** Decision 292's Height-operand (294) and multi-facet (112) classes, unchanged in owner: decisions 283 and 289.
   - **(c)** Rule (a) is fitted on the Wand only. A probe with UV island corners bent 2° to 30°, folded far facets, edges at reaches across both brackets, and gated and open corner edges would confirm the two caps and the collinear exemption. It is not requested here; it is the owner's call whether to add it to decision 289's batch.
   - **(d)** The window-side refusal ε (finding 5): the owner's call.
5. **No new recording is requested.** Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- **The Wand's small residue drops from 25 texels to 11.** What remains is the 294 Height-operand texels (decision 283's float recording) and the 112 multi-facet texels (decision 289's probes), plus those 11.
- **Decision 292's open item (c) is mostly a reach effect.** The 15 Wand texels that only the both-closed assignment fits are all gained: the edge that assignment closes is a far corner edge that does not reach.
- **These need no retesting:**
  - per-tap and per-chart gate forms;
  - a single reach cap or a single endpoint cap for E ≠ τ edges;
  - an endpoint cap on edges in τ's own planar face.
