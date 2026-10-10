# 22. Q9 Platform and CI: Windows 10/11 x64 with DX12 and Vulkan; the owner's machine as the self-hosted GPU runner

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Owner question Q9 asked for the deployment matrix (minimum Windows/CPU/GPU, mandatory software-render path, one folder or single file) and for GPU CI runner availability. Owner answers of 2026-10-10 (Q9 platform, Q9b CI). Astra's docs-set review F22: CPU-first baking does not mean universal machine support.

## Decision

UzPainter targets Windows 10/11 x64 only for now; no Linux or macOS. DX12 is the primary GPU backend and Vulkan the second backend on Windows. A GPU is required for compositing, preview and path tracing. CPU baking needs no GPU and runs on the Windows/CPU/ISA configurations qualified for the pinned Embree build, with an explicit capability error elsewhere; cross-machine repeatability is measured separately. Distribution is one folder. WARP is probed and reported, never mandatory. CI: the owner's machine (GPU plus a licensed Painter) is the self-hosted GPU runner and holds the private oracle store; hosted runners run the CPU-only lanes without oracle blobs. See docs/architecture/13-engine-integration.md §5 and docs/architecture/14-parity-testing.md §6-7.

## Alternatives Considered

- Linux or macOS support now - rejected by the owner
- DX12 as the only backend - rejected: Vulkan is the second backend on Windows
- Single-file distribution - rejected: one folder
- Mandatory software-render (WARP) path - not required

## Consequences

Tier 0-3 comparisons run only where the GPU and the private store are available; a missing oracle blob fails as oracle_unavailable, never passes. GPU CI capacity depends on the owner's machine.
