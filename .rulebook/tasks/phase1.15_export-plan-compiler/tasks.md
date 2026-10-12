## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.14_compositor-core
  - Open: phase1.14 is merged on main, but its child phase1.12_compositor-height-normal is still closing on another branch (wt/phase1.12-close). The plan defers the combined normal's evaluator limits to the evaluator, so its lifts need no change here (decision 085).

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
- [ ] 3.5 Dry run lists exactly the files a real export then writes
  - Painter's side proven: dry run = Painter's written files on 165 Tier 0 export steps, 0 differing. Open: UzPainter's own written files need the phase1.16 writers and phase1.17 receipts (decision 085).
- [ ] 3.6 Tier 0 virtual-map goldens (`AO_Mixed`, `Normal_OpenGL`, `Normal_DirectX` and every other virtual map marked `supported`) exact
  - Normal_OpenGL/DirectX exact (40 maps, 72 comparisons). Open: AO_Mixed misses ao-mixed s1 (30 r1 values; Painter's r1/r2 disagree there); needs recording R-086a and its fit (decision 086).

## 4. Acceptance
- [ ] 4.1 Plan tests green on the hosted CPU lane; Tier 0 virtual-map goldens exact in a local run on the owner's machine (decision 028; the local run report is the evidence)
  - Plan tests green; open until 3.6 (R-086a) closes.

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
  - After merging main (63ad10f): tests/export 15 passed (Tier 0 cases included, local store), tests/toolchain 50 passed, tests/parity + tests/capabilities 967 passed; `zig build export-tests` and `zig build painter` clean with -Werror; ruff and mypy --strict clean.
