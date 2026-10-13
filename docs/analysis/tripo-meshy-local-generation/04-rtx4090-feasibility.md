# 04. Running it on this RTX 4090

Measured on this machine on 2026-10-13: RTX 4090 (24,564 MiB), driver 617.14 (CUDA 13.4 user-mode driver), Ryzen 9 7950X3D, 127 GB RAM, Windows 11 Pro 26200.

## F-015 - Only about 20 GB of the 4090's 24 GB is free, below the stated minimum for the top settings

**Evidence:**
- `nvidia-smi` at about 06:10: 3,689 MiB used and 20,450 MiB free, with `display_active` enabled. An earlier reading at 06:02 showed 3,572 MiB used.
- The used memory belongs to desktop programs: Edge WebView2, Discord, WhatsApp, PowerToys, Kaspersky UI.
- `Win32_VideoController`: the 4090 drives a 1920×1080 display, and the AMD integrated GPU drives the 5120×1440 one.
- Stated minimums:
  - TRELLIS.2: ≥ 24 GB (F-010).
  - Direct3D-S2 at 1024³: ~24 GB (F-012).
  - Hunyuan3D 2.1 shape: 10 GB (F-013).
- A community guide reports occasional out-of-memory errors on a 4090 ([Patreon](https://www.patreon.com/posts/146806567), unverified).
- A third-party guide puts TRELLIS.2 at about 20 GB for 1024³ and about 32 GB for 1536³ ([Apatero](https://apatero.com/blog/trellis-2-comfyui-image-to-3d-complete-guide-2025), unverified).

**Impact:**
- TRELLIS.2 at 1536³ and Direct3D-S2 at 1024³ will probably run out of memory unless memory is freed. Two ways to free it:
  - Move the 1080p display to the motherboard output, which the integrated GPU already uses.
  - Set the desktop programs to "power saving" in Windows graphics settings, so they run on the integrated GPU.
- Lower-memory paths: Pixal3D `--low_vram` (1024), loading stages one at a time, the UltraShape low-VRAM flags, and the community FP8 checkpoints for TRELLIS.2 ([ComfyUI-Trellis2](https://github.com/visualbruno/ComfyUI-Trellis2), 2026-02-26; quality unchecked). `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` (TRELLIS.2 README) reduces fragmentation, not the memory the model needs.
- 1024³ is the first target to test, after a 512³ fit check. 1536³ goes into the plan as something to test, not to assume.

**Confidence:** High for the measurements. Medium for the out-of-memory prediction: no model was run.

## F-016 - The Linux route is half ready: Docker can use the GPU, but the Ubuntu WSL distro is WSL1

**Evidence:**
- **WSL:** `wsl -l -v` lists `Ubuntu-24.04` at version 1 (stopped) and `docker-desktop` at version 2 (running). WSL 2.6.1.0 is installed, with kernel 6.6.87.2-1.
- **Docker:** `docker info` lists an `nvidia` runtime.
- **Windows toolchain:** CUDA toolkit 12.1 (`nvcc` V12.1.66); Python 3.10, 3.12 and 3.13.
- **Versions each model pins:**
  - TRELLIS.2: CUDA 12.4 and torch 2.6, plus flash-attn, nvdiffrast, nvdiffrec, CuMesh, FlexGEMM and o-voxel built by `setup.sh` ([repo](https://github.com/microsoft/TRELLIS.2)).
  - Direct3D-S2: CUDA 12.1, torch 2.5.1 and torchsparse ([repo](https://github.com/DreamTechAI/Direct3D-S2)).
  - Hunyuan3D 2.1: cu124, and builds a custom rasterizer and mesh painter ([repo](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1)).
- **Disk:** C: has 63 GB free; D:, E: and F: have 455-847 GB.
- **Native Windows (community, not upstream):**
  - The ComfyUI-Trellis2 node ships Windows wheels, is "Tested on Windows 11 with Python 3.11 and Torch = 2.7.0 + cu128", and supports Pixal3D, multi-view included ([repo](https://github.com/visualbruno/ComfyUI-Trellis2)).
  - The TRELLIS.2-stableprojectorz fork has a one-click Windows installer (Python 3.11, CUDA 12.8, Torch 2.8) ([repo](https://github.com/IgorAherne/TRELLIS.2-stableprojectorz)).
- **Gated weights:** TRELLIS.2 and Pixal3D load DINOv3 image features, which need access granted on Hugging Face ([03](03-open-models.md), candidate table).

**Impact:**
- WSL1 has no GPU access. Two ways to fix that:
  - Convert the distro to WSL2. This changes the owner's machine configuration, so it needs the owner's approval.
  - Run each model in a CUDA container on Docker Desktop's existing GPU runtime. Check first that the GPU is visible inside a container and that the model's CUDA extensions compile.
- The pinned versions conflict with each other, so each model needs its own environment or image.
- The community Windows builds are a fallback if a container fails. They run newer torch and CUDA than upstream, so their output must be checked against an upstream run.
- A 4 B-parameter checkpoint is about 8 GB at 16-bit precision. Keep the model caches (`HF_HOME`) and Docker data off C:.
- RAM is not a constraint.

**Confidence:** High.

## F-017 - Each generation takes minutes on a 4090; the vendors' second-scale figures are for an H100

**Evidence:**
- TRELLIS.2 on an H100 takes 17 s at 1024³ and 60 s at 1536³ (F-010).
- Hunyuan3D 2.1 on a 4090 had a median of 139.2 s over more than 900 generations, settings not reported ([SaladCloud](https://blog.salad.com/?p=1389)).
- Memory bandwidth (public specifications): 4090 about 1.0 TB/s; H100 2.0 TB/s (PCIe) to 3.35 TB/s (SXM). Sparse-voxel decoding and attention over many tokens are mostly limited by memory speed.

**Impact (planning estimate, to be measured in plan phase 1; bandwidth alone does not predict runtime, since compute, sparse kernels, offloading and extraction also count):** a 4090 should take 2-5× the H100 time:
- About 0.5-1.5 min per sample at 1024³.
- About 2-5 min at 1536³, if it fits.

That is 10-100 samples per hour. It is enough to try several seeds for each piece. Each extra sample costs only electricity, where Meshy charges about 25 credits per generation (F-001).

**Confidence:** Low to medium. This is an estimate from public figures; nothing was run here.

## F-018 - At the scale of one piece, a 1024-1536³ grid already resolves sub-millimetre detail

**Evidence:** Edge length of one voxel at each grid size; generators normalise the object to fill the grid:

| Object (longest side) | 1024³ | 1536³ | 2048³ (Meshy 2K) | 4096³ (Meshy 4K) |
|---|---:|---:|---:|---:|
| Grimoire, 24 cm (`Assets3D/Docs/Pipeline-Guide.md:182`) | 0.23 mm | 0.16 mm | 0.12 mm | 0.06 mm |
| Whole figure, about 1.9 m (example) | 1.86 mm | 1.24 mm | 0.93 mm | 0.46 mm |

**Impact:**
- **Per piece:** the pipeline generates one piece at a time (`Assets3D/Docs/Pipeline-Guide.md:40`), so the grid gap to Meshy matters for features that are small relative to the piece and to the bake's texel size: fine relief such as engraving, stitching and edge chips, and anything on large pieces. These are nominal voxel sizes; padding around the object makes the usable size somewhat larger.
- **The grid is only an upper bound:** as a rule of thumb, features need about 2 voxels to survive extraction, and the learned detail is usually coarser than the grid. Learned detail is measured in phase 2.
- **Gaps and contacts:** a finer grid shrinks the smallest gap that can stay open (about 2 voxels), if the model has learned to keep it. Parts that really touch still fuse at any grid size when one field or one voxel set describes the whole object (F-003).

**Confidence:** High for the arithmetic. Medium for what it means in practice.

## F-019 - Local generation competes for the one GPU that UzPainter's tests use

**Evidence:**
- UzPainter allows "Only one GPU run at a time on the machine" (`CLAUDE.md:69`), and the pipeline's own scheduling lives in the app, not in OS schedulers (`CLAUDE.md`, Commands).
- UzPainter pytest binaries (`UzPainter.exe`, `uzp-store-tests.exe`) were running while this was measured (`ps`).
- The 4090 also runs Blender bakes and Painter work.

**Impact:**
- A generation job that holds about 20 GB cannot overlap with a GPU test suite, a Painter session or a Blender GPU bake.
- The generation client has to follow the same one-GPU-run rule: check for a running `pytest tests/evaluator` or `union_run` first, and run in the background with a completion notice.
- Batches should be scheduled from inside the app, not with OS cron-style tools.

**Confidence:** High.
