## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase4.3_tiles-workflow` (and through the parent `phase4.2_remaining-nodes`); `phase1.18_export-engine` delivered

## 2. Implementation
- [ ] 2.1 Plan compiler resolves `filter.uvTiles` in `exportList` entries into one planned file per selected `(set, stack, output map, UV tile)`; unknown tiles rejected with the valid list
- [ ] 2.2 Plan compiler applies `filter.uvTiles` in `exportParameters` rules in the documented resolution order
- [ ] 2.3 `$udim` and `$uvTileName` expansion per tile, with `( … )` optional groups removed when the wildcard is empty
- [ ] 2.4 Compile-time naming collision check across tiles (EXP-03)
- [ ] 2.5 Receipts and dry run (`list_project_textures`, MCP `export`) list each file with its UV tile
- [ ] 2.6 Per-tile files published through the existing generation directory and atomic pointer update
- [ ] 2.7 Capability-manifest entries for tile filters and wildcards with their evidence ids

## 3. Tests
- [ ] 3.1 Tier 0 export golden: an `exportList` entry with a `filter.uvTiles` subset; planned file list and decoded maps equal Painter's
- [ ] 3.2 Tier 0 export golden: an `exportParameters` rule giving one tile a different `sizeLog2` and bit depth
- [ ] 3.3 Tier 0 naming golden: `$udim`, `$uvTileName` and an optional group, under the `UVTile` and `Default` workflows
- [ ] 3.4 Plan test: a pattern without a tile wildcard on a multi-tile export is rejected as a collision before any file is written
- [ ] 3.5 Determinism: two exports of the UDIM fixture give identical bytes per file (EXP-05)
- [ ] 3.6 Publication fault test: interruption between per-tile files leaves the previous generation selected (EXP-06)

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase4.5_uv-tiles`: tile filter and naming goldens exact, collisions rejected, bytes stable

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
