## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase3.7_fixtures-bracers-hat5`, `phase3.4_uzengine-preset`; for item 3.6 also `phase3.3_unreal-gltf-presets`

## 2. Children (mandatory)
- [ ] 2.1 Child accepted: `phase4.1_hat8-sharpen-filter`
- [ ] 2.2 Child accepted: `phase4.1_hat8-specular-weight-export`

## 3. Integration
- [ ] 3.1 Classify every layer and effect of the 43-layer stack; import stroke-painted content as bitmaps where the documented export route preserves the output, otherwise record `not_migratable` with the reason and raise the owner scope question with `rulebook_task ask`
- [ ] 3.2 Record the hat v8 Painter oracle through the documented API twice (same session; after save/reopen); hashes in `parity/manifests/tier1/hat-v8.json`
- [ ] 3.3 Rebuild hat v8 in UzPainter from the same stack JSON and resources with identical external mesh maps
- [ ] 3.4 Bind one corrected AO per set by usage for generators, delivery and albedo layers, exported for the glTF occlusion slot (BAK-08)
- [ ] 3.5 Consumer-matrix rows 2, 3, 5 and 7 (`08-export.md` §5.1) on the UzPainter and the Painter delivery of hat v8
- [ ] 3.6 Hat v8 runs of consumer-matrix rows 8 (UE 5.6) and 9 (UzEngine)
- [ ] 3.7 Record timing and memory of the 43-layer evaluation and the seven-map export for P5-PERF (NFR-03)

## 4. Tests
- [ ] 4.1 Oracle stability of every hat v8 golden classified before admission
- [ ] 4.2 UzPainter repeatability: two runs byte-identical
- [ ] 4.3 Tier 1: the seven delivered maps equal to the private goldens at native depth
- [ ] 4.4 Save/reopen of the rebuilt project reproduces the same exports
- [ ] 4.5 Rows 2, 3, 5 and 7: bindings (file, channel, colour space, bit depth, metadata) and outputs identical on both deliveries; SpecularWeight gap reported in rows 2 and 3
- [ ] 4.6 Rows 8 and 9 pass on their expected bindings with SpecularWeight reported as a gap
- [ ] 4.7 Report in `parity/reports/phase4/` with max/mean/p99 Δ and differing-texel counts per map and the exceptions relied on

## 5. Acceptance
- [ ] 5.1 DAG gate P4-HAT8 met: equal maps; no `not_migratable` fixture without an owner scope decision

## 6. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 6.1 Update or create documentation covering the implementation
- [ ] 6.2 Write tests covering the new behavior
- [ ] 6.3 Run tests and confirm they pass
