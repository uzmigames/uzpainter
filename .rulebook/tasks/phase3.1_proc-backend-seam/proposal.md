# Proposal: phase3.1_proc-backend-seam

## Why
ARC-05 requires a procedural backend seam with per-asset parity status and no silent substitution of a similar asset; RES-04 requires procedural asset versions pinned inside the project; CLR-06 keeps Painter asset names as internal compatibility aliases only; MAT-03 asks for a generic noise library (`docs/prd.md`). Every procedural family and the snapshot backend plug into this seam. This child of P3-PROC (`phase3.3_procedural-families`) implements `docs/architecture/05-procedural-content.md` §2, §3 (provenance, parity status, aliases), §5, §6 (certification harness) and §7 (D4). It is split out beyond the DAG rule's examples because the seam, the shared kernel library and the certification harness are one independently testable artifact used by five sibling children.

## What Changes
- `ProceduralRequest` and `IProceduralBackend { status; canEvaluate; evaluate }` with `ParityStatus` = `exact` | `calibrated{max |Δ|, mean |Δ|, p99 |Δ|, corpus id}` | `unavailable`; backend order `SnapshotBackend` then `HlslBackend`; `UnsupportedProcedural{asset, reason}` raised before any mutation; no Adobe runtime adapter, none reserved.
- `HlslBackend` host: family registration, kernels generated as HLSL and compiled through the render core (DXIL/SPIR-V, `precise`, no fast-math), cached by content hash; shared primitive library written from public literature: Perlin 1985/2002, simplex and Worley noise, fBm, standard morphological and blur operators.
- Asset library: `uzasset://<family>/<id>@<version>` resources pinned by the project (`docs/architecture/03-project-model.md`); one provenance record per family (public sources, author, calibration corpus id, residuals); internal compatibility alias table so `resource.search` resolves Painter names; `uzpainter assets list --parity`.
- Importing a `.sbsar` raises `UnsupportedProcedural{reason: "no runtime"}`.
- `SourceSubstance` facade semantics (§7): `get/set_parameters` (booleans as int), `get_properties`, `get_preset_list`/`apply_preset`, `image_inputs` with `get/set/reset/remove_source` (bitmap, colour, anchor), `image_outputs`, `output_mapping`, `active_output`, `mask_output`, `resolution: ResolutionOverride{mode, value, log2_offset}` (power of two in [128, 4096]; `Auto` follows the texture-set resolution; raises for sources used by a Filter effect); mesh maps bound by usage automatically; a missing or invalid mesh map fails evaluation loudly.
- Tier 2a certification harness (§6) driving `parity/manifests/` and the comparison tool: 3 meshes (unit sphere, bevelled cube, hat v6 low with its mesh maps) × {1024, 2048, 4096} × {defaults, recipe sets, two boundary sets} × {recorded seed, one other}; max/mean/p99 |Δ| and affected-texel counts; a non-zero residual is a candidate exception, never a pass; a missing blob is `oracle_unavailable`.

## Dependencies
- Prerequisites: `phase0.6_procedural-feasibility`, `phase2.10_pilot-tunic-recovery` (DAG inputs of P3-PROC).
- Parent: `phase3.3_procedural-families`. Unblocks `phase3.2_proc-snapshot-backend`, `phase3.2_proc-generator-families`, `phase3.2_proc-grunge-families`, `phase3.2_proc-filter-families`, `phase3.2_proc-material-families`.

## Acceptance
No substitution and `UnsupportedProcedural` before mutation proven by tests; `SourceSubstance` API probes exact against Tier 0 goldens; pinned asset versions reproduce evaluation on reopen; the harness reports a seeded known residual correctly and never passes it.

## Impact
- Affected specs: procedural
- Affected code: procedural seam, `HlslBackend` host and primitive kernels, asset library, alias table, `uzpainter assets` CLI, `SourceSubstance` facade, Tier 2a harness
- Breaking change: NO
- User benefit: one honest entry point for procedurals that never swaps assets silently
