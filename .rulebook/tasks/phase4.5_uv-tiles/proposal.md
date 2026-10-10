# Proposal: phase4.5_uv-tiles

## Why
OWN-01 (`docs/prd.md`) requires every output-affecting Painter capability to be `supported` or an explicit gap, and names UV tiles among the gaps that stay visible until they are implemented; PRJ-02 limits v1 to a single 0–1 tile per set and records UV tiles as a release gap. Owner decision 019 (Q5, `docs/open-questions.md`) keeps "UV tiles until Phase 4" visible in the capability manifest, and `docs/architecture/10-python-api.md` §3 lists the UV-tile workflow as a `release-gap` that blocks G5 unless implemented or covered by an owner scope decision. The data model was built for this: `docs/architecture/03-project-model.md` §1–§2 carries `workflow (Default|UVTile)` and `uv_tiles[]`; `docs/architecture/12-mesh-import.md` §6 keeps the `TexturingMesh` and raster buffers tile-indexed so `UVTile`/`TextureSetPerUVTile` can be added without a data-model change; `docs/architecture/04-layer-stack-and-compositing.md` §1 has the `UVTile` geometry-mask type; `docs/architecture/09-project-file-format.md` §1 keeps the UV-tile identity on every raster plane; and `docs/architecture/08-export.md` §1 accepts `filter.uvTiles` and the `$udim`/`$uvTileName` wildcards. This is DAG node P4-TILES (`docs/dag.md`), implementing D3 and D11.

This task is the parent integration and acceptance task. Per the DAG task decomposition rule the work is split into three independently testable child tasks: the tile workflow itself, per-tile resolution, and tile export filters.

## What Changes
- `phase4.3_tiles-workflow`: the `UVTile` project workflow (and the `TextureSetPerUVTile` workflow named in `12-mesh-import.md` §6) — mesh import that accepts UVs outside 0–1 and records the tile list per set (`uv_tiles[]`), UV-space rasterisation per tile (`12-…` §5), evaluation per `(stack, channel, UV tile)` (`04-…` §2), the `UVTile` geometry mask, raster planes keyed by UV tile (`09-…` §1), the documented UV-tile symbols in `uzpainter` and the `substance_painter` facade, and a tile-aware recipe dump.
- `phase4.4_tiles-per-tile-resolution`: a resolution per UV tile with the set resolution as default, VRAM admission per tile (`03-…` §2, `13-engine-integration.md` §6), per-tile plane sizes, readback through the documented API, save/reopen.
- `phase4.4_tiles-export-filters`: `filter.uvTiles` in `exportList` and `exportParameters`, the `$udim` and `$uvTileName` wildcards with `( … )` optional groups, per-tile naming collision checks in the plan compiler, and tile-aware receipts (`08-…` §1, §5).
- Parent integration: the UzmiGames-authored UDIM fixture (mesh, recipe and instruction sequence under `parity/manifests/`; Painter goldens recorded privately), the Tier 0/1 report on it in `parity/reports/phase4/`, and the capability manifest moving the UV-tile workflow from `release-gap` to `supported` with its tier evidence.

## Dependencies
- DAG inputs: `phase4.2_remaining-nodes` (P4-NODES).
- Children (mandatory): `phase4.3_tiles-workflow` first; then `phase4.4_tiles-per-tile-resolution` and `phase4.4_tiles-export-filters`, which are independent of each other.
- Downstream: `phase4.6_gate-g4` (G4).

## Acceptance
DAG gate of P4-TILES: Tier 0/1 on a UDIM fixture. In substance: every child task is accepted; on the UzmiGames-authored UDIM fixture the Tier 0 tile-semantics goldens (per-tile evaluation, `UVTile` geometry mask, per-tile resolution, export filters and naming) are exact, and the Tier 1 recipe rebuilt in both tools yields every exported map of every tile equal to the private Painter goldens and byte-stable across two runs (`docs/architecture/14-parity-testing.md` §3); the capability manifest lists the UV-tile workflow as `supported` with that evidence, or keeps any unproven part as an explicit gap.

## Impact
- Affected specs: `uv-tiles`
- Affected code: mesh import (tile list, per-tile UV raster), document model (`workflow`, `uv_tiles[]`), compositor (per-tile evaluation, geometry mask), project store (planes per tile), exporter (tile filters, wildcards), `uzpainter`/`substance_painter` packages, capability manifest, `parity/manifests/`, `parity/reports/phase4/`
- Breaking change: NO (the `Default` workflow is unchanged)
- User benefit: UDIM assets can be authored and exported with Painter's tile semantics, closing a listed release gap
