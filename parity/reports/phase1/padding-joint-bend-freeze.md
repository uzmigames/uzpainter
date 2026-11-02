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

- Every T is a ring texel (470 of 470).
- G is decisive for e2 at 388 of them. There e2 owns no other sample of T's 3 x 3, and owning G
  changes T's taps. The other 82 are the negative bends and interior deficits, kept as controls.

Copies whose predicted kernel values differ, per pair of hypotheses:

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

Phase flips at a fixed deficit (some phases take e2 and others do not):

- `snap256`: 10 families. They include the interior deficit -0.0015 at 1 degree, for both e1
  kinds: the snap loses a sample inside the strip. They also include the exterior deficits 0.001
  and 0.0017: the snap gains one outside.
- `quadsnap256`: 2 families, the exterior deficit 0.001 at 1 degree.
- A constant tolerance predicts no phase dependence.

The canonical predictions (all five hypotheses, every copy's taps and value bits) hash to SHA-256
`23de550c86d5ead42947f48c5db34d596dc3884899296d9e9e96fd4412488650`.

## Reading the recording

For each hypothesis, count the copies whose recorded `infinite` value at T equals the prediction
bit for bit. The phase families and the deficit sweep then bracket the rule:

- a phase-dependent switch at a fixed deficit means grid snapping, and which families flip names
  the grid and the snapped primitive;
- one deficit threshold that holds across bends and phases means a tolerance;
- a bend dependence means a joint rule.

A rule is accepted only with zero new misses on the 30 probes, the Wand maps and this probe.

The Wand's other new texel is unrelated to strips. Its rigid-turn bins lie 0.065 bins past a
rounding boundary, so it stays a precision question.
