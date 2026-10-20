# Proposal: phase2.5_mcp-transport-registry

## Why
Child of `phase2.8_mcp-server` (P2-MCP in `docs/dag.md`), implementing the server layer of D10 (`docs/architecture/11-mcp-server.md` §1, §2 schema rules, §4, §5, §6; decisions 012 and 025). MCP is the primary operating surface for the AI agents; every typed tool needs one transport-independent registry with validated inputs, a uniform mutation and result contract, filesystem roots on canonical paths, and `run_python` only as a trusted opt-in. Requirements: INT-01, INT-03, INT-04, INT-05, INT-07, QG-03, ARC-02, ARC-14 (`docs/prd.md`).

## What Changes
- Transports over one tool registry: stdio (default; stdout carries protocol frames only, logs go to stderr and the ledger) and Streamable HTTP on `127.0.0.1:<port>` with `--mcp-http` (Origin validation, bearer token generated at start or given by `--token`, refusal of non-loopback binding without `--allow-remote`); handlers forward to the worker over the private pipe and run in an executor so the event loop keeps serving progress and cancellation.
- Registry with input schemas (numeric bounds, enums, object references) validated before admission; results as `structuredContent` plus a short text summary; images only as content blocks of `capture`, everything else as files under the allowlisted roots.
- Uniform mutating-tool contract: `idempotency_key` and `expected_revision` accepted; a call may omit `expected_revision` only when it also omits the key, in which case the supervisor generates the key, resolves the precondition once before submission, records both in its ledger and returns both in every receipt; every result carries `revision`, `committed_revision`, `job_id` where applicable, `changed/created/hidden/imported/skipped` lists and `warnings`; structured errors `lease_held`, `busy`, `stale_revision`, `idempotency_conflict`, `outcome_unknown`, `python_disabled`, `gpu_backend_unavailable`.
- Lease at the MCP boundary: implicit for the stdio client, explicit `lease_acquire {owner}` in HTTP mode.
- Path roots `--roots project=<dir>;mesh=<dir>;bake_mesh=<dir>;resource=<dir>;export=<dir>`: paths canonicalised (absolute, reparse points resolved, `file:///` and relative forms normalised) and checked against the root of the operation; results never reference paths outside the roots; roots do not sandbox `run_python`.
- `run_python {code|path, args}` registered only when the supervisor starts with `--allow-python`; returns `result`, stdout and stderr separately; honours lease and revision rules; each API call inside is its own transaction and the error receipt reports the last committed revision and partial changes.
- Tool availability follows the build's capability manifest: a tool whose operation is a `release-gap` fails with a structured capability-gap error before any mutation and becomes available without MCP changes once its implementing package lands.

## Dependencies
- Parent: `phase2.8_mcp-server`.
- Prerequisite: `phase2.4_supervisor-worker` (DAG input of P2-MCP: stdio session hosting, admission, ledger, jobs).
- Followed by `phase2.6_mcp-typed-tool-families` and `phase2.7_mcp-operation-matrix`.

## Acceptance
- stdio framing, HTTP Origin and bearer checks, loopback-only binding and HTTP reconnect pass.
- Out-of-bound or wrongly typed inputs are rejected before admission.
- A path outside the roots (absolute, relative, `file:///`, through a reparse point) is rejected and never echoed.
- Without `--allow-python`, `run_python` is absent from the tool list; with it, results and partial-change receipts follow `11-…` §6.
- The key/precondition omission rule and the result shape hold for every mutating tool.

## Impact
- Affected specs: `mcp` (transports, registry, roots, `run_python`)
- Affected code: supervisor MCP layer in the embedded CPython (official Python MCP SDK, pinned and vendored)
- Breaking change: NO
- User benefit: one safe, validated MCP surface on stdio and HTTP
