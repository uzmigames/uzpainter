# Padding world-offset probe: frozen predictions

Date: 2026-11-02. Status: an authored request, not yet recorded. There is no reference or
production change, and refusals 245/259 stay. Task: phase1.25_pilot-wand, item 2.7. Front A3 of
decision 367. It follows `padding-joint-bend-freeze.md`.

## Why

The `island` rule (own-island far taps turned from the J of every open window that holds them)
fixes 343 ring texels of the Wand kernel probe. Front A2 traced one of its two new texels to
seam discovery (decision 368). The other, `kernel-wand-2048` (339, 1857), is a 4-tap chain. Its
taps 0 and 1 are far taps of tau's own island in triangle K, turned from the wrap seam's J (dot
0.978 with tau, K folded off J at 0.893). The level-0 raw value is 309.565, and Painter's bin is
309. Front A2 reported it 0.065 bins past the rounding boundary, about one float32 step of world
position at |x| = 0.147. Front A2 refuted, on this texel only:
- float32 storage of q and P;
- a seam-wide affine R, t, float32-rounded, with float32 FMA;
- developing P into the window walk's last triangle (+177 new);
- vertex-snapped barycentrics.

## Fixed models

`tools/parity/fit/padding_far32.py` holds the models. They measure every rigidly turned far
distance: decision 364's frame J, decision 366's open windows and, under `island`, the own-island
far taps. The patches `farhook`, `farisland` and `fm<model>` route those distances through them.
The turn's gate is the reference's own condition (`turns`: normals not parallel, dot at most
FOLD_GATE), so no model changes which taps turn. A tap on the turn's axis is still turned.

| Model | q and P | Turn and distance |
| --- | --- | --- |
| `double` | double barycentric (reference) | `plane_rotation`, double norm |
| `store32w` | the double points rounded to float32 | double |
| `pos32w` / `pos32n` | decision 273's float32 texel-centre interpolation of raw (`w`) or box-normalised (`n`) float32 corners | double turn through the same space's corners |
| `rod32w` / `rod32n` | as `pos32` | `plane_rotation`'s Rodrigues turn and decision 273's distance, every float32 operation rounded |
| `inv32w` / `inv32n` | as `pos32` | q turned from tau's plane onto J's in float32, then measured to P |

None is an affine (R, t) form. Normalised distances are converted back to world units in double.

The numeric contract:

