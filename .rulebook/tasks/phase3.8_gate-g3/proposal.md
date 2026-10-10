# Proposal: phase3.8_gate-g3

## Why
Gate G3 "Bake, render, presets" closes Phase 3 (`docs/roadmap.md`, `docs/dag.md` gate rule): it joins every mandatory acceptance item of the phase, requires G2, and cannot be closed by any single work package carrying its evidence. Its criteria prove the PRD requirements that Phase 3 delivers: native bake Tier 2b (OWN-05, BAK-03), procedurals Tier 2a and bracer r9 Tier 1 (MAT-02…04), Vulkan equal to DX12 (ACC-01, decision 017 Q1), the Tier 3 path-tracer report against converged Iray references (VIS-06, ARC-06, ARC-10; decision 018 Q2), consumer-validated presets (OWN-06, EXP-08; decision 023 Q10) and the signed Assets3D amendment (G-01; decision 026 Q13). Implements D14 (`docs/roadmap.md`, `docs/dag.md`) with the tier and exception rules of `docs/architecture/14-parity-testing.md` §3, §5 and §8 and the Tier 3 rules of `docs/architecture/07-preview-and-render-parity.md` §4.

## What Changes
- Gate record `parity/reports/phase3/gate-g3.md` (numbers and hashes only): each joined item with its acceptance evidence, each G3 criterion with the report that proves it, the exceptions relied on, the `not_migratable` settling check, the regenerated capability manifest version and the owner's signature.
- Regenerated capability manifest at the gate (roadmap rule 3).
- Revised duration Hypotheses for the remaining phases, recorded in the gate record (roadmap rule 6).

## Dependencies
- DAG inputs (joined items): `phase2.11_gate-g2` (G2), `phase3.7_fixtures-bracers-hat5` (P3-BRACERS), `phase3.4_uzengine-preset` (P3-UZE), `phase3.3_unreal-gltf-presets` (P3-UNREAL), `phase3.7_path-tracer` (P3-PATHTRACER), `phase3.1_assets3d-cutover` (P3-CUTOVER).
- Mandatory Phase 3 items reaching the gate through those inputs: `phase3.5_embree-bakers` (P3-BAKER), `phase3.3_procedural-families` (P3-PROC), `phase3.6_smart-presets-projections` (P3-SMART), `phase3.3_vulkan-backend-ray-tracing` (P3-VULKAN).
- Downstream: `phase4.6_gate-g4` (G4).

## Acceptance
DAG gate G3: all joined items accepted. Roadmap G3 criteria, each evidenced in the gate record: Tier 2a/2b published per asset and map (exact or owner exception); bracer r9 Tier 1 equal; Vulkan outputs equal to DX12 on the Tier 0 subset and pilot maps; Tier 3 report produced with noise floor and exception proposals (a Tier 3 pass exists only as an owner-approved exception, decision 017); DXR and Vulkan path-tracer outputs compared with every difference reported; UzEngine fixture loads and renders the preset with gaps reported; Unreal/glTF fixtures load; Assets3D rule amendment signed by the owner.

## Impact
- Affected specs: `gates` (G3)
- Affected code: none; `parity/reports/phase3/gate-g3.md`, capability manifest regeneration, `.rulebook/` archive of the Phase 3 tasks
- Breaking change: NO
- User benefit: an evidence-backed decision that native bake, procedurals, the render path and the presets are proven before coverage work closes
