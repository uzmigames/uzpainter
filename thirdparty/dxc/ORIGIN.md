# Origin of DXC

| Field | Value |
|---|---|
| Upstream | https://github.com/microsoft/DirectXShaderCompiler |
| Release | `v1.9.2602` |
| Tag commit | `21d28f727ad395b59394815ef76012e432f7e4e5` |
| Archive | https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2602/dxc_2026_02_20.zip |
| Archive SHA-256 | `a1e89031421cf3c1fca6627766ab3020ca4f962ac7e2caa7fab2b33a8436151e` |
| Archive root | `(none)` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.2_vendor-thirdparty`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/README.md` (1.9.2602); `scripts/setup.ps1` downloads the release asset `dxc_2026_02_20.zip` of tag `v1.9.2602` |
| Licence | `ReleaseNotes.md` "Licenses": `LICENSE-MIT.txt` for `d3d12shader.h`, `LICENSE-LLVM.txt` (University of Illinois/NCSA) for all other files; the package also holds `LICENSE-MS.txt` (Microsoft Software License Terms "MICROSOFT DIRECTX SHADER COMPILER"), whose scope the notes do not state |
| Licence files | `LICENSE-LLVM.txt`, `LICENSE-MIT.txt`, `LICENSE-MS.txt` (verbatim) |
| Distribution role | shipped: `dxcompiler.dll` and `dxil.dll` beside `UzPainter.exe` (`13-engine-integration.md` §5); `dxcapi.h` build-only |
| Selected features | x64 DLLs and `dxcapi.h` only (no `dxc.exe`, `dxv.exe`, import libraries, arm64/x86 builds or other headers); `dxcapi.h` includes only `WinAdapter.h` and `<dlfcn.h>`, both inside its non-Windows branch |
| Include directories | `thirdparty/dxc/inc` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: **release blocker** — RB-DXC-DXIL: redistribution of `dxil.dll` is not confirmed — `LICENSE-MS.txt` has no stated scope and refers to a distributables list absent from the package; resolve by written confirmation of the terms or by not shipping `dxil.dll`
- `dxcompiler.dll` and `dxcapi.h`: NCSA per the package's own licence table; redistribution with the licence text is permitted.
- `dxil.dll`: the licence table puts it under NCSA, but `LICENSE-MS.txt`, the only text in the package that grants binary distribution of Microsoft code, permits distributing only "the object code form of the software listed in the distributables file list in the software", and the package contains no such list.
- Since DXC 1.8.2505 the compiler always uses its internal validator instead of an external `DXIL.dll` (`ReleaseNotes.md`), so whether `dxil.dll` must ship at all is for `phase0.8_toolchain-slice` to measure.

## Selected files (7)

- `LICENSE-LLVM.txt` (1,979 bytes)
- `LICENSE-MIT.txt` (1,093 bytes)
- `LICENSE-MS.txt` (13,163 bytes)
- `ReleaseNotes.md` (20,405 bytes)
- `bin/x64/dxcompiler.dll` (17,951,808 bytes)
- `bin/x64/dxil.dll` (1,503,304 bytes)
- `inc/dxcapi.h` (54,636 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/dxc` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 0 |
| line-endings | 19 |
| different | 0 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 2 |

UzEngine commits the package's text files only; its binaries (`*.dll`, `*.exe`, `*.lib`) are ignored by git and fetched by `scripts/setup.ps1`, so the two DLLs have no committed counterpart.

Line endings only (equal after CRLF -> LF; UzEngine's blob stores LF where the upstream file has CRLF (`core.autocrlf=true` normalised the text on commit)):

- `LICENSE-LLVM.txt`
- `LICENSE-MIT.txt`
- `LICENSE-MS.txt`
- `ReleaseNotes.md`
- `inc/Support/ErrorCodes.h`
- `inc/d3d12shader.h`
- `inc/dxcapi.h`
- `inc/dxcerrors.h`
- `inc/dxcisense.h`
- `inc/dxcpix.h`
- `inc/hlsl/LICENSE.txt`
- `inc/hlsl/README.txt`
- `inc/hlsl/dx/linalg.h`
- `inc/hlsl/enable_if.h`
- `inc/hlsl/vector_utils.h`
- `inc/hlsl/vk/khr/cooperative_matrix.h`
- `inc/hlsl/vk/khr/cooperative_matrix.impl`
- `inc/hlsl/vk/opcode_selector.h`
- `inc/hlsl/vk/spirv.h`

Selected files absent from UzEngine's tree at the commit:

- `bin/x64/dxcompiler.dll`
- `bin/x64/dxil.dll`

UzEngine patches: none under this library at the commit.
