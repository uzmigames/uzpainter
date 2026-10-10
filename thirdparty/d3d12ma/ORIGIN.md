# Origin of D3D12MA

| Field | Value |
|---|---|
| Upstream | https://github.com/GPUOpen-LibrariesAndSDKs/D3D12MemoryAllocator |
| Release | `v3.1.0` |
| Tag commit | `0fa62ed3a0a69b73230a8ec1faa752d4061c8dc8` |
| Archive | https://github.com/GPUOpen-LibrariesAndSDKs/D3D12MemoryAllocator/archive/refs/tags/v3.1.0.tar.gz |
| Archive SHA-256 | `629aa00919f2f0f8cdfcdc485db5077f456e939e418cee148e17458efa055f63` |
| Archive root | `D3D12MemoryAllocator-3.1.0/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.2_vendor-thirdparty`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/README.md` (3.1.0); `scripts/setup.ps1` clones tag `v3.1.0` |
| Licence | MIT (`LICENSE.txt`); `NOTICES.txt` adds the MIT notices of AMD, Microsoft (DirectX-Graphics-Samples code) and VulkanMemoryAllocator |
| Licence files | `LICENSE.txt`, `NOTICES.txt` (verbatim) |
| Distribution role | shipped: compiled into `UzPainter.exe` |
| Selected features | `src/D3D12MemAlloc.cpp` compiled as a source included by the render core's `engine/rhi/dx12/dx12_d3d12ma.cpp`; no samples, tests or natvis |
| Include directories | `thirdparty/d3d12ma/include`, `thirdparty/d3d12ma/src` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)
- Binary distributions reproduce `LICENSE.txt` and `NOTICES.txt`.

## Selected files (4)

- `LICENSE.txt` (1,099 bytes)
- `NOTICES.txt` (2,839 bytes)
- `include/D3D12MemAlloc.h` (171,914 bytes)
- `src/D3D12MemAlloc.cpp` (349,023 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/d3d12ma` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 5 |
| line-endings | 17 |
| different | 0 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 0 |

Line endings only (equal after CRLF -> LF; UzEngine's blob stores LF where the upstream file has CRLF (`core.autocrlf=true` normalised the text on commit)):

- `CHANGELOG.md`
- `NOTICES.txt`
- `include/D3D12MemAlloc.h`
- `src/.editorconfig`
- `src/CMakeLists.txt`
- `src/Common.cpp`
- `src/Common.h`
- `src/D3D12MemAlloc.cpp`
- `src/D3D12MemAlloc.natvis`
- `src/D3D12Sample.cpp`
- `src/Shaders/FxBatchCompilerScript.fxbc`
- `src/Shaders/PS.hlsl`
- `src/Shaders/PS_Compiled.h`
- `src/Shaders/VS.hlsl`
- `src/Shaders/VS_Compiled.h`
- `src/Tests.cpp`
- `src/Tests.h`

Identical files:

- `CMakeLists.txt`
- `LICENSE.txt`
- `README.md`
- `src/Doxyfile`
- `src/cmake/config.cmake.in`

UzEngine patches: none under this library at the commit.
