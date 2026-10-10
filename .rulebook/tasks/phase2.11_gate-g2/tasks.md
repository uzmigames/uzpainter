## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.26_gate-g1, phase2.10_pilot-tunic-recovery, phase2.3_realtime-preview, phase2.4_supervisor-worker

## 2. Joined items
- [ ] 2.1 phase1.26_gate-g1 accepted (previous gate)
- [ ] 2.2 phase2.4_supervisor-worker accepted: worker-kill, lost-acknowledgement and stalled-fence recovery evidence in `parity/reports/phase2/supervisor-settling.json`
- [ ] 2.3 phase2.3_realtime-preview accepted: window-independent captures and non-pausing preview in `parity/reports/phase2/preview-settling.json`
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
