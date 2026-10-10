## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.5_vendor-render-core, phase0.6_toolchain-hardware-slice

## 2. Implementation
- [ ] 2.1 Vendor the CPython 3.13 embeddable package at a pinned 3.13.x release, the headers and import library of the same release, and pybind11, each with licence, notices and `ORIGIN.md`
- [ ] 2.2 Embed the interpreter in `UzPainter.exe`, isolated from any user Python (`._pth` path to `python313.zip` and `Lib\site-packages\`; environment variables and user site ignored)
- [ ] 2.3 Statically link the `uzpainter` pybind11 module and register it as a built-in module
- [ ] 2.4 Pin the official MCP SDK wheel closure for `cp313-win_amd64` into `Lib\site-packages\`; record licence, notices and SHA-256 per wheel in the dependency inventory
- [ ] 2.5 `selftest` stage: start the embedded interpreter and import `uzpainter`
- [ ] 2.6 `selftest` stage: round-trip a 16-bit buffer between C++ and Python through the buffer protocol and compare byte for byte
- [ ] 2.7 `selftest` stage: raise a Python exception and catch it in C++ with type and message; throw a C++ exception from a bound function and catch the mapped Python exception in Python
- [ ] 2.8 `selftest` stage: import the vendored MCP SDK (including its native wheels) in the embedded interpreter
- [ ] 2.9 On any failing stage: build the Python-facing layer as a separate DLL with a C ABI to the core under the same Zig and rerun the stages
- [ ] 2.10 If the stages fail both directly and through the fallback, or `python313.dll` cannot be used from a Zig-built executable: record the failing `selftest` output and raise the toolchain change to the owner as an update of decision 021 (`rulebook_task` ask) before switching toolchains
- [ ] 2.11 Rerun the DLL import closure with the CPython binaries and native wheels; publish `parity/reports/phase0/toolchain-cpython.md` with versions, per-stage results and the chosen route

## 3. Tests
- [ ] 3.1 CPython stages pass on the owner's machine (direct or fallback route) and on a clean Windows 10/11 x64 machine without a Python installation
- [ ] 3.2 Isolation test: with `PYTHONPATH` and a user site-packages pointing to a conflicting module, the embedded interpreter still imports only the vendored modules
- [ ] 3.3 Buffer test: every 16-bit value 0…65535 survives the round trip unchanged
- [ ] 3.4 Exception test: both directions preserve exception type and message, and the interpreter stays usable afterwards
- [ ] 3.5 Inventory test: every wheel in `Lib\site-packages\` has a recorded licence, notice and SHA-256 matching the file

## 4. Acceptance
- [ ] 4.1 Child acceptance (contributes to P0-TOOLCHAIN): CPython boundary qualified directly or through the C-ABI fallback with the route recorded, or the failing evidence recorded and the toolchain change put to the owner; MCP SDK wheel closure pinned and inventoried

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
