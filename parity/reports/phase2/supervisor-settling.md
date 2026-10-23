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

## Acceptance run (2026-10-20, item 4.1)

Worktree `wt/close-p2` at bbc83b54, Debug `UzPainter.exe` SHA-256 `c416de4fd732000f0acc819e1106157b174d922ccde25a30a00617d8a1f7467c` (both runs). Each run merged its backend into `supervisor-settling.json`, replacing the 2026-10-12 entries. A Painter recording session was using the GPU during the DX12 run, which may explain its longer recoveries; no threshold is set (decision 150).

| Run | Command | Result |
|---|---|---|
| Vulkan workers, no device | `UZP_NO_GPU=1 UZP_SETTLING_REPORT=… UZP_MCP_CONTRACT_REPORT=… python -m pytest tests/supervisor -m "settling or mcp_contract"` | 26 passed, 2 skipped (DX12 device tests), exit 0, 221 s |
| DX12 (one GPU run) | `UZP_SUPERVISOR_BACKEND=dx12 UZP_SETTLING_REPORT=… python -m pytest tests/supervisor -m settling` | 14 passed, 1 skipped (`gpu_backend_unavailable`), exit 0, 138 s |
| Guard | `python -m pytest tests/parity/test_guard.py -k "supervisor_settling or mcp_contract or settling_merge"` | 23 passed, exit 0 |

| Case | Vulkan (no device), recovery ms | DX12, recovery ms |
|---|---|---|
| Worker killed during a long job | pass, 116 / 74 | pass, 1097 / 1428 |
| Worker killed inside a save's checkpoint commit | pass, 399 | pass, 399 |
| Worker killed inside a full save's compaction | pass, 386 | pass, 476 |
| Worker terminated from outside | pass, 69 | pass, 1246 |
| `abort()` with minidump | pass, 97 | pass, 702 |
| Access violation with minidump | pass, 112 | pass, 1326 |
| Commit-then-die retry | pass, 73 | pass, 1093 |
| Known-key replay inside the window | pass | pass |
| Replay beyond retention, compacted, ledger lost | pass | pass |
| GPU stall | pending, decision 121 | pass, 2493 |
| Device removal / loss | pending, decision 121 | pass, 511 |
| Client disconnect and reconnect | pass, reconnect 1380 | pass, reconnect 1020 |
| Single call vs unwrapped script vs native `Transaction` failure | pass | pass |
| `--allow-python` off | pass | pass |
| Unavailable backend | pass | not applicable |

Per-call overhead (ms; MCP median, `run` median, overhead median, p90, max): Vulkan read 17.7, 0.009, 17.7, 20.1, 21.7; Vulkan insert 56.2, 49.5, 6.7, 34.5, 59.4; DX12 read 20.6, 0.008, 20.6, 44.7, 1583; DX12 insert 64.4, 40.0, 24.3, 478, 1825.

## Vulkan hardware rerun (2026-10-23)

`UZP_SUPERVISOR_BACKEND=vulkan UZP_SETTLING_REPORT=parity/reports/phase2/supervisor-settling.json python -m pytest tests/supervisor -q` passed all 192 tests in 376.22 s, with no skips. The normal session fixture built a fresh Debug executable and recorded SHA-256 `90c0ecc09ccb4a2dad94cb7904940af5dde2d4cfbfd1c57dd202d833fa4bae29`. This reruns the full architecture 02 section 7 suite with a real Vulkan device; the unavailable-device case explicitly injects its own fixture.

All 15 Vulkan cases in the JSON report now pass. GPU stall recovered in 352.114 ms and injected device loss in 317.773 ms, each with one replacement worker on the same backend and the last committed revision preserved. The hook injects loss into that worker's Vulkan queue; it does not fault the driver. Export regressions also verify no partial publication, publication-lock deadlines, recovery after Python catches an export error, and recovery after a background export fails while the worker command loop is idle. The idle-worker regression separately passed on DX12.

The two 50-call overhead corpora recorded median overhead of 11.537 ms for reads and 12.063 ms for mutations; p90 was 12.447 ms and 18.786 ms respectively. The JSON merge preserves the earlier DX12 evidence. Three additional Vulkan admission tests, collected after this full run began, passed against the same executable: heap-derived admission without the memory-budget extension, invalid fixture rejection, and an inert fixture without `--test-faults`.

The earlier tables remain historical evidence of the device-free Vulkan lane. Their pending device-loss and stall entries are superseded by this hardware run, satisfying the supervisor portion of phase3.1_vulkan-compute-parity item 3.4; the task's other acceptance obligations remain separate.

## Open

- **Hosted CPU lane.** Removed by the owner (decision 200). The local CPU-lane run above is the evidence of the children's item 4.1.
- **G1.** phase1.25_pilot-wand is not accepted yet. The children and this task close on decision 326's recorded scope split (2026-10-20); the Wand's parity stays with phase1.25 and G1.
- **HTTP reconnect.** Reconnecting to a running supervisor over HTTP is phase2.5_mcp-transport-registry's (decision 150).
