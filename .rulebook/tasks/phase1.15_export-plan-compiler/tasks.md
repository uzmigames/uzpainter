## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.14_compositor-core

## 2. Implementation
- [ ] 2.1 Implement the verbatim parser of Painter's export configuration dictionary
- [ ] 2.2 Implement wildcard expansion with optional groups, `srcMapType` resolution, filter semantics and the parameter resolution order
- [ ] 2.3 Compile the typed plan (files, sources, parameters, sizes, names, target formats) with collision checks and a plan hash
- [ ] 2.4 Reject unknown identifiers with valid alternatives and refuse unsupported or later-package formats before any write
- [ ] 2.5 Implement virtual-map resolution: combined normals and geometry-only pass-through from the compositor, `AO_Mixed` and the other documented virtual maps with Tier 0-fitted operators; publish `parity/semantics/virtual-maps.json`
- [ ] 2.6 Expose diagnostic sources to the plan and implement the dry run (`list_project_textures`, `uzpainter.export.plan`)

## 3. Tests
- [ ] 3.1 Naming tests (EXP-03): the patterns used by the pipeline presets expand correctly; two outputs resolving to one path are rejected
- [ ] 3.2 Filter tests: `{}` selects all, `{"dataPaths": []}` selects nothing, `uvTiles` and `outputMaps` filters behave as documented
- [ ] 3.3 Resolution-order test: `exportParameters` rules override preset parameters in list order; an unresolved parameter makes the config invalid
- [ ] 3.4 `Mixed_AO` is rejected with `AO_Mixed` among the alternatives; requesting TIFF or TGA raises before any file exists
- [ ] 3.5 Dry run lists exactly the files a real export then writes
- [ ] 3.6 Tier 0 virtual-map goldens (`AO_Mixed`, `Normal_OpenGL`, `Normal_DirectX` and every other virtual map marked `supported`) exact

## 4. Acceptance
- [ ] 4.1 Plan tests green on the hosted CPU lane; Tier 0 virtual-map goldens exact on the self-hosted GPU runner

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
