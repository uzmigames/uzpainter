## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input); `phase1.14_compositor-core`, `phase1.24_python-api-facade` and `phase2.8_mcp-server` delivered

## 2. Implementation
- [ ] 2.1 Vendor the vector and font rasteriser libraries from upstream with confirmed Apache-2.0-compatible licences, `ORIGIN.md`, `NOTICE`, `LICENSES/` and dependency-inventory entries (LIC-02)
- [ ] 2.2 `vector` and `font` source kinds in the document model with their documented parameters; files embedded as content-addressed resources
- [ ] 2.3 Rasterisation of vector and font sources into source UV space at evaluation resolution, sampled through the existing projection and filtering path
- [ ] 2.4 Record the Tier 0 vector and font goldens through the UzmiGames recorder (twice; blobs private, hashes in `parity/manifests/`) and fit coverage, antialiasing and colour handling into `parity/semantics/vector-font-sources.json`
- [ ] 2.5 Vector and font kinds in `source_set` for `uzpainter`, the facade and the MCP stack family, with set→get readback and recipe-dump entries
- [ ] 2.6 Capability-manifest entries with evidence ids; operation-matrix rows with their Python-disabled conformance fixture

## 3. Tests
- [ ] 3.1 Tier 0 goldens: vector source in a BaseColor fill on the plane and sphere fixtures, exact
- [ ] 3.2 Tier 0 goldens: font source with the documented text and size parameters, exact
- [ ] 3.3 Tier 0 goldens: vector and font sources in a mask stack, exact
- [ ] 3.4 API probes: source parameters set→get, save and reopen
- [ ] 3.5 Python-disabled MCP conformance fixture for `source_set` with vector and font sources
- [ ] 3.6 Repeatability: identical bytes across two runs on DX12 and, once qualified, Vulkan

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase4.2_remaining-nodes`: vector and font Tier 0 goldens exact or excepted; manifest updated

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
