# 12 — Mesh import and texture sets

Implements D11 (`05-resolution.md`) under owner answer Q8 (decision 021: zero dependency on UzEngine). Requirements: PRJ-01, PRJ-02, PRJ-04, PRJ-07, PRJ-08, PRJ-09, PRJ-10, INT-10, INT-12, QG-02 (`docs/prd.md`). Engine facts: `docs/analysis/uzengine-renderer/05-mesh-import.md`, `10-review-response.md` (§4.2 stride defect, §7 FBX normal recomputation).

## 1. Scope

UzPainter imports meshes with its own raw loader into a corner-preserving `TexturingMesh`; it neither vendors nor calls UzEngine's cook path (`.uzmesh`/UZMS/UZMH; `13-engine-integration.md` §2), which selects the first mesh only, runs LOD/SDF work, recomputes FBX normals by default (`r.Mesh.NormalImportMode = 1`) and has a confirmed 32/48-byte stride defect in the glTF route (`mesh_importer.cpp:734-739`, `mesh_io.cpp:152,171-186`). The external UzEngine consumer fixture (`07-preview-and-render-parity.md` §1) runs in UzEngine's own executable; its mesh route avoids that defect or is qualified first — a condition on the consumer test, not a UzPainter dependency.

```
TexturingMesh { objects[] {name, transform, triangles[] {corner ids}},
                corners[] {position id, normal, uv0, tangent xyz + sign (computed), material id},
                positions[], materials[] {name, index}, units {source, scale_to_internal},
                hashes {positions, uvs, corner_normals, triangulation, materials}, certificate }
```

## 2. Formats and parsers

| Format | Parser | Rules |
|---|---|---|
| OBJ | Own parser | `usemtl` → material/texture set; `o`/`g` → object names for geometry masks; negative indices, missing normals/UVs (flagged), multiple UV sets (first used, others recorded) |
| FBX | ufbx (vendored from upstream under its own licence, `docs/licensing-and-clean-room.md` §3) | All meshes, instances and transforms; source units via ufbx; V flip recorded; corner normals preserved (no recomputation) |
| glTF / GLB | fastgltf (vendored from upstream) | All meshes/primitives; `TEXCOORD_0`; stored `TANGENT` recorded but tangents are regenerated for consistency; `GltfSettings.invert_normal_maps` honoured for imported material textures (Painter behaviour) |
| High-poly | same parsers, streamed | Positions, indices, optional normals, vertex colours and material ids as side streams straight into Embree geometry, or into acceleration structures UzPainter builds with explicit vertex strides for the optional GPU baker (`06-baking.md` §1); never through the texturing mesh path or a fixed-stride path such as UzEngine's `BLASManager` (48-byte stride, opaque) |

Painter also accepts `dae`, `ply`, `usd`; they are release gaps in the capability manifest.

## 3. Contracts

