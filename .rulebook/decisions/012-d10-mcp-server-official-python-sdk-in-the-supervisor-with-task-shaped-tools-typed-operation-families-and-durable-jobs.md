# 12. D10 MCP server: official Python SDK in the supervisor with task-shaped tools, typed operation families and durable jobs

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Native MCP is an owner requirement; the official Python SDK v2 has no Tasks support yet; the community bridge's 79 tools were bypassed for raw Python (05-resolution.md D10).

## Decision

Official Python MCP SDK (pinned) hosted in the supervisor; stdio default, loopback Streamable HTTP optional with auth; compact task-shaped tools (sync_stack, bake, export, capture, ...) plus typed operation families covering every required operation so run_python can be disabled; run_python opt-in trusted; persistent job ids with job_status/result/cancel; Tasks extension later; per-project mutation lease; idempotency_key and expected_revision on mutating tools; independent path roots; receipts enumerating changes. See docs/architecture/11-mcp-server.md.

## Alternatives Considered

- Handwritten C++ MCP - rejected: no official SDK
- One tool per inventory row - rejected: unusable catalogue
- Long tail only through arbitrary Python (Claude round 1) - rejected after Astra's coverage argument

## Consequences

Phase 2 gate: the belt round completes through MCP with Python disabled.
