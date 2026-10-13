# 221. Phase 2 acceptance is DX12 plus the GPU-free Vulkan cases, and the Vulkan device cases become phase3.1_vulkan-compute-parity's acceptance obligations

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.1_supervisor-ipc-worker, phase2.4_supervisor-worker, phase2.3_realtime-preview, phase2.5_mcp-transport-registry, phase2.6_mcp-typed-tool-families, phase2.7_mcp-operation-matrix, phase2.8_mcp-server, phase3.1_vulkan-compute-parity

## Context

The Codex plan review of main `173fb65` (`docs/analysis/plan-purpose-review/01-purpose-and-gates.md` F-001) found an acceptance cycle. It holds on main `b44760c`:

- `phase3.1_vulkan-compute-parity` 1.1 needs `phase2.10_pilot-tunic-recovery` accepted. Its item 3.6 compares the Tunic v10 maps on Vulkan and DX12, so Tunic is a real input of its acceptance.
- `phase2.10_pilot-tunic-recovery` 1.1 needs `phase2.8_mcp-server` accepted, and `phase2.8_mcp-server` 1.1 needs `phase2.4_supervisor-worker` accepted.
- `phase2.4_supervisor-worker` 3.4 and 4.1, and its child `phase2.1_supervisor-ipc-worker` 3.3 and 4.1, wait on the Vulkan device-loss and stall cases. Decision 121 gave those cases to phase3.1 items 2.2 and 3.4, because no Vulkan device exists before phase3.1.

So none of these tasks can ever be accepted. `docs/dag.md` checks only the nominal graph (P2-SUPERVISOR's input is P1-WAND, and its gate names no backend), so it missed the deferred conditions in the checklists.

A related wait is not a cycle: `phase2.3_realtime-preview` 4.1 also waits on its Vulkan `preview-settling.json` entries (decision 121, `pending`). That made G2 (pilot parity) and the Assets3D cutover wait on a Phase 3 backend.

The model panel ran one round (dossier in the session scratchpad, `plan-panel/`):

| Claim | GPT (cx/gpt-6-astra) | Kimi (kimi-k3) | Grok (grok-4.5) |
|---|---|---|---|
| F-001 is a real acceptance cycle | AGREE | AGREE | AGREE |
| A sequencing split with backlinks beats earlier Vulkan qualification | AGREE | AGREE | AGREE |
| The split claims nothing untrue once "both backends" is amended and the cases stay `pending` | AGREE | PARTLY (amend every place that cites it) | AGREE |
| phase2.3's Vulkan preview entries move under the same split | AGREE | AGREE | AGREE |
| The cycle check also reads explicit "waits on" notes | PARTLY (prefer structured wait lines) | PARTLY (structured field) | AGREE |

The coordinator relayed the Codex reviewer's constraints. Separate qualification from the pilot comparisons. Keep the Vulkan gap visible until it is qualified. Waive no Vulkan test. Accept no gate silently. Do not require a whole backend early.

## Decision

1. **Sequencing split, nothing waived.** Supervisor acceptance (`phase2.1`, `phase2.4`) and the G2 recovery and capture evidence are DX12 plus every case that needs no GPU device on Vulkan. Those cases already pass, because the Vulkan worker runs with `gpu_status: unavailable`.
2. **The real-Vulkan obligations belong to `phase3.1_vulkan-compute-parity`, in items 3.4, 2.7 and 4.1:**
   - Vulkan device loss through the supervisor (phase2.1 3.3).
   - The Vulkan `gpu_stall` and `device_lost` cases of `supervisor-settling.json` (phase2.4 3.4).
   - A re-run of the `02-…` §7 settling suite with a real Vulkan device: recovery, commit-then-die retry, lost-ledger replay, no duplicate commit (phase2.4 4.1).
   - The five Vulkan entries of `preview-settling.json` (phase2.3 4.1).

   phase3.1 4.1 passes only when none of them is left `pending`. They reach G3 through `phase3.3_vulkan-backend-ray-tracing` and G5 through P5-REPORT (DX12 and Vulkan). Each Phase 2 task carries a backlink, and the reports keep the entries `pending` with decision 121 until phase3.1 settles them.
3. **Qualification is separate from the pilot comparison.** phase3.1's device qualification (items 2.1, 2.2, 2.6, 2.8, 3.1, 3.4, 3.8) needs only `phase1.4_render-core-layer` and the supervisor code on main, so it may start before Tunic. Only the pilot comparisons (3.6, and the pilot maps in 4.1) need `phase2.10_pilot-tunic-recovery`. Its acceptance prerequisite is unchanged.
4. **Acceptance-graph check.** `python -m tools.planning.acceptance_graph` builds a graph over every open task. Its edges are:
   - the unchecked "Prerequisites accepted:", "Child accepted:" and "`<id>` accepted" lines;
   - structured `- Acceptance waits on: <id>` lines;
   - free-text "waits on / wait for `<task>`" sentences in notes on open items, where the sentence's subject is the task itself.

   The check reads only each open task's `tasks.md`; proposals, specs and decisions are not scanned. Every acceptance wait must therefore be canonical there, as a prerequisite line or a structured line. Free-text waits are a safety net: they count as edges, so a cycle they close is still found.

   The check fails on:
   - a cycle, including a task that requires its own acceptance;
   - a prerequisite that names an unknown task;
   - a short reference (`phase3.1`) in a prerequisite or structured line that does not resolve to exactly one task;
   - a free-text wait that no canonical line of the same task names.

   `tests/planning/test_acceptance_graph.py` runs it on the repository. It also includes regression cases: the frozen decision-121 chain from main, which must fail, the same chain after the split, which must pass, a self-loop, and unresolved and ambiguous short references.
   `phase2.3_realtime-preview` gains a structured `Acceptance waits on: phase1.15_compositor-colour-fits` line, which its 4.1 note already stated in free text (decision 162).
5. Items checked under this split, on their recorded DX12 evidence and as decision 121 §3 already directed: phase2.1 3.3 and phase2.4 3.4. No acceptance item (4.1) is checked. phase2.1 4.1 and phase2.4 4.1 stay open: phase2.4 4.1 on its children and G1, and phase2.1 4.1 for the coordinator to check.

## Alternatives Considered

- **Earlier Vulkan qualification as a new Phase 2 task (A2).** Rejected by all three models. It puts Vulkan device work on the Phase 2 critical path ahead of the pilots, renumbers tasks, and contradicts the roadmap's placement of P3-VULKAN. Decision point 3 still lets the device qualification start early without making it a Phase 2 gate.
- **Waiving the Vulkan device cases.** Rejected: exact parity on both backends is the owner's requirement (Q9, decision 022).
- **Parsing every free-text wait as an error.** Rejected: notes describing other tasks or earlier states would give false positives. Free-text waits count as edges, and only later-phase ones must be structured.

## Consequences

- `docs/dag.md`, `docs/roadmap.md` (G2), `docs/task-index.md` and `docs/architecture/02-runtime-topology.md` §7 state the split. The nominal DAG edges are unchanged.
- The check found five problems on main `b44760c` (90 open tasks):
  - four non-canonical free-text waits: phase2.1 → phase3.1, phase2.4 → phase3.1 (twice) and phase2.3 → phase1.15;
  - the cycle phase2.10 → phase2.8 → phase2.4 → phase2.1 → phase3.1 → phase2.10.

  After the split it reports 218 edges (214 prerequisite, 1 structured, 3 free-text, each also canonical) and no problem.
- phase2.4's spec now lists settling entries as `pass`, `fail` or `pending`. Each `pending` entry is a device-needing Vulkan case that decision 121 deferred and that phase3.1 owns.
