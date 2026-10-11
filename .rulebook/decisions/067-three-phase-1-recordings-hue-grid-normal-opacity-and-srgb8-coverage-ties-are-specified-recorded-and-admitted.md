# 67. Three Phase 1 recordings (hue grid, normal-map opacities, sRGB8 coverage ties) are specified, recorded and admitted

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.11_compositor-blend-gaps, phase1.10_compositor-float32-residual, phase0.9_render-reference-capture

## Context

Two open Phase 1 tasks asked for Painter recordings that only the agent holding the Assets3D Painter lock may make:

- `phase1.11_compositor-blend-gaps`: `blend-component-hue` (`parity/reports/phase1/compositor-blend-gaps.md` §3.3), to fit the float32 hue evaluation of Tint, Saturation, Color and Value. The setup, channels and texture sets are specified. The authored fixture `hue-grid` is specified only loosely ("the column index codes a sector, a chroma and a middle position"; "the remaining columns hold the 13 tie and grey cases"). The same report's §5 asks, optionally, for normal-map modes at off-grid opacities and on an exactly flat normal.
- `phase1.10_compositor-float32-residual` (report on branch `wt/phase1.10-diagnostic`): sRGB8 coverage passes through binary16 only from 1/2 up, and the evidence below 1/2 is eight tie rows of `group-coverage-order` s3 (opacity 0.3). Its open item asks for "sRGB8 coverages on 8-bit ties in [0.25, 0.5) at other opacities". No exact specification exists.

Measured for the design (float32 model of the fitted order, `ao = fl(a + fl(m fl(1 - a)))`): with the top opacity a = (2k + 1)/510, row 0 of the mask ramp (m = 0) puts the group coverage on the 8-bit tie (k + 1/2)/255. In [0.25, 0.5) binary16 toward zero equals the plain 8-bit rule identically (both keep 12 fractional bits), so only coverages below 1/4 or above 1/2 separate them.

The model panel was consulted under the owner's delegation on 2026-10-11 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| A: `coverage-srgb8-ties`, k = 64..127 on User0-User7 of eight sets | PARTLY x2, AGREE x1: k = 127 is 1/2 itself, a boundary control (63 ties inside); verify against the stored opacities; the rows above 1/2 serve as the binary16 side |
| A-User8: opacities with several tied rows (0.3, 0.1, 1/6, 9/34, 7/34, 11/34, 7/30, 11/30) | AGREE x2, PARTLY x1 (enumerate the tie rows after float32 evaluation) |
| A-no-controls | PARTLY x3: add one RGB32F control channel |
| B1: group r = y // 16, in-group index t = (y mod 16) 256 + x | PARTLY x2, AGREE x1: centre 3855 (r + 1) exactly; state the reading of "column index" |
| B2: sectors x chromas x middle positions | AGREE x2, DISAGREE x1 (bounds; checked: min stays at or above 1 807, max at most 63 728) |
| B3: the six tie types at every chroma, then grey | PARTLY x3: "13" is not explained by any reading; the superset covers every reading; freeze the order |
| B4: pseudo-random widening cases | PARTLY x2, AGREE x1: pin the generator; keep them out of the fit |
| B5: transposed fixture authored | AGREE x2, PARTLY x1 (test the transpose) |
| B6: L16 takes the red component | AGREE x2, PARTLY x1: give the L16 uniform colours explicitly |
| C1, C2: `blend-normal-opacity` | AGREE x3 / AGREE x2, PARTLY x1 |

## Decision

