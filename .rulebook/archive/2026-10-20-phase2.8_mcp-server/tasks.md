## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase2.4_supervisor-worker — accepted: archived as accepted in `.rulebook/archive/2026-10-20-phase2.4_supervisor-worker/` (e276fda2)
- [x] 1.2 Child accepted: phase2.5_mcp-transport-registry — accepted: archived in `.rulebook/archive/2026-10-20-phase2.5_mcp-transport-registry/` (e42cb825)
- [x] 1.3 Child accepted: phase2.6_mcp-typed-tool-families — accepted: archived in `.rulebook/archive/2026-10-20-phase2.6_mcp-typed-tool-families/` (5e68a8fe)
- [x] 1.4 Child accepted: phase2.7_mcp-operation-matrix — accepted: archived in `.rulebook/archive/2026-10-20-phase2.7_mcp-operation-matrix/` (1325dfaa)

## 2. Implementation
- [x] 2.1 Synthetic UzmiGames-authored project and long-job fixtures for the contract suite (no oracle data)
- [x] 2.2 Contract suite driving the server through MCP clients on stdio and HTTP
- [x] 2.3 Report writer for `parity/reports/phase2/mcp-contract.json`

## 3. Tests
- [x] 3.1 Two writers: the second receives `lease_held`
- [x] 3.2 Lost acknowledgement with retry; worker killed after the durable commit and before the acknowledgement, then the same request (stored outcome, no second revision) and a changed request with the same key (`idempotency_conflict`)
- [x] 3.3 Reconnect in HTTP mode with lease and job state intact
- [x] 3.4 Path outside the roots rejected; stale revision returns `stale_revision {expected, current}`
- [x] 3.5 Beyond retention + compaction + lost ledger: replay with original precondition and with none creates no mutation; known-key replay inside the window returns the stored result despite a newer revision
- [x] 3.6 Capability resource lists every unavailable family and every operation still needing Python as a gap

## 4. Acceptance
- [x] 4.1 DAG gate met: Phase 2 contract fixtures pass on synthetic project/job fixtures and unavailable later families are reported as capability gaps; report written to `parity/reports/phase2/mcp-contract.json`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## 6. Notes (children's evidence)
- phase2.5_mcp-transport-registry (decisions 158, 159; tasks.md §6 there). Its §3 tests are green on Vulkan workers:
  - `tests/supervisor/test_supervisor_transports.py`: stdio frames under logging load; schema, reference and key refusals; roots with a junction, `file:///` and `\\?\`; `run_python` opt-in and partial changes; HTTP Origin, Host and bearer refusals, the bind usage errors, a reconnect keeping lease and job state, and a clean Ctrl+Break.
  - `test_registry.py`, `test_roots.py` and `test_transport_http.py` (pure Python).
  - These cover the HTTP reconnect of 3.3 here and the out-of-root path of 3.4.
- phase2.6_mcp-typed-tool-families (decisions 164, 165; tasks.md §6 there). Its §3 tests are green on Vulkan workers with Python disabled:
  - `tests/supervisor/test_typed_tools.py`: every family listed with its capability status; the stack edit with its receipts; Project, Texture sets, Resources, Stack, Export, Mesh and Render (the downscaled capture block); LAY-06 through MCP; LAY-07 through `sync_stack`; `batch` stop-on-error with per-call results; long tools with and without `wait`; `busy` and `wait_idle`; the gap families refused before admission, also on the worker's own pipe; the resources and prompts.
  - `tests/supervisor/test_registry.py` (pure Python): the argument-value gate failing closed, `status`, `capabilities`, `batch` keys, the image block, the resources.
  - These cover 3.6 here: `uzpainter://capabilities` lists every unavailable family and gated value as a gap.
- phase2.7_mcp-operation-matrix (decision 182; tasks.md §6 there). Its §3 tests are green:
  - `capabilities.json` carries `operation_matrix`, 106 rows, one per required operation (25 INT-02, 81 ARC-14). Today 62 rows are `available` and 44 are `capability gap`. No row is `needs Python`, and none resolves to `run_python`.
  - `uzpainter://capabilities` publishes the matrix unchanged.
  - `tests/capabilities/test_operation_matrix.py` (CPU lane): completeness, fixture collection, the build check's failures and the derived statuses.
  - `tests/supervisor/test_operation_matrix.py` (Vulkan workers, Python disabled): the registered-tool snapshot against a live worker; the published matrix; new fixtures for inline-config and OpenEXR export, `isolate_layer`, display, shader and camera, and the mask-effect gaps.
  - These add the "operation still needing Python" half of 3.6 here: such a row is `needs Python`, a gap, in `uzpainter://capabilities`.

