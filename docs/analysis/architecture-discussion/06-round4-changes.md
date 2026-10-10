# 06 — Round-4 changes (2026-10-10)

Round 4 applies two inputs to the final documentation set under `docs/`: the owner's answers of 2026-10-10 to the questions of `05-resolution.md` §4 (recorded in `docs/open-questions.md` and as rulebook decisions under `.rulebook/decisions/`), and Astra's final review of the set, `docs/analysis/reviews/docs-set-astra-review.md` (verdict "reject for archival; resubmit after correction"; 23 findings: 3 blockers, 15 major, 5 minor). Where an owner answer and a review finding pointed in different directions, the owner answer governs and the finding is marked "superseded by owner". This file is the change record; the binding text is in the `docs/` files it names. `05-resolution.md` stays the round-3 record, and where it disagrees with `docs/`, `docs/` governs.

Abbreviations: `prd` = `docs/prd.md`, `vision` = `docs/vision.md`, `README` = `docs/README.md`, `roadmap` = `docs/roadmap.md`, `dag` = `docs/dag.md`, `open-questions` = `docs/open-questions.md`, `LIC` = `docs/licensing-and-clean-room.md`; two-digit numbers (`07 §2`) are files under `docs/architecture/`. Decision numbers refer to `.rulebook/decisions/`.

## A. Owner answers of 2026-10-10

