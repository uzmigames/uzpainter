# Proposal: phase5.4_parity-report

## Why
P5-REPORT in `docs/dag.md` (integration and acceptance task), implementing D13 as specified in `docs/architecture/14-parity-testing.md` (decisions 015 and 017, with decision 018 for Tier 3 and decision 025 for typed-operation conformance). Release criteria 1–3 of `docs/prd.md` §18 require the full Tier 0–3 evidence with the exception register published, the capability manifest with every in-scope capability supported or covered by an owner scope decision, and Python-disabled conformance for every required operation family. Requirements: G-04, ARC-03, ARC-06, ARC-10, ARC-14, VIS-06, NFR-02, NFR-05, CLR-05. The `docs/dag.md` gate rule makes the final parity report and the packaging verification refer to the same immutable build hash and dependency lock; any later change reopens both, and `phase5.5_clean-history` is verified against that same released tree.

## What Changes
- Integration of the three child reports into the release parity record `parity/reports/phase5/parity-report.json` (numbers and hashes only): the tier report and exception register (`phase5.2_parity-report-tiers`), the Python-disabled conformance result (`phase5.2_parity-report-mcp-conformance`) and the capability manifest with its gap register (`phase5.3_parity-report-capability-gaps`).
- Budgets re-confirmed on the frozen build: the measurements of `phase5.1_performance-budgets` re-run on the frozen build hash and compared with the published budgets.
- Build identity check: every child result, the budget re-confirmation and `phase5.2_packaging` name the same build hash and dependency lock; a mismatch fails the report.
- Reopen rule recorded in the report: any change to the build or lock after freeze reopens this task and `phase5.2_packaging`.

## Dependencies
- Prerequisites (DAG inputs of P5-REPORT): `phase4.6_gate-g4`, `phase3.7_path-tracer`, `phase5.1_performance-budgets`.
- Item-level prerequisite: the sanitisation items of `phase5.5_clean-history` (paraphrase, release-tree scan) are done before the release build is frozen (the build this report and its children use); the rest of `phase5.5_clean-history` follows this task.
- Children (all mandatory): `phase5.2_parity-report-tiers`, `phase5.2_parity-report-mcp-conformance`, `phase5.3_parity-report-capability-gaps`.
- Same frozen build as `phase5.2_packaging`; followed by `phase5.5_clean-history`; joined by `phase5.6_gate-g5`.

## Acceptance
- Tiers 0–2 green or covered by approved exceptions; Tier 3 passed through approved exceptions (blocked otherwise).
- Full Python-disabled MCP conformance passes for every required operation family (every row of the requirement-to-typed-operation matrix).
- Capability manifest lists every remaining gap, each in-scope gap covered by an owner scope decision or reported blocking.
- Budgets re-confirmed on the frozen build; the report's build hash and dependency lock equal those of `phase5.2_packaging`.
- Closes only when all three children pass.

## Impact
- Affected specs: `parity-report` (release evidence integration, build identity)
- Affected code: report integration and build-identity check, CI job on the self-hosted GPU runner, `parity/reports/phase5/`
- Breaking change: NO
- User benefit: one release evidence record the owner can sign at G5, tied to the exact build that ships
