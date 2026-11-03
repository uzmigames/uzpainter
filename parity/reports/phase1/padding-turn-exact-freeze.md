# Padding turn-exact probe: frozen predictions

Date: 2026-11-02. Status: two authored requests, not yet recorded. There is no reference or
production change, and refusals 245/259 stay. Task: phase1.25_pilot-wand, item 2.7. Front A6
of decision 367, on Codex root's GO for preparation only (no capture). It follows the preflight
(`docs/analysis/padding-world-offset-residuals/01-residual-diagnosis.md` §9) and
`padding-world-offset-freeze.md`, whose structure it keeps.

## Why

Hypothesis H (§7) leaves the far turn's float32 order open between `pos32n` (double turn) and
`rod32n` / `inv32n` (float32 Rodrigues, forward or inverse). The preflight showed that exact
90-degree folds do not isolate the turn: every candidate pair is `mixed`. A capture can still
discriminate these controlled recipes, on 3 to 10 primary texels of the exact twins and 22 to 36
of the oblique twins. This probe is that controlled capture, frozen before any Painter data.

## The probe

Two requests under the current envelope's `requests/tier0/semantics/`, one project each:

| Twin | Request | Bytes SHA-256 | Canonical SHA-256 | Mesh SHA-256 |
| --- | --- | --- | --- | --- |
| `x90` | `export-padding-turn-exact-x90` | `c9a659f8…62e3fa` | `6fcc1758…8325d` | `b18c4f3e…575d72` |
| `oblique` | `export-padding-turn-exact-oblique` | `17905604…28be7d4` | `5e8c3d68…bd5d4` | `b5b079b7…c0c84cf` |

The meshes are `parity/fixtures/tier0-semantics/meshes/padding-turn-exact-{x90,oblique}.obj`
(494 faces each), written by the generator
(`python -m tools.parity.tier0_semantics write`; `check` passes). The generator is
`tools/parity/tier0_semantics/padding_turn_exact.py`. Each request is the eight-map kernel
recipe at 512 px, with RGB32F user channels and OpenEXR 32f `infinite` and `passthrough`
exports, each done twice, on the world-offset material `uzp_world_offset`.

- **Copies.** Both meshes hold the same 123 copies: the world-offset probe's three flat convex
  seam pairs (`f37v`, `f23v`, `f53v`) at their offsets, y90 / z90 turns, 2x / 3x scales, UV-slot
  duplicates and z lanes.
- **Twins.** The oblique twin is the world-offset shape. The x90 twin folds J's direction
  (a, b, c) to (0, c, c): the UVs, band depths and 3D edge lengths are the oblique shape's.
- **What differs between the two OBJs** (2,729 and 2,736 lines):
  - the comment line;
  - island B's positions: 246 `v` lines, one far-edge pair per copy;
  - the `vn` lines. The writer keeps one line per distinct normal: the x90 twin has 5 (signed
    coordinate axes) and the oblique twin 12, so the lines shift. The normal index differs on 172
    of the 494 `f` lines, and the normal itself on every island B triangle (246).
- **What is identical:** every `vt` line in order; the position count (744); every face's position
  and UV indices; and island A's 246 triangles and the two box anchors, positions and normals.
- **Layout.** One shelf layout and the world-offset box anchors (box x [-96, 204], y [-64, 64],
  z [-150, 150] cm) for both, so every x90 copy sits in its oblique twin's UV slot, under the
  same mesh box and normalisation, over the same kernel values.
- **Exact values.** Every position and UV is exact in float32; no two copies share a 3D point
  (`padding_world_offset.exact` and `overlaps`, enforced by `obj_bytes`).
- **The preflight now imports this geometry** (`twin`, `copies`, `layout`, `obj_bytes`); its
  own OBJs keep their comment, so its meshes keep their SHA-256 (`3cb37024…752e`,
  `f568f771…eeb`). Each probe OBJ differs from the preflight's OBJ of the same twin
  only in the comment line.

## Recipes

`tools/parity/fit/padding_turn_exact.py` runs each recipe's complete pipeline on both committed
OBJs (`padding_turn_exact_preflight.selection`): the reference at `a69b1434` (decision 368,
production; unchanged since) with `farhook`, then `fm<model>` for a candidate, then `own32mix`.
The recipe sets the kept taps, their order, the count, the undecided flags and the fractions.

