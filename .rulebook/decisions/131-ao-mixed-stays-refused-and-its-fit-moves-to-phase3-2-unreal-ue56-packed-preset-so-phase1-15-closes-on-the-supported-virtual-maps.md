# 131. AO_Mixed stays refused, and its fit moves to phase3.2_unreal-ue56-packed-preset, so phase1.15 closes on the supported virtual maps

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.15_export-plan-compiler, phase1.18_export-engine, phase3.2_unreal-ue56-packed-preset

## Context

Items 3.6 and 4.1 of `phase1.15_export-plan-compiler` are the last open items besides the prerequisite 1.1.

- **3.6** reads "Tier 0 virtual-map goldens (`AO_Mixed`, `Normal_OpenGL`, `Normal_DirectX` and every other virtual map marked `supported`) exact". **4.1** waits on 3.6.
- `Normal_OpenGL` and `Normal_DirectX` are supported and exact: 40 maps, 72 comparisons (`parity/reports/phase1/export-plan-compiler.md` §3).
- `AO_Mixed` is a release gap (decisions 086 and 092).
  - The plan refuses it before writing, naming recording R-092 (`src/export/virtual_maps.cpp`).
  - Its best model misses r1 at 31 values of R-086a.
  - R-092's isolation goldens were recorded and admitted (decision 093: `ao-mixed-isolation`, its float and 8-bit twins). They show that the misses depend on the operand values (mesh map code, channel code, opacity), not on the texel position, and that Painter's AO_Mixed is its own 8-bit write.
  - No exact model is known yet.
- The converted maps and View_2D are also release gaps. They are not marked supported, so they do not count toward 3.6 (decision 092 §4).
- Speed rule 4 of the agent brief (2026-10-12): an item blocked only by a recording or a later phase is checked as a recorded scope split with an owner (the decision-069 pattern), as long as nothing claimed is untrue.
- The first tasks that need AO_Mixed are two Phase 3 presets:
  - `phase3.2_unreal-ue56-packed-preset`: `_OcclusionRoughnessMetallic`, R = `AO_Mixed` (`docs/architecture/08-export.md` §4). It already owns the export-processing remainder of decision 103 (item 2.9).
  - `phase3.2_uze-uzmat-preset`: `<set>_orm`.
- No Phase 1 deliverable exports AO_Mixed. The Wand v1 pilot (`phase1.25_pilot-wand`) exports BaseColor, Roughness, Metallic, Height and Normal_OpenGL only.

The coordinator directed this split. Under speed rule 3, the owner choice is not a real fork, so no model-panel round was held.

## Decision

1. **Items 3.6 and 4.1 are checked as a recorded scope split.** This decision amends them. Their original wording stays.
   - phase1.15 owns the virtual maps it marks supported: `Normal_OpenGL` and `Normal_DirectX`, exact on their Tier 0 goldens.
   - phase1.15 also owns AO_Mixed's refusal before writing, which is what it ships for that map.
   - Nothing claims AO_Mixed is supported.
2. **The AO_Mixed fit moves to `phase3.2_unreal-ue56-packed-preset` item 2.10**, a later task, so no blocker moves down:
   - fit AO_Mixed exactly against R-086a (`ao-mixed`, `ao-mixed-opacity` and its OpenEXR 32f twin) and the R-092 isolation goldens (`ao-mixed-isolation`, `-float`, `-8bit`);
   - implement it in the plan (`src/export/virtual_maps.cpp`) and lift the refusal only when every texel of r1 is exact at PNG 8, PNG 16 and OpenEXR 32f;
   - if the isolation goldens do not identify the operator, the settling recording is R-131: the full grid of mesh-map codes 0-255 against channel codes 0-255, at the opacities of the missed R-086a sets and at opacity 1, as PNG 8 and OpenEXR 32f, with r1, r2 and a same-session repeat. Only the agent that owns Painter records it.
   - `phase3.2_uze-uzmat-preset` (`<set>_orm`) uses the same operator. Until item 2.10 lands, its AO_Mixed output is refused before writing.
3. **The gap stays visible.**
   - The refusal keeps naming R-092 and decision 092.
   - `parity/semantics/virtual-maps.json` keeps AO_Mixed's best model, its misses and the rejected candidates. It is not edited, because its notes are derived by the Tier 0 comparison.
   - `parity/reports/phase1/export-plan-compiler.md` §5 and `docs/architecture/08-export.md` §2 name the owner item.
4. **The converted maps and View_2D are unchanged.** They stay release gaps under decision 092 §2 and §3, refused before writing. `phase5.3_parity-report-capability-gaps` item 2.3 registers them with decision 092.

## Alternatives Considered

- **Keeping 3.6 and 4.1 open until the fit.** Rejected. It would hold phase1.15, phase1.18 and gate G1 on a fit that no Phase 1 deliverable needs.
- **Moving the fit to `phase1.25_pilot-wand`.** Rejected. The Wand does not export AO_Mixed, so the fit has no consumer there.
- **Accepting the 31 misses.** Rejected: a residual is never accepted (decision 032).

## Consequences

- phase1.15 can archive once its prerequisite 1.1 is accepted. phase1.18 item 2.1 then follows.
- `phase3.2_unreal-ue56-packed-preset` item 2.10 is a non-waivable item. Its ORM output cannot ship before it.
- A configuration naming AO_Mixed still fails before writing.

## Amendment (2026-10-21, fit attempt on the admitted R-131 grid)

CPU analysis of the admitted `ao-mixed-grid` (R-131), R-086a and R-092, read-only from the store. Logs are in `tmp/scratch/ao-mixed-fit/`.

- **Channel.** It is reproduced exactly: opacity stored as an L16 code with ties down, and c = fma(C − 1, cov, 1) written as L16. The AO-channel export has 0 misses on every grid set.
- **Best model:** AO_Mixed = WriteUnorm8(float32(a · c)), a = mesh-map code / 255, the decision 092 model.
  - At opacity 1 it is exact on all 65,536 pairs.
  - Below opacity 1, r1 misses on the same 11 (mesh code, channel code, opacity) pairs in every admitted golden, whatever the filter, the format or the operand roles. So AO_Mixed reads a channel operand a few float32 ulps away from the value the channel export writes. No correctly rounded evaluation, conversion, GPU transcendental or expression of size 6 or less gives it.
- **r2 cannot match r1.** r1 and r2 have bit-identical inputs and channel and mesh-map exports, yet their AO_Mixed differs at 27 to 39 values. r2 is the recording made after save and reopen. No fixed operator can be exact on both.
- **The refusal stays.** No item is ticked.
- **Settling recording:**
  - the grid with an L32F AO channel at opacity 0.5 and 0.75, exporting the channel and AO_Mixed as OpenEXR 32f; this exposes the operand;
  - a second and a third reopen (r2, r3) of the L16 grid, to show whether the post-reopen operator is itself reproducible.
- **Open question for the acceptance rule.** This decision compares r1 only. The phase3.2_unreal-ue56-packed-preset item 2.10 acceptance requires both recordings. That conflict is settled when the r3 recording shows whether r2 is reproducible.