- **Normals.** For every model, the normals are the reference's float32 face normals of the raw
  float32 corners (decision 278's `face_normal`), the same in both spaces.
- **Rodrigues models.** They renormalise the normals with `_unit32` (GPU square root). The axis
  is m x n over its GPU-square-root length. The line's point is Cramer's rule through corner 0 of
  J and of tau in the model's space, with a float32 division for 1/det. Each product, sum and
  difference is rounded to float32, without FMA.
- **Distance.** Decision 273's `distance32` is the FMA squared length and the GPU square root.
- **Positions.** `position32` uses the GPU reciprocal of the split UV determinant, then
  fma(l2, P2, fma(l0, P0, l1 P1)).
- **Normalisation.** Decision 273's `box_normalised` of the mesh box: r = 1/150 in float32 and
  c = (54, 0, 0).
- **Gate.** The gate is decided in double for every model. A float32 gate error is therefore not
  modelled. The probe keeps every hinge's dot 0.003 from FOLD_GATE: the folds are 0.6
  to 0.923, the bends 0.862, 0.969 and 0.988.
- **Exact inputs only.** Only the corners are exact. The interpolated q and P are not on the
  grid, which is why `store32w` differs from `double`.

## Existing data (31 probes, CPU)

`python -m tools.parity.fit.padding_corpus` was run on the 30 kernel probes and
`kernel-wand-2048`, with policy `baseline+island+farhook+farisland[+fm<model>]`, after the gate fix.
Ring texels differ from Painter on 1,689 under production and 1,346 under `island`. The hook with
`double` gives 1,346 with 0 changed, so it is a no-op.

| Model | Total | Fixed | New | New outside the Wand probe | Wand texel (339, 1857) |
| --- | ---: | ---: | ---: | --- | --- |
| `store32w` | 1,364 | 25 | 43 | atlas-1024-moved 1, cube 2 | miss |
| `pos32w` | 1,369 | 48 | 71 | hinge-far 1, hinge-vary 1, atlas-1024-moved 5, cube 3 | match |
| `pos32n` | 1,305 | 75 | 34 | hinge-far 1, hinge-vary 1 | match |
| `rod32w` | 1,420 | 58 | 132 | 25 on 8 probes | match |
| `rod32n` | 1,370 | 65 | 89 | 19 on 7 probes | miss |
| `inv32w` | 1,420 | 55 | 129 | 31 on 9 probes | match |
| `inv32n` | 1,369 | 79 | 102 | 35 on 9 probes | match |

Every model adds new misses, so none is a candidate and none is frozen as one.

- `pos32n` nets 40 on the Wand probe (72 fixed, 32 new). Normalised float32 positions move the
  Wand's bins the right way more often than not, but no fixed form here accounts for them.
- Five models reach Painter's bin at (339, 1857), so that texel alone does not discriminate.

## The probe

`export-padding-world-offset` sits under the current envelope's `requests/tier0/semantics/`
(SHA-256 `4e2c2646...3c3f`). Its mesh is
`parity/fixtures/tier0-semantics/meshes/padding-world-offset.obj` (SHA-256 `2c8eb824...b429`,
1,728 positions, 1,232 faces). The generator is
`tools/parity/tier0_semantics/padding_world_offset.py`. The probe is the eight-map kernel recipe
at 512 px, with RGB32F user channels and OpenEXR 32f `infinite` and `passthrough` exports, each
done twice.

- **Copies.** There are 246 copies of 6 seam pairs at 1/32 cm per texel.
  - Island A is 12 x 12 UV texels. In 3D it is stretched 17/16 across the seam and sheared 1/8
    along it, so that no two own taps tie in 3D.
  - Island B is folded convexly about the seam along a Pythagorean direction: (4, 3, 5),
    (12, 5, 13), (3, 4, 5) or (15, 8, 17). A concave seam would be closed by decision 278's
    gate, and its ring texels would take no far tap.
  - Three B are flat.
  - Three B are bent: a band J 1.0625 to 1.625 texel deep, then a band K along a second
    Pythagorean direction. Two of those bends pass decision 282's gate and one (dot 0.988) stays
    below it. So some far taps lie in K, off J's plane, as at the Wand texel.
  - B's UV island is stretched along the seam by 0.25 to 0.75 texel over 12, so that the far
    point's phase drifts along the seam.
- **Exact values.** Every UV is a multiple of 2^-8 texel and every position a multiple of
  2^-16 cm below 256 cm, so the OBJ's float32 values are the authored ones. A translated copy has
  a bit-identical shape.
- **Offsets.**
  - x: 0, 1, 2, 3, 8, 16, 24, 40, 54, 64, 80, 100, 120, 128, 140, 160, 180, 200, -1, -10, -30,
    -60 and -90 cm.
  - y: +-40 cm.
  - z: +-100 cm.
- **Controls.** Copies turned 90 degrees about y and about z, scaled 2 and 3 times in 3D, and
  duplicated in another UV slot. Each set is at x 0, 64 and 128 cm (the duplicates at 64 and 128
  only). Every copy has an explicit role: `base` (x 0), `offset`, `yz`, `turn`, `scale` or `dup`.
- **Mesh box.** Two anchors fix the box at x [-96, 204], y [-64, 64], z [-150, 150] cm.
  Decision 273's scale r = 1/150 and centre (54, 0, 0) are not powers of two, so raw and
  normalised float32 positions round differently.
- **No shared geometry.** Shapes at one offset are 0.5 cm apart in z, and each control kind has
  its own z lane, 4 to 43 cm below. No two copies' 3D boxes meet and no vertex is shared
  (`overlaps`, which the generator enforces).
- **Topology.** As the reference reads the OBJ (vertices welded by float32 value), every copy of
  a shape has the same counts: 2 islands, 2 seam edges, and 4 or 6 triangles with 2 or 3 planar
  faces. Islands, faces or vertices shared between copies: 0
  (`fit.padding_world_offset.topology`).

The kernel bitmaps are periodic in the tile (period 3 and a 17 x 13 tile), not in the copy's
slot. Translated copies with equal chains therefore have different output values, so
translation invariance is compared on the chain: the taps relative to the slot, their order, and
the fractions' bits (`signature`).

## Frozen discrimination table

`python -m tools.parity.fit.padding_world_offset` computes it from the committed OBJ, with float32
UVs, decision 281's snapped ownership and the reference at `a69b1434` (decision 368, production)
plus `farhook` and the model's `fm` patch.

- There are 22,140 ring texels; 6,888 hold a far tap under `double`.
  These far texels split into disjoint sets:
  - undecided by the reference: 574;
  - decided, with taps or tap order that differ between models: 0;
  - the scored set: 6,314.
- **Scored set (predeclared, `stable`).** These ring texels hold a far tap, are decided, and have
  the same taps in the same order under all eight models. On them the models differ only in the
  far chain's fractions. Its membership, per copy, is frozen in the compact predictions (`scored`).
- Of the 826 ring texels where two models differ, the ones outside
  the scored set are all undecided far texels (1 to 41 per pair). They are reported only.

Scored-set ring texels whose predicted output bits (24 float32 components) differ, per model
pair. Two breakdowns are given:

- by offset band: below 8 cm, 8 to 63 cm, 64 cm and above;
- by role: offset / yz / dup / y90 / z90 / scale 2 / scale 3.

Every pair of the eight fixed models differs, the closest by 113 texels
(`pos32n|rod32n`). This separates these fixed models only.

| Pair | Scored | < 8 | 8-63 | >= 64 | By role |
| --- | ---: | ---: | ---: | ---: | --- |
| `double` / `inv32n` | 382 | 53 | 115 | 214 | 228 / 67 / 8 / 32 / 16 / 14 / 17 |
| `double` / `inv32w` | 281 | 2 | 41 | 238 | 184 / 39 / 12 / 20 / 13 / 8 / 5 |
| `double` / `pos32n` | 371 | 53 | 104 | 214 | 225 / 68 / 7 / 29 / 17 / 15 / 10 |
| `double` / `pos32w` | 220 | 3 | 35 | 182 | 128 / 40 / 10 / 23 / 9 / 5 / 5 |
| `double` / `rod32n` | 381 | 60 | 105 | 216 | 226 / 66 / 9 / 33 / 19 / 13 / 15 |
| `double` / `rod32w` | 289 | 1 | 42 | 246 | 180 / 40 / 20 / 25 / 11 / 5 / 8 |
| `double` / `store32w` | 133 | 3 | 9 | 121 | 78 / 18 / 11 / 10 / 8 / 5 / 3 |
| `inv32w` / `inv32n` | 478 | 51 | 116 | 311 | 304 / 73 / 14 / 36 / 15 / 18 / 18 |
| `pos32n` / `inv32n` | 168 | 28 | 49 | 91 | 110 / 23 / 5 / 11 / 1 / 9 / 9 |
| `pos32n` / `inv32w` | 450 | 53 | 109 | 288 | 284 / 72 / 13 / 37 / 16 / 17 / 11 |
| `pos32n` / `rod32n` | 113 | 7 | 35 | 71 | 67 / 17 / 4 / 6 / 6 / 2 / 11 |
| `pos32n` / `rod32w` | 465 | 54 | 108 | 303 | 293 / 69 / 21 / 36 / 16 / 16 / 14 |
| `pos32w` / `inv32n` | 420 | 52 | 108 | 260 | 255 / 72 / 12 / 35 / 13 / 15 / 18 |
| `pos32w` / `inv32w` | 134 | 1 | 16 | 117 | 107 / 3 / 6 / 9 / 4 / 3 / 2 |
| `pos32w` / `pos32n` | 405 | 54 | 103 | 248 | 248 / 71 / 11 / 34 / 14 / 16 / 11 |
| `pos32w` / `rod32n` | 411 | 59 | 96 | 256 | 251 / 67 / 15 / 38 / 14 / 14 / 12 |
| `pos32w` / `rod32w` | 125 | 2 | 15 | 108 | 94 / 2 / 14 / 6 / 2 / 4 / 3 |
| `rod32n` / `inv32n` | 189 | 31 | 57 | 101 | 115 / 34 / 5 / 15 / 5 / 9 / 6 |
| `rod32n` / `inv32w` | 466 | 58 | 104 | 304 | 299 / 66 / 17 / 41 / 16 / 15 / 12 |
| `rod32w` / `inv32n` | 487 | 52 | 117 | 318 | 309 / 70 / 22 / 37 / 15 / 15 / 19 |
| `rod32w` / `inv32w` | 197 | 1 | 13 | 183 | 145 / 3 / 18 / 15 / 6 / 5 / 5 |
| `rod32w` / `rod32n` | 474 | 59 | 103 | 312 | 301 / 65 / 25 / 40 / 16 / 14 / 13 |
| `store32w` / `inv32n` | 435 | 54 | 110 | 271 | 266 / 71 / 15 / 34 / 12 / 17 / 20 |
| `store32w` / `inv32w` | 277 | 3 | 40 | 234 | 185 / 39 / 11 / 20 / 9 / 7 / 6 |
| `store32w` / `pos32n` | 433 | 54 | 101 | 278 | 262 / 76 / 14 / 37 / 13 / 18 / 13 |
| `store32w` / `pos32w` | 198 | 2 | 32 | 164 | 117 / 38 / 7 / 19 / 7 / 4 / 6 |
| `store32w` / `rod32n` | 437 | 61 | 100 | 276 | 261 / 72 / 16 / 41 / 15 / 16 / 16 |
| `store32w` / `rod32w` | 301 | 4 | 39 | 258 | 197 / 38 / 21 / 21 / 9 / 8 / 7 |

Per shape, the fewest scored texels by which a pair differs on that shape alone (0: that
shape alone does not separate the pair; the six together separate every pair):

- `b23-53v`: 17 (pair `pos32n` / `rod32n`)
- `b28-37v`: 1 (pair `pos32w` / `rod32w`)
- `b37-23v`: 20 (pair `pos32n` / `rod32n`)
- `f23v`: 21 (pair `pos32n` / `rod32n`)
- `f37v`: 0 (pair `double` / `store32w`)
- `f53v`: 1 (pair `pos32w` / `rod32w`)

**Translation mask (predeclared, `translation_pairs`).** A pair is a translated copy's ring texel
and its shape's `base` copy's at the same relative texel. The copy is one of 168: offsets, y/z
offsets or UV-slot duplicates. A pair is kept when:

- both texels are in the scored set;
- both have the same relative taps in the same order.

On a kept pair, only a far distance can move the fractions: no own chain and no tap change is
involved. There are 4,164 pairs. These are the pairs whose fractions differ, per model:

| Model | Pairs with other fractions |
| --- | ---: |
| `double` | 0 |
| `inv32n` | 343 |
| `inv32w` | 229 |
| `pos32n` | 366 |
| `pos32w` | 174 |
| `rod32n` | 393 |
| `rod32w` | 235 |
| `store32w` | 103 |

All translated texels, outside the mask too (`translation_changed`):

- **Changes common to every model.** These are outside the mask:
  - 148 far and 846 own chains change taps or tap order.
    Decision 273's float32 comparators order candidates within EQUAL_SHARE (or adjacent own taps
    within OWN_BAND) by position, and the shear removes only the exact ties.
  - 200 own chains change fractions through decision 358's float32 own
    distances.
