# Origin of volk

| Field | Value |
|---|---|
| Upstream | https://github.com/zeux/volk |
| Release | `vulkan-sdk-1.4.304.1` |
| Tag commit | `0b17a763ba5643e32da1b2152f8140461b3b7345` |
| Archive | https://github.com/zeux/volk/archive/refs/tags/vulkan-sdk-1.4.304.1.tar.gz |
| Archive SHA-256 | `01f9facf95167f76d48c752c17ac602ffbc33d2e7157774e2c32a7de614b3687` |
| Archive root | `volk-vulkan-sdk-1.4.304.1/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.2_vendor-thirdparty`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/README.md` (vulkan-sdk-1.4.304.1); `scripts/setup.ps1` clones tag `vulkan-sdk-1.4.304.1` |
| Licence | MIT (`LICENSE.md`) |
| Licence files | `LICENSE.md` (verbatim) |
| Distribution role | shipped: compiled into `UzPainter.exe` |
| Selected features | Meta-loader compiled with `VK_NO_PROTOTYPES`; `vulkan-1.dll` is loaded at run time from the system and never shipped |
| Include directories | `thirdparty/volk/.` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (3)

- `LICENSE.md` (1,066 bytes)
- `volk.c` (267,743 bytes)
- `volk.h` (134,827 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/volk` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 6 |
| line-endings | 0 |
| different | 0 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 0 |

Identical files:

- `CMakeLists.txt`
- `LICENSE.md`
- `README.md`
- `generate.py`
- `volk.c`
- `volk.h`

UzEngine patches: none under this library at the commit.
