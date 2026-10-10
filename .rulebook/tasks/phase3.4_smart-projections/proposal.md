# Proposal: phase3.4_smart-projections

## Why
MAT-01 (triplanar projection with physical-unit scale and normal-weighted blending) and PRJ-07 (physical units preserved, effective projection units recorded), both accepted by Tier 0 projection goldens (`docs/prd.md`), need the 3D projection modes and symmetry that Painter documents for fill layers and fill effects (`layerstack\layereffect\fill.html`). Phase 1 delivered only the UV projection (`phase1.14_compositor-core`). This child of P3-SMART (`phase3.6_smart-presets-projections`) implements the projection and symmetry part of D3 in `docs/architecture/04-layer-stack-and-compositing.md` §5, with the units rule of `docs/architecture/12-mesh-import.md` §3; smart recipes that use triplanar fills (P3-SMART recipes, D4) depend on it.

## What Changes
- Compositor projection kernels (generated HLSL on the render core, `precise` arithmetic): `Triplanar` (hardness, 3D transform, normal-weighted blend), `Planar`, `Spherical` and `Cylindrical` (culling, crop, 3D transform), evaluated from the UV raster's position and normal maps.
- Mirror and radial symmetry for the 3D projections, as documented for fill projections.
- Physical-size scale modes `MaterialPhysicalSize` and `CustomPhysicalSize` using the stored mesh `units {source, scale_to_internal}`; the semantics of `projection_3d.scale` fitted from Tier 0 goldens, not assumed to be metres; the effective scale written into every evaluation and export receipt (PRJ-07).
- Fitted projection semantics (formula, public source, residual; numbers only) under `parity/semantics/projections.json`.
- Projection and symmetry parameters through the documented facade fill API, the native `uzpainter` API and the MCP `fill_set {uid, projection?, symmetry?}` typed tool.
- Tier 0 projection manifests under `parity/manifests/` (plane, sphere, bevelled cube; hashes of the private goldens).
- Capability manifest: the four 3D projections and both symmetry modes `supported` once their goldens pass; `Warp` and `UVSetToUVSet` kept as release gaps owned by P4-NODES (`phase4.2_remaining-nodes`).

## Dependencies
- Prerequisites: `phase3.3_procedural-families` (P3-PROC, the DAG input of P3-SMART).
- Parent: `phase3.6_smart-presets-projections`. Unblocks `phase3.5_smart-material-recipes`.

## Acceptance
Tier 0 projection goldens exact: triplanar hardness and scale, planar, spherical and cylindrical projections, mirror and radial symmetry and both physical-size scale modes on the synthetic meshes equal Painter's decoded outputs at native precision; any difference passes only through an owner-approved exception (decision 017). `Warp` and `UVSetToUVSet` are reported as gaps, not claimed.

## Impact
- Affected specs: smart-presets
- Affected code: compositor projection and symmetry kernels, fill projection parameters in the document model, facade and MCP `fill_set`, Tier 0 projection manifests, `parity/semantics/projections.json`
- Breaking change: NO
- User benefit: triplanar and other 3D projections with physical units, needed by smart materials and the bracer recipes