1. **`tier0/semantics/blend-component-hue`** (`current.py`; §3.3 as written for mesh, resolution, channels, opacities and sets s0-s4). Fixture `hue-grid` (256 x 256 RGB16, `fixtures.hue_grid`): row group r = y // 16, centre code 3855 (r + 1) = 65535 (r + 1)/17; in-group case index t = (y mod 16) 256 + x ("column index" is read as the in-group texel index). t < 504: sector in the order (max, mid) = (R,G), (G,B), (B,R), (R,B), (G,R), (B,G), chroma d from {1, 2, 3, 4, 8, 16, 32, 64, 128, 256, 1024, 4096}, middle offset u from (0, 1, d//4, d//2, 3d//4, d - 1, d); min = centre - d//2, max = min + d, mid = min + u. 504 <= t < 576: the six tie types (R = G, G = B, R = B, each as the maximum and as the minimum) at every chroma; t = 576: grey. t > 576: widening cases from the 32-bit LCG (seed 20261011, a = 1664525, c = 1013904223, draw = state >> 8; sector, d in [1, min(8192, 2 min(centre, 65535 - centre))], u in [0, d]); they are validation data, not fit data. `hue-grid-transposed` is the exact transpose; the L16 channel takes the red component of each (`hue-grid-grey`, `hue-grid-transposed-grey`, decision 048) and uniform greys of each colour's largest component (0.5 for (0.5, 0, 0), 0.25 for grey 0.25).
2. **`tier0/semantics/blend-normal-opacity`**, a sibling of the immutable `blend-component`: s0-s2 NormalMapCombine, NormalMapDetail and NormalMapInverseDetail of fields B over fields A at upper opacity 0.1, 1/3, 0.7 and 0.99 (User0-User3 RGB32F, User4-User7 RGB16); s3-s5 the same modes with the uniform normal (0.5, 0.5, 1.0): flat under fields B, fields A under flat and flat under flat at 0.5, flat under flat at 1, on each format (RGB16 cannot hold 0.5 exactly: a near-flat control); s6-s7 empty.
3. **`tier0/semantics/coverage-srgb8-ties`**: the stack of `group-coverage-order` s1 (root 0 at 1, a Normal group holding fields B under the grey-B mask m = y/255 and fields A on top) with User0-User8 sRGB8 and User9 RGB32F. Top opacity per set i and channel j < 8: (2k + 1)/510, k = 64 + 8i + j, so row 0 lies on the tie (k + 1/2)/255 for k = 64..127 (k = 127 is the boundary 1/2); User8 and User9 per set: 0.3 (the earlier recording's opacity, a cross-session check), 0.1, 1/6, 9/34, 7/34, 11/34, 7/30, 11/30. The recorder accepts `User8` and `User9` (documented `ChannelType` members).
4. **Recording and admission.** One Painter 12.1.5 session, Legacy colour management, documented API only, under the Assets3D Painter lock; r1 (same session) and r2 (after save and reopen); admitted with `uzpainter parity record`; `store verify` ok. Every opacity readback equals the requested value as float32 (320 of 320 in `coverage-srgb8-ties`).

| Golden | Maps | r1 = r2 | Private record (SHA-256) |
|---|---|---|---|
| `tier0/semantics/blend-component-hue` | 64 | 64/64 | `d5faa211e79b4376a12a6a3d20aa277c3cfa9fe885d0b2eb31d7f4ebf22c1bf1` |
| `tier0/semantics/blend-normal-opacity` | 64 | 64/64 | `2a4539ba565470b66c829b91c3d7dc3261c24afd523d26ea17b76b28bfce558b` |
| `tier0/semantics/coverage-srgb8-ties` | 80 | 80/80 | `01127c451fde36c8744d22d0e22fb4f8b1694e27a627e87dc71db41508f4e20d` |

## Alternatives Considered

- Add the normal-map sets to `blend-component` (rejected: a recorded golden is immutable).
- Several golden rows per tie instead of one tie per opacity at row 0 (not adopted: 64 opacities cover [0.25, 0.5) at every 8-bit tie; User8 adds rows with several ties).
- The L16 channel reading the RGB hue grid (rejected: decision 048 gives L channels grey fixtures; an RGB-to-grey import rule would be a second unknown).

## Consequences

`phase1.11_compositor-blend-gaps` can fit the middle weight on `blend-component-hue` s0 User0 and validate on s1-s4 and `blend-component`; `phase1.10` (or its successor) can test the sRGB8 coverage rule on 63 ties below 1/2 at 64 opacities plus the multi-tie rows and the RGB32F control; the normal-map extras are available to phase1.11. Those tasks' files are not changed here.
