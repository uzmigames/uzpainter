# 01. Purpose and gates

## F-001 - Acceptance prerequisites contain a blocking cycle

**Evidence:** Each row requires the item in the next row to be accepted:

| Item | Required acceptance | Source |
|---|---|---|
| Vulkan compute parity | Tunic recovery | `.rulebook/tasks/phase3.1_vulkan-compute-parity/tasks.md:2` |
| Tunic recovery | MCP server | `.rulebook/tasks/phase2.10_pilot-tunic-recovery/tasks.md:2` |
| MCP server | Supervisor | `.rulebook/tasks/phase2.8_mcp-server/tasks.md:2` |
| Supervisor | Vulkan device-fault qualification | `.rulebook/tasks/phase2.4_supervisor-worker/tasks.md:36`; `:44` |

`docs/dag.md:218` validates the nominal 50-node graph as acyclic, but that check omits these deferred acceptance conditions. Implementation can advance; strict acceptance cannot complete this loop unchanged.

**Impact:** High. G2 and downstream release acceptance can remain blocked even after the code works. Record an explicit sequencing/acceptance split or move the required Vulkan qualification earlier; retain Vulkan obligations at the appropriate backend and release gates. This is not permission to waive them.

**Confidence:** High; explicit prerequisite and acceptance text forms the loop.

## F-002 - Product purpose and release safeguards are well aligned

**Evidence:** `docs/vision.md:5` defines AI-only operation, complete Assets3D replacement and standalone Windows delivery. `docs/prd.md:18`, `:20` and `:26` bind capability scope, pilot cutover and parity. `docs/roadmap.md:7` distinguishes pilot scope from full replacement; `docs/dag.md:216` joins mandatory gates, preserves owner scope decisions and pins release evidence to one build.

**Impact:** Positive. The plan tests the intended result rather than feature-name similarity. Preview is not Iray evidence, migration is not arbitrary editing, and an explained residual is not an accepted exception. Preserve these rules while repairing sequencing.

**Confidence:** High for plan alignment; this does not establish implementation feasibility.

## Few indicators that describe readiness honestly

| Milestone | State at the review baseline | Evidence |
|---|---|---|
| Contract/feasibility gate G0 | Closed on owner order | `parity/reports/phase0/gate-g0.md:7` |
| First end-to-end Wand parity | Goldens admitted; UzPainter comparison, repeatability and acceptance open | `.rulebook/tasks/phase1.25_pilot-wand/tasks.md:6`; `:22`; `:29` |
| Production pilots | Belt not accepted; Tunic goldens admitted, rebuild/parity open | `.rulebook/tasks/phase2.9_pilot-belt/tasks.md:18`; `.rulebook/tasks/phase2.10_pilot-tunic-recovery/tasks.md:19`; `:46` |
| Full replacement/release | G5 still requires broader corpus, backends, packaging and owner sign-off | `docs/roadmap.md:18`; `docs/prd.md:226` |

Phase 2 implementation before G1 is useful preparation; it is not evidence that G1, G2 or full replacement has passed.
