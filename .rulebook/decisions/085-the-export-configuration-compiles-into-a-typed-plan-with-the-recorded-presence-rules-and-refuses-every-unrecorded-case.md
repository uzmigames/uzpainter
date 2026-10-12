# 85. The export configuration compiles into a typed plan with the recorded presence rules and refuses every unrecorded case

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.15_export-plan-compiler, phase1.16_export-processing-encoders, phase1.17_export-publication-receipts, phase1.19_pyapi-native-module

## Context

`phase1.15_export-plan-compiler` compiles Painter's `export_project_textures(json_config)` dictionary into a typed plan before any GPU work. The plan holds every output file with its sources, parameters, size, name and format, and a plan hash. It is also the dry run (`list_project_textures`).

Painter's documentation (export.html, "Full json_config dict possibilities") gives:

- the keys, the source names of each `srcMapType` and the wildcards;
- the filter rule: `{}` matches all, `{"dataPaths": []}` matches nothing;
- the parameter order: preset map parameters, then the `exportParameters` rules in list order. A parameter still undefined after that makes the configuration invalid.

The documentation leaves open when Painter skips a map, and what it does with undocumented keys, unusual names, collisions and channel mixes.

Measured facts:

- **Dry run equals Painter's files.** The compiler planned every export step of every recorded golden of the current envelope: 104 goldens and 167 steps over 26 project templates, using the recorder's documented `json_config`. Before decision 086, on 166 steps the planned files equalled the files Painter wrote, with 0 differing. The remaining step, a `meshMap position`, is refused, naming phase1.16. After decision 086, the `ao-mixed` step is also refused (R-086), and the other 165 steps still equal Painter's files.
- **Presence rules behind that result.** A `documentMap` whose channel the stack lacks makes its map absent: Painter writes no file. A legacy name reads its OpenPBR member when the stack lacks the legacy one: roughness → SpecularRoughness, metallic → BaseMetalness, emissive → EmissionColor, anisotropylevel → SpecularRoughnessAnisotropy, scattering → SubsurfaceRadiusScale. A map made only of `defaultMap white` is absent.
- **Scope.** This task writes no file; the writers arrive in phase1.16. The `uzpainter.export` module, including `export.plan(config)`, is phase1.19 item 2.7, and that task has phase1.18 (the export parent of this task) as its prerequisite. Phase1.12 is lifting several evaluator limits of the combined normal on another branch.

The model panel was consulted under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| C1 Undocumented keys refused with NotYetSupported, not ignored; unknown names a ValueError listing the alternatives, `AO_Mixed` first for `Mixed_AO`; formats not in v1 and later-package formats NotYetSupported at parse time, naming the owner | AGREE x1, PARTLY x2: the facts did not show the error paths; they are tested (`test_identifiers_are_checked`, `test_mixed_ao_is_rejected_with_ao_mixed`, `test_refused_formats_raise_before_any_file`) |
| C2 The presence rules adopted on the 166-step evidence; every uncovered combination refused, naming recording request R-085 | AGREE x2, PARTLY x1: file-set equality proves presence, not which source supplies the pixels |
| C3 The plan does not duplicate the evaluator's limits of the combined normal; the evaluator refuses them when the export evaluates, and every file is evaluated before any is written | AGREE x1, PARTLY x2: the evaluate-before-write rule is a downstream obligation; dry-run fidelity holds modulo those refusals |
| C4 Item 2.6 is met by the native entry points; the Python binding is phase1.19 item 2.7 | AGREE x1, PARTLY x2: record the scope split explicitly; the native test executable is not the Python API |
| C5 Item 3.5 is met by the Painter-side equality plus evaluation of the planned files | DISAGREE x1, PARTLY x2: UzPainter's own written files cannot be compared until writers exist |

## Decision

1. **Parsing** (`src/export/config.{h,cpp}`).
   - The dictionary is read verbatim; only the documented keys are accepted. An undocumented key raises `NotYetSupported`, listing the documented keys nearest first. `srcPath` is accepted only when empty, as Painter's own `list_output_maps` emits it.
   - Unknown names, letters, formats, depths and paddings raise `ValueError` with the valid alternatives, nearest first: shared words, then edit distance.
   - TIFF, PSD, WebP, J2K/JP2, PGM, JNG and sbsar (not in v1) and TGA, BMP, JPEG and DDS (owner `phase3.2_unreal-ue56-packed-preset`) raise `NotYetSupported` at parse time.
   - Shelf presets (`resource://`) belong to phase1.17_export-presets, and `exportShaderParams: true` to phase2.3.
2. **Plan semantics** (`src/export/plan.{h,cpp}`, `src/export/EXPORT.md` §2). The documented rules apply, plus the presence rules above. These cases are refused with `NotYetSupported` naming recording **R-085** (its probes are in `parity/reports/phase1/export-plan-compiler.md` §4):
   - a present source mixed with an absent one;
   - a `black`-only map;
   - an unbound mesh map;
   - the legacy aliases never observed;
   - srcChannel L of a three-component source, and srcChannel A of any source;
   - `$mesh`, `$project` and `$sceneMaterial`;
   - an empty wildcard outside a `( … )` group, a group without a wildcard, and nested groups;
   - `uvTiles` filters on a project without UV tiles;
   - two files whose paths are equal ignoring case.

   OCIO colour management and the UV-tile workflow are release gaps.
3. **The evaluator owns its limits.** The plan checks only what needs no evaluation. The combined normal's set-size and Normal-mesh-map limits stay with the evaluator, which raises `unsupported_source` (`NotYetSupported`, decision 082).
   - **Contract for phase1.16 and phase1.17:** the export evaluates every planned file before it writes any, so this refusal also precedes every write.
   - Until then, the dry run lists the files a configuration names. The export may still refuse those files at evaluation.
4. **Plan hash and dry-run shape.** The plan hash is the SHA-256 of the canonical plan JSON (`uzpainter/export-plan/1`) without its hash. The dry run is `ListProjectTextures` / `FilesByStack`, in Painter's `(texture set, stack) → files` shape.
5. **Scope split of item 2.6.** This task delivers the dry run natively: `CompilePlan`, `PlanJson`, `ListProjectTextures`, `EvaluateFileOn`, compiled into `UzPainter.exe` and exercised by `uzp-export-tests`. The Python surface (`uzpainter.export.plan`, `substance_painter.export.list_project_textures`) is phase1.19 item 2.7, which depends on this task's parent, so this task cannot host it.
6. **Item 3.5 stays open.**
   - Proven here: Painter's side. The dry run equals Painter's written files on every compared step, and every planned file of the virtual-map goldens evaluates.
   - Still needed: equality between UzPainter's own dry run and its own written files. That needs the phase1.16 writers, and phase1.17's receipts must check it against the files actually written.

## Alternatives Considered

- Ignoring undocumented keys as Painter might. Rejected: not recorded, and a silent no-op is forbidden.
- Duplicating phase1.12's size and mesh-map refusals at plan time. Rejected: they drift as phase1.12 lifts them; the evaluator is the single owner.
- Checking 2.6 and 3.5 on the native and Painter-side evidence alone. Rejected for 3.5 by the panel. For 2.6 the split is recorded instead, because the Python module's task depends on this one.

## Consequences

- Configurations that use only the recorded semantics compile to the exact file set Painter writes. Everything else fails before any write, naming the recording or task that lifts it.
- Phase1.16 and phase1.17 inherit the evaluate-before-write contract and the comparison of UzPainter's own dry run with its written files.
- Recording R-085 is needed to lift the refused cases.
