# Proposal: phase5.3_parity-report-capability-gaps

## Why
Child of `phase5.4_parity-report` (P5-REPORT in `docs/dag.md`), implementing D2 as specified in `docs/architecture/10-python-api.md` §3 (decision 019, owner Q5). The capability manifest lists every Painter Python symbol and every UzPainter operation as `supported`, `desktop-only-omitted` or `release-gap`, and nothing is silently a no-op (ARC-03). Release criterion 2 of `docs/prd.md` §18 and the `docs/dag.md` gate rule require every in-scope, output-affecting capability to be `supported` or covered by an explicit owner scope decision; reporting a gap is not accepting it, and nothing is called a full replacement while a required gap is open (OWN-01, OWN-03, Q5). The corpus migration assumption of `docs/dag.md` also requires any excluded or replaced `not_migratable` fixture to carry an owner scope decision recorded in the capability manifest. This child delivers the release capability manifest with every remaining gap and its scope status.

## What Changes
- Capability manifest regenerated from the frozen release build: `capabilities.json` in the distribution, `uzpainter capabilities` output and the `uzpainter://capabilities` resource, one entry per qualified symbol and operation context with `status`, `since`, `tier_evidence`, `notes` and `evidence` (10 §3).
- Evidence check: every `supported` entry names Tier 0 evidence present in the Phase 5 tier report; every `desktop-only-omitted` entry carries its per-symbol justification.
- Gap register `parity/reports/phase5/capability-gaps.json`: every `release-gap` entry (for example arbitrary `.sbsar` evaluation, auto-unwrap, material layering, USD scene export, TIFF/PSD/WebP/J2K export, and any gap left after Phase 4) with either the owner scope decision that covers it (decision id under `.rulebook/decisions/`) or the status `blocking`; every `not_migratable` fixture with its owner scope decision or `blocking`.
- Owner scope questions raised through `rulebook_task {action:"ask"}` for each open gap without a decision; the answers are recorded as decisions and referenced from the manifest.
- Wording check over the manifest, release notes and `README.md`: no "full replacement" claim while any required gap is open; milestones named by proven scope.

## Dependencies
- Parent: `phase5.4_parity-report` (integration and acceptance of P5-REPORT).
- Prerequisites (DAG inputs of P5-REPORT): `phase4.6_gate-g4`, `phase3.7_path-tracer`, `phase5.1_performance-budgets` (the release build is frozen after it).
- Uses the generator delivered by `phase1.2_docmodel-capability-manifest` and the Tier 0 evidence of the sibling `phase5.2_parity-report-tiers`; sibling `phase5.2_parity-report-mcp-conformance` reads the same manifest for the operation matrix.

## Acceptance
- Capability manifest generated from the frozen build shows every remaining gap explicitly.
- Every in-scope capability is `supported` or covered by an explicit owner scope decision; any gap without one is reported `blocking` and blocks P5-REPORT.
- No "full replacement" claim exists while a required gap is open.

## Impact
- Affected specs: `capabilities` (manifest statuses, gap register, scope decisions)
- Affected code: capability manifest generator run on the release build, gap register writer, symbol-behaviour tests, `parity/reports/phase5/`
- Breaking change: NO
- User benefit: agents and the owner see exactly what UzPainter supports, what is out of scope by decision, and what still blocks release
