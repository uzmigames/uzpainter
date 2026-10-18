# 01. Requirement delivery

What exists on main `c07e787` (last commit 2026-10-13), checked against each owner requirement in `docs/vision.md:9-17` and `docs/prd.md` §2. "Delivered" means usable output with evidence. Implemented code alone does not count.

## Scorecard

| Requirement | Source | State | Evidence |
|---|---|---|---|
| AI-operated, headless, read-only preview at most (OWN-01) | `prd.md:18`, `:185` | **Delivered, usable.** 67 MCP tools over stdio and HTTP, a worker that recovers after a kill, idempotent retries and no window unless asked | `parity/reports/phase2/practical-e2e.md:43`, `:76-81`; decision 252 |
| Painter's functionality (layers, smart materials, rendering, export, Python, MCP) (OWN-01) | `prd.md:18` | **Partial.** Fills, groups, masks, levels, blends and bitmap or uniform sources work. Smart materials, procedurals, bake and the Iray render do not exist yet. 546 of 1,580 capability entries are `supported` (35 %) | `practical-e2e.md:43`; `README.md:21-26` |
| Render system built from UzEngine, zero dependency (OWN-02) | `prd.md:19` | **Delivered** for DX12: a vendored copy, own Zig build, attribution in `NOTICE` | `NOTICE:7-19`; `build.zig:3`, `:65`; `parity/reports/phase0/gate-g0.md` |
| Complete replacement in Assets3D (OWN-03) | `prd.md:20` | **Not delivered.** No piece is produced by UzPainter. G1 (Wand) is open, G2 (Belt, Tunic) has no accepted item, and the cutover task has 0 of 19 items done | `README.md:35-40`; `.rulebook/tasks/phase3.1_assets3d-cutover/tasks.md` |
| Mirror the Python API and MCP (OWN-04) | `prd.md:21` | **Delivered for the pilot's subset.** The three Assets3D scripts run unchanged through the adapter (create, sync, capture) | `practical-e2e.md:105-112` |
| Native bake from a high-poly mesh (OWN-05) | `prd.md:22` | **Not started.** Only external mesh maps are accepted. Embree appears only in the hardware self-test. All 13 baker tasks have 0 items done | `README.md:26`; `src/selftest/embree_stage.cpp`; `.rulebook/tasks/phase3.4_baker-*` |
| Export: Painter PBR plus Unreal ORM plus UzEngine, compressed (OWN-06) | `prd.md:23`, `:123` | **Partial.** PNG 8/16 and OpenEXR are written exactly for the fitted cases. The Unreal, glTF and UzEngine presets and the BC7/BC5 writers are not started (0 items in 7 tasks) | `practical-e2e.md:55-65`; `.rulebook/tasks/phase3.*_{unreal,uze}*` |
| Compact `.spp`-like save (OWN-07) | `prd.md:24` | **Delivered, budget open.** A self-contained `.uzp` with revisions and fault-injection tests. On today's partial content it is 6-53 % of the matched `.spp`, so the 10 % candidate budget holds for 1 of 5 projects | `parity/reports/phase1/project-store.md:58-64`, `:84` |
| Standalone Windows `.exe`, DX12 primary, Vulkan second (OWN-08) | `prd.md:25`, `:219` | **DX12 only.** `UzPainter.exe` runs on the owner's machine. The Vulkan device is refused at creation. Packaging and the clean-machine check are not started | `src/render/device.cpp:59-61`; `.rulebook/tasks/phase3.1_vulkan-compute-parity/tasks.md` (0/23); `phase5.2_packaging` (0/18) |
| Same textures as Painter (ACC-01, texture) | `prd.md:26` | **Proven on fitted primitives, not on a piece.** Tier 0 goldens and seven exceptions are in place. The Wand's island interiors are exact on four maps, but its pinned five-map export is refused as a whole | `parity/exceptions.json`; `practical-e2e.md:116-121`; `.rulebook/tasks/phase1.25_pilot-wand/tasks.md:22`, `:26` |
| Same render as Painter's Iray (ACC-01, VIS-06) | `prd.md:146`, `:203` | **Research only.** 69 Iray references and a noise-floor report exist. `painter_iray` answers `PathTracerUnavailable`. No fitted lobe reproduces held-out pixels | `practical-e2e.md:72`; `parity/reports/phase0/gate-p3-pathtracer-entry.md:5`; `plan-purpose-review/02-delivery-risks.md` F-004 |
| Clean room, Apache 2.0 (LIC, CLR) | `prd.md:27-35` | **Enforced** (see `03-governance-and-guardrails.md` F-012) | `docs/licensing-and-clean-room.md:11`, `:19` |

## F-001 - The original proposal is intact and stated honestly

**Evidence:** `docs/vision.md:5` and `:9-17` still state the nine owner requirements unchanged. `docs/prd.md:18-26` binds each one to an acceptance test. `README.md:6-8` says UzPainter "is not yet a complete Painter replacement or a qualified release", and `README.md:33` says "Gates measure usable results, not task counts". Scope cuts were made by recorded owner decisions (strokes Q5, no `.spp` reader Q6, Windows only Q9). They do not shrink the proposal.

**Impact:** Positive. The purpose has not been lost in the documents. Nobody claims more than the evidence shows. The plan's acceptance is still output parity, not feature names.

