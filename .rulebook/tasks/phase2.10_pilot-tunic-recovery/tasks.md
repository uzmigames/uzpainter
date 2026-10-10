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
