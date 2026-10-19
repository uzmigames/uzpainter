# 292. The Wand's residue under the full padding model, classified: 457 all-four ring misses, of which 293 wait on decision 283's float recording and 132 are multi-facet; no "other" is left. Decision 278's gate takes the ring texel's own triangle's normal, as 278 wrote it, not the seam edge's triangle's: Wand +21 / −1 (all four 5,877 → 5,897, gutter all four 3,571,662 → 3,575,535), no change on any of 18 probes

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.26_gate-g1

## Context

The Wand v1 is gate G1's pilot. On 2026-10-18 the owner ruled that its maps must be identical to Painter's everywhere ("tudo idêntico"), padding included. Exact `infinite` padding on UV islands is item 2.7 of `phase1.25_pilot-wand`.

**The full model** is decisions 267–291 combined. Decision 291 gives it as "stack S": decisions 282 (a)–(c), 285 (b)–(c) and 288 (d)–(e) on `tests/export/padding_reference.py` at main (decisions 278–281 integrated), with decision 285's clamped gutter flood. Its Wand counts are 5,877 all-four ring texels of 6,334. Decision 290 (tile border) does not apply: the Wand's islands span rows 53–1994 and columns 53–751.

**This pass:**
1. builds stack S plus decision 291's boundary flag as one model;
2. lists and classifies every all-four ring miss, with the gutter texels each one seeds;
3. fits the largest class that has no other owner, on the Wand's own data;
4. lists what else G1 needs for the five Wand maps to be identical.

**How it ran.**
- **The model.** Private scratch `E:/tmp/uzp-scratch/pad292/` (`cls292.py`, `rules292.py`, `gates.py`, `rulefit.py`, `probe_rule.py`), built on decision 291's `hring2.py` and `s282.py`, on main abbbde3's reference. Main's 86c9786, which landed during this pass, integrates decision 285 and decision 288 (d), which stack S already switches on. It reproduces decision 291's stack-S counts exactly: BaseColor 6,181, Roughness 6,289, Metallic 6,311, Height 6,014, all four 5,877, Height LP-consistent 6,316.
- **The boundary flag** is decision 291 (b): some seam edge's far point within 10⁻⁴ texel of a window boundary, and the two sides giving different chains.
- **The gutter** is decision 197's flood with clamped reads (decision 285), seeded by the covered and ring texels. A ring texel's weight is the number of gutter texels whose flood seed it is.
- **Scoring.**
  - On the Wand: BaseColor, Roughness and Metallic (BRM) must be exact. Height is scored exact and as decision 277's LP consistency, because the PNG 16 Height has several L16F preimages.
  - On the probes: all 24 channels bit-exact, per texel against decision 291's stack S.
- **Setting.** On the CPU with numpy and scipy, in about two hours. No Painter, no GPU, no `src/` change. The scripts stay in private scratch because they read oracle values. Clean room: black-box fits of our own recordings only.

## Findings

### 1. Every Wand miss under stack S belongs to a named class

**Gutter.** Given Painter's own ring values, the clamped flood matches Painter on all 3,679,663 gutter texels. So every gutter miss is inherited from a ring miss: 108,001 under stack S.

**The 457 all-four ring misses.** Classes are assigned in the order of the table; a texel goes to the first class it fits.

| Class | Owner | Ring texels | Gutter texels seeded (all of them miss) |
|---|---|---|---|
| **Height operand:** BRM exact, Height LP-consistent but not exact | decision 283's float recording | **293** | **65,517** |
| **Window side** (decision 291 (b)) | decision 291 (a) | **0** | 0 |
| **Multi-facet:** a chain tap in a face with no edge to τ's face | decision 284 | **132** | **35,456** |
| **Flagged `mixed-gates`** (1 also `reach-bracket`) | this decision | **20** | **1,250** |
| **Near-tie distance:** decision 291's 16 | decision 291 (c) | **9** | **5,706** |
| Curved same-island multi-triangle | decision 285 (b) | 2 | 72 |
| Seam edge 1.5 to 2 texels away | decision 285 (d) | 1 | 0 |
| **Other** | — | **0** | 0 |
| Total | | 457 | 108,001 |

