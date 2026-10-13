# 223. `infinite` padding on UV islands is written under exception EXC-007: covered texels exact, padding texels excepted, chosen by the model panel on the owner's delegation

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine, phase1.16_export-processing-encoders

## Context

Decision 220 measured the best-known `infinite` padding rule: covered texels are exact on all 39 padding maps and the Wand's 5, but padding texels miss Painter by up to 59,150 PNG 16 codes, 90 PNG 8 codes and 1.18 in OpenEXR. The owner's ±1-code exception could therefore not be registered, and the Wand (gate G1) stayed blocked on item 2.7.

**The owner's delegation.** On 2026-10-13 the coordinator asked the owner (André) to choose between:
1. keep hunting the exact rule with no exception;
2. a broad exception: padding texels may differ freely, interior exact, checked with a UV coverage mask; keep hunting;
3. exactness only within N texels of the islands, the rest free.

He answered, verbatim: "n sei oq quer dizer isso, fale com outros modelos disponiveis no 9 router" ("I don't know what this means; talk to the other models available on 9router"). This decision treats that answer as delegating the choice to the model panel (memory note *decide with a model panel*). Earlier the same day he had chosen "unblock the Wand now, hunt the exact rule in parallel" (decision 220, Context).

## Measurements

All of them come from the decision-220 prototype (private scratch `pad220/`), run on the CPU from the private store. They compare against Painter's r1 `infinite` exports.

**Option 3 needs the error by distance from coverage.** The table gives the maximum difference over padding texels within N texels of coverage (chessboard distance; N = 1 is the ring). Values are 16-bit codes; * marks a hypothetical encode, for probes that were exported to OpenEXR only.

| Golden | Padding texels N1 / N2 / N4 / N8 / all | PNG 16 max, N1 → all | PNG 16 texels > 1 code, N1 / N2 / N4 / N8 |
|---|---|---|---|
| ramp-r1-p0 | 2,056 / 4,128 / 8,320 / 16,896 / 917,504 | 9,593* at every N | 8 / 24 / 80 / 288 |
| ramp-r2-p0 | 1,544 / 3,104 / 6,272 / 12,800 / 966,656 | 32,743* at every N | 262 / 532 / 1,096 / 2,320 |
| tie-512, tie-2048 | | 1* at every N | 0 |
| export-padding (7 maps) | 9,709 / 18,200 / 34,132 / 67,067 / 260,498 | 23,265 at every N | 3,588 / 5,389 / 8,309 / 14,174 |
| bevelled cube (4 maps) | 9,376 / 18,944 / 38,656 / 48,800 / 48,800 | 51,315 at every N | 8,298 / 16,788 / 34,344 / 43,410 |
| sphere (4 maps) | 8,704 / 14,080 / 16,384 / 16,384 / 16,384 | 44,111 at every N | 7,459 / 12,077 / 14,018 / 14,018 |
| seam-1024 (3 maps) | 7,704 / 15,456 / 31,104 / 62,976 / 2,506,752 | 37,213 at every N | 1,241 / 2,502 / 5,084 / 10,488 |
| Wand BaseColor | 6,334 / 12,698 / 25,518 / 51,528 / 3,685,999 | 42,573 at every N | 6,333 / 12,696 / 25,516 / 51,526 |
| Wand Metallic | same | 59,150 at every N | 1,897 / 3,812 / 7,713 / 15,763 |
| Wand Normal | same | 34,872 at N1, 36,756 overall | 6,334 / 12,698 / 25,518 / 51,528 |

The OpenEXR and PNG 8 maxima behave the same way: every golden reaches its decision-220 maximum already at N = 1. The only exception is the Wand's Normal, which reaches 34,872 of its 36,756 there. **No band N ≥ 1 is exact today.** Option 3 at any N blocks exactly like option 1.

**Painter's padding is stable.** On the Wand, r1, r1-repeat and r2 are byte-identical on all 3,685,999 padding texels of all 5 maps. The divergence is ours, not oracle noise.

**A coverage-only rule.** This rule computes every ring texel with the straight-edge rule: the 8-neighbour weighted mean of decisions 176 and 206, x wrapping. It ignores seams, so it needs nothing but the coverage mask. The table compares it with the full prototype, which needs the 3D mesh, seam partners and unfolding. Values are the mean |Δ| over padding texels in 16-bit codes, then the max.

