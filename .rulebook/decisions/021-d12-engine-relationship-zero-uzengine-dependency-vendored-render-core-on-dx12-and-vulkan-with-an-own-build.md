# 21. D12 Engine relationship: zero UzEngine dependency; vendored render core on DX12 and Vulkan with an own build

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Supersedes decision 014 (slim target on a pinned clean UzEngine commit, reviewed patch queue, mandatory upstream PRs). Owner answers of 2026-10-10: Q8 - zero dependency on UzEngine, the two are separate systems; Q9 - Windows 10/11 x64 with DX12 primary and Vulkan as the second backend (decision 022). UzEngine's working tree was mid-merge of 9220973 when analysed (docs/analysis/uzengine-renderer/10-review-response.md).

## Decision

UzPainter copies (vendors) from UzEngine only the rendering code it needs (RHI with the DX12 and Vulkan backends, shader pipeline, platform window and crash handling, .uztexture/.uzmat format definitions, small utilities) and is otherwise a separate system: no link against runtime.lib, no engine DLL, no pin to keep current, no patch queue, no upstream-PR obligation, no submodule. The copy comes from a clean committed UzEngine revision, never from files of the in-progress merge; Apache-2.0 headers are kept, local modifications are marked, and attribution is recorded in NOTICE and thirdparty/uzengine-render-core/ORIGIN.md. Known defects are fixed in the copy or their path is avoided (the glTF 32/48-byte stride defect is avoided because UzPainter never reads .uzmesh; the DXR check is extended to Tier 1.1/SM6.5). UzPainter keeps its own build: Zig-first stays unless the vendored subset dictates otherwise; CPython is embedded through the C API, qualified in Phase 0 by selftest, with a C-ABI DLL fallback. DX12 is the primary backend and Vulkan the second backend on Windows; UzPainter adds Vulkan ray tracing. One-folder distribution is verified on a clean offline machine. UzEngine may consume UzPainter as a submodule in the future; not now. See docs/architecture/13-engine-integration.md.

## Alternatives Considered

- Pinned clean UzEngine commit with a slim engine target, reviewed patch queue and mandatory upstream PRs (decision 014) - rejected by the owner (Q8)
- Linking UzEngine as a library or through a C-ABI DLL - rejected: zero dependency
- CMake/MSVC-first build - rejected in round 3: the MSVC CMake branch lacks essential sources
- Copying from the in-progress merge working tree - rejected

## Consequences

UzPainter owns maintenance of the vendored code and UzEngine changes never block it. Phase 0 vendors the render core and passes the hardware selftest; Phase 3 qualifies Vulkan ray tracing against DXR. Third-party libraries the vendored code needs are vendored from their own upstreams under their own licences.
