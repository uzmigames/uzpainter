# Proposal: phase4.3_tiles-workflow

## Why
PRJ-02 (`docs/prd.md`) limits v1 to a single 0–1 tile per set and records UV tiles as a release gap; OWN-01 and owner decision 019 (Q5, `docs/open-questions.md`) keep that gap visible until Phase 4, and `docs/architecture/10-python-api.md` §3 makes the UV-tile workflow a `release-gap` that blocks G5 until it is implemented or covered by an owner scope decision. The model already reserves the place for it: `docs/architecture/03-project-model.md` §1–§2 (`workflow (Default|UVTile)`, `uv_tiles[]` with the single tile 1001 in `Default`), `docs/architecture/12-mesh-import.md` §5–§6 (tile-indexed `TexturingMesh` and UV raster buffers; `UVTile`/`TextureSetPerUVTile` addable without a data-model change), `docs/architecture/04-layer-stack-and-compositing.md` §1 (`geometry_mask {type: Mesh|UVTile}`), §2 (evaluation per stack/channel/tile) and §5 (`Fill` projection, "match per tile"), and `docs/architecture/09-project-file-format.md` §1 (each raster plane keeps its UV-tile identity, distinct from evaluator chunk coordinates). Child of P4-TILES (`phase4.5_uv-tiles`), implementing D3 and D11.

## What Changes
- **Project workflows**: `workflow` accepts `UVTile` and `TextureSetPerUVTile` in addition to `Default`; `Default` keeps rejecting UVs outside 0–1 with the tile list (`12-…` §6).
- **Mesh import under a tile workflow**: corners are assigned to UDIM tiles (`1001 + u + 10·v`); the tile list per set is recorded in `uv_tiles[]` (one texture set per tile under `TextureSetPerUVTile`); the certificate reports per-tile counts and flags triangles whose UVs span more than one tile — never repairs them; their evaluation rule is a Tier 0 item compared with Painter.
- **UV raster per tile**: the UV-space rasterisation pass (`12-…` §5) renders position, normal, tangent frame, island and material buffers per `(set, UV tile)` in tile-local coordinates.
- **Evaluation per UV tile**: the compositor DAG and its cache are keyed by `(stack, channel, UV tile, evaluator chunk)`; the `Fill` projection's per-tile matching and the UV projection across tiles follow the Tier 0 goldens.
- **`UVTile` geometry mask**: inclusion lists over tiles on layers and effects (`04-…` §1, §2 step 2).
- **Planes and mesh maps per tile**: paint-layer planes are created per UV tile (`09-…` §1 `tile_u`, `tile_v`); mesh-map bindings carry the UV tile; external mesh maps import per tile.
- **API**: the documented UV-tile symbols of Painter's public `project` and `textureset` API pages mirrored in `uzpainter` and the `substance_painter` facade (documented symbols only, CLR-03), with set→get readback; recipe dump and `inspect` list the tiles, per-tile planes and geometry masks; mesh reload reports added and removed tiles per set (`12-…` §7).
- **Capability manifest**: the workflow entries carry their Tier 0 evidence.

## Dependencies
- DAG input (through the parent): `phase4.2_remaining-nodes`.
- Delivered upstream and used here: `phase1.7_mesh-loader`, `phase1.14_compositor-core`, `phase1.8_project-store`, `phase1.24_python-api-facade`.
- Parent: `phase4.5_uv-tiles`. Children that build on this one: `phase4.4_tiles-per-tile-resolution`, `phase4.4_tiles-export-filters`.

## Acceptance
Part of the P4-TILES gate (Tier 0/1 on a UDIM fixture). This child is accepted when: the Tier 0 tile-workflow goldens on the UzmiGames-authored UDIM mesh (per-tile uniform and bitmap fills, the `UVTile` geometry mask, the `Fill` projection's per-tile matching, a triangle spanning two tiles, workflow and tile-list API readbacks) are exact against the private Painter goldens; the `Default` workflow behaves exactly as before; and a tile project survives save/reopen with identical manifests and planes.

## Impact
- Affected specs: `uv-tiles` (workflow)
- Affected code: mesh import and certificate, UV-space raster pass, document model (`workflow`, `uv_tiles[]`), compositor DAG and cache keys, geometry masks, project store (`plane.tile_u/tile_v`), `uzpainter`/`substance_painter` packages, recipe dump, capability manifest
- Breaking change: NO
- User benefit: UDIM meshes can be imported and painted with Painter's tile semantics
