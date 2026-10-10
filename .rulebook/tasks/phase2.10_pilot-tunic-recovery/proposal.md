# Proposal: phase2.10_pilot-tunic-recovery

## Why
P2-TUNIC in `docs/dag.md` (critical path), the milestone that counts in the owner's pilot order (owner Q7; `docs/roadmap.md` Phase 2 and rule 4), implementing D14 and D3 (`docs/architecture/04-layer-stack-and-compositing.md` §1, §2; `docs/architecture/03-project-model.md` §7). Tunic v10 is the approved paint standard: per-layer resource bindings where same-named masks differ (C07 binds `Source_v10_M_piping`, F03 binds `Source_v9_M_piping`), nested groups with a per-group Height blend override, the double-sided state and dump-and-rebuild. Its G2 pass triggers the Assets3D cutover (`phase3.1_assets3d-cutover`, owner Q13). Requirements: G-02, G-03, LAY-03, LAY-07, LAY-13, PRJ-06, SAV-04, OWN-03, ACC-01 (`docs/prd.md`).

## What Changes
- Tunic v10 rebuilt in UzPainter through the typed MCP tools (the Assets3D client path) from the pipeline's stack JSON and resources with identical external mesh maps: per-layer bindings by content hash with explicit overrides (`F03 → M_piping_lining_v9`), never a global filename replacement; `replace_height` (Height blend override, LAY-03); the double-sided state.
- Tunic v10 Tier 1 goldens recorded on the owner's machine with `tools/parity/recorder/*.py` through Painter's documented API (project state read while Painter is installed and replayed, owner Q6; no `.spp` reader), at least twice with oracle stability classified; blobs and the per-project migration readback in the private store, hashes in `parity/manifests/`.
- Dump-and-rebuild: the rebuilt tunic dumped, rebuilt from the dump and its resources into a new project, and exported.
- Tier 1 report `parity/reports/phase2/tunic-v10-tier1.json`: every exported map, save/reopen, dump-and-rebuild, the three separate results and the exceptions relied on (numbers only).
- If recovery blocks on a schema or binding problem, that investigation moves earlier without dropping the smoke fixtures (`docs/roadmap.md` rule 4).

## Dependencies
- DAG inputs: `phase2.9_pilot-belt` (P2-BELT), `phase2.2_recipe-and-diagnostics` (P2-RECIPE), `phase2.8_mcp-server` (P2-MCP).
- Consumers: `phase2.11_gate-g2` and, after G2, the Phase 3 packages that take P2-TUNIC as input.

## Acceptance
DAG gate: equal maps; rebuild equal. Every Tunic v10 map equals the private golden in native decoded values (or is covered by an owner-approved exception), C07 and F03 resolve to their distinct resources, and the dump-and-rebuild exports are byte-identical to the rebuilt tunic's.

## Impact
- Affected specs: `pilots` (Tunic v10)
- Affected code: none beyond fixes the pilot exposes; fixture manifests, reports
- Breaking change: NO
- User benefit: the approved paint standard reproduced and recoverable from its recipe
