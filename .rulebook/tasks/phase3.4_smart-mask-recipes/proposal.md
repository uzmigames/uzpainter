# Proposal: phase3.4_smart-mask-recipes

## Why
MAT-02 requires edge-wear, cavity-dirt and ground-dirt/dust masks with Painter's parameters, MAT-04 requires the starter assets of locked and delivered recipes to evaluate identically through UzPainter's own certified implementations, and CLR-06 keeps Painter asset names internal (`docs/prd.md`, decision 002). Painter's smart masks are structures of layers and effects whose observed trees must stay private (publication rule, Astra F01). This child of P3-SMART (`phase3.6_smart-presets-projections`) implements the smart-mask part of `docs/architecture/05-procedural-content.md` §3 and the insertion rules of `docs/architecture/04-layer-stack-and-compositing.md` §1 (D3, D4).

## What Changes
- Independently designed UzmiGames smart-mask recipes expressed in the documented layer/effect model (generator, levels and fill effect lists over the certified families), covering the roles of the masks the recipes use; Painter names Dirt Cavities, Edge Dirty Cracks, Edges Uber, Ground Dirt, Dust Dirty and Occlusion Strong exist only as internal compatibility aliases.
- `insert_smart_mask` expansion into an effect list, allowed only in mask stacks, built detached and attached in one transaction (`docs/architecture/03-project-model.md`), each carrying `preset_ref {asset@version}` for provenance only.
- Provenance record per recipe, including the provenance record of every family and resource it uses.
- Alias resolution: on the owner's machine an alias resolves to the private observed structure for migration and testing; where none is available it raises `UnsupportedProcedural{asset, reason: "private preset unavailable"}`; it never substitutes a UzmiGames recipe.
- Publication guard: Adobe preset trees, parameter collections and serialized readbacks (`get_root_layer_nodes`, `content_effects`, `mask_effects`, `get_source`, `get_parameters`) stay in the private store and are rejected from the repository.
- Tier 2a manifests per recipe under `parity/manifests/`.

## Dependencies
- Prerequisites: `phase3.3_procedural-families` (P3-PROC, the DAG input of P3-SMART).
- Parent: `phase3.6_smart-presets-projections`. Unblocks `phase3.5_smart-material-recipes`.

## Acceptance
Every shipped smart-mask recipe passes Tier 2a: the same recipe rebuilt in Painter through the documented API produces equal outputs, or the difference is an owner-approved exception; insertion rules, alias resolution and the publication guard pass their tests.

## Impact
- Affected specs: smart-presets
- Affected code: smart-mask recipe library, `insert_smart_mask`, alias resolution, repository guard rules, Tier 2a manifests
- Breaking change: NO
- User benefit: publishable smart masks with Painter-equal output and clean provenance