| Map | Coverage-only, mean / max | Full prototype, mean / max |
|---|---|---|
| Wand BaseColor | 2,548 / 29,580 | 3,828 / 42,573 |
| Wand Roughness | 499 / 21,074 | 1,471 / 26,267 |
| Wand Metallic | 396 / 42,148 | 2,233 / 59,150 |
| Wand Height | 1.04 / 73 | 2.52 / 55 |
| Wand Normal | 8,282 / 32,238 | 6,398 / 36,756 |
| export-padding (no seams) | identical | identical |
| seam-256 user0 | 7,721 | 820 |
| sphere user0 | 2,319 | 282 |

On the Wand, whose island borders are all seams, the coverage-only rule is closer on 4 of 5 maps. On the synthetic seam goldens the full prototype is closer.

**Where padding texels are read.**
- Tier 3 render parity compares UzPainter's own path tracer with Painter's Iray on the document. It never reads the exported files (CONTRACT §4.1).
- The fixed Assets3D render standard (decision 038) names no texture filtering or mipmap setting.
- Downstream, exported files are read by Blender (bilinear sampling reaches the N = 1 ring at island edges) and by engines that build mip chains (level k mixes padding up to about 2^k texels out).

## Panel

The dossier (measurements above plus nine claims) went to `cx/gpt-6-astra`, `kimi/kimi-k3` and `xai/grok-4.5` in one round.

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 Option 3 is not a real choice today | PARTLY: the Wand Normal reaches its maximum only beyond N1, but no N passes | AGREE | AGREE |
| C2 Option 1 costs more than it buys | PARTLY | PARTLY | AGREE |
| C3 A scoped "padding free, interior exact" exception keeps the spirit of 001/017 | DISAGREE: 017 wants bounds | AGREE | AGREE |
| C4 The risk is bounded to edge bleed; Tier 3 unaffected | PARTLY: coarse mips can reach small islands | PARTLY: normals and metallic edges are visibly wrong | AGREE |
| C5 The basis must say "unfitted rule, owner scope", not oracle instability | AGREE | AGREE | AGREE |
| C6 No numeric bound only with published residuals and narrowing | PARTLY | AGREE | AGREE |
| C7 Ship the coverage-only rule | PARTLY: choose per map | PARTLY: re-measure per asset class | PARTLY: revisit for seam assets |
| C8 A measured bound (59,150) would be meaningless | DISAGREE: useful as a regression ceiling | AGREE | AGREE |
| C9 Report "pass under EXC-007", G1 lists it | AGREE | AGREE | AGREE |

**Votes.**
- Kimi and Grok: **option 2G**, option 2 with guards.
- GPT: a narrower option 2G with measured per-map bounds, limited to the Wand. It disagreed that an unbounded exception keeps decision 017.

**Risks the panel added:**
- the coverage mask becomes the only line between exact and free texels, so a mask bug is a silent hole;
- wrong normals and metallic values at seams are the most visible case;
- the delegation is fragile, because the owner did not make an informed approval;
- one asset should not decide the rule for every asset.

## Decision

1. **Option 2G, by majority (2 of 3).** `infinite` padding on incompletely covered texture sets is written, under exception **EXC-007** (version 1).
2. **What EXC-007 covers:**
   - **Domain.** The Wand v1 Tier 1 golden's domain only, `tier1/pilot/wand-v1` (GPT's narrowing, taken). Any other golden or asset needs a new version of the entry, with its own measurements, or its own entry.
   - **Covered texels.** They must be exactly equal. The entry's only bound is `max_abs_diff` over the covered texels, max 0. A comparison without a coverage mask is not covered by the entry.
   - **Uncovered texels.** They may differ. They are still measured and published in every report, per map: max, mean and count of differing values, overall and within 1, 2, 4 and 8 texels of coverage.
   - **Basis.** A new evidence basis, `owner_scope_split`: Painter is stable, the rule is ours and unfitted, and the scope was decided by the panel on the owner's delegation, recorded here. It is not oracle instability.
3. **No numeric bound on padding texels** (majority on C8).
   - A bound measured on a guessed rule and one mesh would not carry to the next asset.
   - Published residuals and versioned narrowing are the guard instead: the entry is narrowed, by a new version, as each part of the rule becomes exact, straight edges first.
   - GPT's dissent is recorded. A per-map regression ceiling is deferred to the first version that covers a second asset.
