# 03. Open-weight candidates as of 2026-10-13

## Candidate table

These are candidates to benchmark, not a ranking: no common benchmark ranks them (F-014).

| Model | Licence | Generator | Max grid | Stated VRAM | Tested OS | Input | Output |
|---|---|---|---|---|---|---|---|
| **TRELLIS.2-4B** ([repo](https://github.com/microsoft/TRELLIS.2)) | MIT (nvdiffrast and nvdiffrec under their own licences). Image features come from DINOv3, a gated download ([ComfyUI-Trellis2](https://github.com/visualbruno/ComfyUI-Trellis2) notes the access requirement) | 4 B in three flow DiTs of ~1.3 B (structure, shape, material, per the repo's config names) over O-Voxel sparse latents | 1536³ (512/1024/1536) | ≥ 24 GB | Linux only (A100, H100); CUDA 12.4, torch 2.6. Community Windows builds exist (F-016) | 1 image | Mesh + PBR (base colour, roughness, metallic, opacity) |
| **Pixal3D** ([repo](https://github.com/TencentARC/Pixal3D), SIGGRAPH 2026, [arXiv 2605.10922](https://arxiv.org/abs/2605.10922)) | MIT | Pixel-aligned: back-projects image features into a 3D volume. TRELLIS.2 backbone on `main`, Direct3D-S2 on the `paper` branch | 1536 by default; 1024 with `--low_vram` | Not stated; `--low_vram` loads models on demand | Not stated by the authors; the community ComfyUI-Trellis2 node supports it on Windows, multi-view included since 2026-09-07 | 1 image, or multi-view (`inference_mv.py` + `transforms.json`, Sep 2026) | GLB, geometry + PBR |
| **Direct3D-S2** ([repo](https://github.com/DreamTechAI/Direct3D-S2)) | MIT | Sparse SDF DiT with spatial sparse attention | 1024³ | 512: ≥ 10 GB; 1024: ~24 GB | Ubuntu 22.04; Windows through community fixes in issues #11 and #12 | 1 image | Geometry only (OBJ) |
| **Hunyuan3D 2.1** ([repo](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1)) | Tencent Hunyuan 3D 2.1 Community Licence | 3.3 B shape + 2 B paint | Octree 256 by default, up to 512 in the community ComfyUI node ([RunComfy](https://www.runcomfy.com/comfyui-nodes/ComfyUI-Hunyuan3d-2-1/hy3-d21vae-decode)) | Shape 10 GB, texture 21 GB, 29 GB together | macOS, Windows, Linux | 1 image | Mesh, plus an optional texture |
| **Hunyuan3D-2mv** ([HF](https://huggingface.co/tencent/Hunyuan3D-2mv)) | Tencent Hunyuan community licence; the territory excludes the EU, the UK and South Korea ([licence](https://huggingface.co/tencent/Hunyuan3D-2/blob/main/LICENSE)) | Hunyuan3D-2 fine-tuned for multi-view shape control | Not stated | Not stated (Hunyuan3D-2 shape: about 6 GB per its [repo](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)) | Not stated | Front, left and back views | Mesh |
| **UltraShape 1.0** ([arXiv 2512.21185](https://arxiv.org/abs/2512.21185), [HF](https://huggingface.co/infinith/UltraShape), [repo](https://github.com/PKU-YuanGroup/UltraShape-1.0)) | Apache-2.0 (model card). Its code and base model are Hunyuan3D 2.1, so the Tencent licence may also apply; unresolved | Refines a coarse Hunyuan3D 2.1 mesh; 32,768 tokens, voxel queries at 128 (`configs/infer_dit_refine.yaml`) | Refinement stage | Not stated; `--low_vram`, `num_latents` 8192 and `chunk_size` 2048 lower it | Not stated | Coarse mesh + image | Geometry |
| **TripoSG** ([repo](https://github.com/VAST-AI-Research/TripoSG)) | MIT | 1.5 B rectified-flow transformer over a vector-set SDF latent (F-006) | Not stated (marching cubes at a chosen resolution) | ≥ 8 GB | Not stated | 1 image | Geometry |
| **TripoSF** ([repo](https://github.com/VAST-AI-Research/TripoSF)) | MIT | None: the release is a mesh-to-latent autoencoder (VAE) for reconstruction, not an image-to-3D generator (F-006) | 1024³ | ≥ 12 GB at 1024³ | Not stated | An existing mesh | Reconstructed geometry |
| **SAM 3D Objects** ([HF](https://huggingface.co/facebook/sam-3d-objects)) | SAM License, gated (legal name, date of birth and organisation required) | Not stated | Not stated | Not stated | Not stated | Masked object in a scene photo | The example exports a Gaussian splat |
| Hunyuan3D 2.5 (LATTICE, up to 10 B) / 3.0 / 3.1 | No open weights. 2.5 is a paper ([arXiv 2506.16504](https://arxiv.org/abs/2506.16504)). 3.0 is API only: its Hugging Face page returns HTTP 401 and the Tencent-Hunyuan GitHub organisation has no 3.x repository (checked 2026-10-13); press reports call an open release "planned" ([Notebookcheck](https://www.notebookcheck.net/Tencent-s-new-Hunyuan-3D-3-0-brings-realistic-AI-model-generation-to-developers-and-creators.1116964.0.html)) | — | 3.0: 1536³ (Tencent's claim, F-005) | — | — | — | — |
| Sparc3D (the model behind Hitem3D) | No weights found; offered as a hosted service | — | 1024³ in the paper ([arXiv 2505.14521](https://arxiv.org/abs/2505.14521)); Hitem3D is marketed at up to 1536³ (F-005) | — | — | — | — |

Not assessed (claims not verified): Step1X-3D, Hi3DGen, PartCrafter.

## F-010 - TRELLIS.2 has the highest open single-image grid, but its stated minimum is the 4090's entire memory

**Evidence:**
- TRELLIS.2 is "tested only on Linux" and needs "at least 24GB". On an H100 it takes about 3 s at 512³, 17 s at 1024³ and 60 s at 1536³, shape and material together.
- Its GLB export decimates to 1,000,000 faces with 4096 textures; MIT ([repo](https://github.com/microsoft/TRELLIS.2)).
- The O-Voxel paper says the representation handles "open, non-manifold, and fully enclosed surfaces" ([arXiv 2512.14692](https://arxiv.org/abs/2512.14692)).
- A Windows fork with a one-click installer claims to fit 1024³ on 8 GB ([TRELLIS.2-stableprojectorz](https://github.com/IgorAherne/TRELLIS.2-stableprojectorz)). This claim was not verified.

**Impact:** It has the highest open grid and a licence with no territorial limit. The 24 GB minimum leaves no room on this machine (F-015), so 1024³ is the first setting to test and 1536³ must be proven. Open and non-manifold surfaces could suit single-layer cloth. Nothing in O-Voxel labels parts, so parts that touch are not expected to come out separate (F-003); this is an inference, untested.

**Confidence:** High for the stated facts. The fork's low-VRAM claim is unverified.

## F-011 - Pixal3D is the only MIT-licensed open candidate found that accepts multi-view input

**Evidence:**
- MIT; built on TRELLIS.2 on `main`.
- Its conditioning is pixel-aligned: image features are projected back into a 3D volume instead of being read only through attention; multi-view input merges the volumes of several views ([arXiv 2605.10922](https://arxiv.org/abs/2605.10922)).
- Default resolution 1536, or 1024 with `--low_vram`.
- Multi-view inference arrived in September 2026 and needs a folder of views plus a `transforms.json` camera file, with weights separate from the single-image model ([repo](https://github.com/TencentARC/Pixal3D)).
- The other multi-view option found is Hunyuan3D-2mv (front, left and back views), under the Tencent licence and its territory limits (candidate table, F-013).

**Impact:** It fits the pipeline's four-view workflow (`Assets3D/Docs/Pipeline-Guide.md:48`, `:182`). Two things are needed:
- The reference sheets need known camera poses. For orthographic front/left/back/right sheets, the poses can be written by hand.
- Generated back views are "an inferred proposal" that need a consistency review (`Assets3D/Docs/Pipeline-Guide.md:180`). Multi-view does not remove that review.

At multi-view, Meshy itself is capped at 2048³ (F-007), so the gap in grid size is smallest here.

**Confidence:** High for the stated facts. Its use on this content is untested.

## F-012 - Direct3D-S2 produces geometry only, at 1024³, in about 24 GB

**Evidence:**
- "512 resolution requires at least 10GB of VRAM, and 1024 resolution needs around 24GB"; the authors advise against 512, which is an intermediate stage.
- Tested on Ubuntu 22.04 with CUDA 12.1, torch 2.5.1 and torchsparse; Windows through community fixes; MIT. Output is a mesh only ([repo](https://github.com/DreamTechAI/Direct3D-S2)).

**Impact:** Geometry-only output matches how the pipeline uses generators (texture off: `Assets3D/Pipeline/generation/generators_3d.py:120`). It needs a full 24 GB at 1024³, so it has the same memory problem as TRELLIS.2 at 1536³ (F-015). Its pinned CUDA and torch versions conflict with TRELLIS.2's, so each model needs its own environment (F-016).

**Confidence:** High.

## F-013 - Hunyuan3D 2.1 is the easiest to run on Windows, but it carries licence limits and a prior owner exclusion

**Evidence:**
- **Runs on Windows:** Windows is listed, and the shape stage alone needs 10 GB ([repo](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1)). One host ran it on an RTX 4090 in ComfyUI with a median of 139.2 s over more than 900 generations; settings not reported ([SaladCloud](https://blog.salad.com/?p=1389)).
- **Licence limits** ([licence text](https://huggingface.co/tencent/Hunyuan3D-2.1/blob/main/LICENSE)):
  - The territory excludes the EU, the UK and South Korea (§1.l).
  - Products with more than 1 M monthly active users need a separate licence from Tencent (§4).
  - Tencent claims no rights in outputs (§6.d).
  - Outputs may not be used to improve any other AI model (§5.b).
- **Owner decision:** "Rodin and Hunyuan3D were left out, by the user's decision" (`Assets3D/Docs/analysis/skeleton-reconstruction-meshy/08-hand-workbench.md:76`).
- **Newer versions:** no open weights were found for the newer Hunyuan models: 2.5 (LATTICE, 10 B) and 3.x.

**Impact:**
- Its documented Windows support makes it the quickest model to get running; only the shape stage (10 GB) is needed here, and the peak with the UltraShape refiner is not stated. UltraShape (Apache-2.0 card, built on Hunyuan3D 2.1) is a refinement stage made for it.
- **Assumption:** the owner's exclusion covered a paid API test, and may not cover a local run. Until the owner rules, the plan keeps Hunyuan3D out of the required set.
- Whether selling outputs to customers in the excluded territories conflicts with the territory clause is a legal question this analysis does not answer.

**Confidence:** High for the licence text. Medium for how far the owner's exclusion reaches.

## F-014 - No independent benchmark found compares open models with Meshy 7.1 or Tripo v3.1 geometry

**Evidence:**
- Meshy 7's numbers are self-reported, against four unnamed models: 81.0 % overall and 59.8 % on surface detail ([PR Newswire](https://www.prnewswire.com/news-releases/meshy-releases-meshy-7-a-new-foundation-model-that-sets-a-new-bar-for-image-3d-alignment-302849368.html)).
- Meshy 7.1's "Detail Richness" score is also self-reported and covers only commercial models: at a 1024 render, Meshy 7.1 53.5, Rodin 2.5 51.4, Hi3D 3.0 49.1, Tripo 3.1 44.8, Hunyuan3D 3.1 39.4 ([Meshy 7.1 launch](https://www.meshy.ai/blog/meshy-7-1-launch)). The metric rewards high-frequency normal variation, so surface noise could also raise it.
- Hands-on press tests of Ultra 4K exist, aimed at 3D printing, for example [All3DP](https://all3dp.com/1/we-tested-meshy-7-1-does-the-new-ultra-4k-really-improve-3d-prints/) (2026-09-30, verdict "yes and no"). They are qualitative, compare no open model, and were read only through search excerpts because the pages refused automated fetches.
- The roundups found are marketing, not measurements ([example](https://sorceress.games/blog/bench-an-image-to-3d-model-generator-browser-8-models)).
- The open papers compare themselves with each other, not with Meshy 7.1 or Tripo v3.1.

**Impact:** Whether local output reaches parity cannot be settled by reading. It needs a bake-off on the pipeline's own references, checked against the Meshy highs already stored (plan phase 2).

**Confidence:** Medium. This rests on not finding a benchmark.
