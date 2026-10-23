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

## Amendment (2026-10-23, current-envelope stability controls)

The coordinator recorded and admitted the two authored controls under
`painter-12.2.0+js-api.1.1.20-env-a981b586eae7`. Public manifests are under that
envelope's `manifests/tier0/semantics/`; private record references:

- `ao-mixed-grid-l32f`: `2461404b1f25e0e2ec2ab74c24df788eb333e3da033ffd369bfce364bd2460c1`.
- `ao-mixed-grid-l16-reopen3`: `16ff9bbab29885692b30cbe7178e3790ab896ca32cec12eb81cef9ae8fb96969`.

The L16 control retains r1 and three successive Full save/close/reopen recordings,
r2 through r4. Every decoded exported map is identical between r2, r3 and r4.
Relative to r1, AO_Mixed changes at 27, 39, 0 and 27 texels in s0 through s3,
respectively, in each export. The AO channel and mesh-map exports remain identical.
The new r1 and r2 also exactly reproduce the corresponding current-envelope
`ao-mixed-grid` recordings. This establishes repeatable post-reopen behavior for
this control, not an exact operator or a change to acceptance requirements.

The L32F control exposes a further distinction. In r1, every channel value matches
`fma(float32(C - 1), opacity, 1)` with float32 source C and unquantized float32
opacity. After reopen, s1 (opacity 0.75) has 11,520 channel texels increased by one
float32 ULP and 3,584 increased by two ULPs; its AO_Mixed changes at one texel.
Other sets are unchanged. These are aggregate counts; recorded pixels remain
private. API readbacks are unchanged after normalizing the transient project
resource-context identifier.

All immediate export repeats agree. PNG 8 and OpenEXR 32f AO_Mixed twins agree
exactly as code and float32(code / 255); mesh-map EXR values equal the authored
code / 255 rounded to float32. Nearest and BilinearHQ controls agree.

`WriteUnorm8(float32(mesh_export * channel_export))` still misses 2, 1, 0 and 2
texels per set in each L32F recording. Using mesh code multiplied by a float32
reciprocal of 255 reduces some residuals but does not eliminate them and is not
established by the mesh export. No partially improved model is accepted. The
production refusal and item 2.10 remain unchanged; post-reopen reproducibility
alone does not resolve the r1/r2 acceptance question.

Private analysis: `tmp/scratch/ao-mixed-fit/stability.py` and
`current-stability-controls.json`, with the existing current-grid control checked
first. The script reads the store without writing recorded pixels to public files.

A bounded offline follow-up rejected 81 arithmetic hypotheses: three authored
mesh normalizations and three source normalizations (division by 255, float32
reciprocal multiplication by 255, or 16-bit code times the reciprocal of 65535),
combined with nine multiplication/FMA evaluation orders. None is exact even on
r1 across the old L16 grid and the two new controls; none fits all recordings.
Six exported-operand product variants also fail across the eight goldens with
sufficiently precise channel exports. The PNG8-only isolation golden is not used
to infer a high-precision channel operand and remains required for any eventual
operator acceptance. Diagnostic script/report: private
`tmp/scratch/ao-mixed-fit/bounded-arithmetic.{py,json}`. No residual ranking is a
fit verdict, and no candidate advances to production.

### Precomposed-source control (2026-10-23)

`ao-mixed-precomposed-half-l32f` is admitted in the same envelope, private record
`c889c68fd5d8063df78e9e966d13b07febb36a99e2e9e23dfc40eed4845ac2eb`.
Its authored RGB EXR source (SHA-256
`d5cdfd94bf239cfdb4630c78cf0bb72f5582ebea8bcc7a7a8f7edb4e474c3d84`)
precomputes the opacity-0.5 channel formula without oracle pixels. The scalar
identity through an opacity-1 blend is independently tested on all 256 rows.

The capture does **not** satisfy the intended equal-operand precondition. In both
Nearest and BilinearHQ pairs, and in both recordings, the precomposed source's
channel differs from the original at 17,408 texels (68 rows), by at most one
float32 ULP. Mesh maps are identical. AO_Mixed is identical across each pair;
all immediate repeats and r1/r2 exports agree. Because the channels differ,
this result neither establishes an operator of exported operands nor disproves
composition-path dependence.

The changed channel is explained exactly by the RGB-to-scalar arithmetic on
this replicated-grey fixture: `float32(float32(float32(c+c)+c) * float32(1/3))`.
Float32 division by three instead of reciprocal multiplication does not match.
The original opacity-0.5 channel equals the authored c exactly. This isolates
the RGB source conversion as the failed control precondition, rather than
failure of the authored scalar opacity-1 identity. It is scoped evidence for
this fixture, not general acceptance of a new RGB conversion or AO_Mixed rule.
A scalar float EXR source could isolate that conversion in a future control;
none is recorded or claimed here. The AO_Mixed refusal remains.

Private aggregate diagnostics: `tmp/scratch/ao-mixed-fit/precomposed-analysis.json`
and `precomposed-conversion.json`. Authored sources remain at their original paths
and/or under `requests/admitted/tier0/semantics/`. The admission catalog excludes
them from the pending queue and checks every copy against its admitted manifest,
without deleting or moving files. Recorded pixels remain solely in the private store.
