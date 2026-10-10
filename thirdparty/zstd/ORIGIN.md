# Origin of zstd

| Field | Value |
|---|---|
| Upstream | https://github.com/facebook/zstd |
| Release | `v1.5.7` |
| Tag commit | `f8745da6ff1ad1e7bab384bd1f9d742439278e99` |
| Archive | https://github.com/facebook/zstd/releases/download/v1.5.7/zstd-1.5.7.tar.gz |
| Archive SHA-256 | `eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3` |
| Archive root | `zstd-1.5.7/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase1.4_store-container-operations`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzPainter's selection: the newest zstd release on the retrieval date (tag `v1.5.7`, published 2025-02-19; the archive SHA-256 equals the release's `.sha256` asset); payload compression of the `.uzp` container (decision 010, `docs/architecture/09-project-file-format.md` §1) |
| Licence | BSD-3-Clause (`LICENSE`), elected from upstream's dual licence (BSD or GPLv2, stated in every source file; the GPLv2 text `COPYING` is not vendored and not used) |
| Licence files | `LICENSE` (verbatim) |
| Distribution role | shipped: compiled into `uzp_store.lib`, the project store library (`src/store/`, `docs/architecture/09-project-file-format.md` §1); its native tests link it today, `UzPainter.exe` once the worker opens projects |
| Selected features | The compression and decompression units of `lib/` compiled as C11 with `ZSTD_DISABLE_ASM` (the x86-64 assembly `huf_decompress_amd64.S` is not vendored) and without `ZSTD_MULTITHREAD` or `ZSTD_LEGACY_SUPPORT`; no dictionary builder, legacy formats, deprecated API, programs, contrib or tests |
| Include directories | `thirdparty/zstd/lib` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (64)

- `LICENSE` (1,549 bytes)
- `lib/common/allocations.h` (1,637 bytes)
- `lib/common/bits.h` (5,956 bytes)
- `lib/common/bitstream.h` (18,727 bytes)
- `lib/common/compiler.h` (16,644 bytes)
- `lib/common/cpu.h` (5,438 bytes)
- `lib/common/debug.c` (1,091 bytes)
- `lib/common/debug.h` (3,925 bytes)
- `lib/common/entropy_common.c` (13,308 bytes)
- `lib/common/error_private.c` (3,905 bytes)
- `lib/common/error_private.h` (6,438 bytes)
- `lib/common/fse.h` (30,033 bytes)
- `lib/common/fse_decompress.c` (12,478 bytes)
- `lib/common/huf.h` (14,119 bytes)
- `lib/common/mem.h` (12,939 bytes)
- `lib/common/pool.c` (11,782 bytes)
- `lib/common/pool.h` (2,569 bytes)
- `lib/common/portability_macros.h` (4,916 bytes)
- `lib/common/threading.c` (4,886 bytes)
- `lib/common/threading.h` (5,112 bytes)
- `lib/common/xxhash.c` (607 bytes)
- `lib/common/xxhash.h` (262,488 bytes)
- `lib/common/zstd_common.c` (1,683 bytes)
- `lib/common/zstd_deps.h` (3,010 bytes)
- `lib/common/zstd_internal.h` (10,911 bytes)
- `lib/common/zstd_trace.h` (4,562 bytes)
- `lib/compress/clevels.h` (6,860 bytes)
- `lib/compress/fse_compress.c` (24,103 bytes)
- `lib/compress/hist.c` (7,650 bytes)
- `lib/compress/hist.h` (3,754 bytes)
- `lib/compress/huf_compress.c` (58,546 bytes)
- `lib/compress/zstd_compress.c` (345,541 bytes)
- `lib/compress/zstd_compress_internal.h` (68,505 bytes)
- `lib/compress/zstd_compress_literals.c` (9,155 bytes)
- `lib/compress/zstd_compress_literals.h` (1,613 bytes)
- `lib/compress/zstd_compress_sequences.c` (20,004 bytes)
- `lib/compress/zstd_compress_sequences.h` (2,224 bytes)
- `lib/compress/zstd_compress_superblock.c` (34,085 bytes)
- `lib/compress/zstd_compress_superblock.h` (1,168 bytes)
- `lib/compress/zstd_cwksp.h` (28,892 bytes)
- `lib/compress/zstd_double_fast.c` (35,303 bytes)
- `lib/compress/zstd_double_fast.h` (1,767 bytes)
- `lib/compress/zstd_fast.c` (38,104 bytes)
- `lib/compress/zstd_fast.h` (1,178 bytes)
- `lib/compress/zstd_lazy.c` (102,821 bytes)
- `lib/compress/zstd_lazy.h` (9,684 bytes)
- `lib/compress/zstd_ldm.c` (29,313 bytes)
- `lib/compress/zstd_ldm.h` (4,365 bytes)
- `lib/compress/zstd_ldm_geartab.h` (6,077 bytes)
- `lib/compress/zstd_opt.c` (72,006 bytes)
- `lib/compress/zstd_opt.h` (3,046 bytes)
- `lib/compress/zstd_preSplit.c` (8,729 bytes)
- `lib/compress/zstd_preSplit.h` (1,175 bytes)
- `lib/compress/zstdmt_compress.c` (84,098 bytes)
- `lib/compress/zstdmt_compress.h` (4,574 bytes)
- `lib/decompress/huf_decompress.c` (76,910 bytes)
- `lib/decompress/zstd_ddict.c` (9,182 bytes)
- `lib/decompress/zstd_ddict.h` (1,319 bytes)
- `lib/decompress/zstd_decompress.c` (102,400 bytes)
- `lib/decompress/zstd_decompress_block.c` (101,467 bytes)
- `lib/decompress/zstd_decompress_block.h` (2,682 bytes)
- `lib/decompress/zstd_decompress_internal.h` (9,683 bytes)
- `lib/zstd.h` (181,748 bytes)
- `lib/zstd_errors.h` (4,278 bytes)

## Comparison with UzEngine's copy

UzEngine's tree at the commit has no zstd (`runtime/thirdparty/` holds no zstd folder), so there is nothing to compare.
