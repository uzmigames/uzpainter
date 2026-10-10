# Origin of DirectX-Headers

| Field | Value |
|---|---|
| Upstream | https://github.com/microsoft/DirectX-Headers |
| Release | `v1.619.1` |
| Tag commit | `9e393d6d8a3b30dcc6f2806ef604ec16a27b0d7e` |
| Archive | https://github.com/microsoft/DirectX-Headers/archive/refs/tags/v1.619.1.tar.gz |
| Archive SHA-256 | `6193774904c940eebb9b0c51b816b93dd776cfeb25a951f0f4a58f22387e5008` |
| Archive root | `DirectX-Headers-1.619.1/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.2_vendor-thirdparty`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/README.md` (1.619.1); `scripts/setup.ps1` clones tag `v1.619.1` |
| Licence | MIT (`LICENSE`) |
| Licence files | `LICENSE` (verbatim) |
| Distribution role | build-only: headers, nothing of it is compiled on its own or shipped |
| Selected features | `include/directx` only; ahead of the Agility headers in the include order, so `d3d12.h`, `d3d12sdklayers.h` and `d3dx12.h` resolve here; `src/d3dx12_property_format_table.cpp` is not compiled (UzEngine does not compile it either) |
| Include directories | `thirdparty/directx-headers/include`, `thirdparty/directx-headers/include/directx` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (36)

- `LICENSE` (1,093 bytes)
- `include/directx/D3D12MarkerApiEnums.idl` (7,499 bytes)
- `include/directx/D3D12TokenizedProgramFormat.hpp` (130,378 bytes)
- `include/directx/DirectML.h` (79,871 bytes)
- `include/directx/d3d12.h` (1,691,904 bytes)
- `include/directx/d3d12.idl` (302,087 bytes)
- `include/directx/d3d12compatibility.h` (25,465 bytes)
- `include/directx/d3d12compatibility.idl` (4,926 bytes)
- `include/directx/d3d12compiler.h` (34,475 bytes)
- `include/directx/d3d12compiler.idl` (11,382 bytes)
- `include/directx/d3d12sdklayers.h` (182,783 bytes)
- `include/directx/d3d12sdklayers.idl` (97,821 bytes)
- `include/directx/d3d12shader.h` (28,043 bytes)
- `include/directx/d3d12video.h` (459,032 bytes)
- `include/directx/d3d12video.idl` (188,848 bytes)
- `include/directx/d3dcommon.h` (51,955 bytes)
- `include/directx/d3dcommon.idl` (47,674 bytes)
- `include/directx/d3dshadercacheregistration.h` (33,812 bytes)
- `include/directx/d3dshadercacheregistration.idl` (7,441 bytes)
- `include/directx/d3dx12.h` (913 bytes)
- `include/directx/d3dx12_barriers.h` (6,443 bytes)
- `include/directx/d3dx12_check_feature_support.h` (46,273 bytes)
- `include/directx/d3dx12_core.h` (77,309 bytes)
- `include/directx/d3dx12_default.h` (313 bytes)
- `include/directx/d3dx12_pipeline_state_stream.h` (96,018 bytes)
- `include/directx/d3dx12_property_format_table.h` (11,437 bytes)
- `include/directx/d3dx12_render_pass.h` (4,204 bytes)
- `include/directx/d3dx12_resource_helpers.h` (25,743 bytes)
- `include/directx/d3dx12_root_signature.h` (52,198 bytes)
- `include/directx/d3dx12_state_object.h` (93,614 bytes)
- `include/directx/dxcore.h` (1,133 bytes)
- `include/directx/dxcore_interface.h` (14,941 bytes)
- `include/directx/dxgicommon.h` (2,262 bytes)
- `include/directx/dxgicommon.idl` (2,199 bytes)
- `include/directx/dxgiformat.h` (8,022 bytes)
- `include/directx/dxgiformat.idl` (7,909 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/directx_headers` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 32 |
| line-endings | 29 |
| different | 0 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 0 |

Line endings only (equal after CRLF -> LF; UzEngine's blob stores LF where the upstream file has CRLF (`core.autocrlf=true` normalised the text on commit)):

- `CMakeLists.txt`
- `CMakePresets.json`
- `LICENSE`
- `README.md`
- `cmake/directx-headers-config.cmake.in`
- `include/directx/DirectML.h`
- `include/directx/d3d12.h`
- `include/directx/d3d12.idl`
- `include/directx/d3d12compatibility.h`
- `include/directx/d3d12compatibility.idl`
- `include/directx/d3d12sdklayers.h`
- `include/directx/d3d12sdklayers.idl`
- `include/directx/d3d12shader.h`
- `include/directx/d3d12video.h`
- `include/directx/d3d12video.idl`
- `include/directx/d3dcommon.h`
- `include/directx/d3dcommon.idl`
- `include/directx/d3dx12.h`
- `include/directx/dxcore.h`
- `include/directx/dxcore_interface.h`
- `include/directx/dxgicommon.h`
- `include/directx/dxgicommon.idl`
- `include/directx/dxgiformat.h`
- `include/directx/dxgiformat.idl`
- `include/wsl/stubs/basetsd.h`
- `include/wsl/stubs/unknwn.h`
- `include/wsl/stubs/unknwnbase.h`
- `meson.build`
- `meson_options.txt`

Identical files:

- `Android.bp`
- `cmake/DirectX-Headers.pc.in`
- `cmake/JoinPaths.cmake`
- `include/composition/dcomp-preview.h`
- `include/directx/D3D12MarkerApiEnums.idl`
- `include/directx/D3D12TokenizedProgramFormat.hpp`
- `include/directx/d3d12compiler.h`
- `include/directx/d3d12compiler.idl`
- `include/directx/d3dshadercacheregistration.h`
- `include/directx/d3dshadercacheregistration.idl`
- `include/directx/d3dx12_barriers.h`
- `include/directx/d3dx12_check_feature_support.h`
- `include/directx/d3dx12_core.h`
- `include/directx/d3dx12_default.h`
- `include/directx/d3dx12_pipeline_state_stream.h`
- `include/directx/d3dx12_property_format_table.h`
- `include/directx/d3dx12_render_pass.h`
- `include/directx/d3dx12_resource_helpers.h`
- `include/directx/d3dx12_root_signature.h`
- `include/directx/d3dx12_state_object.h`
- `include/dxguids/dxguids.h`
- `include/wsl/stubs/oaidl.h`
- `include/wsl/stubs/ocidl.h`
- `include/wsl/stubs/rpc.h`
- `include/wsl/stubs/rpcndr.h`
- `include/wsl/stubs/winapifamily.h`
- `include/wsl/stubs/wrl/client.h`
- `include/wsl/stubs/wrl/implements.h`
- `include/wsl/winadapter.h`
- `include/wsl/wrladapter.h`
- `src/d3dx12_property_format_table.cpp`
- `src/dxguids.cpp`

UzEngine patches: none under this library at the commit.
