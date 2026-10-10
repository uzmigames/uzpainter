# Origin of VMA

| Field | Value |
|---|---|
| Upstream | https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator |
| Release | `v3.2.1` |
| Tag commit | `c788c52156f3ef7bc7ab769cb03c110a53ac8fcb` |
| Archive | https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator/archive/refs/tags/v3.2.1.tar.gz |
| Archive SHA-256 | `5e7749504cb802427ffb7bec38a0b6a15db46ae253f00560acb3e624d9fe695c` |
| Archive root | `VulkanMemoryAllocator-3.2.1/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.2_vendor-thirdparty`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/README.md` (3.2.1); `scripts/setup.ps1` clones tag `v3.2.1` |
| Licence | MIT (`LICENSE.txt`) |
| Licence files | `LICENSE.txt` (verbatim) |
| Distribution role | shipped: compiled into `UzPainter.exe` |
| Selected features | Single header; the implementation is compiled where the render core defines `VMA_IMPLEMENTATION` (`engine/rhi/vulkan/vulkan_device.cpp`) |
| Include directories | `thirdparty/vma/include` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (2)

- `LICENSE.txt` (1,099 bytes)
- `include/vk_mem_alloc.h` (729,652 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/vma` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 24 |
| line-endings | 1 |
| different | 0 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 0 |

Line endings only (equal after CRLF -> LF; UzEngine's blob stores LF where the upstream file has CRLF (`core.autocrlf=true` normalised the text on commit)):

- `src/Shaders/CompileShaders.bat`

Identical files:

- `CHANGELOG.md`
- `CMakeLists.txt`
- `LICENSE.txt`
- `README.md`
- `bin/Shader.frag.spv`
- `bin/Shader.vert.spv`
- `include/vk_mem_alloc.h`
- `media/Thumbnail.png`
- `src/.editorconfig`
- `src/CMakeLists.txt`
- `src/Common.cpp`
- `src/Common.h`
- `src/Shaders/CMakeLists.txt`
- `src/Shaders/Shader.frag`
- `src/Shaders/Shader.vert`
- `src/Shaders/SparseBindingTest.comp`
- `src/SparseBindingTest.cpp`
- `src/SparseBindingTest.h`
- `src/Tests.cpp`
- `src/Tests.h`
- `src/VmaUsage.cpp`
- `src/VmaUsage.h`
- `src/VulkanSample.cpp`
- `src/vk_mem_alloc.natvis`

UzEngine patches: none under this library at the commit.
