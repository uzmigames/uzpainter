## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase2.9_pilot-belt, phase2.2_recipe-and-diagnostics, phase2.8_mcp-server

## 2. Implementation
- [ ] 2.1 Tunic v10 fixture manifest in `parity/manifests/`: stack JSON, resources and external mesh maps by SHA-256, per-layer binding overrides, instruction sequence, export configuration
- [x] 2.2 Tunic v10 Tier 1 goldens recorded twice through the recorder (documented API, migration readback kept private); oracle stability classified
- [ ] 2.3 Tunic v10 rebuilt through the typed MCP tools with per-layer bindings (C07 → `Source_v10_M_piping`, F03 → `Source_v9_M_piping`, `F03 → M_piping_lining_v9`), `replace_height` and the double-sided state
- [ ] 2.4 Dump-and-rebuild of the rebuilt tunic into a new project
- [ ] 2.5 Tier 1 comparison and report `parity/reports/phase2/tunic-v10-tier1.json`
- [x] 2.6 Before input-dependent rebuild work, complete one bounded inventory using the sources and searches already documented in decisions 194 and 215: identify the nine missing masks, the original normalized OBJ, preserved project/resources and unresolved double-sided scope. Record present/missing inputs, source locations and identity evidence; no repeated sweep without a newly identified source. Done 2026-10-23: `parity/reports/phase2/tunic-v10-input-inventory.md`; only documented sources checked. Nine masks and normalized OBJ remain absent; double-sided scope is settled by decision 196's amendment, not newly decided here.
- [x] 2.7 Verify and preserve available or recovered inputs in the private content-addressed store together with the request, oracle envelope and admitted OCIO golden of decision 215. Verify hashes before use; retain the admitted reference unchanged and record known resource-version matches. The delivered FBX is not assumed identical to the missing normalized OBJ. Done 2026-10-23: ten documented source files and nine recovered bitmap blobs verified; recovered SHA-1 values match decision 215's resource versions. Both envelopes' 17 private records verify, all five golden hashes remain unchanged, and the admitted manifests retain request/configuration pins. Missing originals are not claimed recovered; FBX/OBJ identity remains unproven. Evidence: `parity/reports/phase2/tunic-v10-input-inventory.md`.
- [ ] 2.8 At the inventory checkpoint, verify restored originals against known hashes/resource versions and provenance; restoration alone needs no new scope decision. If original masks or mesh remain unavailable, prepare one owner decision package for recovery versus a new reference, replacement or exclusion, reusing any pending question. A changed baseline requires an explicit recorded owner scope decision and a separately identified reference; retain the existing golden. Keep decision 196 double-sided scope unresolved until its existing owner choice is recorded; this checkpoint does not choose that policy

## 3. Tests
- [ ] 3.1 Tier 1: every exported Tunic v10 map equals the private golden in native decoded values; save/reopen preserves equality
- [ ] 3.2 Bindings: C07 and F03 resolve to different resource hashes although both are named `M_piping` historically; no global filename replacement occurs
- [ ] 3.3 Group Height blend override and double-sided state read back through a freshly resolved handle and after save/reopen
- [ ] 3.4 Dump-and-rebuild: exports byte-identical and recipe digests equal
- [ ] 3.5 Every divergence is listed with the owner-approved exception that covers it, or the test fails

