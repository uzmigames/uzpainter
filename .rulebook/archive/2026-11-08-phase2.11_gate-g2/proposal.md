# Proposal: phase2.11_gate-g2

## Why
Gate G2 "Pilot parity" in `docs/dag.md` and `docs/roadmap.md` (D14). A gate joins every mandatory acceptance item of its phase and requires the previous gate; a work package carrying a gate's evidence cannot close the gate by itself (roadmap rule 2). G2 proves that the first production-parity pilots reproduce under the exception policy and that the operating runtime recovers from faults; its pass unlocks Phase 3 and the Assets3D cutover (owner Q13). Render parity is not part of G2 and cannot satisfy G5. Requirements: OWN-03, ACC-01, G-03, INT-02, ARC-01, ARC-02, ARC-14, VIS-01, VIS-02 (`docs/prd.md`).

## What Changes
- Gate record `parity/reports/phase2/gate-g2.md` (numbers and hashes only): each joined item with its acceptance evidence, the exceptions relied on, build hash, hardware, driver and backend.
- Capability manifest regenerated at the gate; Phase 2 tasks archived in `.rulebook` (roadmap rule 3).
- Duration Hypotheses of the following phases revised in `docs/roadmap.md` (owner Q14).

## Dependencies
- DAG inputs (joined items): `phase1.26_gate-g1` (G1), `phase2.10_pilot-tunic-recovery` (P2-TUNIC), `phase2.3_realtime-preview` (P2-PREVIEW), `phase2.4_supervisor-worker` (P2-SUPERVISOR).
- Reached through them: `phase2.8_mcp-server`, `phase2.2_recipe-and-diagnostics`, `phase2.9_pilot-belt` and their children.
- Consumers: `phase3.1_assets3d-cutover`, `phase3.8_gate-g3`.

## Acceptance
DAG gate: Tier 1 maps and dump-and-rebuild pass under the exception policy (Belt v5 and Tunic v10); the Python-disabled MCP-only Belt round is done; recovery tests pass (worker kill, lost acknowledgement, stalled fence); captures are window-independent. Render parity is not part of G2 and cannot satisfy G5.

## Impact
- Affected specs: `gates` (G2)
- Affected code: none; gate record, regenerated capability manifest, roadmap durations
- Breaking change: NO
- User benefit: an evidence-backed pilot-parity milestone that unlocks the cutover and Phase 3
