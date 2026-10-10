# 13. D11 Mesh import: UzPainter raw loader with corner preservation, MikkTSpace frames and certification

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

UzEngine's cook path selects the first mesh, runs LOD/SDF work, recomputes FBX normals by default and has a confirmed 32/48-byte glTF stride defect (05-resolution.md D11).

## Decision

OBJ (own parser), FBX (ufbx) and glTF (fastgltf) imported raw into a corner-preserving TexturingMesh; explicit unit rule (Painter centimetres; mesh_unit_scale 0/None = file unit); documented triangulation rule for polygons; separate material and object identity; MikkTSpace per-vertex/per-fragment frames proven by a Phase 0 fixture; per-set UV/TBN certificate without auto-repair; auto-unwrap and UV tiles are release gaps; transactional reload by stable identity; high-poly streamed straight to Embree. See docs/architecture/12-mesh-import.md.

## Alternatives Considered

- Reuse UzEngine cook importers (.uzmesh) - rejected: defects and transformations
- New parsers for every format - rejected: vendored parsers suffice

## Consequences

Any cooked route used later for preset validation must be repaired or qualified first.
