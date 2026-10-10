# Proposal: phase4.4_tiles-per-tile-resolution

## Why
P4-TILES (`docs/dag.md`) delivers per-tile resolution as part of the UV-tile workflow, a release gap under OWN-01 and owner decision 019 (Q5) until Phase 4 (`docs/architecture/10-python-api.md` §3). PRJ-03 (`docs/prd.md`) requires per-set resolutions of 2048 and 4096 (8192 SHOULD) with a VRAM admission test; `docs/architecture/03-project-model.md` §2 fixes resolutions as powers of two from 128 to 8192 checked against the VRAM budget at creation, with an explicit refusal; `docs/architecture/13-engine-integration.md` §6 derives the tile admission budget; `docs/architecture/09-project-file-format.md` §1 stores width, height and format per raster plane; `docs/architecture/08-export.md` §3 defines resize at export. Under a tile workflow a UV tile may carry its own resolution, so these rules must hold per tile. Child of P4-TILES (`phase4.5_uv-tiles`), implementing D3 and D11.

## What Changes
- **Document model**: an optional resolution per UV tile (power of two, 128–8192); the set resolution is the default; effective resolution readable per tile; recorded in the manifest and the recipe dump.
- **Admission**: the VRAM admission check runs per tile at creation and on every resolution change; a request above the budget fails explicitly before mutation.
- **Evaluation at the tile's resolution**: UV raster, evaluator chunks and mesh-map sampling at the effective tile resolution; a mesh map whose resolution differs from the tile's is resampled with the filter fitted in Tier 0 (`04-layer-stack-and-compositing.md` §4).
- **Planes on a resolution change**: paint-layer planes of the tile are resampled into new copy-on-write plane versions with the rule fitted from the Tier 0 golden; procedural content re-evaluates at the new resolution.
- **Export**: the default output size of each tile follows its effective resolution unless `sizeLog2` overrides it (`08-…` §3).
- **API**: the documented per-tile resolution symbols of Painter's public `textureset` API page mirrored in `uzpainter` and the facade, with set→get readback; capability-manifest entries with their evidence.

## Dependencies
- DAG input (through the parent): `phase4.2_remaining-nodes`.
- Prior child: `phase4.3_tiles-workflow`. Parent: `phase4.5_uv-tiles`. Independent of `phase4.4_tiles-export-filters`.

## Acceptance
Part of the P4-TILES gate (Tier 0/1 on a UDIM fixture). This child is accepted when the Tier 0 per-tile resolution goldens on the UDIM mesh are exact (tiles at different resolutions in one set; a resolution change after a bitmap was written to a paint layer; per-tile resolution readbacks), admission refuses an over-budget tile before mutation, and the effective per-tile resolutions survive save/reopen.

## Impact
- Affected specs: `uv-tiles` (per-tile resolution)
- Affected code: document model (`uv_tiles[].resolution`), VRAM admission, UV raster and compositor sizing, project store plane versions, exporter default sizing, `uzpainter`/`substance_painter` packages, capability manifest
- Breaking change: NO
- User benefit: tiles can carry the resolution their content needs, as in Painter, without silent memory failures
