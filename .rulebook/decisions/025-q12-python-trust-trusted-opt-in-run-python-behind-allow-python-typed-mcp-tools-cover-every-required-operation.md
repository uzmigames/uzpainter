# 25. Q12 Python trust: trusted opt-in run_python behind --allow-python; typed MCP tools cover every required operation

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Owner question Q12 asked whether run_python and run are trusted opt-in execution or OS-enforced restricted execution, and what must stay available through typed MCP with Python disabled. D10 (decision 012) defines the MCP server and its typed operation families. Owner answer of 2026-10-10 (docs/open-questions.md Q12).

## Decision

run_python is registered only when the supervisor starts with --allow-python and is documented as trusted local execution; path roots constrain the structured tools, not Python. Every required operation is reachable through typed MCP tools and operation families, proven by a conformance fixture per operation family and by the belt round completed through MCP with Python disabled. See docs/architecture/11-mcp-server.md.

## Alternatives Considered

- OS-enforced restricted execution for scripts - not chosen: trusted opt-in
- Python enabled by default - rejected: opt-in only
- Long-tail operations reachable only through Python - rejected (D10)

## Consequences

An operation that still needs Python is shown as a gap by the capability resource and fails the Phase 2 Python-disabled belt round until a typed tool covers it.