## 4. Acceptance
- [ ] 4.1 DAG gate met: equal maps and rebuild equal; report written to `parity/reports/phase2/tunic-v10-tier1.json`; input inventory and preservation records are complete, mesh/resource identity is settled, and any changed baseline or double-sided scope is covered by its explicit owner decision (items 2.6-2.8)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Notes (decision 194; 2026-10-12, branch `wt/p2-tunic`)
- Inputs secured first. Assets3D git-ignores everything of the tunic but `report.json`, so these are now in the private store by SHA-256:
  - `18-Tunica-v10.spp` (`c43db46a…`, the piece manifest's verified pin), `.blend` (`f6243a57…`), the five delivered `Textures/` maps, `Export/18-Tunica-v10.fbx` and `.glb`, `report.json`;
  - from the `.blend`'s packed images: 7 v10 and 7 v9 masks, `Source_v6_HighNormal` and the older sources. Each one's SHA-1 equals the Painter resource version the report recorded.
- Missing: nine masks the v10 stack binds (`M_pores`, `M_fiber`, `M_dyeinv`, `M_stains`, `M_fray`, `M_hem`, `M_cav`, `M_ridgewear`, `M_lining`). Their only identified copy is inside the `.spp`; the documented drive and recycle-bin searches did not find exported original bytes. Those searches do not establish global absence.
- Historical recording request (decision 194; fulfilled by decision 215 below): the migration golden `phase2/tier1/tunic-v10` (r1, r1-repeat, r2) from `parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase2/tier1/tunic-v10.json`, recorded with `python -m tools.parity.recorder record-migration <request> --assets-root E:\UzmiGames\Assets3D` under OCIO (substance config). It does not wait on the lost masks.
- Blockers, each with its owner:
  - Recording (historical blocker, cleared by decision 215): 2.2 is complete; the admitted OCIO golden remains the comparison reference. Rebuild inputs, mesh identity and scope still block 3.1 and 4.1.
  - Nine lost masks (owner): restore their original bytes to `_tmp/claude/<name>.png`, then run `script_run manifest --pilot tunic-rebuild --assets-root E:\UzmiGames\Assets3D --out tests/parity/tier1/tunic_v10/rebuild-fixture.json --store`. Regenerated masks would require an explicitly owner-authorized, separately identified reference, not silently replace approved v10 (2.8). This blocks 2.1 and 2.3-2.5, 3.1-3.5.
  - `infinite` padding (phase1.25 item 2.7): pilot exports remain refused before writing until that capability clears the existing equality/owner-exception contract. Any exception needs measured evidence and an owner-approved, versioned register entry for its domain; no tolerance is assumed.
  - Double-sided state (decision 196; cleared by its amendment of 2026-10-19, SUP-030): decision 196 kept `shader_set` refusing `double_sided: true` until 042 item 5 and 132 item 7 were amended. Under the owner's delegation of 2026-10-19, the supervisors adopted option (b) as decision 196's amendment, with renders pinned:
    - `shader_set` and `render.shader.set_parameters` store `double_sided` true or false, merged into the stored parameters;
    - it survives save and reopen;
    - `parity` is false while it is true, and a Tier 3 comparison rejects that state as render evidence;
    - exported maps stay byte-identical.

    The rebuild fixture keeps its `double_sided: true` pin. The double-sided parts of 2.3 and 3.3 no longer wait on the owner, and the rest of those items is unaffected. Item 2.8's "keep decision 196 double-sided scope unresolved" is settled by that amendment.
  - 1.1: phase2.9, phase2.2 and phase2.8 are not accepted.
- 2.1 (open): the generators are written and tested.
  - `--pilot tunic` wrote the golden's request.
  - `--pilot tunic-rebuild` pins the stack working copy (override on F03 only), 21 bindings over 17 files by SHA-256 and resource version, the Normal map, the mesh (the delivered FBX, an assumption the readback's `last_imported_mesh_path` checks) and the double-sided value. On the real Assets3D it refuses, listing the nine masks.
- 2.2 (historical pre-decision-215 state): the recorder records migration goldens (`tools/parity/recorder/migration.py`, schema kind `painter_project`, interface `painter_project_migration`). The request was committed and awaited the owner's recording; decision 215 below completes this item.
- 2.2 (done, decision 215, Painter batch G, 2026-10-13): the golden is recorded under OCIO and admitted to `manifests/phase2/tier1/tunic-v10.json`. The open showed no dialog and the project stayed OCIO. All five maps (4096 px, 16-bit PNG) are stable, byte-identical in r1, r1-repeat and r2. The readback is equal between r1 and r2 except for the project counter and the file path. The Recording blocker above is cleared.
  - New for 2.3: the readback's `last_imported_mesh_path` is `_tmp/astra-tunica/normalized_low.obj`, which is gone from Assets3D. It is not the `Export/18-Tunica-v10.fbx` the rebuild fixture assumes. Settle the mesh before the rebuild (2.6-2.8); the delivered-FBX assumption in the earlier 2.1 note is superseded by this readback.

## 7. Notes (decision 300; 2026-10-19, branch `wt/res-qual`)
- Recovery step (SUP-008): Painter's Export resource is qualified first on 13 disposable PROJECT bitmaps. First run on 2026-10-23 is `INCONCLUSIVE`: all 26 export attempts stop at the Assets locator before writing; the bulk UI Automation enumeration returns no descendants because the viewport raises E_FAIL; TreeWalker can recover the other controls. Separate processes and source-path absence are verified, and all thirteen staged sources are preserved by hash. No form is qualified, no retry has been consumed, and the locator must be validated before another attempt (`parity/reports/phase2/resource-export-qualification.md`). The pilot forms include the Pillow 16-bit grey mask at 256 and 2048 px.
- If the verdict is `EXACT`, or `PARTIAL` with those forms qualified, a separate request exports the nine masks from a hash-checked private copy of the stored `.spp`. Each is accepted only if its SHA-1 equals the version in decision 215's readback, then stored by SHA-256 for `--pilot tunic-rebuild` to resolve.
- `normalized_low.obj` is not a resource and stays lost on every outcome. Otherwise the pinned current round, `phase2/tier1/tunic-v10-current`, follows decision 300 item 7, with the admitted migration golden kept unchanged. Using it as the changed baseline waits on the owner's own yes.
