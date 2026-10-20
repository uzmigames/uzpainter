# Origin of etcpak

| Field | Value |
|---|---|
| Upstream | https://github.com/wolfpld/etcpak |
| Release | `2.1` |
| Tag commit | `7f15da4739cc5f8562311bdbb800436986d268ca` |
| Archive | https://github.com/wolfpld/etcpak/archive/refs/tags/2.1.tar.gz |
| Archive SHA-256 | `7b076ca044318bafeefef28bf5653f2fe6a21cc63f68f628fc696964925f695e` |
| Archive root | `etcpak-2.1/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-19 |
| Importer | Rulebook task `phase3.1_uze-uztexture-writer`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/README.md` records etcpak as "git (master, 2025)" and its `README.md` says etcpak 2.1; UzPainter pins release `2.1` (tag commit `7f15da47`, published 2026-02-22), the newest release on the retrieval date, for the BC encoder adapter of `docs/architecture/08-export.md` §3 (`phase3.1_uze-uztexture-writer`) |
| Licence | BSD-3-Clause (etcpak, `LICENSE.txt`, Copyright (c) 2013-2026 Bartosz Taudul; contributors in `AUTHORS.txt`); the bundled bc7enc (`bc7enc.cpp`, `bc7enc.h`, Richard Geldreich, Jr.) under MIT or the Unlicense, the user's choice, stated at the end of `bc7enc.cpp`; the bundled bcdec (`bcdec.h`, `bcdec.c`, Sergii Kudlai) under MIT or the Unlicense, stated at the end of `bcdec.h` |
| Licence files | `LICENSE.txt`, `AUTHORS.txt`, `bc7enc.cpp`, `bcdec.h` (verbatim) |
| Distribution role | shipped: `ProcessDxtc.cpp`, `bc7enc.cpp` and `Dither.cpp` compiled into `uzp_texture.lib` (UzPainter's BC encoder adapter, `src/export/bc_encoder.cpp`), which `UzPainter.exe` links for the export's `.uztexture` normal derivative (decision 316), and into its native tests; `bcdec.c` compiled into `uzp-texture-tests.exe` only, the independent decoder oracle |
| Selected features | The BC1, BC3, BC4, BC5 and BC7 block encoders of `ProcessDxtc.cpp` (`CompressBc1`, `CompressBc3`, `CompressBc4`, `CompressBc5`, `CompressBc7` over bc7enc's `bc7enc_compress_block`) compiled as C++ with `-ffp-contract=off`; `Dither.cpp` only because `CompressBc1Dither` in the same unit references it (dithering is never called); the SIMD branches follow the build's target CPU; bcdec's decoders for the tests (`BCDEC_IMPLEMENTATION` through `bcdec.c`); no ETC codecs, command-line application, task dispatcher, image I/O, CMake files or examples |
| Include directories | `thirdparty/etcpak/.` |

Every file below is byte-equal to the archive member at the same path, except for the local changes listed below; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each vendored file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Local changes

- `bcdec.h`: BC7 RGB-only modes do not read alpha endpoints, but the shared P-bit and endpoint expansion loops shift those uninitialised integers before overwriting alpha with 255. Initialise the array so the independent test oracle has defined behaviour; keep undefined-behaviour checks enabled. The authored all-mode corpus exposes the ReleaseSafe trap on mode-0 block 61ea9fd86740340322a13f24c7fc4362.
  - Upstream: `int endpoints[6][4];`
  - Vendored: `int endpoints[6][4] = {0}; /* UzPainter: RGB-only modes still shift alpha before setting it. */`

## Selected files (12)

- `AUTHORS.txt` (182 bytes)
- `Dither.cpp` (5,391 bytes)
- `Dither.hpp` (346 bytes)
- `ForceInline.hpp` (461 bytes)
- `LICENSE.txt` (1,610 bytes)
- `Math.hpp` (1,769 bytes)
- `ProcessDxtc.cpp` (51,609 bytes)
- `ProcessDxtc.hpp` (718 bytes)
- `bc7enc.cpp` (162,527 bytes)
- `bc7enc.h` (4,328 bytes)
- `bcdec.c` (48 bytes)
- `bcdec.h` (71,020 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/etcpak` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 59 |
| line-endings | 0 |
| different | 0 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 0 |

Identical files:

- `AUTHORS.txt`
- `Application.cpp`
- `Bitmap.cpp`
- `Bitmap.hpp`
- `BitmapDownsampled.cpp`
- `BitmapDownsampled.hpp`
- `BlockData.cpp`
- `BlockData.hpp`
- `CMakeLists.txt`
- `CPM.cmake`
- `ColorSpace.cpp`
- `ColorSpace.hpp`
- `DataProvider.cpp`
- `DataProvider.hpp`
- `Debug.cpp`
- `Debug.hpp`
- `Decode.cpp`
- `Decode.hpp`
- `Dither.cpp`
- `Dither.hpp`
- `Error.cpp`
- `Error.hpp`
- `ForceInline.hpp`
- `LICENSE.txt`
- `Math.hpp`
- `MipMap.hpp`
- `ProcessCommon.hpp`
- `ProcessDxtc.cpp`
- `ProcessDxtc.hpp`
- `ProcessRGB.cpp`
- `ProcessRGB.hpp`
- `README.md`
- `Semaphore.hpp`
- `System.cpp`
- `System.hpp`
- `Tables.cpp`
- `Tables.hpp`
- `TaskDispatch.cpp`
- `TaskDispatch.hpp`
- `TextureHeader.cpp`
- `TextureHeader.hpp`
- `Timing.cpp`
- `Timing.hpp`
- `Vector.hpp`
- `bc7enc.cpp`
- `bc7enc.h`
- `bcdec.c`
- `bcdec.h`
- `examples/bc7.png`
- `examples/dxtc.png`
- `examples/etc1.png`
- `examples/etc2.png`
- `examples/kodim23.png`
- `getopt/LICENSE.txt`
- `getopt/getopt.c`
- `getopt/getopt.h`
- `mmap.cpp`
- `mmap.hpp`
- `simd.py`

UzEngine patches: none under this library at the commit.
