## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase4.2_remaining-nodes`

## 2. Children (mandatory, in dependency order)
- [ ] 2.1 Child accepted: `phase4.3_tiles-workflow`
- [ ] 2.2 Child accepted: `phase4.4_tiles-per-tile-resolution`
- [ ] 2.3 Child accepted: `phase4.4_tiles-export-filters`

## 3. Integration
- [ ] 3.1 Author the UDIM fixture under `parity/manifests/`: a UzmiGames-authored mesh with UVs on at least three tiles (one of them non-adjacent), a recipe using uniform fills, a bitmap source, a `UVTile` geometry mask and a per-tile resolution, and the instruction sequence for both tools
- [ ] 3.2 Record the Painter goldens of the UDIM fixture twice on the owner's machine into the private oracle store (hashes only in the public manifest)
- [ ] 3.3 Regenerate the capability manifest: the UV-tile workflow and its symbols move from `release-gap` to `supported` with tier evidence, or stay explicit gaps

## 4. Tests
- [ ] 4.1 Tier 0 tile semantics on the UDIM fixture are exact on the self-hosted GPU runner
- [ ] 4.2 Tier 1: every exported map of every tile equals the private Painter goldens and is byte-stable across two runs
- [ ] 4.3 Save/reopen of the UDIM project reproduces identical exports

## 5. Acceptance
- [ ] 5.1 DAG gate P4-TILES met: Tier 0/1 on a UDIM fixture; report written to `parity/reports/phase4/`

## 6. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 6.1 Update or create documentation covering the implementation
- [ ] 6.2 Write tests covering the new behavior
- [ ] 6.3 Run tests and confirm they pass
