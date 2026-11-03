## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.26_gate-g1, phase2.10_pilot-tunic-recovery, phase2.3_realtime-preview, phase2.4_supervisor-worker
  - Runs last (decision 397, owner 2026-11-03): this gate's runs start only after every feature task of Phase 2 has passed its own tests

## 2. Joined items
- [ ] 2.1 phase1.26_gate-g1 accepted (previous gate)
- [x] 2.2 phase2.4_supervisor-worker accepted: worker-kill, lost-acknowledgement and stalled-fence recovery evidence in `parity/reports/phase2/supervisor-settling.json`
  - Reconciled 2026-11-02 against `.rulebook/archive/2026-10-20-phase2.4_supervisor-worker/tasks.md`, item 4.1 and the acceptance run of 2026-10-20: 14 DX12 cases and 13 GPU-free Vulkan cases passed. Decision 326 records the Wand prerequisite scope split; decision 221 assigns the real-Vulkan obligations to `phase3.1_vulkan-compute-parity`. This join records the existing acceptance, not a new run or acceptance of Wand or G1.
- [x] 2.3 phase2.3_realtime-preview accepted: window-independent captures and non-pausing preview in `parity/reports/phase2/preview-settling.json`
  - Reconciled 2026-11-02 against `.rulebook/archive/2026-10-20-phase2.3_realtime-preview/tasks.md`, section 12: acceptance includes six refreshed DX12/CPU preview tests and section 11's full-size Wand run. Decisions 326 and 221 retain the Wand parity and Vulkan obligations in their owning tasks. G2 prerequisites, pilot joins and acceptance remain open.
- [ ] 2.4 phase2.10_pilot-tunic-recovery accepted: Tunic v10 Tier 1 maps and dump-and-rebuild under the exception policy
- [ ] 2.5 Reached through P2-TUNIC and confirmed: phase2.8_mcp-server, phase2.2_recipe-and-diagnostics, phase2.9_pilot-belt (Belt v5 Tier 1 and the Python-disabled MCP-only round)

## 3. Gate record
- [ ] 3.1 Every exception relied on is an owner-approved entry in `parity/exceptions.json` with its `.rulebook/decisions/` record; none relaxes a structural difference
- [ ] 3.2 Capability manifest regenerated on the gate build; Phase 2 gaps listed (including `painter_iray` unavailable)
- [ ] 3.3 Gate record written to `parity/reports/phase2/gate-g2.md`: joined items, evidence paths and hashes, exceptions, build hash, hardware, driver, backend; states that render parity is not part of G2
- [ ] 3.4 Duration Hypotheses of Phases 3–5 revised in `docs/roadmap.md` (owner Q14)
- [ ] 3.5 Phase 2 tasks archived in `.rulebook`

## 4. Acceptance
- [ ] 4.1 G2 accepted: Tier 1 maps and dump-and-rebuild pass under the exception policy; Python-disabled MCP-only Belt round done; recovery tests pass; captures window-independent

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
