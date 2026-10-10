## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand
- [ ] 1.2 Child accepted: phase2.1_supervisor-ipc-worker
- [ ] 1.3 Child accepted: phase2.2_supervisor-admission-ledger
- [ ] 1.4 Child accepted: phase2.3_supervisor-jobs

## 2. Implementation
- [ ] 2.1 Integration test harness running the `02-…` §7 scenarios end to end through the supervisor's stdio MCP session against a real worker on DX12 and Vulkan
- [ ] 2.2 Per-call overhead benchmark: the same command corpus through the supervisor and through the single-process `run` path, on both backends
- [ ] 2.3 Settling report writer for `parity/reports/phase2/supervisor-settling.json` (numbers, hashes and pass/fail only)

## 3. Tests
- [ ] 3.1 Worker killed during a long job and during a save: session alive, last committed revision correct, recovery time recorded
- [ ] 3.2 Commit-then-die: retry of the same request returns the stored outcome with no second revision; changed request with the same key returns `idempotency_conflict`
- [ ] 3.3 Beyond retention + compaction + lost ledger: replay with original precondition and with none creates no mutation; known-key replay inside the window after the revision advanced returns the stored result
- [ ] 3.4 GPU stall, DX12 device removal and Vulkan device loss: recovery without duplicate commit
- [ ] 3.5 Client disconnect and reconnect: lease and ledger consistent, no duplicate commit
- [ ] 3.6 Single-call failure vs unwrapped multi-call script failure vs failing native `Transaction`: committed calls and partial-change receipts as specified in `02-…` §5
- [ ] 3.7 `--allow-python` off: `run_python` rejected at the IPC boundary; unavailable backend: `gpu_backend_unavailable` while GPU-free operations run

## 4. Acceptance
- [ ] 4.1 DAG gate met: `02-…` §7 tests pass including commit-then-die retry, on both backends, with the settling report written to `parity/reports/phase2/supervisor-settling.json`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
