## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.4_render-core-layer, phase2.10_pilot-tunic-recovery
  - Both archived (2026-11-10 check): `.rulebook/archive/2026-10-10-phase1.4_render-core-layer/`, `.rulebook/archive/2026-11-05-phase2.10_pilot-tunic-recovery/`.

## 2. Child tasks (mandatory)
- [x] 2.1 phase3.1_vulkan-compute-parity accepted
  - Archived as `.rulebook/archive/2026-11-08-phase3.1_vulkan-compute-parity/`. Its 4.1 held on 2026-11-08: the selftest Vulkan compute stages are mandatory (commit fc2598d0); no Vulkan case is `pending` in the settling reports; the Tier 0 subset and the three pilots are byte-equal on Vulkan and DX12; no exception is relied on.
- [x] 2.2 phase3.2_vulkan-ray-tracing accepted
  - Archived as `.rulebook/archive/2026-11-09-phase3.2_vulkan-ray-tracing/`. Its 4.1 held on 2026-11-09: 0 differing rays on every field of every ray-cast fixture (`parity/reports/phase3/ray-cast.json`); the ray-query stage is mandatory (decision 421); no exception.

## 3. Integration
- [x] 3.1 Run `selftest` on the owner's machine with both backends: DX12 slice, Vulkan hardware slice and Vulkan ray-query slice green; availability probes reported separately
  - Joined from phase3.2 item 5.3 (2026-11-09, RTX 4090, native lock held). `tests/toolchain/test_toolchain_gate.py::test_gate_on_the_owners_machine` ran one build in one run: the DX12 hardware slice passed; every probe completed and was reported apart from the slices; the Vulkan compute and ray-query stages passed as mandatory. `test_selftest.py::test_vulkan_hardware_slice_green` and `::test_vulkan_ray_query_slice_green` passed in the same run set.
- [x] 3.2 Run the Tier 0 subset and the Wand v1, Belt v5 and Tunic v10 Tier 1 exports on DX12 and Vulkan from the same build; confirm byte equality of every decoded map
  - Joined from phase3.1 items 3.5 and 3.6.
  - Tier 0 subset (2026-10-23, `tests/export/test_vulkan_export_tier0.py`): each backend ran 40 export steps (80 maps), with 148/148 exact Painter comparisons. All 160 DX12/Vulkan file pairs are byte-identical.
  - Pilots (2026-11-08, `tests/parity/tier1/test_vulkan_tier1.py`, one ReleaseFast `UzPainter.exe`, SHA-256 `9c22d451e333…`): the saved DX12-built project was exported on DX12 and on Vulkan. All 15 maps are `bytes_equal`, with 0 differing values at native depth (`parity/reports/phase3/cross-backend-tier1-{wand-v1,sash-v5,tunic-v10}.json`, outcome `pass`). Every file of the Vulkan Tier 1 rebuilds is byte-identical to the DX12 export. Belt v5 is the Sash v5 current round (decisions 260, 399).
- [x] 3.3 Run the ray-cast fixtures on DXR and Vulkan from the same build; collect every per-ray difference
  - Joined from phase3.2 items 3.4 and 4.1. `parity/reports/phase3/ray-cast.json` covers four fixtures: plane 50 rays, sphere 31, bevelled cube 14, opacity pair 9, with one run per backend. It has 0 differing rays on every field, and every fixture repeats on each backend. Re-run green on 2026-11-09 (`test_ray_cast_fixtures_on_both_backends`, `test_committed_ray_cast_report_is_valid`).
- [x] 3.4 Propose an exception entry for each remaining divergence (domain backend pair, metric, bound, evidence, defect-detection test); none counts until the owner approves it
  - No divergence remains (3.2, 3.3), so no entry is proposed and `parity/exceptions.json` is unchanged. Decision 317's subnormal finding is GPU versus CPU, not DX12 versus Vulkan: both GPU backends flush subnormal float32 operands that the CPU reference keeps.
- [ ] 3.5 Publish the P3-VULKAN qualification report under `parity/reports/phase3/` (numbers and hashes only; build hash, adapter, driver; exceptions relied on listed)
  - Open (2026-11-10). The spec (Vulkan Acceptance Qualification Report) asks for the selftest, Tier 0, pilot and ray-cast results **from one build**. The joined evidence spans several trees:
    - Tier 0 subset: 2026-10-23.
    - Pilots: `9c22d451e333…`, 2026-11-08.
    - Ray-cast report: 2026-11-02, re-run 2026-11-09.
    - Selftest: 2026-11-09.
  - Native code has changed since then (decision 421 bindless, generator kernels). The ray-cast report and the selftest record no build hash.
  - Blocker: one GPU batch on a single commit, with no other GPU run going:
    - `tests/toolchain/test_toolchain_gate.py::test_gate_on_the_owners_machine`
    - `tests/render/test_ray_query.py::test_ray_cast_fixtures_on_both_backends`
    - `tests/export/test_vulkan_export_tier0.py` (DX12 about 576 s, Vulkan about 692 s)
    - `UZP_VULKAN_TIER1_REPORTS=parity/reports/phase3 pytest tests/parity/tier1/test_vulkan_tier1.py` (Tunic alone about 1,300 s)
  - Commands over 10 minutes belong to the coordinator's batch (CLAUDE.md test-time budget). The fixtures build different binaries (Debug `painter`, `uzp-render-tests`, ReleaseFast `painter`), so "one build" can only mean one commit. Whether that reading is intended is the coordinator's call; it is not settled here. The report is assembled from that batch's outputs.
- [x] 3.6 Regenerate the capability manifest with the Vulkan backend and Vulkan ray-query entries `supported` or listed as release gaps
  - Regenerated 2026-11-10 from main with `python -m tools.capabilities.generate_capabilities`: 1,658 entries, schema-valid, output SHA-256 `5d5c0a781ea6…`. The output is a scratch file and is not committed (`zig build painter` ships the manifest). No input changed.
  - Vulkan backend: `substance_painter.export.export_project_textures` and `uzpainter.export.export_project_textures` @ `backend:vulkan` are `supported`. Their tier evidence is `tier0/api-probes/active-channel-order-control`, with the narrow scope given in the notes (phase3.1 item 2.10).
  - Vulkan ray queries: `uzpainter.render.capture` @ `mode:painter_iray:backend:vulkan` is a `release-gap`. The ray-query prerequisite is qualified but the path tracer does not exist yet (phase3.2 item 2.13, decision 421).

## 4. Acceptance
- [ ] 4.1 Acceptance: Vulkan selftest hardware slice green; Tier 0 subset and pilot Tier 1 maps byte-equal on Vulkan and DX12; ray-cast fixtures compared with DXR with every difference reported; every divergence an owner-approved exception; both children accepted
  - Open on 3.5 only (2026-11-10). Every criterion holds on the joined evidence (2.1, 2.2, 3.1-3.4), but the one-build qualification report the spec requires is not published. The tail (5.1-5.3) waits for the same batch.

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
