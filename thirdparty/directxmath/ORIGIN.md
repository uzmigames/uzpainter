# Origin of DirectXMath

| Field | Value |
|---|---|
| Upstream | https://github.com/microsoft/DirectXMath |
| Release | `apr2025` |
| Tag commit | `56206b1916646b29b37e1eac56e96e2008d6c71f` |
| Archive | https://github.com/microsoft/DirectXMath/archive/refs/tags/apr2025.tar.gz |
| Archive SHA-256 | `8ac7f060d7fcc971d77c5a9f3ff98548ecf119c144a7c2dd9d21f4b66ba94cd4` |
| Archive root | `DirectXMath-apr2025/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.2_vendor-thirdparty`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/README.md` (apr2025); `scripts/setup.ps1` clones tag `apr2025` |
| Licence | MIT (`LICENSE`) |
| Licence files | `LICENSE` (verbatim) |
| Distribution role | build-only: headers, nothing of it is compiled on its own or shipped |
| Selected features | The `Inc/` headers and inline files; no extensions, tests or samples |
| Include directories | `thirdparty/directxmath/Inc` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (11)

- `Inc/DirectXCollision.h` (18,114 bytes)
- `Inc/DirectXCollision.inl` (200,097 bytes)
- `Inc/DirectXColors.h` (28,687 bytes)
- `Inc/DirectXMath.h` (128,770 bytes)
- `Inc/DirectXMathConvert.inl` (81,932 bytes)
- `Inc/DirectXMathMatrix.inl` (122,191 bytes)
- `Inc/DirectXMathMisc.inl` (82,204 bytes)
- `Inc/DirectXMathVector.inl` (549,530 bytes)
- `Inc/DirectXPackedVector.h` (51,043 bytes)
- `Inc/DirectXPackedVector.inl` (167,443 bytes)
- `LICENSE` (1,141 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/directxmath` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 18 |
| line-endings | 12 |
| different | 0 |
| uzengine-only | 1 |
| selected but absent from UzEngine's tree | 0 |

Differences and their causes:

- `Inc/sal.h` (uzengine-only): not part of DirectXMath: UzEngine's `scripts/setup.ps1` downloads it from `dotnet/runtime` branch `main` (unpinned) as a SAL stub for non-MSVC platforms. Not vendored: on Windows `#include "sal.h"` (`Inc/DirectXMath.h`) resolves to the toolchain's own `sal.h` (Windows SDK, and Zig 0.15.2's mingw-w64 headers `libc/include/any-windows-any/sal.h`)

Line endings only (equal after CRLF -> LF; UzEngine's blob stores LF where the upstream file has CRLF (`core.autocrlf=true` normalised the text on commit)):

- `Inc/DirectXCollision.h`
- `Inc/DirectXCollision.inl`
- `Inc/DirectXColors.h`
- `Inc/DirectXMath.h`
- `Inc/DirectXMathConvert.inl`
- `Inc/DirectXMathMatrix.inl`
- `Inc/DirectXMathMisc.inl`
- `Inc/DirectXMathVector.inl`
- `Inc/DirectXPackedVector.h`
- `Inc/DirectXPackedVector.inl`
- `Stereo3D/Stereo3DMatrixHelper.cpp`
- `Stereo3D/Stereo3DMatrixHelper.h`

Identical files:

- `.azuredevops/pipelines/DirectXMath-GitHub-CMake-Dev17.yml`
- `.azuredevops/pipelines/DirectXMath-GitHub-CMake.yml`
- `.azuredevops/pipelines/DirectXMath-GitHub-Dev17.yml`
- `.azuredevops/pipelines/DirectXMath-GitHub-MinGW.yml`
- `.azuredevops/pipelines/DirectXMath-GitHub-WSL-11.yml`
- `.azuredevops/pipelines/DirectXMath-GitHub-WSL-13.yml`
- `.azuredevops/pipelines/DirectXMath-GitHub.yml`
- `.azuredevops/pipelines/DirectXMath-SDL.yml`
- `.azuredevops/policies/approvercountpolicy.yml`
- `.nuget/directxmath.nuspec`
- `.nuget/directxmath.targets`
- `.nuget/icon.jpg`
- `.nuget/signconfig.xml`
- `CHANGELOG.md`
- `CMakeLists.txt`
- `CMakePresets.json`
- `LICENSE`
- `README.md`

UzEngine patches: none under this library at the commit.
