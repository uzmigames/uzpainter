## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand, phase2.8_mcp-server

## 2. Implementation
- [ ] 2.1 Belt v5 fixture manifest in `parity/manifests/`: stack JSON, resources and external mesh maps by SHA-256, instruction sequence, export configuration
- [ ] 2.2 Belt v5 Tier 1 goldens recorded twice through the recorder on the owner's machine; oracle stability classified; blobs in the private store, hashes in the manifest
- [ ] 2.3 Belt v5 rebuilt in UzPainter from the same stack JSON and resources, including the `base_tex` swatch fills
- [ ] 2.4 Tier 1 comparison and report `parity/reports/phase2/belt-v5-tier1.json`
- [ ] 2.5 MCP-only round script driving typed tools against a supervisor started without `--allow-python`; call log and receipts in `parity/reports/phase2/belt-v5-mcp-round.json`

## 3. Tests
- [ ] 3.1 Tier 1: every exported Belt v5 map equals the private golden in native decoded values; save/reopen preserves equality
- [ ] 3.2 Repeatability: two UzPainter runs produce byte-identical exports
- [ ] 3.3 MCP-only round: `run_python` absent from the tool list, every call typed, round completed, maps equal to the Tier 1 run
- [ ] 3.4 Every divergence is listed with the owner-approved exception that covers it, or the test fails

## 4. Acceptance
- [ ] 4.1 DAG gate met: equal maps and the Python-disabled MCP integration round completed; reports written to `parity/reports/phase2/`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