## 7. Notes (this task, decision 186)
- Recordings: none. The MCP server is UzPainter's own control plane; no Painter behaviour is reproduced.
- 1.1-1.4: left open on purpose. phase2.4_supervisor-worker is not accepted: it waits on G1, on the Vulkan device cases (decision 121) and on the hosted CPU lane. The three children are merged on main and each has only its 1.1 open for that reason. The task is not archived until they are accepted.
- 1.1-1.4 (decision 200, 2026-10-13): the hosted CPU lane is removed and no longer a condition of phase2.4, which waits on G1 and the Vulkan device cases (decision 121).
- 1.1-1.4 (decision 221, 2026-10-13): the Vulkan device cases are no longer a condition of phase2.4_supervisor-worker; they are acceptance obligations of `phase3.1_vulkan-compute-parity` (items 3.4 and 4.1), which removes the acceptance cycle phase3.1 → phase2.10 → phase2.8 → phase2.4 → phase3.1. phase2.4 is held only by G1 (phase1.25_pilot-wand) through its children.
- 2.1: the synthetic fixtures are in `tests/supervisor/test_mcp_contract.py`: UzmiGames' plane created at 256 px and saved through typed MCP tools with Python disabled (`contract_project`, one copy per test), and the Debug `test_job` as the long job (`LONG_JOB`). No oracle data.
- 2.2: `test_mcp_contract.py` drives each fixture through a `Supervisor` on stdio (`Mcp`) or a resident Streamable HTTP server (`Http`), with Python disabled on Vulkan workers. The children's tests that already run a fixture are tagged `@pytest.mark.mcp_contract(<fixture>, transport=...)`, not copied: commit-then-die and both replays on stdio (`test_supervisor_admission.py`), roots on stdio and the HTTP reconnect (`test_supervisor_transports.py`). Two writers and the reconnect run on HTTP only, because a stdio supervisor has one client.
- 2.3: `tools/parity/settling/mcp_contract.py` writes `parity/reports/phase2/mcp-contract.json` from a run with `UZP_MCP_CONTRACT_REPORT=<path>` (hook in `tests/supervisor/conftest.py`). It lists pass, fail or `not_run` per fixture and transport. The repository guard checks it against its closed schema (`tools/parity/guard/guard.py`, tests in `tests/parity/test_guard.py`).
- 3.1-3.6: every fixture passes on every transport it runs on: 16 entries, all `pass` (`parity/reports/phase2/mcp-contract.md`). 3.2's lost acknowledgement is the client losing the reply after the commit is reported, a fixture apart from commit-then-die (decision 186, C2).
- 4.1: met on the local CPU lane (Debug `UzPainter.exe` SHA-256 `cad31237…15f9`) with the report written and guard-valid. The hosted CPU lane is removed (decision 200); the local CPU lane is the evidence.
- 5.1: `docs/architecture/11-mcp-server.md` §7 (the evidence), `parity/reports/phase2/mcp-contract.md`, decision 186.
- 5.3 (2026-10-12, worktree `wt/p2-mcp-server`):
  - `UZP_NO_GPU=1 UZP_MCP_CONTRACT_REPORT=… python -m pytest tests/supervisor -m mcp_contract`: 12 passed, 2 failed, exit 1, 132 s. Both failures were mistakes in the new HTTP tests: the running jobs were read from `status` instead of `supervisor_status`, and the export root was missing.
  - Rerun of those nodes and of the changed stdio lost-acknowledgement node: 3 passed, exit 0.
  - `tests/parity/test_guard.py` in two disjoint invocations: 10 + 69 passed, exit 0.
  - ruff, `ruff format --check` and mypy on the touched files: clean.
- 1.1-1.4, 4.1 (2026-10-20, worktree `wt/close-p2` at bbc83b54, Debug `UzPainter.exe` SHA-256 `c416de4fd732000f0acc819e1106157b174d922ccde25a30a00617d8a1f7467c`): phase2.4 and the three children are archived as accepted (e276fda2, e42cb825, 5e68a8fe, 1325dfaa). The contract suite re-ran in the same command as phase2.4's Vulkan settling lane, `UZP_NO_GPU=1 UZP_SETTLING_REPORT=… UZP_MCP_CONTRACT_REPORT=… python -m pytest tests/supervisor -m "settling or mcp_contract"`: 26 passed, 2 skipped (the DX12 device tests), exit 0, 221 s (log `tmp/scratch/close-p2/vulkan.log`). `parity/reports/phase2/mcp-contract.json` was rewritten from that run: 16 entries, all `pass`. `tests/parity/test_guard.py -k "supervisor_settling or mcp_contract or settling_merge"`: 23 passed, exit 0.
