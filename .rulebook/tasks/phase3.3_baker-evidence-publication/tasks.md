## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_baker-request-model, phase3.2_baker-normal

## 2. Implementation
- [ ] 2.1 Produce the evidence maps `raw`, `hit`, `coverage`, `miss`, `extension` per usage under `cache/`, regenerable, never altering the compatible map
- [ ] 2.2 Compute used-surface accounting: seven disjoint classes (straight hit, cage hit, centre miss, hidden, ring extended, ring without hit neighbour, repaired), `fallback_texels`, `padding_texels`, `changed_used_texels`, per-part hits/misses/Z<0 texels
- [ ] 2.3 Write `BakeReceipt` with every field of `06-baking.md` §4 plus `{revision, evaluator_profile, compat_profile, app_version, resource_hashes}`
- [ ] 2.4 Implement atomic publication per `(texture set, input revision)`: bind all enabled usages with `baked {…}` provenance and store the receipt, or bind nothing
- [ ] 2.5 Implement the native bake `Job` (id, progress, `cancel()`, terminal `Success | Cancel | Fail`, per-baker error detail) with cancellation checked at tile boundaries and acknowledged immediately
- [ ] 2.6 Implement `bake_async(texture_set) → StopSource`, `bake_selected_textures_async()`, `project.is_busy()` and the `BakingProcessAboutToStart/Progress/Ended` events on the Python dispatcher thread
- [ ] 2.7 Register MCP `bake_start {sets[], wait?}` on the job ledger with `job_status`, `job_result` and `job_cancel`; the receipt states stopped before or after publication

## 3. Tests
- [ ] 3.1 Accounting tests on plane, sphere, bevelled cube with highs and a part with a buried face: exact expected counts per class and the conservation identity (classes sum to `coverage.conservative_texels`)
- [ ] 3.2 Receipt schema and content test: every field present, hashes match stored maps, `fidelity_evidence` set correctly with and without an enabled fallback
- [ ] 3.3 Failure injection: cancel mid-bake, a baker failing on one usage, and worker kill during a bake (bake version of the P2-SUPERVISOR kill check, which Phase 2 ran on a long export) — no partial authoritative bake, last committed revision intact
- [ ] 3.4 Event-order test: `BakingProcessAboutToStart`, progress events, `BakingProcessEnded(status)` dispatched on the dispatcher thread; `is_busy()` true only while running
- [ ] 3.5 MCP native-bake cancellation fixture with Python disabled: `bake_start` then `job_cancel`; `cancelled` terminal state and receipt says before or after commit
- [ ] 3.6 Unavailable GPU backend (bake version of the P2-SUPERVISOR check, `02-…` §7): worker started with an unavailable backend returns `gpu_backend_unavailable` for GPU operations while an Embree CPU bake still runs and publishes

## 4. Acceptance
- [ ] 4.1 Acceptance: accounting and conservation exact on the analytic fixtures; publication all-or-nothing; MCP cancellation during a native bake passes

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
