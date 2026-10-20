# Proposal: phase2.4_supervisor-worker

## Why
P2-SUPERVISOR in `docs/dag.md` (critical path), implementing D1 (`docs/architecture/02-runtime-topology.md`; decision 003 with decisions 021, 022 and 025). AI agents are UzPainter's only operators and talk to it through a client-launched stdio MCP server; the session must survive worker faults (native aborts in the vendored DX12 command list, device removal or loss, stalled GPU waits), retries must never duplicate or silently replay a mutation, and long operations need durable jobs. Requirements: ARC-01, ARC-02, INT-01, INT-04, INT-05, INT-07, BAK-05, NFR-01, NFR-06 (`docs/prd.md`). This parent is the integration and acceptance task; the work is split into three children.

## What Changes
- Pipe IPC, worker roles and crash/relaunch: child `phase2.1_supervisor-ipc-worker`.
- Lease, idempotency, revision precondition and ledger reconciled from persisted operation records: child `phase2.2_supervisor-admission-ledger`.
- Job model and durable terminal states: child `phase2.3_supervisor-jobs`.
- Integration evidence for `docs/architecture/02-runtime-topology.md` §7 in `parity/reports/phase2/supervisor-settling.json` (numbers only: recovery times, per-call overhead, pass/fail per case, backend, build hash).

## Dependencies
- DAG input: `phase1.25_pilot-wand` (P1-WAND).
- Children (all mandatory): `phase2.1_supervisor-ipc-worker`, `phase2.2_supervisor-admission-ledger`, `phase2.3_supervisor-jobs`.
- Consumers: `phase2.8_mcp-server` (P2-MCP) and `phase2.11_gate-g2` (G2).

## Acceptance
DAG gate: `02-…` §7 tests pass, including commit-then-die retry. Concretely: kill the worker during a long job and during a save; kill it after the durable commit and before the acknowledgement, then retry the same request (stored outcome, no second revision) and a changed request with the same key (`idempotency_conflict`); commit a non-idempotent mutation, advance beyond retention and compact, lose the supervisor ledger, then replay the original key with its original precondition and with no precondition (no new mutation), and replay a known key inside the window after the revision advanced (stored result returned); stall the GPU; disconnect and reconnect the client; compare a single-call failure, an unwrapped multi-call script failure and a failing native `Transaction`; inject device removal on DX12 and device loss on Vulkan; with `--allow-python` off `run_python` is rejected at the IPC boundary (its absence from the tool list is verified by `phase2.5_mcp-transport-registry`); with an unavailable backend `gpu_backend_unavailable` is returned while GPU-free operations run. Assert MCP session alive, last committed revision correct, no duplicate commit, recovery time recorded, per-call overhead measured against the single-process `run` path for the same command corpus, on both backends. Decision 221 sequences the backends: this task's acceptance is DX12 plus every case that needs no GPU device on Vulkan; Vulkan device loss, the Vulkan GPU stall and the §7 re-run with a real Vulkan device are acceptance obligations of `phase3.1_vulkan-compute-parity` (items 3.4 and 4.1), kept `pending` in the settling report until then. The parent closes only when all three children pass.

## Impact
- Affected specs: `supervisor`
- Affected code: supervisor, worker lifecycle, IPC, ledger, job model
- Breaking change: NO
- User benefit: a fault-tolerant runtime under the MCP server, the precondition for P2-MCP and the pilots
