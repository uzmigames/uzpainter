## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0_owner-decisions

## 2. Children
- [x] 2.1 Child accepted: phase0.1_vendor-core-copy (commit selection, export, `LICENSE`, `ORIGIN.md`, `MANIFEST.json`, `NOTICE` entry)
- [x] 2.2 Child accepted: phase0.2_vendor-thirdparty (third-party libraries from their own upstreams)
- [x] 2.3 Child accepted: phase0.3_vendor-modifications (UZP-MOD-001…006, `MODIFICATIONS.md`, static-library target)
- [x] 2.4 Child accepted: phase0.4_vendor-check (CI vendoring check)

## 3. Integration tests
- [x] 3.1 Clean build of the vendored static library with UzPainter's `build.zig` on a machine without any UzEngine checkout or artifact
- [x] 3.2 Build inspection: no include path, library path or build step refers outside the UzPainter repository; no `runtime.lib`, no submodule entry, no pin or patch-queue file
- [x] 3.3 Vendoring check green on the integrated tree

## 4. Acceptance
- [x] 4.1 Acceptance gate (P0-VENDOR): builds standalone in UzPainter's own build; no `runtime.lib`, no submodule, no engine path, no pin or patch queue

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Evidence (2026-10-10, owner's machine: Windows 11, NVIDIA GeForce RTX 4090, Zig 0.15.2)
- 1.1, 2.1–2.4: `phase0_owner-decisions` and the four children are archived (`.rulebook/archive/2026-10-10-*`) with every checklist item checked.
- 3.1: the package files of `build.zig.zon` `.paths` (`build.zig`, `build.zig.zon`, `thirdparty/`, `tests/native/`) copied to a folder outside the repository; `zig build render-core native-tests` there with empty `--cache-dir` and `--global-cache-dir`: exit 0, `uzrendercore.lib`, `uzp-vendor-tests.exe`, `dxcompiler.dll`, `dxil.dll`, `D3D12\D3D12Core.dll` produced (about 40 s). Zig's cache manifests list 209 distinct files at prefix 0 (absolute or build-root relative): all inside the copy; the rest are Zig's `lib` folder or the build's own caches; none in the UzPainter repository or a UzEngine checkout. The relocated `uzp-vendor-tests.exe` passes all native cases on the RTX 4090: `factory` 12, `fence dx12` 10, `fence vulkan` 9, `rayquery-decision` 7, `agility` 6, `spirv` 5 (49 PASS, 0 FAIL). Hosted CI (`.github/workflows/parity.yml`, `windows-latest`, no UzEngine) repeats the build on every push.
- 3.2: no `.gitmodules`, `runtime.lib`, `*.patch`/`*.diff` or patch-queue folder in the repository; `build.zig.zon` `.dependencies = .{}` (nothing fetched, nothing pinned); `build.zig` names files only through `b.path`, no absolute or `..` path, no `cwd_relative`, system include or library path; `ORIGIN.md` records the UzEngine commit for attribution only.
- 3.3: `python -m tools.vendoring.vendor_check` exit 0 ("97 vendored files; build paths checked").
- Tests: `tests/vendoring/test_render_core_integration.py` (6 tests: relocated build artefacts, cache-manifest dependency scan, relocated adapter run, no submodule/runtime.lib/patch queue, no package dependency, build-script paths). Quality gate: `python -m mypy` clean (57 files), `python -m ruff check .` clean, `python -m pytest` 337 passed, 0 skipped.
- Docs: `docs/architecture/13-engine-integration.md` §4.2 (acceptance check described), `CHANGELOG.md`.
