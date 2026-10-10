# Origin of the Visual C++ runtime (app-local)

| Field | Value |
|---|---|
| Publisher | Microsoft Corporation |
| Package | Microsoft Visual C++ 2015-2022 Redistributable, app-local deployment folder of Visual Studio 2022: `VC\Redist\MSVC\14.44.35112\x64\Microsoft.VC143.CRT\` |
| File version | `14.44.35211.0` |
| Authenticode signer | CN=Microsoft Windows Software Compatibility Publisher, O=Microsoft Corporation, L=Redmond, S=Washington, C=US (status Valid on import) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.6_toolchain-hardware-slice`, run with `python -m tools.vendoring.vcruntime import` for UzmiGames |
| Why | Measured import closure: Embree 4.4.1's `embree4.dll` and `tbb12.dll` import `MSVCP140.dll` and `VCRUNTIME140.dll`, and `msvcp140.dll` imports `VCRUNTIME140_1.dll`; a clean Windows has no Visual C++ runtime (`13-engine-integration.md` §5; owner answer to q1, 2026-10-10) |
| Distribution role | shipped: beside `UzPainter.exe` |
| Licence | Microsoft Visual Studio 2022 licence terms, Distributable Code (https://aka.ms/vs/17/redist.txt); not Apache-2.0 |

Microsoft publishes these files for app-local deployment in Visual Studio's redist folder rather than as a downloadable archive, so each file is pinned by SHA-256 and Authenticode signer (`MANIFEST.json`, `tools/vendoring/vcruntime.py`); the bytes are the redist folder's, unchanged.

## Licence inventory

- Status: **release blocker** — RB-VCRT-TERMS: the files are Distributable Code of Microsoft Visual Studio 2022 (list: https://aka.ms/vs/17/redist.txt); redistributing them binds UzmiGames to the Visual Studio licence terms for Distributable Code, which only the owner can accept; until then they ship in development builds only

## Files (3)

- `msvcp140.dll` (557,728 bytes), SHA-256 `0f885b509a685d2bbfa652fed26b5fb31d88fbdab0a978c641d1c7b8aa460aa9`, signer thumbprint `81915C173D7FFCBF49EAA8CF7594696B29A035E1`
- `vcruntime140.dll` (124,544 bytes), SHA-256 `d5e4d9a3e835fa679450145d6a7d94e36573a509317111904d9b3712c30d9066`, signer thumbprint `EC5F0D7EE2327688384B4FDF5D7633553A0D055F`
- `vcruntime140_1.dll` (49,792 bytes), SHA-256 `1f2d41c4aa5db0bc33ebf7b66d72943a817d7ce6cbe880502a9403823633093f`, signer thumbprint `EC5F0D7EE2327688384B4FDF5D7633553A0D055F`
