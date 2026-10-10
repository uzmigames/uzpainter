# Origin of zlib

| Field | Value |
|---|---|
| Upstream | https://github.com/madler/zlib |
| Release | `v1.3.2` |
| Tag commit | `da607da739fa6047df13e66a2af6b8bec7c2a498` |
| Archive | https://github.com/madler/zlib/releases/download/v1.3.2/zlib-1.3.2.tar.gz |
| Archive SHA-256 | `bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16` |
| Archive root | `zlib-1.3.2/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.6_toolchain-hardware-slice`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzPainter's selection: the newest zlib release on the retrieval date (tag `v1.3.2`, published 2026-02-17); spng needs zlib (`SPNG_USE_MINIZ` stays undefined) |
| Licence | zlib licence (`LICENSE`; the same notice is in `README` and `zlib.h`) |
| Licence files | `LICENSE`, `README` (verbatim) |
| Distribution role | shipped: compiled into `UzPainter.exe` |
| Selected features | The units spng uses, compiled as C11: `adler32`, `compress`, `crc32`, `deflate`, `inffast`, `inflate`, `inftrees`, `trees`, `zutil`; `gzguts.h` only because `zutil.c` includes it; no gz* sources, `uncompr`, contrib, examples or tests |
| Include directories | `thirdparty/zlib/.` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (22)

- `LICENSE` (1,002 bytes)
- `README` (5,291 bytes)
- `adler32.c` (4,964 bytes)
- `compress.c` (3,639 bytes)
- `crc32.c` (29,735 bytes)
- `crc32.h` (591,749 bytes)
- `deflate.c` (83,286 bytes)
- `deflate.h` (14,213 bytes)
- `gzguts.h` (7,088 bytes)
- `inffast.c` (12,982 bytes)
- `inffast.h` (422 bytes)
- `inffixed.h` (5,968 bytes)
- `inflate.c` (52,247 bytes)
- `inflate.h` (6,683 bytes)
- `inftrees.c` (16,672 bytes)
- `inftrees.h` (3,003 bytes)
- `trees.c` (41,030 bytes)
- `trees.h` (8,472 bytes)
- `zconf.h` (16,955 bytes)
- `zlib.h` (103,848 bytes)
- `zutil.c` (7,454 bytes)
- `zutil.h` (8,512 bytes)

## Comparison with UzEngine's copy

UzEngine takes zlib from vcpkg (`runtime/thirdparty/README.md`, vcpkg section); its tree at the commit has no zlib folder, so there is nothing to compare.
