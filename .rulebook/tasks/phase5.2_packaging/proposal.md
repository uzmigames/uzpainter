# Proposal: phase5.2_packaging

## Why
P5-PACKAGE in `docs/dag.md`, implementing D12 as specified in `docs/architecture/13-engine-integration.md` §5 (platform and one-folder distribution) and the licence obligations of `docs/licensing-and-clean-room.md` §3, §5 and §6 (decisions 002, 021 and 022, owner Q8 and Q9). UzPainter must ship as a standalone one-folder distribution for Windows 10/11 x64 that runs on a clean offline machine without Python, Painter, Blender or SDKs (OWN-08, NFR-01, NFR-07), under Apache-2.0 with every third-party licence confirmed and listed (LIC-01, LIC-02) and no Adobe content (LIC-03). Release criterion 7 of `docs/prd.md` §18 and the `docs/dag.md` gate rule require the package verification and the final parity report to use the same immutable build hash and dependency lock.

## What Changes
- Release folder built from the frozen build with the files of 13 §5: `UzPainter.exe` (vendored render core and libc++ linked statically), `D3D12\D3D12Core.dll` (Agility SDK, pinned; `d3d12SDKLayers.dll` only in debug packages), `dxcompiler.dll` and `dxil.dll`, the CPython 3.13 embeddable files (`python313.dll`, `python313.zip`, `vcruntime140.dll`, `vcruntime140_1.dll`) with `Lib\site-packages\` holding the pinned wheels and the MCP SDK closure, `embree4.dll` (and `tbb12.dll` unless internal tasking), Visual C++ runtime DLLs only as measured, `assets\`, `capabilities.json`, `LICENSE`, `NOTICE` and `LICENSES\`. Never shipped: system DLLs, `vulkan-1.dll` (system loader used), FXC, Slang, `lua51.dll`, FFmpeg, DLSS, FidelityFX, the LunarG Vulkan SDK.
- Read-only install folder: shader cache, logs and the supervisor ledger written under the user's local app-data folder.
- DLL closure computed from the import tables of every shipped binary and compared with an allowlist; DLL count and footprint measured and recorded.
- Dependency lock for the release closure: licence, notices, source/package hash, selected features and distribution role of every direct and transitive dependency (licensing §3), with no "not confirmed" entry left (including the Agility SDK package text, `dxil.dll` redistribution, the exact Visual C++ runtime files and every MCP wheel).
- `NOTICE` and `LICENSES\` complete: UzEngine attribution with its copyright line and selected commit, every third-party notice of the closure (D3D12MA `NOTICES.txt`, CPython's complete notices, and the rest); UzEngine vendoring records (`ORIGIN.md`, `MANIFEST.json`, `MODIFICATIONS.md`) complete and the vendoring check green.
- Provenance record `<name>.provenance.json` beside every shipped preset and asset (licensing §6); the release folder scanned for Adobe-derived content (LIC-03) and for private oracle blobs (licensing §5.4).
- Clean-machine verification on a clean, offline Windows 10/11 x64 machine without Python, Painter, Blender, the Vulkan SDK or the Windows SDK; verification record `parity/reports/phase5/package-verification.json` naming the build hash and dependency lock.

## Dependencies
- Prerequisites (DAG inputs of P5-PACKAGE): `phase4.6_gate-g4`, `phase5.1_performance-budgets` (the release build is frozen after its budgets).
- Item-level prerequisite: the sanitisation items of `phase5.5_clean-history` (paraphrase, release-tree scan) are done before the release build is frozen; the rest of `phase5.5_clean-history` follows this task.
- Same frozen build as `phase5.4_parity-report`; followed by `phase5.5_clean-history`; joined by `phase5.6_gate-g5`.
- Builds on `phase0.5_vendor-render-core` (vendoring records and check) and `phase0.8_toolchain-slice` (`selftest`, link map and DLL closure).

## Acceptance
- The release folder runs offline without SDKs on a clean Windows 10/11 x64 machine.
- The package verification names the same build hash and dependency lock as `phase5.4_parity-report`.
- Inventory complete with no "not confirmed" entry; `LICENSE`, `NOTICE` (with the UzEngine attribution) and `LICENSES\` complete; no Adobe content and no oracle blob in the release.

## Impact
- Affected specs: `packaging` (release folder, licence closure, clean-machine verification)
- Affected code: release packaging step in `build.zig`, DLL-closure and allowlist check, dependency-lock generator, `NOTICE`/`LICENSES\` assembly, release content scan, clean-machine verification job
- Breaking change: NO
- User benefit: anyone can unzip one folder on a Windows 10/11 x64 machine and run UzPainter offline, with complete licence notices
