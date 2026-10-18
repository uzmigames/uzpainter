# 02. Where the effort went

Counts are from main `c07e787`. Decision themes are matched on decision-file titles under `.rulebook/decisions/` (203 records, 2026-10-10 to 2026-10-13). A title can match more than one theme.

| Theme (title keywords) | Decisions | On the G1 critical path? |
|---|---|---|
| Painter recordings, batches, probes, goldens, envelopes | 53 | Partly. They are the oracle input for every fit |
| Colour, sRGB, OCIO, bitmap decode, texture filtering | 46 | Partly. The Wand needs its own colour cases, not every template |
| MCP, supervisor, lease, worker | 23 | No. This is Phase 2, and its acceptance waits on G1 |
| UV-island `infinite` padding | 15 | **Yes.** This is the Wand blocker |
| Preview and viewport | 14 | No. The preview is not parity evidence (`prd.md:146`) |
| Wand, Belt, Tunic | 13 | Yes |
| Iray, path tracer | 9 | No (Phase 3) |
| Vulkan | 6 | No (Phase 3) |
| Procedural, bake | 4 | No (Phase 3) |

Commits: 358 non-merge commits in total, 85 of them `chore`/`docs` on `rulebook`, `decisions` or `changelog`.

## F-007 - The Wand's last mile became an open-ended research hunt with no recorded budget

**Evidence:** `.rulebook/tasks/phase1.25_pilot-wand/tasks.md:15-22` holds item 2.7, UV-island padding. Its progress notes cite decisions 127, 176, 184, 197, 220, 223 and 245, and decisions 129, 206, 210, 211, 216 and 217 add more. That is about ten experiment rounds, and each one ended "refusal kept". Roadmap rule 9 (`docs/roadmap.md:33`, added in `0cf43b9` on 2026-10-13) requires every parity experiment batch to record a hypothesis and a finite wall-clock budget in the task's evidence. The Wand task folder holds no budget record. The owner's own speed rule says to time-box each exactness hunt at about two hours and then record the gap (memory note *throughput*, 2026-10-12). The last result, decision 245, did not close the hunt. It widened the refusal to every virtual Normal on an islanded set, and so to the whole Wand export.

**Impact:** High. G1 and, through the prerequisite chains, every Phase 2 acceptance wait on this one item (F-009). The hunt turned up real facts: the gutter is a jump flood (decision 197), and the island interiors are exact. But it has no stopping rule, so it can keep absorbing capacity without moving a gate.

**Confidence:** High for the missing budget record and the number of rounds. Medium for the claim that more rounds will not converge.

## F-008 - Preview polish took the latest work while the parity target stayed blocked

**Evidence:** The last five commits on main all touch the preview, and four of them change `painter_viewport` shading: ray-traced self-occlusion (`9e57199`, decision 251), a normal fade (`9b704b3`, decision 256), an AO visibility weight (`7b2804d`, decision 257) and a cavity term (`c07e787`, decision 258). Each was a reply to an owner comment on a capture: "interessante mas totalmente sem sombra" (decision 251 Context) and "cadê as cavidades? microshadow? AO bem definido?" (decision 258 Context). Every one of these decisions states that the viewport "stays never-parity evidence". The PRD makes the realtime viewport "the human preview and a fast check, not the parity target" (`docs/prd.md:146`, `:203`).

**Impact:** Medium. Answering the owner is right, and a believable preview helps him judge progress. But each round adds unrecorded shading design that the clean-room Iray path tracer will replace. Meanwhile the Wand's Normal map, which the owner's pipeline actually needs, stays refused. Visual feedback from the owner now steers the work toward a component the contract does not count.

**Confidence:** High on the facts. Medium on the cost, since the four rounds' wall-clock is not recorded.

## F-009 - Phase 2 was built ahead of G1, so a large inventory waits on one pilot item

**Evidence:** The 13 open Phase 2 tasks hold 223 checked and 83 open items. Most of them have every item done except their prerequisite line: for example `phase2.1_*`, `phase2.5_mcp-transport-registry` (19/20), `phase2.6_mcp-typed-tool-families` (20/21). The chains all end on `phase1.25_pilot-wand`: `phase2.4_supervisor-worker/tasks.md:2`, `phase2.3_realtime-preview/tasks.md:2`, `phase2.9_pilot-belt/tasks.md:2`, and `phase2.8_mcp-server/tasks.md:2` through `phase2.4`. The owner's sequencing rule says "every open Phase N task comes before Phase N+1 work" (memory note *follow the task sequence*, 2026-10-11). On 2026-10-13 he said: "eu to achando q vc ta acumulando muito codigo, sem ter certeza de funcionamento" (memory note *practical testing*).

**Impact:** Medium. The early Phase 2 work was not wasted: the practical run (F-003) proves it works. But no task can be archived, the visible progress looks flat, and every new Phase 2 fix adds unaccepted code. The previous review accepted building ahead as "useful preparation" (`plan-purpose-review/01-purpose-and-gates.md:37`). The risk is that preparation keeps growing while the gate it waits on does not move.

**Confidence:** High.

## F-010 - Colour and export fits went wider than the pilots need

**Evidence:** 46 decisions cover colour, decode and filtering. Item 2.6 of the Wand task (`tasks.md:11-14`) fitted the empty-BaseColor base of all 24 shipped export templates, including Dota 2's L8 Specular (decisions 168, 169, 172, 204). The Wand uses one pinned export (`practical-e2e.md:109`). The 8-bit sRGB anisotropic and mip filters (decisions 209, 213, 219, 224, 225) and the OCIO component tables (decisions 190, 202, 207) widen the supported surface for cases no pilot exercises.

**Impact:** Low to medium. This is real, exact parity work, and OWN-01 needs it eventually. But it was done before the first piece passes. Each new fit also creates Painter-recording demand, the single shared resource that the owner also needs for Assets3D painting (memory note *follow the task sequence*).

**Confidence:** Medium. Which template a given pilot needs was not traced case by case.

## F-011 - Process records grew as fast as the product

**Evidence:** 203 decision records in four days (31, 53, 73 and 46 per day). Many are several hundred lines long; decision 258 alone has a six-row measurement table before its decision. 85 of 358 non-merge commits are rulebook, decision or changelog bookkeeping. `git worktree list` shows 43 entries, including scratch branches marked "never merged" (`wt/loadcache-b19prof`). A shared rulebook task tracks 1,259 open checklist items.

**Impact:** Medium. Records keep the clean-room and parity contract auditable, which the proposal needs. But writing, merging and renumbering them costs coordination time, which the owner has already complained about (memory note *throughput*: "vc ta perdendo tempo pra caralho"). Decisions that record a preview constant (decision 256's 0.2 band) get the same treatment as parity contract changes.

**Confidence:** Medium. Time per record is not measured.
