## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase4.2_remaining-nodes` (parent input); `phase1.7_mesh-loader`, `phase1.14_compositor-core`, `phase1.8_project-store` and `phase1.24_python-api-facade` delivered

## 2. Implementation
- [ ] 2.1 Project settings accept `UVTile` and `TextureSetPerUVTile`; `Default` keeps rejecting UVs outside 0–1 with the tile list
- [ ] 2.2 Mesh import under a tile workflow: UDIM tile assignment per corner, `uv_tiles[]` per set (one set per tile under `TextureSetPerUVTile`), certificate counts per tile and a flag for triangles spanning more than one tile
- [ ] 2.3 UV-space raster pass per `(set, UV tile)` in tile-local coordinates
- [ ] 2.4 Compositor DAG and cache keyed by `(stack, channel, UV tile, evaluator chunk)`; `Fill` projection per-tile matching and UV projection across tiles
- [ ] 2.5 `UVTile` geometry mask with tile inclusion lists on layers and effects
- [ ] 2.6 Paint-layer planes per UV tile (`plane.tile_u`, `plane.tile_v`) and mesh-map bindings with their UV tile; external mesh maps imported per tile
- [ ] 2.7 Documented UV-tile symbols of the `project` and `textureset` API pages in `uzpainter` and the facade, with set→get readback through freshly resolved handles
- [ ] 2.8 Recipe dump and `inspect` list tiles, per-tile planes and geometry masks; mesh reload reports added and removed tiles per set
- [ ] 2.9 Capability-manifest entries for the tile workflows with their Tier 0 evidence ids

## 3. Tests
- [ ] 3.1 Tier 0 goldens on the UDIM mesh: per-tile uniform and bitmap fills exact on the self-hosted GPU runner
- [ ] 3.2 Tier 0 golden: `UVTile` geometry mask including one tile and excluding the others
- [ ] 3.3 Tier 0 golden: `Fill` projection per-tile matching and a UV projection crossing a tile boundary
- [ ] 3.4 Tier 0 golden: a triangle spanning two tiles evaluates as in Painter and is flagged in the certificate
- [ ] 3.5 API probes: workflow and tile-list readback after set, save and reopen
- [ ] 3.6 Regression: the `Default` workflow still rejects UVs outside 0–1 and the Phase 1–3 Tier 0 corpus is unchanged
- [ ] 3.7 Store test: two paint layers on the same channel in two different UV tiles keep separate planes after save/reopen and compaction

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase4.5_uv-tiles`: tile-workflow Tier 0 goldens exact, `Default` unchanged, tile project round-trips

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
