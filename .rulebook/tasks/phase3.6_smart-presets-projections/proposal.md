# Proposal: phase3.6_smart-presets-projections

## Why
OWN-01 lists smart materials among the Painter functionality UzPainter must provide; LAY-11 requires portable smart-material folders with identical parameters and resources; MAT-01 and PRJ-07 require triplanar and physical-unit projections; MAT-04 and the clean-room rules CLR-01…CLR-06 require that public presets be independently designed UzmiGames recipes, never Adobe preset trees (`docs/prd.md`; `docs/licensing-and-clean-room.md` rule 7). This is DAG node P3-SMART (`docs/dag.md`), implementing D3 (`docs/architecture/04-layer-stack-and-compositing.md` §1, §5) and D4 (`docs/architecture/05-procedural-content.md` §3). It bundles independently testable artifacts (projection kernels, smart-mask recipes, smart-material recipes), so it is split under the DAG task decomposition rule; this parent is the integration and acceptance task.

## What Changes
Integration of three mandatory children (DAG Outputs of P3-SMART):
- `phase3.4_smart-projections`: `Triplanar`, `Planar`, `Spherical`, `Cylindrical` projections, mirror and radial symmetry, physical-size scale modes, Tier 0 projection goldens.
- `phase3.4_smart-mask-recipes`: independently designed UzmiGames smart-mask recipes expanding to effect lists with `preset_ref`, the internal compatibility alias table for Painter smart-mask names, Tier 2a.
- `phase3.5_smart-material-recipes`: independently designed UzmiGames smart-material recipes expanding to editable groups, `insert_smart_material`/`apply_smart`, portable smart-material folders (LAY-11), Tier 2a.
- Parent-level outputs: the P3-SMART report under `parity/reports/phase3/` (Tier 0 projection results and recipe Tier 2a results; numbers and hashes only) and the regenerated capability manifest.

## Dependencies
- DAG input: `phase3.3_procedural-families` (P3-PROC).
- Children (all mandatory): `phase3.4_smart-projections` and `phase3.4_smart-mask-recipes` (parallel), then `phase3.5_smart-material-recipes`.
- Downstream (DAG): `phase3.7_fixtures-bracers-hat5` (P3-BRACERS).

## Acceptance
DAG gate of P3-SMART: Tier 0 projection goldens exact; every shipped smart-mask and smart-material recipe passes Tier 2a (the same recipe rebuilt in Painter through the documented API produces equal outputs). A non-zero difference passes only through an owner-approved, versioned exception (decision 017). The parent closes only when all three children are accepted.

## Impact
- Affected specs: smart-presets
- Affected code: compositor projection kernels, smart preset expansion (`insert_smart_mask`, `insert_smart_material`, `apply_smart`), `assets/` smart recipes with provenance, alias table, MCP smart tools, capability manifest
- Breaking change: NO
- User benefit: smart masks, smart materials and 3D projections usable by AI clients, with output parity proven and no Adobe content shipped
