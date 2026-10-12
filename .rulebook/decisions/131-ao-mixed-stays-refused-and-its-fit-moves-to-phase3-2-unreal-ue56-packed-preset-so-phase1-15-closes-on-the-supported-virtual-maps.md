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
