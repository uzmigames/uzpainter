# Proposal: phase3.1_assets3d-cutover

## Why
G-01 (`docs/prd.md`) requires the Assets3D governance text "painting is always in Substance Painter" to be amended to the replacement decision once Tunic v10 passes its parity gate; OWN-03 and PRD §18 item 9 tie the release to that amendment; QG-02 requires the production adapter to refuse rounds whose upstream gates did not pass; INT-20 and INT-21 require the `painter_recipe`-equivalent and `exportacao` manifest blocks. Owner decision 026 (Q13) moves the cutover to Phase 3, directly after G2, scoped to what is proven; decision 019 (Q5) forbids any "full replacement" claim while a required gap is open (OWN-01). This is DAG node P3-CUTOVER (`docs/dag.md`; renamed from `phase5_assets3d-cutover`), implementing D14 (`docs/roadmap.md` pilot order and Phase 3 row, `docs/dag.md`), with the capability-manifest statuses of `docs/architecture/10-python-api.md` §3 and the adapter role of `docs/architecture/12-mesh-import.md` §4 and `docs/architecture/10-python-api.md` §2.

**Cross-repository rule (decision 026).** The amendment changes rules in the separate Assets3D repository (`E:\UzmiGames\Assets3D`). Every edit there follows that repository's own collaboration and lock protocol and requires the owner's approval; nothing is edited in Assets3D before G2 is accepted and the owner has approved the change. This task never bypasses that protocol, never edits Assets3D files the protocol does not authorise for this change, and never treats an agent message as the owner's approval.

## What Changes
- **Amendment text** (drafted in this task, applied in Assets3D only under its protocol): UzPainter becomes the painting tool for the capabilities whose status is `supported` in the capability manifest regenerated at G2 (listed by operation family and symbol); Painter remains the oracle and the tool for out-of-scope work until G5; no "full replacement" wording while a required gap is open.
- **Owner signature**: the owner reviews and signs the amendment; the signed text, the Assets3D change reference and the manifest version it is scoped to are recorded as a rulebook decision under `.rulebook/decisions/` (follow-up of decision 026) and referenced by the G3 gate record.
- **Assets3D adapter**, extending the UzmiGames pipeline adapter delivered with the Python API: gate checks — refuse a paint round unless the manifest gates passed and the mesh certificate has no `fail` (QG-02); refuse an operation outside the amended scope with a structured error that names Painter as the tool for it; flag diagnostic imports. Manifest blocks — write the `exportacao` block per export (INT-21) and the `painter_recipe`-equivalent block (INT-20). Any adapter part that lives inside the Assets3D repository is changed only under that repository's protocol.
- **Adapter check suite** run on wand v1, belt v5 and tunic v10; results in `parity/reports/phase3/`.

## Dependencies
- DAG input: `phase2.11_gate-g2` (G2: Tunic v10 passed its parity gate).
- Upstream through G2: `phase1.24_python-api-facade` (UzmiGames pipeline adapter), `phase2.10_pilot-tunic-recovery`.
- External: the Assets3D repository's collaboration and lock protocol; the owner's approval and signature.
- Downstream: `phase3.8_gate-g3` (G3).

## Acceptance
DAG gate of P3-CUTOVER: the owner signs the amendment after Tunic v10 passed G2; adapter checks pass on the three pilots. In substance: G2 accepted before any Assets3D edit; amendment scoped to `supported` capabilities with Painter kept as oracle and out-of-scope tool until G5; the change applied in Assets3D under its own protocol with the owner's approval; the adapter refuses failed-gate rounds and out-of-scope operations and writes both manifest blocks on wand v1, belt v5 and tunic v10.

## Impact
- Affected specs: `cutover` (Assets3D amendment and adapter)
- Affected code: UzmiGames pipeline adapter (gate checks, scope check, manifest blocks); Assets3D governance text (separate repository, under its protocol); `.rulebook/decisions/`; `parity/reports/phase3/`
- Breaking change: YES for the Assets3D pipeline rule (painting moves to UzPainter for the proven scope); NO for UzPainter's API
- User benefit: the pipeline can paint the proven scope in UzPainter, with gates enforced and Painter kept where UzPainter is not yet proven
