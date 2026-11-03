# World-offset padding probe: residual diagnosis

Date: 2026-11-02. Front A4 of decision 367, `phase1.25_pilot-wand` item 2.7. This is offline
analysis of the existing capture only. There is no new capture, no production change and no new
threshold, and refusals 245/259 stay. The freeze (`parity/reports/phase1/padding-world-offset-freeze.md`),
its models, its predictions and its score log are unchanged. Counts only: no coordinates and no
recorded values.

**Result.** No general rule closes the probe, and nothing is accepted.
- **What the data are compatible with.** Float32 arithmetic on box-normalised positions, which no
  fixed model reproduces in full.
- **Best weight diagnosis** (scored set, taps fixed): 6,231 of 6,314. It combines float32 own taps of
  tau in chains with a far tap and a float32 turn of q about the seam edge onto J. That fold changes
  the geometry wherever the seam triangle leaves tau's plane, and the corpus refutes it: 3,038 and
  3,209 misses against production's 2,189.
- **Best general combination on the corpus:** pos32n + own32mix, 2,189 → 1,503 (799 fixed, 113 new).
  inv32n + own32mix follows at 1,529 (821 fixed, 161 new). Neither has zero new misses, so neither is
  a candidate (§6).
- **The next general hypothesis and its discriminating probe** are in §7.

## 1. Binding

| Item | Value |
| --- | --- |
| Capture | run `20261103T000254759804Z-322b78d16b42`, manifest `be095ee7…d651` (admitted in `c62cfb7f`) |
| Frozen predictions | `cc51a73f414cc060b1ae3c0e1cb10347da36403bbe8f0308d9b360d56961cd58` (recomputed by `padding_world_offset.predictions()`) |
| Compact predictions | `a2d9b4730a8c69e204c9b7b104d9bddaac67b2961d0afa8187fe27112b938f42` |
| Frozen score log | `tmp/scratch/world-offset-score.log`, `b4160548a4f6687c2037d5038bdcb1ca5e113681bf98181bda8104c6b04d633a`, verdict `none_fits` |
| Reference | `a69b1434` (decision 368), the freeze's |
| Diagnostic | `tools/parity/fit/padding_world_offset_residual.py`, tests `tests/parity/test_padding_world_offset_residual.py` |

The diagnostic refuses before any analysis unless:
- the predictions and the compact file are the freeze's (`padding_world_offset_score.frozen_problems`);
- the capture is the frozen request's and validates (`validate_capture`, the four `infinite`
  exports identical);
- its trace of the frozen reference reproduces the fractions of all eight frozen models.

That trace check finds 0 differences on all 6,314 scored texels for all eight models.

## 2. The residual sets