| Recipe | Far distance | Own taps of tau's triangle |
| --- | --- | --- |
| `double` | production control | production |
| `pos32n+own32` | `pos32n`: float32 positions, double turn and norm | decision 358's `compare_distance` |
| `rod32n+own32` | `rod32n`: float32 Rodrigues, `distance32` | the same |
| `inv32n+own32` | `inv32n`: q turned tau -> J in float32, `distance32` | the same |

The stages are the preflight's (§9). No other recipe, order or rule enters.

## Pairing, mask and strata (declared before capture)

- **Pairing.** A texel's pair is the same absolute texel in the same copy slot of the shared
  layout. The predictions refuse unless the twins' copies agree slot for slot in role, offset,
  turn, scale and slot.
- **Primary mask: `tau_same`, 1,722 ring texels.** These are the preflight's declared universe.
  Each texel:
  - has the same complete selection (taps, order, count, decided) under every recipe in both
    twins, with a far tap;
  - has the same chosen taps and traced least-distance entries in both twins;
  - has only `turn` far taps (so do all 3,380 matched texels: 8,564 far taps, all `turn`);
  - has tau's corners bit-identical in both twins.
  The fixed-support recipes equal the complete pipeline on every primary chain (0 inconsistent).
- **Exclusions, listed in the compact file.**
  - `unmatched`: 64 of the 3,444 far texels per twin.
  - `not_clean`: 0.
  - `tau_other`: 1,658 matched texels with tau in island B, where q and the own taps move between
    twins. They are scored and reported apart, and decide nothing.
- **Strata** of the primary mask (`tau_other` in brackets):

| Stratum | Texels |
| --- | --- |
| Band < 8 / 8-63 / >= 64 cm | 252 / 546 / 924 (246 / 521 / 891) |
| offset / yz / dup | 966 / 168 / 84 (928 / 160 / 80) |
| turn y90 / z90 | 126 / 126 (125 / 121) |
| scale 2 / 3 | 126 / 126 (122 / 122) |
| Shape f23v / f37v / f53v | 574 / 574 / 574 (510 / 574 / 574) |
| Lane `centre` (x = 54, the control) / `other` | 42 / 1,680 (42 / 1,616) |

## Frozen predictions

Of 11,070 ring texels in the copy slots per twin, 775 have two (twin, recipe) predictions whose
output bits differ.

Primary texels whose predicted output bits differ per recipe pair, per twin, and the joint
patterns (A agree, D differ; x90 first). These equal the preflight's `tau_same` table.

| Pair | x90 | oblique | AD | DA | DD |
| --- | ---: | ---: | ---: | ---: | ---: |
| `pos32n` / `rod32n` | 7 | 26 | 22 | 3 | 4 |
| `pos32n` / `inv32n` | 3 | 22 | 22 | 3 | 0 |
| `rod32n` / `inv32n` | 10 | 36 | 31 | 5 | 5 |
| `pos32n` / `double` | 57 | 54 | 7 | 10 | 47 |
| `rod32n` / `double` | 56 | 56 | 10 | 10 | 46 |
| `inv32n` / `double` | 58 | 68 | 22 | 12 | 46 |

Primary texels whose predicted bits differ between twins, per recipe (`tau_other` in brackets):

| Recipe | All | < 8 / 8-63 / >= 64 | offset / yz / dup / y90 / z90 / s2 / s3 | Centre lane |
| --- | ---: | --- | --- | ---: |
| `double` | 0 (0) | 0 / 0 / 0 | 0 / 0 / 0 / 0 / 0 / 0 / 0 | 0 |
| `pos32n+own32` | 18 (84) | 1 / 4 / 13 | 9 / 4 / 1 / 2 / 0 / 1 / 1 | 1 |
| `rod32n+own32` | 21 (82) | 2 / 5 / 14 | 12 / 4 / 2 / 1 / 0 / 0 / 2 | 1 |
| `inv32n+own32` | 35 (86) | 4 / 11 / 20 | 16 / 9 / 2 / 4 / 2 / 1 / 1 | 1 |

On the primary mask the production control predicts the same bits in both twins everywhere: an
observed twin difference refutes `double`'s frozen bits there.

The compact predictions are `tools/parity/fit/padding_turn_exact_predictions.json` (LF bytes,
SHA-256 `e1e2617eec57297ed1950915fd4295dbbaaa827ad00796642483049b249382f1`). They hold
predicted values only, no recorded data:
- the full predictions' SHA-256:
  `2b6e2f25b629e9435dff9db0be2d95c2e98c580133b1bc242dca4e51be0b88e0`;
