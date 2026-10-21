## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.3_baker-evidence-publication

## 2. Implementation
- [ ] 2.1 Implement the `ID` baker for each `ColorSource`: Vertex Color, Material Color, File ID, Mesh ID/Polygroup
- [ ] 2.2 Implement each `ColorGenerator` (Random, Hue shift, Grayscale) matching Painter's assignment; record the effective palette in the receipt
- [x] 2.3 Add exact label-equality and edge-coverage diagnostics to the comparison tool
  - Note (2026-10-21): `tools/parity/tier1/compare.py` `exact_check`: for the maps a `Subject` names in `id_maps`, the equality report's map entry carries `exact_checks` [{check: `id_labels`, equal, differing_count, edge_coverage_differing_count}] (schema `parity/schema/comparison-report.json`): a texel's label is all its channels; the edge-coverage count is the differing texels on an edge of the oracle's map (a texel differing from one of its four neighbours, no wrapping); a NaN equals only a NaN. The counts reach the register as `id_label_differing_count` and `edge_coverage_differing_count` (CONTRACT.md §8.2). Evidence: `tests/parity/tier1/test_tier1_compare.py` (equal maps pass with zero counts; one edge texel off fails with differing 1 / edge 1, an added interior texel gives 2 / 1; register bounds on the counts pass one edge texel and fail the interior one; NaN and shape refusals), 34 passed, exit 0 (log `tmp/scratch/parity-tools/pytest-compare.log`). CPU only.
- [ ] 2.4 Author the `ID` Tier 2b manifests under `parity/manifests/`

## 3. Tests
- [ ] 3.1 Tier 2b on plane, sphere and bevelled cube with highs for each `ColorSource` × `ColorGenerator` pair the fixtures exercise: hit/coverage first, then maps, exact
- [ ] 3.2 Tier 2b on the wand and hat low/high/cage pairs, exact against private goldens
- [ ] 3.3 Repeat 3.1 at two thread counts and on each qualified ISA; identical bytes

## 4. Acceptance
- [ ] 4.1 Acceptance: `ID` Tier 2b exact or covered by an owner-approved exception on every fixture

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Native CPU label map (2026-10-20, decision 337)
- `src/bake/id_baker.{h,cpp}` on the shared primary hit of `embree_baker.cpp`: with `ColorSource` Mesh ID / Polygroup, a hit texel's label is the index of the high mesh it hit plus one, in request order (`LowAsHigh`: the low part); 0 on non-hit texels, which keep their class. `BakeResult::id_labels` (uint16) and `id_label_meshes` (names in label order); the canonical bytes gain an `IDM1` block only when the map exists.
- Refused before any work with `NotYetSupported` naming this task: `ColorSource` Vertex color, Material color (Painter's default) and File ID (the bake mesh carries no such input) and Submesh (unrecorded); every `ColorGenerator` (the colour Painter gives a label is not recorded), so no colour map and no palette exist yet; `SubSampling` > 1 and `DilationWidth` > 0. A request without a generator bakes the label map only; `RequestFromParameters` always sets one.
- Parameters: ID's values are stored per texture set, saved in `bake_settings.per_baker.ID`, loaded and mapped; no link group (refused, naming this task).
- Evidence (not ticking 2.1, which needs every ColorSource): native cases `id_plane` (two high planes, one label each, 512 texels each), `id_sphere` (the sphere on the ground as one part and as two), `id_bevel` (cube and knob highs matched by name against the analytic hits; the decoy never labelled; with Always the decoy's back faces leave no label), `id_isolation`, `id_refusals`, `id_parameters`.
- Thread counts: `id_threads_in_process` and `test_bytes_equal_across_thread_counts[id-32]`: identical bytes at 1, 4 and N threads on the one qualified ISA (AVX2). Not 3.3, which repeats 3.1's Tier 2b comparison.
- Run: `python -m pytest tests/bake/test_bake_feasibility.py tests/bake/test_baking_project.py -k "id_ or id- or capability_errors or parameters or bake_settings or linked_groups or roundtrip or transactions or invalid"`, 17 passed, exit 0 (log `tmp/scratch/bakers-simple/pytest-id.log`). CPU only.
- Still open: 1.1 (prerequisites not accepted); 2.1 (only Mesh ID / Polygroup; the other sources need bake-mesh inputs and goldens); 2.2 (generators and the recorded palette wait on goldens); 2.4 (manifests); 3.1-3.3 and 4.1 (Tier 2b); the task-wide tails 5.1-5.3. No parity is claimed.