| Set | Texels |
| --- | ---: |
| Scored (freeze's `stable`) | 6,314 |
| Discriminating (the models' bits differ) | 773 |
| Not discriminating | 5,541 |
| Missed by every model | 37 (32 not discriminating, 5 discriminating) |

Misses per model: pos32n 159, inv32n 168, rod32n 192, double 409, pos32w 446, store32w 459, inv32w
492, rod32w 503.

Overlaps (both, first only, second only):
- pos32n and inv32n: 80, 79, 88;
- pos32n and rod32n: 120, 39, 72;
- pos32n and double: 101, 58, 308.

**Bounded decode.** The 805 scored texels that some model misses are the 773 discriminating texels
plus the 32 shared misses outside them. Each was decoded on its fixed taps (`decode_all`):
- the window is the whole level range for 2-tap chains and ±3 bins around pos32n's levels otherwise;
- each has exactly one solution in that window, and none has zero.

That is local uniqueness of the bounded search, not global uniqueness.

**The 37 shared misses.**
- Taps: 36 are 4-tap chains and 1 is a 3-tap chain. All 37 hold two or more far taps
  (FFoF 16, FFoo 9, FFFo 9, others 3).
- Roles: offset 21, yz 13, scale 3. Bands: below 8 cm 6, 8 to 63 cm 21, 64 cm and above 10.
- The level that differs from double is level 0 on 26, level 1 on 5, level 2 on 3, levels 0 and 2
  on 3.
- Sensitivity: on the 37, a change of one tap's distance alone reproduces the decoded levels at
  these smallest tested steps (a 1-2-5 grid from 1e-8 to 5e-1; not a mathematical minimum):

  | Under | Far tap | Own tap |
  | --- | --- | --- |
  | double | 33, at 2e-5 to 5e-3 (12 need at least 1e-3) | 4 |
  | pos32n | 33, at 1e-5 to 5e-3 | 4 |

  This shows per-texel sensitivity only. It is no rule and justifies no correction.

## 3. Invariance of the representatives

A representative is the bounded search's one solution where a model misses, else the double levels,
which all eight models share there and which reproduce the recording. No uniqueness is searched on
those 5,509 texels. No key is unresolved (0), so every pair below has representatives.

Pairs are taken at the same relative texel as the shape's base copy, with the same relative taps
under double.

| Set | Pairs | Representatives differ | Double's levels differ |
| --- | ---: | ---: | ---: |
| Translation (the freeze's predeclared mask) | 4,164 | 384 | 0 |
| Exact 90° turns (exploratory) | 878 | 91 | 0 |
| Scales 2 and 3 (exploratory) | 887 | 73 | 0 |

- **Size of the differences.** On the translation mask, 353 of the 384 differ by one bin at level
  0 (+1 on 226, −1 on 127). 35 are at offsets below 8 cm.
- **What this does not prove.** Kernel phases differ between the slots, so these differences do
  not by themselves prove that Painter's arithmetic depends on position. A common level set
  outside the searched window is not ruled out. They motivate the hypotheses below.
- **Which models co-vary.** Pairs that a model's own levels flag, against the 384:

  | Model | Both flag | Model only | Representatives only |
  | --- | ---: | ---: | ---: |
  | inv32n | 260 | 83 | 124 |
  | pos32n | 232 | 134 | 152 |
  | rod32n | 240 | 153 | 144 |
  | pos32w | 65 | 109 | 319 |

  The box-normalised models track Painter's changes about four times better than the raw-world
  ones.

## 4. Hypotheses checked against history first

- **Not run again** (already refuted exactly):
  - `|fold32(q) − P_K|` with own taps through K: 52 fixed / 2,657 new
    (`padding-tie-side-mixed-chain-diagnostic.md`, cycle 2);
  - own taps of tau in float32 alone: 24 fixed / 3 new, same report.
- **Run here:** the own-tap form recombined with far models.
- **Not tested before and run here:**
  - normals from the normalised corners (root);
  - float32 shares (root);
  - P through J;
  - the model panel's seam-edge fold (`cx/gpt-6-astra` and `cx/gpt-6.1-sol` both ranked it first;
    their prompts carried maths and aggregates only).

## 5. Weight diagnosis on the scored set (taps and order fixed)

`candidates()` holds every texel's taps and order at the reference's. Its counts diagnose weights
only and are not a candidate's score. Columns: matches of 6,314; of the 37 shared misses; of the
773 discriminating texels; of the other 5,509.

| Configuration | Scored | Shared | Discr. | Rest | vs pos32n fixed / new |
| --- | ---: | ---: | ---: | ---: | --- |
| double | 5,905 | 0 | 396 | 5,509 | 58 / 308 |
| pos32n | 6,155 | 0 | 646 | 5,509 | — |
| inv32n | 6,146 | 0 | 637 | 5,509 | 79 / 88 |
| pos32n, float32 shares (division or GPU rcp) | 6,155 | 0 | 646 | 5,509 | 0 / 0 |
| double, float32 shares with GPU rcp | 5,904 | 0 | 395 | 5,509 | 59 / 310 |
| pos32n, normals of normalised corners | 6,155 | 0 | 646 | 5,509 | 0 / 0 |
| P through J (`jpos32n`) | 6,131 | 2 | 630 | 5,499 | 12 / 36 |
| fold32 of q via E into J (`fold32n`) | 6,153 | 3 | 652 | 5,498 | 79 / 81 |
| seam-edge Rodrigues (`edge32n`, both orders) | 6,177 | 3 | 666 | 5,508 | 79 / 57 |
| comparator-convention fold (`fold32nc`) | 6,177 | 3 | 666 | 5,508 | 79 / 57 |
| pos32n + own32 | 6,160 | 8 | 659 | 5,496 | 32 / 27 |
| inv32n + own32 | 6,190 | 15 | 674 | 5,505 | 108 / 73 |
| fold32n + own32 | 6,211 | 18 | 703 | 5,494 | 113 / 57 |
| edge32n + own32 | 6,231 | 18 | 714 | 5,503 | 113 / 37 |
| fold32nc + own32 | 6,231 | 18 | 714 | 5,503 | 113 / 37 |

`own32` measures, in a chain with a far tap, each own tap of tau's triangle as decision 358 measures
single-triangle own chains: `compare_distance`, box-normalised float32, in world units. Extending it
to every own tap of tau's island (`own32chart`) leaves fold32n + own32 at 6,211 and moves
edge32n + own32 from 6,231 to 6,229.

Readings (compatible with the tested partial recipes; Painter's own and far arithmetic is not
identified):
- Float32 shares and normalised normals change no scored texel. Under these fixed taps, the tested
  share and normal forms do not account for the residual.
- Of the 37 shared misses, `own32` fixes 8 with pos32n, 15 with inv32n and 18 with fold32n,
  edge32n and fold32nc. Alone, the own-tap form failed on the corpus (24 fixed / 3 new, history).
- With `own32`, the far forms that turn q onto J's plane in box-normalised float32 do best on this
  probe (6,190 to 6,231). Each form also loses texels that pos32n matches (27 to 73).

## 6. Full pipeline on the corpus

`--corpus` scores each candidate's full pipeline (taps, order and fractions) on the 31 semantics
probes (world-offset included) and the Wand kernel probe. Every knob of the candidate is included
(`fc<model>` far hook, `own32mix`). Base: production (`baseline`) and the freeze's corpus base
(`island` with `farhook` and `farisland`).

Ring texels differing from Painter, summed over the 32 probes (all 24 components against every
recorded `infinite` export). *Base* is the freeze's corpus base.

| Policy | Total | vs production, fixed / new | vs base, fixed / new |
| --- | ---: | --- | --- |
| production (`baseline`) | 2,189 | — | — |
| base (`island`, `farhook`, `farisland`) | 1,846 | 344 / 1 | — |
| base + pos32n + own32mix | 1,503 | 799 / 113 | 458 / 115 |
| base + inv32n + own32mix | 1,529 | 821 / 161 | 480 / 163 |
| base + fold32n + own32mix | 3,038 | 669 / 1,518 | 496 / 1,688 |
| base + edge32n + own32mix | 3,209 | 671 / 1,691 | 493 / 1,856 |

New misses against production, by probe:
- pos32n + own32mix: world-offset 71, Wand kernel 30, joint-bend 8, and one each on corner-reach,
  hinge-single, hinge-vary and window-side. By chain kind: 105 mixed, 8 far.
- inv32n + own32mix: world-offset 50, Wand kernel 63, joint-bend 8, the four atlases 26, concave-fine
  3, cube 4, hinge 6, window-side 1. By chain kind: 131 mixed, 30 far.
- fold32n + own32mix: hinge-single 484, hinge-far 351, hinge-vary 326, tau-prism 148, cube 97,
  Wand kernel 61, world-offset 40, joint-bend 8, and 3 others.
- edge32n + own32mix: hinge-single 484, hinge-far 392, hinge-vary 449, tau-prism 129, cube 93,
  Wand kernel 69, corner-reach 33, world-offset 32, joint-bend 8, and 2 others.

Fixed texels against production are mostly mixed chains: 655 of 799 for pos32n + own32mix, and
678 of 821 for inv32n + own32mix. No policy has zero new misses, so none is a candidate. Among the
far models, only the frozen ones are named as possible candidates, and none is accepted. The
fold family (fold32n, edge32n) is refuted on the full-pipeline corpus by these counts.

All 32 probes ran in one 11-minute CPU run (10 workers). Its aggregate log,
`tmp/scratch/a4-corpus.log`, holds no coordinates.

**The seam-edge folds are another geometry off the planar case.** They turn about E's seam edge,
which is the line where J's and tau's planes meet only when E lies in tau's planar face. On
hinge-far, 4,129 fold calls have E off tau's face (`fold32n:offplane`). `fold32n` alone (far-only, on the
freeze's `island` base) gives 359 ring misses there against the production baseline's 7, all
mixed chains. On world-offset, island A is planar, so the folds and
the frozen turns agree in exact arithmetic. The probe cannot tell a float32 fold from a float32
Rodrigues turn about the J∩tau line by geometry alone.

## 7. The next general hypothesis

**Hypothesis H.** One float32 recipe in box-normalised space measures every chain distance.
- **Own taps.** Every own tap of tau's triangle takes decision 358's `compare_distance`, in mixed
  chains too, not only in single-triangle own chains.
- **Far taps.** They take a float32 rigid turn about the line where J's and tau's planes meet,
  which keeps decision 364's geometry everywhere. Its operation order is not yet identified:
  between pos32n's double turn and rod32n/inv32n's float32 Rodrigues.

**Evidence, as counts only.**

| | pos32n + own32mix | inv32n + own32mix |
| --- | --- | --- |
| Corpus, against production | 2,189 → 1,503 | 2,189 → 1,529 |
| Scored set, taps fixed | 6,160 | 6,190 |

Neither has zero new misses. Their new misses sit mostly on world-offset, the Wand kernel probe and
joint-bend. The seam-edge folds score better on the planar probe, but the corpus refutes them as
geometry. The turn's float32 order and the position rounding both stay open, and this probe
cannot tell them apart: both move the same bins.

**A possible discriminating probe: `export-padding-turn-exact`.** This is design and preflight
only. There is no recording request and no capture.
- **Copies.** The world-offset copies at the same offsets and roles, with seams along a coordinate
  axis through vertex-grid points and convex 90-degree folds. Oblique twins (the world-offset
  shapes) sit in matching slots.
- **What axis-aligned folds do and do not give** (the independent A5 maths audit). cos = 0 and
  sin = 1 are exact. That does not isolate the turn:
  - the Rodrigues turn's Cramer anchor and the edge fold's anchor differ;
  - fl(a + fl(P − a)) can change even the component along the axis;
  - pos32n takes its norm in double, while rod32n and inv32n take `distance32`;
  - the inverse turn permutes components, which changes the FMA sum;
  - the nominal normals must be exact bits.
- **Preflight, a later step** (bounded design is GO; it is not started in this front). It would
  compare explicit named recipes stage by stage:
  - stages: the normal, axis and origin; the turned point; the difference; the norm; the fractions;
  - same matched support and order, same J, tau and K, same gates and least-distance branch;
  - same global box and normalisation, UV slots and intrinsic developed geometry;
  - own controls;
  - no extra grid of arithmetic orders.
  If the stages are not equivalent across the 90-degree and oblique sets, the report states mixed
  causes and does not call the result turn-isolated.
- **Reading, if it is ever captured.** An axis-exact hit with an oblique miss would discriminate
  between those controlled recipes only. It is no causal identification of Painter's arithmetic.
  Likewise, shared misses cannot be attributed to positions or own taps by elimination.
- **Capture is on hold** until the preflight shows discriminating predictions and invariant
  evidence. Then the probe needs its own frozen predictions, models and review before capture, as
  decision 367 requires.

Until then, no rule from this analysis goes further: no production change, no threshold, and
refusals 245/259 stay.

## 8. Limits

- Decoding is bounded and local. Representatives are a mix of bounded solutions and double levels.
- The turn and scale sets are exploratory, not predeclared.
- The weight diagnosis fixes taps and order. Only the full pipeline on the corpus can make a rule
  a candidate, with zero new misses, its own frozen discriminating probe and two reviews.
- Private data handling:
  - Two per-texel caches of one-shot scripts (`a4-miss.pkl` and `a4-all.pkl`, with decoded levels
    and recorded bits) were written to `tmp/scratch` in the repository, which `parity/CONTRACT.md`
    §6.4 forbids.
  - The coordinator found them and moved them unchanged to `%LOCALAPPDATA%\UzPainter\oracle-work`.
    Root verified their hashes and their absence from the repository.
  - The committed tool and its tests write no such file.
  - The model-panel prompts held aggregate maths only.
