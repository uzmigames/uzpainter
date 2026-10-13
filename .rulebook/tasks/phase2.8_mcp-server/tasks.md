## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase2.4_supervisor-worker
- [ ] 1.2 Child accepted: phase2.5_mcp-transport-registry
- [ ] 1.3 Child accepted: phase2.6_mcp-typed-tool-families
- [ ] 1.4 Child accepted: phase2.7_mcp-operation-matrix

## 2. Implementation
- [ ] 2.1 Synthetic UzmiGames-authored project and long-job fixtures for the contract suite (no oracle data)
- [ ] 2.2 Contract suite driving the server through MCP clients on stdio and HTTP
- [ ] 2.3 Report writer for `parity/reports/phase2/mcp-contract.json`

## 3. Tests
- [ ] 3.1 Two writers: the second receives `lease_held`
- [ ] 3.2 Lost acknowledgement with retry; worker killed after the durable commit and before the acknowledgement, then the same request (stored outcome, no second revision) and a changed request with the same key (`idempotency_conflict`)
- [ ] 3.3 Reconnect in HTTP mode with lease and job state intact
- [ ] 3.4 Path outside the roots rejected; stale revision returns `stale_revision {expected, current}`
- [ ] 3.5 Beyond retention + compaction + lost ledger: replay with original precondition and with none creates no mutation; known-key replay inside the window returns the stored result despite a newer revision
- [ ] 3.6 Capability resource lists every unavailable family and every operation still needing Python as a gap

## 4. Acceptance
- [ ] 4.1 DAG gate met: Phase 2 contract fixtures pass on synthetic project/job fixtures and unavailable later families are reported as capability gaps; report written to `parity/reports/phase2/mcp-contract.json`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Notes (children's evidence)
- phase2.5_mcp-transport-registry (decisions 158, 159; tasks.md §6 there). Its §3 tests are green on Vulkan workers:
  - `tests/supervisor/test_supervisor_transports.py`: stdio frames under logging load; schema, reference and key refusals; roots with a junction, `file:///` and `\\?\`; `run_python` opt-in and partial changes; HTTP Origin, Host and bearer refusals, the bind usage errors, a reconnect keeping lease and job state, and a clean Ctrl+Break.
  - `test_registry.py`, `test_roots.py` and `test_transport_http.py` (pure Python).
  - These cover the HTTP reconnect of 3.3 here and the out-of-root path of 3.4.
- phase2.6_mcp-typed-tool-families (decisions 164, 165; tasks.md §6 there). Its §3 tests are green on Vulkan workers with Python disabled:
  - `tests/supervisor/test_typed_tools.py`: every family listed with its capability status; the stack edit with its receipts; Project, Texture sets, Resources, Stack, Export, Mesh and Render (the downscaled capture block); LAY-06 through MCP; LAY-07 through `sync_stack`; `batch` stop-on-error with per-call results; long tools with and without `wait`; `busy` and `wait_idle`; the gap families refused before admission, also on the worker's own pipe; the resources and prompts.
  - `tests/supervisor/test_registry.py` (pure Python): the argument-value gate failing closed, `status`, `capabilities`, `batch` keys, the image block, the resources.
  - These cover 3.6 here: `uzpainter://capabilities` lists every unavailable family and gated value as a gap.
