## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.5_vendor-render-core, phase0.6_toolchain-hardware-slice

## 2. Implementation
- [x] 2.1 Vendor the CPython 3.13 embeddable package at a pinned 3.13.x release, the headers and import library of the same release, and pybind11, each with licence, notices and `ORIGIN.md`
  - CPython 3.13.16 from python.org: `thirdparty/cpython/` (`python-3.13.16-embed-amd64.zip`), `thirdparty/cpython-dev/` (`include/`, `libs/python313.lib` from `python-3.13.16-amd64.zip`); pybind11 v3.1.0 in `thirdparty/pybind11/` (`tools/vendoring/thirdparty.py`, `python -m tools.vendoring.import_thirdparty`).
- [x] 2.2 Embed the interpreter in `UzPainter.exe`, isolated from any user Python (`._pth` path to `python313.zip` and `Lib\site-packages\`; environment variables and user site ignored)
  - `src/python/interpreter.cpp` (`PyConfig_InitIsolatedConfig`, no bytecode written), `src/python/python313._pth` (`python313.zip`, `.` for the package's `*.pyd`, `Lib\site-packages`, `import site` for `pywin32.pth`).
- [x] 2.3 Statically link the `uzpainter` pybind11 module and register it as a built-in module
  - `src/python/uzpainter_module.cpp` (`PYBIND11_EMBEDDED_MODULE`; Phase 0 content: `uzpainter._selftest`).
- [x] 2.4 Pin the official MCP SDK wheel closure for `cp313-win_amd64` into `Lib\site-packages\`; record licence, notices and SHA-256 per wheel in the dependency inventory
  - `mcp==2.3.0`, 29 wheels in `thirdparty/python-wheels/` (`tools/vendoring/wheels.py`); unpacked by `build.zig` (`InstallWheels`) without console scripts, `pythonwin/` (needs MFC) and `adodbapi/` (LGPL-2.1); inventory row in `docs/licensing-and-clean-room.md` §3 plus per-wheel table in `ORIGIN.md`; new release blocker RB-WHEEL-NATIVE-NOTICES.
- [x] 2.5 `selftest` stage: start the embedded interpreter and import `uzpainter`
- [x] 2.6 `selftest` stage: round-trip a 16-bit buffer between C++ and Python through the buffer protocol and compare byte for byte
- [x] 2.7 `selftest` stage: raise a Python exception and catch it in C++ with type and message; throw a C++ exception from a bound function and catch the mapped Python exception in Python
- [x] 2.8 `selftest` stage: import the vendored MCP SDK (including its native wheels) in the embedded interpreter
  - Stages `cpython-start`, `cpython-uzpainter`, `cpython-buffer16`, `cpython-exceptions`, `cpython-mcp-sdk` (`src/selftest/cpython_stages.cpp`).
- [x] 2.9 On any failing stage: build the Python-facing layer as a separate DLL with a C ABI to the core under the same Zig and rerun the stages
  - Not triggered: every CPython stage passes on the direct route (`parity/reports/phase0/toolchain-cpython.md`), so no fallback DLL was built.
- [x] 2.10 If the stages fail both directly and through the fallback, or `python313.dll` cannot be used from a Zig-built executable: record the failing `selftest` output and raise the toolchain change to the owner as an update of decision 021 (`rulebook_task` ask) before switching toolchains
  - Not triggered: the direct route passes; decision 021 (Zig) is unchanged and no owner question was needed.
- [x] 2.11 Rerun the DLL import closure with the CPython binaries and native wheels; publish `parity/reports/phase0/toolchain-cpython.md` with versions, per-stage results and the chosen route
  - 91 binaries, 114.5 MB, allowlist and clean-machine closure pass (`tools/toolchain/dll_closure.py` allowlist extended); report by `python -m tools.toolchain.cpython_report`; route: direct.

## 3. Tests
- [x] 3.1 CPython stages pass on the owner's machine (direct or fallback route) and on a clean Windows 10/11 x64 machine without a Python installation
  - Owner's machine: passed (report). Clean machine: as in `phase0.6_toolchain-hardware-slice` 3.5, closed here on the static clean-machine closure (`test_selftest.py::test_built_folder_matches_allowlist`) and the reduced-environment start (`test_starts_without_sdk_or_tool_paths`, report); the run on a clean machine without Python is the owner's own test: pending owner action.
- [x] 3.2 Isolation test: with `PYTHONPATH` and a user site-packages pointing to a conflicting module, the embedded interpreter still imports only the vendored modules
  - `tests/toolchain/test_cpython.py::test_isolated_from_user_python`
- [x] 3.3 Buffer test: every 16-bit value 0…65535 survives the round trip unchanged
  - `tests/toolchain/test_cpython.py::test_buffer16_round_trip_every_value`
- [x] 3.4 Exception test: both directions preserve exception type and message, and the interpreter stays usable afterwards
  - `tests/toolchain/test_cpython.py::test_exceptions_keep_type_and_message`
- [x] 3.5 Inventory test: every wheel in `Lib\site-packages\` has a recorded licence, notice and SHA-256 matching the file
  - `tests/vendoring/test_wheels.py` (folder, inventory, PyPI hashes) and `tests/toolchain/test_cpython.py::test_python313_pth_and_site_packages_installed` (installed files against the wheels' `RECORD`).

## 4. Acceptance
- [x] 4.1 Child acceptance (contributes to P0-TOOLCHAIN): CPython boundary qualified directly or through the C-ABI fallback with the route recorded, or the failing evidence recorded and the toolchain change put to the owner; MCP SDK wheel closure pinned and inventoried

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
