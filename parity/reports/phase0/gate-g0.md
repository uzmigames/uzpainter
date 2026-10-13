# G0 "Contract frozen" — gate record

Task `phase0.10_gate-g0` (`docs/dag.md` G0, D14; `docs/roadmap.md` Phase 0 gate, rules 2, 3 and 6). Evaluated on 2026-10-11 on the owner's machine (Windows 11, NVIDIA GeForce RTX 4090, Zig 0.15.2, Python 3.13) on the tree of commit `90ce14c` with the working-tree changes of that moment (another task's edits under `src/evaluator/`, `tests/evaluator/`, `build.zig` and its new `parity/semantics/masks-levels.json`; none in any evidence file named below). Numbers and hashes only: every recorded Painter output stays in the private store. SHA-256 values are of the file bytes in that tree.

**Result: G0 held open.** All six joined items are accepted and archived; every G0 clause of `docs/roadmap.md` is evidenced below; the guard blocks nothing and every manifest hash of the current and the superseded envelope resolves in the private store. The owner holds the gate open in strict sequence order (2026-10-11) until the Phase 0 tasks of §5 close, and the full test suite is not green (§4).

**Closed 2026-10-13 on the owner's order.** Every Phase 0 task except this gate is archived (§5), the gate checks of §4 are green again on `6a311f4`, and `phase0.10_gate-g0` is archived as `.rulebook/archive/2026-10-13-phase0.10_gate-g0/`.

## 1. Oracle envelope used by this gate (decision 037)

`parity/envelopes/registry.json` (SHA-256 `361bd5262722c43fd4aaa274726e1ec4cfeb6f05ed88afc296f287e01f342762`): current envelope `painter-12.1.5+js-api.1.1.20` (envelope SHA-256 `1497f6497fd984cadeb5a136ce73fc41c7c601b7a6652c76fa6670be7bc4e406`, promoted 2026-10-11), superseded `painter-12.1.0+js-api.1.1.20` (`0f0c8d5fec0381271fa5df51b448311b6a2e322cc96372fb97b999cb15fd119c`, kept as history). No candidate, no quarantine.

| Manifest root | Envelope | Manifests (phase0 / phase1 / tier0 / tier3) | Listed blobs | Golden records | Environment records | `verify` |
|---|---|---|---|---|---|---|
| `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests` | current | 81 (21 / 1 / 59 / 0) | 2686, all `available` | 81 | 81 | exit 0 |
| `parity/manifests` | superseded | 82 (21 / 1 / 59 / 1) | 2686, all `available` | 81 | 81 | exit 0 |

The one manifest of `parity/manifests` without blobs is `tier3/render-procedure/qualification-sphere.json` (the Iray leg, §5; reported `stale` by the drift report). Whole store: `python -m tools.parity.store verify` exit 0 (`store ... parity-store: ok`).

## 2. Clauses of `docs/roadmap.md` G0

| Clause | Evidence | Verdict |
|---|---|---|
| Approved-source index published | §3.1 | met |
| Tier 0 goldens admitted (blobs private, hashes public) | 59 Tier 0 manifests in each root, every hash `available` (§1); 53 stable, 6 save-reopen-unstable (study `20261011t073506z`, §3.5) | met |
| First `parity/semantics/*.json` fits with residuals | 6 files, 51 entries (§3.2); `python -m tools.parity.fit check` exit 0, every fit re-checked against the current envelope | met |
| Vendored render core builds standalone | §3.7 (`phase0.5_vendor-render-core`); `python -m tools.vendoring.vendor_check` exit 0 at this gate, 97 vendored files | met |
| Hardware `selftest` green on the owner's machine | §3.3; re-run at this gate by `tests/toolchain/test_toolchain_gate.py` (§4) | met |
| WARP probe completed and reported | §3.3: `warp` completed, qualified, 4 of 4 checks passed | met |
| Feasibility reports published (procedural; normal convention) | §3.4, §3.6 | met |
| Oracle envelope recorded and stability study published (decision 034) | §3.5 | met |

The Iray capture procedure and references are not a G0 clause (decision 033).

## 3. Joined items

### 3.1 P0-SOURCES — `phase0.1_approved-source-index`

Archived `.rulebook/archive/2026-10-10-phase0.1_approved-source-index/`.

| Evidence | SHA-256 |
|---|---|
| `docs/approved-sources.md` | `eefb153e516326197c195bffb51da28d74bb7d295d78e6d8868536d51b0b0e49` |

### 3.2 P0-TIER0 — `phase0.8_tier0-goldens`

