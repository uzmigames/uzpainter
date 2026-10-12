# 91. The dry run lists the files the export writes, and the export probes lift the refusals they settle

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.15_export-plan-compiler, phase1.16_export-processing-encoders, phase1.19_pyapi-native-module, phase1.20_pyapi-facade

## Context

Decision 085 refused, with `NotYetSupported` naming recording R-085, every export behaviour that the documentation leaves open and that no recording showed. Decision 087 recorded the R-085 probes on Painter 12.1.5. Probes P0-P13 cover 6 goldens and 45 probe steps, each recorded as r1 (same session) and r2 (after save and reopen).

For each probe, the recorder lists `list_project_textures(config)` and, when that succeeds, `export_project_textures(config)` and the directory inventory. Decision 087 §5 states the outcomes. In short:

- **Wildcards (P1, P2).**
  - `$mesh` is the mesh file stem, `grid2x2`.
  - `$project` is `Untitled` in r1 and `golden` in r2, after the save as `golden.spp`.
  - `$sceneMaterial` is the set's material, which here has the set's name.
  - An empty `$udim` or `$colorSpace` outside a group expands to nothing.
- **Groups (P3).**
  - `$textureSet(_v2)` → `s0(_v2)`
  - `$textureSet((_$udim))` → `s0()`
  - `$textureSet(_$udim` → `s0(_`
- **uvTiles (P4).** The filter `[[0,0]]` selects s0. With `[[1,0]]`, Painter's list shows `"s0": []` and the export writes nothing for s0. A rule filtered on `[[0,0]]` applies to every set.
- **srcChannel L of BaseColor (P5).** Painter writes an L file.
  - **Fit, exact on every texel of r1 and r2 of s0:** `y = fma(0.114, b, fma(0.299, r, 0.587 g))` on the linear channel operands, in float32.
  - **Written with Painter 12.1.5's 16-bit sRGB encode:** `x ≤ 0.0031308 ? 12.92 x : fma(1.055, exp2(0.41666 log2 x), −0.055)`, using the recording GPU's exp2 and log2, then the 16-bit write rule.
  - The same encode reproduces the RGB export of the channel (196608 of 196608 values).
- **srcChannel A (P6).** Only full coverage and no coverage were recorded. A set fully covered by a fill writes RGB, the opaque alpha dropped. An empty set writes RGBA with A = 0.
- **Absent alpha (P7).** An absent Opacity as the alpha of present basecolor RGB writes the RGB file.
- **Black-only maps (P8).** Painter lists them, and the export writes nothing (status Success).
- **Collisions (P9).** Two maps named alike in one preset are written `name` and `name_1`, in preset order. Case-only names are both listed, but NTFS keeps one file. The layered-set case was not recorded.
- **Keys and bitDepth (P10, P11).**
  - Undocumented keys at the root (`exportPathh`) and in a map (`comment`) are accepted silently.
  - An integer `bitDepth` raises `ValueError` "Expected a string value" from `list_project_textures`.
- **Unbound mesh map (P12).** A meshMap with nothing baked or bound is listed, then the export raises `ValueError`.
- **Legacy names (P13).** Every name is listed. The export writes bytes equal to the paired channel's direct export: `coatopacity` = CoatWeight, `sheencolor` = FuzzColor, `sheenroughness` = FuzzRoughness, `sheenopacity` = FuzzWeight, `translucency` = SubsurfaceWeight, `scatteringcolor` = SubsurfaceColor. Without the pairing channel the export raises `ValueError`. `absorptioncolor` and `specularedgecolor` raise on all three templates.
- **Painter's list is not a faithful dry run.** It names files that its export does not write (P8) or refuses (P12, P13).

Item 3.5 reads: "Dry run lists exactly the files a real export then writes".

The model panel was consulted under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5). kimi answered HTTP 503 in the first round and was asked again with the same dossier.

| Claim | Verdicts |
|---|---|
| C1 The dry run lists the files the export writes. Maps Painter lists but does not write or refuses stay in the plan with their kind. The dry run and the export raise ValueError where Painter's export raises | AGREE x2, DISAGREE x1: P12 and P13 do not show a mixed export, with files written and errors raised, so atomic failure is not proven there (adopted: such a mix is refused) |
| C2 `$mesh`, `$project` (`Untitled` unsaved), `$sceneMaterial` (`original_name`), empty wildcards outside groups; multi-dot names refused | AGREE x1, PARTLY x2: a renamed set does not show which name `$sceneMaterial` takes (adopted: refused) |
| C3 One group rule: a `( … )` with no inner parenthesis and a wildcard is a group; every other parenthesis is literal | AGREE x1, PARTLY x2: groups with both empty and non-empty wildcards, and a stray `)`, are extrapolated (adopted: both refused) |
| C4 A Default-workflow set is the tile [0, 0] for exportList and rule filters; a root filtered to nothing is omitted | AGREE x2, PARTLY x1 |
| C5 A later equal path within a root gets `_1`; a third one, equal paths of two roots and case-only names stay refused | AGREE x2, PARTLY x1 |
| C6 Undocumented keys ignored at the root and in a map only; integer bitDepth a ValueError | AGREE x2, PARTLY x1 |
| C7 P7 alpha drop, P8 black-only skip, P12 and P13 export errors, the six pairings | AGREE x1, PARTLY x2: keep each lift to the recorded shape |
| C8 srcChannel L lifted only with an exact fit; srcChannel A stays refused, and a partial-coverage recording is requested | AGREE x2, PARTLY x1 |

