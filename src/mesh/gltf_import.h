#pragma once

// glTF 2.0 / GLB import over fastgltf (`thirdparty/fastgltf/`, `docs/architecture/12-mesh-import.md`
// §2).
//
// - The default scene's node tree (scene 0 when none is the default; every root node when the
//   file has no scene) is walked depth first in order; each node with a mesh is one object, named
//   by the node (else its mesh, else `node<index>`), with its world transform. An instanced mesh
//   gives one object per node; its positions are added once.
// - Corners are the primitives' indices in order (non-indexed primitives: their vertices in
//   order); `positions[]` holds every primitive's `POSITION` values.
// - `NORMAL` is kept as stored; `TEXCOORD_0` is used with v flipped (glTF's v grows downwards:
//   v = 1 - v_gltf, recorded as `v_flip`); later `TEXCOORD_n` are recorded; stored `TANGENT`s are
//   counted but not used (tangents are regenerated, 12 §2).
// - Materials are ordered as the file lists them, named by their name or `material<index>`;
//   primitives without a material use the material `default`, ordered after the file's.
// - `TRIANGLES` primitives are imported; `POINTS` and `LINES*` are skipped and counted;
//   `TRIANGLE_STRIP` and `TRIANGLE_FAN` are refused (`parse_error`).
// - glTF's unit is the metre.

#include <filesystem>
#include <string_view>

#include "mesh/texturing_mesh.h"

namespace uzp::mesh {

/// Parses glTF JSON or GLB `bytes` into `mesh` (empty on entry); external buffers are read
/// relative to `directory`. Throws `ImportError` (`parse_error`) with fastgltf's description.
void ImportGltf(std::string_view bytes, const std::filesystem::path& directory, TexturingMesh& mesh);

}  // namespace uzp::mesh
