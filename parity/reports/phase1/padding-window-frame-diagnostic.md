# Seam-window frame padding diagnostic

Date: 2026-10-27. Status: the best policy is adopted as decision 364 (reference and native,
measured mode only); refusals 245/259 unchanged.
Task: phase1.25_pilot-wand, item 2.7. Follows decision 358 and
`padding-direct-plane-diagnostic.md`.

## Tool

`tools/parity/fit/padding_corpus.py` scores ring policies on all 29 kernel
probes. It predicts every ring texel's 24 components with
`tests/export/padding_reference.py` and compares them bit for bit with all four
recorded `infinite` exports. Every export, passthrough included, must keep the
covered source exactly.

Policies are a frame plus optional named text patches of the reference
(`PATCHES`):

- `--explain` classifies residuals: support, or weights off by how many bins.
- `--infer` and `decode_sparse` read Painter's actual taps from the one-hot
  class weights and the per-texel codes of the kernel maps.

Stdout carries counts only. Residual coordinates go only to an optional private
`--out` file. `tests/parity/test_padding_corpus.py` covers the offline parts
(six cases).

## Results

Counts are differing ring coordinates over all 29 kernel probes, 2026-10-27.
The 27 older probes plus `plane-control` and `tau-prism` give the baseline
3,248, the same as the earlier per-probe figures.

| Policy | Remaining | New vs baseline | Disposition |
| --- | ---: | ---: | --- |
| Baseline (reference at `c3679588`) | 3,248 | — | Reproduced |
| Generic J/tau (decision 358 diagnostic) | 1,477 | 1 | Reproduced |
| `jwin`: J = far triangle of tau's island's seam edge into the tap's island nearest the ring point | 1,289 | 1 | Unaccepted |
| `jwin+anychart`: a far window takes every covered texel, of any island | 1,189 | 1 | Unaccepted |
| `jwk+anychart+windowj`: `jwin`, or the far triangle of the window that puts the tap when no seam leads to the tap's island | 1,103 | 1 | Best; unaccepted |
| … `+snapcol`: a far column within 1e-4 of a window boundary snapped onto it | 1,039 | 22 | Rejected |
| `jnear+anychart`: J from the nearest seam edge of any island | 1,521 | 404 | Rejected |
| … `+uvwin`: far point from the UV similarity across the seam edge | worse on 4 of 5 probes | 541 on 5 probes | Rejected |

The one new coordinate of every J/tau-family policy is the same hinge-far
slender-triangle texel described in decision 358. The best policy's
per-probe residuals:

| Probe | Baseline | Best |
| --- | ---: | ---: |
| kernel-bevelled-cube-256 | 336 | 309 |
| hinge-vary | 961 | 202 |
| window-side | 132 | 132 |
| corner-reach | 137 | 105 |
| kernel-sphere-256 | 103 | 103 |
| kernel-atlas-512 / 1024 / 2048 / 1024-moved | 30 / 32 / 31 / 65 | 30 / 32 / 31 / 65 |
| tau-prism | 227 | 39 |
| tie-sweep-seams-box320 / centred / offcentre | 35 / 2 / 1 | 35 / 2 / 1 |
| hinge-far | 395 | 7 |
| hinge-single | 677 | 6 |
| plane-control | 80 | 0 |
| concave-fine | 4 | 4 |
| The other 13 probes | 0 | 0 |

## Findings

**Window islands.** On hinge-vary's gapped-seam copies, Painter takes far taps
from the hinged island K behind the thin seam triangle J. The reference's
window filter keeps only J's and tau's islands, which drops them.

**Far frame.** Rotating the far side rigidly from J's plane into tau's plane
holds with J taken from a seam, not from a face path. Taking J from the seam
nearest the ring point in any island regresses the atlases, corner and cube.
The window's own J helps only for taps outside every seam's island.

**Window boundaries.** On window-side, the far column at a boundary differs from
an integer by 1e-7 to 2e-5 in double arithmetic. Identical configurations land
on both sides, so neither snapping nor the double sign predicts Painter's
choice. This fits a GPU float32 attribute interpolation over a rasterized seam
strip (decisions 281 and 339), which the reference does not emulate. Still
open.

**Residual classes in the best policy.** These counts come from tap decoding on
the J/tau-family policies:

| Probe | Decoded residuals |
| --- | --- |
| Cube | 4-tap support changes and multi-bin weight shifts |
| Corner | Weights off by one or two bins, and reorders |
| Sphere | Pole-wedge far windows one texel off |
| Atlases | Two-tap weights off by 14 to 59 bins, and support changes |
| Hinge-vary | Copies still outside every decoded window (245 undecoded under `jwin`) |

No production policy, tolerance, exception, checkbox or refusal changed. Item
2.7 and refusals 245/259 remain open.

## Adoption (decision 364)

The best policy now lives in `tests/export/padding_reference.py` and `src/export/padding.cpp`.
Scored against the previous reference (`--policy git:7c4d804f --policy baseline`), it gives 3,248
-> 1,103 with 2,145 fixed and 1 new.

`--native` runs `uzp-export-tests ring` on every kernel probe's mesh, with the 24 kernel components
as values. On all 168,275 ring texels of the 29 probes, its taps and values equal the reference
bit for bit, and it misses Painter on the same 1,103 coordinates.

## Transparent uncovered islands (decision 365)

Decoding hinge-vary's remaining residuals showed far points that cross a seam strip covering no
texel centre. Carrying the point on across such an island gives 1,103 -> 984 with zero new
coordinates. The native ring again equals the reference on every ring texel. The variants that
walk on always, or whenever the window is empty, regress the corner, atlas and cube (decision
365).