| Q | Answer | Docs changed | Decision |
|---|---|---|---|
| Q1 Equality contract | Exact equality is the rule; any divergence passes only through an owner-approved exception with evidence, recorded in the exception register. No preset tolerances; diagnostic metrics never grant an exception | prd ACC-01, G-04, VIS-06, ARC-10; vision; open-questions; 04 §3, §7; 05 §3, §6; 07 §4; 14 §1, §5; dag P0-CONTRACT | 017 |
| Q2 Render reference | Painter's Iray is the render-parity target, not the realtime viewport. Clean-room path tracer (public path-tracing literature; NVIDIA's MDL specification and the BSD-3 MDL SDK allowed; nothing from Adobe or Iray internals) on DX12 DXR and Vulkan ray tracing. Converged references captured on the owner's machine into the private oracle store with scene, camera, environment, sample count and seed fixed where Painter exposes them. Iray is stochastic, so pixel-exact equality is not achievable; every Tier 3 residual goes through the Q1 register. The realtime viewport stays as human preview and fast check | vision; prd ACC-01, CLR-01, CLR-05, VIS-06, ARC-06, ARC-09, ARC-10, §16; open-questions; README; 01 §1; 07 (reworked around Iray); 10 §7; 11 §2; 14 §1, §3, §4; LIC §2–§4; 13 §2.3, §4.1; dag P0-FEAS-RENDER, P2-PREVIEW, P3-PATHTRACER | 018 (supersedes 008) |
| Q3/Q4 Shader and procedural route, Adobe content | Closed by decision 002: Apache-2.0, clean room, no Adobe content, project-private snapshots for migration only | open-questions (dated 2026-10-10); 10 §6 (alias table no longer conditional) | 002 |
| Q5 Scope and milestone labelling | Brush strokes are out of scope (Painter's Python API does not expose them); no stroke engine anywhere; paint layers remain layers receiving bitmaps and projections (LAY-12). Milestones named by proven scope; remaining gaps (arbitrary `.sbsar`, UV tiles, warp, auto-unwrap) visible in the capability manifest; no "full replacement" claim while a required gap is open | vision; prd OWN-01, OWN-03, LAY-12, §16, §18 item 2; open-questions; 01 §2; 04 §1; 05 §5; 09 §1; 10 §3; 11 §2, §7; roadmap rule 7; dag (P4-STROKES removed, corpus migration assumption) | 019 (supersedes 004) |
| Q6 Migration mechanism | Rebuild through Painter's documented API while it is installed, proven by output equality; no `.spp` reader | vision; prd G-03, §16; open-questions; 03 §7; 09 §5; 14 §2 | 020 |
| Q7 Pilot order | Wand v1 → Belt v5 → Tunic v10 | prd OWN-03; open-questions; roadmap; dag | 016 |
| Q8 Engine relationship | Zero dependency on UzEngine. UzPainter vendors only the rendering code it needs from a clean commit (never from files of an in-progress merge), keeps the Apache-2.0 licence and records attribution; known defects (glTF 32/48-byte stride) fixed in the copy or the path avoided. No `runtime.lib` link, pin, patch queue, upstream obligation or submodule; own build (Zig-first unless the vendored subset dictates otherwise). UzEngine may consume UzPainter as a submodule later, not now | vision; prd OWN-02, LIC-02, ARC-06, ARC-07, ARC-08, §16, §17; open-questions; README; 01; 02 §1; 04 §7; 07 §1, §3.5; 08; 12 §1–§5; 13 §1–§3; LIC §3; dag P0-VENDOR, P1-CORE (P0-PIN removed) | 021 (supersedes 014) |
| Q9/Q9b Platform, deployment, CI | Windows 10/11 x64 only; DX12 primary plus Vulkan as the second backend on Windows; no Linux/macOS now; one-folder distribution; CPU baking on the qualified configurations, GPU required for compositing, preview and path tracing. Q9b: the owner's machine (GPU, licensed Painter) is the self-hosted GPU runner and holds the private oracle store | vision; prd OWN-08, CLR-05, NFR-01, ARC-09, §17, §18 item 1; open-questions; 01; 02; 03 §4; 06; 07 §2, §3.5; 12 §2; 13 §2.3, §5, §7; 14 §6, §7; roadmap; dag P0-TOOLCHAIN, P0-STORE, P3-VULKAN | 022 |
| Q10 Export consumers | UE 5.6 with PNG/TGA by default and optional DDS BC7/BC5; UzEngine `.uzmat` + compressed `.uztexture`; SpecularWeight reported as a consumer gap | prd OWN-06, EXP-08, §18 item 5; open-questions; README; 08; 13 §2.1, §4.1; roadmap Phase 3; dag P3-UZE, P3-UNREAL, P4-HAT8 | 023 |
| Q11 Project file | Self-contained portable file; 10 % of the matched `.spp` as candidate budget; current + previous checkpoint plus the last 50 mutation revisions | vision; prd OWN-07, SAV-01, SAV-02, NFR-04, §18 item 6; open-questions; README; 09; 11 §4; roadmap G5; dag P1-STORE | 024 |
| Q12 Script trust | Trusted opt-in `run_python` behind `--allow-python`; every required operation reachable through typed MCP tools | prd INT-02, ARC-14, §18 item 3; open-questions; README; 02 §1, §3, §7; 10 §2; 11; roadmap Phase 2; dag P2-MCP | 025 |
| Q13 Cutover governance | The Assets3D "painting is always in Substance" rule is amended after Tunic v10 passes its parity gate (G2) | vision; prd G-01, OWN-03, §18 item 9; open-questions; roadmap; dag P3-CUTOVER | 026 |
| Q14 Roadmap dates | Durations shown as labelled Hypotheses, revised at each gate | prd §18; open-questions; roadmap | 016 |
| Repository history | The private repository's first commit contains pre-sanitisation text; before the repository is made public, history is recreated clean (owner-authorised force push at that moment). Release criterion | prd §18 item 8; open-questions; LIC §5.1; roadmap G5; dag P5-HISTORY → G5 | 027 |

## B. Astra findings F01–F23

Severity as given in the review. Verdicts: **applied**, **superseded by owner** (an owner answer replaced the premise of the finding).

| Id | Severity | Verdict | Files § |
|---|---|---|---|
| F01 Preset provenance | Blocker | Applied: public recipes and presets are independently designed, with one provenance record each and a parity test before shipping; observed Painter preset content stays private | 05 §3; 08 §4; LIC §1.7, §6; dag P3-SMART; `05-resolution.md` header note |
| F02 Storage-doc internals | Blocker | Applied: Astra's replacement text; only public facts (HDF5 signature, file sizes) cited | 09 §3 |
| F03 Recorded oracle data public | Blocker | Applied: every recorded Painter output (images, API readbacks, default/template captures, Iray references) private; only hashes and independently authored expectations public | prd CLR-05; 03 §2; 04 §9; 05 §3; 06 §2; 07 §2.2, §3.3; 14 §4, §6, §9; LIC §1.6, §5.4; dag P0-CONTRACT, P0-STORE, P0-TIER0 |
| F04 Historical-source quarantine | Major | Applied: historical analyses are not implementation inputs until the approved-source index clears their exact revision | README; `docs/analysis/README.md`; LIC §2; 04 intro; 06 §2; 07 §3.1; dag P0-SOURCES |
| F05 Dependency inventory | Major | Applied: D3D12MA, fmt, SPIRV-Reflect and FLIP (`NVlabs/flip`, BSD-3, pinned, diagnostic only) inventoried; Python wheel closure "not confirmed" until verified | LIC §3; 13 §2.2, §2.5; 07 §4; 14 §4 |
| F06 Private facade entry | Major | Applied: facade holds documented symbols only; the pipeline's private capture call is served by a UzmiGames adapter shim; recorder uses the documented API plus a qualified capture procedure | prd ARC-09; 07 §2.1, §2.2; 10 §0, §2, §4; 14 §2; dag P0-RECORDER, P0-FEAS-RENDER |
| F07 WARP mandatory | Major | Applied: WARP is a probe; its failure does not fail G0; "probe completed" reported separately from "backend qualified" | roadmap G0; dag P0-TOOLCHAIN; 07 §3.5; 13 §4.2, §7; 14 §7 |
| F08 Idempotency atomicity | Major | Applied: the operation record `{project_uuid, idempotency_key, request_hash, outcome, committed_revision}` is committed in the same transaction as the revision; supervisor reconciles; `idempotency_conflict`, `outcome_unknown`; commit-then-die test | prd ARC-02, §18 item 4; 01 §2, §7; 02 §3, §5, §7; 03 §6; 09 §1, §4, §7; 11 §4, §7; 14 §8; dag P1-DOCMODEL, P1-STORE |
| F09 Script rollback | Major | Applied: one call = one transaction; a failing script reports partial commits; only a native `Transaction` is atomic across calls | 02 §5, §7; 03 §6; 10 §5; 11 §6 |
| F10 Plane identity | Major | Applied: persistent `plane_id`, `plane_chunk` table, chunk coordinates separate from UV tiles, integrity rules and test | 01 §2; 09 §1, §7 |
| F11 Multi-map publication | Major | Applied: generation directory plus one atomic pointer update; interruption tested at every step | prd EXP-06; 08 §5; dag P1-EXPORT |
| F12 Colour model | Major | Applied: declared colour configuration preserved; unsupported configurations fail explicitly (03 §1 already compliant, unchanged) | 07 §3.4; 10 §4; dag P1-PYAPI |
| F13 Hidden-window consumer path | Major | Superseded by owner (Q8): no UzEngine renderer runs in UzPainter (`engine_preview`/`SceneRenderer` removed); UzEngine output is validated by an external consumer fixture; every UzPainter capture is windowless | prd NFR-01; 01 §3, §6; 07 §1, §5; 13 §2.1, §2.4; 14 §7 |
| F14 Missing DAG prerequisites | Major | Applied: gate nodes G0–G5 chained, missing edges added, every mandatory node reaches G5; G2 excludes render parity; reporting a gap is not accepting it; packaging and final report on one build hash and dependency lock | dag; roadmap rule 2; prd §18; 07 §4 (item 5), §6; LIC §5 |
| F15 MUST clauses and proof obligations | Major | Applied: full normative text restored for LAY-06/07, BAK-07, INT-02, INT-11, ARC-14; `BakeReceipt` fields; 9-row consumer matrix; requirement-to-typed-operation matrix and Python-disabled conformance fixtures | prd LAY-06, LAY-07, BAK-07, INT-02, INT-11, ARC-14; 03 §1, §6; 04 §1; 06 §4; 08 §5.1; 10 §6; 11 §2, §6, §7; dag P2-MCP |
| F16 Iray silently waived | Major | Superseded by owner (Q2): Iray is now the render-parity target, so the non-goal is removed rather than reworded | vision; prd §16; 01 §1; 07; 14 §1, §3; decision 018 |
| F17 Blanket Phase 0 approvals | Major | Applied: Phase 0 records decisions; no blanket re-approval; only an operation that would change a decision waits | open-questions; roadmap Phase 0; dag P0-OWNER |
| F18 DAG not task-sized | Major | Applied: ids are stable parent packages split into child tasks before task creation; critical path labelled provisional and includes P3-SMART | README; dag |
| F19 Pilot phase labels | Minor | Applied: Wand v1 in Phase 1; Belt v5 and Tunic v10 in Phase 2 | roadmap; `05-resolution.md` header note |
| F20 Rejected-route wording | Minor | Applied: Astra's replacement text; no Adobe runtime adapter exists or is reserved | README (05 row); 01 §3; 05 §2 |
| F21 Fixture called ratified | Minor | Applied: "Proposed, not yet ratified" | 07 §2.3 |
| F22 CPU baking universality | Minor | Applied: CPU baking only on Windows/CPU/ISA configurations qualified for the pinned Embree build; explicit error elsewhere | prd §17; open-questions Q9; 01 §1; 06 §1; 13 §5; decision 022 |
| F23 Collapsed workloads | Minor | Applied: each recorded workload stated separately; the combined worst case is a stress fixture, not a baseline | prd NFR-03 |

The clean-room sanitiser flags of `docs/analysis/clean-room-redactions.md` were applied in the same round: 06 §2 (stored sample defaults removed; defaults captured in Phase 0 through the documented API), 09 §3 (only the HDF5 signature and the three `.spp` file sizes cited), 10 §3 (an undocumented export key removed; the gap described by behaviour).

## C. Assumptions made by the editors

Each assumption holds until the owner overrides it; overriding one is an owner decision, not an editorial change.

| Assumption | Where |
|---|---|
| Retention (Q11) also keeps every `protected` checkpoint (SAV-02, QG-05) beyond current + previous + the last 50 mutation revisions; `compact` removes older unprotected named checkpoints | 09 §4 |
| The 10 % budget (Q11) is the target the census is measured against; it becomes a release gate only after the owner confirms it with the census results | 09 §3; prd §18 item 6 |
| The shipped baking-defaults table is `assets/defaults/baking.json`, hand-written from public documentation and observation with per-entry provenance; the raw Painter capture stays private | 06 §2 |
| The Vulkan backend and Vulkan ray tracing are qualified in Phase 3 (`P3-VULKAN`, whose gate includes the Vulkan hardware selftest); Phases 1–2 and the pilots run on DX12 only, and Phase 0 only probes Vulkan availability (coordinator ruling) | roadmap Phase 3; dag P1-CORE, P3-VULKAN; 13 §4.2, §7 |
| Phase 3 duration Hypothesis 9–12 weeks; total Hypothesis 30–39 weeks | roadmap |
| A stroke-painted fixture layer is migrated as a flattened bitmap when the documented API can export it; otherwise the fixture is `not_migratable` and excluded from Tier 1 gates, with the exclusion listed in the gate record and the final report | roadmap rule 7; dag (corpus migration assumption); 14 §2 |
| The path tracer and the GPU baker use compute shaders with inline ray queries only: DXR Tier 1.1 + SM 6.6; Vulkan 1.2+ with `VK_KHR_acceleration_structure`, `VK_KHR_deferred_host_operations`, `VK_KHR_ray_query`; no DXR pipeline state objects and no `VK_KHR_ray_tracing_pipeline`; one kernel source for both backends; `PathTracerUnavailable`, no fallback. The vendored shader-table builder is not used | 07 §3.5; 13 §2.3, §4.1; dag P3-PATHTRACER |
| Iray capture: settings Painter exposes publicly are taken from the python-doc and three public Adobe help pages; undocumented settings are marked "not confirmed — Phase 0 probe"; seven-step capture; each reference recorded twice in separate sessions plus once at k·S samples; private store | 07 §2.1, §2.2 |
| The pipeline adapter that drives undocumented UI objects for review renders is not a recorder dependency unless the owner approves it in a recorded decision | 07 §2 |
| UzEngine carries no `NOTICE` file and no per-file licence headers, so "headers kept" (Q8) is met by copying unmodified files byte for byte, shipping UzEngine's `LICENSE` with the copy and naming the vendored code, copyright line and source commit in UzPainter's `NOTICE`; P0-VENDOR re-checks at the selected commit | 13 §3.3; LIC §3 |
| The glTF 32/48-byte stride defect is handled by "path avoided": that code is on the vendoring denylist and not copied; the other defects found in the subset are fixed in the copy (UZP-MOD-001…007) | 13 §2.4, §3.4; 12 §1 |
| The vendored commit is the newest commit on UzEngine `main` that passes the selection criteria at P0-VENDOR time, never the working tree (the UzEngine checkout had uncommitted edits on 2026-10-10) | 13 §3.1 |
| Q7 and Q14 are recorded under the existing decision 016 rather than new decisions | open-questions; README Status |

## D. DAG id changes

Before round 4 the DAG had 40 nodes and 60 edges; after it, 49 nodes and 98 edges, acyclic, with phase and gate names identical in `roadmap.md` and `dag.md` (static check in `dag.md`).

| Change | Rulebook task id | Alias | Reason |
|---|---|---|---|
| Removed | `phase0_engine-pin` | P0-PIN | No pin, patch queue or upstream obligation (Q8, decision 021) |
| Removed | `phase4_paint-strokes` | P4-STROKES | Brush strokes out of scope (Q5, decision 019) |
| Added | `phase0_approved-source-index` | P0-SOURCES | Approved-source index with itemised provenance audit (F04) |
| Added | `phase0_vendor-render-core` | P0-VENDOR | Render core copied from a clean UzEngine commit (Q8) |
| Added | `phase3_vulkan-backend-ray-tracing` | P3-VULKAN | Vulkan as second backend with Vulkan ray tracing (Q9) |
| Added | `phase3_path-tracer` | P3-PATHTRACER | Clean-room path tracer against Iray references (Q2) |
| Added | `phase5_clean-history` | P5-HISTORY | Clean repository history before going public (decision 027) |
| Added | `phase0_gate-g0` … `phase5_gate-g5` | G0–G5 | Explicit gate nodes joining every mandatory item, each requiring the previous gate (F14) |
| Renamed | `phase1_engine-integration-layer` → `phase1_render-core-layer` | P1-ENGINE → P1-CORE | No UzEngine integration exists any more (Q8) |
| Renamed | `phase2_parity-viewport` → `phase2_realtime-preview` | P2-VIEWPORT → P2-PREVIEW | The viewport is preview and fast check only (Q2) |
| Renamed | `phase5_assets3d-cutover` → `phase3_assets3d-cutover` | P5-CUTOVER → P3-CUTOVER | Cutover follows Tunic v10's parity gate G2 (Q13) |
| Kept, retargeted | `phase0_render-reference-capture` | P0-FEAS-RENDER | Now captures converged Iray references (Q2) |
| Kept, retargeted | `phase4_dxr-baker` | P4-DXR | Optional `GpuBaker` with `dx12_rt` and `vulkan_rt` backends (Q9) |

## E. Consistency sweep

After the parallel edits, a mechanical sweep over `docs/README.md`, `vision.md`, `prd.md`, `roadmap.md`, `dag.md`, `open-questions.md`, `licensing-and-clean-room.md` and `docs/architecture/*.md` checked stale decision ids, gate and phase names, owner-answer leftovers (viewport as target, in-process engine renderer, engine link/pin/patch queue, strokes, non-Windows targets, preset tolerances, ray-tracing pipeline as a requirement), DAG ids and document cross-references. Corrections made:

| File | Correction |
|---|---|
| prd OWN-03, §18 item 9 | G5 called the release gate, not the cutover gate; cutover is `P3-CUTOVER` after G2 |
| LIC header | Q2 cited as decision 018 (superseding 008) |
| 01 §4 | Supervisor command line carries `--gpu-backend dx12\|vulkan` and the worker `--allow-python`, as defined in 02 §1 |
| README (06 row) | Baking summary names the optional GPU baker on DX12 DXR and Vulkan ray query instead of "DXR-later" |
| 06 §1 | Capability-check extension cited at 13 §3.4 |
| 08 §3 (PNG row) | UzEngine's 8-bit PNG encoder cited at 13 §2.4 (not vendored) |
| 13 §4.2, §7; dag P3-VULKAN | Phase 0 selftest must pass on DX12 hardware and only probes Vulkan availability; Phase 1 (`P1-CORE`) evidence on DX12; the Vulkan hardware selftest and cross-backend equality belong to Phase 3 (`P3-VULKAN`), matching the DAG |
| 13 §2.1, §2.4, §3.3, §4.1; LIC §3; dag P0-VENDOR | Only rendering code is vendored (Q8): `uztexture_format.h` kept as the `.uztexture` format definition, `uztexture_format.cpp` (writer) left out and denylisted, subset now 97 files, about 28,100 lines; UzPainter writes `.uztexture` and `.uzmat` with its own code, as 01, 08 and decision 021 state |

## Notes

- All 91 pipeline rows with a MUST component still appear in the PRD at MUST; the PRD lists every requirement changed in round 4 in its §19.
- Decision 016 (D14) still mentions strokes in Phase 4; decision 019 overrides that line. The rulebook decision tool cannot edit titles and drops sections when it re-renders a decision, so 004, 008 and 014 were marked superseded by setting `supersededBy` in their metadata.
- r4-engine ran one read-only `git status --short` in the UzEngine repository despite the no-git rule; no changes were made there.
