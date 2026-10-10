## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase4.6_gate-g4, phase3.7_path-tracer, phase5.1_performance-budgets; frozen release build hash recorded

## 2. Implementation
- [ ] 2.1 Regenerate the requirement-to-typed-operation matrix from the frozen build with the capability manifest; publish it in `uzpainter://capabilities`
- [ ] 2.2 Conformance fixtures: project lifecycle (`project_create/open/save/save_as/close/inspect/recipe/revert`), texture sets, resources
- [ ] 2.3 Conformance fixtures: stack family including the Phase 4 node, effect and source kinds and paint layers receiving bitmaps and projections
- [ ] 2.4 Conformance fixtures: recipes (`sync_stack` name addressing and group-only rebuild, `apply_smart`, `batch` with stop-on-error)
- [ ] 2.5 Conformance fixtures: native bake (`bake_configure`, `bake_start`, cancellation receipt), mesh reload and certificate
- [ ] 2.6 Conformance fixtures: every export target and preset, `capture` in `painter_iray`, `painter_viewport` and each diagnostic mode, diagnostics tools
- [ ] 2.7 Conformance fixtures: jobs and lease (`job_*`, `lease_*`, `busy`, `wait_idle` timeout as a failure)
- [ ] 2.8 Mutating-fixture contract assertions: `idempotency_key` and `expected_revision` accepted; results carry `revision`, `committed_revision`, `job_id`, change lists and `warnings`; failures return structured errors
- [ ] 2.9 Result writer `parity/reports/phase5/mcp-conformance.json`: one row per matrix row with tool, fixture, outcome and build hash; a row without a typed tool reported as a release gap

## 3. Tests
- [ ] 3.1 Supervisor started without `--allow-python` on the frozen build: `run_python` absent from the tool list, and a `run_python` request on the pipe rejected with `python_disabled`
- [ ] 3.2 Every conformance fixture of §2 passes over stdio with Python disabled on the self-hosted GPU runner (DX12 and Vulkan for GPU families)
- [ ] 3.3 Matrix completeness check: every required operation has a typed tool and a fixture; the capability resource lists no required operation that needs Python
- [ ] 3.4 Negative check: a matrix row deliberately stripped of its tool in a test build is reported as a release gap and fails the suite

## 4. Acceptance
- [ ] 4.1 Full Python-disabled MCP conformance passes for every row of the requirement-to-typed-operation matrix on the frozen build; result attached to `phase5.4_parity-report`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
