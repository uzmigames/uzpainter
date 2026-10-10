## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input); `phase1.14_compositor-core`, `phase1.24_python-api-facade` and `phase2.8_mcp-server` delivered

## 2. Implementation
- [ ] 2.1 `compare_mask` and `color_selection` effect kinds with their documented parameters; insertion only in mask stacks, the documented error elsewhere
- [ ] 2.2 Record the Tier 0 compare-mask and colour-selection goldens through the UzmiGames recorder (twice; blobs private, hashes in `parity/manifests/`) and fit their semantics into `parity/semantics/mask-effects.json`
- [ ] 2.3 Compare-mask kernel: mono-channel, in mask-stack order with its own mode and opacity
- [ ] 2.4 Colour-selection kernel reading the inputs its documented parameters name; a missing or invalid mesh-map binding fails evaluation loudly
- [ ] 2.5 Both kinds in `effect_insert`/`effect_set` for `uzpainter`, the facade and the MCP stack family with set→get readback and recipe-dump entries
- [ ] 2.6 Capability-manifest entries with evidence ids; operation-matrix rows with Python-disabled conformance fixtures

## 3. Tests
- [ ] 3.1 Tier 0 goldens: compare-mask parameter sweeps, exact
- [ ] 3.2 Tier 0 goldens: colour-selection parameter sweeps on an authored ID map, exact
- [ ] 3.3 Tier 0 goldens: both effects ordered with levels, fill and subtraction effects, with mode and opacity, exact
- [ ] 3.4 API probes: insertion into a content stack or the hierarchy raises the documented error without mutation; parameter set→get after save and reopen
- [ ] 3.5 Missing-input test: colour selection with no ID binding fails evaluation explicitly
- [ ] 3.6 Python-disabled MCP conformance fixtures for both kinds

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase4.2_remaining-nodes`: compare-mask and colour-selection Tier 0 goldens exact or excepted; manifest updated

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
