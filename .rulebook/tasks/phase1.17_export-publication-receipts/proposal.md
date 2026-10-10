# Proposal: phase1.17_export-publication-receipts

## Why
A delivery must be atomic and verified: files and receipt go to a new generation directory published by one atomic pointer update, the last delivery stays selected on failure, the host never dies, fixed-name consumers read one complete generation through an adapter or a publication lock, and every export carries a receipt with revision, profiles, hashes, normal tags and the manifest `exportacao` block (EXP-06, EXP-09, EXP-10, INT-21, QG-03, ARC-11). Implements D7 (decision 009: Painter-compatible JSON compiled into a validated plan) with owner answer Q10 (decision 023) in `docs/architecture/08-export.md` §1–§6; Phase 1 covers the plan compiler, padding/resize/dither, PNG8/16, EXR, the PBR, Blender and inline presets, generation-directory publication and receipts, while the Unreal, glTF and UzEngine presets and the TGA/BMP/JPEG/DDS writers follow in P3-UNREAL and P3-UZE. Child of `phase1.18_export-engine` (P1-EXPORT), covering `docs/architecture/08-export.md` §5.

## What Changes
- `src/export/publish.{h,cpp}`: every file and the receipt written into a new generation directory under `exportPath`, flushed and verified against the plan (size and SHA-256 per file), then published by one atomic durable update of `current.json` (temporary file, flush, rename); failure at any step leaves the previous generation selected; `uzpainter export --recover` lists and removes incomplete generations.
- `src/export/fixed_names.{h,cpp}`: journalled fixed-name copies `{generation, files[], copied[]}`, a delivery adapter that pins one published generation for a fixed-name consumer, and a coordinated publication lock that completes recovery before consumption and excludes writers for the entire read; staging names are never advertised as a committed delivery.
- `src/export/receipt.{h,cpp}` + `src/export/schema/receipt.schema.json`: `{revision, generation, evaluator_profile, compat_profile, app_version, build, resource_hashes, plan hash, per file: path, bytes, sha256, format, bit depth, colour space, size, preset, channel mapping, normal tag (geometry_only|combined + relief round), consumer gaps}` plus the manifest `exportacao` block (`fontes`, `saidas`, `momento`, `preset`, `mapas`, `comparacao`, `evidencias`, `pendencias`).
- Test-only fault hooks between every publication step, excluded from release builds.

## Dependencies
- DAG input of the parent: `phase1.14_compositor-core`.
- Sibling prerequisites: `phase1.15_export-plan-compiler`, `phase1.16_export-processing-encoders`.
- Parent: `phase1.18_export-engine`. Consumers: `phase1.23_pyapi-pipeline-adapter` (fixed-name delivery for the pipeline scripts), later the INT-11 consumer fixtures.

## Acceptance
Publication interruption tests pass: interrupting between every step (each file, the receipt, the pointer, each fixed-name copy) leaves a consumer reading the pointer with the old or the new complete generation; recovery completes or discards the interrupted one; after interrupting each fixed-name copy, invoking the fixed-name consumer through its adapter immediately consumes one complete generation or fails before consumption. Receipt schema tests pass.

## Impact
- Affected specs: `export`
- Affected code: `src/export/publish.*`, `src/export/fixed_names.*`, `src/export/receipt.*`, `src/export/schema/receipt.schema.json`, CLI `uzpainter export --recover`, `tests/export/`
- Breaking change: NO
- User benefit: Consumers always see one complete, verified delivery, and every map carries the evidence of how it was produced.
