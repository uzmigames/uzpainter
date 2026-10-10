# Proposal: phase2.8_mcp-server

## Why
P2-MCP in `docs/dag.md` (critical path), implementing D10 (`docs/architecture/11-mcp-server.md`; decisions 012 and 025). AI agents are UzPainter's only operators; they need a native MCP server with typed operation families, resources, prompts, roots, a single-writer and retry contract, `run_python` only behind `--allow-python` (owner Q12), HTTP mode for a resident instance and a requirement-to-typed-operation matrix. Requirements: INT-01…07, LAY-06, LAY-07, QG-03, ARC-01, ARC-02, ARC-14 (`docs/prd.md`). This parent is the integration and acceptance task; the work is split into three children.

## What Changes
- Transports, registry, mutation/result contract, roots and `run_python` gating: child `phase2.5_mcp-transport-registry`.
- Typed tool groups, long jobs, resources and prompts: child `phase2.6_mcp-typed-tool-families`.
- Requirement-to-typed-operation matrix in the capability manifest: child `phase2.7_mcp-operation-matrix`.
- Phase 2 contract fixtures (synthetic, UzmiGames-authored project and job fixtures) and their report `parity/reports/phase2/mcp-contract.json` (pass/fail per fixture, numbers only).

## Dependencies
- DAG input: `phase2.4_supervisor-worker` (P2-SUPERVISOR).
- Children (all mandatory): `phase2.5_mcp-transport-registry`, `phase2.6_mcp-typed-tool-families`, `phase2.7_mcp-operation-matrix`.
- Consumers: `phase2.9_pilot-belt`, `phase2.10_pilot-tunic-recovery`; later evidence owned elsewhere: the Python-disabled Belt round (`phase2.9_pilot-belt` / `phase2.11_gate-g2`), native-bake cancellation (`phase3.5_embree-bakers`), full Python-disabled conformance (`phase5.4_parity-report` / `phase5.6_gate-g5`).

## Acceptance
DAG gate: Phase 2 typed-tool, transport, lease, error and retry contract fixtures pass on synthetic project/job fixtures; unavailable later families are reported as capability gaps. Fixtures (`11-…` §7): two writers; a lost acknowledgement with retry; a worker killed immediately after the durable project commit and before the supervisor's acknowledgement (retry the same request, then a changed request with the same key); reconnect in HTTP mode; a path outside the roots; a stale revision; a non-idempotent mutation committed, advanced beyond retention and compacted, supervisor ledger lost, original key replayed with its original precondition and with no precondition (neither replay creates a mutation), and a known-key replay inside the window returning the stored result despite a newer revision. The capability resource shows any operation that still needs Python as a gap. P2-BELT/G2 accepts the Python-disabled Belt round, P3-BAKER native-bake cancellation and P5-REPORT/G5 full Python-disabled conformance; none of them is part of this task's closure. The parent closes only when all three children pass.

## Impact
- Affected specs: `mcp`
- Affected code: supervisor MCP layer, worker command handlers, capability manifest generator
- Breaking change: NO
- User benefit: a complete, safe MCP surface for AI operators
