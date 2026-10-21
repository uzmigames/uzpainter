## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase3.1_baker-request-model, phase3.2_baker-normal - recorded scope split under decision 326's rule: neither prerequisite is accepted. phase3.1 stays open on its prerequisite (phase2.10), item 3.1 (Tier 0 goldens of the defaults and property metadata) and 4.1; phase3.2 on its prerequisites, item 2.1 (the Normal domains outside SubSampling 1 / DilationWidth 0 / identity transforms), 2.4 and its Tier 2b items. None of that is read by the evidence, the accounting, the receipt or the publication of section 6; nothing here claims either task accepted

## 2. Implementation
- [x] 2.1 Produce the evidence maps `raw`, `hit`, `coverage`, `miss`, `extension` per usage under `cache/`, regenerable, never altering the compatible map - section 6
- [x] 2.2 Compute used-surface accounting: seven disjoint classes (straight hit, cage hit, centre miss, hidden, ring extended, ring without hit neighbour, repaired), `fallback_texels`, `padding_texels`, `changed_used_texels`, per-part hits/misses/Z<0 texels - section 6
- [x] 2.3 Write `BakeReceipt` with every field of `06-baking.md` §4 plus `{revision, evaluator_profile, compat_profile, app_version, resource_hashes}` - section 6
- [x] 2.4 Implement atomic publication per `(texture set, input revision)`: bind all enabled usages with `baked {…}` provenance and store the receipt, or bind nothing - section 6
- [ ] 2.5 Implement the native bake `Job` (id, progress, `cancel()`, terminal `Success | Cancel | Fail`, per-baker error detail) with cancellation checked at tile boundaries and acknowledged immediately
- [ ] 2.6 Implement `bake_async(texture_set) → StopSource`, `bake_selected_textures_async()`, `project.is_busy()` and the `BakingProcessAboutToStart/Progress/Ended` events on the Python dispatcher thread
- [ ] 2.7 Register MCP `bake_start {sets[], wait?}` on the job ledger with `job_status`, `job_result` and `job_cancel`; the receipt states stopped before or after publication

## 3. Tests
- [x] 3.1 Accounting tests on plane, sphere, bevelled cube with highs and a part with a buried face: exact expected counts per class and the conservation identity (classes sum to `coverage.conservative_texels`) - section 6
- [x] 3.2 Receipt schema and content test: every field present, hashes match stored maps, `fidelity_evidence` set correctly with and without an enabled fallback - section 6
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

## 6. Evidence, accounting, receipt and publication (2026-10-21, decision 347)
- 2.1: `src/bake/bake_accounting.*` `EvidenceFiles`/`WriteEvidence`: per usage `map`, `raw` (none for Thickness), `hit`, `coverage`, `miss`, `extension` under `cache/bake/<key>/<Usage>/`; PNG for integer maps and masks, the `UZPF32` container for float maps. A pure function of request and result: `evidence_regenerated` writes, deletes and regenerates them byte for byte with the compatible map unchanged.
- 2.2: `AccountUsage`: the conservative used surface (open texel square overlaps a UV triangle, `BakeResult::used_surface`), the seven disjoint classes per usage, `fallback_texels` (opt-in `BakeRequest::neutral_fallback`, Normal only), `padding_texels`, `changed_used_texels`, `surface_modified`, `fidelity_evidence`, per-part hits/misses/Z<0 (`BakeResult::texel_part`). Conservation is checked inside and asserted by the tests.
- 2.3: `src/bake/bake_receipt.*` `BuildReceipt`/`ReceiptJson`/`ReceiptBytes`: every field of `06-baking.md` section 4 plus `{revision, evaluator_profile, compat_profile, app_version, resource_hashes}` and `parity_status`.
- 2.4: `src/bake/bake_publication.*` `PublishBake`: one transaction per `(set, input revision)`; refuses a stale revision, a resolution mismatch, a Normal convention other than the project's, a diagnostic result and every usage without a bindable map (float maps, ID labels, Thickness), then binds AO (L16) and Normal (RGB16) with `baked {...}` provenance and the receipt as a resource. Native only; Python/MCP (2.6, 2.7) stay open.
- 3.1: `accounting_plane`, `accounting_sphere` (cube-sphere), `accounting_bevel`, `accounting_buried_face`: exact per-class counts from the fixtures' geometry and the conservation identity.
- 3.2: `receipt_content`: field sets, map/raw hashes against the evidence files, settings hash, cage and mask hashes, `fidelity_evidence` without fallback, with fallback and on the diagnostic path. `publication_atomic` covers 2.4.
- CPU only (Embree): `tests/bake/test_bake_feasibility.py` and `tests/bake/test_baking_project.py`; ruff and mypy on the touched Python. Logs: `tmp/scratch/bake-receipt/`. Items 2.5-2.7, 3.3-3.6, 4.1 and the tails stay open; every usage stays `pending-evidence`.
