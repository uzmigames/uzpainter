# Origin of spng

| Field | Value |
|---|---|
| Upstream | https://github.com/randy408/libspng |
| Release | `v0.7.4` |
| Tag commit | `fb768002d4288590083a476af628e51c3f1d47cd` |
| Archive | https://github.com/randy408/libspng/archive/refs/tags/v0.7.4.tar.gz |
| Archive SHA-256 | `47ec02be6c0a6323044600a9221b049f63e1953faf816903e7383d4dc4234487` |
| Archive root | `libspng-0.7.4/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.6_toolchain-hardware-slice`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/README.md` (spng 0.7.4), also the newest spng release on the retrieval date; selected over libpng from the inventory (`docs/licensing-and-clean-room.md` §3) for the 16-bit PNG encoder and decoder of `selftest` |
| Licence | BSD-2-Clause (`LICENSE`) |
| Licence files | `LICENSE` (verbatim) |
| Distribution role | shipped: compiled into `UzPainter.exe` |
| Selected features | `spng/spng.c` compiled as C11 with `SPNG_STATIC` and zlib (`SPNG_USE_MINIZ` undefined); encoder and decoder, 8 and 16 bits per sample; no examples or tests |
| Include directories | `thirdparty/spng/spng` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (3)

- `LICENSE` (1,341 bytes)
- `spng/spng.c` (199,677 bytes)
- `spng/spng.h` (13,338 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/spng` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 16 |
| line-endings | 0 |
| different | 0 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 0 |

Identical files:

- `.gitlab-ci.yml`
- `CMakeLists.txt`
- `LICENSE`
- `README.md`
- `cmake/Config.cmake.in`
- `cmake/libspng.pc.in`
- `meson.build`
- `meson_options.txt`
- `spng/spng.c`
- `spng/spng.h`
- `subprojects/benchmark_images.wrap`
- `subprojects/fuzzing_corpora.wrap`
- `subprojects/libpng.wrap`
- `subprojects/miniz.wrap`
- `subprojects/spngt.wrap`
- `subprojects/zlib.wrap`

UzEngine patches: none under this library at the commit.