- **Double model.** With unchanged taps, it changes no far chain's fractions
  (0).
- **Float32 models.** They change the fractions of far chains whose taps are unchanged, as
  in the mask table above.

The compact predictions are `tools/parity/fit/padding_world_offset_predictions.json` (SHA-256 `a2d9b4730a8c69e204c9b7b104d9bddaac67b2961d0afa8187fe27112b938f42`). They hold:

- per copy and model, the SHA-256 of its ring's output bits;
- the 826 ring texels where two models differ, with each model's
  fractions and bits;
- the full predictions' SHA-256: `cc51a73f414cc060b1ae3c0e1cb10347da36403bbe8f0308d9b360d56961cd58`.

The full predictions (about 70 MB, not committed) are reproduced by `predictions()` from the
committed OBJ.

Tool SHA-256 at freeze (the committed LF bytes; the compact predictions too):

- `tools/parity/fit/padding_far32.py`: `7aef14fa1a7568a73cb52baee491504704eb4a92098cb95ef8b0af590204ec4f`
- `tools/parity/fit/padding_world_offset.py`: `4ea0a45135244a5afc96a476038e5b204e93cfc6fdc2e44cfc37c7084713facd`
- `tools/parity/tier0_semantics/padding_world_offset.py`: `eace51ab3013619b4ec124ccebb4b4488a04188c3794757219f2f9fda34ba800`

