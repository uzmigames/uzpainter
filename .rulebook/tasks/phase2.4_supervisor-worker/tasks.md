## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand
- [ ] 1.2 Child accepted: phase2.1_supervisor-ipc-worker
- [ ] 1.3 Child accepted: phase2.2_supervisor-admission-ledger
- [ ] 1.4 Child accepted: phase2.3_supervisor-jobs

## 2. Implementation
- [x] 2.1 Integration test harness running the `02-…` §7 scenarios end to end through the supervisor's stdio MCP session against a real worker on DX12 and Vulkan
- [x] 2.2 Per-call overhead benchmark: the same command corpus through the supervisor and through the single-process `run` path, on both backends
- [x] 2.3 Settling report writer for `parity/reports/phase2/supervisor-settling.json` (numbers, hashes and pass/fail only)

## 3. Tests
- [x] 3.1 Worker killed during a long job and during a save: session alive, last committed revision correct, recovery time recorded
- [x] 3.2 Commit-then-die: retry of the same request returns the stored outcome with no second revision; changed request with the same key returns `idempotency_conflict`
- [x] 3.3 Beyond retention + compaction + lost ledger: replay with original precondition and with none creates no mutation; known-key replay inside the window after the revision advanced returns the stored result
- [ ] 3.4 GPU stall, DX12 device removal and Vulkan device loss: recovery without duplicate commit
- [x] 3.5 Client disconnect and reconnect: lease and ledger consistent, no duplicate commit
- [x] 3.6 Single-call failure vs unwrapped multi-call script failure vs failing native `Transaction`: committed calls and partial-change receipts as specified in `02-…` §5
- [x] 3.7 `--allow-python` off: `run_python` rejected at the IPC boundary; unavailable backend: `gpu_backend_unavailable` while GPU-free operations run

## 4. Acceptance
- [ ] 4.1 DAG gate met: `02-…` §7 tests pass including commit-then-die retry, on both backends, with the settling report written to `parity/reports/phase2/supervisor-settling.json`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## 6. Notes (scope splits and evidence)
- Recordings: none. The supervisor is UzPainter's own control plane; no Painter behaviour is reproduced.
- 1.1-1.4: left open on purpose. phase1.25_pilot-wand (G1) is not accepted. The three children are merged on main, and each stays open only on G1 and the hosted CPU lane (their item 4.1, whose results are attached here).
- 2.1: the children's MCP tests that settle a 02 §7 case carry `@pytest.mark.settling(<case>)`. `tests/supervisor/test_settling.py` adds the missing cases: kill inside a save's commit and inside a compaction, disconnect and reconnect, the three-way failure comparison, `python_disabled`, `gpu_backend_unavailable`, and the overhead benchmark. `UZP_SUPERVISOR_BACKEND` selects the backend. The Vulkan worker has no device before phase3.1 (decision 121), so on Vulkan every GPU-free case runs (decision 150).
- 2.2: 50 `run_python` calls per snippet (a read, and one fill-layer insert) against the same source run in one `UzPainter.exe run` script, 3 warm-up calls each. Overhead medians: 12.6 and 17.9 ms on Vulkan, 11.3 and 14.2 ms on DX12. The Debug build is named by its hash, and no threshold is set (decision 150).
- 2.3: `tools/parity/settling/report.py` merges each run per case and backend. It writes cases not run as `not_run` and Vulkan device cases as `pending` (decision 121). The repository guard checks the report against a closed schema.
- 3.1: a Debug `UzPainter.exe` compiles the store fault hooks. The worker's `kill_during_save` and `kill_during_compaction` act inside the next `project_save` only (decision 151).
- 3.4: open. GPU stall and DX12 device removal pass (368 and 401 ms recovery). The Vulkan device-loss and stall variants wait for phase3.1_vulkan-compute-parity items 2.2 and 3.4 (decision 121).
- 3.5: on stdio, a disconnect ends the session. Reconnects of HTTP clients to a running supervisor are phase2.5_mcp-transport-registry's (decision 150).
- 3.1-3.7, 5.3 (local runs 2026-10-12, worktree `wt/p2-sup-worker`, `UzPainter.exe` SHA-256 4fb4d965aa6019050e7d71bd6566094442450549c3ded628b746f7120a70e611):
  - `UZP_NO_GPU=1 python -m pytest tests/supervisor` (Vulkan workers): 81 passed, 4 skipped, exit 0, 164 s.
  - `UZP_SUPERVISOR_BACKEND=dx12 python -m pytest tests/supervisor -m settling` (the one GPU run): 14 passed, 1 skipped (`gpu_backend_unavailable` needs a backend without a device), exit 0, 59 s.
  - `tests/parity/test_guard.py` plus `test_pyapi_cli.py::test_run_with_an_unavailable_backend`: 52 passed, exit 0.
  - The children's evidence and every number are in `parity/reports/phase2/supervisor-settling.md` and `.json`.
- 4.1: open. It waits on the Vulkan device cases (decision 121), on the hosted CPU lane (the owner's push) and on the children's acceptance (G1).
