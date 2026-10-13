# 186. The MCP contract suite tags the children's tests, adds the missing fixture and transport pairs, and closes 4.1 on local evidence

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.8_mcp-server, phase2.5_mcp-transport-registry, phase2.6_mcp-typed-tool-families, phase2.7_mcp-operation-matrix, phase2.4_supervisor-worker

## Context

`phase2.8_mcp-server` is the parent and acceptance task of P2-MCP. Its DAG gate (`docs/dag.md`, `docs/architecture/11-mcp-server.md` §7 Phase 2) asks for typed-tool, transport, lease, error and retry contract fixtures on synthetic project and job fixtures, and for the unavailable later families to be reported as capability gaps. The fixtures are:

- two writers;
- a lost acknowledgement with retry;
- a worker killed after the durable commit and before the acknowledgement;
- a reconnect in HTTP mode;
- a path outside the roots;
- a stale revision;
- replays beyond retention with a lost ledger, and inside the window.

The capability resource must also show any operation that still needs Python as a gap.

The three children are merged on main. Each has only its 1.1 open, because phase2.4_supervisor-worker is not accepted: it waits on G1, on the Vulkan device cases (decision 121) and on the hosted CPU lane. Several fixtures already run in the children's stdio tests. The parent suites of phase2.4 and phase2.3 (decisions 150 and 162) tag the children's tests and never copy them. A stdio supervisor has exactly one client, and its lease owner is implicit. In HTTP mode, owners are explicit (`lease_acquire`).

The model panel's votes (one round):

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 Tag the children's tests with `mcp_contract(fixture, transport=...)`; a new file adds only the missing pairs; the report never shows a pass for a fixture that did not run | AGREE | AGREE | AGREE |
| C2 The lost acknowledgement is the client losing the reply of a committed mutation, a fixture apart from commit-then-die (the worker killed) | PARTLY | AGREE | AGREE |
| C3 Two writers and the reconnect run on HTTP only | AGREE | PARTLY | AGREE |
| C4 4.1 is checked on local CPU-lane evidence; 1.1-1.4 stay open, so the task is not archived; the hosted lane is noted, not claimed | AGREE | AGREE | AGREE |
| C5 The live `uzpainter://capabilities` shows the needs-Python rows equal to the `run_python` rows (none today), none available, and the named later families as gaps; no fake row is injected | AGREE | AGREE | AGREE |

Refinements adopted:

- C2: the commit is observed independently of the reply. The test reads `job_status` until it reports the commit, and only then drops the reply (GPT). The lost-acknowledgement fixture also sends a changed request with the same key and expects `idempotency_conflict` (Kimi).
- C3: `lease_held` is asserted with its fields, with `active_job` set while the holder's long job runs, and the non-holder's read still works (GPT).
- C5: the named family rows are looked up by operation, so a missing row fails (GPT). No totals are asserted, because the counts change as the matrix grows (Kimi).

Rejected:

- A `reason` on `not_run` entries (Kimi). The report's closed fixture-to-transport table already says where each fixture runs, and the guard's schema stays numbers and identifiers.
- A stdio "second client" negative case (Kimi). A stdio supervisor has one pipe pair. No second client can attach, so there is nothing to refuse.

## Decision

1. **Suite.**
   - `tests/supervisor/test_mcp_contract.py` runs each fixture against a `Supervisor` on stdio (`Mcp`) or on a resident Streamable HTTP server (`Http`). Each client answers `call(name, arguments)` with the structured content.
   - Children's tests that already run a fixture on a transport carry `@pytest.mark.mcp_contract(<fixture>, transport=...)` where they are:
     - `test_supervisor_admission.py`: commit-then-die, and both replays, on stdio;
     - `test_supervisor_transports.py`: roots on stdio, and the HTTP reconnect.
2. **Synthetic fixtures (2.1).**
   - The project is UzmiGames' plane, created at 256 px and saved once through typed MCP tools with Python disabled. Each test opens its own copy.
   - The long job is the Debug build's `test_job` under `--test-faults`.
   - Mutations are the typed `layer_insert`. Every supervisor runs with Python disabled on a Vulkan worker (no device).
3. **Fixtures and transports** (`tools/parity/settling/mcp_contract.py`, `FIXTURES`).
   - `two_writers` and `http_reconnect` run on HTTP only.
   - Every other fixture runs on both transports: `lost_acknowledgement_retry`, `commit_then_die_retry`, `path_outside_roots`, `stale_revision`, `replay_inside_window`, `replay_beyond_retention_lost_ledger` and `capability_gaps`.
   - The lost acknowledgement on stdio: the client ends the session after the job's commit is reported. A new session on the same ledger then retries. On HTTP: the request's own connection drops after the commit is reported, and the owner reconnects and retries.
4. **Report (2.3).**
   - `UZP_MCP_CONTRACT_REPORT=<path>` merges a run into `parity/reports/phase2/mcp-contract.json`. Each entry is one fixture on one transport: pass, fail or `not_run`, the test count, seconds, the date and the exe's SHA-256.
   - A fixture fails when any of its tests fails. A fixture that has not run is `not_run`.
   - The repository guard checks the file against its closed schema.
5. **Closure.**
   - 2.x, 3.x, 4.1 and 5.x are checked on the local CPU-lane run.
   - 1.1-1.4 stay open until phase2.4 and the three children are accepted (G1, decision 121's Vulkan device cases, the hosted CPU lane). The task is therefore not archived.
   - The hosted CPU lane's run follows the owner's push. It is noted, not claimed.
