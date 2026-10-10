# Origin of CPython

| Field | Value |
|---|---|
| Upstream | https://www.python.org/downloads/release/python-31316/ |
| Release | `v3.13.16` |
| Tag commit | `cbc944f4bc59639a444dd971c737788ba2283a91` |
| Archive | https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip |
| Archive SHA-256 | `97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297` |
| Archive root | `(none)` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.7_toolchain-cpython`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzPainter's selection: CPython 3.13 because Painter 12.1 ships 3.13.9 (`docs/architecture/10-python-api.md` §1); 3.13.16 (tag `v3.13.16`, released 2026-09-30) is the newest 3.13 release with Windows binaries on the retrieval date |
| Licence | PSF License Version 2 with the historical BeOpen, CNRI and CWI licences, the Zero-Clause BSD licence for documentation code and the licences of the incorporated software (bzip2, libffi, OpenSSL, SQLite, expat, mpdecimal, zlib and others), all in `LICENSE.txt`; its section "Additional Conditions for this Windows binary build" covers the Microsoft Distributable Code linked into every `.exe`, `.dll` and `.pyd` |
| Licence files | `LICENSE.txt` (verbatim) |
| Distribution role | shipped: every selected file beside `UzPainter.exe` (`13-engine-integration.md` §5); `python313.dll` is imported by `UzPainter.exe`, which embeds the interpreter |
| Selected features | The Windows x64 embeddable package without `python.exe`, `pythonw.exe`, `python313._pth` (UzPainter installs its own, `src/python/python313._pth`) and the catalog `python.cat`: `python313.dll`, the standard library as `python313.zip`, the standard extension modules (`*.pyd`) and the DLLs they load, `python3.dll` for stable-ABI wheels, and the package's `vcruntime140.dll` and `vcruntime140_1.dll` (file version 14.51.36247.0, newer than `thirdparty/vc-runtime/`'s 14.44, so these two are the ones installed) |
| Include directories |  |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)
- The package's `python313.dll`, `python3.dll`, `vcruntime140.dll`, `vcruntime140_1.dll` and `LICENSE.txt` are byte-equal to those of `python-3.13.16-amd64.zip` (`thirdparty/cpython-dev/`), whose SHA-256 python.org publishes in its signed release index `windows-3.13.16.json`.
- `vcruntime140.dll` and `vcruntime140_1.dll` are Microsoft Visual C++ Distributable Code like `thirdparty/vc-runtime/`: their redistribution falls under release blocker RB-VCRT-TERMS (`docs/licensing-and-clean-room.md` §3).

## Selected files (30)

- `LICENSE.txt` (33,861 bytes)
- `_asyncio.pyd` (72,928 bytes)
- `_bz2.pyd` (86,752 bytes)
- `_ctypes.pyd` (134,368 bytes)
- `_decimal.pyd` (286,944 bytes)
- `_elementtree.pyd` (136,416 bytes)
- `_hashlib.pyd` (69,344 bytes)
- `_lzma.pyd` (159,456 bytes)
- `_multiprocessing.pyd` (38,112 bytes)
- `_overlapped.pyd` (57,568 bytes)
- `_queue.pyd` (35,552 bytes)
- `_socket.pyd` (86,752 bytes)
- `_sqlite3.pyd` (131,296 bytes)
- `_ssl.pyd` (190,688 bytes)
- `_uuid.pyd` (27,872 bytes)
- `_wmi.pyd` (39,648 bytes)
- `_zoneinfo.pyd` (51,424 bytes)
- `libcrypto-3.dll` (6,021,880 bytes)
- `libffi-8.dll` (39,696 bytes)
- `libssl-3.dll` (1,308,920 bytes)
- `pyexpat.pyd` (200,416 bytes)
- `python3.dll` (72,416 bytes)
- `python313.dll` (6,142,176 bytes)
- `python313.zip` (3,837,053 bytes)
- `select.pyd` (32,992 bytes)
- `sqlite3.dll` (1,584,864 bytes)
- `unicodedata.pyd` (712,416 bytes)
- `vcruntime140.dll` (178,616 bytes)
- `vcruntime140_1.dll` (50,112 bytes)
- `winsound.pyd` (31,968 bytes)

## Comparison with UzEngine's copy

UzEngine's tree at the commit has no CPython, so there is nothing to compare.