Archived `.rulebook/archive/2026-10-10-phase0.8_tier0-goldens/` with its children `phase0.6_tier0-semantics-goldens`, `phase0.6_tier0-defaults-templates`, `phase0.6_tier0-api-probes`, `phase0.7_tier0-stability-fits` (all archived 2026-10-10). 59 Tier 0 goldens, each recorded at least twice; first fits: 51 entries (6 exact, 43 calibrated with residuals, 2 gaps moved to `phase0.7_tier0-semantics-ui-cases`).

| Evidence | SHA-256 |
|---|---|
| `parity/reports/phase0/tier0-goldens.md` | `95b2676a8fc97b423544737d3f6d886c8b4c354566d03c1e13af45716b88750c` |
| `parity/reports/phase0/tier0-stability.md` | `a6140d2f523531ceaab6de7f7d11d09e4586ede5b786418e8fb1f227bd275b17` |
| `parity/semantics/blend-modes.json` (34 entries) | `7b172ec7d3b8c3a9f4d01b5f40c0d8d8f388de53b075a8f3c1370998fbe72ef4` |
| `parity/semantics/evaluator-profile.json` (4) | `324fc6b87391d84984e9ecef5b28abb79d951e31d8c0fb0b92c936b529a60710` |
| `parity/semantics/srgb-transfer.json` (3) | `b2cdff89e4822bfd22b39d77c0cd078ed753f316b6d3376e6fb22ef815b44137` |
| `parity/semantics/height-to-normal.json` (4) | `458d763c6411b120c6a2e92732a6ac6d945c284120cdc4e1ee6e7174063333f8` |
| `parity/semantics/resampling.json` (4) | `d1790f5fb128fccd60360b7a5ccfa56600f4106b091f3a23ecc5ec890e45fdf1` |
| `parity/semantics/ao-mixed.json` (2) | `d7481445707676102736388f9ea8bfbf156bd232fafa639192bcfb877e5c5659` |

### 3.3 P0-TOOLCHAIN — `phase0.8_toolchain-slice`

Archived `.rulebook/archive/2026-10-10-phase0.8_toolchain-slice/` with its children `phase0.6_toolchain-hardware-slice`, `phase0.7_toolchain-probes`, `phase0.7_toolchain-cpython`. Acceptance run: `UzPainter.exe selftest` exit 0, `hardware_slice: passed`, 14 stages passed (5 slice, 4 probes completed with WARP qualified, 5 CPython); CPython boundary qualified directly (no C-ABI fallback); Zig kept (decision 021 unchanged).

| Evidence | SHA-256 |
|---|---|
| `parity/reports/phase0/toolchain-slice.md` | `13f9dc59055bd5fba3f37ee097960a5e7753a31f204424907ccde5a7e96335a8` |
| `parity/reports/phase0/toolchain-hardware-slice.md` | `99e7e6788ea4685324b1f5068a987447ac211ae261cc1ca7092a9c97ab760aae` |
| `parity/reports/phase0/toolchain-probes.md` | `4cedda0542eb3fb2dbeb30d09010be6b6a1f695f1ac30e8e37aecb166adf11a5` |
| `parity/reports/phase0/toolchain-cpython.md` | `daada2880e5ef5d0d9bc77d054f88c7c6578535ec8b045c5bc39a1edc829465f` |

### 3.4 P0-FEAS-PROC — `phase0.6_procedural-feasibility`

Archived `.rulebook/archive/2026-10-10-phase0.6_procedural-feasibility/`. 16 goldens; go/no-go for Phase 3 scope: Position go (6 of 6 equal), Metal Edge Wear no-go (1 of 8 equal), Leather Damaged no-go (0 of 2 equal). `python -m tools.parity.feasibility check` exit 0 (16 cases reproduce the published residuals, superseded-envelope goldens). Re-run of the same comparison with the published fits against the current envelope's 16 manifests: the three verdicts are unchanged (6 of 6, 1 of 8, 0 of 2 equal); Position and Metal Edge Wear residuals equal the published ones; Leather Damaged residuals differ (its 2 goldens are `changed` in the drift report, verdict no-go under both envelopes).

| Evidence | SHA-256 |
|---|---|
| `parity/reports/phase0/procedural-feasibility.md` | `47ab430d106f2599ea2fab41e05721ffa9d92c82fc76039d3ff95c1f33ca42c2` |
| `parity/semantics/procedural-feasibility.json` | `1daac5f278875529c7c57ef5ddbb255c1ec79125698b6b97da76774c71d468d6` |

### 3.5 P0-ORACLE-ENVELOPE — `phase0.9_oracle-envelope`

