# Origin of SPIRV-Reflect

| Field | Value |
|---|---|
| Upstream | https://github.com/KhronosGroup/SPIRV-Reflect |
| Release | `vulkan-sdk-1.4.309.0` |
| Tag commit | `c637858562fbce1b6f5dc7ca48d4e8a5bd117b70` |
| Archive | https://github.com/KhronosGroup/SPIRV-Reflect/archive/refs/tags/vulkan-sdk-1.4.309.0.tar.gz |
| Archive SHA-256 | `ee57238d4a2c0abf7f0641fb5143bde211e8e31a94194458bab2b6b0a97cb282` |
| Archive root | `SPIRV-Reflect-vulkan-sdk-1.4.309.0/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.2_vendor-thirdparty`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `scripts/setup.ps1` clones tag `vulkan-sdk-1.4.309.0` (`runtime/thirdparty/README.md` has no SPIRV-Reflect section) |
| Licence | Apache-2.0 (`LICENSE`); `include/spirv/unified1/spirv.h` carries the Khronos MIT-style permission notice in its header |
| Licence files | `LICENSE` (verbatim) |
| Distribution role | shipped: compiled into `UzPainter.exe` |
| Selected features | `spirv_reflect.c` compiled as C11; no command-line tool, examples or tests |
| Include directories | `thirdparty/spirv-reflect/.`, `thirdparty/spirv-reflect/include` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)
- The tag has no `NOTICE` file, so Apache-2.0 §4(d) adds no attribution text.

## Selected files (4)

- `LICENSE` (11,357 bytes)
- `include/spirv/unified1/spirv.h` (152,524 bytes)
- `spirv_reflect.c` (219,598 bytes)
- `spirv_reflect.h` (95,914 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/spirv-reflect` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 12 |
| line-endings | 0 |
| different | 0 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 0 |

Identical files:

- `.git-blame-ignore-revs`
- `CMakeLists.txt`
- `CODE_OF_CONDUCT.adoc`
- `LICENSE`
- `README.md`
- `common/output_stream.cpp`
- `common/output_stream.h`
- `include/spirv/unified1/spirv.h`
- `main.cpp`
- `spirv_reflect.c`
- `spirv_reflect.cpp`
- `spirv_reflect.h`

UzEngine patches: none under this library at the commit.
