# Proposal: phase5.2_parity-report-mcp-conformance

## Why
Child of `phase5.4_parity-report` (P5-REPORT in `docs/dag.md`), implementing D10 as specified in `docs/architecture/11-mcp-server.md` §2, §6 and §7 (decision 012 with decision 025, owner Q12). Typed MCP operation families must cover every required operation, and `run_python` is a trusted opt-in registered only with `--allow-python` (ARC-14); the DAG assigns to P5-REPORT/G5 the acceptance of full Python-disabled conformance for every required operation family, after each implementation exists (Phase 2 accepted only synthetic contract fixtures and the Belt round). Release criterion 3 of `docs/prd.md` §18 requires the requirement-to-typed-operation matrix and a Python-disabled conformance fixture to cover every required operation family. Requirements: ARC-14, INT-01, INT-02, INT-04, INT-05, INT-07, LAY-06, LAY-07, QG-03.

## What Changes
- Requirement-to-typed-operation matrix regenerated from the frozen release build together with the capability manifest and published in `uzpainter://capabilities`: every required operation (INT-02, ARC-14 and the requirements each family serves) mapped to its typed tool and its conformance fixture.
- Python-disabled conformance suite run against the frozen build, supervisor started without `--allow-python`, one fixture per required operation family (11 §7): project lifecycle; texture sets; resources; the stack family including the Phase 4 node, effect and source kinds and paint layers receiving bitmaps and projections; recipes (`sync_stack` name addressing and group-only rebuild, LAY-06/07; `apply_smart`; `batch`); native bake; mesh reload; every export target; `capture` in each mode (`painter_iray`, `painter_viewport`, diagnostic views); diagnostics; jobs and lease.
- Contract checks inside each mutating fixture: `idempotency_key` and `expected_revision` accepted, results carry `revision`, `committed_revision`, `job_id` where applicable, the changed/created/hidden/imported/skipped lists and `warnings`; structured errors on failure (QG-03).
- Python-policy check: `run_python` absent from the tool list and rejected at the IPC boundary with `python_disabled`; the capability resource lists no required operation that still needs Python.
- Conformance result `parity/reports/phase5/mcp-conformance.json`: one row per matrix row with its fixture, outcome and the build hash.

## Dependencies
- Parent: `phase5.4_parity-report` (integration and acceptance of P5-REPORT).
- Prerequisites (DAG inputs of P5-REPORT): `phase4.6_gate-g4`, `phase3.7_path-tracer` (the `painter_iray` capture family), `phase5.1_performance-budgets` (the release build is frozen after it).
- Builds on `phase2.8_mcp-server` and its child `phase2.7_mcp-operation-matrix`, which introduced the matrix and its Phase 2 contract fixtures.
- Siblings: `phase5.2_parity-report-tiers`, `phase5.3_parity-report-capability-gaps`; all three report on the same build hash.

## Acceptance
- Full Python-disabled MCP conformance passes for every required operation family: every row of the requirement-to-typed-operation matrix has a typed tool and a passing conformance fixture on the frozen build.
- A required operation without a typed tool is reported as a release gap and fails this item; `run_python` is never the route for a required operation.

## Impact
- Affected specs: `mcp` (typed-operation conformance, Python policy)
- Affected code: matrix generator, conformance fixtures per operation family, CI job on the self-hosted GPU runner, `parity/reports/phase5/`
- Breaking change: NO
- User benefit: an AI agent can perform every required operation through typed MCP tools with Python disabled, proven on the release build
