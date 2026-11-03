# H1 preflight: turn the far chart's corners, then interpolate

Date: 2026-11-03. Front A7b of decision 367, `phase1.25_pilot-wand` item 2.7, on Codex root's
GO for an H1-only authored preflight (H2 is out; A6 stays closed as `none_fits`). Authored
geometry, the two committed turn-exact OBJs, the committed kernel bitmaps and the frozen
reference only. There is no capture, no oracle store read, no score and no production change.
Refusals 245/259 stay. Counts only.

**Status.** Ran once on 2026-11-03 (§5). The complete fixed H1 is refuted by a post-hoc
aggregate argument (§5.2); nothing is accepted.

## 1. H1

For a far tap P (a texel centre of triangle K) of ring texel q (of tau), through each counted
window's J (decision 366):

1. Each of K's three box-normalised float32 corners is turned J -> tau by one fixed turn: the
   frozen `rod32n` Rodrigues sequence (`padding_far32._rodrigues32`) in the same frame (source J,
   target tau, the line's point through J's and tau's normalised corner 0).
2. P' = decision 273's `position32` of the tap's centre over K's float32 UVs and the turned
   corners (split UV determinant, as for every far tap).
3. The distance is `distance32(q, P')`, q by `position32` through tau's normalised corners,
   divided in double by the box scale r. Own taps of tau's triangle take decision 358's
   comparator (`own32mix`).
4. The turn's gate (`padding_far32.turns`), its fallback (the double `plane_rotation`), the least
   distance over open windows and everything downstream are the frozen pipeline's.

Recipe name: `dev32n+own32`. In exact arithmetic a rigid turn is affine and exact barycentrics sum
to 1, so turning the corners first gives decision 364's point. In float32 the turned corners and
the weights round (decision 273's weights need not sum to 1), so H1 can differ from `rod32n`.

## 2. Files

| File | Role |
| --- | --- |
| `tools/parity/fit/padding_develop32.py` | H1 (`far_distance`, `turned_corners`), `devhook`, `selection` |
| `tools/parity/fit/padding_develop_preflight.py` | the preflight (proof, selection, bits, twins, stop, reading) |
| `tests/parity/test_padding_develop_preflight.py` | authored tests |
| this file | design and result |

`devhook` is applied after the frozen `farhook`: it replaces farhook's import of
`padding_far32.far_distance` with `padding_develop32.far_distance` and sets FAR_MODEL to
`dev32n`; then `own32mix`. No existing helper, request, mesh or prediction changes; the test
pins the freeze's seven tool hashes (LF bytes), the compact predictions, both meshes and both
requests. The preflight itself consumes no request and validates none: the request pins belong
to the A6 freeze (`parity/reports/phase1/padding-turn-exact-freeze.md`).

## 3. What the preflight reports

- **Refusals first.** The committed compact predictions must hash to the freeze before the
  frozen recipes are recomputed (`padding_turn_exact.predictions()`); the recomputed predictions
  must hash to `2b6e2f25…88e0` and equal the compact file (`padding_turn_exact_score`'s checks).
- **Input receipt.** Before and after the CPU work, the tool hashes (exact bytes) every input it
  consumes: the code closure (every `tools/` module loaded once every patched module the workers
  build has been built), the frozen reference's text at `a69b1434`, both committed OBJs, the
  eight kernel bitmaps and the compact predictions. It refuses when one changed, and the output
  carries the receipt.
- **General affine identity.** A rigid turn is affine and exact barycentrics sum to 1, so in
  exact arithmetic turning K's corners and then combining them gives decision 364's turned
  point. This is the argument; authored tests pin it on an oblique rational turn, with a
  normalisation similarity, and on its inconclusive (irrational) case.
- **Exercised-branch check** (`proof`), separate from the identity. H1's complete selection on
  each twin records every turned branch it computes (frame and window turns, flip-window trials
  included), distinct by (texel, tap, J, tau, K), which are all the inputs of H1's turned
  distance. Each is checked in rationals: K's raw corners turned by decision 364's exact frame
  and combined by the tap's exact barycentrics, against `developed()`; and the same under the
  box normalisation as an exact similarity (c, r), against r² times `developed()`. The exact
  barycentrics are checked to sum to 1 and to reproduce the texel centre; they are separate
  from decision 273's float32 weights, which need not sum to 1. Its counts cover these branches
  only, on these two meshes. Status, with no epsilon:
  - `invalid` on any rational difference: the preflight and its conclusion are void, the line
    stops and the tool exits 1;
  - `uncertified` when a branch is inconclusive (a normal or the sine irrational) or none was
    checked: the reading says so and certifies nothing;
  - `branches_equal` otherwise.
- **Selection.** H1's complete pipeline on both committed OBJs against each frozen recipe:
  differing taps and order or count, differing decided status, H1's undecided texels, and
  texels whose H1 selection differs between twins. Not assumed unchanged; A5's selection is not
  reused as proof.
- **Masks, fixed.** The frozen primary mask (1,722) and its centre lane (42, copies at x = 54),
  plus every copy-slot ring texel (`slots`, descriptive). Differences are reported; no subset is
  selected.
- **Comparison.** Per frozen recipe: masked texels whose predicted output bits differ from H1's
  per twin, and the joint patterns (A agree, D differ; x90 first). Per recipe, H1 included: the
  masked texels whose predicted bits differ between twins.
- **Stop rule.** H1 is bit-indistinguishable from a frozen recipe when no primary texel differs
  on either twin: the line stops. An `invalid` proof stops it too.
- **Reading.** Zero predicted primary twin differences reject only this complete, fixed H1
  candidate against Painter's 31 observed (`parity/reports/phase1/padding-turn-exact-score.md`),
  not the double-development family. No A6 score is computed.

## 4. Assumptions

- The proof's ideal geometry is the authored float32 corners and UVs in rationals with decision
  364's exact frame, in world space and under the exact similarity of the box normalisation. The
  float32 normalisation's own rounding is not part of the ideal.
- The branch check covers the branches H1's own complete selection computes on the two
  committed OBJs, not every branch H1 could compute elsewhere.
- The stop rule is judged on the primary mask; the copy slots are reported for information.

## 5. Result

### 5.1 The preflight as run (no score)

One run, exit code 0:
`python -m tools.parity.fit.padding_develop_preflight --jobs 5 --out tmp/scratch/develop-preflight.json`.
The output JSON stays as written (SHA-256 `5ee8141a47a5c3e0bd9a10ef3d1f364786d0c9802776e3042fc5e0f8a3662900`).
It holds authored counts only: no Painter data, no oracle read, no score.

**Receipt.** Taken before and after the CPU work; nothing changed. SHA-256 of the receipt
(canonical JSON) `0391e1b8402335a054257755a202666416d52be177aed9e0ab8d1d168cd57726`.

| Inputs | Count | SHA-256 |
| --- | ---: | --- |
| Code closure (`tools/` modules loaded) | 47 | group `f2f34b06…850f8d` |
| `padding_develop32.py` (in the closure) | 1 | `7f5dacb9…6f9b06` |
| `padding_develop_preflight.py` (in the closure) | 1 | `8fc097e6…e5078` |
| Reference `a69b1434:tests/export/padding_reference.py` (text) | 1 | `5315c0bf…c20c16` |
| x90 OBJ | 1 | `b18c4f3e…575d72` |
| oblique OBJ | 1 | `b5b079b7…c0c84cf` |
| Kernel bitmaps | 8 | group `3020121d…04dd93` |
| Compact predictions | 1 | `e1e2617e…82f1` |

Group hashes are of the group's canonical JSON in the receipt. The recomputed frozen
predictions hash to `2b6e2f25…88e0`, the freeze's. H1's predictions hash to
`fc848ec80639074f84158bc74ab977fc13143a8d061c1992b7aa369dd34e3afb`.

**Exercised-branch check: `branches_equal`.** Per twin, 15,416 distinct branches (30,463
calls), every one equal in rationals; 6,027 of them on the primary mask. None differ and none
are inconclusive. This covers the branches H1's own selection computes on these two meshes only.

**Selection.** H1 keeps the same taps, order, count and decided status as each of the four
frozen recipes on the primary mask, the centre lane and all 11,070 copy-slot texels, on both
twins. H1 is never undecided. Its support differs between twins on 499 copy-slot texels, none of
them in the primary mask or the centre lane.

**Bits.** Primary texels (1,722) whose predicted bits differ from H1's (A agree, D differ; x90
first):

| Recipe | x90 | oblique | AD | DA | DD |
| --- | ---: | ---: | ---: | ---: | ---: |
| `double` | 60 | 59 | 3 | 4 | 56 |
| `pos32n+own32` | 31 | 32 | 9 | 8 | 23 |
| `rod32n+own32` | 24 | 32 | 14 | 6 | 18 |
| `inv32n+own32` | 30 | 40 | 22 | 12 | 18 |

On the centre lane (42), H1 differs from `double` on one oblique texel and from no float32
recipe.

**Predicted twin differences:**

| Recipe | Primary | Centre lane |
| --- | ---: | ---: |
| `dev32n+own32` (H1) | 7 | 1 |
| `double` | 0 | 0 |
| `pos32n+own32` | 18 | 1 |
| `rod32n+own32` | 21 | 1 |
| `inv32n+own32` | 35 | 1 |

The four frozen counts equal the A6 freeze's.

**Stop rule: `stop = false`.** This is only the pre-declared filter: the proof is not `invalid`
and H1 is bit-indistinguishable from no frozen recipe. It approves nothing. The tool's reading:
"H1 predicts 7 primary twin differences; no score taken".

### 5.2 Post-hoc aggregate rejection (added after the run)

This conclusion was not declared before the run. It was reasoned afterwards by Codex root and
confirmed by an independent maths review. It uses no oracle read and computes no score.

- **Same universe and metric.** Painter's 31 observed primary twin differences
  (`parity/reports/phase1/padding-turn-exact-score.md`) are counted on the same frozen
  1,722-texel primary mask (predictions `2b6e2f25…88e0`, compact `e1e2617e…82f1`). They use the
  same equality predicate on all 24 float32 components: the scorer's four repeated `infinite`
  exports are validated identical, and a match needs all four equal to the predicted bits.
- **The argument.** Let A be the 31 texels where Painter's twins differ and B the 7 where H1
  predicts they differ. Then |A \ B| >= 24. On each texel of A \ B, H1 predicts the same bits
  in both twins while Painter's differ, so at least one twin's prediction is wrong.
- **Conclusion.** At least 24 paired primary texels hold at least one output mismatch. The
  complete fixed H1 (`dev32n+own32`, in this pipeline) is refuted.
- **What stays unknown:** which texels these are, how far off they are, and the total number of
  mismatches. Nothing is said about the wider corner-development family.
- **The pre-declared reading was too weak.** It rejected H1 only at zero predicted twin
  differences. Passing the nonzero-count filter was necessary but insufficient for exactness. Any
  predicted count unequal to the observed 31 forces a mismatch; here 7 < 31 gives the lower
  bound of 24.

No code change, variant, search or capture proposal for unchanged H1 follows. Production,
refusals 245/259 and every frozen artefact stay unchanged.
