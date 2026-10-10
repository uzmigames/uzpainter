# Origin of SQLite

| Field | Value |
|---|---|
| Upstream | https://www.sqlite.org/ |
| Release | `3.54.0` |
| Tag commit | `be8d059e9a49089ab2dce5ed26dd87aaf598fdc5fbe0b107c0dd758464bcd5e3` |
| Archive | https://www.sqlite.org/2026/sqlite-amalgamation-3540000.zip |
| Archive SHA-256 | `68e913b0fe8ec6b4e5f391c594a28872884e80d6cd042a1e50c957be46b5aa4d` |
| Archive root | `sqlite-amalgamation-3540000/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase1.4_store-container-operations`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzPainter's selection: the newest SQLite release on the retrieval date (3.54.0, check-in of 2026-10-09 named by `SQLITE_SOURCE_ID` in `sqlite3.h`); the `.uzp` container of decision 010 (`docs/architecture/09-project-file-format.md` §1) |
| Licence | Public domain: the author's dedication ("The author disclaims copyright to this source code") heads `sqlite3.h` and every part of `sqlite3.c` (https://www.sqlite.org/copyright.html) |
| Licence files | `sqlite3.h` (verbatim) |
| Distribution role | shipped: compiled into `uzp_store.lib`, the project store library (`src/store/`, `docs/architecture/09-project-file-format.md` §1); its native tests link it today, `UzPainter.exe` once the worker opens projects |
| Selected features | The amalgamation `sqlite3.c` compiled as C11 with `SQLITE_THREADSAFE=1`, `SQLITE_DQS=0`, `SQLITE_DEFAULT_FOREIGN_KEYS=1`, `SQLITE_OMIT_LOAD_EXTENSION` and `SQLITE_OMIT_DEPRECATED`; no shell (`shell.c`) and no `sqlite3ext.h` |
| Include directories | `thirdparty/sqlite/.` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (2)

- `sqlite3.c` (9,580,800 bytes)
- `sqlite3.h` (695,737 bytes)

## Comparison with UzEngine's copy

UzEngine's tree at the commit has no SQLite (`runtime/thirdparty/` holds no SQLite folder), so there is nothing to compare.
