# Origin of ufbx

| Field | Value |
|---|---|
| Upstream | https://github.com/ufbx/ufbx |
| Release | `v0.23.1` |
| Tag commit | `26a482ae66871d7de36eb722aa060bce95bce274` |
| Archive | https://github.com/ufbx/ufbx/archive/refs/tags/v0.23.1.tar.gz |
| Archive SHA-256 | `21edd1021dfb430e37aa6214c9b3bbaa5634b1859cbbef7231e738af4f19c956` |
| Archive root | `ufbx-0.23.1/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase1.4_mesh-importers`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/README.md` lists ufbx 0.14.3; UzPainter selects the newest ufbx release on the retrieval date instead (tag `v0.23.1`, tagged 2026-09-25; ufbx publishes its releases as annotated tags, not GitHub releases), for the FBX importer of `docs/architecture/12-mesh-import.md` §2 |
| Licence | MIT or public domain, the user's choice (`LICENSE`: "ALTERNATIVE A - MIT License", Copyright (c) 2020 Samuli Raivio; "ALTERNATIVE B - Public Domain (www.unlicense.org)"); `ufbx.c` and `ufbx.h` carry no notice of their own |
| Licence files | `LICENSE` (verbatim) |
| Distribution role | build-only today: compiled into `uzp_mesh.lib` (UzPainter's mesh importers, `src/mesh/`) and its native tests `uzp-mesh-tests.exe` (`phase1.4_mesh-importers`); shipped once `UzPainter.exe` links the importers |
| Selected features | `ufbx.c` compiled as C11 with the default configuration (no `UFBX_CONFIG_HEADER`, `UFBX_CONFIG_SOURCE` or `UFBX_HEADER_PATH`); the `extra/` helpers, language bindings, examples, tests, test data and `misc/` tools are not vendored |
| Include directories | `thirdparty/ufbx/.` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (3)

- `LICENSE` (2,631 bytes)
- `ufbx.c` (1,181,511 bytes)
- `ufbx.h` (223,898 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/ufbx` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 1 |
| line-endings | 0 |
| different | 2 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 0 |

Differences and their causes:

- `ufbx.c` (different): version, not a patch: UzEngine's blob is byte-equal to `ufbx.c` of upstream tag `v0.14.3` (commit `19bdb7e7`); UzPainter vendors `v0.23.1`
- `ufbx.h` (different): version, not a patch: UzEngine's blob is byte-equal to `ufbx.h` of upstream tag `v0.14.3` (`UFBX_HEADER_VERSION` 0.14.3); UzPainter vendors `v0.23.1`

Identical files:

- `LICENSE`

UzEngine patches: none under this library at the commit.
