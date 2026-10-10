## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.11_gate-g2`, `phase3.7_fixtures-bracers-hat5`, `phase3.4_uzengine-preset`, `phase3.3_unreal-gltf-presets`, `phase3.7_path-tracer`, `phase3.1_assets3d-cutover`

## 2. Joined items
- [ ] 2.1 G2 accepted and its gate record present in `parity/reports/phase2/gate-g2.md`
- [ ] 2.2 P3-BRACERS accepted (`phase3.7_fixtures-bracers-hat5`)
- [ ] 2.3 P3-UZE accepted (`phase3.4_uzengine-preset`)
- [ ] 2.4 P3-UNREAL accepted (`phase3.3_unreal-gltf-presets`)
- [ ] 2.5 P3-PATHTRACER accepted (`phase3.7_path-tracer`)
- [ ] 2.6 P3-CUTOVER accepted (`phase3.1_assets3d-cutover`)
- [ ] 2.7 Mandatory items reaching the gate through those inputs accepted: `phase3.5_embree-bakers`, `phase3.3_procedural-families`, `phase3.6_smart-presets-projections`, `phase3.3_vulkan-backend-ray-tracing`

## 3. Criteria evidence
- [ ] 3.1 Tier 2a published per asset and Tier 2b per map: exact or covered by an owner-approved exception
- [ ] 3.2 Bracer r9 Tier 1 equal
- [ ] 3.3 Vulkan outputs equal to DX12 on the Tier 0 subset and the pilot maps (or owner-approved exceptions)
- [ ] 3.4 Tier 3 report present with noise floor and exception proposals; no Tier 3 pass recorded without an owner-approved register entry
- [ ] 3.5 DXR vs Vulkan path-tracer comparison present with every difference reported
- [ ] 3.6 UzEngine fixture loads and renders the preset; gaps reported
- [ ] 3.7 Unreal and glTF fixtures load
- [ ] 3.8 Assets3D rule amendment signed by the owner and its decision record referenced
- [ ] 3.9 Settling check: no gate fixture marked `not_migratable` without an owner scope decision in the capability manifest and gate record
- [ ] 3.10 Every exception relied on is an owner-approved entry in `parity/exceptions.json` and listed in the gate record

## 4. Gate record
- [ ] 4.1 Capability manifest regenerated and its version recorded
- [ ] 4.2 Duration Hypotheses for Phases 4–5 revised and recorded (roadmap rule 6)
- [ ] 4.3 Gate record written to `parity/reports/phase3/gate-g3.md` (numbers and hashes only)
- [ ] 4.4 Every other Phase 3 task archived in `.rulebook` (roadmap rule 3)

## 5. Acceptance
- [ ] 5.1 DAG gate G3 met: all joined items accepted; owner signs the gate record

## 6. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 6.1 Update or create documentation covering the implementation
- [ ] 6.2 Write tests covering the new behavior
- [ ] 6.3 Run tests and confirm they pass
