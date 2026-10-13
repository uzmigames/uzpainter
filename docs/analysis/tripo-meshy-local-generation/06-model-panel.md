# 06. Model panel review

Two rounds of outside opinions on 2026-10-13, through the local 9router proxy. The panel informs wording and checks reasoning. Where it conflicts with a primary source, the source wins.

## Who was asked

| Round | Time (-03:00) | Prompt | Answered | Failed |
|---|---|---|---|---|
| 1 | 06:03-06:20 | The owner's question in English, as five open questions: vendor internals, how density is reached, feasibility on a 4090, train or assemble, hype claims. Every claim tagged [KNOWN] or [INFERRED] | cx/gpt-6.1-sol, cx/gpt-6-astra, cx/gpt-5.6-sol (temperature 0.3); kimi/kimi-k3 (temperature 1) | xai/grok-4.5 and xai/grok-4.6: two attempts each, HTTP 503 wrapping an upstream 502 "fetch connect timeout" |
| 2 | 06:30 | A self-contained dossier of the 15 claims below; AGREE / PARTLY / DISAGREE per claim, with reasoning | cx/gpt-6.1-sol, cx/gpt-6-astra, cx/gpt-5.6-sol, xai/grok-4.5 (temperature 0.3) | kimi/kimi-k3 (temperature 1) and xai/grok-4.6: two attempts each, same upstream 502 connect timeout |

Notes:
- Kimi K3 accepts only temperature 1. At 0.3 it returned HTTP 400, so its round-1 answer was taken at 1.
- Self-reported knowledge cutoffs are unreliable. They changed between rounds: GPT-6.1 said August 2025 in round 1 and June 2024 in round 2; GPT-5.6 said 2025-03-08, then June 2024. In round 2, Grok gave about October 2024. Kimi said early 2025, and GPT-6-astra gave none in round 1. In practice no model knew the 2026 releases (TRELLIS.2, Pixal3D, Meshy 7.1, Tripo H3.1/P2.0). All four round-2 models said so and judged those facts on reasoning alone.
- Raw answers were kept outside the repository, in the session scratchpad.

## Round 1: consensus

All four models agreed on these points, which match the analysis:
- Neither vendor's production internals are public, and TripoSR is not the current Tripo product.
- Triangle count is not detail. Sampling a field more finely adds no information, and FlexiCubes or dual contouring do not invent detail. GPT-6-astra: "Five-million-triangle smooth blob remains smooth blob."
- A dense 2048³ grid does not fit in 24 GB, so evaluation must be sparse or chunked.
- One 4090 can produce useful high-poly bake sources, but consistent parity with the services is not assured.
- Assemble existing models. Do not train from scratch, and fine-tune only for a narrow domain.
- Run the CUDA projects under Linux (WSL2 or containers) and keep the DCC tools (Blender, Painter) on Windows.
- Judge geometry with textures off: clay material, grazing light, wireframe.

## Round 1: disagreements and how they were settled

