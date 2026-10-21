## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input), `phase3.4_smart-projections`; `phase1.7_mesh-loader` and `phase1.4_render-core-layer` delivered

## 2. Implementation
- [x] 2.1 Mesh import keeps every recorded UV set (OBJ, FBX, glTF `TEXCOORD_n`) as tile-indexed data, included in the mesh hashes and certificate
  - Note (2026-10-21): `TexturingMesh::uv_sets` holds every UV set after the first, one UV per corner, in uv0's tile-indexed space (FBX layers by name, glTF `TEXCOORD_n` by n with v flipped; an OBJ has one set). `hashes.secondary_uvs` and the certificate's `uv.secondary_sets` (name, corners without UV, tiles) appear only for more than one set, so single-UV hashes and certificates are unchanged. A report written before keeps re-deriving; a reload that moves only these sets reports `secondary_uvs` and leaves mesh maps valid. Evidence: `uzp-mesh-tests run` case `secondary_uv_sets`, `uzp-mesh-reload-tests run` case `secondary_uv_sets_reload`, `tests/mesh/test_mesh_import.py` `test_gltf_every_uv_set_kept`, `test_gltf_uv_set_missing_from_a_primitive`, `test_fbx_every_uv_set_kept` (CPU).
- [ ] 2.2 UV raster pass rasterises a source UV set into the target set's space
- [ ] 2.3 Record the Tier 0 warp and UV-set goldens through the UzmiGames recorder (twice; blobs private, hashes in `parity/manifests/`) and fit their semantics into `parity/semantics/projections.json`
- [ ] 2.4 `UVSetToUVSet` projection kernel with the documented parameters and the fitted filter
- [ ] 2.5 `Warp` projection kernel with the documented parameters, evaluated from the UV raster's position and normal maps
- [ ] 2.6 Mirror and radial symmetry for these modes where the documented parameters allow it; unproven combinations raise `NotYetSupported`
- [ ] 2.7 Both modes in `fill_set` for `uzpainter`, the facade and the MCP stack family with set→get readback; capability-manifest entries and operation-matrix conformance fixture

## 3. Tests
- [ ] 3.1 Tier 0 goldens: `UVSetToUVSet` from a second UV set on a UzmiGames-authored mesh, exact
- [ ] 3.2 Tier 0 goldens: `Warp` parameter sweeps on the plane, sphere and bevelled cube, exact
- [ ] 3.3 Tier 0 goldens: symmetry combined with these modes where documented, exact
- [ ] 3.4 Regression: Phase 1–3 projection goldens and mesh certificates of single-UV meshes unchanged
- [ ] 3.5 API probes: projection parameters set→get, save and reopen; unproven combinations raise before mutation
- [ ] 3.6 Python-disabled MCP conformance fixture for `fill_set` with both modes

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase4.2_remaining-nodes`: warp and UV-set Tier 0 goldens exact or excepted; manifest updated

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
