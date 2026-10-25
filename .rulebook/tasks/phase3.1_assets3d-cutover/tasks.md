## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.11_gate-g2` (Tunic v10 passed G2); the Assets3D repository's collaboration and lock protocol read and its current lock state checked before any edit there

## 2. Implementation
- [ ] 2.1 Derive the amendment scope from the capability manifest regenerated at G2: the operation families and symbols with status `supported`
- [ ] 2.2 Draft the amendment text: UzPainter paints the proven scope; Painter remains the oracle and the tool for out-of-scope work until G5; no "full replacement" wording while a required gap is open
- [ ] 2.3 Present the draft to the owner for approval and signature; record the signed text, scope manifest version and approval as a rulebook decision (follow-up of decision 026)
- [ ] 2.4 Apply the signed amendment in the Assets3D repository only under that repository's collaboration and lock protocol, with the owner's approval; record the change reference
- [x] 2.5 Adapter gate check: refuse a paint round unless the manifest gates passed and the mesh certificate has no `fail`; flag diagnostic imports (QG-02; software enforcement only, not pilot admission)
  - Pre-implementation findings (2026-10-24, read-only survey of Assets3D; no edit there): the pipeline moved to `Pipeline/manifest/manifest-schema-v2.json`. `exportacao`/`comparacao`/`formato_mapa` of INT-21 are now `export`/`comparison`/`map_format` with English fields (`sources`, `outputs`, `moment`, `preset`, `maps`, `comparison.result` in identical-bytes|identical-pixels|visual-equivalence|different|pending, `evidence`, `open_items`). Gates are `gates.{technical,visual,user}.<free key>` with `state` (pass|fail|pending|not_applicable), `applicability` (confirmed|not-verified|reopened) and `stages` (geometry, fit, coverage, low_uv, bake, painting, rig, export). The six real piece manifests (Skeletal Mage 18, 19, 20, 23, 24, 25) mark every gate `not-verified`. Tunic v10 has `technical/uv-producao` = fail (low_uv) and `snapshot-v10` pending (geometry, bake). No manifest has a `low_high_fidelity` gate. Assets3D's generated painting check still names `piece-manifest-v1` and `gates/visual geometria-encaixe`. The 'mesh certificate' of QG-02 is UzPainter's own import certificate (`12-mesh-import.md` §4, `status` pass|warn|fail), not an Assets3D field. Decision needed before implementing 2.5: which stages must have a gate with `state` pass, whether `applicability` must be `confirmed` (with today's data every round, including the pilots, would be refused), and how a v1 `low_high_fidelity` requirement maps to v2. Recommendation (to be decided jointly with Codex, not inferred): production requires, for each of geometry/fit, low_uv and bake, a gate covering that stage with `state` pass and `applicability` confirmed, and no gate covering those stages in `fail`. Anything else proceeds only as a flagged diagnostic import. Under this rule Tunic v10 stays refused until Assets3D re-verifies its gates under its own protocol.
  - Decision 360 accepts the LOCAL v2 prerequisite policy, not owner signature or cutover. `adapters/assets3d/gate_contract.py` and `check-production REQUEST [--diagnostic]` provide a read-only pinned-evidence preflight; M11 documents its schema and unsupported proofs. Positive assessments never set `production_authorized`; their success alone cannot authorize execution.
  - QG-02 software enforcement verified (2026-10-25): Python requires explicit `--production-round REQUEST` or `--diagnostic-import`, revalidates every consumed input, probes compiled runtime support, forwards SHA-256/size pins and requires native REQUIRED/ARMED status before restore. The native guard checks actual imports and rechecks pins before persistence; M12 documents the contract. Validation: 83 adapter/checker CPU cases plus the added selectorless-empty-evidence rejection passed; `tests/python/test_assets3d_production_guard.py::test_adapter_production_round_against_the_native_guard` passed once (12.32s), exercising the real client/runner/host with a genuine native import report and AUTHORED prerequisite gates: create/save, restore and same-mesh reload/save succeed; wrong-mesh reload refuses without changing revision or store bytes. This closes only the software obligation of 2.5. Broader tests 3.1-3.3, G2, real Assets3D pilot admission, owner signature and M8 route-token closure remain unclaimed and open.
- [ ] 2.6 Adapter scope check: refuse an operation outside the amended scope with a structured error naming Painter as the tool for it
- [ ] 2.7 Adapter manifest blocks: `exportacao` per export (INT-21) and the `painter_recipe`-equivalent block with defaults, evaluator version and content identity (INT-20)
- [ ] 2.8 Any adapter file that lives inside Assets3D changed only under that repository's protocol, with the owner's approval

## 3. Tests
- [ ] 3.1 Adapter checks on wand v1, belt v5 and tunic v10: accepted rounds pass and write both manifest blocks
- [ ] 3.2 Refusal test: a round whose upstream manifest gate failed is refused before any mutation
- [ ] 3.3 Refusal test: a mesh certificate with `fail` refuses the round; a `warn` diagnostic import proceeds flagged
- [ ] 3.4 Scope test: an operation on a `release-gap` capability is refused with the structured out-of-scope error
- [ ] 3.5 Manifest-block schema test for `exportacao` and the recipe block on the three pilots
- [ ] 3.6 Results written to `parity/reports/phase3/`

## 4. Acceptance
- [ ] 4.1 DAG gate P3-CUTOVER met: owner signed the amendment after Tunic v10 passed G2; adapter checks pass on the three pilots

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