- the meshes, recipes, reference and pairing;
- per copy pair its slot, role and strata, and per twin and recipe the SHA-256 of its ring's
  output bits;
- the masks (`primary`, `tau_other`, `not_clean`, `unmatched` per twin), the frozen membership;
- the 775 discriminating texels with every twin's and recipe's fractions and bits.

The full predictions (not committed) are reproduced by `predictions()` from the committed OBJs
(about 100 s on CPU; two runs gave the same hashes).

Tool SHA-256 at freeze (LF bytes):

- `tools/parity/tier0_semantics/padding_turn_exact.py`: `93c32ce166aaeebc27a575565d8d4b2070df8ea094b3ddcf7f09b2a3812290f3`
- `tools/parity/tier0_semantics/padding_world_offset.py`: `eace51ab3013619b4ec124ccebb4b4488a04188c3794757219f2f9fda34ba800`
- `tools/parity/fit/padding_turn_exact.py`: `71824bdf4a2420b8043fb7eaf20c9fcbbdbb2403c5615b4a197ef6e288e471fa`
- `tools/parity/fit/padding_turn_exact_preflight.py`: `9f642dcf484769a26bc36d428c93a264db728712d0c82aea31eb886c09a738d2`
- `tools/parity/fit/padding_world_offset_residual.py`: `76af4358acc1b5f4c66bec3a7fd196ab7ae6f56bd5b6f3539919d2b06178ffea`
- `tools/parity/fit/padding_far32.py`: `7aef14fa1a7568a73cb52baee491504704eb4a92098cb95ef8b0af590204ec4f`
- `tools/parity/fit/padding_world_offset.py`: `4ea0a45135244a5afc96a476038e5b204e93cfc6fdc2e44cfc37c7084713facd`

## Reading the recording

The scorer is `python -m tools.parity.fit.padding_turn_exact_score`. It refuses, before any
score:
- unless the compact file's exact bytes hash to the freeze's (checked before the predictions
  are computed), the recomputed predictions hash to `2b6e2f25…88e0`, and the compact file equals
  them;
- unless each capture is of its own frozen request (`identity_problems`): the request's exact
  bytes, the admitted manifest equal to that request plus private records, the frozen mesh, and
  the record's golden id, input hashes and instruction-sequence hash;
- unless each capture validates as `padding_joint_bend_score` does: r1 and r2, one RGB32F template
  of the one texture set at 512 px, user0..7 at steps 45 to 48, the covered source kept, and the
  four `infinite` exports present and identical on the ring;
- unless every predicted texel is a ring texel of both recordings.

The two capture checks run on the exact manifest and record that `Probe` loads and scores, one
read of each (`load_probe`, through `Probe`'s `check` callback). They run after the generic
`validate_record` and before any export is read, so a record swapped after an earlier read
cannot escape them (tested).

It compares recorded bits with the frozen predicted bits directly, on every primary texel, and
reports per declared stratum and, apart, on `tau_other`:
1. **Per twin.** Per recipe, the texels whose recorded `infinite` value equals the prediction bit
   for bit, on each twin; and the joint pattern (M match, X miss; x90 first).
2. **Twin difference.** Whether a texel's recorded bits differ from its pair's, compared per
   recipe with that recipe's predicted twin difference (observed first: DD, DA, AD, AA).
3. **Outcomes, declared before capture.**
   - One recipe matches every primary texel on both twins (`fits_both`): it is the only one of
     these four controlled recipes the probe does not refute. It is no production rule.
   - Several match (`not_separated`), or none (`none_fits`).
   - `configuration` is `dependent` when some primary texel's recorded bits differ between
     twins: Painter's output then depends on the fold for the same UVs, kernel values and
     developed geometry. That is the only claim the probe may make about Painter.

No fraction is decoded for a verdict, and there is no threshold, no subset chosen after the
capture, no per-texel winner, no order search and no rule the corpus refuted. That both twins
keep the same support is model evidence from the frozen pipeline, never an observed Painter
internal. An axis-exact hit with an oblique miss discriminates the controlled recipes only: it
does not separate the turn from the turned point's rounding, the difference or the norm (§9).
The plan stops after this one paired capture and score.

A rule is accepted only with zero new misses on the corpus, the Wand maps and this probe, the
reference and native identical on every ring texel, a pinning test and two model reviews.

## Before capture

Root reviews the two exact requests and this freeze before any runtime. No external model saw
private data; none was consulted for this freeze.
