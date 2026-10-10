## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.3_document-model

## 2. Implementation
- [x] 2.1 Implement `TexturingMesh` with per-corner attributes and the five content hashes
- [x] 2.2 Implement the OBJ parser (`usemtl`, `o`/`g`, negative indices, missing normals/UVs flagged, extra UV sets recorded)
- [x] 2.3 Vendor ufbx and fastgltf from upstream with licence files and origin records; implement FBX and glTF/GLB import (all meshes, instances, transforms, units, V flip, `TEXCOORD_0`, stored tangents recorded)
- [x] 2.4 Implement the triangulation contract (exact for triangles, documented fan rule for polygons, flagged)
- [x] 2.5 Implement units (`mesh_unit_scale` rule, effective scale recorded) and material/object identity, including the duplicate-material-name error and `allow_duplicate_material_names`
- [x] 2.6 Create one texture set per material in file order through the document model, storing the original mesh bytes as a resource
- [x] 2.7 Implement the explicit refusals: UVs outside 0–1 with the tile list, `dae`/`ply`/`usd` as release gaps, `AutoUnwrapSettings` → `NotYetSupported`

## 3. Tests
- [x] 3.1 Corner preservation: a triangulated OBJ imports with corner hashes equal to the source (no re-triangulation, welding, normal recomputation or UV repacking)
- [x] 3.2 Negative OBJ indices fixture imports equal to its positive-index twin
- [x] 3.3 N-gon fixture: fan triangulation flagged; Tier 0 quad-triangulation comparison against Painter's result on the same quad mesh (local run on the owner's machine, private oracle, decision 028)
- [x] 3.4 Duplicate material names: import error by default; explicit merge with `allow_duplicate_material_names`
- [x] 3.5 Instances/transforms fixture (FBX and glTF): all instances present with their transforms
- [x] 3.6 Units fixture: centimetre and metre sources give the recorded effective scale
- [x] 3.7 Multi-set body fixture: three texture sets created in file order
- [x] 3.8 Directional orientation fixture (INT-12): an asymmetric mask PNG lands in the expected texels
- [x] 3.9 UVs outside 0–1 fail with the tile list; `dae` import and `AutoUnwrapSettings` raise their documented errors

## 4. Acceptance
- [x] 4.1 All tests of this child green (hosted CPU lane; the Tier 0 triangulation comparison in a local run on the owner's machine, decision 028, whose report is the evidence)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