## Decision

1. **Dry run** (`src/export/plan.{h,cpp}`).
   - `CompilePlan`'s `files`, and `ListProjectTextures`, are exactly the files the export writes.
   - A preset map the export does not write is kept in `skipped` with a `SkipKind`:
     - `absent`: its sources are absent;
     - `not_written`: Painter lists it and writes nothing (black only);
     - `export_error`: Painter lists it and its export raises `ValueError` (an unbound mesh map; a legacy name without its channel or pairing).
   - `CheckExportable` raises `ValueError` for an `export_error` when the plan has no file to write. `ListProjectTextures` calls it, and so must the export (phase1.16, phase1.17). If the plan also writes files, `CheckExportable` raises `NotYetSupported`.
   - The plan holds what the Python facade (phase1.19, phase1.20) needs to reproduce Painter's own `list_project_textures` answer where the recordings show it. That facade decides its own shape.
   - A configuration may write no file (P8). The former "writes no file" `ValueError` had no recording behind it and is removed.
2. **Names.**
   - `$textureSet` is the set's name. `$sceneMaterial` is `original_name`, refused for a renamed set.
   - `$mesh` is the stem of the mesh's import-report source name. `$project` is the stem of `PlanContext::projectPath`, or `Untitled` when the path is empty. A name with more than one dot is refused.
   - Empty wildcards expand to nothing, outside groups too.
   - The group rule of C3 applies. A group with both empty and non-empty wildcards is refused, and so is a `)` after no literal `(`.
   - Within one exportList entry, a later equal path gets `_1` before its extension. A third one is refused, and so are equal paths of two entries and case-only collisions.
3. **Filters.** A Default-workflow texture set is the tile [0, 0]. A `uvTiles` filter selects it when the filter lists [0, 0].
4. **Keys.** Undocumented keys at the root and in a preset map are ignored. Undocumented keys elsewhere stay refused. An integer `bitDepth` is a `ValueError` ("Expected a string value").
5. **Presence and channels.**
   - P7's alpha drop is lifted for exactly that shape: three present sources and one absent source, the absent one at destination A.
   - Black-only maps are `not_written`. A mix of black and white stays refused.
   - The six P13 pairings are adopted (`RecordedAliasTarget`). `RaisesWhenAbsent` marks the eight legacy names whose absence is an `export_error`. Only decision 085's five pairings are read in the reverse direction.
   - srcChannel L of a three-component source is lifted as P5's luma (`PlannedChannel::luma`, evaluated by `EvaluateFileOn`). The luma of an sRGB8 channel's base value is refused at evaluation: the evaluator holds the base's export value (0.90634 for BaseColor), and P5 shows Painter uses its linear 0.8. The 16-bit sRGB encode is the writer's (phase1.16), which was told of it.
   - srcChannel A stays refused.
6. **Evidence.**
   - `test_dry_run_equals_painter_probes`: all 90 probe compilations (45 probes × r1, r2) behave as Painter did. Bit depths and channel counts match, and each legacy name reads the channel whose bytes Painter wrote (24 pairings). The 6 refused compilations are the case-only probe and the two P6 probes, in both recordings.
   - `test_luma_probe_exact`: P5's luma and the channel's RGB on s0, 0 differing values on r1 and r2.
   - The 165-step comparison of decision 085 stays equal.
7. **Recording R-091** (requested, for the agent that owns Painter) covers the cases still refused:
   - srcChannel A at partial coverage;
   - a renamed set's `$sceneMaterial`;
   - mesh and project names with two dots;
   - a group with both an empty and a non-empty wildcard, and a stray `)`;
   - three equal paths, and equal paths from two exportList entries and from two stacks of a layered set;
   - the case-only collision with the map order reversed;
   - an export mixing an `export_error` with written files;
   - undocumented keys in channels, exportList entries, filters, parameters and presets;
   - black mixed with white, and other present and absent mixes.

## Alternatives Considered

- **A dry run that reproduces Painter's list** (C1). Rejected: it would name files the export never writes, against item 3.5. Painter's list for absent documentMaps is not recorded either. The plan keeps what that list needs.
- **Lifting the whole group rule, any undocumented key and every present and absent mix.** Rejected by the panel's narrowing: one recorded shape each.

## Consequences

- Configurations using the recorded probe behaviours now compile to exactly Painter's file set. The unrecorded neighbours fail before any write, naming R-091.
- Phase1.16 and phase1.17 must call `CheckExportable` before writing.
- Phase1.16 inherits three writer facts from these goldens:
  - Painter 12.1.5 writes an sRGB8 channel at 16 bits as the encode of its linear operand, not as the operand (P5);
  - an all-opaque alpha is dropped (P6 and the converted maps);
  - EXR 32f values are not clamped.
