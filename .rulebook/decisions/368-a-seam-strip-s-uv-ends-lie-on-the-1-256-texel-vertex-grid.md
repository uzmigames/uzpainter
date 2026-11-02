# 368. A seam strip's UV ends lie on the 1/256-texel vertex grid

**Status**: accepted
**Date**: 2026-11-02
**Related Tasks**: phase1.25_pilot-wand

## Context

The `island` diagnostic (own-island far taps turned from the J of every open window that holds
them) fixes 343 ring texels on the Wand kernel probe and adds 2 new ones. One of the 2 is not a
frame case: Painter's bins there need a second window, through a seam whose run our strip map
never discovers.

- The seam ends at a UV joint bent about 2.8 degrees.
- The only sample of the ring texel's 3 x 3 that could discover it lies in the wedge that
  decision 339's straight strip ends leave at the joint: 0.0017 texel past one strip's end,
  0.0105 texel before the next one's start.

Several end rules fix that texel with zero new misses on the 30 recorded probes (the Wand kernel
probe included). Each is a fitted range (an end tolerance, a sin cap on mitred joins) or an
untested grid choice. So the probe `export-padding-joint-bend` was authored to tell them apart.

- The geometry: 470 island corners whose seam edge leaves the corner bent 1 to 6 degrees (both
  signs). The ring texel's sample lies -0.004 to 0.025 texel before the strip's start.
- Phase pairs move the corner through one 1/256 step at a fixed deficit.
- Controls: copies turned, mirrored, scaled and translated.
- Five models were frozen before capture (`parity/reports/phase1/padding-joint-bend-freeze.md`,
  model part SHA-256 `5d8a35d2...bd57`).
- It was recorded on 12.2.0 (Legacy) with r1 and r2 and admitted (`8cd9fe11`). The template is
  RGB32F, the covered source is kept bit for bit, and all four `infinite` exports are identical.

Target texels matching Painter bit for bit, of 470 (`tools/parity/fit/padding_joint_bend_score.py`):

| Model | Matches |
| --- | ---: |
| Strip UV ends rounded to 1/256 texel | 470 |
| Strip quad corners rounded to 1/256 texel | 409 |
| Straight ends (decision 339) | 408 |
| Mitred joins | 394 |
| End tolerance 0.005 texel | 248 |

The rounded ends match every stratum, including the predicted loss of a sample inside the
straight strip and the gains outside it. They are decision 281's vertex grid, which coverage
already uses.

## Decision

In `tests/export/padding_reference.py` (`strip_covers`) and `src/export/padding.cpp`
(`StripCovers`), identically:

1. **Rounded ends.** Before the strip's coverage test, each of the seam edge's two UV ends is
   rounded in texel space to the nearest 1/256 texel, ties to even (`round` / `std::nearbyint`,
   as `covered_texels` and `CoveredTexels` round triangle vertices).
2. **Everything else unchanged.** The strip's width, top-left rule, draw order and runs, the
   reach, windows, frames, ordering and quantization all stay as they were.

No tolerance, exception or refusal lift. The `island` rule stays out: the Wand's other new texel
(a rigid-turn tie 0.065 bins past a rounding boundary) is still open.

## Consequences

Across the 31 recorded padding probes (joint-bend and the Wand kernel probe included), ring
texels differing go from 1,751 to 1,689. All 62 fixed texels are on joint-bend, and no probe has
a new one.

- The joint-bend ring keeps 213 other residuals. Agreement on its 470 targets is not
  whole-probe parity.
- The Wand kernel probe and the Wand maps are unchanged (no chain changes).
- The reference equals the diagnostic patch `snap256` texel for texel.
- `uzp-export-tests ring` equals the reference on every ring texel of the 31 probes (194,749 ring
  texels), taps and values. The executable came from the pytest fixture's build and its SHA-256
  prefix is `ec8bd9dc53edc907`. Its full hash was not kept: pytest's retention removed the build
  before it was recorded. This is an implementation checkpoint, not G1 acceptance; a gate run must
  bind the full executable and source hashes.
- The comparison's first run gave 30 probes exact. It then failed on the Wand kernel probe, whose
  mesh is an extensionless store blob that the native reader refuses: a harness failure, kept in
  `tmp/scratch/a2-native.log`. The Wand row (6,334 ring texels, exact) comes from a second run on
  an `.obj` copy of the pin-checked blob. `padding_corpus.native` now stages that copy itself and
  checks it against the pin.
- `test_seam_strip_ends_lie_on_the_vertex_grid` pins one gain (T takes B2's tap only through the
  rounded end) and one loss (a sample inside the straight strip falls outside the rounded one).

Reviews of the frozen diff (`cx/gpt-6-astra`, `cx/gpt-6.1-sol`): both ACCEPT, no bug found.
Item 2.7 and refusals 245/259 stay open.
