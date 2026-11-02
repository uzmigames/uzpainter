# Padding joint-bend probe: frozen predictions

Date: 2026-11-02. Status: an authored request, not yet recorded. There is no reference or
production change, and refusals 245/259 stay. Task: phase1.25_pilot-wand, item 2.7. Front A2 of
decision 367. It follows `padding-tie-side-mixed-chain-diagnostic.md`.

## Why

Cycle 3 of front A found the `island` rule (own-island far taps turned from the J of every open
window that holds them). On the Wand kernel probe it fixes 343 ring texels and adds 2 new ones.
Front A2 traced one of the 2 new texels to seam discovery, not to the frame.

- In Painter's bins, a second window joins: the seam that ends at a UV joint bent by about 2.8
  degrees (|sin| 0.049).
- The one sample of the ring texel's 3 x 3 that could discover that seam falls in the wedge that
  the strip map's straight ends leave at the joint. It lies 0.0017 texel past one strip's end and
  0.0105 texel before the other's start.

Scored on CPU over the 30 recorded probes, on top of `island` (corpus total 1,134 ring texels
differing):

| Strip-end variant | Total | Fixed | New |
| --- | ---: | ---: | ---: |
| Straight ends (current) | 1,134 | — | — |
| Strip UV ends snapped to 1/256 texel (`snap256`) | 1,133 | 1 | 0 |
| Strip quad corners snapped to 1/256 texel (`quadsnap256`) | 1,134 | 0 | 0 |
| End tolerance 0.002, 0.005 or 0.01 texel (`eps…`) | 1,133 | 1 | 0 |
| End tolerance 0.02 texel | 1,141 | 0 | 7 |
| Ends snapped to 1/16 texel | 1,146 | 1 | 13 |
| Ends snapped to 1/512 texel | 1,134 | 0 | 0 |
| Mitred joins, any angle | 1,195 | 1 | 62 (sphere) |
| Mitred joins at UV \|sin\| up to 0.05 or 0.1 | 1,133 | 1 | 0 |

On the Wand maps (CPU), `island` and `island+snap256` give the same result: union 102 -> 16, with
0 new. Across the 30 probes, the ring texels whose result depends on a joint-gap sample need it
unowned at every joint with \|sin\| of at least 0.131 (154 texels). Only the Wand texel needs it
owned, at \|sin\| 0.049.

A single positive texel cannot set the rule. Each variant that fixes it is either a fitted range
(tolerance, sin cap) or an untested grid choice (`snap256`). The probe below discriminates
between them.

## The probe

`export-padding-joint-bend` (request under the current envelope's `requests/tier0/semantics/`)
uses mesh `parity/fixtures/tier0-semantics/meshes/padding-joint-bend.obj` (SHA-256 `afd1a413...237d`,
generator `tools/parity/tier0_semantics/padding_joint_bend.py`). It is the eight-map kernel
recipe at 512 px, with RGB32F user channels and OpenEXR 32f `infinite` and `passthrough` exports,
each done twice.

The mesh holds 470 copies of decision 298's island corner (CornerCopy), with A's second facet
flat:

- A's seam edge e2 leaves the corner V bent by 1, 2, 2.8, 4 or 6 degrees, in both signs.
- Edge e1 is either no seam, or a gated seam whose B1 covers no texel.
- The ring texel T lies 0.22 or 0.3125 texel beside e1.
- The sample G, one row from T toward V, lies a swept deficit before e2's strip start: -0.004 to
  0.025 texel. G is the only route by which T can discover e2.
- Phase pairs move V's row through one 1/256 step (8 phases) at fixed deficits of -0.0015, 0.001
  and 0.0017, by translating the copy perpendicular to e2.
- Controls: copies turned 90 degrees, mirrored, scaled 2x in 3D, and translated.
- Copies that cannot keep every texel centre 1/64 texel from every UV border edge are left out.

## Frozen discrimination table

`python -m tools.parity.fit.padding_joint_bend` computes these from the committed OBJ: float32
UVs, decision 281's snapped ownership, and the eight kernel maps' predicted float32 values at T.

These are model predictions; the recording decides.

- Every T is a ring texel (470 of 470).
- At 388 copies, G is the only route to e2 in these models:
  - under straight ends, e2 wins no sample of T's 3 x 3;
  - under every one of the five models, e2 wins at most G (per-sample strip winners);
  - giving G alone to e2 changes T's predicted output bits.
- The other 82 copies are the negative bends and interior deficits, kept as controls.

Copies whose predicted output bits differ, per pair of models. This separates these five fixed
models only; `eps005` is one tolerance, not the whole family of constant tolerances.

| Pair | Copies |
| --- | ---: |
| straight / snap256 | 62 |
| straight / quadsnap256 | 19 |
| straight / eps005 | 272 |
| straight / miter | 52 |
| snap256 / quadsnap256 | 61 |
| snap256 / eps005 | 222 |
| snap256 / miter | 76 |
| quadsnap256 / eps005 | 259 |
| quadsnap256 / miter | 63 |
| eps005 / miter | 222 |

Predicted phase pairs at a fixed deficit: two phases of one family where the model's output
bits differ from straight ends at one phase and equal them at the other, while `eps005`'s
relation to straight ends is the same at both.

- `snap256`: 10 families. These are the deficits 0.001 and 0.0017 at 1 and 2.8 degrees, and
  -0.0015 at 1 degree, each for both e1 kinds.
- `quadsnap256`: 2 families, the deficit 0.001 at 1 degree.
- Predicted loss of G inside the strip: `snap256` at the deficit -0.0015 at 1 degree, for both
  e1 kinds. In one phase of the pair, straight ends give each copy's own G to e2 and the snap
  takes it away; in the other phase, the snap's bits equal straight ends. `quadsnap256` predicts
  no such loss.

The canonical model predictions (five models, every copy's taps and output bits) hash to
SHA-256 `5d8a35d285f65599e8a9bb591a619bca6f58dab3ffa63ef66b9eee4b9210bd57`
(`padding_joint_bend_score.model_part`). They are the same as at the first freeze (824d542f,
whose helper output, with its tap-based decisive flag, hashed to `23de550c...8650`). The helper's
full output, with the per-sample e2 winners, G found under every turn and the decisive test,
hashes to `4eab167402a94e0db46f9ad584dcae76166d2ae1509bc53ecf995cf513514c8e`.

## Reading the recording

For each model, count the copies whose recorded `infinite` value at T equals the prediction bit
for bit, per stratum (e1 kind, bend sign, deficit side, phase families, controls). That scores
these five fixed models; the following are diagnostic leads, not conclusions:

- a phase-dependent switch at a fixed deficit points to grid snapping;
- one deficit threshold that holds across bends and phases points to a tolerance;
- a dependence on the bend points to a joint rule.

A rule is accepted only with zero new misses on the 30 probes, the Wand maps and this probe.

The Wand's other new texel is unrelated to strips. Its rigid-turn bins lie 0.065 bins past a
rounding boundary, so it stays a precision question.
