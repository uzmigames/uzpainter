#pragma once

// FBX import over ufbx (`thirdparty/ufbx/`, `docs/architecture/12-mesh-import.md` §2).
//
// - Every node with a mesh is one object (an instanced mesh gives one object per node), with the
//   node's geometry-to-world transform (its geometric transform included) in file units; ufbx
//   is asked for no unit, axis or handedness conversion, so positions stay as authored.
// - Corners are the mesh's polygon vertices in file order; a mesh's control points are added to
//   `positions[]` once, however many nodes instance it.
// - Corner normals are the file's (`LayerElementNormal`), never recomputed (ufbx generates none);
//   UVs are the first UV set, as stored (FBX's v grows upwards: no flip); later sets are
//   recorded by name.
// - A face's material is the node's material for the face's slot (per-instance materials), else
//   the mesh's; materials are ordered as the file lists them, unnamed ones named
//   `material<index>`. Faces without a material use the material `default`, ordered after the
//   file's.
// - Faces of fewer than three corners (points, lines) are skipped and counted.
// - Units: the scene's `UnitScaleFactor` (metres per unit through ufbx); the axes are recorded.

#include <string_view>

#include "mesh/texturing_mesh.h"

namespace uzp::mesh {

/// Parses FBX `bytes` (binary or ASCII) into `mesh` (empty on entry). Throws `ImportError`
/// (`parse_error`) with ufbx's description when the file cannot be read.
void ImportFbx(std::string_view bytes, TexturingMesh& mesh);

}  // namespace uzp::mesh