Archived `.rulebook/archive/2026-10-11-phase0.9_oracle-envelope/`. Environment record on every admitted golden: 81 of 81 golden records carry an `oracle-environment` blob in each root (§1). Stability study `20261011t073506z` (current envelope): 59 goldens, 53 stable, 6 save-reopen-unstable, 0 fresh-process-unstable, 0 same-session-unstable, 0 incomplete. Canary run as the first step of the 12.1.5 refresh. Corpus drift 12.1.0 → 12.1.5: 81 goldens, 64 unchanged, 5 changed, 12 unstable, 0 unavailable, 0 new, 0 missing.

| Evidence | SHA-256 |
|---|---|
| `parity/reports/phase0/oracle-envelope.md` | `140be41441c1151b3ad86f4e9606eaaa2473a5f01debda68734f586c2fa76363` |
| `parity/reports/phase0/oracle-envelope-study-20261011t073506z.json` | `ef84e64a9e31de213563f0ea2788300bf3b8f81922b0ba47f3a073db5e22feb7` |
| `parity/reports/phase0/oracle-envelope-drift-canary-painter-12.1.5_js-api.1.1.20.json` | `c02a3e6b076c2577ed47e7ed4f501be90a0e21a9d5c44b6d4e81e99a57070306` |
| `parity/reports/phase0/oracle-envelope-drift-corpus-painter-12.1.5_js-api.1.1.20.json` | `288ad132de75357cd61df2bc017d541d479373d14f4b03033c7cfff84dd1afb3` |
| `parity/envelopes/registry.json` | `361bd5262722c43fd4aaa274726e1ec4cfeb6f05ed88afc296f287e01f342762` |
| `parity/CONTRACT.md` | `3d03b95b5784d74b99a7ffbff1e2d5416bc28c154a7e0db3ce3b3b6fc25bfec5` |

### 3.6 P0-NORMAL — `phase0.9_normal-convention-fixture`

Archived `.rulebook/archive/2026-10-10-phase0.9_normal-convention-fixture/`. 5 goldens, each recorded twice, r1 against r2 max |Δ| 0; 6 entries: 2 exact (`green-channel-directx`, `no-hit-texels`), 4 calibrated with worst max |Δ| 1 (`green-channel-opengl`, `tangent-frame-per-fragment`, `tangent-frame-per-vertex`, `tangent-frame-project-default`). `python -m tools.parity.normal_convention check` exit 0. All 5 goldens are `unchanged` from 12.1.0 to 12.1.5 in the corpus drift report, so the residuals hold for the current envelope.

| Evidence | SHA-256 |
|---|---|
| `parity/reports/phase0/normal-convention.md` | `f9a92564d3728e415c6330c696a88ec2d3c44f1865acd45f4bbea359012db316` |
| `parity/semantics/tangent-frame.json` | `d49694bf9d9ba64f4a4ba417f47e34cf0a1b2978d0b71e0a7a7c7b686f5506cf` |

### 3.7 Items reaching G0 through the joined items

All archived 2026-10-10 under `.rulebook/archive/`:

| Task | Evidence | SHA-256 |
|---|---|---|
| `phase0_owner-decisions` | `docs/open-questions.md` | `1f78a152e9e031488dfa483bda2fb92bd90c9e58e2362b9ba85782e75cfff30a` |
| `phase0.2_parity-contract` | `parity/CONTRACT.md` | `3d03b95b5784d74b99a7ffbff1e2d5416bc28c154a7e0db3ce3b3b6fc25bfec5` |
| `phase0.3_painter-oracle-recorder` | `parity/RECORDER.md` | `5c5d43c7ab5d8c569ddee3307e4ff93d187f50b33a2b503d1a9d1b710dce5a6d` |
| `phase0.5_private-oracle-store` | `parity/STORE.md` | `859a405d61bb30d39b9e4c361809588e0c9214d05fe69e89fb5a0d6655ca380d` |
| `phase0.5_private-oracle-store` | `parity/GUARD.md` | `d815131d6619cd2e067674ddc6a65fee7e79b0ffe49a5739cfc5ed20582d986c` |
| `phase0.5_vendor-render-core` | `thirdparty/uzengine-render-core/MANIFEST.json` | `d59ad237b4a5fe5c95b0fdf1f3a4cddab6dacd679f8d8ae63a58bf8c0ddf9267` |
| `phase0.5_vendor-render-core` | `thirdparty/uzengine-render-core/ORIGIN.md` | `8b42c081d0c5e248e9307ed4575e29cea69b14b0a13f2d7d49eaa914d966979c` |
| `phase0.5_vendor-render-core` | `thirdparty/uzengine-render-core/MODIFICATIONS.md` | `92144cae4bcece2649ef95dec1accde86d016efff6d3f3c310a0743c39f39689` |