## Reading the recording

Validate the capture as `padding_joint_bend_score` does:

- RGB32F template;
- user0..7 at steps 45 to 48;
- covered source kept;
- the four `infinite` exports identical on the ring.

The scorer is `python -m tools.parity.fit.padding_world_offset_score`. It refuses unless:

- the recomputed predictions hash to the freeze's SHA-256, and the compact file's exact bytes
  hash to its own and equal them;
- the capture is of the frozen request (`identity_problems`), checked before any score:
  - the request's exact bytes hash to `4e2c2646...3c3f`;
  - the admitted manifest is that request plus private records (inputs, instruction sequence,
    settings and identity fields);
  - the mesh is `2c8eb824...b429`;
  - the record's golden id, input hashes and instruction-sequence hash are the request's;
- the capture validates as above;
- every predicted texel is a ring texel of the recording.

It reports matches separately for the scored set, the excluded set, the whole ring of the
copies, the discriminating texels (in all and split into scored and excluded ones) and the
mask's pairs. A pair counts when both of its texels match.

Scoring is limited to the scored set and to these eight fixed models. It compares recorded
output bits with the frozen predicted bits directly. No fraction is decoded for a verdict.

1. **Model match.** Per model, count the scored texels whose recorded `infinite` value equals the
   prediction bit for bit. Report this per role, band and shape, on the discriminating texels and
   on the translation mask.
   - A model is refuted where its predicted bits differ from the recording.
   - On the mask, `double` predicts the same fractions for every pair. A recorded mismatch there
     refutes `double`'s frozen fractions at those texels. It does not by itself show that any
     position-dependent arithmetic exists: a different, translation-invariant fraction sequence
     might reproduce both texels of a pair. Claims stay limited to discriminating the eight fixed
     models.
   - Agreement refutes only the frozen models that predict otherwise, not every possible float32
     arithmetic.
