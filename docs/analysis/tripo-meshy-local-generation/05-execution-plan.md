# 05. Execution plan

**Where:** this work belongs in the Assets3D repository (`Pipeline/generation/`, tasks under `Assets3D/.rulebook/tasks/`). UzPainter does not change: generation is a non-goal for UzPainter (`docs/vision.md:54`).

**Rule:** Meshy stays the default high-poly source until phase 2 measures a local model at or above it on the bake and the reference review (not necessarily on every metric). A local model that loses on detail can still be used where cost and control matter more: drafts, extra seeds and per-part trials.

## Phase 0 - Decisions (no GPU work)

| # | Decision | Who | Input |
|---|---|---|---|
| D1 | Whether Hunyuan3D 2.1 (+ UltraShape) and Hunyuan3D-2mv join the local bake-off | Owner, who excluded Hunyuan3D earlier | F-011, F-013 |
| D2 | Docker CUDA containers, one image per model (recommended: no change to the owner's distro), or converting `Ubuntu-24.04` to WSL2 | Owner, if converting; otherwise the agent | F-016 |
| D3 | Generation jobs take the same one-GPU-run slot as UzPainter's GPU suites | Coordinator | F-019 |
| D4 | Free VRAM: move the 1080p display to the integrated GPU, or set desktop programs to power saving | Owner (a physical or settings change) | F-015 |
| D5 | Request access to Meta's gated DINOv3 weights on Hugging Face (TRELLIS.2 and Pixal3D need them) and record the licence terms of every checkpoint used | Owner (account action and licence acceptance) | F-016, [03](03-open-models.md) candidate table |

**Exit:** D1-D5 are recorded in an Assets3D decision.

## Phase 1 - Prove the environment (2 h time box per model)

1. Check that the GPU is visible inside a container before building anything else.
2. Build one container image per model, with caches on D:/E:/F::
   - TRELLIS.2: CUDA 12.4, torch 2.6.
   - Pixal3D: on TRELLIS.2.
   - Direct3D-S2: CUDA 12.1, torch 2.5.1.
   - Hunyuan3D 2.1, only if D1 allows it.
   - If a TRELLIS.2 or Pixal3D build fails inside its time box, try the community Windows build (F-016) before dropping the model.
3. Run each model's official example image at 512³ as a fit check, then 1024³, then 1536³ where the model supports it.
4. Record for each run:
   - Peak VRAM, from `torch.cuda.max_memory_allocated` and `nvidia-smi`.
   - Wall time, cold start and warm separately.
   - Raw and decimated triangle counts, and whether the raw (undecimated) mesh can be exported.
   - Peak system RAM and export time for the raw mesh.
   - Checkpoint SHA-256, seed and settings.

**Exit:** each model either runs at ≥ 1024³ within the free VRAM, or is dropped with the measured reason. This confirms or corrects F-015 and F-017.

## Phase 2 - Bake-off against the stored Meshy highs

**Corpus.** Each piece already has its reference, its Meshy high and the reference-view cameras (`Assets3D/Creatures/Undead/Skeletal Mage/Models3D/ref-views.json`):

| Piece | What it tests |
|---|---|
| 09 Staff, 12 Bone wand | Long, thin pieces |
| 10 Hat | Cloth folds |
| 13 Grimoire | Four views. Pixal3D multi-view against Meshy Ultra 2K |
| 14 Ritual lantern | Fine relief (1.8 M-triangle source) |
| One skeletal unit (palm, or the skull crop) | Fusion (F-003) |

**Runs:** each surviving model at 1024³, and at 1536³ where phase 1 allows, with 4 seeds per piece. Use the same reference images Meshy received, with hashes recorded.

**Measurements:**
- **Shape against the reference:** silhouette IoU (overlap) against the reference views, using the stored cameras.
- **Side-by-side renders:** clay renders under the pipeline's fixed render preset, next to the Meshy high.
- **Topology:**
  - Connected components.
  - Non-manifold edges.
  - Thin features lost or fused.
  - Contacts: for the skeletal unit, check each known bone contact against labelled parts. A fused union can be perfectly manifold with one component, so the counts above cannot detect fusion on their own.
- **Bake:** normal and AO bakes onto the same low-poly target with the same cage and settings, from each candidate high and from the Meshy high. The bake, not the triangle count, decides.
- **Cost:**
  - Raw and decimated triangles.
  - Time, including the minutes of cleanup each accepted high needed.
  - Peak VRAM.
  - Failure rate: seeds rejected per accepted high.

**Review:** the pipeline's usual review against the reference, with the generator labels hidden. The owner looks only at the final board.

**Exit:** a table recording, for each piece and model, whether the local output is at or above Meshy or below it, with the reason, plus a go or no-go for phase 3.

## Phase 3 - Integration (only on a go from phase 2)

1. Add a `local` subcommand to `Assets3D/Pipeline/generation/generators_3d.py`. It writes the same `job.json` as the vendor routes, plus:
   - Checkpoint hash, seed, resolution, steps, peak VRAM and seconds.
   - A check that the GPU slot is free (D3).
2. Store outputs read-only, exactly as Meshy highs are stored (`Assets3D/Docs/Pipeline-Guide.md:42`). Keep the raw mesh next to the decimated high, so later decimation choices can be redone without regenerating.
3. Take one piece's local high through the full pipeline (retopology, UV, bake) to prove it is usable downstream.

**Exit:** one piece is accepted at the bake stage from a local high, and its regeneration from `job.json` repeats it (F-004).

## Phase 4 - Fusion experiments (optional, after phase 2)

1. Generate parts separately on the hand pilot. With no per-generation cost, splitting finer is no longer limited by credits (`Assets3D/Docs/analysis/skeleton-reconstruction-meshy/08-hand-workbench.md:80`).
2. Try part-aware generation:
   - Hunyuan3D-Part (P3-SAM + X-Part), if D1 allows it.
   - Tripo `generate_parts`, if its API is funded (F-009).

**Exit:** parts that touch come out as separate solids, or a recorded negative result that closes the question.

## Not in scope

- Texture generation: the pipeline paints in Painter/UzPainter.
- Training a generator. One 4090 cannot train a foundation model of this kind. Fine-tuning is worth considering only if phase 2 shows a narrow, repeated failure and licensed 3D data exists for it ([06](06-model-panel.md), claim 13).
- Replacing Meshy multi-view before Pixal3D multi-view has proven itself.
- Any change to UzPainter.
