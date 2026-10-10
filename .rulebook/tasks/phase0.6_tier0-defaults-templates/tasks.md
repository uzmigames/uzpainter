## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store

## 2. Implementation
- [ ] 2.1 Instruction sequence for baking defaults: fresh project, `BakingParameters.common()` and `baker(usage)` for the ten `MeshMapUsage` bakers, every key with value, name, short name, label, widget type, enum values, enum value and nested properties
- [ ] 2.2 Instruction sequence for templates: enumerate the project templates shipped with Painter 12.1.0 that the documented project-creation API accepts; create a project per template on a UzmiGames synthetic mesh and read back each stack's channel set and `ChannelFormat` through the documented `textureset` API
- [ ] 2.3 Record each capture at least twice (same session; after save/reopen; defaults also on a second fresh project) in the shape of `parity/schema/golden-private.json`
- [ ] 2.4 Admit the captures with `uzpainter parity record` and write `parity/manifests/phase0/tier0-defaults-templates.json` with instruction sequences, template identifiers, Painter build id and hashes only

## 3. Tests
- [ ] 3.1 Completeness test: the defaults capture contains every key returned by `common().keys()` and by `baker(usage).keys()` for all ten usages, and the template capture lists every enumerated template
- [ ] 3.2 Manifest test: the public manifest validates against `parity/schema/golden-public.json` and contains no captured value
- [ ] 3.3 Store test: `uzpainter parity verify` passes for every hash on the owner's machine
- [ ] 3.4 Guard test: a captured defaults JSON staged for commit is rejected by the repository guard

## 4. Acceptance
- [ ] 4.1 Child acceptance (contributes to P0-TIER0): baking defaults and template channel sets/formats captured ≥ 2× through the documented API; blobs private, hashes public; verify passes

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
