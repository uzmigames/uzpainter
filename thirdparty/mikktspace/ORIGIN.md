# Origin of mikktspace

| Field | Value |
|---|---|
| Upstream | https://github.com/mmikk/MikkTSpace |
| Release | `master@3e895b49` |
| Tag commit | `3e895b49d05ea07e4c2133156cfa94369e19e409` |
| Archive | https://github.com/mmikk/MikkTSpace/archive/3e895b49d05ea07e4c2133156cfa94369e19e409.tar.gz |
| Archive SHA-256 | `aeba65ddee85a679133d510d71d00b108f603752f90b15b9ecf7777033f6e351` |
| Archive root | `MikkTSpace-3e895b49d05ea07e4c2133156cfa94369e19e409/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.9_normal-convention-fixture`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/mikktspace` holds the same upstream code (its `mikktspace.c` carries one local patch, below); upstream has no release tags, so UzPainter pins commit `3e895b49`, the head of `master` on the retrieval date (approved source S-MIKK, `docs/architecture/12-mesh-import.md` §3) |
| Licence | zlib licence, stated in the comment block at the top of `mikktspace.h` (the same notice heads `mikktspace.c`) |
| Licence files | `mikktspace.h` (verbatim) |
| Distribution role | build-only: compiled into `uzp-normal-prototype.exe`, the Phase 0 tangent-frame prototype of `phase0.9_normal-convention-fixture`; not shipped |
| Selected features | `mikktspace.c` compiled as C11 (`genTangSpaceDefault`, per-corner tangents and bitangent sign); the repository's `README.md` is not vendored |
| Include directories | `thirdparty/mikktspace/.` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (2)

- `mikktspace.c` (57,439 bytes)
- `mikktspace.h` (8,209 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/mikktspace` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 2 |
| line-endings | 0 |
| different | 1 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 0 |

Differences and their causes:

- `mikktspace.c` (different): UzEngine patched the rotate in `QuickSort`'s pivot generator (a shift by 32 when the rotate amount is 0, undefined in C, which Zig's Debug sanitizer traps); UzPainter vendors the upstream file unchanged and compiles it with `-fno-sanitize=undefined` instead (`build.zig`)

Identical files:

- `README.md`
- `mikktspace.h`

UzEngine patches: none under this library at the commit.