4. **The rule shipped is the coverage-only one** (guard (f); majority PARTLY on C7, with the Wand as the asset in scope).
   - Ring texels take the straight-edge 8-neighbour mean of decisions 176 and 206, with x wrap.
   - The gutter is decision 197's jump flood from the covered and ring texels.
   - Covered texels are never touched.
   - It acts on the values the file stores: OpenEXR floats, and PNG codes as UNORM operands, with each filled code written back by the write rule. The reason is OCIO: a PNG 16 sRGB channel under OCIO stores only Painter's recorded codes (decision 190), and a mean of linear values has no recorded code. The first Wand export proved it, refusing BaseColor with "an unrecorded OCIO sRGB value". Decision 223's Wand measurements were made on the same PNG 16 codes.
   - It needs only the coverage mask, so no 3D mesh reaches the export path. The full prototype stays in private scratch for the exact hunt.
5. **Defect detection.**
   - One code on one covered texel fails, whatever the register holds.
   - An injected padding error passes under EXC-007 and shows in the published padding residuals.
   - The coverage mask's equality to Painter's is tested on the position-encoded probes.
6. **The R-090 refusal is lifted only for `infinite` padding on incompletely covered sets.** `passthrough` keeps its own rules (decision 090). The `color`, `transparent` and `diffusion` paddings stay refused.
7. **Item 2.7 stays open** for the exact rule, owned by `phase1.25_pilot-wand`, in decision 220 §5's order. G1's gate record lists EXC-007 as relied on. A Wand pass is reported as "pass under EXC-007 (padding texels excepted)", never as exact.
8. **For the owner** (owner-only: an exception's terms):
   - EXC-007 is recorded `approved_by: owner` on the strength of his delegation above.
   - He may withdraw it, or replace its terms, at any time. A new version of the entry does that.

## Result: the Wand's Tier 1 run (DX12, 2026-10-13)

The run used `tests/parity/tier1/wand_v1`, with UzPainter built ReleaseFast. In a Debug build the export took 465 s to its first 2048 map, which is past the adapter's 600 s limit per call. Report: `parity/reports/phase1/tier1-wand-v1.json`.

**Verdict: `fail`.** EXC-007 is relied on, and the two rebuilds are byte-identical. The oracle is stable.

| Map | Covered texels: values differing (max) | Padding texels: values differing / max / mean (PNG 16 codes) | Under EXC-007 |
|---|---|---|---|
| BaseColor | 0 | 9,523,887 / 29,580 / 2,138 | pass |
| Roughness | 0 | 621,903 / 21,074 / 499 | pass |
| Metallic | 0 | 329,614 / 42,148 / 396 | pass |
| Height | 0 | 709,980 / 73 / 1.04 | pass |
| Normal | 2,499 (537 codes) | 11,040,082 / 32,238 / 4,302 | **fail** |

**The Normal failure is a covered-texel divergence, not padding.**
- All 1,071 differing covered texels lie on the island edge: each has an uncovered 8-neighbour. No texel farther inside differs.
- The Normal is the `Normal_OpenGL` virtual map, computed from Height. At the island edge, Painter's normal reads Height values outside the island, so it depends on Painter's Height padding there. The exception cannot cover it, and it must not: covered texels stay exact.
- This makes the exact rule (item 2.7) a covered-texel requirement for a virtual normal near island edges, not only a padding one.
- The Wand's 3.1 stays open on that.
- Next, in the exact hunt: test whether Painter derives the edge normals from its padded Height, and which ring that needs.

## Alternatives Considered

- **Option 1** (keep hunting, the Wand blocked): rejected 0 of 3. Eight passes have not found the seam-corner, pole and sign rules.
- **Option 3** (exact within N texels): rejected. It is measured impossible for every N ≥ 1 today.
- **Option 2 without guards:** rejected. It would freeze a divergence silently.
- **The full prototype as the shipped rule:** rejected. It is farther from Painter on 4 of the Wand's 5 maps, and it needs the 3D mesh and seam unfolding in the export path.

## Consequences

- The Wand can be exported and compared. Its Tier 1 verdict can pass only with every covered texel exact; today 4 of 5 maps do, and the Normal fails on its island-edge texels (Result).
- The comparison report gains per-map padding residuals.
- The exception schema gains the basis `owner_scope_split` and the bound scope `covered`.
- The verdict tool takes a coverage mask.
- `parity/semantics/export-processing.json` keeps `padding-islands` as a gap: the exact rule is not identified.
