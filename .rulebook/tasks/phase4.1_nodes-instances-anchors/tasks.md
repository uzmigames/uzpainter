## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input); `phase1.14_compositor-core`, `phase1.24_python-api-facade`, `phase2.8_mcp-server` and `phase3.3_procedural-families` delivered

## 2. Implementation
- [ ] 2.1 Record the Tier 0 instance, anchor and reference goldens and the API probes (cycle, insertion, source deletion) through the UzmiGames recorder (twice; blobs private, hashes in `parity/manifests/`); fit reference semantics into `parity/semantics/anchors.json`
- [ ] 2.2 Instance layers: creation, hierarchy-only insertion, evaluation of the source subtree at the instance's position with the instance's own blending and masks, source edits propagating, source deletion as probed
- [ ] 2.3 Anchor effects publishing the current content under their name at their position in the content-effect list
- [ ] 2.4 `reference` sources with channel mapping or referenced channel, alpha matte and levels, in fills, fill effects, masks and generator image inputs
- [ ] 2.5 Instances and references in the evaluation DAG with subtree-hash invalidation; cycles raise `ValueError` before mutation
- [ ] 2.6 `layer_instantiate`, `anchor_list` and reference sources in `uzpainter`, the facade and the MCP stack family with set→get readback and recipe-dump entries
- [ ] 2.7 Capability-manifest entries with evidence ids; operation-matrix rows with Python-disabled conformance fixtures

## 3. Tests
- [ ] 3.1 Tier 0 goldens: instance with the source's blending, with a different blending and with its own mask, exact
- [ ] 3.2 Tier 0 golden: source layer edited after instancing, instance output follows, exact
- [ ] 3.3 Tier 0 goldens: reference sources with channel mapping, referenced channel, alpha matte and levels, exact
- [ ] 3.4 Tier 0 goldens: anchor referenced from a mask stack and from a generator image input, exact
- [ ] 3.5 API probes: a reference cycle raises `ValueError` and leaves the revision unchanged; an instance inserted into an effect stack raises the documented error; source deletion matches the probe
- [ ] 3.6 Invalidation test: editing an anchored layer re-evaluates every dependent node and nothing else
- [ ] 3.7 Python-disabled MCP conformance fixtures for `layer_instantiate`, `anchor_list` and reference sources

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase4.2_remaining-nodes`: instance and anchor Tier 0 goldens exact or excepted; manifest updated

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
