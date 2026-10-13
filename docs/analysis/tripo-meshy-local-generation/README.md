# Tripo/Meshy internals and local high-poly generation on an RTX 4090

Desk research and machine inspection, 2026-10-13. No model was installed or run, and no vendor credits were spent. Sources: public papers, READMEs, API docs and vendor pages (cited inline), the Assets3D repository (`E:/UzmiGames/Assets3D`, cited as `Assets3D/…`), and measurements of this machine. Before this analysis, rulebook memory held no knowledge entries and no learnings on this topic.

Scope note: image-to-3D generation is an Assets3D stage. UzPainter lists replacing it as a non-goal (`docs/vision.md:54`). This analysis lives here because it was requested here; the work it proposes belongs in Assets3D.

## Answer

**How Tripo and Meshy work:**
- Neither vendor discloses its current architecture (F-005).
- In plain words, the documented open recipe works like this ([02](02-commercial-internals.md), step by step):
  1. An image network turns the picture into features.
  2. A large diffusion (flow) transformer turns random noise into a compact 3D code that fits those features.
  3. A decoder turns the code into a surface description, evaluated only near the surface on a grid refined coarse to fine.
  4. Triangles are cut from that surface: tens of millions at fine grids.
  5. A simplifier reduces them, and texture comes from a separate model.
- Tripo's open papers document this recipe (F-006):
  - TripoSG is a rectified-flow transformer over a 3D VAE, conditioned on DINOv2 and CLIP features. The released model has 1.5 B parameters; the paper's 4 B mixture-of-experts version is not released.
  - SparseFlex/TripoSF reaches 1024³, but its release is only a reconstruction autoencoder, not an image-to-3D model.
