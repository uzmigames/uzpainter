# 02. How Tripo and Meshy work inside, as far as public sources show

Both services are closed. This file separates three kinds of claim: what each vendor states, what its open research shows, and what follows by inference from the public research. Inferences are labelled.

## How an image becomes a dense mesh, step by step

This is the recipe the open systems document (TripoSG, TRELLIS.2, Direct3D-S2, Hunyuan3D 2.x). That Tripo and Meshy follow it is an inference (F-008). Figures are documented unless marked as estimates.

1. **Clean the picture.** The object is cut out from its background and centred. TripoSG's repo uses RMBG-1.4 for this ([repo](https://github.com/VAST-AI-Research/TripoSG)).
2. **Turn pixels into features.** A pretrained image network splits the picture into small patches and gives each patch a vector of numbers describing what is there (an edge, a fold, a rivet) and where. TripoSG uses DINOv2-L for local detail and CLIP-ViT-L/14 for the overall look ([arXiv 2502.06608](https://arxiv.org/html/2502.06608)). TRELLIS.2 uses DINOv3 (`trellis2/modules/image_feature_extractor.py` in its [repo](https://github.com/microsoft/TRELLIS.2)). Meshy 7's "multi-scale" image encoder is this step (F-005).
3. **Generate a 3D code, not a mesh.** A large transformer starts from random noise and, over a series of denoising steps, turns it into a compact 3D code (the *latent*) that fits the image features, which it reads through cross-attention. This is the diffusion / rectified-flow model, and the only stage that invents the hidden back. The code takes one of two forms:
   - a **vector set**: a fixed number of tokens with no fixed place in space (TripoSG: 512-4,096 tokens; Hunyuan3D 2.x);
   - a **sparse voxel latent**: vectors attached only to the cells of a coarse grid that the object occupies. TRELLIS.2 first decides which cells are occupied, then fills them with shape vectors, then with material vectors. Its "4 B" is three flow models of about 1.3 B parameters each (config names such as `slat_flow_img2shape_dit_1_3B_512_bf16.json` in its [repo](https://github.com/microsoft/TRELLIS.2)).

   Newer work mixes the two by tying tokens to coarse voxels: LATTICE's "VoxSet" ([arXiv 2512.03052](https://arxiv.org/abs/2512.03052)) and UltraShape's voxel-anchored refinement ([arXiv 2512.21185](https://arxiv.org/abs/2512.21185)). Pixal3D instead projects each pixel's features back into a 3D volume, so a pixel and the 3D point behind it are linked directly ([arXiv 2605.10922](https://arxiv.org/abs/2605.10922)).
4. **Decode the code into a surface description.** In most systems a decoder network answers, for any 3D point, "how far is this point from the surface, and is it inside or outside?" The answer is a signed distance field (SDF) or an inside/outside occupancy value, and the surface is where it crosses zero. The decoder is the second half of a VAE trained beforehand on a large 3D set (TripoSG: about 2 M curated objects). Sparse-voxel systems can skip the field: TRELLIS.2's O-Voxel is "field-free" and stores surface data in each active voxel directly, which lets it keep open and non-manifold surfaces ([model card](https://huggingface.co/microsoft/TRELLIS.2-4B)). Nothing is a triangle yet.
5. **Work only where the surface is (coarse to fine).** To build a mesh, the decoder is asked at the corners of a grid of N×N×N cells. At high N the full grid does not fit in memory: 4096³ is 6.9 × 10¹⁰ points, 128 GiB for a single 16-bit value each, and even 2048³ is 16 GiB. Evaluating it tile by tile would fit, but almost all of that work would be spent on empty space. So the decoder is asked on a coarse grid; only the cells the surface passes through are kept and split 2× per axis, and this repeats up to the final grid. A compact object's surface crosses only about 2.5·N² of the N³ cells (illustrative estimate, F-008), about 0.06 % at 4096³. That is how Meshy can generate "in a massive space with billions of voxels" (F-007) on real hardware. Open examples: TRELLIS.2 cascades 512³ → 1024³ → 1536³; Direct3D-S2 goes 512³ → 1024³.
6. **Cut the surface into triangles (surface extraction).** In each crossed cell, marching cubes reads the signs at the 8 corners and places one to four triangles where the field crosses zero, about two on average (an estimate). FlexiCubes and dual contouring place the vertices more carefully and keep sharp edges better; SparseFlex uses FlexiCubes ([arXiv 2503.21732](https://arxiv.org/abs/2503.21732)). The result is a very dense, evenly spaced mesh of the order of 5·N² triangles: roughly 5 M at 1024³ and 84 M at 4096³ (estimate, F-008; the constant depends on the shape), close to Meshy's "as many as 80 million".
7. **Simplify.** The raw mesh spends as many triangles on a flat cover as on an engraving. A decimator merges triangles where the surface is flat and keeps them where it bends, down to a target. The pipeline receives 0.16-1.8 M triangles from Meshy (F-002); TRELLIS.2's export example targets 1 M (F-010). Remeshing to quads and low-poly retopology are separate, optional steps (F-009).
8. **Texture separately.** Colour and PBR maps come from a second model run on the finished geometry (Hunyuan3D-Paint, or TRELLIS.2's material latent). Assets3D turns this stage off and paints in Painter/UzPainter.

**Why the triangle count is not the detail.** Three numbers matter, and they differ:
- **The grid (N)** sets the smallest feature that *can* appear: as a rule of thumb, a groove needs about 2 cells to survive extraction (F-018). It is an upper bound.
- **The model** (latent size, decoder, training data) sets which features *do* appear. If the decoded field is smooth, a finer grid only cuts the same smooth surface into more, smaller triangles. TripoSG's ablation shows where detail comes from. Its Normal-FID score, where lower is better, goes from 9.47 to 8.38 between 512 and 2,048 latent tokens, and only to 8.12 at 4,096 and 7.94 with mixture-of-experts. Replacing raw Objaverse with the curated TripoSG data takes it to 3.36 ([arXiv 2502.06608](https://arxiv.org/html/2502.06608), Table 2).
- **The triangle count** follows the surface area measured in cells, then whatever the simplifier keeps. A 10 M-triangle sphere carries no detail. A well-decimated 300 k-triangle mesh can keep everything a 5 M raw mesh had (an illustration, not a measurement).

Vendor face figures (Tripo H3.1 "up to 2,000,000"; Rodin Gen-2.5 "more than 10 million polygons" raw; Meshy 80 M raw; F-005) are output limits or reported maxima, not measurements of detail. Detail has to be judged on the untextured mesh, with imported normal maps off, under raking light, against the reference (plan phase 2).

## F-005 - Neither vendor publishes the architecture of its current model

**Evidence:**
- **Meshy 7:** the launch release names only a multi-scale image encoder that accepts higher-resolution input, and training data filtered so that each sample matches its target geometry ([PR Newswire, Meshy 7](https://www.prnewswire.com/news-releases/meshy-releases-meshy-7-a-new-foundation-model-that-sets-a-new-bar-for-image-3d-alignment-302849368.html)).
- **Meshy 7.1:** "we have scaled up our geometry representation and generation backbone", with mesh extraction and simplification "to support ultra-high face count". No paper, parameter count or data source is given ([Meshy 7.1 launch](https://www.meshy.ai/blog/meshy-7-1-launch)).
- **Tripo v3.1:** the model page gives inputs, prices and limits, but no architecture, parameter count or resolution ([Tripo v3.1](https://developers.tripo3d.com/en/models/v3-1)). Third-party sources give conflicting parameter counts for "Tripo 3.0" (20 B and 200 B), and VAST confirms neither.
- The current products of both vendors and their main competitors, as documented (checked 2026-10-13):

| Product | Date | Documented output | Architecture disclosed |
|---|---|---|---|
| Tripo H3.1 (API `v3.1-20260211`, the "flagship") | 2026-02 (date in the version string) | `face_limit` "up to 2,000,000", adaptive; `geometry_quality: detailed` ("Ultra") ([page](https://developers.tripo3d.com/en/models/v3-1)) | None |
| Tripo P1.0 | Announced 2026-03-09 (GDC) | Low-poly: face limit 48-20,000 ([P1 page](https://developers.tripo3d.com/en/models/p1)) | "Native 3D diffusion architecture" only ([PR Newswire](https://www.prnewswire.com/news-releases/tripo-ai-debuts-production-grade-native-3d-diffusion-at-gdc-2026-302708371.html)) |
| Tripo P2.0 | Preview August 2026; launched 2026-09-21 | Native quad-dominant meshes: up to 50,000 triangles or 25,000 quads; up to four versions per prompt ([VoxelMatters](https://www.voxelmatters.com/tripo-ai-launches-p2-0-model-to-generate-native-quad-meshes-for-production-pipelines/)) | "3D-native foundation model" only |
| Meshy 7 | Live 2026-08-10 (release dated 2026-08-12) | Geometry at 2048³ (7.1 launch FAQ) | Multi-scale image encoder, rebuilt data (above) |
| Meshy 7.1 | Rolling out from 2026-09-10; `latest` in the API from 2026-09-18 ([changelog](https://docs.meshy.ai/en/api/changelog)) | Ultra 2K at 2048³, Ultra 4K at 4096³; raw meshes up to 80 M triangles (F-007) | "Scaled up" representation and backbone only |
| Rodin Gen-2.5 (Hyper3D) | 2026-05-26 | Raw outputs "more than 10 million polygons"; raw triangle, quad and Smart Low-Poly outputs ([press release](https://business.thepilotnews.com/thepilotnews/article/pressadvantage-2026-5-26-hyper3d-launches-rodin-gen-25-bringing-sculpt-level-detail-and-production-control-to-ai-3d-generation)) | None for Gen-2.5. The earlier CLAY paper describes a VAE + latent DiT of up to 1.5 B ([arXiv 2406.13897](https://arxiv.org/abs/2406.13897)) |
| Hunyuan3D 3.0 (Tencent) | Announced 2025-09-16 | "1536³ geometric resolution", "3.6B voxel" (Tencent's claim, reported by [CGWorld](https://cgworld.jp/flashnews/01-202509-Hunyuan3D-30.html)) | No technical report; API only (F-013) |
| Hitem3D (Math Magic) | 2025-07-11 | Up to 1536³ (vendor's claim, [press release](https://www.barchart.com/story/news/33359451/math-magic-launches-worlds-first-15363-ultrahighresolution-ai-3d-model-generator-hitem3d)) | Built on its Sparc3D paper ([arXiv 2505.14521](https://arxiv.org/abs/2505.14521)); no weights |

**Impact:** Neither vendor's internals can be read from its product. They can only be inferred from the vendor's own open papers (Tripo) and from the public research both build on. A local replacement therefore has to be judged on its outputs (plan phase 2), not by matching architectures. For high-poly work Tripo's product is H3.1; P1.0 and P2.0 are low-poly and quad products.

**Confidence:** High that nothing is disclosed in the vendor pages, papers and press reviewed.

## F-006 - Tripo's open papers describe the recipe its products are built on

**Evidence:**

| Release | What it is | Scale and resolution | Licence and requirements |
|---|---|---|---|
| TripoSR ([arXiv 2403.02151](https://arxiv.org/abs/2403.02151)) | Feed-forward transformer that predicts a triplane (the LRM design), made with Stability AI | Output in under 0.5 s on an A100 | MIT; about 6 GB ([repo](https://github.com/VAST-AI-Research/TripoSR)) |
| TripoSG ([arXiv 2502.06608](https://arxiv.org/html/2502.06608)) | Rectified-flow transformer over a 3D VAE. The VAE is trained on SDF, normal and eikonal losses. Image features come from CLIP-ViT-L/14 (global) and DINOv2-L (local), each through its own cross-attention | The paper trains 1.5 B parameters, then scales to about 4 B with mixture-of-experts (8 experts, top-2, last six layers). 2,048→4,096 latent tokens. About 2 M training objects curated from Objaverse(-XL) and ShapeNet. **The released checkpoint is the 1.5 B model** ("1.5B parameters operating on 2048 latent tokens", [model card](https://huggingface.co/VAST-AI/TripoSG)); the paper does not say the 4 B model is released. The marching-cubes resolution is "a given resolution", not stated | MIT; ≥ 8 GB ([repo](https://github.com/VAST-AI-Research/TripoSG)) |
| TripoSF / SparseFlex ([arXiv 2503.21732](https://arxiv.org/abs/2503.21732)) | A sparse voxel grid kept only near the surface, plus a FlexiCubes-style surface extractor. Trained from rendering losses only. **The released TripoSF is only the autoencoder (VAE):** `inference.py --mesh-path` takes an existing mesh and reconstructs it. It does not take an image, and no image-conditioned generator for it is released | Up to 1024³ | MIT; ≥ 12 GB at 1024³ ([repo](https://github.com/VAST-AI-Research/TripoSF)) |

**Impact:** These papers show how Tripo builds a model: a shape latent space from a 3D VAE, a large flow transformer conditioned on image features, and sparse high-resolution surface extraction. Of the open releases only TripoSG turns an image into a shape. TripoSF shows how Tripo reaches 1024³, but it is not a local image-to-3D generator. The open checkpoints are early-2025 research models. The commercial v3.x is larger and is not disclosed (F-005). The open releases show the recipe; they do not reproduce Tripo's product.

**Confidence:** High for the papers. Low for how closely they match the commercial service.

## F-007 - Meshy 7.1 "Ultra 4K" generates on a 4096³ grid, then simplifies meshes of up to 80 M triangles

**Evidence:**
- `geometry_resolution` accepts `standard`, `2k` or `4k`. "`4k` runs it at 4096³" and requires `meshy-7.1` or `latest`. `ultra_mode: true` is the deprecated name for `2k` ([image-to-3d API](https://docs.meshy.ai/en/api/image-to-3d)).
- Ultra 4K is single-view only. Ultra 2K supports single- and multi-view. "A raw mesh directly from the model, without any simplification, can contain as many as 80 million triangles." Meshy claims to be the only model on the market at 4096³ ([Meshy 7.1 launch](https://www.meshy.ai/blog/meshy-7-1-launch); [VoxelMatters](https://www.voxelmatters.com/meshy-7-1-raises-geometric-detail-with-a-new-ultra-4k-mode/)).
- The same launch post says Meshy 7 generated at 2048³, and that Ultra 4K detail is "built into the mesh itself rather than painted onto a texture map". This is Meshy's own claim; no third party has measured it.
- Remeshing is off by default for Meshy 6/7. With triangle topology the API returns "a decimated triangle mesh" (same API page).
- The pipeline's delivered highs have 0.16-1.8 M triangles (F-002).

**Impact:** Meshy's own simplifier, not the grid, sets how many triangles the pipeline receives: roughly 40-500× fewer than the raw mesh. The grid sets the smallest feature the model can express. No open model found goes above 1536³ (F-010), so its grid is at least 2.7× coarser per axis than Meshy's Ultra 4K. Multi-view inputs are already limited to 2048³ at Meshy, which makes the multi-view gap smaller (1.33×).

**Confidence:** High for the API facts. The 80 M figure is Meshy's own claim and was not measured here.

## F-008 - The shared architecture (inferred): VAE latent, flow transformer, isosurface extraction, simplification

**Evidence:** Each stage below appears in several public systems that the vendors either published or compete with:

| Stage | Public examples | What sets the detail |
|---|---|---|
| 1. Input preparation | Background removal and recentring; DINOv2/CLIP features (TripoSG), DINOv3 (TRELLIS.2); Meshy's "multi-scale image encoder" | Input image resolution, and how cleanly the subject is isolated |
| 2. Shape latent (3D VAE) | Vector-set tokens: TripoSG with 2-4 k tokens, Hunyuan3D 2.x. Sparse voxel latents: TRELLIS.2 O-Voxel ([arXiv 2512.14692](https://arxiv.org/abs/2512.14692)), Direct3D-S2 ([arXiv 2505.17412](https://arxiv.org/abs/2505.17412)), Sparc3D ([arXiv 2505.14521](https://arxiv.org/abs/2505.14521)), SparseFlex. Hybrids: LATTICE "VoxSet" ([arXiv 2512.03052](https://arxiv.org/abs/2512.03052)) | Number of tokens or active voxels, and how much the VAE compresses |
| 3. Generator | Flow-matching / rectified-flow DiT: TripoSG 1.5 B released (4 B in the paper), TRELLIS.2 4 B (three ~1.3 B models), Hunyuan3D 2.5 "LATTICE" up to 10 B ([arXiv 2506.16504](https://arxiv.org/abs/2506.16504)) | Parameter count and training data. Vendors add curated or licensed data on top of Objaverse-class sets |
| 4. Coarse-to-fine | TRELLIS.2 cascade 512³→1024³→1536³; Direct3D-S2 512→1024; UltraShape refines a Hunyuan3D 2.1 coarse mesh ([arXiv 2512.21185](https://arxiv.org/abs/2512.21185)) | Final grid N³ |
| 5. Surface extraction | Marching cubes or FlexiCubes on SDF/occupancy, evaluated only in active cells; TRELLIS.2 reads its "field-free" per-voxel surface data instead | N³. A compact object yields roughly 5·N² triangles (estimate below) |
| 6. Simplification and delivery | Meshy's "extraction and simplification" step; TRELLIS.2 `to_glb(decimation_target=1000000)` and `simplify(16777216)` with the comment "nvdiffrast limit" ([TRELLIS.2](https://github.com/microsoft/TRELLIS.2)) | Vendor-chosen target |
| 7. Texture (optional) | A separate multi-view paint model (Hunyuan3D-Paint), or native PBR voxels (TRELLIS.2) | Not used by Assets3D: texture is off, and painting happens in Painter/UzPainter |

Size estimate (an inference, checked against Meshy's own figure): the surface of a compact object that fills the grid crosses about 2.5·N² cells, and marching cubes emits about 2 triangles per crossed cell. That gives about 5·N² triangles: roughly 5 M at 1024³, 12 M at 1536³, 21 M at 2048³ and 84 M at 4096³. The 4096³ figure agrees with Meshy's "as many as 80 million". The scaling with N² holds; the constant 5 is illustrative and varies with the object's surface area, thin parts and the extractor. That the numbers agree does not show how Meshy extracts.

Not every system follows every stage: TRELLIS.2 decodes surface data per voxel without an SDF (walkthrough step 4), and background removal, remeshing and texture are optional. Multi-view image diffusion, where a model first paints extra views and then reconstructs from them, is not the core of any current system found. Tripo's papers, TRELLIS.2, Hunyuan3D 2.x and Meshy's voxel-grid generation are 3D-native. Multi-view survives as an optional input (Meshy multi-image, Pixal3D, Hunyuan3D-2mv) and in texture stages. Whether a closed vendor uses it somewhere cannot be ruled out.

**Impact:** The commercial lead likely comes in large part from scale and engineering rather than a different principle: generators of 10 B parameters or more (estimate; the largest documented is Hunyuan3D 2.5 at 10 B), grids up to 4096³, proprietary data curation, a robust extractor and simplifier, and retries or ranking. How much each factor contributes is unknown, and undisclosed architecture differences may also matter. The open models work the same way at 4 B parameters and up to 1536³. A local model can therefore match the kind of output, a dense sealed mesh. How close it comes in learned detail can only be measured (plan phase 2).

**Confidence:** Medium. The stages are documented for the open systems; that the vendors use them is inferred.

## F-009 - The vendor APIs: Tripo controls face count and parts, Meshy controls resolution and simplification

**Evidence:**
- **Tripo v3.1:**
  - `face_limit` goes "up to 2,000,000" and is adaptive.
  - `geometry_quality` is `standard` or `detailed` ("Ultra"), at +20 credits.
  - Image and multiview generation cost 20/30/40 credits (no / standard / detailed texture).
  - Generate in parts costs +20 credits; quad costs +5 and smart low-poly +10.
  - Sources: [Tripo v3.1](https://developers.tripo3d.com/en/models/v3-1); `generate_parts` requires `texture: false` per the [migration notes](https://developers.tripo3d.com/assets/developer/tripo-v2-to-v3-migration/SKILL.md).
- **Meshy:**
  - `target_polycount` runs 100-300,000 when remeshing (default 30,000); `should_remesh` defaults to false for Meshy 6/7.
  - Multi-image takes `geometry_resolution` `standard` or `2k`, and 1-4 images.
  - Sources: [image-to-3d](https://docs.meshy.ai/en/api/image-to-3d); [multi-image-to-3d](https://docs.meshy.ai/en/api/multi-image-to-3d).

**Impact:** Tripo's `generate_parts` is the only vendor option aimed at the fusion defect (F-003). The pipeline cannot test it while Tripo's API balance is 0 (F-001). The open counterpart is part-aware generation, such as Tencent's Hunyuan3D-Part (P3-SAM + X-Part) ([model card](https://huggingface.co/tencent/Hunyuan3D-Part)); plan phase 4 covers it.

**Confidence:** High for the API facts. Neither part-generation route has been tested on this content.
