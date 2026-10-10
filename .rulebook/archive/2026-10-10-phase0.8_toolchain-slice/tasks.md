## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.5_vendor-render-core

## 2. Children
- [x] 2.1 Child accepted: phase0.6_toolchain-hardware-slice (`build.zig`, `selftest`, DX12 hardware slice, link map, DLL closure)
- [x] 2.2 Child accepted: phase0.7_toolchain-probes (Vulkan, ray-query and WARP probe reports)
- [x] 2.3 Child accepted: phase0.7_toolchain-cpython (CPython boundary qualified or C-ABI fallback chosen)

## 3. Integration tests
- [x] 3.1 Full `UzPainter.exe selftest` on the owner's machine from one build: hardware slice green, probe reports written, CPython checks green; result attached to the gate evidence
- [x] 3.2 Toolchain decision recorded per `13-engine-integration.md` §4.2: Zig kept, or the change and its failing selftest output recorded as an update to decision 021

## 4. Acceptance
- [x] 4.1 Acceptance gate (P0-TOOLCHAIN): hardware slice green on the owner's machine; WARP probe completed and reported (WARP failure leaves that path unsupported and does not fail G0); CPython boundary qualified or fallback chosen

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Evidence (2026-10-10, owner's machine: Windows 11 25H2, NVIDIA GeForce RTX 4090, Zig 0.15.2)
- 1.1, 2.1–2.3: `phase0.5_vendor-render-core` and the three children are archived (`.rulebook/archive/2026-10-10-*`) with every checklist item checked; their reports are `parity/reports/phase0/toolchain-hardware-slice.md`, `toolchain-probes.md`, `toolchain-cpython.md`.
- 3.1: `zig build painter` exit 0; one `UzPainter.exe selftest` of that build: exit 0, `result: passed`, `hardware_slice: passed`; 14 stages passed (5 slice, 4 probes all completed — WARP qualified on the Microsoft Basic Render Driver — and 5 CPython). Link map inspection and `dll_closure --clean-machine` (91 binaries, 114,552,184 bytes) passed. Evidence: `parity/reports/phase0/toolchain-slice.md`.
- 3.2: Zig kept (§4.2 step 2; CPython boundary passed directly, no fallback). Decision 021 unchanged (only commit `c503712`, no working-tree edit).
- 4.1: gate met; table in `toolchain-slice.md`. Hosted CI (decision 028): the same build under `UZP_NO_GPU=1` passes with GPU and probe stages skipped with the decision's reason, CPython stages passed.
- Pending owner action (not an agent item): clean-machine start on a clean Windows 10/11 x64. Follow-ups for the owner recorded in the report: no `longPathAware` manifest (install path at most 161 characters); `thirdparty/vc-runtime/` `vcruntime140*.dll` 14.44 no longer installed (CPython's 14.51 copies are), nothing deleted.
- Tests: `tests/toolchain/test_toolchain_gate.py` (gate on one build and one run; hosted lane under `UZP_NO_GPU=1`), 2 passed; under `UZP_NO_GPU=1`, 1 passed, 1 skipped with its reason. Quality gate: `python -m mypy` clean (138 files), `python -m ruff check .` clean, `python -m pytest` 746 passed, 1 failed — `tests/parity/fit/test_stability_and_publication.py::test_report_lists_every_published_fit_and_entry`, in `tools/parity/fit/`'s in-progress work owned by another agent, outside this task.
- Docs: `parity/reports/phase0/toolchain-slice.md`, `CHANGELOG.md`.
