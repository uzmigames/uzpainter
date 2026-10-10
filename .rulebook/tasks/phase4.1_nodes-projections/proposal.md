# Proposal: phase4.1_nodes-projections

## Why
`docs/architecture/04-layer-stack-and-compositing.md` §5 lists the documented fill projections; `Warp` and `UVSetToUVSet` are release gaps "until their goldens exist", and `docs/architecture/10-python-api.md` §3 makes "warp and UV-set-to-UV-set projections" a `release-gap` raising `NotYetSupported`. Owner decision 019 (Q5, `docs/open-questions.md`) keeps "warp/UV-set projection until Phase 4" visible in the capability manifest, and OWN-01 (`docs/prd.md`) requires each to become `supported` or remain an explicit gap. `phase3.4_smart-projections` delivered the UV, triplanar, planar, spherical and cylindrical modes with mirror and radial symmetry and explicitly left these two modes to P4-NODES. `UVSetToUVSet` needs the additional UV sets that `docs/architecture/12-mesh-import.md` §2 records at import but does not yet use. Child of P4-NODES (`phase4.2_remaining-nodes`) per the DAG task decomposition rule, implementing D3.

## What Changes
- **Additional UV sets**: the mesh import keeps every recorded UV set as tile-indexed data beside `uv0` (OBJ, FBX through ufbx, glTF `TEXCOORD_n`), included in the mesh hashes and certificate; the UV-space raster pass can rasterise a source UV set into the target set's space.
- **`UVSetToUVSet` projection**: content authored in one UV set resampled into the texturing UV set with the documented parameters and the Tier 0 fitted filter (`04-…` §4 manual filtering).
- **`Warp` projection**: the documented warp parameters of the fill projection API, evaluated from the UV raster's position and normal maps; semantics fitted from Tier 0 goldens.
- **Symmetry**: mirror and radial symmetry from `phase3.4_smart-projections` applied to these modes wherever the documented parameters allow it; a combination without an exact golden stays an explicit gap.
- **Semantics record**: formulas, public sources and residuals added to `parity/semantics/projections.json` (numbers only).
- **API**: both modes in `fill_set` for `uzpainter`, the `substance_painter` facade (documented symbols only, CLR-03) and the MCP stack family; set→get readback; the `NotYetSupported` path removed only for the combinations proven by goldens.

## Dependencies
- DAG input (through the parent): `phase2.10_pilot-tunic-recovery`.
- Child-level prerequisite: `phase3.4_smart-projections` (3D projection and symmetry kernels, projection parameter model).
- Delivered upstream and used here: `phase1.7_mesh-loader`, `phase1.4_render-core-layer` (UV raster).
- Parent: `phase4.2_remaining-nodes`. `phase4.1_nodes-paint-layers` can project bitmaps with these modes once this child is accepted.

## Acceptance
Part of the P4-NODES gate (Tier 0 extended; manifest updated). This child is accepted when the Tier 0 goldens for `Warp` and `UVSetToUVSet` (UzmiGames-authored meshes with two UV sets; warp parameter sweeps; symmetry combinations where documented) are exact on the self-hosted GPU runner or covered by an owner-approved exception, Phase 1–3 projection goldens are unchanged, and the capability manifest shows both modes `supported` with evidence or as explicit gaps.

## Impact
- Affected specs: `compositor` (warp and UV-set projections)
- Affected code: mesh import (secondary UV sets, hashes, certificate), UV raster pass, projection kernels, fill projection model, `uzpainter`/`substance_painter` packages, MCP `fill_set`, capability manifest, `parity/semantics/projections.json`
- Breaking change: NO (existing mesh hashes gain secondary-UV entries only for meshes that have them)
- User benefit: the remaining documented projection modes are available with Painter's results
