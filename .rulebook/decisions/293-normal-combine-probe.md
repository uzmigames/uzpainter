# 293. Decision 276 item 5's recording: one Tier 0 probe whose two texture sets differ only in a bound Normal mesh map, with Height and Normal-channel content alone, in pairs and all together, to pin the float32 form and the order of the gutter's mesh-map combination; designed, recording pending

**Status**: accepted (the request); recording pending
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.12_compositor-height-normal

## Context

Outside the islands, Painter's virtual Normal is the bound Normal mesh map F at the texel, combined with the padded mesh-free normal M of the texel's flood seed (decision 276 §2). The ring copies M from the nearest covered 8-neighbour (decision 287). With decision 285's clamped flood, the Wand's Normal outside the islands is within 1 code of this rule everywhere (decision 292 §4). Two parts are still open:

- **(b) the float32 form** (decision 276 item 4 (b)). The padded quantity could be the encoded normal fma(M, ½, ½), the unit vector M, or the separate height and channel normals. The gutter's combination could also take each of these forms.
  - The Wand's 16-bit codes pin the structure only to within 1 code: 4,966 of 6,334 ring texels are exact.
  - No float32 recording has a bound mesh map on islands.
- **(c) the order** (decision 276 item 4 (c)) when a set has both a mesh map and Normal-channel content. No recording has that.
  - Inside the islands the order is recorded (decision 079, F1): N = n(RNM(n(RNM(F, Hn)), C)). Here RNM is reoriented normal mapping, n is normalisation, Hn is the Sharp height normal and C is the channel normal.
  - Outside the islands, Painter could use F ⊕ M with M = n(RNM(n(RNM(flat, Hn)), C)), which decision 276 §2 implies. It could also use the in-island order on separately padded Hn and C, or another order.

Decision 276 item 5 names the recording that closes both: an islanded mesh, a bound 16-bit Normal mesh map, Height and Normal-channel content on the islands, and `Normal_OpenGL` as OpenEXR 32f with `infinite` padding, recorded r1 and r2. Decision 292 lists it as G1's last Normal blocker outside the islands.

The coordinator's brief was to keep it to one or two small Tier 0 requests, at most 512 px and 2 minutes of Painter. It had to use the existing machinery and controlled content that can be solved texel by texel.

**Binding a Normal mesh map needs no recorder change.** `TextureSet.set_mesh_map_resource` is already in the vocabulary (`parity/RECORDER.md` §2), with an optional `texture_set`; without one it binds every set. Its readback `get_mesh_map_resource` reports every set's binding. `export-bit-depth` and `export-presets-*` bind normal-b this way.

## Decision

### 1. The request: `tier0/semantics/export-padding-normal-combine`

One Legacy golden at 256 px in OpenGL, from `recording_requests.padding_normal_combine_probe`. Its fixtures come from `request_fixtures.combine_*`.

**The mesh (`normal-combine.obj`).** Two texture sets, `uzp_nc_mesh` and `uzp_nc_free`, with exactly the same UVs.
- Each set has four 48 × 48 texel islands, one centred in each 128 px quadrant: top-left texels at (40, 40), (168, 40), (40, 168) and (168, 168).
- Their borders lie on texel boundaries, so the UVs are dyadic and the coverage is crisp: 9,216 covered texels per set.
- Every island is 40 texels from the tile border. No texel of decision 287 §4 (neighbours only across the border) exists, and decision 290's border rows do not apply.
- Each island is its own 4.8 cm quad. There are no shared 3D edges, so the Height ring takes no seam taps.

**The content.** Island (qx, qy), counted from the top-left, gets the Height ramp when qx = 1 and the channel patch when qy = 1.

