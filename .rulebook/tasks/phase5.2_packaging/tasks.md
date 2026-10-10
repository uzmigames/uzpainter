## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase4.6_gate-g4, phase5.1_performance-budgets; sanitisation items §2 of phase5.5_clean-history (paraphrase, release-tree scan) done (item-level); frozen release build hash recorded

## 2. Implementation
- [ ] 2.1 Release packaging step that assembles the one-folder distribution of 13 §5 from the frozen build (`UzPainter.exe`, `D3D12\D3D12Core.dll`, `dxcompiler.dll`, `dxil.dll`, CPython 3.13 embeddable files with `Lib\site-packages\`, `embree4.dll`, measured Visual C++ runtime DLLs, `assets\`, `capabilities.json`, `LICENSE`, `NOTICE`, `LICENSES\`)
- [ ] 2.2 Writable state redirected to the user's local app-data folder (shader cache, logs, supervisor ledger); install folder left read-only
- [ ] 2.3 DLL closure from the import tables of every shipped binary, compared with an allowlist; DLL count and footprint recorded
- [ ] 2.4 Dependency lock for the release closure with licence, notices, package hash, selected features and distribution role per dependency; Agility SDK, `dxil.dll`, Visual C++ runtime files and every MCP wheel confirmed, no "not confirmed" entry left
- [ ] 2.5 `NOTICE` and `LICENSES\` assembled from the lock, including the UzEngine attribution (copyright line, selected commit) and every third-party notice; vendoring records complete
- [ ] 2.6 Provenance record beside every shipped preset and asset, validated against its schema
- [ ] 2.7 Release content scan: Adobe file signatures and Adobe-derived content (LIC-03), hashes from the private store index, files outside the allowlist
- [ ] 2.8 Verification record `parity/reports/phase5/package-verification.json` with build hash, dependency lock hash, DLL closure and clean-machine results

## 3. Tests
- [ ] 3.1 Clean-machine run on an offline Windows 10/11 x64 machine without Python, Painter, Blender, the Vulkan SDK or the Windows SDK: `UzPainter.exe selftest` hardware slice green on DX12, an MCP session starts with `--mcp`, and a wand v1 export through `UzPainter.exe run` matches the frozen build's export bytes
- [ ] 3.2 Vulkan loader absent or too old on the clean machine: the Vulkan backend reports unavailable and DX12 operation is unaffected
- [ ] 3.3 Vendoring check green on the release tree; DLL closure equals the allowlist; no file outside the allowlist in the release folder
- [ ] 3.4 Release scan finds no Adobe content and no oracle blob; every shipped preset and asset has a valid provenance record
- [ ] 3.5 Build identity: the verification record's build hash and lock equal those of `phase5.4_parity-report`

## 4. Acceptance
- [ ] 4.1 Release folder runs offline without SDKs on a clean Windows 10/11 x64 machine; same build hash and lock as `phase5.4_parity-report`; inventory has no "not confirmed" entry; verification attached to `phase5.6_gate-g5`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
