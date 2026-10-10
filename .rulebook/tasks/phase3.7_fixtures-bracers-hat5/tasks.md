## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase3.5_embree-bakers`, `phase3.6_smart-presets-projections`

## 2. Implementation
- [ ] 2.1 Bracer r9: record the Painter oracle through the documented API (twice: same session and after save/reopen), blobs in the private store, hashes in `parity/manifests/tier1/bracer-r9.json`
- [ ] 2.2 Bracer r9: rebuild in UzPainter from the same stack JSON and resources with identical external mesh maps, procedurals served by certified `HlslBackend` families
- [ ] 2.3 Bracer r9: port the smart-material folder with identical parameters and resources and its provenance records (LAY-11)
- [ ] 2.4 Hat v5: classify every layer and effect; for stroke-painted content, verify the documented export route preserves the required output and import it as a bitmap, or record `not_migratable` with the reason
- [ ] 2.5 Hat v5: record the Painter oracle twice and rebuild in UzPainter; manifest `parity/manifests/tier1/hat-v5.json`
- [ ] 2.6 Native-bake leg: bake the fixtures' mesh maps with `EmbreeBaker` from their low/high (and cage) sources; manifests under `parity/manifests/tier2b/`
- [ ] 2.7 If a fixture is `not_migratable`, raise the owner scope question with `rulebook_task ask` and record any decision in the capability manifest and gate report

## 3. Tests
- [ ] 3.1 Oracle stability per golden: the two Painter recordings compared and classified before admission
- [ ] 3.2 UzPainter repeatability: two runs of each fixture are byte-identical
- [ ] 3.3 Bracer r9 Tier 1: every exported map equal to the private goldens at native depth
- [ ] 3.4 Bracer r9 with `SnapshotBackend` disabled still passes Tier 1 (MAT-04 through certified families only)
- [ ] 3.5 Hat v5 Tier 1/2: maps equal, procedural relief included
- [ ] 3.6 Tier 2b per baked map: hit/coverage evidence first, then maps, against Painter's CPU bakes
- [ ] 3.7 Save/reopen of both rebuilt projects reproduces the same exports
- [ ] 3.8 Reports in `parity/reports/phase3/` with max/mean/p99 Δ and differing-texel counts per map, Tier 2a status per used asset, exceptions relied on, bracer layer-workload timing and memory

## 4. Acceptance
- [ ] 4.1 DAG gate P3-BRACERS met: required fixtures pass their applicable tiers through equality or approved output exceptions; no `not_migratable` fixture without an owner scope decision

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
