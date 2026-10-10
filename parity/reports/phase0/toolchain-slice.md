# P0-TOOLCHAIN acceptance — owner's machine run

Task `phase0.8_toolchain-slice`, the integration and acceptance task of P0-TOOLCHAIN (`docs/dag.md`; `docs/architecture/13-engine-integration.md` §4.2, §5, §7). Decision 028: GPU checks run locally on the owner's machine and this report is their evidence. Run on 2026-10-10 (selftest started 18:47:33 UTC) on the tree of commit `a0032e8` with the working-tree changes of that moment (none in `build.zig`, `build.zig.zon`, `src/` or `.rulebook/decisions/`). The children's reports hold the detail: `toolchain-hardware-slice.md`, `toolchain-probes.md`, `toolchain-cpython.md` (this folder).

**Result: P0-TOOLCHAIN accepted.** One build, one `selftest` run: DX12 hardware slice passed; all four probes completed and reported (WARP qualified); CPython boundary qualified directly. The clean-machine start is pending owner action (below); it is not part of the P0-TOOLCHAIN gate wording and the owner runs it himself.

## Gate

| Gate item (`docs/dag.md`) | Evidence of this run | Verdict |
|---|---|---|
| Hardware slice green on the owner's machine | `dx12-device`, `shader-compile`, `compute-readback`, `png16`, `embree` passed on the NVIDIA GeForce RTX 4090; `hardware_slice: passed` | met |
| WARP probe completed and reported (supported capabilities, executed checks, unsupported reasons); WARP failure does not fail G0 | `warp` completed, verdict qualified, 4 of 4 checks passed, no unsupported item; probe stages are not mandatory and not part of the slice, so no probe outcome can fail the run | met |
| CPython boundary qualified or fallback chosen | all five CPython stages passed through the direct route; the C-ABI fallback was not needed | met (direct) |

## Build

| Item | Value |
|---|---|
| Command | `zig build painter --prefix <work>\dist`, exit code 0 |
| Zig | 0.15.2 (pinned in `build.zig.zon` `minimum_zig_version`, refused otherwise by `build.zig`, pinned in `.github/workflows/parity.yml`); Debug build |
| `UzPainter.exe` | 12,675,072 bytes, SHA-256 `2DEDC5652FA7E2CE5B8918ACFC8B7C5302F17A61A37CC35421DF99DE7A09E95F` |
| Machine | Windows 11 25H2 (build 10.0.26200.9457), AMD Ryzen 9 7950X3D, NVIDIA GeForce RTX 4090 (driver 32.0.16.1714, Vulkan driver NVIDIA 617.14) |

## `UzPainter.exe selftest` (GPU run)

Exit code 0, `result: passed`, `hardware_slice: passed`.

| Stage | Mandatory | Hardware slice | Result | Facts |
|---|---|---|---|---|
| `dx12-device` | yes | yes | passed | D3D_FEATURE_LEVEL_12_2, SM6.9, Agility SDK 619 (`D3D12Core.dll` 1.619.2.0 from the folder) |
| `shader-compile` | yes | yes | passed | DXC 1.9 (1.9.2602.17), `cs_6_6`: 3528 bytes DXIL, 1632 bytes SPIR-V |
| `compute-readback` | yes | yes | passed | 100 x 64 R16_FLOAT, row pitch 256, 0 mismatches |
| `png16` | yes | yes | passed | GPU readback written by spng 0.7.4, decoded at 16 bits, 0 mismatches |
| `embree` | yes | yes | passed | Embree 4.4.1 (TBB), hit t 2.0, u 0.2, v 0.3 |
| `dx12-ray-query` | no | no | passed | completed, supported: DXR Tier 1.2, SM 6.9; 3/3 checks |
| `vulkan-availability` | no | no | passed | completed, available: loader 1.4.341, device Vulkan 1.4.351; 24/24 checks |
| `vulkan-ray-query` | no | no | passed | completed, supported: `VK_KHR_acceleration_structure`, `VK_KHR_deferred_host_operations`, `VK_KHR_ray_query`; 5/5 checks |
| `warp` | no | no | passed | completed, qualified on Microsoft Basic Render Driver 10.0.26100.9278 (feature level 12_1, SM 6.8); hosted WARP lane `dx12-device`, `shader-compile`, `compute-readback`, `png16` |
| `cpython-start` | yes | no | passed | `python313.dll` 3.13.16 from the folder; isolated, environment ignored, no user site |
| `cpython-uzpainter` | yes | no | passed | `uzpainter` built into `UzPainter.exe` |
| `cpython-buffer16` | yes | no | passed | 65536 16-bit values C++ to Python to C++, 0 mismatches |
| `cpython-exceptions` | yes | no | passed | Python to C++ and C++ to Python keep type and message; interpreter usable afterwards |
| `cpython-mcp-sdk` | yes | no | passed | `mcp` 2.3.0 from `Lib\site-packages`; in-process MCP tool call returned |

