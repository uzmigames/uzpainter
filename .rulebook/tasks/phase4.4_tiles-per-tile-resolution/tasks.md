## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase4.3_tiles-workflow` (and through the parent `phase4.2_remaining-nodes`)

## 2. Implementation
- [ ] 2.1 Optional resolution per UV tile in the document model (power of two, 128–8192), set resolution as default, effective value readable and dumped in the recipe
- [ ] 2.2 VRAM admission per tile at creation and on every resolution change; explicit refusal before mutation
- [ ] 2.3 UV raster, evaluator chunks and mesh-map sampling at the effective tile resolution, with Tier 0 fitted resampling for mesh maps of another resolution
- [ ] 2.4 Resolution change on a tile with paint planes: resample into new copy-on-write plane versions per the fitted rule; procedural content re-evaluated
- [ ] 2.5 Export default size per tile from its effective resolution; `sizeLog2` still overrides
- [ ] 2.6 Documented per-tile resolution symbols in `uzpainter` and the facade with set→get readback; capability-manifest entries with evidence ids

## 3. Tests
- [ ] 3.1 Tier 0 golden: one set with tile 1001 at 2048 and tile 1002 at 1024, every channel exported at 16 bit, exact
- [ ] 3.2 Tier 0 golden: a bitmap written to a paint layer, then the tile resolution changed, exported and compared exactly
- [ ] 3.3 API probes: per-tile resolution set→get, reset to the set default, save and reopen
- [ ] 3.4 Admission test with a reduced synthetic VRAM budget: the over-budget tile is refused with an explicit error and the project revision is unchanged
- [ ] 3.5 Export test: default per-tile output sizes and a `sizeLog2` override produce the planned sizes

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase4.5_uv-tiles`: per-tile resolution goldens exact, admission explicit, round trip preserved

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