- Meshy states that 7.1 "Ultra 4K" generates on a 4096³ grid. Its raw meshes reach up to 80 M triangles, which Meshy then simplifies, and the detail is "built into the mesh" (F-007; Meshy's own claims, unmeasured).
- The commercial lead likely comes in large part from scale, curated data and robust extraction and simplification, not from a different method (F-008, inferred). Scale here means generators of 10 B parameters or more and grids up to 4096³. How much each factor contributes is unknown.
- **Triangle count is not detail.** The grid sets the smallest feature that can appear; the model and its training data set which features do. Vendor face limits measure output size, not quality: Tripo H3.1 up to 2 M, Rodin Gen-2.5 more than 10 M raw, Meshy 80 M raw (02).

**Can this RTX 4090 generate high-poly meshes locally?**
- **Yes, for high-poly meshes.** Open models under MIT run at 1024³ and produce millions of raw triangles (an estimate), more than the 0.16-1.8 M the pipeline uses today (F-002, F-010-F-012, F-018). The candidates to benchmark are TRELLIS.2 4B, Pixal3D (which also takes multi-view input) and Direct3D-S2.
- **Not yet shown: parity with Meshy 7.1.**
  - Against single-view Ultra 4K, the open grid is 4× coarser per axis at 1024³ and 2.7× at 1536³. Against multi-view Ultra 2K it is 2× and 1.33×.
  - No independent benchmark was found (F-014).
  - About 20 GB of the card's 24 GB is free, which puts 1536³ at risk (F-015).
- **Running locally does not fix the fusion defect.** Parts that touch fuse when one field describes the whole object (F-003). Free per-part generation is the local lever.
- **Do not train a model.** Assemble the open models and post-process; every panel model agreed ([06](06-model-panel.md)).

**Recommended next step:** take the phase 0 decisions (D1-D5, including DINOv3 access and freeing VRAM). Then prove each model's environment in 2 hours (phase 1) and run the bake-off against the stored Meshy highs (phase 2). Meshy stays the default until a local model measures at or above it ([05](05-execution-plan.md)).

**Model panel:** GPT-6.1, GPT-6-astra and GPT-5.6 answered both rounds; Kimi K3 answered round 1 and Grok 4.5 round 2. No claim drew a majority of DISAGREE. The one contested claim, how fusion arises, was narrowed in wording; its conclusion stands ([06](06-model-panel.md)).

## Verdict

| Question | Answer |
|---|---|
| Are the Tripo/Meshy internals public? | No. Tripo's open research and the public literature show the shared recipe; the commercial specifics are inferred. |
| Can a 4090 run a state-of-the-art open generator? | Yes, at 1024³ (to be measured). 1536³ must be proven: ~20 GB is free against a stated 24 GB minimum. |
| Is the local output "high-poly"? | Yes. The raw mesh is millions of triangles at 1024³, decimated to any target. |
| Is it as good as Meshy 7.1 Ultra 4K? | Unknown. It needs the phase 2 bake-off. |
| Does it remove the per-generation cost? | Yes. A sample costs electricity and roughly 0.5-5 min of GPU time (estimate), against about 25 Meshy credits. |
| Does it make generation re-runnable? | Likely, with a pinned checkpoint, seed and settings. Vendor models get retired (F-004). |
| Does it fix fused parts? | No. Only part-aware generation or finer per-part generation could, and both are untested (phase 4). |
| Is Windows ready? | Not upstream: the model repos are tested on Linux. Docker has a GPU runtime; the Ubuntu WSL distro is WSL1 and has no GPU access. Community Windows builds of TRELLIS.2 and Pixal3D exist, unverified (F-016). |

## Reading order

1. [Current use](01-current-use.md): F-001-F-004. Meshy 7.1 as the baseline, the 0.16-1.8 M triangle range, fusion, model retirement.
2. [Commercial internals](02-commercial-internals.md): a step-by-step walkthrough of how an image becomes a dense mesh and why triangle count is not detail, then F-005-F-009. What the 2026 products disclose, Tripo's papers, Meshy's 4096³ grid, the shared recipe, the API controls.
3. [Open models](03-open-models.md): F-010-F-014. Candidate table, TRELLIS.2, Pixal3D and Hunyuan3D-2mv for multi-view, Direct3D-S2, Hunyuan3D 2.1 licence, no benchmark.
4. [RTX 4090 feasibility](04-rtx4090-feasibility.md): F-015-F-019. Free VRAM, Linux and community Windows routes, time per sample, voxel size per piece, GPU sharing.
5. [Execution plan](05-execution-plan.md): phase 0 decisions, phase 1 environment proof, phase 2 bake-off against stored Meshy highs, phase 3 integration, phase 4 fusion experiments.
6. [Model panel](06-model-panel.md): who was asked, round-1 consensus and disagreements, the round-2 verdict per claim, and the decisions taken.

## Corrections after review (same day)

These were found by checking the first draft against primary sources and the panel:
- **TripoSG:** the released model is 1.5 B parameters; the 4 B mixture-of-experts model exists only in the paper (F-006).
- **TripoSF:** its release is a mesh-to-latent autoencoder, not an image-to-3D generator. The candidate table had listed it with image input (03).
- **TRELLIS.2:**
  - Its sparse voxels are "field-free": not every decoder uses a distance field (02, walkthrough step 4).
  - It needs gated DINOv3 weights (03, decision D5).
- **Multi-view:** Hunyuan3D-2mv also accepts multi-view input, under the Tencent licence. Pixal3D is the only MIT-licensed option (F-011).
- **Meshy-5:** the API retired it on 2026-10-10, in addition to the August discontinuation (F-004).
- **Added from sources:**
  - Tripo P1.0, H3.1 and P2.0; the Meshy 7 and 7.1 dates; Rodin Gen-2.5; Hunyuan3D 3.0's status; Hitem3D (F-005).
  - Community Windows builds (F-016).
  - Meshy's self-reported Detail Richness scores (F-014).
- **Narrowed after the panel:**
  - How fusion arises (F-003, F-018).
  - "Mainly scale" (F-008).
  - The dense-grid and 5·N² wording (02).
  - The bake-off metrics: contact checks, bake comparison, cleanup time (05).

## Limits

- Several figures come from third parties and are marked in the files: Hunyuan3D 2.1 on a 4090 (SaladCloud), 4090 out-of-memory reports, TRELLIS.2 memory per resolution (Apatero), and the Windows builds' low-VRAM and compatibility claims.
- The 4090 timings are estimates scaled from H100 figures.
- The fusion claim for other vendors is a model-panel opinion, not a test.
- The panel models did not know the 2026 releases. Their votes on those facts rest on reasoning, not knowledge (06).
- Meshy prices in USD were not verified; only the pipeline's recorded credit costs are used.
