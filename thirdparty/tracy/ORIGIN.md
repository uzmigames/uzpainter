# Origin of Tracy

| Field | Value |
|---|---|
| Upstream | https://github.com/wolfpld/tracy |
| Release | `v0.13.1` |
| Tag commit | `05cceee0df3b8d7c6fa87e9638af311dbabc63cb` |
| Archive | https://github.com/wolfpld/tracy/archive/refs/tags/v0.13.1.tar.gz |
| Archive SHA-256 | `d4efc50ebcb0bfcfdbba148995aeb75044c0d80f5d91223aebfaa8fa9e563d2b` |
| Archive root | `tracy-0.13.1/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.2_vendor-thirdparty`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/README.md` (0.13.1, commit `05cceee0`); `scripts/setup.ps1` clones tag `v0.13.1` |
| Licence | BSD-3-Clause (`LICENSE`) |
| Licence files | `LICENSE` (verbatim) |
| Distribution role | build-only: headers, nothing of it is compiled on its own or shipped |
| Selected features | Public headers only: the textual include closure (all preprocessor branches) of `tracy/Tracy.hpp`, `tracy/TracyD3D12.hpp` and `tracy/TracyVulkan.hpp`, the three headers the render core includes. `TRACY_ENABLE` stays undefined, so the macros compile to stubs; no `TracyClient.cpp` and no other client source is vendored or linked |
| Include directories | `thirdparty/tracy/public` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (26)

- `LICENSE` (1,618 bytes)
- `public/client/TracyCallstack.h` (926 bytes)
- `public/client/TracyCallstack.hpp` (3,702 bytes)
- `public/client/TracyFastVector.hpp` (2,673 bytes)
- `public/client/TracyKCore.hpp` (437 bytes)
- `public/client/TracyLock.hpp` (17,132 bytes)
- `public/client/TracyProfiler.hpp` (36,581 bytes)
- `public/client/TracyScoped.hpp` (7,154 bytes)
- `public/client/TracySysPower.hpp` (592 bytes)
- `public/client/TracySysTime.hpp` (435 bytes)
- `public/client/tracy_SPSCQueue.h` (4,954 bytes)
- `public/client/tracy_concurrentqueue.h` (54,120 bytes)
- `public/client/tracy_rpmalloc.hpp` (17,850 bytes)
- `public/common/TracyAlign.hpp` (394 bytes)
- `public/common/TracyAlloc.hpp` (1,186 bytes)
- `public/common/TracyApi.h` (352 bytes)
- `public/common/TracyColor.hpp` (17,206 bytes)
- `public/common/TracyForceInline.hpp` (465 bytes)
- `public/common/TracyMutex.hpp` (255 bytes)
- `public/common/TracyProtocol.hpp` (3,855 bytes)
- `public/common/TracyQueue.hpp` (23,476 bytes)
- `public/common/TracySystem.hpp` (754 bytes)
- `public/common/TracyWinFamily.hpp` (392 bytes)
- `public/tracy/Tracy.hpp` (15,041 bytes)
- `public/tracy/TracyD3D12.hpp` (21,566 bytes)
- `public/tracy/TracyVulkan.hpp` (31,673 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/tracy` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 77 |
| line-endings | 0 |
| different | 1 |
| uzengine-only | 1 |
| selected but absent from UzEngine's tree | 0 |

Differences and their causes:

- `public/tracy/TracyD3D12.hpp` (different): UzEngine committed the file with its patch `0001-fix-getdesc-abi-directx-headers.patch` applied: upstream lines 122 and 137 call `queue->GetDesc().Type`, UzEngine's call `queue->GetDesc(&queueDesc)` (out-parameter form). Not applied here: both lines are in the `#else` branch (lines 33-498) of `#ifndef TRACY_ENABLE` (line 4), which UzPainter's build never compiles because `TRACY_ENABLE` stays undefined; the upstream file is vendored and no modification entry is created
- `patches/0001-fix-getdesc-abi-directx-headers.patch` (uzengine-only): UzEngine's patch for `TracyD3D12.hpp` (see above); the build does not need it, so neither the patch nor its result is vendored

