# Proposal: phase0.1_vendor-core-copy

## Why
Owner Q8 (decision 021, superseding decision 014) gives UzPainter zero dependency on UzEngine: the rendering code it needs is copied once from a clean UzEngine commit and then evolves independently, with no `runtime.lib`, DLL, submodule, pin, patch queue or upstream obligation (PRD OWN-02, ARC-07; `docs/architecture/13-engine-integration.md` §1). The checkout of 2026-10-10 carries uncommitted edits on top of a recently completed merge, so a copy from a working tree would have no reproducible origin. The copy must come from a commit object that passes explicit checks, keep UzEngine's Apache-2.0 licence and attribution (LIC-02), and record a per-file manifest so that every later change is detectable. Child of `phase0.5_vendor-render-core` (implements D12).

## What Changes
- Commit selection (`13-…` §3.1): candidate commits on UzEngine's `main` identified by full hash; files exported from the commit object (`git archive <hash>` into a staging folder outside both repositories), never from a working tree. Checks per candidate: (a) no conflict markers in any manifest file; (b) the include closure computed from the exported tree equals the manifest, with no unresolved include outside the listed third-party and Windows SDK headers; (d) every behaviour cited in `13-…` §2.3 and §3.4 re-verified at that commit with its line numbers. Check (c) (UzPainter's build of the subset and the hardware `selftest`) is confirmed by `phase0.3_vendor-modifications` and `phase0.6_toolchain-hardware-slice` and recorded in `ORIGIN.md` when they pass. The newest passing commit on `main` is selected; UzEngine's own build/test status at that commit is recorded as information only.
- `thirdparty/uzengine-render-core/` with upstream relative paths kept (`13-…` §3.2): the subset of §2.1 — RHI interface (`engine/rhi/*.h`, `rhi_config.cpp`, `rhi_factory.cpp`), DX12 backend (`engine/rhi/dx12/*`), Vulkan backend (`engine/rhi/vulkan/*`), shader compiler/reflection/cache (`engine/shader/`), `engine/asset/formats/uztexture_format.h` (header only), `engine/math/*`, logging, assertions, profiling, paths, `platform/platform_types.h` and the Windows platform files (crash handler, stack walker, file system, window, input) — about 97 files and 28,100 lines on 2026-10-10, recomputed at the selected commit.
- Files excluded by `13-…` §2.4 are not copied: `engine/config/**`, `engine/core/cvar.*`, `engine/rhi/dx11`, `engine/rhi/metal`, `engine/rhi/optimization`, `renderer/**`, `asset/importers/**`, `asset/formats/uzmesh_format.*`, `asset/formats/uztexture_format.cpp`, the shader front end beyond the compiler, and everything else listed there (the glTF 32/48-byte stride defect path is avoided by not vendoring it).
- `LICENSE` (UzEngine's Apache-2.0 licence at the selected commit, "Copyright 2026 Uzmi Games"), `ORIGIN.md` (repository, commit hash and date, selection evidence for checks a–d, import date, importer, re-verified line numbers), `MANIFEST.json` (per file `{upstream_path, vendored_path, upstream_commit, upstream_blob_sha1, upstream_sha256, vendored_sha256, status, modifications}`; every file `verbatim` at import).
- UzPainter root `NOTICE` entry naming the vendored UzEngine code, its copyright line and the selected commit; a re-check for an upstream `NOTICE` at the selected commit (repository root, `runtime/`, `runtime/engine`, `runtime/platform`), reproducing its attribution notices if one exists; per-file licence headers kept verbatim if the commit adds any.

## Dependencies
- Prerequisites: `phase0_owner-decisions` (P0-OWNER, decision 021, archived).
- Parent: `phase0.5_vendor-render-core` (P0-VENDOR) closes only when this child passes.
- Successors: `phase0.2_vendor-thirdparty` (library versions at the selected commit), `phase0.3_vendor-modifications` (modifies the copied files), `phase0.4_vendor-check` (checks the manifest written here).

## Acceptance
A commit object on UzEngine's `main` selected by checks (a), (b) and (d) with evidence in `ORIGIN.md`; the §2.1 subset exported from that commit into `thirdparty/uzengine-render-core/` with upstream paths; every verbatim file byte-equal to upstream (`vendored_sha256 = upstream_sha256`, blob SHA-1 equal to the commit's tree entry); no denylisted path copied; `LICENSE`, `ORIGIN.md`, `MANIFEST.json` and the root `NOTICE` entry written. Contributes to the P0-VENDOR gate (copied, not linked; no submodule, no engine path, no pin or patch queue — `docs/dag.md`).

## Impact
- Affected specs: render-core
- Affected code: `thirdparty/uzengine-render-core/` (new), root `NOTICE`
- Breaking change: NO
- User benefit: a reproducible, attributed copy of the render core that builds without UzEngine and whose every later change is detectable
