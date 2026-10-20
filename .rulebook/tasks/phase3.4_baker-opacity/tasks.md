## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.3_baker-evidence-publication

## 2. Implementation
- [x] 2.1 Implement the `Opacity` baker: high-poly opacity at the hit, misses handled per the shared ray-cast core - native CPU map in section 6 (decision 341)
- [ ] 2.2 Encode in the channel format established by the Tier 2b goldens; record it in the receipt
- [ ] 2.3 Add exact alpha-equality and edge-coverage diagnostics to the comparison tool
- [ ] 2.4 Author the `Opacity` Tier 2b manifests under `parity/manifests/`

## 3. Tests
- [ ] 3.1 Tier 2b on plane, sphere and bevelled cube with highs: hit/coverage first, then maps, exact against private goldens
- [ ] 3.2 Tier 2b on the wand and hat low/high/cage pairs, exact against private goldens
- [ ] 3.3 Repeat 3.1 at two thread counts and on each qualified ISA; identical bytes

## 4. Acceptance
- [ ] 4.1 Acceptance: `Opacity` Tier 2b exact or covered by an owner-approved exception on every fixture

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Native CPU map (2026-10-20, decision 341)
- `src/bake/opacity_baker.{h,cpp}` on the shared primary hit of `embree_baker.cpp`: the opacity of the high surface at the hit. A bake mesh carries no transparency input, so a hit texel is 1; misses, back-face hits, hidden and uncovered texels are 0 and keep their class, as in every map of the core. `BakeResult::opacity` is float32 in [0, 1], unencoded; the canonical bytes gain an `OPA1` block only when the map exists.
- Refused before any work with `NotYetSupported` naming this task and decision 341: `SubSampling` > 1 (no recorded resolve or coverage fraction) and `DilationWidth` > 0. Opacity has no parameters (`assets/defaults/baking.json`), so nothing is stored or mapped.
- Assumption: if Painter's Opacity reads a transparency of the high mesh (a texture's alpha, a material opacity), that input lies outside the bake mesh and outside every analytic fixture.
- Evidence for 2.1: native cases `opacity_plane` (a high plane under half the low plane: the covered left half 1, the right half centre misses at 0; a full plane: every covered texel 1), `opacity_sphere` (low as high: 1 on every straight hit, the back-face contact texels 0), `opacity_bevel` (the bevelled cube with highs against the analytic hits at max_depth 0.04 and 0.07), `opacity_isolation` (with AO: AO's bytes and classes unchanged, no `OPA1` block in an AO result) and `opacity_refusals`.
- Thread counts: `opacity_threads_in_process` and `test_bytes_equal_across_thread_counts[opacity-32]`: identical bytes at 1, 4 and N threads on the one qualified ISA (AVX2). Not 3.3, which repeats 3.1's Tier 2b comparison.
- Run: `python -m pytest tests/bake/test_bake_feasibility.py -k "opacity or capability_errors"`, 8 passed, exit 0 (log `tmp/scratch/bakers-more/pytest-opacity.log`). CPU only.
- Still open: 1.1 (prerequisites not accepted); 2.2 (the channel format waits on the goldens; nothing publishes a receipt yet, `phase3.3_baker-evidence-publication`); 2.3 (alpha-equality and edge-coverage diagnostics belong to the comparison tool under `tools/parity`, outside this slice); 2.4 (manifests under `parity/manifests/`); 3.1-3.3 and 4.1 (Tier 2b against private goldens); the task-wide tails 5.1-5.3. No parity is claimed.