Identical files:

- `LICENSE`
- `public/TracyClient.cpp`
- `public/client/TracyAlloc.cpp`
- `public/client/TracyArmCpuTable.hpp`
- `public/client/TracyCallstack.cpp`
- `public/client/TracyCallstack.h`
- `public/client/TracyCallstack.hpp`
- `public/client/TracyCpuid.hpp`
- `public/client/TracyDebug.hpp`
- `public/client/TracyDxt1.cpp`
- `public/client/TracyDxt1.hpp`
- `public/client/TracyFastVector.hpp`
- `public/client/TracyKCore.cpp`
- `public/client/TracyKCore.hpp`
- `public/client/TracyLock.hpp`
- `public/client/TracyOverride.cpp`
- `public/client/TracyProfiler.cpp`
- `public/client/TracyProfiler.hpp`
- `public/client/TracyRingBuffer.hpp`
- `public/client/TracyRocprof.cpp`
- `public/client/TracyScoped.hpp`
- `public/client/TracyStringHelpers.hpp`
- `public/client/TracySysPower.cpp`
- `public/client/TracySysPower.hpp`
- `public/client/TracySysTime.cpp`
- `public/client/TracySysTime.hpp`
- `public/client/TracySysTrace.cpp`
- `public/client/TracySysTrace.hpp`
- `public/client/TracyThread.hpp`
- `public/client/tracy_SPSCQueue.h`
- `public/client/tracy_concurrentqueue.h`
- `public/client/tracy_rpmalloc.cpp`
- `public/client/tracy_rpmalloc.hpp`
- `public/common/TracyAlign.hpp`
- `public/common/TracyAlloc.hpp`
- `public/common/TracyApi.h`
- `public/common/TracyColor.hpp`
- `public/common/TracyForceInline.hpp`
- `public/common/TracyMutex.hpp`
- `public/common/TracyProtocol.hpp`
- `public/common/TracyQueue.hpp`
- `public/common/TracySocket.cpp`
- `public/common/TracySocket.hpp`
- `public/common/TracyStackFrames.cpp`
- `public/common/TracyStackFrames.hpp`
- `public/common/TracySystem.cpp`
- `public/common/TracySystem.hpp`
- `public/common/TracyVersion.hpp`
- `public/common/TracyWinFamily.hpp`
- `public/common/TracyYield.hpp`
- `public/common/tracy_lz4.cpp`
- `public/common/tracy_lz4.hpp`
- `public/common/tracy_lz4hc.cpp`
- `public/common/tracy_lz4hc.hpp`
- `public/libbacktrace/LICENSE`
- `public/libbacktrace/alloc.cpp`
- `public/libbacktrace/backtrace.hpp`
- `public/libbacktrace/config.h`
- `public/libbacktrace/dwarf.cpp`
- `public/libbacktrace/elf.cpp`
- `public/libbacktrace/fileline.cpp`
- `public/libbacktrace/filenames.hpp`
- `public/libbacktrace/internal.hpp`
- `public/libbacktrace/macho.cpp`
- `public/libbacktrace/mmapio.cpp`
- `public/libbacktrace/posix.cpp`
- `public/libbacktrace/sort.cpp`
- `public/libbacktrace/state.cpp`
- `public/tracy/Tracy.hpp`
- `public/tracy/TracyC.h`
- `public/tracy/TracyCUDA.hpp`
- `public/tracy/TracyD3D11.hpp`
- `public/tracy/TracyLua.hpp`
- `public/tracy/TracyMetal.hmm`
- `public/tracy/TracyOpenCL.hpp`
- `public/tracy/TracyOpenGL.hpp`
- `public/tracy/TracyVulkan.hpp`

UzEngine patches: `patches/0001-fix-getdesc-abi-directx-headers.patch`, not applied (cause above).