## 4. Checks on the gate tree

| Check | Result |
|---|---|
| `python -m tools.parity.guard` | exit 0; store-hash rule against the store (1026 hashes); 2490 files checked, 0 blocked |
| `python -m tools.parity.store verify parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests` | exit 0; 81 manifests, 2686 blobs `available` |
| `python -m tools.parity.store verify parity/manifests` | exit 0; 82 manifests, 2686 blobs `available` |
| `python -m tools.parity.store verify` | exit 0; store ok |
| `python -m tools.parity.fit check` | exit 0; 6 fits re-checked against `painter-12.1.5+js-api.1.1.20` |
| `python -m tools.parity.feasibility check` | exit 0; 16 cases |
| `python -m tools.parity.normal_convention check` | exit 0 |
| `python -m tools.vendoring.vendor_check` | exit 0; 97 vendored files |
| `python -m ruff check .` | exit 0 |
| `python -m ruff format --check .` | exit 0; 202 files |
| `python -m mypy` | exit 0; 202 source files |
| `python -m pytest` | not green: 1396 passed of 1410 (`tests/parity` alone: 699 passed, `test_gate_g0.py` 3 passed); 3 failed and 11 not run, all in `tests/store/test_store_inspect.py` (`phase1.7_store-inspect-census`): its native cases each ran into the 900 s per-case timeout, and a direct `uzp-store-inspect-tests.exe run inspect_fields` gave no output within 120 s, while two other full-suite runs were on the machine; cause not diagnosed |

Re-run 2026-10-13 on `6a311f4` with the archive of this gate, affected checks only (CLAUDE.md test time budget; the full suite is the coordinator's batch): `python -m pytest tests/parity/test_gate_g0.py` exit 0, 3 passed; `python -m tools.parity.guard` exit 0, store-hash rule against the store (3615 hashes), 3480 files checked, 0 blocked; `python -m tools.parity.store verify parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests` exit 0, 248 manifests, 19767 blobs `available`; `python -m tools.parity.store verify parity/manifests` exit 0, 82 manifests, 2686 blobs `available`; `python -m tools.parity.store verify` exit 0, store ok. `phase1.7_store-inspect-census`, whose timeouts kept the 2026-10-11 suite red, is archived (2026-10-13).

## 5. Phase 0 tasks not archived (roadmap rule 3 exemptions)

24 Phase 0 tasks are archived under `.rulebook/archive/`. Open, by recorded decision:

| Task | Status | Exemption source |
|---|---|---|
| `phase0.9_render-reference-capture` (P0-FEAS-RENDER) | pending | decision 033: no longer a G0 join; entry gate of P3-PATHTRACER |
| `phase0.6_render-reference-procedure` | in progress (6 of 17 items) | decision 033 (child of P0-FEAS-RENDER) |
| `phase0.7_render-reference-captures` | pending | decision 033 (child of P0-FEAS-RENDER) |
| `phase0.8_render-reference-fits` | pending | decision 033 (child of P0-FEAS-RENDER) |
| `phase0.7_tier0-semantics-ui-cases` | pending | owner answer to q1 of `phase0.6_tier0-semantics-goldens`, 2026-10-10 (`.rulebook/archive/2026-10-10-phase0.6_tier0-semantics-goldens/.metadata.json`): "That child task must not block G0." |

Since closed (2026-10-13): `phase0.7_tier0-semantics-ui-cases` was archived 2026-10-11 (`d086d44`); the three Iray-leg children were archived 2026-10-11 and `phase0.9_render-reference-capture` on 2026-10-13 (`6a311f4`, the owner signed the P3-PATHTRACER entry gate record). No Phase 0 task other than this gate remains open.

## 6. Capability manifest

No capability manifest existed before `phase1.3_document-model` delivered its generator (`generate_capabilities.py`, through its child `phase1.2_docmodel-capability-manifest`); Phase 0 had none to regenerate under roadmap rule 3.

## 7. Phase 1 duration Hypothesis (owner Q14, roadmap rule 6)

Measured: Phase 0 ran from 2026-10-10 (first commit) to 2026-10-11 (last joined item archived), 2 days of elapsed time against the 3–4 week Hypothesis; Phase 1 started 2026-10-10 and has 19 of 42 tasks archived at this gate. Revised Phase 1 Hypothesis: 1–2 weeks of elapsed time (was 5–6 weeks). Extrapolated, not measured: task throughput so far is mostly single-component work; integration (P1-WAND, the Tier 1 goldens and G1's fault-injection checks) has no measurement yet. Decision 035 replaces this Hypothesis with a measured re-forecast when P1-WAND completes.
