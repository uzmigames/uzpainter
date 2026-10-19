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
- [ ] 2.9 Author `assets/defaults/baking.json` with per-entry provenance and a local check on the owner's machine (decision 028) against the private defaults capture
- [ ] 2.10 Implement linked groups (`set_linked_group`, `set_linked_group_common_parameters`, `unlink_all*`, `get_link_group*`, `get_linked_texture_sets*`) as one transaction across linked sets; persist `bake_settings {common, detail, per_baker}`
- [ ] 2.11 Register the MCP Baking parameter tools `bake_inspect`, `bake_configure`, `bake_set_mesh_inputs`, `bake_capture_preset`, `bake_apply_preset`

## 3. Tests
- [ ] 3.1 Tier 0 API-probe goldens for current baking defaults and property metadata (`common().keys()`, `baker(usage).keys()`, labels, widget types, enum values) compared exactly on the owner's machine
- [ ] 3.2 Defaults check: every `assets/defaults/baking.json` entry equals the private capture hash it cites
- [ ] 3.3 Local CPU lane (decision 200): repeatability of the ray-cast core on the analytic fixtures (plane, sphere, bevelled cube with highs) at 1, 4 and max threads — identical bytes
- [ ] 3.4 Matching and cage tests on the bevelled cube with highs (suffix filtering, `LowAsHigh`, distance-based and custom cage), dilation keeps RAW, subsampling coverage counts
- [ ] 3.5 Linked-set transaction test: a failing `set` on one linked set leaves every set unchanged; capability error test on an unqualified ISA configuration

## 4. Acceptance
- [ ] 4.1 Acceptance: defaults and property metadata exact against Tier 0 goldens; repeatable across thread counts; linked-set changes atomic

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Notes (feasibility slice, decision 302; 2026-10-19, branch `wt/bake-feas`)
- A permitted early-feasibility slice (SUP-014, `docs/roadmap.md` rule 1), not acceptance of any item above: no box is ticked, and prerequisite 1.1 still gates the task.
- Built: `src/bake/` (`EmbreeBaker` on the vendored Embree 4.4.1, its `BakeRequest`/`Capabilities`/`BakeResult`, the distance-based cage's primary ray, the AO usage), `tests/bake/` (authored fixtures generated in code, no Painter or Assets3D data) and the `bake-feasibility-tests` build step.
  - Toward 2.2: a synchronous `bake`, plus the capability error for an unqualified CPU, ISA or Embree build. `IBaker` and `JobHandle` are still open.
  - Toward 2.3: Hammersley addressing by texel index and sample id, a fixed reduction order and fixed 16 x 16 tiles.
  - Toward 2.6: the texel classes uncovered / straight hit / back-face hit / centre miss, and the ray classes escaped / front / back-face / self. Cage hit, hidden and `SubSampling` are still open.
- Toward 3.3 (plane, box and sphere-on-ground fixtures; the bevelled cube with highs is still open): the scene's bytes are identical at 1, 4 and 32 threads (SHA-256 `11cdde9b…e1d0fa`). `python -m pytest tests/bake/test_bake_feasibility.py`: exit 0, 12 passed.
- Parity: AO is `pending-evidence` (owner `phase3.4_baker-ao`), never `supported`. No Python or MCP symbol is exposed, so the capability manifest is unchanged.

## 7. Notes (request-model slice, decision 306; 2026-10-19, branch `wt/bake-req`)
- A second permitted slice (SUP-014), not acceptance: no box is ticked, prerequisite 1.1 still gates the task, and AO stays `pending-evidence` (owner `phase3.4_baker-ao`). No Python or MCP symbol is exposed, so the capability manifest is unchanged.
- Toward 2.2: `IBaker` (`caps()`, `bake() -> JobHandle`) and `JobHandle` (id, progress in tiles, `cancel()`, `wait()`, `Success | Cancel | Fail`, the result published whole on `Success` only); refusals are thrown before any job exists. SUP-023 fixed: workers in a joining container (a failed spawn no longer reaches `std::terminate`), Embree scene and geometries owned from their first acquisition, only the serial BVH build qualified (any other count bakes only on an explicit diagnostic path); SUP-031 fixed: a throwing tile callback fails the job instead of escaping a worker thread.
- Toward 2.4: `FilterMethod` Always / By mesh name with the `_low`/`_high`/`_ignorebf` suffixes, `LowAsHigh` with name matching, and `IgnoreBackface`, through an Embree argument filter on the primary ray.
- Toward 2.5: a custom cage given in memory (one per low part, same topology); loading it from a file stays `NotYetSupported`. Relative-to-bounding-box distances are still open.
- Toward 2.6: the `CageHit` and `Hidden` (request mask) texel classes; `SubSampling` 1/2/4/8 as per-texel coverage and hit counts.
- Toward 2.7: `DilationWidth` into uncovered texels only, RAW kept; `ApplyDiffusion` is refused (`NotYetSupported`). Units are still open.
- Toward 2.8: `BakingParameters`/`Property` with the keys of `06-baking.md` §2, labels and option labels from the public pages, value types only where a page widget or the task states them (others `Pending`), typed `set()` in one transaction; Painter's `name()`, `widget_type()`, enum integers, ranges, `properties()` and every default but the three suffixes raise `NotYetSupported` until the Tier 0 capture (2.8, 2.9, 3.1). Linked groups (2.10) are not started.
- Toward 3.3 and 3.4: the bevelled cube with highs (a chamfered cube, a knob with an `_ignorebf` cover, a decoy) with analytic per-texel classes. Its bytes are identical at 1, 4 and 32 threads (SHA-256 `0034cd97…2f3ed`); the sphere scene's RAW AO, class and ray maps are byte-identical to slice 1's. `python -m pytest tests/bake/test_bake_feasibility.py`: exit 0, 31 passed.
