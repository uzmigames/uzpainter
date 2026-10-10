# Origin of Agility SDK

| Field | Value |
|---|---|
| Upstream | https://www.nuget.org/packages/Microsoft.Direct3D.D3D12 |
| Release | `1.619.2` |
| Tag commit | none (NuGet package, not a git tag) |
| Archive | https://www.nuget.org/api/v2/package/Microsoft.Direct3D.D3D12/1.619.2 |
| Archive SHA-256 | `eb92d90bb23b2ec23410c41d791e41dbdbec942ab946924d1fdcb31eac6f0735` |
| Archive root | `(none)` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.2_vendor-thirdparty`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `scripts/setup.ps1` downloads package version `1.619.2` (`$agilityVersion`, set by UzEngine commit `94924089`, 2026-09-07); `runtime/thirdparty/README.md` still says 1.619.1. The package the tree actually fetches, 1.619.2, is taken; both export `D3D12_SDK_VERSION` 619, equal to DirectX-Headers v1.619.1 |
| Licence | Microsoft Software License Terms "MICROSOFT DIRECTX" (`LICENSE.txt`) for `build/native/bin/`; MIT (`LICENSE-CODE.txt`) for `build/native/include/` (scope stated in the package `README.md`) |
| Licence files | `LICENSE.txt`, `LICENSE-CODE.txt`, `distributable files.txt` (verbatim) |
| Distribution role | shipped: `D3D12Core.dll` in the distribution's `D3D12\` folder; `d3d12SDKLayers.dll` in debug packages only (`13-engine-integration.md` §5); headers build-only |
| Selected features | x64 runtime DLLs only (no arm64/win32, no PDBs, no `d3dconfig.exe` or state-object compiler); headers kept for `D3D12_SDK_VERSION` but shadowed by DirectX-Headers in the include order |
| Include directories | `thirdparty/agility/build/native/include` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: **release blocker** — RB-AGILITY-TERMS: redistribution of `D3D12Core.dll` is confirmed, but the distribution requirements (end-user terms protecting Microsoft, indemnification) are legal commitments only the owner can accept; the release packaging (`phase5.2_packaging`) must carry those terms before a release
- `distributable files.txt` lists `D3D12Core.dll`, `d3d12SDKLayers.dll` and `d3dconfig.exe` as distributable, so `LICENSE.txt` ("Distributables") permits redistributing the two vendored DLLs in object-code form.
- `LICENSE.txt` "Distribution Requirements" bind every distributor: add significant primary functionality; (i) require distributors and external end users to agree to terms that protect the DLLs and Microsoft at least as much as `LICENSE.txt`; (ii) indemnify Microsoft. It also forbids trademark use suggesting endorsement.
- UzEngine's README lists the package as "MIT"; only the headers are MIT.

## Selected files (36)

- `LICENSE-CODE.txt` (1,093 bytes)
- `LICENSE.txt` (13,147 bytes)
- `README.md` (16,598 bytes)
- `build/native/bin/x64/D3D12Core.dll` (5,019,680 bytes)
- `build/native/bin/x64/d3d12SDKLayers.dll` (4,962,336 bytes)
- `build/native/include/D3D12TokenizedProgramFormat.hpp` (133,012 bytes)
- `build/native/include/d3d12.h` (1,691,904 bytes)
- `build/native/include/d3d12.idl` (302,087 bytes)
- `build/native/include/d3d12compatibility.h` (25,465 bytes)
- `build/native/include/d3d12compatibility.idl` (4,926 bytes)
- `build/native/include/d3d12compiler.h` (35,452 bytes)
- `build/native/include/d3d12compiler.idl` (11,672 bytes)
- `build/native/include/d3d12markerapienums.idl` (7,618 bytes)
- `build/native/include/d3d12sdklayers.h` (182,842 bytes)
- `build/native/include/d3d12sdklayers.idl` (97,876 bytes)
- `build/native/include/d3d12shader.h` (28,043 bytes)
- `build/native/include/d3d12video.h` (459,032 bytes)
- `build/native/include/d3d12video.idl` (188,848 bytes)
- `build/native/include/d3dcommon.h` (51,955 bytes)
- `build/native/include/d3dcommon.idl` (47,674 bytes)
- `build/native/include/d3dshadercacheregistration.h` (34,810 bytes)
- `build/native/include/d3dshadercacheregistration.idl` (7,635 bytes)
- `build/native/include/d3dx12/d3dx12.h` (913 bytes)
- `build/native/include/d3dx12/d3dx12_barriers.h` (6,635 bytes)
- `build/native/include/d3dx12/d3dx12_check_feature_support.h` (47,466 bytes)
- `build/native/include/d3dx12/d3dx12_core.h` (79,380 bytes)
- `build/native/include/d3dx12/d3dx12_default.h` (325 bytes)
- `build/native/include/d3dx12/d3dx12_pipeline_state_stream.h` (97,735 bytes)
- `build/native/include/d3dx12/d3dx12_property_format_table.h` (11,564 bytes)
- `build/native/include/d3dx12/d3dx12_render_pass.h` (4,309 bytes)
- `build/native/include/d3dx12/d3dx12_resource_helpers.h` (26,354 bytes)
- `build/native/include/d3dx12/d3dx12_root_signature.h` (53,425 bytes)
- `build/native/include/d3dx12/d3dx12_state_object.h` (96,187 bytes)
- `build/native/include/dxgiformat.h` (8,022 bytes)
- `build/native/include/dxgiformat.idl` (7,909 bytes)
- `distributable files.txt` (93 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/agility` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 0 |
| line-endings | 0 |
| different | 0 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 36 |

