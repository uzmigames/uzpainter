# Turn-exact padding probe: score

The frozen scorer `python -m tools.parity.fit.padding_turn_exact_score` (commit `afc57b46`) was run once on 2026-11-03 against the two admitted captures:

| Twin | Request (bytes) | Record |
|---|---|---|
| x90 | `c9a659f8…e3fa` | `fc745152…976b` |
| oblique | `17905604…e7d4` | `81b54967…e342` |

Both were recorded in one Legacy session, where the envelope check passed. Each is admitted under its own golden id, with 66 private records and store verification passing. The scorer checked the compact predictions (`e1e2617e…82f1`) and the full predictions (`2b6e2f25…88e0`) before reading the store, and validated each capture on the snapshot its probe loaded. Each ring holds 11,070 texels. The full output is kept outside the repository: `tmp/scratch/turn-exact-score.log`, SHA-256 `bb0ee4a1707af95a5c12a9c6492991821f9d7f190995143aec8f5ddb6a2c912e`, counts only. This report gives its aggregates.

**Outcome: `none_fits`.** No frozen recipe matches both twins on every primary texel. **Configuration: `dependent`.** Painter's own output bits differ between the two twins on 31 of the 1,722 primary texels, and on 75 of the 1,658 `tau_other` texels.

**Primary mask** (`tau_same`, 1,722 texels; 64 unmatched texels per twin excluded). "Both" counts texels matching on both twins. "Twin difference" counts texels where the recipe predicts Painter's observed agreement or disagreement between the twins.

| Recipe | x90 | oblique | Both | Neither | Twin difference |
|---|---:|---:|---:|---:|---:|
| double (production) | 1,661 | 1,655 | 1,643 | 49 | 1,691 |
| pos32n + own32 | 1,716 | 1,705 | 1,700 | 1 | 1,701 |
| rod32n + own32 | 1,709 | 1,689 | 1,681 | 5 | 1,686 |
| inv32n + own32 | 1,719 | 1,713 | 1,711 | 1 | 1,712 |

- double predicts no twin difference at all. All 31 texels where Painter's twins differ count against it.
- The float32 recipes predict twin differences that Painter partly does not show:

  | Recipe | Painter differs, recipe agrees | Recipe differs, Painter agrees | Both differ |
  |---|---:|---:|---:|
  | pos32n + own32 | 17 | 4 | 14 |
  | rod32n + own32 | 23 | 13 | 8 |
  | inv32n + own32 | 3 | 7 | 28 |

- **Centre lane** (42 primary texels, the normalised-centre control): Painter's twins differ on 1. Each float32 recipe matches both twins on all 42; double matches both on 41.
- **`tau_other`** (1,658 texels, outside the primary mask): Painter's twins differ on 75. x90 / oblique matches: double 1,544 / 1,534, pos32n 1,604 / 1,606, rod32n 1,600 / 1,587, inv32n 1,646 / 1,595.
- The declared strata (bands, kinds, turns, scales, shapes) are all in the score log. Observed twin differences per stratum:
  - bands: <8, 4 of 252; 8-63, 12 of 546; ≥64, 15 of 924;
  - shapes: f23v, 22 of 574; f37v, 2 of 574; f53v, 7 of 574.

**What this shows and does not show.**
- It shows that Painter's padding output depends on the fold configuration (exact 90° versus oblique) at fixed UVs, slots and anchors.
- It shows that none of the four controlled recipes reproduces both captures.
- It does not identify Painter's arithmetic. Support equality between the twins is model evidence, not an observation of Painter's internals.
- It changes nothing in production, accepts no rule and adds no exception. Guards 245/259 are unchanged.

Per the plan, there is no follow-up experiment, subset or order search on this result.