| Point | Positions | Evidence | Decision |
|---|---|---|---|
| Which open models | GPT-6.1: TripoSG, Hunyuan3D-2mv, TRELLIS. GPT-6-astra: TripoSG, TRELLIS, Hunyuan3D 2.0. GPT-5.6: a multi-view diffusion stack (Unique3D, Wonder3D, InstantMesh, CRM). Kimi: Hunyuan3D 2.1 or TRELLIS | All of these predate 2026. TRELLIS (v1) extracts its mesh at 256³: its decoder works at 64 and extracts at 4× (`trellis/models/structured_latent_vae/decoder_mesh.py`, [repo](https://github.com/microsoft/TRELLIS)). TripoSR defaults to `--mc-resolution 256` (`run.py`, [repo](https://github.com/VAST-AI-Research/TripoSR)). The 2026 models run at 1024-1536³ ([03](03-open-models.md)) | Keep the analysis's candidates: TRELLIS.2, Pixal3D, Direct3D-S2. The round-1 lists reflect the models' cutoffs. Hunyuan3D-2mv (GPT-6.1) was added as a multi-view option under decision D1 |
| Do the vendors generate extra views first (multi-view image diffusion)? | Yes, inferred: GPT-5.6, Kimi. Not necessarily: GPT-6.1, GPT-6-astra | Tripo's papers are 3D-native. Meshy describes an image encoder feeding generation on a 4096³ voxel grid ([F-005](02-commercial-internals.md), [F-007](02-commercial-internals.md)) | Not the core of any documented current system. It remains an optional input path and a texture-stage tool (F-008). Round 2, claim 4: nobody defended it as the core |
| Is vendor fine detail geometry or baked normal maps? | Kimi: "Pores, scratches, fabric weave = normal maps baked in texture stage." GPT-5.6: some detail in web renders "likely comes from normal maps" | Meshy's launch post says Ultra 4K detail is "built into the mesh itself rather than painted onto a texture map" ([Meshy 7.1](https://www.meshy.ai/blog/meshy-7-1-launch); self-reported). The pipeline turns texture off and bakes from the mesh (F-001, F-002) | The normal-map view is an opinion; the vendor claim is documented but unmeasured. For this pipeline the question is moot: only mesh detail reaches the bake. Check with clay renders (round 2, claim 11: unanimous) |
| Raw face count to expect | 100 k-1 M (GPT-6.1, GPT-5.6); tens of thousands to several hundred thousand, over 1 M with some decoders (GPT-6-astra); 0.5-2 M at 1024³ (Kimi) | TRELLIS.2's example caps the raw mesh at 16,777,216 faces ("nvdiffrast limit") before decimating to 1,000,000 ([repo](https://github.com/microsoft/TRELLIS.2)). Estimate: about 5 M at 1024³ (F-008) | Millions of raw triangles at 1024³ (estimate). The round-1 ranges fit the 256-512³ decoders the models knew |
| Starting resolution | GPT-5.6: start at 256³ or 512³, do not brute-force 1024³. GPT-6.1: 256-512³, then try 1024³ | Direct3D-S2 advises against 512, which is an intermediate stage ([repo](https://github.com/DreamTechAI/Direct3D-S2)). TRELLIS.2 takes about 17 s at 1024³ on an H100 | 1024³ is the working setting for the sparse models. 512³ serves only as a fit check (plan phase 1) |
| Size of the quality gap | Kimi: "~70-85% of commercial geometry quality". GPT-6-astra: "no fixed percentage gap is defensible here" | No benchmark compares open models with Meshy 7.1 (F-014) | No percentage. The gap is unknown until the bake-off |
| Time per asset | Kimi: 5-15 min of GPU plus 10-30 min cleanup. GPT-6-astra: 30-90 min for a usable prop. GPT-5.6: 30-90 min for a simple prop | The analysis's 0.5-5 min is GPU time per sample only (F-017) | No conflict: GPU time and total labour differ. Phase 2 now records cleanup minutes |

Smaller round-1 errors, compared with the documents:
- GPT-6-astra said TripoSG needs at least 16 GB; the repo says at least 8 GB.
- GPT-6-astra merged the Hunyuan3D 2.0 figures (6 GB shape, 16 GB with texture) with 2.1's 29 GB total.
- Kimi placed TRELLIS (v1) extraction at "up to 1024³"; its code extracts at 256³.
- Kimi had TripoSG decoding occupancy; the paper decodes an SDF.

## Round 2: verdicts on the 15 claims

A = AGREE, P = PARTLY, D = DISAGREE.

| # | Claim (short) | GPT-6.1 | GPT-6-astra | GPT-5.6 | Grok 4.5 | Change adopted |
|---|---|:-:|:-:|:-:|:-:|---|
| 1 | Neither vendor discloses its architecture | P | P | A | A | "Not disclosed in the sources reviewed" (F-005) |
| 2 | TripoSG = VAE + 1.5 B flow model; TripoSF is only a VAE | A | P | A | P | None needed: the figures were checked against the model cards today |
| 3 | Meshy: 4096³, 80 M raw, detail in mesh (vendor claims) | A | A | A | P | Keep raw, delivered and remesh counts apart; the vendor claims stay marked unmeasured |
| 4 | The shared recipe; multi-view diffusion is not the core | P | P | P | A | A family of recipes. Not every decoder uses an SDF: TRELLIS.2's O-Voxel is "field-free" ([model card](https://huggingface.co/microsoft/TRELLIS.2-4B)). Walkthrough step 4 and F-008 corrected |
| 5 | 4096³ cannot be dense; raw ≈ 5·N² | P | P | P | A | "Does not fit in memory; tiling fits but wastes the work." The constant 5 is illustrative |
| 6 | Triangle count is not detail; vendor figures are ceilings | P | P | A | A | "Output limits or reported maxima". "2 voxels" is a rule of thumb. Rodin's "more than 10 million" is not a ceiling |
| 7 | The commercial lead is mainly scale and engineering | P | P | P | A | "Likely in large part"; the contributions are unknown and undisclosed architecture may matter (F-008, README) |
| 8 | Best open candidates: TRELLIS.2, Pixal3D, Direct3D-S2 | P | P | P | P | "Candidates to benchmark, not a ranking" (03). Hunyuan3D 2.1 "runs easily" narrowed to its 10 GB shape stage |
| 9 | 1024³ feasible on ~20 GB; 1536³ unproven; minutes per sample | P | P | P | A | 1024³ is the first target after a 512³ fit check. Timings are planning estimates. `expandable_segments` reduces fragmentation, not demand (F-015, F-017) |
| 10 | Grid gap 4× / 2.7× (single view), 2× / 1.33× (multi-view); real gap unknown | P | P | A | A | Nominal voxel sizes. The gap matters for features small relative to the piece and the bake texel. "No benchmark found" (F-018, F-014) |
| 11 | Judge vendor detail on the untextured mesh | A | A | A | A | Unanimous. Imported normal maps off as well (02) |
| 12 | Local runs do not fix fusion; one field seals touching parts | D | D | P | A | Contested; see below |
| 13 | Do not train; assemble; local advantages | P | P | A | A | Keep the raw mesh untouched and bake from it. Local runs still cost electricity and labour. Seeds do not guarantee bit-exact repeats (F-004, plan phase 3) |
| 14 | Windows: Linux containers per model; community wheels | P | P | P | A | Check GPU passthrough and extension builds first. Community Windows builds are a fallback, checked against an upstream run (F-016, phase 1) |
| 15 | Next step: time-boxed bake-off; Meshy stays the default | P | A | A | A | Connected components cannot detect fusion. Added: contact checks against labelled parts, bake comparison on one low-poly, cleanup minutes and failure rate (plan phase 2) |

Totals: GPT-6.1 3 A / 11 P / 1 D; GPT-6-astra 3 A / 11 P / 1 D; GPT-5.6 8 A / 7 P; Grok 4.5 12 A / 3 P. No claim drew a majority of DISAGREE. Most PARTLY votes asked for more precise wording, not a different direction.

### The contested claim: fusion (claim 12)

- **For changing it:**
  - GPT-6-astra: "One scalar field can represent multiple disconnected surfaces."
  - GPT-6.1: "any resolution" overstates it.
  - GPT-5.6 proposed "single-field, single-surface pipelines usually merge touching or overlapping parts."
- **For keeping it:** Grok 4.5 agreed: "Local per-part split is real advantage."
- **Evidence:**
  - The pipeline's own audit shows fusion at bone contacts in Meshy output: the body high has 2 connected components (F-003).
  - Implicit-surface theory supports the objection: one field can hold separate pieces with a clear gap, but cannot keep touching or overlapping solids apart.
  - No open model has been tested on this content.
- **Decision (majority plus theory):**
  - The wording is narrowed. One field, or one unlabelled voxel set, cannot keep touching or overlapping parts apart, and the learned prior may close real gaps narrower than about 2 voxels; clearly separated pieces can survive.
  - The conclusion stands: running locally does not fix fusion by itself. The remedies are per-part generation, part-aware models, or manual separation.
  - Applied in F-003 and F-018.

### Omissions the panel raised, and where they went

| Omission | Raised by | Applied in |
|---|---|---|
| Compare normal/AO bakes on the same low-poly, cage and settings, not just meshes | GPT-6-astra, GPT-5.6 | Plan phase 2, "Bake" |
| Check whether the raw, undecimated mesh can be exported at all | GPT-6.1, GPT-6-astra | Plan phases 1 and 3 |
| Whole-pipeline budget: system RAM, export time, DCC load | GPT-6.1, GPT-6-astra | Plan phase 1 |
| Licence audit of every checkpoint, including the gated DINOv3 weights | GPT-5.6, Grok 4.5 | Decision D5 |
| Camera calibration and consistency of multi-view inputs | GPT-6-astra, GPT-5.6 | Already in F-011 (hand-written poses, back-view review) |
| FP8 checkpoints and offloading to fit 1536³ | Grok 4.5 | F-015 |
