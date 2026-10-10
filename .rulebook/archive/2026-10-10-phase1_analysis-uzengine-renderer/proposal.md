# Proposal: phase1_analysis-uzengine-renderer

## Why
UzPainter must be built on the UzEngine renderer (E:\UzmiGames\UzEngine, C++23, DX12 SM6.6 primary with DX11/Vulkan fallbacks). Before any architecture decision can be made, the engine has to be analyzed deeply enough to know what can be reused as-is (headless rendering, RHI compute/readback, material/texture standard, mesh importers, image IO, build pipeline, MCP/IPC patterns), what must be extended, and what is missing for a texturing tool (UV-space rasterization, baking, compositing, dilation, export compression). Without this evidence-based inventory the architect would be guessing.

## What Changes
Nine read-only analysis documents under `docs/analysis/uzengine-renderer/`, each one theme, every factual claim tagged Fact / Hypothesis / Recommendation and cited with a UzEngine file path:

1. `01-module-map.md` — engine modules, dependencies, what links into a standalone tool.
2. `02-headless-rendering.md` — engine mode / offscreen render / CPU readback path today.
3. `03-rhi-capabilities-for-texturing.md` — compute, UAV, formats, readback, bindless, mips, DXR, backend parity.
4. `04-material-and-texture-standard.md` — the exact UzEngine texture/material standard (UzPainter export preset).
5. `05-mesh-import.md` — uzfbx / uzgltf / uzmesh / uzcook, mesh representation, tangents, limits.
6. `06-thirdparty-and-image-io.md` — every thirdparty library and its reuse potential.
7. `07-build-and-packaging.md` — Zig vs CMake, standalone exe tools, shader embedding, scripting, distributable footprint.
8. `08-mcp-and-ipc-patterns.md` — how the MCP server talks to the engine, reusable conventions.
9. `09-gaps-and-risks.md` — what the renderer lacks for texturing, difficulty and natural insertion point.

No UzEngine file is modified, built or executed.

## Impact
- Affected specs: none (analysis only)
- Affected code: none; documents only under `docs/analysis/uzengine-renderer/`
- Breaking change: NO
- User benefit: an architect can decide reuse / extend / build-new for UzPainter with file-level evidence instead of assumptions.