What the table shows:
- **No unexplained class is left.** Decision 281's 96 "other" texels and decision 285's 70 are all exact or in a named class.
- **The window side does not touch the Wand's misses.** Two ring texels have a far point within 10⁻⁴ of a window boundary: (131, 830) is side-independent, and (633, 1570) is side-dependent and exact today on the float64 side. Decision 291 (b) refuses it. It seeds 2 gutter texels.
- **Of decision 291's 16 near-tie texels**, 6 fall in the Height-operand class (their BRM is exact) and 1 in the multi-facet class.
- **Map by map.** The multi-facet class is mostly BaseColor-only (83 of 132). The Height-operand class is Height only by definition.

### 2. Decision 278's gate takes τ's normal, not the seam edge triangle's

**The class.** In the 20 `mixed-gates` texels, a ring texel reaches two seam edges, one gated and one open.
- **16 have one fit.** τ's own seam edge (E = τ) is gated, concave and folded 15° to 28°. The open edge belongs to a neighbouring triangle E ≠ τ of the same curved island. The only gate assignment that reproduces all four maps closes both edges.
- **The other 4** match no gate assignment.
- **In 5 of the 16**, q lies behind the open edge's J, but that edge stays open because its own fold n_E · n_J is 0.992 to 0.999. Measured from τ instead, n_τ · n_J is 0.519 to 0.981, past the gate.
- **In the other 11**, q lies in front of J's plane for the open edge, so no dot product closes it.

**The cause.** Decision 278 states its gate as n_τ · n_J ≤ c₀ and n_J · (q − p) < 0, with τ the ring texel's triangle and q the ring point in τ's plane. The reference's `seam_gate` and `padding.cpp`'s `GateOf` instead pass E's normal, E being the triangle that owns the seam edge. The two agree whenever E = τ or E is coplanar with τ, and that holds on every probe. On the Wand's curved islands they differ.

**The rule.** The gate's dot product is n_τ · n_J, the float32 dot product of the ring texel's own triangle's normal and the far triangle's. The side test, the threshold 0.985 and the bracket (0.98498905, 0.98501915] are unchanged.

**Wand counts, ring of 6,334 and gutter of 3,679,663:**

| Map | Stack S ring | **τ-normal gate ring** | Stack S gutter | **τ-normal gate gutter** |
|---|---|---|---|---|
| BaseColor | 6,181 | **6,201** | 3,641,593 | **3,645,466** |
| Roughness | 6,289 | **6,299** | 3,668,573 | **3,668,608** |
| Metallic | 6,311 | **6,313** | 3,665,485 | **3,665,486** |
| Height (LP-consistent) | 6,014 (6,316) | **6,016 (6,318)** | 3,601,774 | **3,601,775** |
| **All four** | 5,877 | **5,897** | 3,571,662 | **3,575,535** |
| BRM + Height consistent | 6,170 | **6,190** | — | — |

- The rule gains 21 texels and loses 1, (412, 707), which joins the multi-facet class.
- The 21 come from three classes:
  - 5 of the 20 `mixed-gates` texels, those of the class description;
  - 14 of the 132 multi-facet texels;
  - 2 of the near-tie texels.

**The probes do not change.** Under the τ-normal gate all 18 probes are identical texel for texel to stack S:
- the five ramps and `tie-512`;
- `atlas-512`, `-1024`, `-2048` and `-1024-moved` (3,038, 3,036, 3,037, 3,007);
- the three sweeps (7,663, 7,666, 7,591);
- `concave-fold`, `-shape` and `-fine` (7,759, 15,487, 12,236);
- `sphere-256` (1,978) and `bevelled-cube-256` (1,998).

So the probes neither confirm nor contradict the change. Only the Wand separates the two normals.

**Other gate forms tried.** Each was scored on the 5,753 Wand ring texels that reach a seam edge folded past 0.985 by either normal. Some gate assignment of their edges is all-four exact on 5,361 of them.

