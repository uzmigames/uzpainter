## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase3.7_fixtures-bracers-hat5` (parent input), `phase3.3_procedural-families` including `phase3.2_proc-filter-families`

## 2. Implementation
- [ ] 2.1 Sharpen filter effect in mask stacks: mono-channel evaluation of the current mask value, mask-stack blending with `channel=None`, documented insertion rules and errors
- [ ] 2.2 Expose the insertion and parameters through the native API, the facade (documented symbols only) and the typed MCP stack family; update the requirement-to-typed-operation matrix row
- [ ] 2.3 Author the Tier 0 sharpen mask fixtures (synthetic meshes, bitmap and levels mask content, parameter/mode/opacity sweep); record the Painter goldens twice through the documented API; manifests `parity/manifests/tier0/mask-sharpen-*.json`
- [ ] 2.4 Add hat v8's recorded Sharpen parameter sets to the Tier 2a matrix of the Sharpen family where missing
- [ ] 2.5 Capability manifest: Sharpen in the mask-stack context `supported` with its Tier 0 evidence id

## 3. Tests
- [ ] 3.1 Tier 0 sharpen mask goldens exact at native depth
- [ ] 3.2 Tier 2a for the Sharpen family with hat v8's recorded parameter sets
- [ ] 3.3 Mask-context API probes: set→get readback through a freshly resolved handle; a channel argument in mask-stack blending raises `ValueError` as documented; persisted after save/reopen
- [ ] 3.4 Effect-order test in a mask stack: sharpen computes from the mask value produced by the effects below it

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase4.2_coverage-hat-v8`: sharpen mask goldens exact; hat v8 Sharpen instances equal

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