| Input | Fixture | What it holds |
|---|---|---|
| Normal mesh map, bound on `uzp_nc_mesh` only | `normal-combine-mesh-map.png`, 16-bit RGB | Per quadrant, its own smooth field of normals: the tilt starts at 15°, 20°, 25° or 10° and rises by 20° across x; the azimuth starts at 0°, 90°, 180° or 270° and rises by 60° down y. Every texel holds its own normal, and no two quadrants share one. |
| Height, one fill on each set | `normal-combine-height.png`, 16-bit grey | Signed −0.95 everywhere, except on the right-hand quadrants: there it is −0.95 + 0.0035 u v. Here u and v are the texels past 24 from the island's left and top borders (0 to 23), clamped beyond the island. |
| Normal channel, one fill above on each set | `normal-combine-channel.png`, 16-bit RGB | Tilted 20° to 35° down each quadrant, with the azimuth rising by 90° across it. It starts at 45°, or at 90° on the right-hand quadrants. |
| The channel fill's mask (black, with a bitmap fill effect) | `normal-combine-mask.png`, 16-bit grey | Exactly 1 on the bottom quadrants and 0 on the top ones. The channel's coverage is therefore 1 (C = decode of the bitmap) or 0 (C exactly flat, decision 079 F3). |

**The exports.** Every step is done twice in the session, as in every padding probe. r1 and r2 come from the recorder.
- `Normal_OpenGL`, Height and the Normal channel at OpenEXR 32f, `infinite`.
- `Normal_OpenGL` at PNG 16, `infinite`. This export is the Wand's format. It ties the float32 result to the 16-bit write rule the Wand is scored on.

**Why the covered normals are exactly computable.** The Sharp stencil reads the left and upper taps (`tools/parity/fit/normal.py`).
- On a ramp island, the Height has no gradient within the island's top and left 24 texels or within 2 texels outside them (checked by the test).
- So every Height tap that a covered stencil reads outside the island is a padded copy of one constant: −0.95 as stored. A lerp chain of equal taps returns that value.
- Every covered height normal, and so every covered M, is therefore independent of item 2.7's open Height ring (decisions 263 and 288). It follows from the evaluator's exact interior (decision 223) alone.
- On the right column (below the band) and the bottom row (right of it), the seeds' height normals tilt by up to 16°, in a direction that changes from seed to seed.

### 2. What each region separates

**The two sets share coverage, ring and flood.** Decision 287's ring and decision 197's flood with decision 285's clamped reads depend only on texels.
- `uzp_nc_free` therefore gives, at every texel, the padded encoded mesh-free normal that Painter wrote. It is a bit-exact copy of the seed's value (decisions 276 §2 and 287 §5), read straight from the recording.
- `uzp_nc_mesh` gives Painter's combination of F at the same texel with that same padded quantity.
- Each gutter texel of the mesh set is then one equation, with every operand known: F (authored), the free set's value at the same texel, and the seed's Hn and C (from the model and the authored bitmaps).

| Island (both sets) | `uzp_nc_mesh` | `uzp_nc_free` | Separates |
|---|---|---|---|
| top-left: no ramp, no patch | F alone (M flat) | nothing (control) | Whether the gutter applies one combination (F with the padded M) or two (F with Hn, then with C). They differ in float32 bits at 3,867 of 14,080 texels. Encoded and unit M coincide here. |
| top-right: ramp | F + H | H alone | (b): F with unit M against F with decoded fma(M, ½, ½). They differ in float32 bits at 2,058 of 14,080 texels. The orders coincide to below 1 code. |
| bottom-left: patch | F + C | C alone | (b) as above: 10,464 of 14,080 texels differ in float32 bits. The orders coincide to below 1 code. |
| bottom-right: ramp and patch | F + H + C | H + C | (c): F ⊕ n(RNM(Hn, C)) against n(RNM(n(RNM(F, Hn)), C)) differ by at least 1 code at 3,435 of 14,080 texels, and by up to 337 codes; against n(RNM(n(RNM(F, C)), Hn)) at 3,439 texels, by up to 695. Also (b), at 9,776 texels. |

- Together the regions cover F, H and C each alone, every pair, and all three. Absence is exact in every case:
  - F is absent because the free set binds no map.
  - H is absent where its gradient is zero.
  - C is absent where the mask's coverage is 0.
