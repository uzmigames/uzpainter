# Proposal: phase1.15_export-plan-compiler

## Why
The Assets3D scripts call `export_project_textures(json_config)` with Painter's dictionary; UzPainter must accept it verbatim, compile it into a typed plan before any GPU work, reject unknown identifiers with the valid alternatives (the pipeline's `Mixed_AO` crashed Painter; the documented name is `AO_Mixed`), check naming collisions, and expose the plan as a dry run (EXP-01, EXP-03, EXP-04, EXP-09, INT-13, QG-03). Implements D7 (decision 009: Painter-compatible JSON compiled into a validated plan) with owner answer Q10 (decision 023) in `docs/architecture/08-export.md` §1–§6; Phase 1 covers the plan compiler, padding/resize/dither, PNG8/16, EXR, the PBR, Blender and inline presets, generation-directory publication and receipts, while the Unreal, glTF and UzEngine presets and the TGA/BMP/JPEG/DDS writers follow in P3-UNREAL and P3-UZE. Child of `phase1.18_export-engine` (P1-EXPORT), covering `docs/architecture/08-export.md` §1, §2 and §6.

## What Changes
- `src/export/config.{h,cpp}`: parser for `exportPath`, `exportShaderParams`, `defaultExportPreset` (name or `resource://` URL), `exportPresets[].{name, maps[].{fileName, channels[].{destChannel, srcChannel, srcMapType, srcMapName}, parameters}}`, `exportList[].{rootPath, filter.{outputMaps, uvTiles}, exportPreset}`, `exportParameters[].{filter.{dataPaths, outputMaps, uvTiles}, parameters.{fileFormat, bitDepth, dithering, sizeLog2, paddingAlgorithm, dilationDistance}}`.
- `src/export/plan.{h,cpp}`: wildcard expansion (`$project $mesh $textureSet $sceneMaterial $colorSpace $udim $uvTileName`, `( … )` optional groups); `srcMapType ∈ {documentMap, meshMap, virtualMap, defaultMap}`; filter semantics (`{}` matches all, `{"dataPaths": []}` matches nothing); resolution order preset parameters then `exportParameters` in list order; every parameter defined after resolution or the config is invalid; naming collision checks; typed plan of every output file with resolved sources, parameters, size, naming and target format; plan hash.
- Unknown identifiers rejected with the valid alternatives; formats not in v1 (TIFF, PSD, WebP, J2K/JP2, PGM, JNG, `sbsar`) and formats delivered by later packages (TGA, BMP, JPEG, DDS) raise before anything is written.
- `src/export/virtual_maps.{h,cpp}`: `Normal_OpenGL`/`Normal_DirectX` from `phase1.12_compositor-height-normal` (tag `combined`); geometry-only pass-through through `meshMap normal_base` (tag `geometry_only`); `AO_Mixed` and the other documented virtual maps (`Diffuse`, `Specular`, `Glossiness`, `Glossiness2`, `Unity4Diff`, `Unity4Gloss`, `reflection`, `1/ior`, `f0`, `View_2D`) defined from Adobe's public output-template documentation with operators fitted in Tier 0 (`parity/semantics/virtual-maps.json`); a virtual map whose golden does not yet pass stays `release-gap` and raises before writing.
- Diagnostic sources (channels, mesh maps, masks, isolated layers, unlit BaseColor, difference maps) addressable by the plan (EXP-04).
- `list_project_textures(json_config)` and `uzpainter.export.plan(config)` return the plan (dry run).

## Dependencies
- DAG input of the parent: `phase1.14_compositor-core` (virtual normal sources from `phase1.12_compositor-height-normal`, diagnostics from `phase1.13_compositor-diagnostics`).
- Parent: `phase1.18_export-engine`. Siblings building on this child: `phase1.16_export-processing-encoders`, `phase1.17_export-presets`, `phase1.17_export-publication-receipts`.

## Acceptance
Plan tests pass (EXP-03 naming and collisions, wildcard and filter semantics, resolution order, invalid configurations, unknown identifiers, refused formats) and the Tier 0 virtual-map goldens for the virtual maps marked `supported` are exact. Goldens are private and compared locally on the owner's machine (decision 028; the local run report is the evidence; hosted CI skips these tests with an explicit reason); only fitted operators, their public sources and residuals are published under `parity/semantics/` (`docs/architecture/14-parity-testing.md` §6).

## Impact
- Affected specs: `export`
- Affected code: `src/export/config.*`, `src/export/plan.*`, `src/export/virtual_maps.*`, `parity/semantics/virtual-maps.json`, `tests/export/`
- Breaking change: NO
- User benefit: Pipeline export configurations run unchanged, and every mistake surfaces before a single file is written.
