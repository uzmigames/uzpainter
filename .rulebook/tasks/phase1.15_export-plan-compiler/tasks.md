## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.14_compositor-core
  - Open: phase1.12_compositor-height-normal is archived (2026-10-11); phase1.14 and its child phase1.13 are closing on `wt/close-compositor`. The plan defers the combined normal's evaluator limits to the evaluator, so its lifts need no change here (decision 085).

## 2. Implementation
- [x] 2.1 Implement the verbatim parser of Painter's export configuration dictionary
- [x] 2.2 Implement wildcard expansion with optional groups, `srcMapType` resolution, filter semantics and the parameter resolution order
- [x] 2.3 Compile the typed plan (files, sources, parameters, sizes, names, target formats) with collision checks and a plan hash
- [x] 2.4 Reject unknown identifiers with valid alternatives and refuse unsupported or later-package formats before any write
- [x] 2.5 Implement virtual-map resolution: combined normals and geometry-only pass-through from the compositor, `AO_Mixed` and the other documented virtual maps with Tier 0-fitted operators; publish `parity/semantics/virtual-maps.json`
  - Normal_OpenGL/DirectX supported (exact); AO_Mixed and the ten converted maps release gaps refused before writing until recording R-086 (decision 086).
- [x] 2.6 Expose diagnostic sources to the plan and implement the dry run (`list_project_textures`, `uzpainter.export.plan`)
  - Native dry run (CompilePlan, PlanJson, ListProjectTextures); the Python binding is phase1.19 item 2.7 (decision 085 scope split).

## 3. Tests
- [x] 3.1 Naming tests (EXP-03): the patterns used by the pipeline presets expand correctly; two outputs resolving to one path are rejected
- [x] 3.2 Filter tests: `{}` selects all, `{"dataPaths": []}` selects nothing, `uvTiles` and `outputMaps` filters behave as documented
- [x] 3.3 Resolution-order test: `exportParameters` rules override preset parameters in list order; an unresolved parameter makes the config invalid
- [x] 3.4 `Mixed_AO` is rejected with `AO_Mixed` among the alternatives; requesting TIFF or TGA raises before any file exists
- [x] 3.5 Dry run lists exactly the files a real export then writes
  - Painter's side proven: dry run = Painter's written files on 165 Tier 0 export steps, and every R-085 probe compiles as Painter behaved (90 compilations, 6 refused as unrecorded, R-091; decision 091). UzPainter's side (decision 085): `WriteExport` writes exactly the dry run's files, with the sizes and SHA-256 it reports, in two processes (`tests/export/test_export_encoders.py::test_written_files_equal_the_dry_run_in_two_processes`, CPU, 1 passed 2026-10-12) and on the 40 export steps of phase1.16's Tier 0 goldens (`test_written_goldens_equal_painter_files`, phase1.16's local run); phase1.17's receipt lists the published files with their sizes and SHA-256 (`tests/export/test_export_publication.py::test_receipt_schema_and_fields`).
- [x] 3.6 Tier 0 virtual-map goldens (`AO_Mixed`, `Normal_OpenGL`, `Normal_DirectX` and every other virtual map marked `supported`) exact
  - Scope split (decision 131): Normal_OpenGL/DirectX, the maps marked supported, are exact (40 maps, 72 comparisons). AO_Mixed stays a release gap refused before writing (its best model misses r1 at 31 values of R-086a, decision 092); its exact fit moves to `phase3.2_unreal-ue56-packed-preset` item 2.10. Converted maps fitted but not marked supported (decision 092).

## 4. Acceptance
- [x] 4.1 Plan tests green on the hosted CPU lane; Tier 0 virtual-map goldens exact in a local run on the owner's machine (decision 028; the local run report is the evidence)
  - Plan tests green; the supported virtual maps' Tier 0 goldens exact (`parity/reports/phase1/export-plan-compiler.md` §3); AO_Mixed is the scope split of 3.6 (decision 131).

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
  - After merging main (63ad10f): tests/export 15 passed (Tier 0 cases included, local store), tests/toolchain 50 passed, tests/parity + tests/capabilities 967 passed; `zig build export-tests` and `zig build painter` clean with -Werror; ruff and mypy --strict clean.