## Link map and DLL import closure

- `python -m tools.toolchain.link_map`: exit code 0. `uzrendercore.lib` (30 members), `c++.lib` (26) and `c++abi.lib` (15) linked statically; `UzPainter.exe` imports `python313.dll`, `d3d12.dll`, `dxgi.dll`, `VERSION.dll`, `ADVAPI32.dll`, `KERNEL32.dll`, `ntdll.dll`, `WINMM.dll`, `dbghelp.dll` and C-runtime API sets; no C++ runtime DLL.
- `python -m tools.toolchain.dll_closure <work>\dist\bin --clean-machine`: exit code 0, "allowlist and clean-machine closure check passed". 91 binaries, footprint 114,552,184 bytes, 121 distinct Windows system DLLs and API sets; every other import resolves inside the folder.

## Decision 021 and the toolchain

Zig is kept (`13-engine-integration.md` §4.2 step 2): the hardware slice passed under the pinned Zig and the CPython boundary passed directly, so no step 3 or step 4 condition arose. Decision 021 (`.rulebook/decisions/021-…md`) is unchanged: its only commit is `c503712` and the working tree does not modify it. No UzEngine build, path or artefact is involved.

## Hosted CI without a GPU (decision 028)

The same executable with `UZP_NO_GPU=1` (as `.github/workflows/parity.yml` sets for the hosted job): exit code 0, `result: passed`, `hardware_slice: skipped`. `dx12-device`, `compute-readback` and the four probe stages skipped with "no GPU: UZP_NO_GPU=1 (hosted CI has no GPU, decision 028; the hardware slice runs on the owner's machine)", the `probes` array is empty; `shader-compile`, `png16`, `embree` and all five CPython stages passed. A hosted run therefore checks the CPU half of the slice and the whole CPython boundary, and the GPU half is this report.

## Clean-machine start — pending owner action

The static closure is closed against a clean Windows, and copies of the folder start with the environment reduced to the Windows folders (children's reports). The start on a clean Windows 10/11 x64 machine without Python or the Visual C++ runtime installed is the owner's own test: **pending owner action**. It is not an agent item.

## Follow-ups recorded for the owner (not part of this gate)

- **No `longPathAware` manifest.** `UzPainter.exe` carries no application manifest at all, so its file APIs and the embedded interpreter's are limited to `MAX_PATH`; the install folder path may be at most 161 characters (`toolchain-cpython.md`, Path length). A deeper folder makes wheel files unreachable and `cpython-mcp-sdk` fails.
- **Two files of `thirdparty/vc-runtime/` are no longer installed.** `build.zig` installs `vcruntime140.dll` and `vcruntime140_1.dll` from `thirdparty/cpython/` (14.51.36247.0) instead of `thirdparty/vc-runtime/` (14.44.35211.0); only `msvcp140.dll` 14.44.35211.0 still comes from `thirdparty/vc-runtime/`. The 14.44 `vcruntime140*.dll` copies stay in the repository unused; nothing was deleted. (The closure table of `toolchain-hardware-slice.md` predates the CPython task and still shows the 14.44 sizes; this run and `toolchain-cpython.md` show the installed 14.51 files.) Whether to remove them, or to keep `thirdparty/vc-runtime/` as the single source of the runtime, is the owner's call (release blocker RB-VCRT-TERMS covers the runtime's terms either way).

## Reproduce

```
zig build painter --prefix <work>\dist
<work>\dist\bin\UzPainter.exe selftest --out-dir <work>\gpu
set UZP_NO_GPU=1 && <work>\dist\bin\UzPainter.exe selftest --out-dir <work>\nogpu
python -m tools.toolchain.link_map --work <work>\linkmap
python -m tools.toolchain.dll_closure <work>\dist\bin --clean-machine
python -m pytest tests/toolchain
```