UzEngine has no committed copy: `.gitignore` lists `/runtime/thirdparty/agility/` and `scripts/setup.ps1` downloads the package on each machine, so there is nothing at the commit to compare.

Selected files absent from UzEngine's tree at the commit:

- `LICENSE-CODE.txt`
- `LICENSE.txt`
- `README.md`
- `build/native/bin/x64/D3D12Core.dll`
- `build/native/bin/x64/d3d12SDKLayers.dll`
- `build/native/include/D3D12TokenizedProgramFormat.hpp`
- `build/native/include/d3d12.h`
- `build/native/include/d3d12.idl`
- `build/native/include/d3d12compatibility.h`
- `build/native/include/d3d12compatibility.idl`
- `build/native/include/d3d12compiler.h`
- `build/native/include/d3d12compiler.idl`
- `build/native/include/d3d12markerapienums.idl`
- `build/native/include/d3d12sdklayers.h`
- `build/native/include/d3d12sdklayers.idl`
- `build/native/include/d3d12shader.h`
- `build/native/include/d3d12video.h`
- `build/native/include/d3d12video.idl`
- `build/native/include/d3dcommon.h`
- `build/native/include/d3dcommon.idl`
- `build/native/include/d3dshadercacheregistration.h`
- `build/native/include/d3dshadercacheregistration.idl`
- `build/native/include/d3dx12/d3dx12.h`
- `build/native/include/d3dx12/d3dx12_barriers.h`
- `build/native/include/d3dx12/d3dx12_check_feature_support.h`
- `build/native/include/d3dx12/d3dx12_core.h`
- `build/native/include/d3dx12/d3dx12_default.h`
- `build/native/include/d3dx12/d3dx12_pipeline_state_stream.h`
- `build/native/include/d3dx12/d3dx12_property_format_table.h`
- `build/native/include/d3dx12/d3dx12_render_pass.h`
- `build/native/include/d3dx12/d3dx12_resource_helpers.h`
- `build/native/include/d3dx12/d3dx12_root_signature.h`
- `build/native/include/d3dx12/d3dx12_state_object.h`
- `build/native/include/dxgiformat.h`
- `build/native/include/dxgiformat.idl`
- `distributable files.txt`

UzEngine patches: none under this library at the commit.
