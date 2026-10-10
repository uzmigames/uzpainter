## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.3_procedural-families

## 2. Implementation
- [ ] 2.1 Implement `insert_smart_mask`: detached expansion into a mask-stack effect list attached in one transaction, `preset_ref {asset@version}` recorded, insertion outside a mask stack rejected
- [ ] 2.2 Author the UzmiGames smart-mask recipes for the edge-wear, cavity-dirt, edge-crack, ground-dirt, dust and occlusion roles in the documented layer/effect model, with per-recipe provenance records
- [ ] 2.3 Register the Painter smart-mask names as internal aliases resolving to the private observed structure on the owner's machine, else `UnsupportedProcedural{reason: "private preset unavailable"}`
- [ ] 2.4 Extend the repository guard to reject observed preset trees, parameter collections and serialized readbacks
- [ ] 2.5 Author the Tier 2a manifests per recipe under `parity/manifests/`, with Painter rebuild instructions using only the documented API

## 3. Tests
- [ ] 3.1 Tier 2a: each recipe rebuilt in Painter through the documented API and in UzPainter on unit sphere, bevelled cube and hat v6 low × {1024, 2048, 4096} produces equal outputs
- [ ] 3.2 Insertion-rule test: `insert_smart_mask` into a content stack raises; a failing expansion attaches nothing
- [ ] 3.3 Alias tests: with the private structure present the alias resolves to it; without it `UnsupportedProcedural` is raised and no UzmiGames recipe is substituted
- [ ] 3.4 Guard test: a recorded preset readback JSON is rejected; an authored recipe JSON passes

## 4. Acceptance
- [ ] 4.1 Acceptance: every shipped smart-mask recipe passes Tier 2a (equal or owner-approved exception); insertion, alias and guard tests pass

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