2. **Diagnostic only.** `padding_corpus.inverse_bins` may decode Painter's levels on the
   predicted taps. It returns the levels nearest the prediction among those whose forward chain
   reproduces all 24 recorded components bit for bit. Another reproducing set may exist, so
   decoded levels explain a miss and decide nothing.
3. **Outcomes, declared before capture.**
   - Exactly one model matches every scored texel: it becomes a candidate. It is not production
     until it passes the 31 probes with zero new misses (none of the eight does today).
   - Several match: the probe does not separate them.
   - None matches: the probe records evidence only, no model is kept, and the residual stays an
     open precision question.
   - Texels outside the scored set are reported but decide nothing.

A rule is accepted only with:

- zero new misses on the 31 probes, the Wand maps and this probe;
- the reference and native identical on every ring texel;
- a pinning test;
- two model reviews.

## Reviews before capture

The design was reviewed by `cx/gpt-6-astra` and `cx/gpt-6.1-sol` (maths and aggregates only).

| Round | Draft | `cx/gpt-6-astra` | `cx/gpt-6.1-sol` |
| --- | --- | --- | --- |
| 1 | First draft | NO-GO | NO-GO |
| 2 | Shear, scored set, numeric contract | NO-GO | NO-GO |
| 3 | Paired mask, frozen membership, direct bit verdicts | NO-GO | GO |
| 4 | Reading narrowed to discriminating the fixed models | GO | (GO at round 3) |

What each NO-GO asked for, and the change made:

- **Round 1.** Both models found the double translation null contaminated by the reference's
  float32 tie comparators. They also asked for a stable scored set, a stratified table, a
  narrower reading and a numeric contract. A is now sheared, the scored set is predeclared, the
  table is stratified, and the contract is written out above.
- **Round 2.** They asked for disjoint counts, an explicit copy/base mask, and verdicts without
  decoding. Those are now in the report.
- **Round 3.** `cx/gpt-6-astra` objected that a masked `double` mismatch was read as evidence of
  position-dependent arithmetic. The claim is now limited to discriminating the fixed models
  (Reading, item 1).

Before this, root (Codex) found four further issues, all fixed:

- the `pos32n` space mix;
- possible welds between controls placed at one offset: there are now lanes, `overlaps` and
  `topology`;
- output bits compared across slots whose bitmap phases differ: chains are now compared by
  `signature`;
- the base-copy selection, and the turn gate's early return: copies now have explicit roles, and
  the gate is `turns`.