- **Triangulation.** Already-triangulated input is kept exactly (`PRJ-01`); polygonal faces are triangulated by a documented fan rule from the first corner and flagged in the certificate; the rule is a Tier 0 item compared with Painter's result on the same quad mesh.
- **Units.** Painter's unit is centimetres; `mesh_unit_scale` 0/None means "use the file unit", otherwise the given scale (`project.Settings.mesh_unit_scale` in the public API documentation; `docs/analysis/substance-parity/05-project-and-spp.md` §1.1 is historical context). UzPainter stores `units {source, scale_to_internal}` and applies them to cage/ray distances, physical-size projections and the camera; the effective scale is in every receipt (PRJ-07).
- **Identity.** Material identity (name + index) and object identity are separate; duplicate material names are an import error unless `allow_duplicate_material_names` merges them explicitly; texture sets are created one per material in file order (PRJ-02).
- **Tangents.** MikkTSpace (Mikkelsen's reference `mikktspace.c`, vendored from upstream under its own licence) per corner; `TangentSpace.PerVertex` interpolates the bitangent, `PerFragment` rebuilds it per texel from interpolated N and T with the stored sign (default `PerFragment`, as the pipeline). Whether this equals Painter's frame is settled by the Phase 0 fixture: bake a known hemisphere normal in Painter and UzPainter, compare in tangent space, and shade the same map in UzEngine's own executable (external consumer fixture) to fix its green-channel convention (unconfirmed in the engine — `10-review-response.md` §4.5).
- **Orientation.** Image rows are stored top-down; the pipeline's mask tools write rows flipped relative to their raster arrays (`A3D\Docs\Pipeline\Pintura\regularize_garment_trim.py`); the import of `M_*.png`/`T_*.png` follows PNG order and a directional fixture confirms it (INT-12).

## 4. Certificate (PRJ-09, PRJ-10)

Computed at import and stored with the mesh hash; never auto-repairs:

```json
{"corners": {"non_finite_normals": n, "zero_normals": n, "zero_tangents": n, "zero_bitangents": n, "degenerate_tbn": n, "flipped_handedness": n},
 "faces": {"coincident_opposite": n, "zero_area_uv": n, "flipped_uv": n, "ngons_triangulated": n},
 "uv": {"outside_0_1": n, "per_set": {"<set>": {"overlap_px": n, "islands": n, "density_px_per_cm": {"min":…, "p50":…, "max":…}, "anisotropy_max":…, "gap_px":…, "border_px":…}}},
 "mesh": {"objects": n, "triangles": n, "materials": [...], "units": {...}}, "hashes": {...}, "status": "pass|warn|fail"}
```

Diagnostic imports proceed with `warn`; the Assets3D production adapter (a pipeline-side script) refuses a paint round unless the manifest gates passed and the certificate has no `fail` (QG-02). UzPainter never repacks UVs.

## 5. UV-space rasterisation

A UzPainter compute/graphics pass renders the texturing mesh in UV space per set and tile into position, normal, tangent frame, island id and material id buffers (RGBA32F/R32Uint) with texel-centre coverage and a conservative coverage mask (supersampled); these feed projections, generators and bakers. Conservative rasterisation is not available in the vendored RHI (`uzengine-renderer/03-rhi-capabilities-for-texturing.md` §3), so coverage is computed by supersampling; island-edge behaviour is a Tier 0 item against Painter.

## 6. UV tiles

`ProjectWorkflow.Default` only in v1; UVs outside 0–1 fail import with the tile list, pointing to the release gap. The `TexturingMesh` and raster buffers are tile-indexed so `UVTile`/`TextureSetPerUVTile` can be added without changing the data model (Phase 4).

## 7. Reload (PRJ-08)

`project.reload_mesh(path, settings, cb)`: parse and certify the new mesh; match texture sets by material identity (ambiguity — renamed, split or merged materials — is an explicit error with the mapping proposal, never a silent attach); keep stacks and resources; re-rasterise; compare corner hashes per set and classify texels unchanged / moved / new / replaced; mark mesh maps, geometry masks, procedural caches and downstream receipts `invalid`; report `{sets: added, removed, renamed}` and the per-set region classes. One transaction; failure leaves the old mesh.

## 8. Auto-unwrap

`AutoUnwrapSettings` is accepted, recorded and rejected with `NotYetSupported` at import (xatlas exists in UzEngine but is not Painter's unwrapper; equivalence is unproven). Release gap.

## 9. Settling evidence (Phase 1, node P1-MESH)

Fixtures: mirrored UVs, hard edges, negative OBJ indices, n-gons, duplicate material names, instances/transforms, units, multi-set body, coincident opposite faces (the hat lesson `A3D\Docs\Pipeline\Licoes\bake-normais-tbn-por-canto.md`); reload/rename/split fixtures that preserve or deliberately reject bindings; the normal-convention fixture across Painter, UzPainter and UzEngine.
