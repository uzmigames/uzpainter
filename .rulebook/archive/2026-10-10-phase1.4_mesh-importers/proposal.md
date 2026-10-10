# Proposal: phase1.4_mesh-importers

## Why
The Assets3D pipeline delivers triangulated low-poly OBJ files with `usemtl` materials (and FBX/glTF on some pieces); UzPainter must import them into a corner-preserving `TexturingMesh` without re-triangulation, welding, normal recomputation or UV repacking, create one texture set per material in file order, and record units and identities explicitly (PRJ-01, PRJ-02, PRJ-07, INT-10, INT-12, INT-14). Implements D11 (decision 013) under owner answer Q8 (decision 021: zero dependency on UzEngine; UzPainter neither vendors nor calls UzEngine's cook path) in `docs/architecture/12-mesh-import.md`, with the normal convention and per-fragment frame settled by P0-NORMAL. Child of `phase1.7_mesh-loader` (P1-MESH), covering `docs/architecture/12-mesh-import.md` §1–§3, §6 and §8.

## What Changes
- `src/mesh/texturing_mesh.{h,cpp}`: `TexturingMesh {objects[], corners[] (position id, normal, uv0, tangent slot, material id), positions[], materials[], units {source, scale_to_internal}, hashes {positions, uvs, corner_normals, triangulation, materials}}`.
- `src/mesh/obj_parser.{h,cpp}`: own OBJ parser: `usemtl` → material/texture set; `o`/`g` → object names for geometry masks; negative indices; missing normals/UVs flagged; several UV sets (first used, others recorded).
- `src/mesh/fbx_import.{h,cpp}` over ufbx and `src/mesh/gltf_import.{h,cpp}` over fastgltf (each vendored from upstream under its own licence): all meshes, instances and transforms; FBX source units and V flip recorded, corner normals preserved; glTF `TEXCOORD_0`, stored `TANGENT` recorded (tangents regenerated).
- Contracts: already-triangulated input kept exactly; polygons triangulated by the documented fan rule from the first corner and flagged; Painter unit rule (`mesh_unit_scale` 0/None = file unit) with the effective scale recorded; material identity (name + index) separate from object identity; duplicate material names are an import error unless `allow_duplicate_material_names` merges them explicitly; one texture set per material in file order; image rows top-down with PNG order for `M_*.png`/`T_*.png`.
- Explicit refusals: UVs outside 0–1 fail import with the tile list (UV tiles are a release gap); `dae`, `ply`, `usd` are release gaps; `AutoUnwrapSettings` is recorded and rejected with `NotYetSupported`.

## Dependencies
- DAG inputs of the parent: `phase1.3_document-model` (texture-set creation, resource storage of the original bytes).
- Parent: `phase1.7_mesh-loader`. Siblings building on this child: `phase1.5_mesh-tangents-certificate`, `phase1.6_mesh-reload`.

## Acceptance
The `docs/architecture/12-mesh-import.md` §9 fixtures owned by this child pass: negative OBJ indices, n-gons, duplicate material names, instances/transforms, units, multi-set body; plus corner-hash preservation (PRJ-01), the directional orientation fixture (INT-12) and the Tier 0 quad-triangulation comparison with Painter.

## Impact
- Affected specs: `mesh`
- Affected code: `src/mesh/texturing_mesh.*`, `src/mesh/obj_parser.*`, `src/mesh/fbx_import.*`, `src/mesh/gltf_import.*`, `thirdparty/ufbx/`, `thirdparty/fastgltf/`, `tests/mesh/`
- Breaking change: NO
- User benefit: Meshes arrive exactly as authored, with every unit, identity and orientation decision recorded rather than guessed.
