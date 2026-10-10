# Python Embedding and Packaging for Windows .exe

Research compiled 2026-10-09.

## Option Comparison

| Option | What It Is | Pros | Cons | License | Key Source |
|--------|-----------|------|------|---------|-----------|
| **CPython Embeddable Package** | Official Python distribution from python.org; single-folder, no installer needed. Configure via `python3xx._pth` to add site-packages and enable pip. | Zero setup; no registry pollution; redistributable as-is; smaller than full Python (~30-50 MB for Python 3.13); `python3xx._pth` configures stdlib + site-packages paths; pip works after uncommenting `import site`. | Older Python versions (pre-3.11) auto-imported site; Python 3.11+ requires explicit `import site` in .pth file, complicating `pip install`; docs say .pth file handling is fragile if formatting wrong. | **Fact**: Python Software Foundation License (PSF), permissive open-source. [Source](https://www.python.org/downloads/windows/?Windows+embeddable+package=) | [python.org embeddable download](https://www.python.org/downloads/windows/?Windows+embeddable+package=) |
| **pybind11 Embedding** | C++ binding library that includes C API for embedding CPython; provides GIL management, subinterpreter support (Python 3.12+, each with own GIL), free-threading support (Python 3.13+). | Full C++ interop; calling Python from C++ and vice versa; **Fact**: Python 3.12+ supports subinterpreters with separate GILs, enabling true concurrency in threads [source](https://pybind11.readthedocs.io/en/stable/advanced/embedding.html); battle-tested in production. | Larger binary footprint than minimal embedding; steep learning curve for GIL / subinterpreter setup; not designed for bundling .exe. | **Fact**: BSD 3-Clause License. [Source](https://github.com/pybind11/pybind11) | [pybind11 Embedding Docs](https://pybind11.readthedocs.io/en/stable/advanced/embedding.html) |
| **nanobind** | Faster, leaner successor to pybind11 (v0.7+, 2024); optimizes C++ wrapping and GIL handling (releases GIL by default for pure C++ functions). | Smaller binary; faster compilation; **Hypothesis** (not confirmed): better multi-core scalability via localized locking vs global GIL. | **Fact**: Does NOT support Python embedding (intentionally out-of-scope per design) [source](https://github.com/wjakob/nanobind/discussions/302); limits use to C++ wrapping only, not hosting Python. | **Fact**: BSD 3-Clause License. [Source](https://github.com/wjakob/nanobind) | [nanobind GitHub discussions](https://github.com/wjakob/nanobind/discussions/302) |
| **PyInstaller (with C++ extension)** | Freezes Python app + dependencies + CPython runtime into single .exe; can bundle native DLLs. Uses --onefile flag to collapse tree into monolithic binary; alternative to embedding. | Simplest for pure Python scripts; automatic dependency discovery; redistributable single .exe; avoids embedding complexity. | For C++ extensions: must configure .spec file to include compiled .pyd DLLs; PyInstaller detects MSVC DLLs automatically but custom binaries need manual inclusion; no in-process C++ compilation; typical .exe size 50-100 MB (vs ~10-30 MB for embedded CPython + minimal DLLs). | **Fact**: PyInstaller under GPL v2 + PyInstaller Exception (permissive for frozen apps). [Source](https://github.com/pyinstaller/pyinstaller) | [PyInstaller Docs](https://pyinstaller.org/en/stable/operating-mode.html) |
| **Substance Painter Model** | Adobe ships Python 3.13 at `<install>/resources/pythonsdk/python.exe`; app loads Python via C++ embedding, exposing `substance_painter` module for scripting. | Proven in production (Substance Painter 12.x); clean separation of app-level Python API; Python 3.13 support confirmed. | Proprietary approach; no public documentation on embedding strategy; API surface designed for Painter-specific tasks (not generic); unclear how to adapt for different renderer (UzEngine). | **Fact**: Substance Painter 12.x bundles Python 3.13. [Source](https://experienceleague.adobe.com/en/docs/substance-3d-dev/painter-python/api/api-overview) | [Substance Painter Python SDK](https://experienceleague.adobe.com/en/docs/substance-3d-dev/painter-python/api/module-index) |

## Trade-Off Summary

**Packaging Strategy:**
- **Smallest footprint, no external runtime:** CPython Embeddable (~30–50 MB base) + pip + wheels in a single folder, distributed as-is (no .exe wrapper). Requires user to run `python.exe` from bundle or wrap in batch script.
- **Single .exe, moderate size:** PyInstaller --onefile (~70–120 MB); simplest for reaching end-users but slower startup (decompresses on launch).
- **Single .exe, smallest compiled size:** pybind11 embedding (~20–40 MB C++ binary + bundled CPython 3.13) with static linking; most control over initialization but steepest learning curve for threading/GIL.

**Python API Exposure (for UzPainter scripting):**
- **In-process, C++ calling Python:** Embed CPython via pybind11; write Python plugins that inherit a module (e.g., `uzpainter.*`) exposed by C++ core. Fastest, no IPC overhead.
- **Out-of-process, subprocess:** Bundle Python, spawn as child; communicate via stdin/stdout (MCP-compatible) or sockets. Decouples app from Python crashes; enables Python-only tooling but adds latency.

**GIL and Concurrency (for long bakes):**
- Python 3.13+ free-threading mode (PEP 703) removes GIL entirely if PyInstaller / pybind11 compiled with `Py_NOGIL`; requires explicit build flag.
- Python 3.12+ subinterpreters (each with own GIL) allow true per-thread concurrency via pybind11; see [pybind11 2.13.0 release notes](https://github.com/pybind11/pybind11/releases/tag/v2.13.0).

**Hypothesis to Confirm in Next Phase:**
- Substance Painter's python313 at `resources/pythonsdk` is embedded via Windows C API, not a separate process. Confirm by inspecting Painter binary's imports or reverse-engineering a minimal API doc.
- PyInstaller's --onefile on Windows uses runtime decompression to %TEMP% (adds 1-2s startup); acceptable for a tool, not for interactive renders.

**Recommendation Route (facts only):**
1. CPython Embeddable + pybind11 embedding for tightest control + smallest .exe.
2. PyInstaller --onefile if team has limited C++ experience; Python 3.13 GIL-free mode gains back threading performance.
3. Avoid nanobind for this use case (no embedding support).

## Sources
- [CPython Embeddable Package Configuration](https://bnikolic.co.uk/blog/python/2022/03/14/python-embedwin.html)
- [Python 3.11+ Import Site Issue](https://github.com/python/cpython/issues/102169)
- [pybind11 Embedding and GIL](https://pybind11.readthedocs.io/en/stable/advanced/embedding.html)
- [pybind11 v2.13.0 Subinterpreter Support](https://github.com/pybind11/pybind11/releases/tag/v2.13.0)
- [nanobind Design Rationale](https://github.com/wjakob/nanobind/discussions/302)
- [PyInstaller --onefile Documentation](https://pyinstaller.org/en/stable/operating-mode.html)
- [Substance Painter Python 3.13 API](https://experienceleague.adobe.com/en/docs/substance-3d-dev/painter-python/api/api-overview)
- [Python Software Foundation License](https://www.python.org/psf/)
