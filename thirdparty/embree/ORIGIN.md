# Origin of Embree

| Field | Value |
|---|---|
| Upstream | https://github.com/RenderKit/embree |
| Release | `v4.4.1` |
| Tag commit | `f590db83ef6559387df7f6d8725c34fb7acf851d` |
| Archive | https://github.com/RenderKit/embree/releases/download/v4.4.1/embree-4.4.1.x64.windows.zip |
| Archive SHA-256 | `5aa1fa3161a720f9c610b06c652b80f421cb2b1fe8221fdf92b74157336fdf8f` |
| Archive root | `embree-4.4.1.x64.windows/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.6_toolchain-hardware-slice`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzPainter's selection: the newest Embree 4.x release on the retrieval date (tag `v4.4.1`, published 2026-04-02), its prebuilt x64 Windows package (`13-engine-integration.md` §5: `embree4.dll` + `tbb12.dll` from an Embree 4.x release) |
| Licence | Apache-2.0 (`share/doc/Embree_superbuild/LICENSE.txt`; every header carries `SPDX-License-Identifier: Apache-2.0`); `tbb12.dll` is oneTBB, Apache-2.0, with its notices in `third-party-programs-TBB.txt`; `third-party-programs.txt` lists the notices of the release's components |
| Licence files | `share/doc/Embree_superbuild/LICENSE.txt`, `share/doc/Embree_superbuild/third-party-programs.txt`, `share/doc/Embree_superbuild/third-party-programs-TBB.txt` (verbatim) |
| Distribution role | shipped: `embree4.dll` and `tbb12.dll` beside `UzPainter.exe` (`13-engine-integration.md` §5), loaded at run time by the `embree` stage of `selftest`; headers build-only |
| Selected features | Prebuilt x64 Windows release with TBB tasking: `embree4.dll`, `tbb12.dll` and the C API headers `include/embree4/*.h`. No import library (UzPainter loads `embree4.dll` with `LoadLibraryExW` and resolves the C API by name), no `tbbmalloc.dll` (neither vendored DLL imports it), no tutorials, ISPC headers, CMake files or documentation besides the licence files |
| Include directories | `thirdparty/embree/include` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)
- Apache-2.0 §4(d): the release has no `NOTICE` file; binary distributions reproduce `LICENSE.txt`, `third-party-programs.txt` and `third-party-programs-TBB.txt`.
- `embree4.dll` and `tbb12.dll` import the Visual C++ runtime (`MSVCP140.dll`, `VCRUNTIME140.dll`), which the package does not contain; the measured import closure (`tools.toolchain.dll_closure`) records them, and their app-local shipping is governed by the Visual C++ runtime row of `docs/licensing-and-clean-room.md` §3.

## Selected files (15)

- `bin/embree4.dll` (37,435,952 bytes)
- `bin/tbb12.dll` (348,008 bytes)
- `include/embree4/rtcore.h` (355 bytes)
- `include/embree4/rtcore_buffer.h` (2,418 bytes)
- `include/embree4/rtcore_builder.h` (3,809 bytes)
- `include/embree4/rtcore_common.h` (15,787 bytes)
- `include/embree4/rtcore_config.h` (2,975 bytes)
- `include/embree4/rtcore_device.h` (5,132 bytes)
- `include/embree4/rtcore_geometry.h` (15,987 bytes)
- `include/embree4/rtcore_quaternion.h` (2,591 bytes)
- `include/embree4/rtcore_ray.h` (11,706 bytes)
- `include/embree4/rtcore_scene.h` (21,605 bytes)
- `share/doc/Embree_superbuild/LICENSE.txt` (11,560 bytes)
- `share/doc/Embree_superbuild/third-party-programs-TBB.txt` (47,390 bytes)
- `share/doc/Embree_superbuild/third-party-programs.txt` (113,087 bytes)

## Comparison with UzEngine's copy

UzEngine's tree at the commit has no Embree (`runtime/thirdparty/` holds no Embree folder), so there is nothing to compare.