| Gate (all with threshold 0.985 unless stated) | All four (of 5,753) |
|---|---|
| n_E · n_J, q in τ's plane (the reference, decision 278 as implemented) | 5,322 |
| **n_τ · n_J, q in τ's plane (decision 278 as written)** | **5,342** |
| n_E · n_J, q in E's plane | 5,318 |
| n_τ · n_J, q in E's plane | 5,331 (full ring: 5,886) |
| Concave edge (J's apex in front of E's plane), n_E · n_J or n_τ · n_J, no side test | 5,318 / 5,330 |
| min or max of the two dot products | 5,341 / 5,318 |
| n_τ · n_J at 0.97, 0.98, 0.99, 0.995 | 5,334 / 5,339 / 5,341 / 5,332 |
| n_τ · n_J with side "q behind J in τ's plane or in E's plane" | 5,346 |
| n_τ · n_J with side "q behind J, or J's apex in front of τ's plane" | 5,350 |
| A texel-level gate: every edge closed when τ's own edge is gated | Wand 5,892, but cube 1,998 → 1,954 and atlases −26 to −29 |
| A texel-level gate: every edge closed when any edge is gated | Wand 5,810 |
| A far window tap kept only when every window holding it is open | Wand 5,823 |

The two compound side tests gain 4 and 8 texels more. They were not run on the probes and have no basis in decision 278's data, so they are not adopted.

**Still open in this class:** 19 Wand ring texels are exact under some gate assignment that the τ-normal gate does not choose. For example, (391, 864) and (391, 867) need both edges closed, while (391, 865), between them, needs a far tap that both windows hold.

### 3. The Wand after this decision

**The ring:** 437 all-four misses (from 457), seeding 104,128 gutter misses (from 108,001).

| Class | Ring texels | Gutter texels seeded |
|---|---|---|
| Height operand | 293 | 65,517 |
| Multi-facet | 119 | 33,999 |
| Flagged `mixed-gates` (1 also `reach-bracket`) | 15 | 348 |
| Near-tie distance | 7 | 4,192 |
| Curved same-island multi-triangle | 2 | 72 |
| Seam edge 1.5 to 2 texels away | 1 | 0 |
| Window side, other | 0 | 0 |

**The heaviest single seeds:**
- Height operand: (459, 534) with 13,611 gutter texels, and (624, 1402) with 13,151;
- multi-facet: (574, 1404) with 5,374, (574, 1454) with 3,839 and (322, 1979) with 3,582.

### 4. The Normal gutter's 28 seed ties are the clamped flood

Decision 285 (f) asked whether its clamped flood also explains decision 287's 28 Wand Normal gutter misses. It does. Main's 86c9786, which integrated decision 285 while this pass ran, reports the same 28 → 0.

**The test.** Decision 287's Wand Normal model (`pad287/wand3.py`) was rerun with the flood's out-of-image reads clamped:
- the ring is a copy of the nearest covered 8-neighbour's mesh-free normal;
- the gutter is the flood seed's mesh-free normal under the mesh map at the texel;
- the coverage is snapped.

| Flood reads | Ring within 1 code | Gutter within 1 code | Gutter exact | Gutter max |
|---|---|---|---|---|
| Skipped (decision 287) | 6,334 / 6,334 | 3,679,635 / 3,679,663 | 3,435,905 | 592 |
| **Clamped (decision 285)** | 6,334 / 6,334 | **3,679,663 / 3,679,663** | 3,435,912 | **1** |

r1 and r2 give the same counts. So the Wand's Normal outside the islands is at the 16-bit noise floor everywhere: the covered round trip of the recovery is also within 1 code, with 506,003 of 508,307 exact. Decision 276's 4,370 ties, which were computed on Painter's own recovered ring, were not rescored.

### 5. What G1 needs for the five Wand maps to be identical

