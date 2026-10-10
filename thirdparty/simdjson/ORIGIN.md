# Origin of simdjson

| Field | Value |
|---|---|
| Upstream | https://github.com/simdjson/simdjson |
| Release | `v4.6.11` |
| Tag commit | `f5de14f09256982933af2849beb43778bd421ca7` |
| Archive | https://github.com/simdjson/simdjson/archive/refs/tags/v4.6.11.tar.gz |
| Archive SHA-256 | `61d948fc24f0d793829ad658058e7597d064988a89b4607ea02e401a82df98ff` |
| Archive root | `simdjson-4.6.11/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase1.4_mesh-importers`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzPainter's selection: the simdjson version fastgltf `v0.9.1` pins (`cmake/dependencies.cmake`: `SIMDJSON_TARGET_VERSION` "4.6.11", whose `singleheader/simdjson.h` and `singleheader/simdjson.cpp` fastgltf's build downloads); tag `v4.6.11`, released 2026-09-05. The newer 5.0.x releases (2026-09-28 to 2026-10-08) start a major version fastgltf v0.9.1 does not name |
| Licence | Apache-2.0 (`LICENSE`) or MIT (`LICENSE-MIT`), the user's choice (`README.md` "License"); the amalgamation embeds code under its own notices (licence notes below) |
| Licence files | `LICENSE`, `LICENSE-MIT` (verbatim) |
| Distribution role | build-only today: compiled into `uzp_mesh.lib` (UzPainter's mesh importers, `src/mesh/`) and its native tests `uzp-mesh-tests.exe` (`phase1.4_mesh-importers`); shipped once `UzPainter.exe` links the importers |
| Selected features | The amalgamated single-header build: `singleheader/simdjson.cpp` compiled as C++ with run-time selection of the SIMD kernels (no architecture flags; `-mevex512` lets Zig 0.15.2's clang compile the AVX-512 `icelake` kernel's target regions against the baseline x86-64 CPU), `singleheader/simdjson.h` included by fastgltf; the split `include/` and `src/` trees, the amalgamation script and demo, `singleheader.zip`, benchmarks, tools, tests and documentation are not vendored |
| Include directories | `thirdparty/simdjson/singleheader` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)
- The tag has no `NOTICE` file, so Apache-2.0 §4(d) adds no attribution text.
- Both amalgamated files embed `simdjson/internal/instruction_set.h`, adapted from PyTorch's `simd.h` under BSD-3-Clause with its notice in place (Facebook, Idiap Research Institute, Deepmind Technologies, NEC Laboratories America, NYU); clause 2 requires binary distributions to reproduce that notice.
- `simdjson.cpp` embeds `to_chars.cpp`, the Grisu2 conversion adapted from JSON for Modern C++, which states "distributed under the MIT license, Copyright (c) 2009 Florian Loitsch"; its UTF-8 validator is credited "based on code from Google Fuchsia (Apache Licensed)".
- string-view lite (Boost Software License 1.0, Martin Moene) is embedded inside `#ifndef SIMDJSON_HAS_STRING_VIEW`, a branch a C++17-or-later build never compiles.

## Selected files (4)

- `LICENSE` (11,355 bytes)
- `LICENSE-MIT` (1,065 bytes)
- `singleheader/simdjson.cpp` (2,758,235 bytes)
- `singleheader/simdjson.h` (7,742,579 bytes)

## Comparison with UzEngine's copy

UzEngine's tree at the commit has no simdjson (`runtime/thirdparty/` holds no simdjson folder; its `fastgltf` entry is a submodule link without files), so there is nothing to compare.
