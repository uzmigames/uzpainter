## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input), `phase3.4_smart-projections`; `phase1.8_project-store`, `phase1.14_compositor-core` and `phase2.8_mcp-server` delivered

## 2. Implementation
- [ ] 2.1 `paint` layer and `paint` effect kinds with the documented insertion rules (effects mono-channel in mask stacks) and the documented facade symbols for creating them
- [ ] 2.2 Whole-bitmap operation writing a resource into the plane of each addressed channel at the plane's resolution and format, as one transaction creating a new copy-on-write plane version
- [ ] 2.3 Projected-bitmap operation rasterising a bitmap through every supported projection mode into the plane; unsupported modes raise `NotYetSupported` before mutation
- [ ] 2.4 Evaluation of paint content with per-channel blending, masks and content effects; empty planes read as the empty value
- [ ] 2.5 Record the Tier 0 paint goldens through the UzmiGames recorder (twice; blobs private, hashes in `parity/manifests/`); a case Painter's documented routes cannot produce is recorded `not_migratable` with the reason
- [ ] 2.6 Migration route: paint content exported through Painter's documented export API imported with the whole-bitmap operation, with an equality check on the migrated output
- [ ] 2.7 Native `uzpainter` paint-content operations and the typed MCP tool `paint_set`; recipe-dump entries for planes and content versions; capability-manifest and operation-matrix entries

## 3. Tests
- [ ] 3.1 Tier 0 goldens: empty paint layer and empty paint effect in content and mask stacks, exact
- [ ] 3.2 Tier 0 goldens: whole bitmaps in a paint layer and in a paint effect (content and mask stacks), exact
- [ ] 3.3 Tier 0 goldens: projected bitmaps for each supported projection mode, exact
- [ ] 3.4 Tier 0 goldens: blend modes, opacity, masks and filter effects over paint content, exact
- [ ] 3.5 Store test: two paint layers on one channel and tile keep separate planes through save, reopen, revert and compaction
- [ ] 3.6 Migration test: a paint layer of an authored Painter fixture exported through the documented API and re-imported reproduces the same exported maps
- [ ] 3.7 API surface test: no stroke symbol in `uzpainter`, the facade or the MCP tool list
- [ ] 3.8 Python-disabled MCP conformance fixture for `paint_set` with a whole and a projected bitmap

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase4.2_remaining-nodes`: paint Tier 0 goldens exact or excepted, `not_migratable` cases reported, manifest updated

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
