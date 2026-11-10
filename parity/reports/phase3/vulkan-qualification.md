# P3-VULKAN qualification report

Task `phase3.3_vulkan-backend-ray-tracing` item 3.5 (spec "Vulkan Acceptance Qualification Report"). Run 2026-11-10 on the owner's machine, with the native lock held for the whole batch and no other GPU test running. Numbers and hashes only: every Painter output stays in the private store.

**Verdict: pass.** The selftest is green on DX12 and on Vulkan. Ray-cast records are identical on DXR and Vulkan: 0 differing rays on every field of all four fixtures. The Tier 0 subset and the 15 pilot Tier 1 maps are byte-equal on DX12 and Vulkan. No DX12/Vulkan exception is relied on.

## 1. One build: commit, binaries, machine

"From one build" means one commit (coordinator's reading, 2026-11-10). The four fixtures build four different binaries, so each binary is built by its own fixture from the same commit and its SHA-256 is recorded here.

- Commit: `8bdbf185c4939c16862e2b6ffe6505f930752b31`. It was HEAD at the start of the batch and is the tree every binary was built from. Another agent committed `b54e2df86d1e6c52f78aa7d557b69c9357e56c02` during the Tier 1 run. It touches three rulebook files only (decision 428 and `phase3.3_procedural-families/tasks.md`), no native, render, build or Python package input, so nothing was re-run.
- Build inputs were clean at that commit: `git status` showed no change under `src/`, `thirdparty/`, `python/`, `tests/render/`, `tests/native/`, `build.zig` or `build.zig.zon`. The uncommitted files in the checkout were Python tests and tools, a rulebook README and parity request/report files of other tasks. None of them is compiled into a binary.

| Binary | Fixture (command) | Used by | SHA-256 |
|---|---|---|---|
| `UzPainter.exe` Debug | `tests/toolchain/conftest.py::painter_bin` (`zig build painter`) | selftest (§2) | `4d344e9da406f1fa1bf89b2e823211e5c63a9fcb6d16ee8c2d896b88170f3f9f` |
| `uzp-render-tests.exe` | `tests/render/conftest.py::render_tests` (`zig build render-tests`) | ray-cast (§3) | `238f98ea67536f6e4b0ab0c3eb7c38e216462054747194906193f0677ebf622b` |
| `uzp-export-tests.exe` | `tests/export/conftest.py::export_tests` (`zig build export-tests -j4`) | Tier 0 subset (§4) | `bc2b3f7d8eb5487e029c97f4bfd84a2f6f244eb3263c9a0d4e402fab6e6b0fa5` |
| `UzPainter.exe` ReleaseFast | `tests/parity/tier1/test_vulkan_tier1.py::painter` (`zig build painter -Doptimize=ReleaseFast`) | pilots (§5) | `db2aaebeb846299756bb2f83923e45c726e7ef95cdb793d4c63efba279a55e99` |

Machine: Windows build 10.0.26200.9711 (25H2), AMD Ryzen 9 7950X3D, Zig 0.15.2.

| Backend | Adapter | Driver |
|---|---|---|
| DX12 hardware (DXR Tier 1.1) | NVIDIA GeForce RTX 4090 | 32.0.16.1714 |
| Vulkan (with `VK_KHR_ray_query`) | NVIDIA GeForce RTX 4090 | NVIDIA 617.14 |
| DX12 WARP (probe only) | Microsoft Basic Render Driver | 10.0.26100.9711 |

The pilot reports list both adapters of the machine: `AMD Radeon(TM) Graphics | NVIDIA GeForce RTX 4090`, drivers `32.0.21042.62 | 32.0.16.1714`.

## 2. Selftest on both backends

`tests/toolchain/test_toolchain_gate.py::test_gate_on_the_owners_machine`: passed (50.7 s). The run used the Debug `UzPainter.exe` `4d344e9d…`, one process, report schema `uzpainter.selftest/1`. Results: `result` passed, `hardware_slice` passed, `vulkan_hardware_slice` passed, exit code 0.

| Group | Stage | Status | Mandatory | In hardware slice |
|---|---|---|---|---|
| DX12 hardware slice | `dx12-device`, `shader-compile`, `compute-readback`, `png16`, `embree` | passed (5/5) | yes | yes |
| Probes | `dx12-ray-query`, `vulkan-availability`, `vulkan-ray-query`, `warp` | passed (4/4) | no | no |
| Vulkan slice | `vulkan-device`, `vulkan-compute-readback`, `vulkan-png16`, `vulkan-ray-query-trace` | passed (4/4) | yes | no |
| CPython boundary | `cpython-start`, `cpython-uzpainter`, `cpython-buffer16`, `cpython-exceptions`, `cpython-mcp-sdk` | passed (5/5) | yes | no |

| Probe | Backend | Verdict | Executed checks | Unsupported items |
|---|---|---|---|---|
| `dx12-ray-query` | dx12 | supported | 3 | 0 |
| `vulkan-availability` | vulkan | available | 24 | 0 |
| `vulkan-ray-query` | vulkan | supported | 5 | 0 |
| `warp` | dx12-warp | qualified | 4 | 0 |

## 3. Ray-cast fixtures, DXR versus Vulkan

`tests/render/test_ray_query.py::test_ray_cast_fixtures_on_both_backends`: passed (5.5 s). The run used `uzp-render-tests.exe` `238f98ea…` and kernel SHA-256 `64a8331a3177098fec62b007d6420a8a53dcd11f1847ef00d53f3c50237a1b51`. The raw output (SHA-256 `403cff16926b4a3c54395a667fcc7ea8d75ed3707d0556b196f1e346b0d3921a`) was rebuilt with `python -m tools.parity.raycast`. The rebuilt report is byte-identical to the committed `parity/reports/phase3/ray-cast.json` (SHA-256 `e643600cc97cf6e209acabd6d1e91214aaaa1d4e515842f6b0bc7ccb41fd6c80`), so that file stands as this build's report. Adapter SHA-256: `e7d86226…` on both backends. Driver SHA-256: `0d4a9945…` (DX12), `6289d4f1…` (Vulkan).

| Fixture | Rays | DX12 repeatable, strict differing | Vulkan repeatable, strict differing | DX12 vs Vulkan differing rays (any field) |
|---|---|---|---|---|
| `plane` | 50 | yes, 0 | yes, 0 | 0 |
| `sphere` | 31 | yes, 0 | yes, 0 | 0 |
| `bevelled-cube` | 14 | yes, 0 | yes, 0 | 0 |
| `opacity-pair` | 9 | yes, 0 | yes, 0 | 0 |

The cross-backend fields compared per ray are hit, instance id, primitive id, geometry index, instance index, barycentrics and t. Every field has 0 differences, and the maximum delta of t and of the barycentrics is 0. Outcome: `pass`.

## 4. Tier 0 subset, DX12 versus Vulkan

`tests/export/test_vulkan_export_tier0.py`: 2 passed (1,156 s), on `uzp-export-tests.exe` `bc2b3f7d…`.

| Backend | Export steps | Maps per run | Runs (separate processes) | Exact Painter comparisons |
|---|---|---|---|---|
| dx12 | 40 | 80 | 2 | 148/148 |
| vulkan | 40 | 80 | 2 | 148/148 |

The steps come from three goldens: `semantics/height-normal-plane-amplitudes` (16 maps per run), `semantics-ui/height-normal-sharp-plane-strength` (32) and `semantics-ui/height-normal-sobel-plane-strength` (32). Each backend wrote 160 files. All 160 DX12/Vulkan pairs at the same path are byte-identical. The sorted SHA-256 listing is the same for both backends, and its own SHA-256 is `c2ad9233af8e779cd9a1a85fb61e9d5e2a25128cf98ceb023d4321600222e1ee`. The files have 41 distinct contents.

## 5. Pilot Tier 1 maps, DX12 versus Vulkan

`UZP_VULKAN_TIER1_REPORTS=parity/reports/phase3 pytest tests/parity/tier1/test_vulkan_tier1.py`: 6 passed (1,903 s), on the ReleaseFast `UzPainter.exe` `db2aaebe…`. Both DX12 and Vulkan used that one binary. The reports `tier1-<pilot>-vulkan.json` and `cross-backend-tier1-<pilot>.json` were rewritten by this run. Compared with the 2026-11-08 run, only the build hash, the bundle hashes and the project UUIDs changed. Every map SHA-256 is unchanged.

| Pilot | Tier 1 on Vulkan vs Painter | Exception relied on (Painter parity) | Cross-backend outcome | Maps `bytes_equal` | Differing values at native depth |
|---|---|---|---|---|---|
| Wand v1 | pass | EXC-010 v1 | pass | 5/5 | 0 of 37,748,736 |
| Belt v5 (Sash v5 current round) | pass | EXC-012 v1 | pass | 5/5 | 0 of 37,748,736 |
| Tunic v10 | pass | EXC-011 v3 | pass | 5/5 | 0 of 251,658,240 |

In each case the DX12-built project was saved, then exported on DX12 and, in a fresh process reopening the same file, on Vulkan. The DX12 and Vulkan runs have the same project revision: Wand 169, Sash 223, Tunic 241. Every file of both Vulkan Tier 1 rebuilds is byte-identical to the DX12 export (`test_vulkan_maps_byte_equal_dx12`).

## 6. Exceptions relied on

- **DX12 versus Vulkan (Tier 0, pilots, ray-cast): none.** `parity/exceptions.json` is unchanged, and every cross-backend comparison above is strict.
- **Painter parity of the Vulkan Tier 1 runs:** the three pilot exceptions that the DX12 Tier 1 runs already use, with unchanged terms. They are EXC-010 v1 (decision 395), EXC-012 v1 (decision 399) and EXC-011 v3 (decision 410). They cover each pilot's difference from Painter, not any backend difference.
