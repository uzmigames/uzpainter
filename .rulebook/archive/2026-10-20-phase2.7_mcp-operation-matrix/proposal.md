# Proposal: phase2.7_mcp-operation-matrix

## Why
Child of `phase2.8_mcp-server` (P2-MCP in `docs/dag.md`), implementing the requirement-to-typed-operation matrix of D10 (`docs/architecture/11-mcp-server.md` §2, §6, §7; owner Q12, decision 025) and its place in the capability manifest of D2 (`docs/architecture/10-python-api.md` §3). A required operation without a typed tool must be visible as a release gap from Phase 2 on, never covered by `run_python`; release (P5-REPORT/G5) checks every row. Requirements: INT-02, ARC-03, ARC-14 (`docs/prd.md`).

## What Changes
- Matrix generator run with the capability manifest generator at build time: one row per required operation (the INT-02 list: status/project info; create with mesh, settings, mesh maps and colour management; open/close/save/save_as; list texture sets; import resource; set mesh maps; stack sync from JSON; smart materials and procedural layers; get/set layer properties; replace mask resource; snapshot/recipe dump; export with preset or inline config; capture; mesh reload; bake and job status; per-layer isolation; plus the operations of ARC-14 and the requirements each family serves), naming the requirement ids, the typed tool, the Python-disabled conformance fixture id and the status (`available`, `capability gap`, `needs Python` = gap).
- The matrix published in `capabilities.json` and through `uzpainter://capabilities`.
- A build check that fails when a required operation has no row, a row names a tool that is not registered, or an `available` row has no conformance fixture id.

## Dependencies
- Parent: `phase2.8_mcp-server`.
- Prerequisites: `phase2.4_supervisor-worker` (DAG input of P2-MCP), `phase2.6_mcp-typed-tool-families`.
- Consumers: `phase2.9_pilot-belt` (Python-disabled round), `phase5.2_parity-report-mcp-conformance` (full conformance at release).

## Acceptance
- Every INT-02 operation has a row; rows for operations not yet implemented show `capability gap`; no row is satisfied by `run_python`.
- The build check fails on a missing row, an unregistered tool or an available row without a fixture id.

## Impact
- Affected specs: `mcp` (operation matrix)
- Affected code: capability manifest generator, build checks
- Breaking change: NO
- User benefit: the owner and agents see at any time which required operations are reachable without Python
