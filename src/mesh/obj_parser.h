#pragma once

// UzPainter's own Wavefront OBJ parser (`docs/architecture/12-mesh-import.md` §2).
//
// - `v`, `vt`, `vn` are kept in file order (`positions[]`; extra `v` components such as vertex
//   colours and the `vt` w component are ignored). `vt` with only u has v = 0.
// - `f` references are `v`, `v/vt`, `v//vn` or `v/vt/vn`, 1-based; a negative index counts back
//   from the last element defined above the face (-1 is the latest). Each reference is one corner.
//   A corner without `vt` or `vn` gets (0, 0) or (0, 0, 0) and is counted in the flags.
// - `o` and `g` name objects (for geometry masks): each such line whose name differs from the
//   current object's starts a new object. Faces before any of them belong to the object
//   `default`.
// - `usemtl` selects the material by name; materials are ordered by their first `usemtl`, and
//   faces before any `usemtl` use the material `default`. `mtllib` names are recorded; material
//   libraries are not read (texture sets need only the names).
// - OBJ has one UV set and no unit: units are "unspecified" and the file unit is taken as
//   Painter's centimetre unless `mesh_unit_scale` says otherwise (`ImportMesh`).
// - `l` and `p` elements have no surface and are counted as skipped; `s`, `vp`, free-form
//   geometry statements and unknown keywords are ignored.

#include <string_view>

#include "mesh/texturing_mesh.h"

namespace uzp::mesh {

/// Parses `text` into `mesh` (empty on entry). Throws `ImportError` (`parse_error`) naming the
/// line for a malformed statement or an index out of range.
void ParseObj(std::string_view text, TexturingMesh& mesh);

}  // namespace uzp::mesh
