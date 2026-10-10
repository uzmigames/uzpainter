# Proposal: phase0.7_toolchain-cpython

## Why
UzPainter embeds CPython 3.13 (Painter 12.1 ships 3.13.9): the worker hosts the `substance_painter` facade and `run` scripts over the pybind11 `uzpainter` module, and the supervisor runs the official Python MCP SDK from a private, vendored site-packages (`docs/architecture/10-python-api.md` §1, `11-mcp-server.md`, `02-runtime-topology.md` §1). PRD ARC-08 requires Phase 0 qualification of the CPython boundary with a documented fallback, and the toolchain decision procedure of `13-engine-integration.md` §4.2 keeps Zig only if this boundary works directly or through the C-ABI fallback; otherwise the toolchain changes on recorded evidence. The P0-TOOLCHAIN gate states "CPython boundary qualified or fallback chosen" (`docs/dag.md`). The MCP SDK wheel closure is also an unconfirmed licence entry until the wheels are pinned with licence, notices and hash (`docs/licensing-and-clean-room.md` §3; LIC-02). Child of `phase0.8_toolchain-slice` (implements D12, D1).

## What Changes
- Vendored CPython 3.13 embeddable package (`python313.dll`, `python313.zip`, `vcruntime140.dll`, `vcruntime140_1.dll`) at a pinned 3.13.x release, plus the headers and import library of the same release from the official CPython distribution, with licence/notices and `ORIGIN.md`; pybind11 (BSD-3-Clause) vendored the same way.
- Embedding in `UzPainter.exe`: interpreter isolated from any user Python (`._pth` restricting the path to `python313.zip` and `Lib\site-packages\`; environment variables and user site ignored); the `uzpainter` pybind11 module statically linked and registered as a built-in module.
- `Lib\site-packages\` with the pinned official MCP SDK wheel closure (pydantic and its native core, anyio, httpx and the rest, each for `cp313-win_amd64` where native), with licence, notices and SHA-256 per wheel recorded in the dependency inventory.
- `selftest` CPython stages (on the harness of `phase0.6_toolchain-hardware-slice`): embed `python313.dll`; import the statically linked `uzpainter` module; round-trip a 16-bit buffer between C++ and Python through the buffer protocol byte for byte; raise a Python exception caught in C++ with type and message, and a C++ exception surfacing in Python as the mapped Python exception; import the vendored MCP SDK.
- Decision procedure of `13-…` §4.2: if a stage fails, build the Python-facing layer as a separate DLL with a C ABI to the core and rerun under the same Zig; a toolchain change (clang-cl or MSVC with a UzPainter-owned CMake build) only on recorded evidence that the boundary fails both directly and through the fallback, or that `python313.dll` cannot be loaded or used from a Zig-built executable — that change updates decision 021 and therefore waits for the owner.
- DLL import closure rerun with the CPython binaries and native wheels; owner's-machine run published as `parity/reports/phase0/toolchain-cpython.md` (versions, per-stage result, chosen route: direct, C-ABI fallback, or recorded evidence for a toolchain change).

## Dependencies
- Prerequisites: `phase0.5_vendor-render-core` (P0-VENDOR), `phase0.6_toolchain-hardware-slice` (executable, `selftest` harness, DLL-closure tool).
- Parent: `phase0.8_toolchain-slice` (P0-TOOLCHAIN) closes only when this child passes.
- Successors: `phase1.24_python-api-facade` (P1-PYAPI builds on the qualified boundary), `phase2.8_mcp-server` (P2-MCP runs the vendored SDK), `phase5.2_packaging` (wheel closure in the release inventory).

## Acceptance
The CPython stages of `selftest` pass on the owner's machine either directly or through the C-ABI fallback under the pinned Zig, and the chosen route is recorded; or, if both fail, the failing `selftest` output is recorded and the toolchain change is put to the owner as an update of decision 021. The MCP SDK wheel closure is pinned with licence, notices and hash per wheel. Contributes to the P0-TOOLCHAIN gate "CPython boundary qualified or fallback chosen" (`docs/dag.md`).

## Impact
- Affected specs: build
- Affected code: `thirdparty/cpython/`, `thirdparty/pybind11/`, embedding code in `UzPainter.exe`, `Lib\site-packages\` wheel lock, `selftest` CPython stages, `parity/reports/phase0/toolchain-cpython.md`
- Breaking change: NO
- User benefit: the Python API, facade and MCP server rest on an embedding route proven on the target toolchain, isolated from any Python installed on the machine
