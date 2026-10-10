# 14. D12 Engine integration: Zig-first slim target on a clean pinned UzEngine commit with a reviewed patch queue

**Status**: superseded
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

UzEngine's CMake MSVC branch omits the renderer and job sources; the working tree is mid-merge of 9220973 (started 2026-10-10 00:05), so a clean pin must follow that merge (05-resolution.md D12, uzengine-renderer/10-review-response.md).

## Decision

UzPainter has its own build.zig consuming a pinned engine commit (first clean commit after the merge lands, build and tests green, hashes recorded) with a slim target (RHI, shader pipeline, jobs, formats, codecs, mikktspace, platform; no FFmpeg/DLSS/Lua); CPython embedded through the C API from the same toolchain, qualified in Phase 0 by selftest with a documented C-ABI DLL fallback; fork with a reviewed patch series and mandatory upstream PRs; one-folder distribution verified on a clean offline machine. See docs/architecture/13-engine-integration.md.

## Alternatives Considered

- CMake/MSVC-first (Astra round 1; Claude round 2) - rejected: the MSVC CMake branch lacks essential sources
- Engine DLL through the C ABI only - kept as fallback
- Pin 19ffb9b from the dirty tree - rejected

## Consequences

Phase 0 toolchain slice decides the CPython boundary; engine changes are small and upstreamed.
