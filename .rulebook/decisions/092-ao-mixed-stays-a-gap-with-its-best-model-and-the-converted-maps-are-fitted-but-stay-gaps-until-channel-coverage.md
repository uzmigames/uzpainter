# 92. AO_Mixed stays a gap with its best model, and the converted maps are fitted but stay gaps until channel coverage

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.15_export-plan-compiler, phase1.18_export-engine

## Context

Decision 086 left AO_Mixed and the ten converted virtual maps as release gaps until recording R-086. Decision 087 recorded R-086:

- R-086a is the AO_Mixed opacity sweep `ao-mixed-opacity` and its OpenEXR 32f twin;
- R-086b is the converted maps `virtual-maps-converted` and its twin.

Their encodings were left `undetermined`. Both were fitted in the scratchpad against the private store; only numbers are published here.

### AO_Mixed

- **Shape.** The values lie on the 8-bit lattice before encoding: k/255 in the EXR. Step A equals step B. r1 and r2 differ by one 8-bit step at 9 to 41 values per set.
- **Best model.**
  1. `alpha` = the layer opacity's L16 code / 65535.
  2. `C` = the fill's stored L16 code / 65535.
  3. `c = fma(C - 1, alpha, 1)`: the AO channel before its L16 write. `WriteUnorm16(c)` reproduces the channel export with 0 misses on r1.
  4. `a` = the AO mesh map code / 255.
  5. `v = a c` in float32.
  6. AO_Mixed = the 8-bit write of `v`: truncated to 12 fractional bits, then the nearest code, ties down.
- **Misses on r1.** 31 values over the three goldens:

  | Golden | Sets | Misses per set |
  |---|---|---|
  | `ao-mixed-opacity` | s0-s7 | 0/9/2/0/0/9/2/0 |
  | the EXR twin | s0-s7 | the same |
  | `ao-mixed` | s0-s3 | 0/9/0/0 |

  Each miss lies within 3 ulps of `v` from a 2^-12 boundary. The calibrated operator of decision 086 missed 195 on the new goldens.
- **What no model reproduces.** Where `C = 0`, `c = 1 - alpha` is exact in any order of operations, yet `v` must rise by 2 to 3 ulps. No correctly rounded float32 evaluation of the tested inputs reproduces r1. The rejected candidates are in `virtual-maps.json`. r2 is not explained.

### Converted maps

Inputs, all float32:
- `L` = BaseColor's linear sRGB8 operand;
- `r`, `m` = the roughness and metalness codes / 255.

Helpers:
- `enc`: Painter 12.1.5's GPU sRGB encode, with exponent 0.41666 and the recording GPU's exp2 and log2;
- `toL`: the Rec. 601 fma chain.

| Map | Operator | Exact on |
|---|---|---|
| Diffuse | `enc(L (1 - m))` | every texel of s0-s7, PNG 16 and EXR 32f, 0 differing |
| Specular | `enc(fma(L - 0.04, m, 0.04))` | same |
| Glossiness | `toL(1 - r)` | same |
| Glossiness2 | `toL((1 - r)²)` | same |
| Unity4Diff | RGB `enc(L)`, alpha = BaseColor coverage | same |
| Unity4Gloss | RGB `(m + (1 - r)) 0.5`, alpha = roughness coverage | same |
| reflection | `fma(enc(L) - 1, enc(m), 1)` | same |
| 1/ior | `toL(fma(-k, m, k))`, `k` = 0x3F2AAAAA | same |
| f0 | `fma(0.96, m, 0.04)` | same |
| View_2D | none | not an operator on the channels |

- **Uncovered texels.** Where a channel has no layer, the maps read `L` = 1.3, `r` = 0.5980393 and `m` = 0, not the channel's base value. This was seen on one template only.
- **Coverage.** Coverage was only full or none per set.
- **Alpha.** An all-opaque alpha is dropped from the file.
- **View_2D.** Its values vary texel to texel without a period wherever roughness is above 0, and sets with identical inputs differ at a few texels.
- **The evaluator.** It returns channels composited over their base and gives no per-texel coverage.

The model panel was consulted under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| D1 AO_Mixed stays a gap; publish the best model, its misses and the unknown; R-092 isolates it | AGREE x2, PARTLY x1: the tests reject the tested pipelines; they do not prove one faulty rounding step (wording adopted). Keep twins, repeats and reopen pairs in R-092, and judge on r1 |
| D2 The nine fitted maps stay gaps until (a) channel coverage from the evaluator, (b) R-092 on other templates and fractional coverage, (c) a fit through `EvaluateFileOn` exact on every texel | AGREE x1, PARTLY x2: track the dependency per map. The alpha needs coverage, and the uncovered inputs need the inactive-channel semantics. Measure that isolated root alpha equals Painter's coverage before choosing an API (adopted) |
| D3 View_2D is a gap without an operator | AGREE x2, PARTLY x1: the evidence shows missing render state; it does not prove that a whole renderer is needed. Probe the view state first |
| D4 Items 3.6 and 4.1 stay open on AO_Mixed only; unsupported maps do not count toward "every map marked supported" | AGREE x2, PARTLY x1 |

## Decision

1. **AO_Mixed stays a release gap.**
   - The plan refuses it before writing, naming recording R-092 (`Support`, `src/export/virtual_maps.cpp`).
   - `parity/semantics/virtual-maps.json` records the best model, its misses per set, the rejected candidates and the unknown: Painter's operand conversions or arithmetic on that path.
   - `parity/semantics/ao-mixed.json` (calibrated, Painter 12.1.0) is unchanged.
2. **The nine fitted converted maps stay release gaps.** `virtual-maps.json` records each operator with its inputs and fit. Per map, they depend on:
   - **alpha:** Unity4Diff and Unity4Gloss need the coverage of BaseColor and roughness. Whether metalness coverage also counts for Unity4Gloss is not recorded.
   - **uncovered inputs:** all nine read fixed inputs where a channel has no layer. These are recorded on one template only.

   They are lifted when all three of these hold:
   - (a) the evaluator exposes per-texel channel coverage, measured equal to Painter's;
   - (b) recording R-092 covers other templates, inactive versus empty channels, fractional coverage (opacity below 1, masked fills, groups) and stacked layers;
   - (c) the maps, evaluated through the plan (`EvaluateFileOn`) and written by the phase1.16 writers, equal r1 on every texel at PNG and EXR, including the dropped opaque alpha.
3. **View_2D** stays a release gap with no published operator. R-092 probes its view state (environment, lighting, sampling) before any renderer scope is set.
4. **Items 3.6 and 4.1** stay open on AO_Mixed. Only maps marked supported count toward 3.6.
5. **Recording R-092** (requested, for the agent that owns Painter):
   - for AO_Mixed:
     - a constant AO mesh map with a varying channel;
     - a constant channel with a varying mesh map;
     - values at the 31 missed coordinates;
     - repeats, an EXR twin and reopen pairs;
   - for the converted maps:
     - the probes of 2(b);
     - the View_2D view-state probes.

## Alternatives Considered

- **Implementing the nine maps for fully covered sets only.** Rejected: the plan cannot know coverage before evaluation, and the evaluator cannot report it.
- **Accepting AO_Mixed's 31 misses.** Rejected: a residual is never accepted (decision 032).

## Consequences

- Configurations naming AO_Mixed or a converted map still fail before writing, now naming R-092.
- The evaluator owes a channel-coverage output before the converted maps can land.
