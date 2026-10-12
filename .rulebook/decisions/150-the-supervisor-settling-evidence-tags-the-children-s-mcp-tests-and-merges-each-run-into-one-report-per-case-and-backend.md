# 150. The supervisor settling evidence tags the children's MCP tests and merges each run into one report per case and backend

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.4_supervisor-worker, phase2.1_supervisor-ipc-worker, phase2.2_supervisor-admission-ledger, phase2.3_supervisor-jobs, phase3.1_vulkan-compute-parity, phase2.5_mcp-transport-registry

## Context

phase2.4_supervisor-worker is the parent of P2-SUPERVISOR. It must run the settling cases of `docs/architecture/02-runtime-topology.md` §7 end to end through the supervisor's stdio MCP session, on DX12 and Vulkan. It must also record the recovery time of every fault case and the per-call overhead against the single-process `run` path, in `parity/reports/phase2/supervisor-settling.json`.

Its three children are merged, and most §7 cases already exist as their MCP-level tests. No Vulkan device exists before phase3.1_vulkan-compute-parity (decision 121).

Panel round (one round, shared with decision 151):

- C1 (tag the children's tests and add only the missing cases): PARTLY ×3. Count only tests that go through the supervisor's stdio session, list missing cases explicitly, and say where recovery times come from.
- C2 (Vulkan lane): AGREE ×3.
- C4 (disconnect on stdio): AGREE ×2 (Kimi, Grok), PARTLY ×1 (GPT). Wait for the worker's end and check the durable operation rows before the reconnect.
- C5 (overhead): PARTLY ×3. Warm both paths, match the project state, and avoid a p95 from 20 samples. Kimi asked for a Release build. GPT and Grok asked only that the measurement be defined.
- C6 (report safety): AGREE ×2, PARTLY ×1 (GPT). Encode `pending` and its decision explicitly, and allow only listed fields.

## Decision

1. **Harness.**
   - Each MCP-level test that settles a §7 case carries `@pytest.mark.settling(<case>)`. Pipe-level tests are not tagged.
   - `tests/supervisor/test_settling.py` adds the missing cases:
     - kill during a save and during a compaction (decision 151);
     - disconnect and reconnect;
     - the comparison of a single-call failure, an unwrapped script failure and a native `Transaction` failure;
     - `python_disabled` and `gpu_backend_unavailable` through MCP;
     - the overhead benchmark.
   - A conftest hook records each tagged test's outcome and run time, and the recoveries its supervisors reported in `supervisor_status`.
   - Under `UZP_SETTLING_REPORT`, the run merges these into the report (`tools/parity/settling/report.py`).
2. **Backends.**
   - `UZP_SUPERVISOR_BACKEND` selects the backend of the tagged MCP tests.
   - The CPU lane runs them on Vulkan workers, which report `gpu_status: unavailable`.
   - One GPU run repeats them on DX12, together with the DX12 device-fault cases.
   - The device cases on Vulkan (`gpu_stall`, `device_lost`) are listed as `pending` with decision 121, never as a pass.
   - `gpu_backend_unavailable` needs a backend without a device. On this runtime that is only Vulkan.
3. **Report.**
   - Entries are keyed by case and backend. Each carries the exe's SHA-256 and the date.
   - A case that has not run is `not_run`.
   - The file holds numbers, enums, identifiers, dates and digests only.
   - The guard checks it against a closed JSON Schema, with no extra fields allowed.
4. **Disconnect on stdio.**
   - A disconnect is the end of the client's session. The client closes stdin while a long mutating job (`test_job`) is before its commit point.
   - The test waits for the supervisor's and the worker's exit, and checks that the project file holds no operation row of the key.
   - A new supervisor on the same ledger then reopens the project. It retries the same key and precondition, which commits once, and retries again, which returns the stored outcome.
   - The lease is the new session's. The old job is terminal and committed nothing: `interrupted`, or `cancelled` before its commit point when the ended wait's cancel reached the worker before the pipe closed.
   - Reconnects of HTTP clients to a running supervisor are phase2.5's.
5. **Overhead.**
   - The same two snippets (a read, and one fill-layer insert) run as `run_python` calls through the supervisor, and as `exec` of the same source in one `UzPainter.exe run` script.
   - Both start from copies of one project at the same revision, after 3 warm-up calls.
   - Each path runs 50 timed calls per snippet.
   - Overhead = each MCP round trip minus the in-process median. The report gives its median, p90 and maximum, per backend.
   - The test fixture's Debug build is measured, and the exe's hash identifies it. No threshold is set, because no budget is specified.

## Alternatives Considered

- **Copy the children's cases into the parent.** Rejected: two copies would drift.
- **Measure the overhead on a Release build.** Rejected for now. The supervisor side is Python, and the build that ran the cases is the one the report names. A Release measurement can join the same report as further entries.

## Consequences

- phase2.4 item 4.1 stays open until the Vulkan device exists (decision 121) and the hosted CPU lane has run.
- phase2.5 adds its HTTP reconnect case to the same report.
