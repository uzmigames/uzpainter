# Origin of fastgltf

| Field | Value |
|---|---|
| Upstream | https://github.com/spnda/fastgltf |
| Release | `v0.9.1` |
| Tag commit | `705564d4d54500ae88befb0db9e361e447923655` |
| Archive | https://github.com/spnda/fastgltf/archive/refs/tags/v0.9.1.tar.gz |
| Archive SHA-256 | `d8705a496deb2831775baeef5009be36d24bf3d10f8d29ab016e977d0119c872` |
| Archive root | `fastgltf-0.9.1/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase1.4_mesh-importers`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: UzPainter's selection: the newest fastgltf release on the retrieval date (tag `v0.9.1`, published 2026-09-27), for the glTF/GLB importer of `docs/architecture/12-mesh-import.md` §2; its JSON parser is `thirdparty/simdjson/` |
| Licence | MIT (`LICENSE.md`, Copyright (c) 2022 - 2026 Sean Apeler; every selected header and source carries the same notice) |
| Licence files | `LICENSE.md` (verbatim) |
| Distribution role | build-only today: compiled into `uzp_mesh.lib` (UzPainter's mesh importers, `src/mesh/`) and its native tests `uzp-mesh-tests.exe` (`phase1.4_mesh-importers`); shipped once `UzPainter.exe` links the importers |
| Selected features | The three library units `src/base64.cpp`, `src/fastgltf.cpp` and `src/io.cpp` compiled as C++ against `thirdparty/simdjson/` (`src/fastgltf.cpp` with `-mcrc32`, which its `sse4.2` CRC-32C target region needs under Zig 0.15.2's clang; the function is chosen at run time only on CPUs with SSE4.2) with the CMake option defaults (`FASTGLTF_USE_CUSTOM_SMALLVECTOR`, `FASTGLTF_DISABLE_CUSTOM_MEMORY_POOL`, `FASTGLTF_USE_64BIT_FLOAT`, `FASTGLTF_ENABLE_KHR_IMPLICIT_SHAPES` and `FASTGLTF_ENABLE_KHR_PHYSICS_RIGID_BODIES` all off); the headers `include/fastgltf/` (the DirectXMath and glm element-trait headers are vendored with them but no compiled unit includes them); no C++ module interface `src/fastgltf.ixx`, CMake files, downloaded `deps/`, tests, examples or documentation |
| Include directories | `thirdparty/fastgltf/include` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (12)

- `LICENSE.md` (1,101 bytes)
- `include/fastgltf/base64.hpp` (4,426 bytes)
- `include/fastgltf/core.hpp` (46,502 bytes)
- `include/fastgltf/dxmath_element_traits.hpp` (4,005 bytes)
- `include/fastgltf/glm_element_traits.hpp` (4,006 bytes)
- `include/fastgltf/math.hpp` (33,836 bytes)
- `include/fastgltf/tools.hpp` (39,580 bytes)
- `include/fastgltf/types.hpp` (87,580 bytes)
- `include/fastgltf/util.hpp` (19,028 bytes)
- `src/base64.cpp` (17,866 bytes)
- `src/fastgltf.cpp` (260,908 bytes)
- `src/io.cpp` (13,637 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/fastgltf` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 0 |
| line-endings | 0 |
| different | 0 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 12 |

UzEngine's tree records `runtime/thirdparty/fastgltf` only as a submodule link (gitlink to fastgltf commit `d4734a7e55d8d25155e755d895e018e423845cd0`, committed upstream 2024-07-25) with no `.gitmodules` and no files at the commit, so there is nothing to compare.

Selected files absent from UzEngine's tree at the commit:

- `LICENSE.md`
- `include/fastgltf/base64.hpp`
- `include/fastgltf/core.hpp`
- `include/fastgltf/dxmath_element_traits.hpp`
- `include/fastgltf/glm_element_traits.hpp`
- `include/fastgltf/math.hpp`
- `include/fastgltf/tools.hpp`
- `include/fastgltf/types.hpp`
- `include/fastgltf/util.hpp`
- `src/base64.cpp`
- `src/fastgltf.cpp`
- `src/io.cpp`

UzEngine patches: none under this library at the commit.
