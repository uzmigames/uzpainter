# Proposal: phase3.5_smart-material-recipes

## Why
OWN-01 lists smart materials among the Painter functionality UzPainter must provide, LAY-11 requires portable smart-material folders with identical parameters and resources, INT-02 requires MCP tools for smart materials, and MAT-04 with CLR-01…CLR-06 require clean-room presets (`docs/prd.md`). Painter's smart materials are Adobe content that UzPainter never ships (`docs/licensing-and-clean-room.md` rules 3 and 7). This child of P3-SMART (`phase3.6_smart-presets-projections`) implements the smart-material part of D4 (`docs/architecture/05-procedural-content.md` §3, publication rule) on the layer model of D3 (`docs/architecture/04-layer-stack-and-compositing.md` §1) and the composite-operation rule of `docs/architecture/03-project-model.md`.

## What Changes
- Independently designed UzmiGames smart-material recipes in the documented layer/effect model, shipped under `assets/` with a provenance record for each recipe and for every family and resource it uses; they reference only certified P3-PROC families, projections from `phase3.4_smart-projections` and smart masks from `phase3.4_smart-mask-recipes`.
- `insert_smart_material` (native `uzpainter` API and facade): expands a recipe to an editable group with `preset_ref {asset@version}` kept for provenance only, built detached and attached in one transaction; allowed only in the hierarchy, as Painter's insertion rules state.
- MCP `smart_material_insert` and the `apply_smart {config_json, texture_set}` recipe tool with the `painter_layer_stack.py smart` semantics (`docs/architecture/11-mcp-server.md`).
- Portable smart-material folders (LAY-11): `smart_export {uid, kind: material, path}` writes the group's recipe, its resources by content hash and the provenance records; inserting the folder into another project reproduces identical parameters, resources and outputs.
- Compatibility aliases for Painter smart-material names (Leather Damaged, Bronze Armor, the recorded forged-iron recipe): on the owner's machine they resolve to the private observed structure for migration and testing; elsewhere they raise `UnsupportedProcedural{asset, reason: "private preset unavailable"}`; a UzmiGames recipe is never substituted.
- Tier 2a manifests under `parity/manifests/` for every shipped recipe (each rebuilt in Painter through the documented API; private golden hashes).

## Dependencies
- Prerequisites: `phase3.4_smart-mask-recipes`, `phase3.4_smart-projections`.
- Parent: `phase3.6_smart-presets-projections`.

## Acceptance
Every shipped smart-material recipe passes Tier 2a: the same recipe rebuilt in Painter through the documented API produces equal outputs over the `05-…` §6 matrix; a non-zero residual passes only through an owner-approved exception (decision 017). The portable-folder round trip yields identical parameters, resources and outputs. Painter names never resolve to a substitute.

## Impact
- Affected specs: smart-presets
- Affected code: smart-material expansion, `apply_smart`, MCP smart tools, portable folder export/import, `assets/` recipes with provenance, alias table entries
- Breaking change: NO
- User benefit: reusable, portable smart materials with proven output parity and no Adobe content
