## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.11_gate-g2` (Tunic v10 passed G2); the Assets3D repository's collaboration and lock protocol read and its current lock state checked before any edit there

## 2. Implementation
- [ ] 2.1 Derive the amendment scope from the capability manifest regenerated at G2: the operation families and symbols with status `supported`
- [ ] 2.2 Draft the amendment text: UzPainter paints the proven scope; Painter remains the oracle and the tool for out-of-scope work until G5; no "full replacement" wording while a required gap is open
- [ ] 2.3 Present the draft to the owner for approval and signature; record the signed text, scope manifest version and approval as a rulebook decision (follow-up of decision 026)
- [ ] 2.4 Apply the signed amendment in the Assets3D repository only under that repository's collaboration and lock protocol, with the owner's approval; record the change reference
- [ ] 2.5 Adapter gate check: refuse a paint round unless the manifest gates passed and the mesh certificate has no `fail`; flag diagnostic imports (QG-02)
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