| Item | Status | Blocked on |
|---|---|---|
| **BaseColor, Roughness, Metallic: the ring** | 144 misses outside the Height-operand class: 119 multi-facet, 15 `mixed-gates`, 7 near-tie, 2 curved, 1 reach | Decision 284 open item (a): a far-side-hinge probe, the owner's call. The rest have no recording blocker. |
| **BaseColor, Roughness, Metallic: the gutter** | follows the ring exactly (clamped flood, 0 misses given Painter's ring) | the ring |
| **Height: the ring** | 293 Height-only texels, BRM-exact and LP-consistent | Decision 283's `phase1/tier1/wand-v1-float` recording, pending the Assets3D Painter lock. It is not in the private store as of this pass. |
| **Height: the gutter** | follows the ring | the ring |
| **Normal: the ring** | decision 287's copy of the nearest covered 8-neighbour, 6,334 of 6,334 within 1 code | the 16-bit form of the mesh-map combination, decision 276 item 4 (b): needs decision 276 item 5's recording (mesh map, Height and Normal content on islands, `Normal_OpenGL` OpenEXR 32f `infinite`) |
| **Normal: the gutter** | decision 276: the mesh map at the texel on the padded mesh-free normal. With decision 285's clamped reads, 3,679,663 of 3,679,663 within 1 code (finding 4) | the same 1-code form, decision 276 item 4 (b) |
| **Normal: the covered edge texels** | decision 263's stencil reads the float32 Height ring (decision 288 (a): without decision 206's 1 − (1 − m)) | The Height ring above, plus decision 283's recording to pin the Wand's float32 ring values |
| **The interior** (covered texels, all five maps) | being measured end to end in another branch (`wt/e2e-measure`) | that measurement |
| **Refusals to keep until each is exact** | decision 259 `CheckPadding`, decision 245 `CheckIslandNormal`, decision 291 (b) window side (1 Wand texel, exact today), decision 278's bracket | — |

## Decision

1. **Recorded, not implemented.**
   - Item 2.7 stays open, and EXC-007 stays withdrawn (decision 259).
   - No production code, semantics entry, capability, conformance case, exception or test changes. `src/export/padding.cpp` and `tests/export/padding_reference.py` are unchanged.
2. **Identified, for the integration:**
   - **(a) The gate's normal.** Decision 278's gate is evaluated with τ's normal: n_τ · n_J ≤ 0.985 and n_J · (q − p) < 0, with q the ring point in τ's plane. Its bracket (0.98498905, 0.98501915] applies to the same n_τ · n_J.
     - In the reference, `seam_gate(E.normal, …)` becomes `seam_gate(T.normal, …)`.
     - In `padding.cpp`, `GateOf(E, J, …)` takes τ's triangle for the normal.
     - The 278 text already reads this way; the implementations deviate from it.
   - **(b) The full model** for the integration is stack S (decision 291 finding 1) with (a), decision 291 (b)'s refusal, and decision 285's clamped flood.
     - On the Wand: all four 5,897 ring texels and 3,575,535 gutter texels.
     - On the probes: unchanged from stack S.
   - **(c) The Normal's gutter** uses the same clamped flood (finding 4, as integrated in 86c9786). This closes decision 287's 28 seed ties and decision 285's open item (f) for the Wand.
3. **Rejected,** with the counts of finding 2:
   - texel-level gates (τ's edge or any edge gated closes every edge);
   - keeping a far tap only when every window holding it is open;
   - a concave-edge test without the side test;
   - the side test with q in E's plane;
   - other thresholds on n_τ · n_J.
4. **Still open:**
   - **(a)** The 293 Height-operand texels: decision 283's recording.
   - **(b)** The 119 multi-facet texels: decision 284 (a) and (b).
   - **(c)** The 15 `mixed-gates` texels. Across the Wand, 19 ring texels are exact under a gate assignment that the τ-normal gate does not choose (finding 2).
   - **(d)** Decision 291's near-tie texels: 7 left.
   - **(e)** 2 curved texels and 1 reach texel (decision 285 (b), (d)).
   - **(f)** The Normal's 16-bit mesh-map combination (decision 276 item 4 (b)). The ring and gutter are within 1 code, with 4,966 of 6,334 ring texels exact. Decision 276 item 5's recording closes it.
5. **No new recording is requested.** Decision 283's request and decision 276 item 5's recording stand. Owner: `phase1.25_pilot-wand` item 2.7.

## Consequences

- **The Wand's padding residue is fully named.** Under the full model plus (a), 437 all-four ring misses remain:
  - 293 wait only on the float recording of decision 283;
  - 119 are decision 284's multi-facet distance;
  - 26 are small open classes.
- **Recording decision 283 is the largest single unblock for G1's padding.** Its 293 texels seed 65,517 of the 104,128 inherited gutter misses.
- **These need no retesting:**
  - the texel-level and all-windows gate forms;
  - an edge-concavity gate without the side test;
  - thresholds other than 0.985 on n_τ · n_J;
  - a search for an unexplained "other" class on the Wand.
