# Origin of tinyexr

| Field | Value |
|---|---|
| Upstream | https://github.com/syoyo/tinyexr |
| Release | `v3.2.0` |
| Tag commit | `6f470c9ab24bf3992bc512ce07e8ecb00d9bf105` |
| Archive | https://github.com/syoyo/tinyexr/archive/refs/tags/v3.2.0.tar.gz |
| Archive SHA-256 | `df2bd61124a35d8138f8b0bc22418a1d4fe33622c818e0e022f5522afc0821b0` |
| Archive root | `tinyexr-3.2.0/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase1.16_export-processing-encoders`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/README.md` pins tinyexr 1.0.9; UzPainter's selection is the newest release on the retrieval date (tag `v3.2.0`, published 2026-07-08), the export's OpenEXR writer (`docs/licensing-and-clean-room.md` §3, decision 089) |
| Licence | BSD-3-Clause (`LICENSE`, also heading `tinyexr.h`); the OpenEXR-derived code in `tinyexr.h` under Industrial Light & Magic's BSD-3-Clause notice, reproduced in the header |
| Licence files | `LICENSE`, `tinyexr.h` (verbatim) |
| Distribution role | shipped: the header-only implementation compiled once into `UzPainter.exe` and `uzp-export-tests.exe` by `src/export/tinyexr_unit.cpp` |
| Selected features | `TINYEXR_IMPLEMENTATION` with `TINYEXR_USE_MINIZ` 0 over the vendored zlib (`zlib.h` included first; `uncompress` from `uncompr.c`), PIZ compression enabled, no threads, no ZFP; the scanline writer and reader of single-part images (`SaveEXRImageToMemory`, `LoadEXRImageFromMemory`); the v3 C sources under `src/` are not vendored |
| Include directories | `thirdparty/tinyexr/.` |

Every file below is byte-equal to the archive member at the same path, except for the local changes listed below; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each vendored file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Local changes

- `tinyexr.h`: The heap order of the PIZ Huffman table builder (`hufBuildEncTable`) breaks ties between equal frequencies by the symbol's address, as OpenEXR's own `FHeapCompare` does (OpenEXR added the tie-break so that `std::make_heap`/`pop_heap`/`push_heap` build the same table with every standard library). Upstream compares frequencies only, so its PIZ bytes depend on the C++ library's heap algorithm: with Zig's libc++ it re-encodes 20 of Painter 12.1.5's 216 recorded OpenEXR files byte for byte, with the tie-break all 216 (decision 089).
  - Upstream: `bool operator()(long long *a, long long *b) { return *a > *b; }`
  - Vendored: `bool operator()(long long *a, long long *b) { return *a > *b || (*a == *b && a > b); }  // UzPainter local change (thirdparty/tinyexr/ORIGIN.md)`

## Selected files (4)

- `LICENSE` (1,549 bytes)
- `exr_reader.hh` (4,645 bytes)
- `streamreader.hh` (3,782 bytes)
- `tinyexr.h` (385,857 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/tinyexr` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 0 |
| line-endings | 0 |
| different | 1 |
| uzengine-only | 2 |
| selected but absent from UzEngine's tree | 3 |

Differences and their causes:

- `tinyexr.h` (different): UzEngine pins tinyexr 1.0.9 (`runtime/thirdparty/README.md`); UzPainter takes release v3.2.0, so the headers differ by version
- `miniz.c` (uzengine-only): UzEngine compiles tinyexr with miniz; UzPainter sets `TINYEXR_USE_MINIZ` 0 and uses the vendored zlib, so miniz is not vendored
- `miniz.h` (uzengine-only): see `miniz.c`

Selected files absent from UzEngine's tree at the commit:

- `LICENSE`
- `exr_reader.hh`
- `streamreader.hh`

UzEngine patches: none under this library at the commit.
