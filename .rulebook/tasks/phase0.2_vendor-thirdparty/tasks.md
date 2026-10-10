## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0_owner-decisions, phase0.1_vendor-core-copy (selected UzEngine commit recorded)

## 2. Implementation
- [ ] 2.1 Read `runtime/thirdparty/README.md` at the selected commit and record the exact version of each library of `13-engine-integration.md` §2.5
- [ ] 2.2 Fetch D3D12MA, DirectX-Headers and DirectXMath from their upstream releases into `thirdparty/<library>/` with licence files, `NOTICES.txt` (D3D12MA) and `ORIGIN.md`
- [ ] 2.3 Fetch the DirectX Shader Compiler release (`dxcapi.h`, `dxcompiler.dll`, `dxil.dll`, licence files) and the Agility SDK package (`D3D12Core.dll`, headers) with archive SHA-256 in `ORIGIN.md`
- [ ] 2.4 Fetch volk, Vulkan Memory Allocator, Vulkan-Headers and SPIRV-Reflect from their upstream releases with licence files and `ORIGIN.md`
- [ ] 2.5 Fetch spdlog (bundled fmt, compiled-library mode) and Tracy public headers only (no client linked) with licence files and `ORIGIN.md`
- [ ] 2.6 Byte-compare each upstream package with UzEngine's copy at the selected commit; record identical files, differing files and the cause of each difference in the library's `ORIGIN.md`
- [ ] 2.7 For each UzEngine patch under `thirdparty/<lib>/patches/`: apply it only if the build needs it, then log it as a local modification (id, files, reason, description, upstream behaviour cited, date, author, covering test)
- [ ] 2.8 Confirm licence, notices, package hash, selected features and distribution role per library against the pinned package; record the DXC `LICENSE-MS.txt` / `dxil.dll` redistribution result and the Agility SDK licence result as confirmed or as a named release blocker

## 3. Tests
- [ ] 3.1 Provenance check: every `thirdparty/<library>/` folder has a licence file and an `ORIGIN.md` whose archive SHA-256 matches a recomputation over the fetched package
- [ ] 3.2 Include check: every third-party include reached by the vendored subset's closure (`13-…` §2.2) resolves under `thirdparty/<library>/` or to a Windows SDK header, never to a UzEngine path
- [ ] 3.3 Comparison check: rerunning the byte comparison against UzEngine's copy at the selected commit reproduces the recorded result

## 4. Acceptance
- [ ] 4.1 Child acceptance (contributes to P0-VENDOR): all §2.5 libraries vendored from their own upstream with licence, notices and `ORIGIN.md`; differences and applied patches logged; inventory rows confirmed or carrying an explicit release-blocker status

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
