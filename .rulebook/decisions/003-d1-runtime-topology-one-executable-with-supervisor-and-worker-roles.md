# 3. D1 Runtime topology: one executable with supervisor and worker roles

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Architecture discussion rounds 1-3 (docs/analysis/architecture-discussion/05-resolution.md). In stdio MCP the AI client launches the server and owns its pipes; UzEngine's DX12 command list aborts the process on repeated RHI errors and a worker death must not end the agent's session.

## Decision

UzPainter.exe --mcp is a GPU-free supervisor (official Python MCP SDK, admission, lease, job ledger, worker lifecycle); UzPainter.exe --worker owns the document, engine and embedded CPython; private named-pipe IPC reuses the tool-call JSON shapes with artifact references; run/CLI modes are single-process. Idempotency keys and revision preconditions prevent silent replay. See docs/architecture/02-runtime-topology.md.

## Alternatives Considered

- Single process embedding engine, CPython and MCP (Claude round 1) - rejected: a native fault or device removal ends the MCP session
- Python host loading an engine DLL - rejected: ties the product to a Python launcher
- Separate MCP front process plus engine worker with a different protocol vocabulary - subsumed

## Consequences

Two interpreter instances and an IPC layer; Phase 2 measures per-call overhead and verifies crash recovery (kill during bake/save, stalled fence, lost acknowledgement).