- **How the counts were made.** They are this design's predicted separations, from the CPU model on the authored inputs (`tools/parity/fit/normal.py`), not from oracle data. Each gutter or ring texel's seed was approximated by the nearest island texel, and each quadrant has 14,080 uncovered texels.
- **The covered texels** of `uzp_nc_mesh` recheck decision 079's in-island order on the same content.
- **The PNG 16 export** carries the same values through the 16-bit write rule (`unorm` in `tools/parity/fit/normal.py`). Once (b) and (c) are fitted, the Wand's 1,368 inexact ring texels and its inexact gutter can be rescored against it.

### 3. Recording

**Pending.** It goes into the next Painter session. The `wt/rec-batch` agent holds the queue and records it.

- **The command.** It runs in a Legacy session (no `OCIO`, no `PAINTER_ACE_CONFIG`), under the Assets3D Painter lock, as in `parity/RECORDER.md` §11.1 step 3:

  ```powershell
  python -m tools.parity.recorder record parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/tier0/semantics/export-padding-normal-combine.json
  ```

- **The record is void, and must be reported, if:**
  - the `get_mesh_map_resource` readback does not show the map on `uzp_nc_mesh` and none on `uzp_nc_free`;
  - the covered texels are not exactly 9,216 per set;
  - the exported Normal channel is not (0.5, 0.5, 1) on every covered texel of the two top islands;
  - or it is (0.5, 0.5, 1) on a covered texel of the two bottom islands.
- **Painter time.** One 256 px project with two sets and eight export calls: well under 2 minutes, on the scale of decision 278's 12 s recordings.
- **Admission.**
  1. Admit it with `python -m tools.parity.store record parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/tier0/semantics/export-padding-normal-combine.json --run <run>`.
  2. Add the name to `recording_requests.ADMITTED`.
  3. Delete the request, as in §11.3.

### 4. No production change

- Decision 245's `CheckIslandNormal`, decision 259's `CheckPadding` and R-090 are unchanged.
- No `src/`, semantics entry or capability changes.
- The recorder needed no change.
- **Changed:** the generator (`request_fixtures.py`, `recording_requests.py`), five authored fixtures, the request, a fixture test in `tests/parity/test_recording_requests.py`, and the runbook line in `parity/RECORDER.md`.

## Assumptions

- **The two sets pad identically**, because their UVs are identical. Decisions 287 and 197 depend only on texels. The only thing that differs between the sets is the 3D position, and that reaches only the Height ring kernel, which the constant bands take out of play.
- **The default projection maps the bitmaps texel for texel at 256 px**, as on every earlier 256 px fill (decision 079).
- **Decision 245's own request is not covered.** That request is an islanded mesh with no Height layer, a Normal fill and a mesh map, under `passthrough`. Here every set has a Height layer. `passthrough` is left out because its uncovered texels differ between r1 and r2 (decision 245).

## Alternatives Considered

- **One texture set with a flat-coded mesh map where F should be absent.** Rejected: no 16-bit code decodes to exactly 0 (65535 is odd), so "absent" would be a tiny tilt that changes float32 bits. A second set with no binding is exact, and it also gives the padded quantity straight from the recording.
- **A Normal-channel bitmap that is flat-coded outside the patches, with no mask.** Rejected for the same reason. A mask makes the coverage exactly 0.
- **A plain linear Height ramp across the island.** Rejected. Its left and top edge texels would read the Height ring, which item 2.7 has not yet made exact. The u v ramp with constant bands keeps every covered normal computable.
- **The islands, sphere or cube meshes.** Rejected. Their edges are not texel-aligned and their seams bring the Height ring in.
- **512 px or a second request.** Not needed. Each quadrant gives 14,080 equations, and the order differences reach hundreds of codes at 256 px.

## Consequences

- **Once recorded, the Wand's Normal outside the islands can be made bit-exact.** Decision 276 items 4 (b) and 4 (c) can be fitted texel by texel. Decision 292 item 4 (f) then closes: the Wand's Normal ring and gutter go from within 1 code to bit-exact.
- **What G1's Normal still needs after that** is the covered edge texels (decision 263's float32 Height ring), which item 2.7 owns.
