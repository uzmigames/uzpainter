# `phase2.4_supervisor-worker`: settling evidence (local run)

This task is the parent of P2-SUPERVISOR (`docs/architecture/02-runtime-topology.md` §7). It collects the local evidence of its three children and the parent's own settling run. The numbers are in `supervisor-settling.json` beside this file. Decisions 150 and 151; the children's decisions are 120, 121, 138-141.

All runs were on the owner's machine on 2026-10-12, worktree `wt/p2-sup-worker`, Debug `UzPainter.exe` SHA-256 `4fb4d965aa6019050e7d71bd6566094442450549c3ded628b746f7120a70e611` (both runs built the same bytes). No Painter recording is involved: the supervisor is UzPainter's own control plane.

## Parent runs

| Run | Command | Result |
|---|---|---|
| CPU lane (Vulkan workers, no device) | `UZP_NO_GPU=1 UZP_SETTLING_REPORT=… python -m pytest tests/supervisor` | 81 passed, 4 skipped (the DX12 tests), exit 0, 164 s |
| DX12 (one GPU run) | `UZP_SUPERVISOR_BACKEND=dx12 UZP_SETTLING_REPORT=… python -m pytest tests/supervisor -m settling` | 14 passed, 1 skipped (`gpu_backend_unavailable` needs a backend without a device), exit 0, 59 s |
| Guard and store sanity | `python -m pytest tests/parity/test_guard.py tests/python/test_pyapi_cli.py::test_run_with_an_unavailable_backend` | 52 passed, exit 0 |

While the tests were written, the first run of `test_settling.py` gave 6 passed and 1 failed. The failure was a wrong assertion in the test: a traceback of source given as a string has no source lines. After the fix, that node, the disconnect node and one guard node passed (3 passed, exit 0).

## Cases (02 §7)

Every case asserts that the MCP session stays alive, the last committed revision is correct and nothing is committed twice. Recovery is the supervisor's own `recovery_ms` (death detected to project reopened). It is measured on the Debug build.

| Case | Test | Vulkan (no device) | DX12 |
|---|---|---|---|
| Worker killed during a long job (before and after its commit point) | `test_supervisor_jobs.py::test_a_worker_killed_during_a_long_job_is_interrupted_and_resolved` | pass, 233 / 551 ms | pass, 414 / 337 ms |
| Worker killed inside a save's checkpoint commit | `test_settling.py::test_worker_killed_during_a_save[kill_during_save-incremental]` | pass, 1076 ms | pass, 363 ms |
| Worker killed inside a full save's compaction | `test_settling.py::test_worker_killed_during_a_save[kill_during_compaction-full]` | pass, 87 ms | pass, 384 ms |
| Worker terminated from outside | `test_supervisor_mcp.py::test_worker_killed_from_outside` | pass, 69 ms | pass, 332 ms |
| `abort()` with minidump | `test_supervisor_mcp.py::test_native_fault_writes_a_minidump_and_relaunches[abort]` | pass, 106 ms | pass, 333 ms |
| Access violation with minidump | `…[seh]` | pass, 143 ms | pass, 349 ms |
| Commit-then-die retry (stored outcome, then `idempotency_conflict`) | `test_supervisor_admission.py::test_lost_acknowledgement_returns_the_stored_outcome` | pass, 174 ms | pass, 327 ms |
| Known-key replay inside the window after the revision advanced | `test_supervisor_admission.py::test_a_replay_beyond_retention_with_a_lost_ledger_never_mutates` | pass | pass |
| Replay beyond retention, compacted, ledger lost (with and without precondition) | same test | pass | pass |
| GPU stall (`timeout`, relaunch) | `test_supervisor_gpu.py::test_device_fault_…[gpu_stall-…]` | pending, decision 121 | pass, 368 ms |
| Device removal / loss (`device_removed`, relaunch) | `test_supervisor_gpu.py::test_device_fault_…[remove_device-…]` | pending, decision 121 | pass, 401 ms |
| Client disconnect and reconnect | `test_settling.py::test_client_disconnect_and_reconnect` | pass, reconnect 1218 ms | pass, reconnect 1453 ms |
| Single call vs unwrapped script vs native `Transaction` failure | `test_settling.py::test_single_call_script_and_transaction_failures` | pass | pass |
| `--allow-python` off: not listed, `python_disabled` | `test_settling.py::test_python_disabled_through_mcp` | pass | pass |
| Unavailable backend: `gpu_backend_unavailable` while export, save and a mutation run | `test_settling.py::test_unavailable_backend_through_mcp` | pass | not applicable (DX12 has a device) |

The reconnect time runs from the new supervisor's start until its reopened project answers. It includes the worker's start, so DX12's is longer: it creates a device.

## Per-call overhead against `UzPainter.exe run`

Each snippet ran as 50 `run_python` calls through the supervisor and 50 times in one `run` script, after 3 warm-up calls each, on copies of one project. Overhead is each MCP round trip minus the in-process median, in ms. No threshold is set (decision 150).

| Backend | Snippet | MCP median | `run` median | Overhead median | p90 | max |
|---|---|---|---|---|---|---|
| Vulkan | read (`project.revision()`) | 12.6 | 0.012 | 12.6 | 16.4 | 32.7 |
| Vulkan | one fill-layer insert | 52.0 | 34.1 | 17.9 | 40.5 | 48.4 |
| DX12 | read | 11.4 | 0.009 | 11.3 | 12.8 | 30.1 |
| DX12 | one fill-layer insert | 36.0 | 21.8 | 14.2 | 25.4 | 44.2 |

## Children's local evidence

| Child | Local run | Result |
|---|---|---|
| `phase2.1_supervisor-ipc-worker` (decisions 120, 121) | CPU lane 2026-10-12. DX12 on `ad945b0`: 2 passed, 2 failed. Fixed in `be67f28`; affected rerun of 5 nodes, 33.84 s. | CPU green. DX12 rerun 5 passed, exit 0; `UzPainter.exe` `bf830725…0e85`, `uzp-render-tests.exe` `7a46b27c…1b82`. |
| `phase2.2_supervisor-admission-ledger` (decisions 138, 139) | `UZP_NO_GPU=1 python -m pytest tests/supervisor`, worktree `wt/p2-admission-ledger` | 66 passed, 4 skipped, exit 0, 61 s |
| `phase2.3_supervisor-jobs` (decisions 140, 141) | `UZP_NO_GPU=1 python -m pytest tests/supervisor tests/capabilities/test_capabilities.py`, worktree `wt/p2-jobs` | 101 passed, 1 failed, 4 skipped, exit 1, 82 s. The failure was an expected `busy` message. After the fix, 8 passed, exit 0, 139 s. |

The parent's CPU run above repeats all three children's `tests/supervisor` cases on the merged tree: 81 passed, exit 0.

## Open

- **Vulkan device cases.** The Vulkan device-loss hook and GPU stall wait for the Vulkan device: phase3.1_vulkan-compute-parity items 2.2 and 3.4 (decision 121). They are `pending` in the report.
- **Hosted CPU lane.** It runs on the owner's push. It is the children's item 4.1, attached here.
- **G1.** phase1.25_pilot-wand is not accepted yet, so no prerequisite item is checked.
- **HTTP reconnect.** Reconnecting to a running supervisor over HTTP is phase2.5_mcp-transport-registry's (decision 150).
