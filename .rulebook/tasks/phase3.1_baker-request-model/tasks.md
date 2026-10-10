## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase2.10_pilot-tunic-recovery

## 2. Implementation
- [ ] 2.1 Vendor Embree 4.x from its upstream release under `thirdparty/` with `LICENSE`, `NOTICE` and `ORIGIN.md`; pin version and build configuration (ISA set, tasking, no fast-math) in `build.zig`
- [ ] 2.2 Define `IBaker`, `Capabilities`, `BakeRequest` and `JobHandle`; implement `EmbreeBaker` with the explicit capability error for unqualified CPU/ISA configurations
- [ ] 2.3 Implement deterministic sampling (Hammersley by texel index and sample id), fixed reduction order and thread-count-independent tile partitioning
- [ ] 2.4 Implement low/high matching (`FilterMethod`, `_low`/`_high`/`_ignorebf` suffixes, `LowAsHigh`) and `IgnoreBackface`
- [ ] 2.5 Implement cages: custom cage mesh and distance-based frontal/rear (absolute or relative to the bounding box); report `Automatic` as a release gap in the capability manifest
- [ ] 2.6 Implement per-texel hit classification (straight hit, cage hit, centre miss, hidden) and `SubSampling` coverage accumulation
- [ ] 2.7 Implement `DilationWidth` with optional `ApplyDiffusion` on the baked map only, keeping RAW; record distances in project units
- [ ] 2.8 Implement the `BakingParameters`/`Property` model (`common()`, `baker(usage)`, `set`, `Property.*`) from the Phase 0 discovery capture; enum integers from `enum_values()` labels
- [ ] 2.9 Author `assets/defaults/baking.json` with per-entry provenance and a self-hosted check against the private defaults capture
- [ ] 2.10 Implement linked groups (`set_linked_group`, `set_linked_group_common_parameters`, `unlink_all*`, `get_link_group*`, `get_linked_texture_sets*`) as one transaction across linked sets; persist `bake_settings {common, detail, per_baker}`
- [ ] 2.11 Register the MCP Baking parameter tools `bake_inspect`, `bake_configure`, `bake_set_mesh_inputs`, `bake_capture_preset`, `bake_apply_preset`

## 3. Tests
- [ ] 3.1 Tier 0 API-probe goldens for current baking defaults and property metadata (`common().keys()`, `baker(usage).keys()`, labels, widget types, enum values) compared exactly on the owner's machine
- [ ] 3.2 Defaults check: every `assets/defaults/baking.json` entry equals the private capture hash it cites
- [ ] 3.3 Hosted CPU lane: repeatability of the ray-cast core on the analytic fixtures (plane, sphere, bevelled cube with highs) at 1, 4 and max threads — identical bytes
- [ ] 3.4 Matching and cage tests on the bevelled cube with highs (suffix filtering, `LowAsHigh`, distance-based and custom cage), dilation keeps RAW, subsampling coverage counts
- [ ] 3.5 Linked-set transaction test: a failing `set` on one linked set leaves every set unchanged; capability error test on an unqualified ISA configuration

## 4. Acceptance
- [ ] 4.1 Acceptance: defaults and property metadata exact against Tier 0 goldens; repeatable across thread counts; linked-set changes atomic

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