**Confidence:** High.

## F-002 - Nothing usable for production has shipped: no gate past G0, and the simplest pilot's export is refused

**Evidence:** G1 is open (`README.md:38`). The Wand is the Phase 1 smoke fixture, and its pinned five-map export is refused as a whole since decision 245 (`.rulebook/tasks/phase1.25_pilot-wand/tasks.md:22`). Its Tier 1 test ends `XFAIL` (`:26`). The practical run says: "No export containing the Normal map succeeds on a real mesh, under any padding" (`parity/reports/phase2/practical-e2e.md:35`, row B18 at `:180`). Assets3D still paints every piece in Substance Painter.

**Impact:** High. Today the pipeline cannot use UzPainter for any real asset, because every Assets3D delivery needs a Normal map. The refusal is correct under the parity contract: it is better than a wrong map. But the owner's main goal, replacement, has not produced a single delivered piece after four days of high-volume work (538 commits, 203 decisions).

**Confidence:** High.

## F-003 - The foundation under the proposal is real and works end to end

**Evidence:** The practical run (`practical-e2e.md:41-81`) drove `UzPainter.exe` through the official MCP SDK: 67 tools, worker-kill recovery (`:81`), idempotency conflicts (`:77`), job cancel with no partial files (`:79`), save/reopen with an identical layer list (`:51`). The three unchanged Assets3D scripts ran through the adapter (`:105-112`). A user export of the Wand's four document maps equals Painter's R9 maps on every island-interior texel, 0 differing (`:116-121`). Of the 19 findings, 17 were fixed on main the same day (`:163-181`; B7, B12 and B13 by commit `8ae6848`, decision 248). B17 was confirmed as Painter's own behaviour, and B18 became an explicit refusal.

**Impact:** Positive. The AI-operated shell (MCP, facade, store, supervisor, export publication) is the part of the proposal that is closest to done. The remaining work is mostly parity and missing capabilities, not plumbing.

**Confidence:** High for what the run covered. It covered DX12 only and no Painter-side comparison beyond the Wand R9 maps (`:226-234`).

## F-004 - Four pillars of the proposal have no implementation yet

**Evidence:** The 68 open tasks of Phases 3-5 have 1,143 open checklist items and 0 checked. That covers:

- native bake (OWN-05): `phase3.1_baker-request-model` through `phase3.5_embree-bakers`, 13 tasks;
- the clean-room Iray path tracer (VIS-06, ARC-06): `phase3.4_path-tracer-transport` through `phase3.7_path-tracer`;
- the Vulkan backend (OWN-08, §17): `phase3.1_vulkan-compute-parity`, `phase3.2_vulkan-ray-tracing`, `phase3.3_vulkan-backend-ray-tracing`; in code, `src/render/device.cpp:59-61` refuses Vulkan;
- engine export presets (OWN-06) and packaging (OWN-08): `phase3.1`-`3.4` Unreal and UzEngine tasks, `phase5.2_packaging`.

The roadmap names the path tracer as the leg that may set the total duration (`docs/roadmap.md:16`). Roadmap rule 1 lets feasibility work on bake and the Iray capture overlap Phases 1-2 (`:24`).

**Impact:** High for the schedule. These are the long, research-heavy parts of the proposal. The Iray leg is already known not to fit held-out pixels (`plan-purpose-review/02-delivery-risks.md` F-004). Under the task-sequence rule they start only after G2, so they sit behind the pilot blockers in F-002 and F-006.

**Confidence:** High for the counts. Medium on the duration they imply.

## F-005 - About a third of Painter's surface is supported, and the rest is visible

**Evidence:** The 2026-10-13 build reports 546 `supported`, 363 `release-gap`, 656 `pending-evidence` and 15 `desktop-only-omitted` capability entries (`practical-e2e.md:43`). The facade task still lists 257 pending-evidence Painter symbols (`.rulebook/tasks/phase1.24_python-api-facade/tasks.md:15`). The checked-in `zig-out/bin/capabilities.json` is from 2026-10-11 and shows no `supported` entry, so it is stale.

**Impact:** Medium. The proposal's "same functionality" is about 35 % covered by entry count. Entries are not weighted by importance. Gaps are reported, not hidden, which matches OWN-01's acceptance rule.

**Confidence:** Medium. These are entry counts, not a measure of what the pipeline uses.

## F-006 - The production pilots depend on owner actions with no date

**Evidence:**
- Belt v5: the round folder is gone, 21 input paths are missing, and the owner must restore them or approve a new golden (decision 192 §1). `phase2.9_pilot-belt` has 0 of 17 items done.
- Tunic v10: the migration golden is recorded, but the rebuild needs nine masks that only the Painter project holds (decision 194). The double-sided state stays refused until the owner amends decisions 042 and 132 (decision 196). `phase2.10_pilot-tunic-recovery` has 1 of 18 items done.

The previous review raised this as F-005 (`plan-purpose-review/02-delivery-risks.md`), and roadmap rule 8 (`docs/roadmap.md:32`) bounds the inventory, but no decision checkpoint has a date.

**Impact:** High for G2 and the cutover. Engineering cannot replace missing approved bytes. Until the owner answers, Belt and Tunic cannot be accepted, and G2, Phase 3 and the replacement wait with them.

**Confidence:** High.
