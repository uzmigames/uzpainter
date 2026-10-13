## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase2.9_pilot-belt, phase2.2_recipe-and-diagnostics, phase2.8_mcp-server

## 2. Implementation
- [ ] 2.1 Tunic v10 fixture manifest in `parity/manifests/`: stack JSON, resources and external mesh maps by SHA-256, per-layer binding overrides, instruction sequence, export configuration
- [ ] 2.2 Tunic v10 Tier 1 goldens recorded twice through the recorder (documented API, migration readback kept private); oracle stability classified
- [ ] 2.3 Tunic v10 rebuilt through the typed MCP tools with per-layer bindings (C07 → `Source_v10_M_piping`, F03 → `Source_v9_M_piping`, `F03 → M_piping_lining_v9`), `replace_height` and the double-sided state
- [ ] 2.4 Dump-and-rebuild of the rebuilt tunic into a new project
- [ ] 2.5 Tier 1 comparison and report `parity/reports/phase2/tunic-v10-tier1.json`

## 3. Tests
- [ ] 3.1 Tier 1: every exported Tunic v10 map equals the private golden in native decoded values; save/reopen preserves equality
- [ ] 3.2 Bindings: C07 and F03 resolve to different resource hashes although both are named `M_piping` historically; no global filename replacement occurs
- [ ] 3.3 Group Height blend override and double-sided state read back through a freshly resolved handle and after save/reopen
- [ ] 3.4 Dump-and-rebuild: exports byte-identical and recipe digests equal
- [ ] 3.5 Every divergence is listed with the owner-approved exception that covers it, or the test fails

## 4. Acceptance
- [ ] 4.1 DAG gate met: equal maps and rebuild equal; report written to `parity/reports/phase2/tunic-v10-tier1.json`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Notes (decision 194; 2026-10-12, branch `wt/p2-tunic`)
- Inputs secured first. Assets3D git-ignores everything of the tunic but `report.json`, so these are now in the private store by SHA-256:
  - `18-Tunica-v10.spp` (`c43db46a…`, the piece manifest's verified pin), `.blend` (`f6243a57…`), the five delivered `Textures/` maps, `Export/18-Tunica-v10.fbx` and `.glb`, `report.json`;
  - from the `.blend`'s packed images: 7 v10 and 7 v9 masks, `Source_v6_HighNormal` and the older sources. Each one's SHA-1 equals the Painter resource version the report recorded.
- Missing: nine masks the v10 stack binds (`M_pores`, `M_fiber`, `M_dyeinv`, `M_stains`, `M_fray`, `M_hem`, `M_cav`, `M_ridgewear`, `M_lining`). Their only copy is inside the `.spp`. They are not on any drive or in any recycle bin.
- Recordings needed: one, the migration golden `phase2/tier1/tunic-v10` (r1, r1-repeat, r2) from `parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase2/tier1/tunic-v10.json`, recorded with `python -m tools.parity.recorder record-migration <request> --assets-root E:\UzmiGames\Assets3D` under OCIO (substance config). It does not wait on the lost masks.
- Blockers, each with its owner:
  - Recording (owner's Painter session): blocks 2.2, 3.1 and 4.1.
  - Nine lost masks (owner): restore their original bytes to `_tmp/claude/<name>.png`, then run `script_run manifest --pilot tunic-rebuild --assets-root E:\UzmiGames\Assets3D --out tests/parity/tier1/tunic_v10/rebuild-fixture.json --store`. Regenerated masks would be a new golden, not the approved v10. This blocks 2.1 and 2.3-2.5, 3.1-3.5.
  - `infinite` padding (phase1.25 item 2.7): every pilot export is refused before writing until it lands.
  - Double-sided state (owner; decision 196): UzPainter's `shader_set` keeps refusing `double_sided: true`, because decisions 042 and 132 accept only the `open-pbr` defaults and the panel cannot widen an owner-scoped setter contract. The tunic's approved state has it on. The double-sided parts of 2.3 and 3.3 are a scope split owned by the owner. The owner can:
    - amend 042 item 5 and 132 item 7 to store it as project state with renders pinned (decision 196 item 5 specifies this, tests included);
    - or drop the pin from the rebuild fixture and from 2.3 and 3.3.

    The rest of 2.3 and 3.3 is unaffected, and so are the exported maps.
  - 1.1: phase2.9, phase2.2 and phase2.8 are not accepted.
- 2.1 (open): the generators are written and tested.
  - `--pilot tunic` wrote the golden's request.
  - `--pilot tunic-rebuild` pins the stack working copy (override on F03 only), 21 bindings over 17 files by SHA-256 and resource version, the Normal map, the mesh (the delivered FBX, an assumption the readback's `last_imported_mesh_path` checks) and the double-sided value. On the real Assets3D it refuses, listing the nine masks.
- 2.2 (open): the recorder records migration goldens (`tools/parity/recorder/migration.py`, schema kind `painter_project`, interface `painter_project_migration`). The request is committed; the recording is the owner's.
